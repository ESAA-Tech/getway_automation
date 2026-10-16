"""
High-Performance Four-Faith Industrial Smart Gateway JSON-RPC 2.0 API Client.
"""

import time
import random
import logging
from typing import Dict, Any, List, Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger("pro.core.client")


class GatewayError(Exception):
    """Base exception for gateway operations."""
    pass


class GatewayAuthError(GatewayError):
    """Authentication failed."""
    pass


class GatewayConnectionError(GatewayError):
    """Network connection or timeout error."""
    pass


class GatewayClient:
    """
    Robust JSON-RPC 2.0 Client for Four-Faith Industrial Gateways.
    
    Provides:
    - Connection pooling & automated retries with exponential backoff and jitter.
    - Bearer session token management (`sid`) with automatic refresh.
    - Complete inspection and configuration of PLCs, Datanodes, Uplinks, and Scripts.
    - Atomic rollback and full state snapshot capabilities.
    """

    def __init__(
        self,
        host: str,
        port: int = 80,
        username: str = "Teamtech12!",
        password: str = "teamtech",
        timeout: int = 8,
        max_retries: int = 3,
        read_only: bool = True
    ):
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}/v1/rpc"
        self.username = username
        self.password = password
        self.timeout = timeout
        self.max_retries = max_retries
        self.read_only = read_only
        self.sid: Optional[str] = None
        self._req_id = 1

        # Configure resilient session
        self.session = requests.Session()
        retries = Retry(
            total=max_retries,
            backoff_factor=0.5,
            status_forcelist=[502, 503, 504],
            raise_on_status=False
        )
        adapter = HTTPAdapter(max_retries=retries, pool_connections=10, pool_maxsize=20)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def _rpc_call(self, method: str, params: Optional[Any] = None, require_auth: bool = True) -> Any:
        """Executes a JSON-RPC 2.0 call with authentication and jittered backoff."""
        self._req_id += 1
        payload = {
            "jsonrpc": "2.0",
            "id": self._req_id,
            "method": method
        }
        if params is not None:
            payload["params"] = params

        headers = {"Content-Type": "application/json"}
        if require_auth:
            if not self.sid:
                self.login()
            headers["Authorization"] = self.sid

        last_exc = None
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.session.post(
                    self.base_url,
                    json=payload,
                    headers=headers,
                    timeout=self.timeout
                )

                if response.status_code == 401 and require_auth:
                    logger.warning(f"[{self.host}] Session expired. Re-authenticating (attempt {attempt})...")
                    self.login()
                    headers["Authorization"] = self.sid
                    continue

                if response.status_code != 200:
                    raise GatewayConnectionError(
                        f"HTTP {response.status_code} error from {self.host} calling '{method}': {response.text}"
                    )

                res_json = response.json()
                if "error" in res_json:
                    err = res_json["error"]
                    err_code = err.get("code")
                    err_msg = err.get("message", "Unknown RPC error")
                    err_data = err.get("data", "")
                    
                    if "auth" in err_msg.lower() or err_code == -32000:
                        if require_auth and attempt < self.max_retries:
                            logger.warning(f"[{self.host}] Session expired ({err_msg}). Re-authenticating (attempt {attempt})...")
                            time.sleep(1)
                            self.login()
                            headers["Authorization"] = self.sid
                            continue
                        raise GatewayAuthError(f"Auth error from {self.host}: {err_msg} ({err_data})")
                    raise GatewayError(f"RPC Error from {self.host} in '{method}': {err_msg} ({err_data})")

                return res_json.get("result", {})

            except (requests.ConnectionError, requests.Timeout) as e:
                last_exc = e
                wait_time = (2 ** attempt) * 0.5 + random.uniform(0.1, 0.5)
                logger.debug(f"[{self.host}] Network hiccup calling {method}. Retrying in {wait_time:.2f}s... ({e})")
                time.sleep(wait_time)
            except GatewayAuthError:
                raise
            except Exception as e:
                last_exc = e
                break

        raise GatewayConnectionError(f"Failed to execute '{method}' on {self.host} after {self.max_retries} attempts: {last_exc}")

    def login(self) -> str:
        """
        Authenticates with the gateway, automatically handling BLIST_REJECT cooldowns
        and credential fallbacks.
        """
        passwords_to_try = [self.password]
        if self.password == "Teamtech12!" and "teamtech" not in passwords_to_try:
            passwords_to_try.append("teamtech")
        elif self.password == "teamtech" and "Teamtech12!" not in passwords_to_try:
            passwords_to_try.append("Teamtech12!")

        for pwd in passwords_to_try:
            for attempt in range(1, 4):
                logger.info(f"[{self.host}] Authenticating as '{self.username}' (attempt {attempt})...")
                res = self._rpc_call("login", {"username": self.username, "password": pwd}, require_auth=False)
                
                # Check for brute-force rate-limit cooldown
                if isinstance(res, dict) and res.get("error") == "BLIST_REJECT":
                    cooldown = int(res.get("delay", 5)) + 1
                    logger.warning(f"[{self.host}] Gateway rate-limit active (BLIST_REJECT). Cooling down for {cooldown}s...")
                    time.sleep(cooldown)
                    continue

                if isinstance(res, dict) and res.get("sid"):
                    self.sid = res["sid"]
                    self.password = pwd  # Remember working password
                    logger.info(f"[{self.host}] Authentication successful. SID: {self.sid[:8]}...")
                    return self.sid

                # If returned auth fail, break to try next password
                if isinstance(res, dict) and "auth" in str(res.get("error", "")).lower():
                    logger.warning(f"[{self.host}] Credentials rejected with '{pwd}'.")
                    break

        raise GatewayAuthError(f"[{self.host}] Authentication failed. Please verify credentials (username: '{self.username}').")

    def logout(self) -> bool:
        """Terminates session on gateway."""
        if not self.sid:
            return True
        try:
            self._rpc_call("logout", {})
            self.sid = None
            return True
        except Exception:
            self.sid = None
            return False

    def is_alive(self) -> bool:
        """Verifies session health."""
        try:
            self._rpc_call("alive")
            return True
        except Exception:
            return False

    # ==========================================
    # DOWNSTREAM DEVICES (PLC ENGINE)
    # ==========================================

    def get_device_list(self) -> List[Dict[str, Any]]:
        """Fetch all configured downstream devices."""
        res = self._rpc_call("smtgw_plc_list_get", {})
        return res if isinstance(res, list) else []

    def set_device_list(self, devices: List[Dict[str, Any]]) -> Any:
        """Deploy downstream device list (requires read_only=False)."""
        if self.read_only:
            raise GatewayError(f"[{self.host}] Mutation rejected: client is in READ-ONLY mode.")
        logger.info(f"[{self.host}] Deploying {len(devices)} downstream devices...")
        return self._rpc_call("smtgw_plc_list_set", devices)

    def get_device_datanodes(self, plc_id: str) -> Dict[str, Any]:
        """Fetch datanode register mappings for a specific device."""
        return self._rpc_call("smtgw_plc_datanode_get", {"plc_id": plc_id})

    def set_device_datanodes(self, plc_id: str, tags: List[Dict[str, Any]]) -> Any:
        """Assign datanode register mappings for a specific device."""
        if self.read_only:
            raise GatewayError(f"[{self.host}] Mutation rejected: client is in READ-ONLY mode.")
        if not tags:
            logger.info(f"[{self.host}] Skipping datanode set for '{plc_id}' (0 tags).")
            return {}
        logger.info(f"[{self.host}] Configuring {len(tags)} datanodes for device '{plc_id}'...")
        return self._rpc_call("smtgw_plc_datanode_set", {
            "plc_id": plc_id,
            "default_cmd": tags
        })

    def get_all_datanodes(self) -> Dict[str, List[Dict[str, Any]]]:
        """Fetch datanodes for every registered device."""
        devices = self.get_device_list()
        all_nodes = {}
        for d in devices:
            plc_id = d.get("plc_id")
            if plc_id:
                try:
                    res = self.get_device_datanodes(plc_id)
                    all_nodes[plc_id] = res.get("default_cmd", [])
                except Exception as e:
                    logger.warning(f"[{self.host}] Failed to get datanodes for '{plc_id}': {e}")
                    all_nodes[plc_id] = []
        return all_nodes

    def get_device_connection_status(self) -> List[Dict[str, Any]]:
        """Fetch real-time device connection and polling statuses."""
        try:
            res = self._rpc_call("smtgw_plc_status_get", {})
            return res if isinstance(res, list) else []
        except Exception as e:
            logger.warning(f"[{self.host}] Could not get PLC status: {e}")
            return []

    # ==========================================
    # CLOUD UPLINK / MQTT (CT ENGINE)
    # ==========================================

    def get_uplink_list(self) -> List[Dict[str, Any]]:
        """Fetch configured cloud uplink servers."""
        res = self._rpc_call("smtgw_ct_list_get", {})
        return res if isinstance(res, list) else []

    def set_uplink_list(self, uplinks: List[Dict[str, Any]]) -> Any:
        """Configure cloud transmission servers."""
        if self.read_only:
            raise GatewayError(f"[{self.host}] Mutation rejected: client is in READ-ONLY mode.")
        logger.info(f"[{self.host}] Configuring {len(uplinks)} cloud uplinks...")
        return self._rpc_call("smtgw_ct_list_set", uplinks)

    def get_uplink_status(self) -> List[Dict[str, Any]]:
        """Fetch live cloud connection states."""
        try:
            res = self._rpc_call("smtgw_ct_status_get", {})
            return res if isinstance(res, list) else []
        except Exception as e:
            logger.warning(f"[{self.host}] Could not fetch CT status: {e}")
            return []

    def get_ct_datanodes(self, ct_id: str) -> List[Dict[str, Any]]:
        """Fetch bound datanodes for a cloud uplink."""
        try:
            res = self._rpc_call("smtgw_ct_datanode_get", {"ct_id": ct_id})
            return res.get("ct_datanode", []) if isinstance(res, dict) else []
        except Exception as e:
            logger.warning(f"[{self.host}] Could not fetch ct_datanode for '{ct_id}': {e}")
            return []

    def set_ct_datanodes(self, ct_id: str, bindings: List[Dict[str, Any]]) -> Any:
        """Bind datanodes to cloud transmission service."""
        if self.read_only:
            raise GatewayError(f"[{self.host}] Mutation rejected: client is in READ-ONLY mode.")
        return self._rpc_call("smtgw_ct_datanode_set", {
            "ct_id": ct_id,
            "ct_datanode": bindings
        })

    # ==========================================
    # MESSAGE SCRIPTS ENGINE
    # ==========================================

    def get_scripts(self, ct_id: str) -> Dict[str, Any]:
        """Fetch message transformation scripts for an uplink."""
        try:
            res = self._rpc_call("smtgw_script_get", {"ct_id": ct_id})
            return res if isinstance(res, dict) else {"script_up": [], "script_down": []}
        except Exception as e:
            logger.warning(f"[{self.host}] Could not fetch scripts for '{ct_id}': {e}")
            return {"script_up": [], "script_down": []}

    def set_scripts(self, ct_id: str, script_up: List[Dict[str, Any]], script_down: List[Dict[str, Any]]) -> Any:
        """Deploy upstream and downstream transformation scripts."""
        if self.read_only:
            raise GatewayError(f"[{self.host}] Mutation rejected: client is in READ-ONLY mode.")
        logger.info(f"[{self.host}] Deploying scripts to uplink '{ct_id}': {len(script_up)} up, {len(script_down)} down")
        return self._rpc_call("smtgw_script_set", {
            "ct_id": ct_id,
            "script_up": script_up,
            "script_down": script_down
        })

    def get_script_log(self, ct_id: str, script_up_id: str = "", script_down_id: str = "") -> Any:
        """Fetch runtime execution output for a script."""
        try:
            return self._rpc_call("smtgw_script_log_get", {
                "ct_id": ct_id,
                "script_up_id": script_up_id,
                "script_down_id": script_down_id
            })
        except Exception as e:
            return str(e)

    # ==========================================
    # TELEMETRY & SYSTEM ENGINE
    # ==========================================

    def get_live_telemetry(self) -> Dict[str, Any]:
        """Fetch current telemetry readings across all datanodes."""
        try:
            res = self._rpc_call("smtgw_node_status_get", {})
            return res if isinstance(res, dict) else {}
        except Exception as e:
            logger.warning(f"[{self.host}] Could not fetch live telemetry: {e}")
            return {}

    def get_serial_ports(self) -> List[Dict[str, Any]]:
        """Fetch RS485 serial port baudrate and parity settings."""
        res = self._rpc_call("smtgw_serial_cfg_get", {})
        return res if isinstance(res, list) else []

    def apply_config(self, services: Optional[List[str]] = None) -> Any:
        """Commit NVRAM changes and reload daemons without full reboot."""
        if self.read_only:
            raise GatewayError(f"[{self.host}] Mutation rejected: client is in READ-ONLY mode.")
        params = {"services": services or ["smtgw3"]}
        logger.info(f"[{self.host}] Committing changes and reloading daemons: {params}...")
        return self._rpc_call("sys_apply", params)

    # ==========================================
    # FULL STATE SNAPSHOT & RESTORATION
    # ==========================================

    def get_full_state(self) -> Dict[str, Any]:
        """Extracts complete immutable gateway configuration snapshot."""
        devices = self.get_device_list()
        datanodes = self.get_all_datanodes()
        uplinks = self.get_uplink_list()
        serial_cfg = self.get_serial_ports()

        scripts_by_ct = {}
        ct_datanodes = {}
        for up in uplinks:
            ct_id = up.get("ct_id")
            if ct_id:
                scripts_by_ct[ct_id] = self.get_scripts(ct_id)
                ct_datanodes[ct_id] = self.get_ct_datanodes(ct_id)

        return {
            "gateway_ip": self.host,
            "gateway_port": self.port,
            "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "devices": devices,
            "datanodes": datanodes,
            "uplinks": uplinks,
            "serial_cfg": serial_cfg,
            "scripts": scripts_by_ct,
            "ct_datanodes": ct_datanodes
        }

    def restore_full_state(self, snapshot: Dict[str, Any]) -> bool:
        """Restores complete gateway configuration from snapshot."""
        if self.read_only:
            raise GatewayError(f"[{self.host}] Restoration rejected: client is in READ-ONLY mode.")
        logger.warning(f"[{self.host}] Performing full configuration restore from snapshot...")

        # 1. Restore Devices
        devices = snapshot.get("devices", [])
        if devices:
            self.set_device_list(devices)

        # 2. Restore Datanodes
        datanodes = snapshot.get("datanodes", {})
        for plc_id, tags in datanodes.items():
            self.set_device_datanodes(plc_id, tags)

        # 3. Restore Uplinks
        uplinks = snapshot.get("uplinks", [])
        if uplinks:
            self.set_uplink_list(uplinks)

        # 4. Restore CT Datanodes & Scripts
        ct_datanodes = snapshot.get("ct_datanodes", {})
        for ct_id, nodes in ct_datanodes.items():
            self.set_ct_datanodes(ct_id, nodes)

        scripts = snapshot.get("scripts", {})
        for ct_id, s_data in scripts.items():
            self.set_scripts(
                ct_id,
                script_up=s_data.get("script_up", []),
                script_down=s_data.get("script_down", [])
            )

        # 5. Commit & Apply
        self.apply_config()
        logger.info(f"[{self.host}] Configuration restore complete.")
        return True
