"""
Four-Faith Embedded JavaScript Transformation Script Builder.
De-duplicates redundant periodic scripts into unified telemetry formatters
and standardizes downlink control command targets according to SCMP Backend
Architecture (scmp-backend/packages/common/src/topics/index.ts).

Topic Architecture Pattern:
  scmp/v1/{siteId}/{poleCode}/{deviceType}/{deviceId}/{direction}[/{action}]
"""

import os
import json
import copy
import base64
from typing import Dict, Any, List, Tuple, Optional
from .topics import build_device_topic


class ScriptBuilder:
    """
    Constructs clean, de-duplicated upstream and downstream JavaScript scripts
    for deployment to Four-Faith gateways via smtgw_script_set RPC.
    Adheres strictly to SCMP Backend topic architecture.
    """

    @staticmethod
    def _b64(text: str) -> str:
        return base64.b64encode(text.encode("utf-8")).decode("utf-8")

    @classmethod
    def get_env_telemetry_js(cls, device_id: str = "env-01") -> str:
        return f"""// Consolidated Environmental Telemetry Formatter (SCMP Standard)
try {{
    var raw = JSON.parse(api_data);
    var env = raw.subdev && (raw.subdev.enviromental || raw.subdev.environmental);
    var gateway_sn = raw.sn || "GW-SINGLE";
    var ctimeStr = (env && env.ctime) ? String(env.ctime).trim() : "";

    var isOffline = !env || ctimeStr === "" || ctimeStr.indexOf("1970-01-01") === 0;

    if (isOffline) {{
        var faultPayload = JSON.stringify({{
            deviceType: "env",
            deviceId: "{device_id}",
            gateway_sn: gateway_sn,
            status: "offline",
            faultCode: "ERR_ENV_OFFLINE",
            faultDescription: "Sensor acquisition timeout or disconnected",
            timestamp: new Date().toISOString()
        }});
        api_log("[ENV] Sensor OFFLINE. Publishing alert.\\n");
        api_out(api_event, faultPayload);
    }} else {{
        var telemetry = {{
            deviceType: "env",
            deviceId: "{device_id}",
            gateway_sn: gateway_sn,
            status: "online",
            timestamp: env.ctime || new Date().toISOString(),
            temperature: Number(env.Temperature || env.temp || 0),
            humidity: Number(env.Humidity || env.hum || 0),
            pressure: Number(env.pressure || env.Pressure || 0),
            pm1: Number(env.PM1 || env.pm1 || 0),
            pm25: Number(env["PM2.5"] || env.pm25 || env.pm2_5 || 0),
            pm10: Number(env.PM10 || env.pm10 || 0),
            tsp: Number(env.Tsp || env.tsp || 0),
            co2: Number(env.CO2 || env.co2 || 0),
            co: Number(env.CO || env.co || 0),
            so2: Number(env.SO2 || env.so2 || 0),
            no2: Number(env.NO2 || env.no2 || 0),
            o3: Number(env.O3 || env.o3 || 0),
            h2s_tvoc: Number(env.H2s_tvoc || env.h2s_tvoc || 0),
            noise: Number(env.Noise || env.noise || 0),
            windSpeed: Number(env.Wind_speed || env.windSpeed || 0),
            wind_direction: Number(env.Wind_direction || 0),
            rainfall: Number(env.Rainfall || env.rainfall || 0),
            illuminance: Number(env.Illuminance || 0),
            radiation: Number(env.Radiation || 0),
            uv_index: Number(env.Uv_index || 0),
            negative_o2_ions: Number(env.neg_oxygen_ions || 0)
        }};
        api_log("[ENV] Clean telemetry published.\\n");
        api_out(api_event, JSON.stringify(telemetry));
    }}
}} catch (e) {{
    api_log("[ENV ERROR] " + e.toString() + "\\n");
}}
"""

    @classmethod
    def get_io_telemetry_js(cls, device_id: str = "gw-01") -> str:
        return f"""// Smart Pole Gateway & IO Power Status Telemetry (SCMP Standard)
try {{
    var raw = JSON.parse(api_data);
    var io = raw.subdev && raw.subdev.IO;
    var gateway_sn = raw.sn || "GW-SINGLE";

    if (io) {{
        var ioPayload = {{
            deviceType: "gateway",
            deviceId: "{device_id}",
            gateway_sn: gateway_sn,
            status: "online",
            timestamp: io.ctime || new Date().toISOString(),
            metrics: {{
                ac_out1_lamp: Number(io["AC-OUT1"] || 0),
                ac_out2_strip: Number(io["AC-OUT2"] || 0),
                ac_out3_led: Number(io["AC-OUT3"] || 0),
                system_power_en: Number(io.smart_lightpole_en || 0),
                ac_dc_switch: Number(io.ac_dc_switch || 0)
            }}
        }};
        api_out(api_event, JSON.stringify(ioPayload));
    }}
}} catch (e) {{
    api_log("[IO ERROR] " + e.toString() + "\\n");
}}
"""

    @classmethod
    def get_rgb_telemetry_js(cls, device_id: str = "rgb-01") -> str:
        return f"""// Modbus RTU RGB Controller Telemetry (SCMP Standard)
try {{
    var raw = JSON.parse(api_data);
    var rgb = raw.subdev && raw.subdev.rgb_controller;
    var gateway_sn = raw.sn || "GW-SINGLE";

    if (rgb && rgb.power_state !== undefined && rgb.power_state !== "null") {{
        var rgbPayload = {{
            deviceType: "rgb",
            deviceId: "{device_id}",
            gateway_sn: gateway_sn,
            status: "online",
            timestamp: rgb.ctime || new Date().toISOString(),
            metrics: {{
                power: Number(rgb.power_state || 0),
                brightness: Number(rgb.brightness || 0),
                mode: Number(rgb.light_mode || 0),
                red: Number(rgb.red_level || 0),
                green: Number(rgb.green_level || 0),
                blue: Number(rgb.blue_level || 0)
            }}
        }};
        api_out(api_event, JSON.stringify(rgbPayload));
    }}
}} catch (e) {{
    api_log("[RGB ERROR] " + e.toString() + "\\n");
}}
"""

    @classmethod
    def get_lamp_control_js(cls) -> str:
        return """// Downlink Streetlight / Lamp Control Handler (SCMP Envelope & Direct Compatible)
api_log("=== SCMP Lamp Command Received ===\\n" + api_data + "\\n");
try {
    var payload = api_data.replace(/'/g, '"');
    payload = payload.replace(/([{,]\\s*)([a-zA-Z0-9_\\-]+)\\s*:/g, '$1"$2":');
    var envelope = JSON.parse(payload);

    var params = {};
    if (envelope.data && envelope.data.params) {
        params = envelope.data.params;
    } else if (envelope.content) {
        params = envelope.content;
    } else {
        params = envelope;
    }

    var switchStatus = params.switchStatus !== undefined ? params.switchStatus : (
        params.switch_status !== undefined ? params.switch_status : (
            params.state !== undefined ? params.state : params["AC-OUT1"]
        )
    );

    var val = "0";
    if (switchStatus === "on" || switchStatus === "ON" || switchStatus === 1 || switchStatus === "1" || switchStatus === true) {
        val = "1";
    }

    api_log("Lamp command resolved: " + (val === "1" ? "ON" : "OFF") + " (" + val + ")\\n");
    api_write_node("IO", "AC-OUT1", val);
    api_write_node("IO", "smart_lightpole_en", "1");
    api_write_node("IO", "ac_dc_switch", "1");

    if (params.dimLevel !== undefined && params.dimLevel !== null) {
        api_log("Dim level: " + params.dimLevel + "\\n");
    }
} catch (e) {
    api_log("[CMD ERROR] " + e.toString() + "\\n");
}
"""

    @classmethod
    def get_rgb_control_js(cls) -> str:
        return """// Downlink Modbus RGB Controller Handler (SCMP Envelope & Direct Compatible)
api_log("=== SCMP RGB Command Received ===\\n" + api_data + "\\n");
try {
    var payload = api_data.replace(/'/g, '"');
    payload = payload.replace(/([{,]\\s*)([a-zA-Z0-9_\\-]+)\\s*:/g, '$1"$2":');
    var envelope = JSON.parse(payload);

    var params = (envelope.data && envelope.data.params) ? envelope.data.params : envelope;

    var power = params.power !== undefined ? params.power : params.switchStatus;
    if (power !== undefined) {
        var powerVal = (power === "on" || power === "ON" || power === 1 || power === "1" || power === true) ? "1" : "0";
        api_write_node("rgb_controller", "power_state", powerVal);
    }
    if (params.brightness !== undefined) api_write_node("rgb_controller", "brightness", String(params.brightness));
    if (params.mode !== undefined) {
        var modeVal = params.mode === "static" ? "1" : (params.mode === "breathe" ? "2" : String(params.mode));
        api_write_node("rgb_controller", "light_mode", modeVal);
    }
    if (params.color && typeof params.color === "string" && params.color.indexOf("#") === 0) {
        var hex = params.color.replace("#", "");
        if (hex.length === 6) {
            var r = parseInt(hex.substring(0, 2), 16);
            var g = parseInt(hex.substring(2, 4), 16);
            var b = parseInt(hex.substring(4, 6), 16);
            api_write_node("rgb_controller", "red_level", String(r));
            api_write_node("rgb_controller", "green_level", String(g));
            api_write_node("rgb_controller", "blue_level", String(b));
        }
    } else {
        if (params.r !== undefined) api_write_node("rgb_controller", "red_level", String(params.r));
        if (params.g !== undefined) api_write_node("rgb_controller", "green_level", String(params.g));
        if (params.b !== undefined) api_write_node("rgb_controller", "blue_level", String(params.b));
    }
} catch (e) {
    api_log("[RGB CMD ERROR] " + e.toString() + "\\n");
}
"""

    @classmethod
    def get_camera_fault_js(cls, device_id: str = "camera-01", camera_ip: str = "192.168.4.120") -> str:
        return f"""// Camera Connectivity Fault Diagnostic Check (SCMP Standard)
try {{
    var pingRes = api_sys_exec("ping -c 2 -W 2 {camera_ip} >/dev/null 2>&1 && echo OK || echo FAIL");
    if (pingRes && pingRes.indexOf("FAIL") !== -1) {{
        var alert = {{
            deviceType: "camera",
            deviceId: "{device_id}",
            status: "offline",
            target_ip: "{camera_ip}",
            faultCode: "ERR_CAM_TIMEOUT",
            faultDescription: "Camera ICMP ping check timeout",
            timestamp: new Date().toISOString()
        }};
        api_out(api_event, JSON.stringify(alert));
    }}
}} catch (e) {{
    api_log("[CAM CHECK ERROR] " + e.toString() + "\\n");
}}
"""

    @classmethod
    def get_screen_fault_js(cls, device_id: str = "screen-01", screen_ip: str = "192.168.4.125") -> str:
        return f"""// LED Screen Connectivity Fault Diagnostic Check (SCMP Standard)
try {{
    var pingRes = api_sys_exec("ping -c 2 -W 2 {screen_ip} >/dev/null 2>&1 && echo OK || echo FAIL");
    if (pingRes && pingRes.indexOf("FAIL") !== -1) {{
        var alert = {{
            deviceType: "screen",
            deviceId: "{device_id}",
            status: "offline",
            target_ip: "{screen_ip}",
            faultCode: "ERR_SCREEN_TIMEOUT",
            faultDescription: "LED Screen ICMP ping check timeout",
            timestamp: new Date().toISOString()
        }};
        api_out(api_event, JSON.stringify(alert));
    }}
}} catch (e) {{
    api_log("[SCREEN CHECK ERROR] " + e.toString() + "\\n");
}}
"""

    @classmethod
    def build_standard_scripts(
        cls,
        pole_id: str = "P001",
        site_id: str = "default-site",
        screen_ip: str = "192.168.4.125",
        camera_ip: str = "192.168.4.120",
        env_device_id: str = "env-01",
        lamp_device_id: str = "lamp-01",
        rgb_device_id: str = "rgb-01",
        camera_device_id: str = "camera-01",
        screen_device_id: str = "screen-01",
        gw_device_id: str = "gw-01",
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Builds standardized upstream and downstream scripts for a pole.
        All MQTT topic patterns strictly adhere to SCMP Architecture:
          scmp/v1/{siteId}/{poleCode}/{deviceType}/{deviceId}/{direction}[/{action}]

        Returns: (script_up, script_down)
        """
        script_up = [
            {
                "script_id": "EnvTelemetry",
                "ds": "periodic_report",
                "event": build_device_topic(site_id, pole_id, "env", env_device_id, "telemetry"),
                "param": "1",
                "cycle": 10,
                "code": cls._b64(cls.get_env_telemetry_js(device_id=env_device_id))
            },
            {
                "script_id": "PoleIoTelemetry",
                "ds": "periodic_report",
                "event": build_device_topic(site_id, pole_id, "gateway", gw_device_id, "status"),
                "param": "1",
                "cycle": 15,
                "code": cls._b64(cls.get_io_telemetry_js(device_id=gw_device_id))
            },
            {
                "script_id": "RgbTelemetry",
                "ds": "periodic_report",
                "event": build_device_topic(site_id, pole_id, "rgb", rgb_device_id, "telemetry"),
                "param": "1",
                "cycle": 10,
                "code": cls._b64(cls.get_rgb_telemetry_js(device_id=rgb_device_id))
            },
            {
                "script_id": "CameraFault",
                "ds": "periodic_report",
                "event": build_device_topic(site_id, pole_id, "camera", camera_device_id, "status"),
                "param": "0",
                "cycle": 30,
                "code": cls._b64(cls.get_camera_fault_js(device_id=camera_device_id, camera_ip=camera_ip))
            },
            {
                "script_id": "ScreenFault",
                "ds": "periodic_report",
                "event": build_device_topic(site_id, pole_id, "screen", screen_device_id, "status"),
                "param": "0",
                "cycle": 30,
                "code": cls._b64(cls.get_screen_fault_js(device_id=screen_device_id, screen_ip=screen_ip))
            }
        ]

        script_down = [
            {
                "script_id": "LampControl",
                "ds": "form_server",
                "event": build_device_topic(site_id, pole_id, "lamp", lamp_device_id, "cmd", "control"),
                "param": "0",
                "cycle": 0,
                "code": cls._b64(cls.get_lamp_control_js())
            },
            {
                "script_id": "RgbControl",
                "ds": "form_server",
                "event": build_device_topic(site_id, pole_id, "rgb", rgb_device_id, "cmd", "control"),
                "param": "0",
                "cycle": 0,
                "code": cls._b64(cls.get_rgb_control_js())
            }
        ]

        return script_up, script_down

    @classmethod
    def load_exact_scripts(
        cls,
        source: str = "testserver",
        pole_id: Optional[str] = None,
        site_id: Optional[str] = None
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Loads the exact, unmodified scripts directly from the gateway's
        'testserver' (24 upstream, 5 downstream) or 'test' (20 upstream, 5 downstream)
        uplinks, preserving exact script IDs, exact repetition, parameters, and code,
        aligned with SCMP Topic Architecture (scmp-backend/packages/common/src/topics/index.ts).
        """
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        filename = f"{source}_scripts.json" if source in ["testserver", "test"] else "testserver_scripts.json"
        filepath = os.path.join(base_dir, "templates", filename)

        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Template not found: {filepath}")

        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        script_up = copy.deepcopy(data.get("script_up", []))
        script_down = copy.deepcopy(data.get("script_down", []))

        # Dynamic replacement if specific site_id or pole_id is configured
        default_site = "5efa910f-8e17-4443-af76-8b0a674d23f5"
        default_pole = "Pole-CBD-3444"

        for s in script_up:
            if "event" in s and isinstance(s["event"], str):
                if site_id and site_id not in ["default-site", default_site]:
                    s["event"] = s["event"].replace(default_site, site_id)
                if pole_id and pole_id not in ["P001", default_pole]:
                    s["event"] = s["event"].replace(default_pole, pole_id).replace("P001", pole_id).replace("POLE-GW-01", pole_id)

        for s in script_down:
            if "event" in s and isinstance(s["event"], str):
                if site_id and site_id not in ["default-site", default_site]:
                    s["event"] = s["event"].replace(default_site, site_id).replace("36e3d400-e836-4452-9f66-44edec11bd7c", site_id)
                if pole_id and pole_id not in ["P001", default_pole]:
                    s["event"] = s["event"].replace(default_pole, pole_id).replace("Pole-CBD-3483", pole_id).replace("P001", pole_id)

        return script_up, script_down

