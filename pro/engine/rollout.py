"""
Staged Rollout, Canary Pipeline, and Automated Rollback Controller.
Prevents city-wide outages through gated canary verification.
"""

import os
import time
import json
import logging
from enum import Enum
from typing import List, Dict, Any, Optional, Callable, Tuple
from dataclasses import dataclass, field

from pro.core.client import GatewayClient
from pro.core.validator import GatewayValidator, ValidationReport
from pro.storage.backup_catalog import BackupCatalog
from pro.engine.worker_pool import WorkerPool, TaskResult

logger = logging.getLogger("pro.engine.rollout")


class RolloutStage(str, Enum):
    LINT = "Stage 0: Pre-Flight Lint"
    CANARY = "Stage 1: Canary Deploy"
    PILOT = "Stage 2: Pilot Cluster"
    FULL = "Stage 3: Full City Rollout"
    AUDIT = "Stage 4: Post-Deployment Audit"


@dataclass
class RolloutReport:
    """Summary of the complete rollout execution."""
    timestamp: str
    total_gateways: int = 0
    canary_passed: bool = False
    canary_gateway: str = ""
    successful_gateways: List[str] = field(default_factory=list)
    failed_gateways: List[str] = field(default_factory=list)
    rolled_back_gateways: List[str] = field(default_factory=list)
    stage_durations: Dict[str, float] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)

    def to_markdown(self) -> str:
        lines = [
            f"# Multi-Gateway Staged Rollout Audit Report",
            f"- **Execution Timestamp**: `{self.timestamp}`",
            f"- **Total Target Gateways**: `{self.total_gateways}`",
            f"- **Canary Gating**: `{'PASSED' if self.canary_passed else 'FAILED / HALTED'}`",
            f"- **Successfully Provisioned**: `{len(self.successful_gateways)}`",
            f"- **Failed / Offline**: `{len(self.failed_gateways)}`",
            f"- **Automatically Rolled Back**: `{len(self.rolled_back_gateways)}`",
            "",
            "## Execution Timeline by Stage",
            "| Stage | Duration (s) |",
            "| :--- | :--- |"
        ]
        for stage, dur in self.stage_durations.items():
            lines.append(f"| {stage} | {dur:.2f}s |")

        if self.failed_gateways:
            lines.append("")
            lines.append("## Failed Gateways")
            for f_gw in self.failed_gateways:
                lines.append(f"- ❌ `{f_gw}`")

        if self.errors:
            lines.append("")
            lines.append("## Error Log")
            for err in self.errors:
                lines.append(f"- `{err}`")

        return "\n".join(lines)


class RolloutEngine:
    """
    Coordinates multi-stage deployments across city edge gateways.
    """

    def __init__(
        self,
        backup_catalog: Optional[BackupCatalog] = None,
        batch_size: int = 20,
        concurrency: int = 15,
        reports_dir: str = "reports"
    ):
        self.catalog = backup_catalog or BackupCatalog()
        self.batch_size = batch_size
        self.concurrency = concurrency
        self.reports_dir = reports_dir
        os.makedirs(self.reports_dir, exist_ok=True)

    def run_preflight_lint(
        self,
        gateways: List[Dict[str, Any]],
        devices_by_gw: Dict[str, List[Any]]
    ) -> List[str]:
        """Validates configuration parameters before sending any network packets."""
        errors = []
        seen_ips = set()
        seen_ids = set()

        for gw in gateways:
            gw_id = gw.get("gateway_id")
            ip = gw.get("ip_address")

            if gw_id in seen_ids:
                errors.append(f"Duplicate gateway ID detected: '{gw_id}'")
            seen_ids.add(gw_id)

            if ip in seen_ips:
                errors.append(f"Duplicate IP address detected across gateways: '{ip}'")
            seen_ips.add(ip)

            # Check downstream device station IDs
            devs = devices_by_gw.get(gw_id, [])
            seen_slaves_per_channel: Dict[str, set] = {}
            for d in devs:
                chn = getattr(d, "channel", d.get("channel") if isinstance(d, dict) else "")
                slave = str(getattr(d, "devaddr_str", d.get("devaddr_str") if isinstance(d, dict) else ""))
                if chn and slave:
                    if chn not in seen_slaves_per_channel:
                        seen_slaves_per_channel[chn] = set()
                    if slave in seen_slaves_per_channel[chn]:
                        errors.append(f"Gateway '{gw_id}': Duplicate Modbus slave ID '{slave}' on channel '{chn}'")
                    seen_slaves_per_channel[chn].add(slave)

        return errors

    def execute_canary_deployment(
        self,
        canary_gw_info: Dict[str, Any],
        deploy_fn: Callable[[GatewayClient, Dict[str, Any]], bool],
        auto_rollback: bool = True
    ) -> Tuple[bool, Optional[str]]:
        """
        Executes deployment on single canary gateway with automated rollback.
        Returns: (success: bool, error_msg: Optional[str])
        """
        ip = canary_gw_info.get("ip_address")
        gw_id = canary_gw_info.get("gateway_id", "CANARY")
        port = canary_gw_info.get("port", 80)
        user = canary_gw_info.get("username", "Teamtech12!")
        pwd = canary_gw_info.get("password", "teamtech")

        logger.info(f"=== STAGE 1: CANARY ROLLOUT ON {gw_id} ({ip}) ===")
        client = GatewayClient(host=ip, port=port, username=user, password=pwd, read_only=False)

        snapshot_path = None
        try:
            client.login()

            # 1. Take Pre-Flight Backup
            snapshot_path = self.catalog.create_snapshot(client, gateway_id=gw_id, tag="CANARY_PRE_FLIGHT")
            logger.info(f"[{ip}] Pre-flight backup recorded: {snapshot_path}")

            # 2. Deploy Configuration Delta
            success = deploy_fn(client, canary_gw_info)
            if not success:
                raise RuntimeError("Deployment function reported failure.")

            # 3. Post-Apply Verification Soak Test
            validator = GatewayValidator(client, gateway_id=gw_id)
            report = validator.wait_and_verify(settle_delay_seconds=4)

            if not report.is_healthy:
                raise RuntimeError(f"Post-apply health check failed: {report.errors}")

            logger.info(f"[+] Canary deployment verified successfully on {gw_id} ({ip}).")
            return True, None

        except Exception as e:
            err_msg = str(e)
            logger.critical(f"[-] CANARY DEPLOYMENT FAILED on {gw_id}: {err_msg}")

            if auto_rollback and snapshot_path:
                logger.warning(f"[{ip}] Initiating AUTOMATED CANARY ROLLBACK to snapshot: {snapshot_path}...")
                try:
                    snapshot = self.catalog.load_snapshot(snapshot_path)
                    client.restore_full_state(snapshot)
                    logger.info(f"[{ip}] Canary rollback successfully applied.")
                except Exception as rb_err:
                    logger.critical(f"[{ip}] FATAL: Automated rollback failed: {rb_err}")

            return False, err_msg

    def execute_staged_rollout(
        self,
        gateways: List[Dict[str, Any]],
        devices_by_gw: Dict[str, List[Any]],
        deploy_fn: Callable[[GatewayClient, Dict[str, Any]], bool],
        canary_ip: Optional[str] = None,
        auto_rollback: bool = True
    ) -> RolloutReport:
        """
        Executes complete staged pipeline across all gateways.
        """
        report = RolloutReport(
            timestamp=time.strftime("%Y-%m-%d %H:%M:%S"),
            total_gateways=len(gateways)
        )

        # Stage 0: Lint
        t0 = time.time()
        lint_errors = self.run_preflight_lint(gateways, devices_by_gw)
        report.stage_durations[RolloutStage.LINT.value] = time.time() - t0
        if lint_errors:
            report.errors.extend(lint_errors)
            logger.error(f"Pre-flight lint failed with {len(lint_errors)} errors. Halting rollout.")
            return report

        if not gateways:
            return report

        # Stage 1: Canary
        canary_gw = None
        if canary_ip:
            for g in gateways:
                if g.get("ip_address") == canary_ip:
                    canary_gw = g
                    break
        if not canary_gw:
            canary_gw = gateways[0]

        report.canary_gateway = canary_gw.get("gateway_id", "CANARY")
        t1 = time.time()
        c_passed, c_err = self.execute_canary_deployment(canary_gw, deploy_fn, auto_rollback=auto_rollback)
        report.stage_durations[RolloutStage.CANARY.value] = time.time() - t1
        report.canary_passed = c_passed

        if not c_passed:
            report.failed_gateways.append(canary_gw.get("gateway_id"))
            report.errors.append(f"Canary failure: {c_err}")
            if auto_rollback:
                report.rolled_back_gateways.append(canary_gw.get("gateway_id"))
            logger.critical("Canary stage failed. Pipeline terminated to prevent city-wide blast radius.")
            self._save_report(report)
            return report

        report.successful_gateways.append(canary_gw.get("gateway_id"))

        # Remaining gateways
        remaining_gateways = [g for g in gateways if g.get("gateway_id") != canary_gw.get("gateway_id")]
        if not remaining_gateways:
            self._save_report(report)
            return report

        # Stage 2 & 3: Batched Concurrent Rollout
        t2 = time.time()
        pool = WorkerPool(max_workers=self.concurrency)

        def worker_task(gw_info: Dict[str, Any]) -> bool:
            ip = gw_info.get("ip_address")
            gw_id = gw_info.get("gateway_id", "GW")
            client = GatewayClient(
                host=ip,
                port=gw_info.get("port", 80),
                username=gw_info.get("username", "Teamtech12!"),
                password=gw_info.get("password", "teamtech"),
                read_only=False
            )
            client.login()
            snap_path = self.catalog.create_snapshot(client, gateway_id=gw_id, tag="BATCH_PRE_FLIGHT")
            try:
                ok = deploy_fn(client, gw_info)
                if not ok:
                    raise RuntimeError("Deployment returned False")
                return True
            except Exception as e:
                if auto_rollback and snap_path:
                    snap = self.catalog.load_snapshot(snap_path)
                    client.restore_full_state(snap)
                    report.rolled_back_gateways.append(gw_id)
                raise

        # Process in batches
        for i in range(0, len(remaining_gateways), self.batch_size):
            batch = remaining_gateways[i : i + self.batch_size]
            batch_num = (i // self.batch_size) + 1
            logger.info(f"=== STAGE 3: EXECUTING BATCH {batch_num} ({len(batch)} GATEWAYS) ===")
            results = pool.execute_all(batch, worker_task, task_name=f"Batch {batch_num}")

            for r in results:
                if r.status == "SUCCESS":
                    report.successful_gateways.append(r.gateway_id)
                else:
                    report.failed_gateways.append(r.gateway_id)
                    if r.error:
                        report.errors.append(f"{r.gateway_id}: {r.error}")

        report.stage_durations[RolloutStage.FULL.value] = time.time() - t2
        self._save_report(report)
        return report

    def _save_report(self, report: RolloutReport):
        ts = time.strftime("%Y%m%d_%H%M%S")
        md_file = os.path.join(self.reports_dir, f"audit_report_{ts}.md")
        with open(md_file, "w", encoding="utf-8") as f:
            f.write(report.to_markdown())
        logger.info(f"Audit report saved: {md_file}")
