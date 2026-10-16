# Pro: Production City-Wide Edge Gateway Orchestration Platform

An enterprise-grade, declarative orchestration and data acquisition automation suite built specifically for **Four-Faith Industrial Smart Gateways** (`smtgw3`, OpenWrt, Libuhttpd) across up to **100+ edge gateways city-wide**.

---

## 1. Directory Structure

```text
pro/
├── __init__.py                     # Package entry & versioning
├── __main__.py                     # Module runner (`python -m pro`)
├── cli.py                          # Unified Production CLI
├── core/
│   ├── __init__.py
│   ├── client.py                   # High-performance JSON-RPC 2.0 API client
│   ├── ssh_client.py               # Dropbear Out-of-band SSH client (legacy ciphers)
│   ├── diff_engine.py              # Mathematical state drift engine (Δadd, Δupdate, Δremove)
│   └── validator.py                # Post-apply telemetry verifier & health gate
├── models/
│   ├── __init__.py
│   ├── gateway.py                  # Pydantic models for Gateways & Network
│   ├── device.py                   # Pydantic models for Downstream PLCs/Channels
│   └── datanode.py                 # Pydantic models for Modbus registers & scripts
├── storage/
│   ├── __init__.py
│   ├── backup_catalog.py           # Versioned snapshots & disaster recovery catalog
│   └── inventory_repo.py           # Ingestion for gateways.csv, devices.csv & profiles
├── engine/
│   ├── __init__.py
│   ├── worker_pool.py              # Async/ThreadPool concurrency (10-20 workers)
│   └── rollout.py                  # Canary pipeline, staged batches & auto-rollback
├── messaging/
│   ├── __init__.py
│   └── script_builder.py           # Standardized, de-duplicated Duktape JavaScript generator
└── templates/
    └── profiles/
        ├── rgb_controller_v1.json         # Modbus RTU RGB Luminaire & Strip Profile
        ├── enviromental_sensor_v1.json    # 20+ Tag Weather Station Profile
        ├── smartpole_io_v1.json           # Smart Pole Power & Relay Box Profile
        └── screen_controller_v1.json      # LED Screen Controller Profile
```

---

## 2. CLI Usage & Operational Commands

The platform can be run directly using `python -m pro` or `python pro/cli.py`.

### 1. Read-Only Deep Inspection (`inspect`)
Safely connects, performs a pre-flight snapshot, and audits downstream devices, registers, cloud uplinks, and live readings:
```bash
python -m pro --mode inspect --gateway 192.168.4.1
```

### 2. State Drift Calculation (`diff`)
Computes mathematical difference between declarative inventory (`inventory/devices.csv`) and live gateway NVRAM:
```bash
python -m pro --mode diff --gateway 192.168.4.1
```

### 3. Automated Configuration Snapshot (`backup`)
Extracts complete JSON snapshot of NVRAM, datanodes, uplinks, and scripts to `backups/`:
```bash
python -m pro --mode backup --inventory inventory/gateways.csv
```

### 4. Declarative Synchronization (`sync`)
Provisions target gateways with pre-flight linting, canary gating, and automated rollback:
```bash
# Dry run simulation (no gateway writes)
python -m pro --mode sync --canary 192.168.4.1 --dry-run

# Staged rollout across all gateways in batches of 20 with auto-rollback
python -m pro --mode sync --inventory inventory/gateways.csv --canary 192.168.4.1 --batch-size 20
```

### 5. Telemetry De-duplication & Messaging (`messaging`)
Consolidates redundant periodic scripts (18-24 per gateway) into unified upstream telemetry and downstream control topics as specified in `getway.md`:
```bash
# Preview proposed script consolidation (read-only)
python -m pro --mode messaging --gateway 192.168.4.1 --pole-id P001

# Apply consolidated de-duplicated scripts to gateway NVRAM
python -m pro --mode messaging --gateway 192.168.4.1 --pole-id P001 --apply
```

### 6. Atomic Disaster Recovery Rollback (`rollback`)
Restores gateway NVRAM to an exact prior snapshot:
```bash
python -m pro --mode rollback --gateway 192.168.4.1 --backup-file backups/GW-TARGET_192.168.4.1_20261012_094331_AUDIT_SNAPSHOT.json
```

---

## 3. Key Architectural Features

1. **Idempotent Reconciliation**: Minimal delta updates ensure that re-applying configurations never creates duplicate devices or unnecessary daemon restarts.
2. **Blast Radius Gating**: Rollout runs through Stage 0 (Lint) -> Stage 1 (Canary 192.168.4.1) -> Stage 2 (Batches of 20). If Canary verification fails, it rolls back automatically and halts.
3. **Out-of-Band SSH Fallback**: Built-in Dropbear SSH support with legacy cipher profiles (`diffie-hellman-group1-sha1`, `ssh-rsa`) for emergency uhttpd/daemon recovery.
4. **Zero-Duplication Telemetry**: Solves the MQTT flooding issue where 18-24 scripts emitted identical full sensor trees every 5s.
