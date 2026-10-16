# City-Wide Multi-Gateway Automated Data Acquisition & Provisioning Plan

## 1. Executive Summary & Project Context

This implementation plan details the end-to-end automation architecture for provisioning and synchronizing **data acquisition devices across up to 100+ edge gateways city-wide**.

Following live inspection of Gateway `192.168.4.1`, the gateway architecture and management protocols were identified:
- **Hardware & Platform**: Four-Faith Smart Industrial Gateway (`smtgw` engine, OpenWrt kernel, Libuhttpd).
- **Core Automation Protocol**: High-performance **JSON-RPC 2.0 API** (`POST http://<gateway_ip>/v1/rpc`) with session-based bearer authentication (`Authorization: <sid>`).
- **Secondary Shell Access**: Dropbear SSH (`port 22`, legacy cipher profile: `diffie-hellman-group1-sha1`, `ssh-rsa`, `hmac-sha1`).
- **Core Acquisition Subsystem**: The `smtgw` engine manages:
  1. **Communication Channels & Device List** (`smtgw_plc_list_get` / `set`): Ethernet devices (Modbus TCP), serial devices (`RS485-1`, `RS485-2` Modbus RTU).
  2. **Data Acquisition Nodes / Tag Register Maps** (`smtgw_plc_datanode_get` / `set`): Register addresses, data types (`u16`, `u32`, `float`), formulas, and polling intervals.
  3. **Cloud Uplink / Telemetry Dispatch** (`smtgw_ct_list_get` / `set`): MQTT endpoints, client IDs, and credentials.
  4. **Dynamic Application Engine** (`sys_apply`): Commits changes to flash memory and reloads acquisition daemons without requiring hard reboots.
  5. **Telemetry Smoke Test Engine** (`smtgw_node_status_get`): Live telemetry verification.

---

## 2. Technical Profile & Discovered Gateway Baseline

| Parameter | Discovered Production Value | Scaled City-Wide Target |
| :--- | :--- | :--- |
| **Gateway Model** | Four-Faith Industrial Smart Gateway | ~100 Gateways (city subnets / VPNs) |
| **Primary Automation Protocol** | HTTP JSON-RPC 2.0 (`/v1/rpc`) | Async HTTP Pool (10–20 concurrent workers) |
| **Default Username** | `Teamtech12!` | Secure `.env` / Central Vault |
| **Default Password** | `teamtech` | Secure `.env` / Central Vault |
| **Secondary Protocol** | Dropbear SSH 0.52 (Port 22) | Automated fallback / low-level diagnostics |
| **Downstream Protocols** | Modbus TCP (Ethernet), Modbus RTU (RS485), Smart Box | Automated tag import per device type |
| **Upstream Telemetry** | MQTT Client (`TRNS_PROTO_CUSTOM_MQTT`, Port 1883) | Automated broker & topic provisioning |

---

## 3. High-Level Automation Architecture

```mermaid
graph TD
    subgraph Central Station / Management Host
        INV["Inventory Engine<br/>gateways.csv & devices.csv"]
        ENG["Python Automation Engine<br/>(Async HTTP JSON-RPC Pool)"]
        VAL["Validation & Health Monitor"]
        REP["Audit & Deployment Report (Markdown/JSON)"]
    end

    subgraph City-Wide Four-Faith Gateways (Up to 100)
        GW1["Gateway 1<br/>192.168.4.1"]
        GW2["Gateway 2<br/>192.168.4.2"]
        GWN["Gateway N<br/>10.x.x.x (Up to 100)"]
    end

    subgraph Downstream Edge Devices & Sensors
        DEV1["Modbus TCP Devices<br/>(Sensors, Screen, Energy Meters)"]
        DEV2["RS485 Modbus RTU Devices<br/>(Environmental, CO2, PM1/10)"]
    end

    INV --> ENG
    ENG -- "POST /v1/rpc (Async Concurrency)" --> GW1
    ENG -- "POST /v1/rpc (Async Concurrency)" --> GW2
    ENG -- "POST /v1/rpc (Async Concurrency)" --> GWN

    GW1 --> DEV1
    GW1 --> DEV2

    GW1 -- "smtgw_node_status_get" --> VAL
    GW2 -- "smtgw_node_status_get" --> VAL
    GWN -- "smtgw_node_status_get" --> VAL
    VAL --> REP
```

---

## 4. Reverse-Engineered JSON-RPC 2.0 API Workflow

The automation engine communicates directly with the gateway's native API, removing all manual web form entry:

```
[1. POST login] -> Obtain 'sid'
       │
[2. POST smtgw_plc_list_get & backup] -> Save existing configuration backup
       │
[3. Match Device Inventory] -> Compute Delta (New/Updated device IPs, ports, slave IDs)
       │
[4. POST smtgw_plc_list_set] -> Bulk update device list
       │
[5. POST smtgw_plc_datanode_set] -> Bulk inject tag register maps (PM10, CO2, etc.)
       │
[6. POST smtgw_ct_list_set] -> Provision MQTT uplink broker & credentials
       │
[7. POST sys_apply] -> Commit changes to NVRAM & reload acquisition service
       │
[8. POST smtgw_plc_status_get & smtgw_node_status_get] -> Verify live telemetry
```

### Key API Schemas

#### A. Authentication (`login`)
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
*Response*:
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "sid": "bc134f32f2289a061b98f862340e02f0",
    "role": "admin"
  }
}
```

#### B. Bulk Device List Configuration (`smtgw_plc_list_set`)
Allows declaring all downstream devices (Ethernet Modbus TCP, Serial Modbus RTU, smart boxes) in one bulk array:
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "smtgw_plc_list_set",
  "params": [
    {
      "plc_id": "Screen",
      "chn_en": true,
      "channel": "ethernet",
      "ipaddr": "192.168.4.125",
      "port": 502,
      "devtyp": "PLC_MDBS_TCP",
      "manufacturer": "MFR_MODBUS",
      "devaddr_str": "1",
      "acq_intv": 500,
      "acqtimeout": 500
    },
    {
      "plc_id": "enviromental",
      "chn_en": true,
      "channel": "RS485-1",
      "ipaddr": "",
      "port": 0,
      "devtyp": "PLC_MDBS_RTU",
      "manufacturer": "MFR_MODBUS",
      "devaddr_str": "255",
      "acq_intv": 500,
      "acqtimeout": 1000
    }
  ]
}
```

#### C. Register & Tag Configuration (`smtgw_plc_datanode_set`)
Bulk assigns registers, data types, and scaling formulas to a device:
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "smtgw_plc_datanode_set",
  "params": {
    "plc_id": "enviromental",
    "default_cmd": [
      {
        "portid": "PM10",
        "rdwr": "rw",
        "datanum": 1,
        "datatype": "u16",
        "addrtype": "03(4X)",
        "startaddr": "8",
        "cal_type": "disabled",
        "formula": ""
      },
      {
        "portid": "CO2",
        "rdwr": "rw",
        "datanum": 1,
        "datatype": "u16",
        "addrtype": "03(4X)",
        "startaddr": "19",
        "cal_type": "cal",
        "formula": "${this}*10"
      }
    ]
  }
}
```

#### D. Commit & Apply (`sys_apply`)
Commits changes without interrupting active network routing:
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "sys_apply",
  "params": {}
}
```

#### E. Telemetry Verification (`smtgw_node_status_get`)
Validates that acquisition is actively reading values:
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "smtgw_node_status_get",
  "params": {}
}
```

---

## 5. Input Inventory Design (CSV / Excel / YAML)

To support up to 100 gateways and hundreds of downstream devices, the input data is decoupled into two clean tabular files:

### File 1: `gateways.csv`
Defines the management connection details for all 100 gateways:
```csv
gateway_id,ip_address,port,username,password,location,uplink_mqtt_broker,uplink_mqtt_port
GW-CITY-001,192.168.4.1,80,Teamtech12!,teamtech,Sector 4 North,192.168.4.124,1883
GW-CITY-002,192.168.5.1,80,Teamtech12!,teamtech,Sector 5 East,192.168.4.124,1883
...
```

### File 2: `devices.csv`
Defines downstream devices and their IP/Channel mappings per gateway:
```csv
gateway_id,plc_id,channel,device_type,target_ip,target_port,slave_id,interval_ms,tag_template
GW-CITY-001,Screen,ethernet,PLC_MDBS_TCP,192.168.4.125,502,1,500,screen_template
GW-CITY-001,enviromental,RS485-1,PLC_MDBS_RTU,,,255,1000,env_sensor_template
GW-CITY-002,WaterPump01,ethernet,PLC_MDBS_TCP,192.168.5.50,502,1,1000,pump_template
```

### File 3: Tag Templates (`config/tag_templates.json`)
Pre-packaged register profiles for standard devices (e.g. Environmental Sensor, Energy Meter, Screen) so tags don't have to be entered repeatedly.

---

## 6. Implementation Deliverables & Project Structure

The project codebase will be laid out as follows in `env/`:

```text
env/
├── implementation_plan.md          # Complete architectural specification
├── inventory/
│   ├── gateways.csv                # List of 100 gateways
│   └── devices.csv                 # Downstream device mappings
├── templates/
│   └── tag_library.json            # Reusable register & tag definitions
├── backups/                        # Automatic pre-update config backups
├── reports/                        # Timestamped execution & health reports
├── src/
│   ├── __init__.py
│   ├── gateway_client.py           # Four-Faith JSON-RPC API client
│   ├── inventory_loader.py         # CSV & template validator
│   ├── orchestrator.py             # Parallel multi-gateway sync engine
│   └── ssh_fallback.py             # OpenSSH legacy cipher fallback
├── sync_gateways.py                # Main CLI execution entrypoint
└── requirements.txt                # Python dependencies
```

---

## 7. Execution Phases & Milestones

| Phase | Milestone | Deliverable | Status |
| :--- | :--- | :--- | :--- |
| **Phase 1** | **Gateway Reverse-Engineering** | Identification of Four-Faith RPC API, credentials verification, live schema dump | **COMPLETED** |
| **Phase 2** | **Core API Client & Tag Importer** | `gateway_client.py` supporting login, backup, `plc_list_set`, `datanode_set`, `sys_apply` | Ready for build |
| **Phase 3** | **Inventory Parser & Templates** | `inventory_loader.py` supporting `gateways.csv`, `devices.csv`, and tag libraries | Ready for build |
| **Phase 4** | **Async Multi-Gateway Orchestrator** | `sync_gateways.py` running concurrent workers (10-20 at once) across 100 gateways | Ready for build |
| **Phase 5** | **Telemetry Verification & Audit Reporting** | Live reading check (`smtgw_node_status_get`) and Markdown deployment report | Ready for build |
| **Phase 6** | **Dry-Run & Field Rollout** | Execution against test gateway `192.168.4.1`, followed by staged city-wide rollout | Ready for test |

---

## 8. Safety, Rollback & Fault Tolerance

1. **Pre-flight Backups**: Before modifying any gateway, the engine queries `smtgw_plc_list_get`, `smtgw_plc_datanode_get`, and `smtgw_ct_list_get`, saving a JSON snapshot in `backups/<gateway_id>_<timestamp>.json`.
2. **Automatic Rollback**: If `sys_apply` returns an error or post-apply verification fails, the engine re-posts the previous backup state.
3. **Fail-Soft Isolation**: If gateway #14 is powered off or unreachable, it does not block the other 99 gateways. Unreachable gateways are logged in the failure summary table.
4. **Credential Security**: Credentials can be read from environment variables or a `.env` file rather than plain text.
