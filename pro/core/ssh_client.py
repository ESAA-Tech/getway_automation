"""
Dropbear Out-of-Band SSH Manager for Four-Faith OpenWrt Gateways.
Supports legacy ciphers (diffie-hellman-group1-sha1, ssh-rsa, hmac-sha1).
"""

import subprocess
import logging
from typing import Tuple, Optional, Dict, Any

logger = logging.getLogger("pro.core.ssh_client")


class GatewaySSHClient:
    """
    Manages out-of-band Dropbear SSH sessions on Four-Faith Gateways.
    Used for disaster recovery, service restarts, and low-level diagnostics.
    """

    def __init__(
        self,
        host: str,
        port: int = 22,
        username: str = "root",
        password: Optional[str] = "teamtech",
        timeout: int = 10
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.timeout = timeout
        self._paramiko_client = None

    def _exec_paramiko(self, command: str) -> Tuple[int, str, str]:
        """Executes command using Paramiko with legacy cipher negotiation."""
        import paramiko
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        # Support older Dropbear key exchanges & ciphers
        client.connect(
            hostname=self.host,
            port=self.port,
            username=self.username,
            password=self.password,
            timeout=self.timeout,
            banner_timeout=self.timeout,
            look_for_keys=False,
            allow_agent=False,
            disabled_algorithms={
                "pubkeys": []  # Allow ssh-rsa
            }
        )

        stdin, stdout, stderr = client.exec_command(command, timeout=self.timeout)
        exit_code = stdout.channel.recv_exit_status()
        out_str = stdout.read().decode("utf-8", errors="replace")
        err_str = stderr.read().decode("utf-8", errors="replace")
        client.close()
        return exit_code, out_str, err_str

    def _exec_subprocess(self, command: str) -> Tuple[int, str, str]:
        """Fallback to OpenSSH command-line binary."""
        ssh_cmd = [
            "ssh",
            "-p", str(self.port),
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "ConnectTimeout=" + str(self.timeout),
            "-o", "KexAlgorithms=+diffie-hellman-group1-sha1",
            "-o", "HostKeyAlgorithms=+ssh-rsa",
            f"{self.username}@{self.host}",
            command
        ]
        res = subprocess.run(
            ssh_cmd,
            capture_output=True,
            text=True,
            timeout=self.timeout
        )
        return res.returncode, res.stdout, res.stderr

    def exec_command(self, command: str) -> Tuple[int, str, str]:
        """Executes a remote shell command with automatic driver fallback."""
        try:
            return self._exec_paramiko(command)
        except Exception as p_err:
            logger.debug(f"[{self.host}] Paramiko SSH execution failed: {p_err}. Trying subprocess fallback...")
            try:
                return self._exec_subprocess(command)
            except Exception as sub_err:
                logger.error(f"[{self.host}] Subprocess SSH fallback failed: {sub_err}")
                raise RuntimeError(f"SSH execution failed on {self.host}: {p_err}; fallback: {sub_err}")

    def test_connection(self) -> bool:
        """Verifies SSH reachability."""
        try:
            code, out, _ = self.exec_command("echo READY")
            return code == 0 and "READY" in out
        except Exception:
            return False

    def restart_uhttpd(self) -> bool:
        """Restarts the Libuhttpd web server daemon."""
        logger.warning(f"[{self.host}] Restarting /etc/init.d/uhttpd over SSH...")
        code, out, err = self.exec_command("/etc/init.d/uhttpd restart")
        return code == 0

    def restart_smtgw(self) -> bool:
        """Restarts the smtgw3 acquisition daemon."""
        logger.warning(f"[{self.host}] Restarting /etc/init.d/smtgw over SSH...")
        code, out, err = self.exec_command("/etc/init.d/smtgw restart")
        return code == 0

    def get_system_info(self) -> Dict[str, Any]:
        """Gathers Linux kernel version, uptime, and memory statistics."""
        info = {}
        try:
            code, out, _ = self.exec_command("uname -a; uptime; free")
            if code == 0:
                lines = out.splitlines()
                info["kernel"] = lines[0] if lines else "N/A"
                info["raw"] = out
        except Exception as e:
            info["error"] = str(e)
        return info
