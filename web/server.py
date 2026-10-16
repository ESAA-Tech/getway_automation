"""
Production Web Gateway Provisioning Station Server.
Exposes clean, dedicated REST endpoints for single-press gateway provisioning.
"""

import os
import sys
import json
import logging
from typing import Dict, Any, List
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from pro.core.client import GatewayClient
from pro.storage.backup_catalog import BackupCatalog
from pro.storage.inventory_repo import InventoryRepository
from pro.messaging.script_builder import ScriptBuilder

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s]: %(message)s")
logger = logging.getLogger("web.server")

app = Flask(__name__, static_folder=os.path.join(os.path.dirname(__file__), "static"))
CORS(app)

catalog = BackupCatalog(backup_dir=os.path.join(BASE_DIR, "backups"))
repo = InventoryRepository(profiles_dir=os.path.join(BASE_DIR, "pro", "templates", "profiles"))

client_cache: Dict[str, GatewayClient] = {}

def get_client(ip: str, user: str = "Teamtech12!", pwd: str = "teamtech", read_only: bool = False) -> GatewayClient:
    key = f"{ip}_{read_only}"
    if key not in client_cache or not client_cache[key].is_alive():
        client = GatewayClient(host=ip, username=user, password=pwd, read_only=read_only, timeout=8)
        client.login()
        client_cache[key] = client
    return client_cache[key]


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/api/gateways", methods=["GET"])
def get_gateways():
    """Returns all declared gateways from inventory."""
    try:
        csv_path = os.path.join(BASE_DIR, "inventory", "gateways.csv")
        gateways = repo.load_gateways(csv_path)
        data = [{
            "gateway_id": g.gateway_id,
            "ip_address": g.network.management_ip,
            "port": g.network.management_port,
            "location": g.location.sector,
            "description": g.location.description
        } for g in gateways]
        return jsonify({"success": True, "gateways": data})
    except Exception as e:
        logger.error(f"Failed to load gateways: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/status", methods=["GET"])
def get_status():
    """Inspects gateway connectivity and returns current configuration summary."""
    ip = request.args.get("ip", "192.168.4.1")
    try:
        client = get_client(ip, read_only=True)
        devices = client.get_device_list()
        uplinks = client.get_uplink_list()
        target_ct = uplinks[0].get("ct_id") if uplinks else "testserver"
        scripts = client.get_scripts(target_ct) if target_ct else {"script_up": [], "script_down": []}

        return jsonify({
            "success": True,
            "online": True,
            "ip": ip,
            "devices_count": len(devices),
            "devices": [d.get("plc_id") for d in devices],
            "uplinks": [u.get("ct_id") for u in uplinks],
            "scripts_count": {
                "upstream": len(scripts.get("script_up", [])),
                "downstream": len(scripts.get("script_down", []))
            }
        })
    except Exception as e:
        logger.warning(f"Gateway {ip} check error: {e}")
        return jsonify({"success": False, "online": False, "ip": ip, "error": str(e)})


def execute_single_gateway_provision(
    target_ip: str,
    screen_ip: str,
    pole_id: str,
    cloud_config: Dict[str, Any],
    site_id: str = "default-site",
    script_source: str = "testserver",
    user: str = "Teamtech12!",
    pwd: str = "teamtech"
) -> Dict[str, Any]:
    """
    Executes the exact end-to-end provisioning sequence for a single gateway:
    1. Pre-flight backup snapshot
    2. Writes the 4 Child Devices (Screen, enviromental, IO, rgb_controller)
    3. Injects all Datanode Variables for each child device
    4. Registers Cloud Service in Cloud List
    5. Imports all Child Device variables into Cloud
    6. Copies Message Management Scripts with exact naming & structure from testserver or test
    7. Commits to NVRAM (sys_apply)
    """
    logs = []
    def log_step(msg: str):
        logger.info(f"[{target_ip}] {msg}")
        logs.append(msg)

    log_step(f"Connecting to Gateway {target_ip}...")
    client = GatewayClient(host=target_ip, username=user, password=pwd, read_only=False, timeout=10)
    client.login()

    # 1. Pre-Flight Safety Snapshot
    log_step("1. Capturing pre-flight NVRAM snapshot...")
    snap = catalog.create_snapshot(client, gateway_id=f"GW_{pole_id}", tag="PRE_PROVISION")
    log_step(f"   Saved backup: {os.path.basename(snap)}")

    # 2. Define the 4 Child Devices
    log_step(f"2. Writing Child Devices (Screen @ {screen_ip}, enviromental, IO, rgb_controller)...")
    child_devices = [
        {
            "plc_id": "Screen",
            "chn_en": True,
            "channel": "ethernet",
            "devtyp": "PLC_FF_BOX",
            "manufacturer": "MFR_LOCAL",
            "ipaddr": screen_ip,
            "port": 0,
            "devaddr_str": "0",
            "acq_intv": 500,
            "acqtimeout": 500,
            "optimization": True,
            "bit16_order": "ab",
            "bit32_order": "abcd",
            "flt32_order": "abcd",
            "bit16_order_d": "ab",
            "bit32_order_d": "abcd",
            "flt32_order_d": "abcd"
        },
        {
            "plc_id": "enviromental",
            "chn_en": True,
            "channel": "RS485-1",
            "devtyp": "PLC_MDBS_RTU",
            "manufacturer": "MFR_MODBUS",
            "ipaddr": "",
            "port": 0,
            "devaddr_str": "255",
            "acq_intv": 500,
            "acqtimeout": 1000,
            "optimization": True,
            "bit16_order": "ab",
            "bit32_order": "abcd",
            "flt32_order": "abcd",
            "bit16_order_d": "ab",
            "bit32_order_d": "abcd",
            "flt32_order_d": "abcd"
        },
        {
            "plc_id": "IO",
            "chn_en": True,
            "channel": "ethernet",
            "devtyp": "PLC_FF_BOX",
            "manufacturer": "MFR_LOCAL",
            "ipaddr": "",
            "port": 0,
            "devaddr_str": "0",
            "acq_intv": 500,
            "acqtimeout": 500,
            "optimization": True,
            "bit16_order": "ab",
            "bit32_order": "abcd",
            "flt32_order": "abcd",
            "bit16_order_d": "ab",
            "bit32_order_d": "abcd",
            "flt32_order_d": "abcd"
        },
        {
            "plc_id": "rgb_controller",
            "chn_en": True,
            "channel": "RS485-2",
            "devtyp": "PLC_MDBS_RTU",
            "manufacturer": "MFR_MODBUS",
            "ipaddr": "",
            "port": 0,
            "devaddr_str": "1",
            "acq_intv": 500,
            "acqtimeout": 1000,
            "optimization": True,
            "bit16_order": "ab",
            "bit32_order": "abcd",
            "flt32_order": "abcd",
            "bit16_order_d": "ab",
            "bit32_order_d": "abcd",
            "flt32_order_d": "abcd"
        }
    ]

    # Preserve and merge with any existing child devices already configured on the gateway
    existing_devices = client.get_device_list()
    merged_devices_dict = {d.get("plc_id"): d for d in existing_devices if d.get("plc_id")}
    for cd in child_devices:
        merged_devices_dict[cd["plc_id"]] = cd
    merged_devices = list(merged_devices_dict.values())

    client.set_device_list(merged_devices)
    log_step(f"   Child devices updated: {len(merged_devices)} total devices active (all pre-existing devices preserved).")

    # 3. Inject Datanode Variables for each device
    log_step("3. Injecting Datanode Variables for all devices...")
    # Screen is an Ethernet LED device, so register polling tags are not required.

    # IO variables (5 NVRAM tags)
    io_tags = [
        {"portid": "AC-OUT3", "rdwr": "rw", "datanum": 64, "datatype": "s", "cal_type": "disabled", "map_up_o": "", "map_down_o": "", "map_up_t": "", "map_down_t": "", "formula": "", "startaddr": "ac_enabled3", "addrtype": "nvram", "int_bit": "", "decimal_bit": ""},
        {"portid": "AC-OUT2", "rdwr": "rw", "datanum": 64, "datatype": "s", "cal_type": "disabled", "map_up_o": "", "map_down_o": "", "map_up_t": "", "map_down_t": "", "formula": "", "startaddr": "ac_enabled2", "addrtype": "nvram", "int_bit": "", "decimal_bit": ""},
        {"portid": "AC-OUT1", "rdwr": "rw", "datanum": 64, "datatype": "s", "cal_type": "disabled", "map_up_o": "", "map_down_o": "", "map_up_t": "", "map_down_t": "", "formula": "", "startaddr": "ac_enabled1", "addrtype": "nvram", "int_bit": "", "decimal_bit": ""},
        {"portid": "ac_dc_switch", "rdwr": "rw", "datanum": 64, "datatype": "s", "cal_type": "disabled", "map_up_o": "", "map_down_o": "", "map_up_t": "", "map_down_t": "", "formula": "", "startaddr": "ac_dc_switch", "addrtype": "nvram", "int_bit": "", "decimal_bit": ""},
        {"portid": "smart_lightpole_en", "rdwr": "rw", "datanum": 64, "datatype": "s", "cal_type": "disabled", "map_up_o": "", "map_down_o": "", "map_up_t": "", "map_down_t": "", "formula": "", "startaddr": "smart_lightpole_en", "addrtype": "nvram", "int_bit": "", "decimal_bit": ""}
    ]
    client.set_device_datanodes("IO", io_tags)

    # RGB Controller variables (6 Holding Registers)
    rgb_profile = repo.load_profile("rgb_controller_v1.json")
    client.set_device_datanodes("rgb_controller", [t.to_rpc_dict() for t in rgb_profile.registers])

    # Environmental Sensor variables (21 Weather Registers)
    env_profile = repo.load_profile("enviromental_sensor_v1.json")
    client.set_device_datanodes("enviromental", [t.to_rpc_dict() for t in env_profile.registers])
    log_step("   Datanode registers injected: 21 Weather, 5 IO, 6 RGB.")

    # 4. Cloud List Configuration
    ct_id = cloud_config.get("ct_id", "testserver").strip() or "testserver"
    broker_url = cloud_config.get("url", "192.168.4.124").strip()
    broker_port = int(cloud_config.get("port", 1883))
    mqtt_user = cloud_config.get("username", "gw-pole-test").strip()
    mqtt_pwd = cloud_config.get("password", "gateway_secret").strip()
    client_id_prefix = cloud_config.get("client_id_prefix", "scmp-pole").strip()
    full_client_id = f"{client_id_prefix}-{pole_id}"

    log_step(f"4. Configuring Cloud Uplink '{ct_id}' -> Broker {broker_url}:{broker_port} (Client ID: {full_client_id})...")
    uplink_obj = {
        "ct_id": ct_id,
        "proto": "TRNS_PROTO_CUSTOM_MQTT",
        "svr_en": True,
        "url": broker_url,
        "srvport": broker_port,
        "mqtt_clientid": full_client_id,
        "mqtt_username": mqtt_user,
        "mqtt_pswd": mqtt_pwd,
        "mqtt_keepalive": 60,
        "mqtt_timeout": 10,
        "periodic_time": 10,
        "clear_data": True,
        "store_mode": "memory",
    }
    
    # Preserve all existing cloud services, only updating or appending the target service
    existing_uplinks = client.get_uplink_list()
    merged_uplinks = []
    matched = False
    for u in existing_uplinks:
        if u.get("ct_id") == ct_id:
            merged_uplinks.append(uplink_obj)
            matched = True
        else:
            merged_uplinks.append(u)
    if not matched:
        merged_uplinks.append(uplink_obj)

    client.set_uplink_list(merged_uplinks)
    log_step(f"   Uplink '{ct_id}' configured. Preserved all {len(merged_uplinks)} cloud services.")

    # 5. Import variables from child devices to cloud while preserving existing variables
    log_step("5. Importing child device variables into cloud uplink...")
    bound_datanodes = []
    for t in env_profile.registers:
        bound_datanodes.append({"plc_id": "enviromental", "portid": t.portid, "change_report": False})
    for t in io_tags:
        bound_datanodes.append({"plc_id": "IO", "portid": t["portid"], "change_report": False})
    for t in rgb_profile.registers:
        bound_datanodes.append({"plc_id": "rgb_controller", "portid": t.portid, "change_report": False})
    
    # Merge with any existing variables the user had bound to this cloud uplink
    existing_bound = client.get_ct_datanodes(ct_id)
    existing_keys = {(b.get("plc_id"), b.get("portid")) for b in existing_bound if isinstance(b, dict)}
    for b in bound_datanodes:
        key = (b.get("plc_id"), b.get("portid"))
        if key not in existing_keys:
            existing_bound.append(b)
            existing_keys.add(key)

    client.set_ct_datanodes(ct_id, existing_bound)
    log_step(f"   Imported variables into Cloud '{ct_id}': {len(existing_bound)} total variables bound (all existing preserved).")

    # 6. Copy Message Management scripts from testserver / test without modifying
    if script_source in ["testserver", "test"]:
        log_step(f"6. Injecting exact unmodified scripts from '{script_source}' (exact naming & repetition, SCMP topics)...")
        script_up, script_down = ScriptBuilder.load_exact_scripts(source=script_source, pole_id=pole_id, site_id=site_id)
        client.set_scripts(ct_id, script_up=script_up, script_down=script_down)
        log_step(f"   Injected exact {len(script_up)} upstream and {len(script_down)} downstream scripts from {script_source} with exact naming.")
    else:
        log_step(f"6. Injecting consolidated SCMP scripts with Pole '{pole_id}', Site '{site_id}'...")
        script_up, script_down = ScriptBuilder.build_standard_scripts(pole_id=pole_id, site_id=site_id, screen_ip=screen_ip)
        client.set_scripts(ct_id, script_up=script_up, script_down=script_down)
        log_step(f"   Injected 5 upstream and 2 downstream scripts (topics: scmp/v1/{site_id}/{pole_id}/...).")

    # 7. Commit changes to NVRAM & reload acquisition daemons
    log_step("7. Committing configuration to Flash NVRAM (sys_apply)...")
    client.apply_config(["smtgw3"])
    log_step("   Done! Acquisition and transmission daemons reloaded.")

    return {
        "gateway_ip": target_ip,
        "pole_id": pole_id,
        "site_id": site_id,
        "script_source": script_source,
        "snapshot": snap,
        "variables_count": len(bound_datanodes),
        "scripts_up": len(script_up),
        "scripts_down": len(script_down),
        "logs": logs
    }


@app.route("/api/provision", methods=["POST"])
def provision_gateway():
    """
    Dedicated endpoint to write Child Devices, Datanodes, Cloud List,
    Cloud Datanode Imports, and Scripts with exact naming and repetition.
    """
    data = request.json or {}
    target_ip = data.get("target_ip", "192.168.4.1").strip()
    screen_ip = data.get("screen_ip", "192.168.4.125").strip()
    pole_id = data.get("pole_id", "P001").strip() or "P001"
    site_id = data.get("site_id", "default-site").strip() or "default-site"
    script_source = data.get("script_source", "testserver").strip() or "testserver"
    cloud_config = data.get("cloud_config", {})
    write_all = bool(data.get("write_all_gateways", False))

    if write_all:
        try:
            csv_path = os.path.join(BASE_DIR, "inventory", "gateways.csv")
            gateways = repo.load_gateways(csv_path)
            results = []
            for idx, gw in enumerate(gateways, start=1):
                gw_ip = gw.network.management_ip
                gw_pole = f"P{idx:03d}" if pole_id == "AUTO" else f"{pole_id}-{idx:02d}"
                res = execute_single_gateway_provision(
                    target_ip=gw_ip,
                    screen_ip=screen_ip,
                    pole_id=gw_pole,
                    site_id=site_id,
                    script_source=script_source,
                    cloud_config=cloud_config,
                    user=gw.auth.username,
                    pwd=gw.auth.get_effective_password(gw.gateway_id)
                )
                results.append(res)
            return jsonify({"success": True, "count": len(results), "results": results})
        except Exception as e:
            logger.error(f"Error provisioning all gateways: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
    else:
        try:
            res = execute_single_gateway_provision(
                target_ip=target_ip,
                screen_ip=screen_ip,
                pole_id=pole_id,
                site_id=site_id,
                script_source=script_source,
                cloud_config=cloud_config
            )
            return jsonify({"success": True, "result": res})
        except Exception as e:
            logger.error(f"Error provisioning gateway {target_ip}: {e}")
            return jsonify({"success": False, "error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8085))
    print(f"[*] Starting Gateway Provisioning Station on http://127.0.0.1:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
