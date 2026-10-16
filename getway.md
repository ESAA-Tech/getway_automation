# Edge Gateway Architecture & Message Management Specification

> **Target Gateway:** Four-Faith Industrial Smart Gateway (`192.168.4.1`)  
> **Firmware Subsystem:** `smtgw3` (Edge Data Acquisition & Cloud Transmission Engine)  
> **Control Plane:** JSON-RPC 2.0 API (`http://192.168.4.1/v1/rpc`)  
> **Default Admin Credential:** `Teamtech12!`  

---

## 1. Executive Summary & Root Cause Analysis

### 1.1 Problem Statement: Telemetry Duplication
In the current gateway configuration, **18 to 24 separate scripts** were created in the Message Management subsystem (`msgManage` / `smtgw_script_*`) for individual sensor tags (`Temperature`, `Humidity`, `Pressure`, `PM2.5`, `PM10`, `CO2`, `SO2`, `NO2`, `CO`, `O3`, `Wind speed`, `Rainfall`, etc.).

Every single one of these scripts had:
- **Trigger Type (`ds`):** `periodic_report`
- **Execution Interval (`cycle`):** `5` seconds
- **Topic (`event`):** `aacra/smartpole/P001/env/telemetry`
- **Script Logic:**
  ```javascript
  var data = JSON.parse(api_data);
  var env = data.subdev && data.subdev.enviromental;
  // ...
  api_out(api_event, api_data);
  ```

### 1.2 The Duplication Mechanism
In the Four-Faith gateway execution runtime:
1. `api_data` is **not** a single sensor register. It is the **complete collected datanode tree** of all active sub-devices on the gateway (`subdev.enviromental`, `subdev.IO`, `subdev.Screen`, `subdev.rgb_controller`).
2. When multiple scripts share the `periodic_report` trigger and invoke `api_out(api_event, api_data)` to the same topic `aacra/smartpole/P001/env/telemetry`, **each script triggers independently every 5 seconds**.
3. **Consequence:** 18 identical copies of the full JSON payload were published to the MQTT broker every 5 seconds (over **216 duplicate messages per minute** for a single pole), causing network congestion, broker queue bloat, database write lock contention, and false alarm flooding.

### 1.3 Architectural Solution
- **Consolidation:** Replace the 18 redundant scripts with **one single consolidated upstream telemetry script** (`EnvTelemetry`) that checks sensor health and emits the clean telemetry JSON once per polling cycle.
- **Dedicated Fault Monitors:** Separate physical checks (`camera_fault`, `screen_fault`) into individual, rate-limited diagnostics scripts (30s cycle) using lock files to prevent CPU thrashing.
- **Unified Downlink Command Dispatching:** Streamline downstream scripts (`script_down`) into clear device targets (Luminaire, LED strip, Screen, Modbus RGB) with standardized topic naming, removing obsolete test subscriptions (`subscribe`, `new`, `testsub`).

---

## 2. Gateway Subsystems & Core Concepts

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       Four-Faith Edge Gateway (192.168.4.1)                  │
├─────────────────────────────────────────────────────────────────────────────┤
│ 1. Downstream Devices (PLC Engine - smtgw_plc_*)                            │
│    - Enviromental Sensor (RS485-1, Modbus RTU Slave 255, 9600 8N1)          │
│    - RGB Controller     (RS485-2, Modbus RTU Slave 1, 9600 8N1)            │
│    - Smart Pole IO Box  (Internal Ethernet, AC relays OUT1/OUT2/OUT3)      │
│    - Modbus TCP Screen  (Ethernet 192.168.4.125)                            │
├─────────────────────────────────────────────────────────────────────────────┤
│ 2. Datanode Acquisition Matrix (smtgw_plc_datanode_*)                       │
│    - Registers, data types (u16, f32), addresses (03(4X)), scaling formulas │
├─────────────────────────────────────────────────────────────────────────────┤
│ 3. Cloud Transmission Uplinks (smtgw_ct_*)                                  │
│    - testserver: 192.168.4.124:1883 (Active SCMP MQTT Broker)               │
│    - test:       192.168.4.109:1883 (Secondary / Mosquitto Test Broker)     │
├─────────────────────────────────────────────────────────────────────────────┤
│ 4. Message Management & Transformation Engine (smtgw_script_*)              │
│    - script_up:   Periodic & Change Telemetry Formatters (api_out)          │
│    - script_down: Cloud Command Subscribers (api_write_node)                │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.1 The Gateway Script Runtime Sandbox
The gateway runs an embedded JavaScript (Duktape/V8 subset) engine with specific built-in globals:

| Global Symbol | Description | Scope |
| :--- | :--- | :--- |
| `api_data` | Stringified JSON of current collected datanodes or incoming MQTT command payload | Read-only input |
| `api_event` | Configured topic name (`event` property of the script definition) | Read-only input |
| `api_out(topic, payload)` | Publishes an MQTT message to the specified topic | Uplink publish |
| `api_write_node(plc_id, tag_id, value)` | Writes a value directly to a downstream device register / IO node | Downlink control |
| `api_sys_exec(cmd)` | Executes a Linux shell command on the gateway OS (e.g. `mkdir`, `ping`, `rm`) | Diagnostics |
| `api_log(msg)` | Outputs log lines to the gateway's script debug buffer (`smtgw_script_log_get`) | Diagnostics |
| `global.set(key, val)` / `global.get(key)` | Persists in-memory state across execution cycles | State tracking |

---

## 3. Standardized SCMP Topic Naming Hierarchy

To maintain seamless data routing between edge gateways and the SCMP system backend (`scmp-backend/packages/common/src/topics/index.ts`), all MQTT topics follow a strict hierarchy based on Site Identifier (`{site_id}`, default: `default-site`), Pole Identifier (`{pole_id}` / `{pole_code}`, e.g., `P001`), Device Type, and Device ID:

```
Pattern: scmp/v1/{siteId}/{poleCode}/{deviceType}/{deviceId}/{direction}[/{action}]
```

### 3.1 Upstream Telemetry & Status (`script_up`)

| Subsystem / Purpose | Standardized Topic Pattern | Trigger (`ds`) | Cycle | QoS |
| :--- | :--- | :--- | :--- | :--- |
| **Environmental Telemetry** | `scmp/v1/{site_id}/{pole_id}/env/env-01/telemetry` | `periodic_report` | 10s | 1 |
| **Gateway & IO Power Status** | `scmp/v1/{site_id}/{pole_id}/gateway/gw-01/status` | `change_report` / `periodic_report` | 15s | 1 |
| **RGB Controller Telemetry** | `scmp/v1/{site_id}/{pole_id}/rgb/rgb-01/telemetry` | `periodic_report` | 10s | 1 |
| **Camera Connectivity Status** | `scmp/v1/{site_id}/{pole_id}/camera/camera-01/status` | `periodic_report` | 30s | 0 |
| **LED Screen Connectivity Status** | `scmp/v1/{site_id}/{pole_id}/screen/screen-01/status` | `periodic_report` | 30s | 0 |

### 3.2 Downstream Control Commands (`script_down`)

| Subsystem | Standardized Command Topic | Target Hardware / Node | Supported Payloads |
| :--- | :--- | :--- | :--- |
| **Main Luminaire (Lamp)** | `scmp/v1/{site_id}/{pole_id}/lamp/lamp-01/cmd/control` | IO `AC-OUT1` & `smart_lightpole_en` | SCMP `MqttEnvelope` (`data.params.switchStatus`) or legacy `{"state": 1}` |
| **RGB Modbus Controller** | `scmp/v1/{site_id}/{pole_id}/rgb/rgb-01/cmd/control` | Modbus RTU Station 1 (`rgb_controller`) | SCMP `MqttEnvelope` (`data.params.color`, `brightness`) or `{"power": 1, ...}` |

---

## 4. De-duplicated Script Implementations

### 4.1 Consolidated Environmental Telemetry (`EnvTelemetry`)
- **Script ID:** `EnvTelemetry`
- **Topic:** `scmp/v1/{site_id}/{pole_id}/env/env-01/telemetry`
- **Trigger:** `periodic_report`, **Cycle:** `10` seconds, **QoS:** `1`

```javascript
// Consolidated Environmental Telemetry Formatter (De-duplicated)
try {
    var raw = JSON.parse(api_data);
    var env = raw.subdev && raw.subdev.enviromental;
    var gateway_sn = raw.sn || "GW-SINGLE";
    var ctimeStr = (env && env.ctime) ? String(env.ctime).trim() : "";

    // Sensor health & offline validation
    var isOffline = !env || ctimeStr === "" || ctimeStr.indexOf("1970-01-01") === 0;

    if (isOffline) {
        var faultPayload = JSON.stringify({
            gateway_sn: gateway_sn,
            device_id: "enviromental",
            status: "OFFLINE",
            timestamp: new Date().toISOString(),
            error: "Sensor acquisition timeout or disconnected"
        });
        api_log("[ENV] Sensor OFFLINE. Publishing alert.\n");
        api_out(api_event, faultPayload);
    } else {
        // Build clean, typed telemetry message
        var telemetry = {
            gateway_sn: gateway_sn,
            device_id: "enviromental",
            status: "ONLINE",
            timestamp: env.ctime || new Date().toISOString(),
            metrics: {
                temperature: Number(env.Temperature || 0),
                humidity: Number(env.Humidity || 0),
                pressure: Number(env.pressure || 0),
                pm1: Number(env.PM1 || 0),
                pm2_5: Number(env["PM2.5"] || 0),
                pm10: Number(env.PM10 || 0),
                tsp: Number(env.Tsp || 0),
                co2: Number(env.CO2 || 0),
                co: Number(env.CO || 0),
                so2: Number(env.SO2 || 0),
                no2: Number(env.NO2 || 0),
                o3: Number(env.O3 || 0),
                h2s_tvoc: Number(env.H2s_tvoc || 0),
                wind_speed: Number(env.Wind_speed || 0),
                wind_direction: Number(env.Wind_direction || 0),
                rainfall: Number(env.Rainfall || 0),
                illuminance: Number(env.Illuminance || 0),
                radiation: Number(env.Radiation || 0),
                uv_index: Number(env.Uv_index || 0),
                negative_o2_ions: Number(env.neg_oxygen_ions || 0)
            }
        };
        api_log("[ENV] Publishing consolidated telemetry.\n");
        api_out(api_event, JSON.stringify(telemetry));
    }
} catch (e) {
    api_log("[ENV ERROR] " + e.toString() + "\n");
}
```

### 4.2 Consolidated Gateway & IO Power Status (`PoleIoTelemetry`)
- **Script ID:** `PoleIoTelemetry`
- **Topic:** `scmp/v1/{site_id}/{pole_id}/gateway/gw-01/status`
- **Trigger:** `periodic_report`, **Cycle:** `15` seconds, **QoS:** `1`

```javascript
try {
    var raw = JSON.parse(api_data);
    var io = raw.subdev && raw.subdev.IO;
    var gateway_sn = raw.sn || "GW-SINGLE";

    if (io) {
        var ioPayload = {
            deviceType: "gateway",
            deviceId: "gw-01",
            gateway_sn: gateway_sn,
            status: "online",
            timestamp: io.ctime || new Date().toISOString(),
            metrics: {
                ac_out1_lamp: Number(io["AC-OUT1"] || 0),
                ac_out2_strip: Number(io["AC-OUT2"] || 0),
                ac_out3_led: Number(io["AC-OUT3"] || 0),
                system_power_en: Number(io.smart_lightpole_en || 0),
                ac_dc_switch: Number(io.ac_dc_switch || 0)
            }
        };
        api_out(api_event, JSON.stringify(ioPayload));
    }
} catch (e) {
    api_log("[IO ERROR] " + e.toString() + "\n");
}
```

### 4.3 RGB Modbus Controller Telemetry (`RgbTelemetry`)
- **Script ID:** `RgbTelemetry`
- **Topic:** `scmp/v1/{site_id}/{pole_id}/rgb/rgb-01/telemetry`
- **Trigger:** `periodic_report`, **Cycle:** `10` seconds, **QoS:** `1`

```javascript
try {
    var raw = JSON.parse(api_data);
    var rgb = raw.subdev && raw.subdev.rgb_controller;
    var gateway_sn = raw.sn || "GW-SINGLE";

    if (rgb && rgb.power_state !== undefined && rgb.power_state !== "null") {
        var rgbPayload = {
            deviceType: "rgb",
            deviceId: "rgb-01",
            gateway_sn: gateway_sn,
            status: "online",
            timestamp: rgb.ctime || new Date().toISOString(),
            metrics: {
                power: Number(rgb.power_state || 0),
                brightness: Number(rgb.brightness || 0),
                mode: Number(rgb.light_mode || 0),
                red: Number(rgb.red_level || 0),
                green: Number(rgb.green_level || 0),
                blue: Number(rgb.blue_level || 0)
            }
        };
        api_out(api_event, JSON.stringify(rgbPayload));
    }
} catch (e) {
    api_log("[RGB ERROR] " + e.toString() + "\n");
}
```

### 4.4 Unified Downlink Lamp & IO Command Handler (`LampControl`)
- **Script ID:** `LampControl`
- **Topic:** `scmp/v1/{site_id}/{pole_id}/lamp/lamp-01/cmd/control`
- **Trigger:** `form_server`, **QoS:** `0`

```javascript
api_log("=== SCMP Lamp Command Received ===\n" + api_data + "\n");
try {
    var payload = api_data.replace(/'/g, '"');
    payload = payload.replace(/([{,]\s*)([a-zA-Z0-9_\-]+)\s*:/g, '$1"$2":');
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

    api_log("Lamp command resolved: " + (val === "1" ? "ON" : "OFF") + "\n");
    api_write_node("IO", "AC-OUT1", val);
    api_write_node("IO", "smart_lightpole_en", "1");
    api_write_node("IO", "ac_dc_switch", "1");
} catch (e) {
    api_log("[CMD ERROR] " + e.toString() + "\n");
}
```

### 4.5 Downlink Modbus RGB Controller Handler (`RgbControl`)
- **Script ID:** `RgbControl`
- **Topic:** `scmp/v1/{site_id}/{pole_id}/rgb/rgb-01/cmd/control`
- **Trigger:** `form_server`, **QoS:** `0`

```javascript
api_log("=== RGB Controller Command Received ===\n" + api_data + "\n");
try {
    var payload = api_data.replace(/'/g, '"');
    payload = payload.replace(/([{,]\s*)([a-zA-Z0-9_\-]+)\s*:/g, '$1"$2":');
    var cmd = JSON.parse(payload);

    if (cmd.power !== undefined) api_write_node("rgb_controller", "power_state", String(cmd.power));
    if (cmd.brightness !== undefined) api_write_node("rgb_controller", "brightness", String(cmd.brightness));
    if (cmd.mode !== undefined) api_write_node("rgb_controller", "light_mode", String(cmd.mode));
    if (cmd.r !== undefined) api_write_node("rgb_controller", "red_level", String(cmd.r));
    if (cmd.g !== undefined) api_write_node("rgb_controller", "green_level", String(cmd.g));
    if (cmd.b !== undefined) api_write_node("rgb_controller", "blue_level", String(cmd.b));
} catch (e) {
    api_log("[RGB CMD ERROR] " + e.toString() + "\n");
}
```

---

## 5. JSON-RPC 2.0 API Specification

All gateway interactions are executed against endpoint `POST http://192.168.4.1/v1/rpc` with `Authorization: <sid>` header.

### 5.1 Authentication (`login`)
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "login",
  "params": {
    "username": "Teamtech12!",
    "password": "teamtech"
  }
}
```
**Response:**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "sid": "4a7d5f66cac1367f75f617030063b4be",
    "username": "Teamtech12!",
    "role": "admin"
  }
}
```

### 5.2 Cloud Service Uplink Query & Set (`smtgw_ct_list_*`)
- **Get:** `{"method": "smtgw_ct_list_get", "params": {}}`
- **Set:** `{"method": "smtgw_ct_list_set", "params": [<uplink_object_1>, ...]}`
- **Uplink Schema:**
  ```json
  {
    "ct_id": "testserver",
    "proto": "TRNS_PROTO_CUSTOM_MQTT",
    "svr_en": true,
    "url": "192.168.4.124",
    "srvport": 1883,
    "mqtt_clientid": "scmp-pole-POLE-GW-01",
    "mqtt_username": "gw-pole-test",
    "mqtt_pswd": "gateway_secret",
    "mqtt_keepalive": 60,
    "mqtt_timeout": 10,
    "periodic_time": 10,
    "clear_data": true,
    "store_mode": "memory",
    "datastore": false
  }
  ```

### 5.3 Datanode Cloud Binding (`smtgw_ct_datanode_*`)
- **Get:** `{"method": "smtgw_ct_datanode_get", "params": {"ct_id": "testserver"}}`
- **Set:**
  ```json
  {
    "method": "smtgw_ct_datanode_set",
    "params": {
      "ct_id": "testserver",
      "ct_datanode": [
        {"plc_id": "enviromental", "portid": "Temperature", "change_report": false},
        {"plc_id": "IO", "portid": "AC-OUT1", "change_report": false},
        {"plc_id": "rgb_controller", "portid": "power_state", "change_report": false}
      ]
    }
  }
  ```

### 5.4 Message Scripts Set (`smtgw_script_set`)
```json
{
  "method": "smtgw_script_set",
  "params": {
    "ct_id": "testserver",
    "script_up": [
      {
        "script_id": "EnvTelemetry",
        "ds": "periodic_report",
        "event": "scmp/v1/default-site/P001/env/env-01/telemetry",
        "param": "1",
        "cycle": 10,
        "code": "<Base64_Encoded_JavaScript>"
      }
    ],
    "script_down": [
      {
        "script_id": "LampControl",
        "ds": "form_server",
        "event": "scmp/v1/default-site/P001/lamp/lamp-01/cmd/control",
        "param": "0",
        "cycle": 0,
        "code": "<Base64_Encoded_JavaScript>"
      }
    ]
  }
}
```

### 5.5 NVRAM Commit & Service Reload (`sys_apply`)
```json
{
  "method": "sys_apply",
  "params": {
    "services": ["smtgw3"]
  }
}
```

---

## 6. Safe Provisioning Workflow & Tooling

The included tool [manage_gateway_messaging.py](file:///c:/Users/mahesaa/OneDrive/Documents/env/manage_gateway_messaging.py) automates the entire migration safely.

### 6.1 Safety Measures
1. **Pre-flight Snapshot:** A full NVRAM snapshot of all devices, datanodes, uplinks, and active scripts is backed up to `backups/PRE_MSG_RECON_<timestamp>.json` before any write.
2. **Read-Only / Dry-Run Mode:** Running with `--dry-run` or `--inspect` evaluates state drift and prints the exact diff without modifying the gateway.
3. **Atomic Service Apply:** Calls `sys_apply(["smtgw3"])` only after both `ct_datanode_set` and `script_set` successfully validate.

### 6.2 Running the Tool
```bash
# 1. Inspect current active scripts and detect duplicate topics
python manage_gateway_messaging.py --host 192.168.4.1 --inspect

# 2. Perform a dry-run showing proposed de-duplication diff
python manage_gateway_messaging.py --host 192.168.4.1 --pole-id P001 --dry-run

# 3. Apply the clean, de-duplicated configuration
python manage_gateway_messaging.py --host 192.168.4.1 --pole-id P001 --apply
```
