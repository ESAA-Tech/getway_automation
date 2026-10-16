"""
Versioned JSON Snapshot Storage & Disaster Recovery Rollback Catalog.
"""

import os
import json
import time
import logging
from typing import Dict, Any, List, Optional
from pro.core.client import GatewayClient

logger = logging.getLogger("pro.storage.backup_catalog")


class BackupCatalog:
    """
    Manages immutable pre-flight backups, rollback snapshots, and catalog indices.
    """

    def __init__(self, backup_dir: str = "backups"):
        self.backup_dir = backup_dir
        os.makedirs(self.backup_dir, exist_ok=True)
        self.index_file = os.path.join(self.backup_dir, "catalog_index.json")

    def _load_index(self) -> Dict[str, Any]:
        if os.path.exists(self.index_file):
            try:
                with open(self.index_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save_index(self, index_data: Dict[str, Any]):
        try:
            with open(self.index_file, "w", encoding="utf-8") as f:
                json.dump(index_data, f, indent=2)
        except Exception as e:
            logger.warning(f"Could not persist catalog index: {e}")

    def create_snapshot(
        self,
        client: GatewayClient,
        gateway_id: str,
        tag: str = "PRE_APPLY"
    ) -> str:
        """
        Extracts full gateway state and saves an immutable snapshot.
        Returns the absolute filepath to the saved backup file.
        """
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"{gateway_id}_{client.host}_{timestamp}_{tag}.json"
        filepath = os.path.join(self.backup_dir, filename)

        state = client.get_full_state()
        state["backup_metadata"] = {
            "gateway_id": gateway_id,
            "gateway_ip": client.host,
            "timestamp": timestamp,
            "tag": tag,
            "filename": filename
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)

        # Update index
        index = self._load_index()
        gw_backups = index.get(gateway_id, [])
        gw_backups.append({
            "timestamp": timestamp,
            "tag": tag,
            "filepath": filepath,
            "device_count": len(state.get("devices", [])),
            "uplink_count": len(state.get("uplinks", []))
        })
        index[gateway_id] = gw_backups
        self._save_index(index)

        logger.info(f"[{client.host}] Snapshot saved: {filepath}")
        return filepath

    def get_latest_snapshot(self, gateway_id: str) -> Optional[str]:
        """Finds the most recent backup for a gateway ID."""
        index = self._load_index()
        gw_backups = index.get(gateway_id, [])
        if gw_backups:
            return gw_backups[-1].get("filepath")
        
        # Fallback to filesystem scan
        matches = []
        for fname in os.listdir(self.backup_dir):
            if fname.startswith(gateway_id) and fname.endswith(".json") and fname != "catalog_index.json":
                matches.append(os.path.join(self.backup_dir, fname))
        if matches:
            matches.sort(key=os.path.getmtime)
            return matches[-1]
        return None

    def load_snapshot(self, filepath: str) -> Dict[str, Any]:
        """Loads snapshot JSON from disk."""
        if not os.path.isabs(filepath):
            filepath = os.path.join(self.backup_dir, filepath)
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)

    def list_snapshots(self, gateway_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Lists available snapshots."""
        index = self._load_index()
        if gateway_id:
            return index.get(gateway_id, [])
        all_snaps = []
        for gid, snaps in index.items():
            all_snaps.extend(snaps)
        return all_snaps
