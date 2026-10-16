"""
Downstream Field Device and Channel Schemas.
"""

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class DeviceType(str, Enum):
    MODBUS_TCP = "PLC_MDBS_TCP"
    MODBUS_RTU = "PLC_MDBS_RTU"
    FOUR_FAITH_BOX = "PLC_FF_BOX"
    SMART_BOX = "PLC_SMART_BOX"


class ChannelType(str, Enum):
    ETHERNET = "ethernet"
    RS485_1 = "RS485-1"
    RS485_2 = "RS485-2"


class DeviceConfig(BaseModel):
    """Configuration mapping for downstream PLC / Smart Box."""
    plc_id: str = Field(..., description="Unique Device ID on Gateway (e.g. enviromental, Screen, IO, rgb_controller)")
    chn_en: bool = Field(default=True, description="Enable communication channel")
    channel: str = Field(default="RS485-1", description="Physical bus: ethernet, RS485-1, RS485-2")
    devtyp: str = Field(default="PLC_MDBS_RTU", description="Driver type: PLC_MDBS_RTU, PLC_MDBS_TCP, PLC_FF_BOX")
    manufacturer: str = Field(default="MFR_MODBUS", description="Manufacturer code: MFR_MODBUS, MFR_LOCAL")
    ipaddr: str = Field(default="", description="Target IP for TCP devices")
    port: int = Field(default=0, ge=0, le=65535, description="Target TCP port")
    devaddr_str: str = Field(default="1", description="Slave address / station ID (e.g. 1, 255)")
    acq_intv: int = Field(default=500, ge=50, le=60000, description="Acquisition interval (ms)")
    acqtimeout: int = Field(default=1000, ge=50, le=60000, description="Acquisition timeout (ms)")
    cmd_acqdelay: int = Field(default=0, description="Inter-command delay (ms)")
    optimization: bool = Field(default=True, description="Group consecutive register reads")
    
    # Word & Byte Ordering
    bit16_order: str = Field(default="ab", description="16-bit word order")
    bit32_order: str = Field(default="abcd", description="32-bit word order")
    flt32_order: str = Field(default="abcd", description="Float32 byte order")
    bit16_order_d: str = Field(default="ab")
    bit32_order_d: str = Field(default="abcd")
    flt32_order_d: str = Field(default="abcd")

    def to_rpc_dict(self) -> dict:
        """Converts model to Four-Faith smtgw_plc_list_set JSON-RPC format."""
        return {
            "plc_id": self.plc_id,
            "chn_en": self.chn_en,
            "channel": self.channel,
            "devtyp": self.devtyp,
            "manufacturer": self.manufacturer,
            "ipaddr": self.ipaddr,
            "port": self.port,
            "devaddr_str": self.devaddr_str,
            "acq_intv": self.acq_intv,
            "acqtimeout": self.acqtimeout,
            "cmd_acqdelay": self.cmd_acqdelay,
            "optimization": self.optimization,
            "bit16_order": self.bit16_order,
            "bit32_order": self.bit32_order,
            "flt32_order": self.flt32_order,
            "bit16_order_d": self.bit16_order_d,
            "bit32_order_d": self.bit32_order_d,
            "flt32_order_d": self.flt32_order_d
        }
