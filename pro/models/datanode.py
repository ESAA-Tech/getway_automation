"""
Modbus Register Point, Datanode, Script, and Uplink Schemas.
"""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class RegisterPoint(BaseModel):
    """Single telemetry point / Modbus register configuration."""
    portid: str = Field(..., description="Point variable name (e.g. Temperature, red_level, AC-OUT1)")
    startaddr: str = Field(..., description="Register start address (e.g. 0, 8, 19)")
    addrtype: str = Field(default="03(4X)", description="Modbus function code (01(0X), 02(1X), 03(4X), 04(3X))")
    datatype: str = Field(default="u16", description="Data type: u16, u32, float, bool")
    datanum: int = Field(default=1, description="Word count (1 for 16-bit, 2 for 32-bit)")
    rdwr: str = Field(default="rw", description="Read/Write permissions: ro, rw, wo")
    cal_type: str = Field(default="disabled", description="Formula state: disabled or cal")
    formula: str = Field(default="", description="Calculation expression (e.g. ${this}/10.0)")
    description: Optional[str] = Field(default="", description="Point description")

    # Native Four-Faith auxiliary attributes
    map_up_o: str = Field(default="")
    map_down_o: str = Field(default="")
    map_up_t: str = Field(default="")
    map_down_t: str = Field(default="")
    int_bit: str = Field(default="")
    decimal_bit: str = Field(default="")

    def to_rpc_dict(self) -> dict:
        """Converts to native Four-Faith smtgw_plc_datanode_set format."""
        return {
            "portid": self.portid,
            "rdwr": self.rdwr,
            "datanum": self.datanum,
            "datatype": self.datatype,
            "cal_type": self.cal_type,
            "map_up_o": self.map_up_o,
            "map_down_o": self.map_down_o,
            "map_up_t": self.map_up_t,
            "map_down_t": self.map_down_t,
            "formula": self.formula,
            "startaddr": str(self.startaddr),
            "addrtype": self.addrtype,
            "int_bit": self.int_bit,
            "decimal_bit": self.decimal_bit
        }


class DeviceProfile(BaseModel):
    """Reusable template profile for a device type."""
    profile_id: str
    description: Optional[str] = ""
    device_defaults: Dict[str, Any] = Field(default_factory=dict)
    registers: List[RegisterPoint] = Field(default_factory=list)


class ScriptDefinition(BaseModel):
    """Message management transformation script (Duktape JavaScript)."""
    script_id: str = Field(..., description="Unique script identifier (e.g. EnvTelemetry, LampControl)")
    ds: str = Field(default="periodic_report", description="Trigger: periodic_report, change_report, form_server")
    event: str = Field(..., description="MQTT publish/subscribe topic")
    param: str = Field(default="1", description="Execution parameter / QoS")
    cycle: int = Field(default=0, description="Periodic cycle interval (seconds, 0 for event-based)")
    code: str = Field(..., description="Base64 encoded JavaScript source or raw JS")

    def to_rpc_dict(self) -> dict:
        return {
            "script_id": self.script_id,
            "ds": self.ds,
            "event": self.event,
            "param": self.param,
            "cycle": self.cycle,
            "code": self.code
        }


class CloudUplinkConfig(BaseModel):
    """Uplink server connection parameters for smtgw_ct_list_set."""
    ct_id: str = Field(default="testserver", description="Uplink service ID")
    proto: str = Field(default="TRNS_PROTO_CUSTOM_MQTT", description="Uplink protocol")
    svr_en: bool = Field(default=True, description="Enable service")
    url: str = Field(..., description="Broker hostname / IP")
    srvport: int = Field(default=1883, ge=1, le=65535, description="Broker port")
    mqtt_clientid: str = Field(..., description="MQTT client ID")
    mqtt_username: str = Field(default="", description="MQTT username")
    mqtt_pswd: str = Field(default="", description="MQTT password")
    mqtt_keepalive: int = Field(default=60)
    mqtt_timeout: int = Field(default=10)
    periodic_time: int = Field(default=10)
    clear_data: bool = Field(default=True)
    store_mode: str = Field(default="memory")
    datastore: bool = Field(default=False)

    def to_rpc_dict(self) -> dict:
        return {
            "ct_id": self.ct_id,
            "proto": self.proto,
            "svr_en": self.svr_en,
            "url": self.url,
            "srvport": self.srvport,
            "mqtt_clientid": self.mqtt_clientid,
            "mqtt_username": self.mqtt_username,
            "mqtt_pswd": self.mqtt_pswd,
            "mqtt_keepalive": self.mqtt_keepalive,
            "mqtt_timeout": self.mqtt_timeout,
            "periodic_time": self.periodic_time,
            "clear_data": self.clear_data,
            "store_mode": self.store_mode,
            "datastore": self.datastore
        }
