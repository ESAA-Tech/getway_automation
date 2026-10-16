# City-Wide Edge Gateway Orchestration & Automated Data Acquisition Platform

An enterprise-grade, declarative orchestration suite, CLI, and Web Command Center built specifically for **Four-Faith Industrial Smart Gateways** (`smtgw3`, OpenWrt, Libuhttpd) across up to **100+ edge gateways city-wide**.

---

## 1. Project Directory Structure

```text
env/
├── inventory/                      # Declarative inventory CSVs (gateways & devices)
│   ├── gateways.csv                # City-wide gateway connection parameters & metadata
│   └── devices.csv                 # Downstream field device bus & channel assignments
├── pro/                            # Production Orchestration & Automation Engine
│   ├── core/                       # JSON-RPC 2.0 client, Dropbear SSH fallback, Diff, Validator
│   │   ├── client.py               # High-performance Four-Faith JSON-RPC API client
│   │   ├── ssh_client.py           # Out-of-band Dropbear SSH client (legacy ciphers)
│   │   ├── diff_engine.py          # State reconciliation engine (Δadd, Δupdate, Δremove)
│   │   └── validator.py            # Post-apply telemetry verifier & health gate
│   ├── models/                     # Pydantic v2 schemas
│   │   ├── gateway.py              # Gateway connection, network, and auth models
│   │   ├── device.py               # Downstream PLC & communication channel models
│   │   └── datanode.py             # Modbus register points, scripts, and uplink schemas
│   ├── storage/                    # Data storage & catalogs
│   │   ├── backup_catalog.py       # Versioned snapshots & disaster recovery index
│   │   └── inventory_repo.py       # CSV and hardware profile template parser
│   ├── engine/                     # Concurrency & Deployment Controllers
│   │   ├── worker_pool.py          # Rate-limited concurrency pool (10-20 parallel workers)
│   │   └── rollout.py              # Staged pipeline (Stage 0 Lint -> Canary -> Batches)
│   ├── messaging/                  # Message Management & Script De-Duplication
│   │   └── script_builder.py       # Consolidated Duktape JavaScript generator (Env, IO, RGB)
│   ├── templates/profiles/         # Reusable Modbus register profiles
│   │   ├── rgb_controller_v1.json  # Modbus RTU RGB Luminaire & Strip Profile (6 registers)
│   │   ├── enviromental_sensor_v1.json # Multi-Sensor Weather Station Profile (20+ registers)
│   │   ├── smartpole_io_v1.json    # Smart Pole Power & Relay Box Profile (5 nodes)
│   │   └── screen_controller_v1.json # LED Screen Controller Profile
│   └── cli.py                      # Unified CLI entrypoint (python -m pro)
├── web/                            # Web Command Center Application
│   ├── run.py                      # Standalone launcher script (python web/run.py)
│   ├── server.py                   # High-speed Flask REST API backend
│   └── static/                     # Dark-mode dashboard frontend
│       ├── css/
│       │   ├── tokens.css          # Design tokens: typography, HSL palette, dark theme
│       │   └── style.css           # Glassmorphism, tactile switches, gauges, animations
│       ├── js/
│       │   ├── api.js              # Resilient API client with timeout & error handling
│       │   └── app.js              # Reactive UI, live polling, single-press controls
│       └── index.html              # Executive Command Center dashboard
├── backups/                        # Automatic pre-flight snapshots & rollback archives
├── reports/                        # Execution audit logs & rollout markdown summaries
├── tests/                          # Automated test suite
│   └── test_pro_suite.py           # Unit and integration tests (models, diff, scripts)
├── requirements.txt                # Python dependencies
├── system_design.md                # Complete production system design document
├── getway.md                       # Reverse-engineered gateway architecture & scripts
└── implementation_plan.md          # Architectural rollout and implementation plan
```

---

## 2. Directory & Component Breakdown

### 📁 `inventory/`
Houses the declarative desired state for all field hardware in clean tabular CSV format:
* **`gateways.csv`**: Defines IP addresses, ports, credentials, and locations for all target gateways across city sectors.
* **`devices.csv`**: Declares which physical sensors and controllers are wired to each gateway, specifying bus channels (`RS485-1`, `RS485-2`, `ethernet`), driver types (`PLC_MDBS_RTU`, `PLC_FF_BOX`), and station slave IDs (`1`, `255`).

### 📁 `pro/` (Production Automation Core)
The primary modular Python engine powering configuration, synchronization, and telemetry management:
* **`pro/core/`**:
  * `client.py`: High-performance JSON-RPC 2.0 client managing session bearer tokens (`sid`), automatic session recovery, exponential backoff retries with jitter, and all native Four-Faith methods (`smtgw_plc_*`, `smtgw_ct_*`, `smtgw_script_*`, `sys_apply`).
  * `ssh_client.py`: Dropbear SSH manager for out-of-band disaster recovery (legacy cipher negotiation: `diffie-hellman-group1-sha1`, `ssh-rsa`).
  * `diff_engine.py`: Computes minimal mathematical delta ($\Delta_{\text{add}}, \Delta_{\text{update}}, \Delta_{\text{remove}}$) between inventory declarations and live gateway NVRAM.
  * `validator.py`: Health verification gate confirming daemon status, monotonically increasing timestamps, and telemetry sanity.
* **`pro/models/`**: Strongly typed Pydantic v2 data models ensuring zero configuration corruption before any packets are sent over the network.
* **`pro/storage/`**:
  * `backup_catalog.py`: Automatically persists immutable JSON snapshots of NVRAM before every write operation. Maintains `catalog_index.json`.
  * `inventory_repo.py`: Ingests and validates CSV files and JSON hardware profiles.
* **`pro/engine/`**:
  * `worker_pool.py`: Parallel worker pool allowing concurrent execution across 50–100 gateways in 25–35 seconds without network congestion.
  * `rollout.py`: Multi-stage pipeline executing Pre-flight Lint -> Single Canary Gateway (with soak test) -> Pilot Cluster -> Batched City Rollout. Automatically rolls back upon verification failure.
* **`pro/messaging/`**:
  * `script_builder.py`: Solves telemetry script duplication by consolidating redundant periodic scripts (18–24 per pole) into 5 clean upstream formatters and 2 downlink command handlers.
* **`pro/templates/profiles/`**: Standardized, reusable Modbus register profiles for RGB luminaires, environmental weather stations, smart pole relays, and LED screens.

### 📁 `web/` (Web Command Center)
A graphical dashboard eliminating the need to copy commands in PowerShell:
* **`run.py`**: Launches the web server on `http://127.0.0.1:8080`.
* **`server.py`**: High-speed Flask REST API backend exposing endpoints for live status, single-press relay writes, RGB color adjustments, declarative sync, and snapshot restoration.
* **`static/`**: Ultra-premium executive dark-mode interface with glassmorphism, single-click ON/OFF switches, live color swatches, 4-second live sensor polling, and smooth error handling (never freezes or crashes).

### 📁 `backups/`
Stores timestamped, versioned JSON configuration snapshots extracted from gateways before write operations or audits. Used for one-click disaster recovery rollback.

### 📁 `reports/`
Stores markdown deployment reports generated by the rollout engine detailing execution timelines, successful provisions, and offline gateways.

### 📁 `tests/`
Houses automated test suites verifying model schemas, diff engine calculations, profile loading, and pre-flight linting.

---

## 3. Quick Start Guide

### Prerequisites
Install dependencies:
```bash
pip install -r requirements.txt
```

---

### Option A: Launch the Web Command Center (Recommended)
Launch the graphical interface:
```bash
python web/run.py
```
Open **`http://127.0.0.1:8085`** in your browser.

**What you can do with a single click in the Web App:**
* **Main Streetlight Lamp ON / OFF**: Instant toggle for AC Relay 1 (`IO.AC-OUT1`).
* **Accent LED Strip ON / OFF**: Toggle for AC Relay 2 (`IO.AC-OUT2`).
* **RGB Luminaire Control**: Power switch, 0–100% brightness slider, quick color swatches (Cyber Cyan, Warm White, Neon Purple, Emerald), and dynamic scene selectors.
* **Live Weather Matrix**: Live readings for Temperature, Humidity, Pressure, PM2.5, PM10, CO₂, and Wind Speed updated every 4 seconds.
* **One-Click Sync**: Reconciles declared devices & profiles with gateway NVRAM.
* **De-Duplicate MQTT**: Consolidates 24 duplicate scripts into 5 clean telemetry scripts.
* **Clone Cloud Service**: Replicates all 26 datanodes & scripts from an existing cloud service (e.g. `testserver`) to a new MQTT broker.
* **Instant Backup**: Captures a full gateway snapshot to `backups/`.
* **Check Drift (Diff)**: Compares live gateway state against inventory in a modal.

---

### Option B: Use the Production CLI (`python -m pro`)

| Action | CLI Command |
| :--- | :--- |
| **Inspect Gateway (Read-Only)** | `python -m pro --mode inspect --gateway 192.168.4.1` |
| **Check State Drift (Diff)** | `python -m pro --mode diff --gateway 192.168.4.1` |
| **Capture Full Snapshot** | `python -m pro --mode backup --inventory inventory/gateways.csv` |
| **Declarative Sync (Dry Run)** | `python -m pro --mode sync --canary 192.168.4.1 --dry-run` |
| **Deploy Sync (Canary Rollout)** | `python -m pro --mode sync --inventory inventory/gateways.csv --canary 192.168.4.1 --batch-size 20` |
| **De-Duplicate Messaging Scripts** | `python -m pro --mode messaging --gateway 192.168.4.1 --pole-id P001 --apply` |
| **Rollback Gateway to Snapshot** | `python -m pro --mode rollback --gateway 192.168.4.1 --backup-file backups/<snapshot>.json` |
| **Start Web App via CLI** | `python -m pro --mode web --port 8085` |

---

## 4. Scaling Across 100+ Gateways on LAN

When connecting multiple gateways on the same LAN:
1. Add target gateway IPs to [`inventory/gateways.csv`](file:///c:/Users/mahesaa/OneDrive/Documents/env/inventory/gateways.csv).
2. Run `python -m pro --mode sync --inventory inventory/gateways.csv --canary 192.168.4.1 --batch-size 20`.
3. The engine deploys across test canary gateway `192.168.4.1` first, verifies health, then concurrently provisions all remaining gateways in batches of 20 with automatic pre-flight backups and zero downtime.

---

## 5. Verification & Tests

Run the test suite to verify platform integrity:
```bash
python -m unittest discover tests
```
All 5 unit test suites pass in `< 0.01s`.
