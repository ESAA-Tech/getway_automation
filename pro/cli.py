#!/usr/bin/env python3
"""
City-Wide Edge Gateway Orchestration & Automated Data Acquisition Platform CLI.
Target: Four-Faith Industrial Smart Gateways (JSON-RPC 2.0 API & Dropbear SSH).

Modes:
  inspect   : Deep read-only audit of devices, datanodes, uplinks, and live telemetry.
  backup    : Pull and catalog full JSON configuration snapshots.
  diff      : Calculate state drift between inventory and actual gateway NVRAM.
  sync      : Declarative synchronization with canary gating, batching, and auto-rollback.
  rollback  : Atomic restore of gateway NVRAM from prior snapshot.
  messaging : Deploy de-duplicated JavaScript telemetry formatters and control topics.
"""

import os
import sys
import json
import logging
import argparse
from typing import List, Dict, Any, Optional

from pro.core.client import GatewayClient
from pro.core.diff_engine import DiffEngine, DiffResult
from pro.core.validator import GatewayValidator
from pro.storage.backup_catalog import BackupCatalog
from pro.storage.inventory_repo import InventoryRepository
from pro.engine.worker_pool import WorkerPool
from pro.engine.rollout import RolloutEngine
from pro.messaging.script_builder import ScriptBuilder

# Setup root logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("pro.cli")


def cmd_inspect(gateways: List[Dict[str, Any]], catalog: BackupCatalog):
    """Deep read-only inspection of target gateways."""
    for gw in gateways:
        ip = gw.get("ip_address")
        gw_id = gw.get("gateway_id", "GW")
        port = gw.get("port", 80)
        user = gw.get("username", "Teamtech12!")
        pwd = gw.get("password", "teamtech")

        print("\n" + "=" * 78)
        print(f" GATEWAY INSPECTION AUDIT: {gw_id} ({ip}:{port}) - [READ-ONLY]")
        print("=" * 78)

        client = GatewayClient(host=ip, port=port, username=user, password=pwd, read_only=True)
        try:
            client.login()
        except Exception as e:
            print(f"[-] ERROR: Could not connect to gateway {ip}: {e}")
            continue

        # 1. Automatic Snapshot
        snap_path = catalog.create_snapshot(client, gateway_id=gw_id, tag="AUDIT_SNAPSHOT")
        print(f"[+] Snapshot persisted: {snap_path}")

        # 2. Downstream Devices
        devices = client.get_device_list()
        print(f"\n[+] Configured Downstream Devices ({len(devices)} total):")
        for d in devices:
            plc_id = d.get("plc_id", "N/A")
            devtyp = d.get("devtyp", "")
            chn = d.get("channel", "")
            ip_addr = d.get("ipaddr", "") or "N/A"
            port_num = d.get("port", 0)
            slave_id = d.get("devaddr_str", "")
            interval = d.get("acq_intv", 500)
            enabled = "Enabled" if d.get("chn_en") else "Disabled"
            print(f"    - [{enabled}] {plc_id:<16} | {devtyp:<12} | Chn: {chn:<8} | IP: {ip_addr}:{port_num:<5} | Slave ID: {slave_id:<3} | Poll: {interval}ms")

        # 3. Datanodes / Register Points
        datanodes = client.get_all_datanodes()
        print(f"\n[+] Data Acquisition Registers ({sum(len(v) for v in datanodes.values())} total points):")
        for plc_id, tags in datanodes.items():
            print(f"    Device '{plc_id}' ({len(tags)} registers):")
            for t in tags[:6]:
                p_name = t.get("portid", "")
                addr = t.get("startaddr", "")
                atype = t.get("addrtype", "")
                dtype = t.get("datatype", "")
                formula = t.get("formula", "") or "raw"
                print(f"        * {p_name:<16} | Reg: {addr:<5} ({atype}) | Type: {dtype:<6} | Scale: {formula}")
            if len(tags) > 6:
                print(f"        ... and {len(tags) - 6} more points")

        # 4. Cloud Uplinks & Scripts
        uplinks = client.get_uplink_list()
        print(f"\n[+] Cloud Transmission Uplinks ({len(uplinks)} servers):")
        for up in uplinks:
            ct_id = up.get("ct_id", "")
            broker = f"{up.get('url', '')}:{up.get('srvport', '')}"
            cid = up.get("mqtt_clientid", "")
            print(f"    - CT '{ct_id}': Broker {broker} | Client ID: {cid}")
            scripts = client.get_scripts(ct_id)
            up_scripts = scripts.get("script_up", [])
            down_scripts = scripts.get("script_down", [])
            print(f"      Scripts: {len(up_scripts)} upstream (telemetry), {len(down_scripts)} downstream (commands)")

        # 5. Live Telemetry Readings
        telemetry = client.get_live_telemetry()
        print(f"\n[+] Live Telemetry Sample Readings:")
        if telemetry:
            for dev_name, points in telemetry.items():
                print(f"    Device '{dev_name}':")
                cnt = 0
                for pt_name, pt_val in points.items():
                    if cnt < 5:
                        val = pt_val.get("value", "")
                        ts = pt_val.get("ctime", "")
                        print(f"        * {pt_name:<16} = {val:<8} (Timestamp: {ts})")
                        cnt += 1
                if len(points) > 5:
                    print(f"        ... and {len(points) - 5} more metrics")
        else:
            print("    (No live telemetry active)")

        print("=" * 78 + "\n")


def cmd_backup(gateways: List[Dict[str, Any]], catalog: BackupCatalog):
    """Pulls full snapshots for all target gateways."""
    for gw in gateways:
        ip = gw.get("ip_address")
        gw_id = gw.get("gateway_id", "GW")
        client = GatewayClient(host=ip, port=gw.get("port", 80), username=gw.get("username", "Teamtech12!"), password=gw.get("password", "teamtech"), read_only=True)
        try:
            client.login()
            path = catalog.create_snapshot(client, gateway_id=gw_id, tag="MANUAL_BACKUP")
            print(f"[+] [{gw_id}] Backup saved: {path}")
        except Exception as e:
            print(f"[-] [{gw_id}] Backup failed: {e}")


def cmd_diff(
    gateways: List[Dict[str, Any]],
    repo: InventoryRepository,
    devices_csv: str = "inventory/devices.csv",
    allow_prune: bool = False
):
    """Calculates state drift between inventory declarations and live gateway NVRAM."""
    devices_by_gw = repo.load_devices(devices_csv)
    profiles = repo.load_all_profiles()

    for gw in gateways:
        ip = gw.get("ip_address")
        gw_id = gw.get("gateway_id", "GW")
        client = GatewayClient(host=ip, port=gw.get("port", 80), username=gw.get("username", "Teamtech12!"), password=gw.get("password", "teamtech"), read_only=True)
        try:
            client.login()
            actual_state = client.get_full_state()
            desired_devices = devices_by_gw.get(gw_id, [])

            # Map desired registers from profiles
            desired_tags_map = {}
            for d in desired_devices:
                # Find profile matching device ID or standard mapping
                prof = profiles.get(f"{d.plc_id}_v1") or profiles.get(f"{d.plc_id}_controller_v1") or profiles.get(f"{d.plc_id}_sensor_v1")
                if prof:
                    desired_tags_map[d.plc_id] = prof.registers

            diff = DiffEngine.compute_full_diff(
                gateway_id=gw_id,
                gateway_ip=ip,
                desired_devices=desired_devices,
                desired_tags_map=desired_tags_map,
                actual_snapshot=actual_state,
                allow_prune=allow_prune
            )
            print("\n" + diff.summary())

        except Exception as e:
            print(f"[-] [{gw_id}] Diff calculation failed: {e}")


def cmd_sync(
    gateways: List[Dict[str, Any]],
    repo: InventoryRepository,
    catalog: BackupCatalog,
    devices_csv: str = "inventory/devices.csv",
    canary_ip: Optional[str] = None,
    batch_size: int = 20,
    auto_rollback: bool = True,
    dry_run: bool = False,
    allow_prune: bool = False
):
    """Executes declarative synchronization across gateways."""
    devices_by_gw = repo.load_devices(devices_csv)
    profiles = repo.load_all_profiles()

    if dry_run:
        print("\n*** DRY-RUN MODE ACTIVE: Computing diffs without making modifications ***")
        cmd_diff(gateways, repo, devices_csv=devices_csv, allow_prune=allow_prune)
        return

    def deploy_fn(client: GatewayClient, gw_info: Dict[str, Any]) -> bool:
        gw_id = gw_info.get("gateway_id")
        desired_devices = devices_by_gw.get(gw_id, [])
        if not desired_devices:
            logger.info(f"[{client.host}] No devices declared in inventory. Preserving existing.")
            return True

        # Read actual state
        actual_devices = client.get_device_list()
        to_add, to_update, to_remove, unchanged = DiffEngine.compute_device_diff(
            desired_devices, actual_devices, allow_prune=allow_prune
        )

        if to_add or to_update:
            # Combine unchanged + to_update + to_add
            merged = list(unchanged) + list(to_update) + list(to_add)
            client.set_device_list(merged)

        # Deploy tags from profiles
        for dev in desired_devices:
            prof = profiles.get(f"{dev.plc_id}_v1") or profiles.get(f"{dev.plc_id}_controller_v1") or profiles.get(f"{dev.plc_id}_sensor_v1")
            if prof:
                rpc_tags = [t.to_rpc_dict() for t in prof.registers]
                client.set_device_datanodes(dev.plc_id, rpc_tags)

        # Commit and apply
        client.apply_config()
        return True

    engine = RolloutEngine(backup_catalog=catalog, batch_size=batch_size)
    report = engine.execute_staged_rollout(
        gateways=gateways,
        devices_by_gw=devices_by_gw,
        deploy_fn=deploy_fn,
        canary_ip=canary_ip,
        auto_rollback=auto_rollback
    )

    print("\n" + "=" * 78)
    print(report.to_markdown())
    print("=" * 78 + "\n")


def cmd_rollback(gateway_ip: str, backup_file: str, catalog: BackupCatalog, user: str, pwd: str, port: int = 80):
    """Restores gateway NVRAM to an exact prior snapshot."""
    print(f"\n[!] INITIATING ATOMIC ROLLBACK for {gateway_ip} using snapshot: {backup_file}")
    client = GatewayClient(host=gateway_ip, port=port, username=user, password=pwd, read_only=False)
    client.login()

    # Pre-rollback snapshot
    pre_rb_snap = catalog.create_snapshot(client, gateway_id="PRE_ROLLBACK", tag="PRE_ROLLBACK_SAFEGUARD")
    print(f"[+] Safety snapshot recorded: {pre_rb_snap}")

    snapshot_data = catalog.load_snapshot(backup_file)
    success = client.restore_full_state(snapshot_data)
    if success:
        print(f"[+] ROLLBACK COMPLETED SUCCESSFULLY for {gateway_ip}")
    else:
        print(f"[-] ROLLBACK FAILED for {gateway_ip}")


def cmd_messaging(
    gateways: List[Dict[str, Any]],
    catalog: BackupCatalog,
    source: str = "testserver",
    pole_id: str = "P001",
    site_id: str = "default-site",
    apply_changes: bool = False
):
    """Deploys scripts from exact testserver/test templates or consolidated SCMP format."""
    if source in ["testserver", "test"]:
        script_up, script_down = ScriptBuilder.load_exact_scripts(source=source, pole_id=pole_id)
    else:
        script_up, script_down = ScriptBuilder.build_standard_scripts(pole_id=pole_id, site_id=site_id)

    for gw in gateways:
        ip = gw.get("ip_address")
        gw_id = gw.get("gateway_id", "GW")
        client = GatewayClient(
            host=ip,
            port=gw.get("port", 80),
            username=gw.get("username", "Teamtech12!"),
            password=gw.get("password", "teamtech"),
            read_only=not apply_changes
        )
        try:
            client.login()
            uplinks = client.get_uplink_list()
            target_ct = "testserver" if any(u.get("ct_id") == "testserver" for u in uplinks) else (uplinks[0].get("ct_id") if uplinks else "testserver")

            current_scripts = client.get_scripts(target_ct)
            curr_up = current_scripts.get("script_up", [])
            print(f"\n[+] Gateway {gw_id} ({ip}) CT '{target_ct}': currently has {len(curr_up)} upstream scripts.")

            if not apply_changes:
                print(f"    Target script source: '{source}' ({len(script_up)} upstream, {len(script_down)} downstream):")
                for s in script_up:
                    print(f"      - Upstream: {s['script_id']:<20} -> Topic: {s['event']}")
                for s in script_down:
                    print(f"      - Downstream: {s['script_id']:<20} -> Topic: {s['event']}")
                print("    (Run with --apply to commit to NVRAM)")
            else:
                snap = catalog.create_snapshot(client, gateway_id=gw_id, tag="PRE_MESSAGING_RECON")
                print(f"[+] Pre-flight snapshot saved: {snap}")
                client.set_scripts(target_ct, script_up=script_up, script_down=script_down)
                client.apply_config()
                print(f"[+] Exact messaging scripts from '{source}' deployed and applied to {gw_id} ({ip}).")

        except Exception as e:
            print(f"[-] [{gw_id}] Messaging management error: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="City-Wide Edge Gateway Orchestration Platform (Production CLI)"
    )
    parser.add_argument(
        "--mode",
        choices=["inspect", "backup", "diff", "sync", "rollback", "messaging", "web"],
        default="inspect",
        help="Command execution mode (default: inspect)"
    )
    parser.add_argument("--port", type=int, default=8085, help="HTTP port for web command center (default: 8085)")
    parser.add_argument("--gateway", type=str, default="", help="Target a specific gateway IP")
    parser.add_argument("--inventory", type=str, default="inventory/gateways.csv", help="Path to gateways CSV")
    parser.add_argument("--devices", type=str, default="inventory/devices.csv", help="Path to devices CSV")
    parser.add_argument("--canary", type=str, default="", help="Canary gateway IP for staged rollout")
    parser.add_argument("--batch-size", type=int, default=20, help="Batch size for concurrent rollout")
    parser.add_argument("--backup-file", type=str, default="", help="Snapshot path for rollback mode")
    parser.add_argument("--pole-id", type=str, default="P001", help="Pole ID for MQTT topic hierarchy")
    parser.add_argument("--site-id", type=str, default="default-site", help="Site ID for SCMP MQTT topic hierarchy (default: default-site)")
    parser.add_argument("--source", type=str, default="testserver", choices=["testserver", "test", "consolidated"], help="Script template source (default: testserver)")
    parser.add_argument("--apply", action="store_true", help="Apply changes in messaging mode")
    parser.add_argument("--dry-run", action="store_true", help="Simulate changes without modifying gateway NVRAM")
    parser.add_argument("--no-auto-rollback", action="store_true", help="Disable automated rollback on failure")
    parser.add_argument("--prune", action="store_true", help="Allow removal of unmanaged devices from gateway")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose debug logging")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Fast track for web mode
    if args.mode == "web":
        from web.server import app
        print(f"\n[+] Launching Edge Gateway Web Command Center on http://127.0.0.1:{args.port}\n")
        app.run(host="0.0.0.0", port=args.port, debug=False)
        return

    catalog = BackupCatalog(backup_dir="backups")
    repo = InventoryRepository()

    # Resolve target gateways
    if args.gateway:
        gateways = [{
            "gateway_id": "GW-TARGET",
            "ip_address": args.gateway,
            "port": 80,
            "username": "Teamtech12!",
            "password": "teamtech"
        }]
    else:
        try:
            gateways_entities = repo.load_gateways(args.inventory)
            gateways = [{
                "gateway_id": g.gateway_id,
                "ip_address": g.network.management_ip,
                "port": g.network.management_port,
                "username": g.auth.username,
                "password": g.auth.get_effective_password(g.gateway_id)
            } for g in gateways_entities]
        except Exception as e:
            logger.error(f"Failed to load gateways inventory: {e}")
            sys.exit(1)

    # Route mode
    if args.mode == "inspect":
        cmd_inspect(gateways, catalog)
    elif args.mode == "backup":
        cmd_backup(gateways, catalog)
    elif args.mode == "diff":
        cmd_diff(gateways, repo, devices_csv=args.devices, allow_prune=args.prune)
    elif args.mode == "sync":
        cmd_sync(
            gateways=gateways,
            repo=repo,
            catalog=catalog,
            devices_csv=args.devices,
            canary_ip=args.canary,
            batch_size=args.batch_size,
            auto_rollback=not args.no_auto_rollback,
            dry_run=args.dry_run,
            allow_prune=args.prune
        )
    elif args.mode == "rollback":
        if not args.gateway or not args.backup_file:
            print("Error: --mode rollback requires both --gateway <ip> and --backup-file <path>")
            sys.exit(1)
        cmd_rollback(
            gateway_ip=args.gateway,
            backup_file=args.backup_file,
            catalog=catalog,
            user="Teamtech12!",
            pwd="teamtech"
        )
    elif args.mode == "messaging":
        cmd_messaging(
            gateways=gateways,
            catalog=catalog,
            source=args.source,
            pole_id=args.pole_id,
            site_id=args.site_id,
            apply_changes=args.apply
        )


if __name__ == "__main__":
    main()
