"""
Post-Apply Telemetry Verifier & Health Gate.
Validates live sensor polling, daemon states, and reading freshness.
"""

import time
import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from pro.core.client import GatewayClient

logger = logging.getLogger("pro.core.validator")


@dataclass
class ValidationReport:
    """Stores health check results after configuration application."""
    gateway_id: str
    gateway_ip: str
    is_healthy: bool = True
    daemon_running: bool = True
    devices_online: List[str] = field(default_factory=list)
    devices_offline: List[str] = field(default_factory=list)
    active_telemetry_samples: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def summary(self) -> str:
        status_str = "HEALTHY (PASSED)" if self.is_healthy else "UNHEALTHY (FAILED)"
        lines = [
            f"=== Health Gate Report: {self.gateway_id} ({self.gateway_ip}) -> {status_str} ===",
            f"Daemon smtgw3: {'ACTIVE' if self.daemon_running else 'CRASHED/STOPPED'}",
            f"Devices Online: {', '.join(self.devices_online) if self.devices_online else 'None'}",
            f"Devices Offline / Degraded: {', '.join(self.devices_offline) if self.devices_offline else 'None'}"
        ]
        if self.errors:
            lines.append("Errors:")
            for err in self.errors:
                lines.append(f"  [X] {err}")
        if self.warnings:
            lines.append("Warnings:")
            for warn in self.warnings:
                lines.append(f"  [!] {warn}")
        return "\n".join(lines)


class GatewayValidator:
    """
    Validates live acquisition daemon state and sensor telemetry after deployment.
    """

    def __init__(self, client: GatewayClient, gateway_id: str = "GW"):
        self.client = client
        self.gateway_id = gateway_id

    def wait_and_verify(
        self,
        expected_devices: Optional[List[str]] = None,
        settle_delay_seconds: int = 5,
        max_wait_seconds: int = 15
    ) -> ValidationReport:
        """
        Polls gateway status after a configuration apply to ensure stability.
        """
        logger.info(f"[{self.client.host}] Settling acquisition daemons ({settle_delay_seconds}s)...")
        time.sleep(settle_delay_seconds)

        report = ValidationReport(gateway_id=self.gateway_id, gateway_ip=self.client.host)

        # 1. Verify session & daemon responsiveness
        if not self.client.is_alive():
            try:
                self.client.login()
            except Exception as e:
                report.is_healthy = False
                report.daemon_running = False
                report.errors.append(f"Gateway became unresponsive after apply: {e}")
                return report

        # 2. Check PLC connection statuses
        plc_statuses = self.client.get_device_connection_status()
        status_map = {p.get("plc_id"): p.get("status", "") for p in plc_statuses if p.get("plc_id")}

        # 3. Check live telemetry samples
        telemetry = self.client.get_live_telemetry()
        report.active_telemetry_samples = telemetry

        expected = expected_devices or [d.get("plc_id") for d in self.client.get_device_list()]

        for dev_id in expected:
            dev_status = status_map.get(dev_id, "").lower()
            dev_telemetry = telemetry.get(dev_id, {})

            # Check if telemetry points exist and have recent non-zero/non-epoch timestamps
            has_live_points = False
            if isinstance(dev_telemetry, dict) and dev_telemetry:
                for pt_name, pt_val in dev_telemetry.items():
                    ctime = str(pt_val.get("ctime", "")).strip()
                    if ctime and not ctime.startswith("1970-01-01"):
                        has_live_points = True
                        break

            if dev_status in ["connect", "ok", "ready"] or has_live_points:
                report.devices_online.append(dev_id)
            else:
                report.devices_offline.append(dev_id)
                report.warnings.append(f"Device '{dev_id}' status='{dev_status}', no active live samples yet.")

        # If any core devices crashed, note error
        if len(report.devices_offline) > 0 and len(report.devices_online) == 0:
            report.is_healthy = False
            report.errors.append("No downstream devices reporting online status.")

        return report
