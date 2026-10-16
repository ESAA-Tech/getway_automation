"""
Declarative Inventory Ingestion & Hardware Profile Repository.
Parses and validates gateways.csv, devices.csv, and template profiles.
"""

import os
import csv
import json
import logging
from typing import List, Dict, Any, Optional
from pro.models.gateway import GatewayEntity, GatewayNetwork, GatewayAuth, GatewayLocation
from pro.models.device import DeviceConfig
from pro.models.datanode import DeviceProfile, RegisterPoint

logger = logging.getLogger("pro.storage.inventory_repo")


class InventoryRepository:
    """
    Ingests and validates CSV inventory records and device profile templates.
    """

    def __init__(self, profiles_dir: Optional[str] = None):
        base_dir = os.path.dirname(os.path.dirname(__file__))
        self.profiles_dir = profiles_dir or os.path.join(base_dir, "templates", "profiles")
        self._profiles_cache: Dict[str, DeviceProfile] = {}

    def load_gateways(self, csv_path: str = "inventory/gateways.csv") -> List[GatewayEntity]:
        """Loads and validates gateway definitions from CSV."""
        if not os.path.exists(csv_path):
            raise FileNotFoundError(f"Gateways inventory file not found: {csv_path}")

        gateways = []
        with open(csv_path, mode="r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row_idx, row in enumerate(reader, start=2):
                gw_id = row.get("gateway_id", "").strip()
                if not gw_id or gw_id.startswith("#"):
                    continue

                ip = row.get("ip_address", "").strip()
                if not ip or ip.startswith("#"):
                    continue

                port_str = row.get("port", "80").strip()
                port = int(port_str) if port_str.isdigit() else 80

                user = row.get("username", "Teamtech12!").strip()
                pwd = row.get("password", "teamtech").strip()
                loc = row.get("location", "").strip()
                desc = row.get("description", "").strip()

                entity = GatewayEntity(
                    gateway_id=gw_id,
                    network=GatewayNetwork(
                        management_ip=ip,
                        management_port=port
                    ),
                    auth=GatewayAuth(
                        username=user,
                        password=pwd
                    ),
                    location=GatewayLocation(
                        sector=loc,
                        description=desc
                    )
                )
                gateways.append(entity)

        logger.info(f"Loaded {len(gateways)} valid gateway definitions from {csv_path}")
        return gateways

    def load_devices(self, csv_path: str = "inventory/devices.csv") -> Dict[str, List[DeviceConfig]]:
        """Loads downstream device declarations grouped by gateway_id."""
        if not os.path.exists(csv_path):
            raise FileNotFoundError(f"Devices inventory file not found: {csv_path}")

        devices_by_gw: Dict[str, List[DeviceConfig]] = {}
        with open(csv_path, mode="r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row_idx, row in enumerate(reader, start=2):
                gw_id = row.get("gateway_id", "").strip()
                if not gw_id or gw_id.startswith("#"):
                    continue

                plc_id = row.get("plc_id", "").strip()
                if not plc_id:
                    continue

                channel = row.get("channel", "RS485-1").strip()
                devtyp = row.get("device_type", "PLC_MDBS_RTU").strip()
                mfr = row.get("manufacturer", "MFR_MODBUS").strip()
                target_ip = row.get("target_ip", "").strip()
                
                port_str = row.get("target_port", "0").strip()
                port = int(port_str) if port_str.isdigit() else 0

                slave_id = row.get("slave_id", "1").strip()
                interval_str = row.get("interval_ms", "500").strip()
                interval = int(interval_str) if interval_str.isdigit() else 500

                timeout_str = row.get("timeout_ms", "1000").strip()
                timeout = int(timeout_str) if timeout_str.isdigit() else 1000

                dev_cfg = DeviceConfig(
                    plc_id=plc_id,
                    chn_en=True,
                    channel=channel,
                    devtyp=devtyp,
                    manufacturer=mfr,
                    ipaddr=target_ip,
                    port=port,
                    devaddr_str=slave_id,
                    acq_intv=interval,
                    acqtimeout=timeout
                )

                if gw_id not in devices_by_gw:
                    devices_by_gw[gw_id] = []
                devices_by_gw[gw_id].append(dev_cfg)

        logger.info(f"Loaded devices mapping across {len(devices_by_gw)} gateways from {csv_path}")
        return devices_by_gw

    def load_profile(self, profile_name_or_id: str) -> DeviceProfile:
        """Loads a reusable device register profile JSON."""
        # Check cache
        if profile_name_or_id in self._profiles_cache:
            return self._profiles_cache[profile_name_or_id]

        filename = profile_name_or_id if profile_name_or_id.endswith(".json") else f"{profile_name_or_id}.json"
        path = os.path.join(self.profiles_dir, filename)

        if not os.path.exists(path):
            raise FileNotFoundError(f"Device profile not found: {path}")

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        profile = DeviceProfile(**data)
        self._profiles_cache[profile.profile_id] = profile
        self._profiles_cache[profile_name_or_id] = profile
        return profile

    def load_all_profiles(self) -> Dict[str, DeviceProfile]:
        """Loads all available profile JSON files in profiles directory."""
        if not os.path.exists(self.profiles_dir):
            return {}

        profiles = {}
        for fname in os.listdir(self.profiles_dir):
            if fname.endswith(".json"):
                try:
                    p = self.load_profile(fname)
                    profiles[p.profile_id] = p
                except Exception as e:
                    logger.warning(f"Could not load profile {fname}: {e}")
        return profiles
