"""
State Reconciliation and Diff Engine.
Calculates mathematical delta between Desired State (Inventory) and Actual State (Gateway NVRAM).
"""

from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from pro.models.device import DeviceConfig
from pro.models.datanode import RegisterPoint


@dataclass
class DiffResult:
    """Stores the granular diff between desired and actual gateway states."""
    gateway_id: str
    gateway_ip: str
    
    # Device deltas
    devices_to_add: List[Dict[str, Any]] = field(default_factory=list)
    devices_to_update: List[Dict[str, Any]] = field(default_factory=list)
    devices_to_remove: List[Dict[str, Any]] = field(default_factory=list)
    devices_unchanged: List[Dict[str, Any]] = field(default_factory=list)

    # Register/Datanode deltas: Dict[plc_id, {"to_add": [], "to_update": [], "to_remove": []}]
    datanode_diffs: Dict[str, Dict[str, List[Dict[str, Any]]]] = field(default_factory=dict)

    # Cloud uplink deltas
    uplinks_to_add: List[Dict[str, Any]] = field(default_factory=list)
    uplinks_to_update: List[Dict[str, Any]] = field(default_factory=list)

    # Script deltas
    scripts_to_update: Dict[str, Any] = field(default_factory=dict)

    has_drift: bool = False

    def summary(self) -> str:
        lines = [
            f"--- State Diff for {self.gateway_id} ({self.gateway_ip}) ---",
            f"Devices: +{len(self.devices_to_add)} to add, ~{len(self.devices_to_update)} to update, -{len(self.devices_to_remove)} to remove, ={len(self.devices_unchanged)} unchanged"
        ]
        for plc_id, d_diff in self.datanode_diffs.items():
            lines.append(f"  Device '{plc_id}' Tags: +{len(d_diff.get('to_add', []))} add, ~{len(d_diff.get('to_update', []))} update, -{len(d_diff.get('to_remove', []))} remove")
        if self.uplinks_to_add or self.uplinks_to_update:
            lines.append(f"Uplinks: +{len(self.uplinks_to_add)} add, ~{len(self.uplinks_to_update)} update")
        if self.scripts_to_update:
            lines.append(f"Scripts: De-duplication consolidation proposed")
        lines.append(f"Overall State Drift: {'DRIFT DETECTED' if self.has_drift else 'IN SYNC (Zero Drift)'}")
        return "\n".join(lines)


class DiffEngine:
    """
    Mathematical state drift calculation and reconciliation engine.
    Ensures safe, idempotent provisioning by computing minimal deltas.
    """

    @staticmethod
    def _normalize_dict(d: Dict[str, Any], ignore_keys: Optional[List[str]] = None) -> Dict[str, Any]:
        ignore = set(ignore_keys or [])
        return {str(k): str(v) for k, v in d.items() if k not in ignore and v is not None}

    @classmethod
    def compute_device_diff(
        cls,
        desired_devices: List[DeviceConfig],
        actual_devices: List[Dict[str, Any]],
        allow_prune: bool = False
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Computes device differences.
        Returns: (to_add, to_update, to_remove, unchanged)
        """
        actual_by_id = {d.get("plc_id"): d for d in actual_devices if d.get("plc_id")}
        desired_by_id = {d.plc_id: d.to_rpc_dict() for d in desired_devices}

        to_add = []
        to_update = []
        unchanged = []
        to_remove = []

        # Find adds and updates
        for plc_id, desired_dict in desired_by_id.items():
            if plc_id not in actual_by_id:
                to_add.append(desired_dict)
            else:
                actual_dict = actual_by_id[plc_id]
                # Compare critical functional attributes
                compare_keys = ["chn_en", "channel", "devtyp", "devaddr_str", "ipaddr", "port", "acq_intv", "acqtimeout"]
                has_diff = False
                for k in compare_keys:
                    d_val = str(desired_dict.get(k, ""))
                    a_val = str(actual_dict.get(k, ""))
                    if d_val != a_val:
                        has_diff = True
                        break
                if has_diff:
                    to_update.append(desired_dict)
                else:
                    unchanged.append(actual_dict)

        # Find removes (only if prune is explicitly permitted)
        if allow_prune:
            for plc_id, actual_dict in actual_by_id.items():
                if plc_id not in desired_by_id:
                    to_remove.append(actual_dict)

        return to_add, to_update, to_remove, unchanged

    @classmethod
    def compute_datanode_diff(
        cls,
        desired_tags: List[RegisterPoint],
        actual_tags: List[Dict[str, Any]],
        allow_prune: bool = False
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Computes datanode tag register differences for a single device.
        """
        actual_by_tag = {t.get("portid"): t for t in actual_tags if t.get("portid")}
        desired_by_tag = {t.portid: t.to_rpc_dict() for t in desired_tags}

        to_add = []
        to_update = []
        to_remove = []

        for tag_id, desired_dict in desired_by_tag.items():
            if tag_id not in actual_by_tag:
                to_add.append(desired_dict)
            else:
                actual_dict = actual_by_tag[tag_id]
                compare_keys = ["startaddr", "addrtype", "datatype", "datanum", "rdwr", "cal_type", "formula"]
                has_diff = False
                for k in compare_keys:
                    d_val = str(desired_dict.get(k, ""))
                    a_val = str(actual_dict.get(k, ""))
                    if d_val != a_val:
                        has_diff = True
                        break
                if has_diff:
                    to_update.append(desired_dict)

        if allow_prune:
            for tag_id, actual_dict in actual_by_tag.items():
                if tag_id not in desired_by_tag:
                    to_remove.append(actual_dict)

        return {
            "to_add": to_add,
            "to_update": to_update,
            "to_remove": to_remove
        }

    @classmethod
    def compute_full_diff(
        cls,
        gateway_id: str,
        gateway_ip: str,
        desired_devices: List[DeviceConfig],
        desired_tags_map: Dict[str, List[RegisterPoint]],
        actual_snapshot: Dict[str, Any],
        allow_prune: bool = False
    ) -> DiffResult:
        """Computes comprehensive diff across devices and datanodes."""
        actual_devices = actual_snapshot.get("devices", [])
        actual_datanodes = actual_snapshot.get("datanodes", {})

        to_add, to_update, to_remove, unchanged = cls.compute_device_diff(
            desired_devices, actual_devices, allow_prune=allow_prune
        )

        datanode_diffs = {}
        for plc_id, tags in desired_tags_map.items():
            actual_tags = actual_datanodes.get(plc_id, [])
            d_diff = cls.compute_datanode_diff(tags, actual_tags, allow_prune=allow_prune)
            if d_diff["to_add"] or d_diff["to_update"] or d_diff["to_remove"]:
                datanode_diffs[plc_id] = d_diff

        has_drift = bool(to_add or to_update or to_remove or datanode_diffs)

        return DiffResult(
            gateway_id=gateway_id,
            gateway_ip=gateway_ip,
            devices_to_add=to_add,
            devices_to_update=to_update,
            devices_to_remove=to_remove,
            devices_unchanged=unchanged,
            datanode_diffs=datanode_diffs,
            has_drift=has_drift
        )
