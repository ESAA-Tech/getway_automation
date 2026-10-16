"""
Gateway Connection, Authentication, and Inventory Schemas.
"""

import os
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator


class GatewayAuth(BaseModel):
    """Credentials for JSON-RPC and secondary SSH administration."""
    username: str = Field(default="Teamtech12!", description="Gateway Web/RPC Admin User")
    password: str = Field(default="teamtech", description="Gateway Web/RPC Password")
    password_env: Optional[str] = Field(default=None, description="Environment variable holding password")
    ssh_username: str = Field(default="root", description="Dropbear SSH user")
    ssh_password: Optional[str] = Field(default=None, description="Dropbear SSH password")

    def get_effective_password(self, gateway_id: str = "") -> str:
        """Resolves password dynamically with environment variable fallback."""
        if self.password_env and os.getenv(self.password_env):
            return os.getenv(self.password_env)
        if gateway_id and os.getenv(f"GW_PASS_{gateway_id}"):
            return os.getenv(f"GW_PASS_{gateway_id}")
        if os.getenv("DEFAULT_GW_PASS"):
            return os.getenv("DEFAULT_GW_PASS")
        return self.password


class GatewayNetwork(BaseModel):
    """Network connection parameters."""
    management_ip: str = Field(..., description="IPv4 address of gateway management interface")
    management_port: int = Field(default=80, ge=1, le=65535, description="JSON-RPC HTTP port")
    ssh_fallback_port: int = Field(default=22, ge=1, le=65535, description="Dropbear SSH port")
    timeout_seconds: int = Field(default=8, ge=1, le=60, description="HTTP socket timeout")
    max_retries: int = Field(default=3, ge=1, le=10, description="Max RPC retry attempts")


class GatewayLocation(BaseModel):
    """Geographic or municipal positioning."""
    sector: Optional[str] = Field(default="", description="City Sector / Substation")
    pole_id: Optional[str] = Field(default="P001", description="Physical Smart Pole ID (e.g. P001)")
    description: Optional[str] = Field(default="", description="Human-readable site notes")


class GatewayUplinkConfig(BaseModel):
    """Upstream cloud broker connection."""
    primary_broker: str = Field(default="192.168.4.124", description="MQTT Broker IP")
    port: int = Field(default=1883, ge=1, le=65535, description="MQTT Broker Port")
    client_id_prefix: str = Field(default="scmp-pole", description="Client ID prefix")
    username: str = Field(default="gw-pole-test", description="MQTT Auth Username")
    password: str = Field(default="", description="MQTT Auth Password")
    keepalive: int = Field(default=60, ge=5, le=3600, description="Keepalive heartbeat seconds")


class GatewayEntity(BaseModel):
    """Complete declared gateway specification."""
    gateway_id: str = Field(..., description="Unique Gateway ID (e.g. GW-001)")
    network: GatewayNetwork
    auth: GatewayAuth = Field(default_factory=GatewayAuth)
    location: GatewayLocation = Field(default_factory=GatewayLocation)
    uplink: Optional[GatewayUplinkConfig] = Field(default=None)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("gateway_id")
    @classmethod
    def validate_gateway_id(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("gateway_id cannot be blank")
        return clean
