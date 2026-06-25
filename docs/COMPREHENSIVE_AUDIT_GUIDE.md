# TestPilot Audit Guide: Comprehensive Reference Document

> **Document Purpose**: This guide provides a complete overview of the TestPilot audit framework, project structure, calibration methodology, and report standards for writing audit documentation.
>
> **Last Updated**: 2026-03-20  
> **Status**: Draft for guide creation  
> **Reference Materials**: `docs/audit-todo.md`, `docs/plan.md`, `AGENTS.md`, `plugins/wifi_llapi/reports/audit-report-*.md`

---

## Executive Summary

TestPilot is a YAML-driven deterministic WiFi test framework focused on **workbook-aligned calibration** of WiFi Local Link API (LLAPI) cases. The audit process validates each test case against live hardware evidence while maintaining strict alignment with the acceptance baseline workbook (`0310-BGW720-300_LLAPI_Test_Report.xlsx`).

**Current Status (as of 2026-03-20)**:
- **Calibrated cases**: 370 / 415 official cases (89%)
- **Remaining**: 186 cases under sequential calibration
- **Active blockers**: 3 (D035, D052, D053) — parked, to be revisited after main queue
- **Repository**: `/home/paul_chen/prj_pri/testpilot`

---

## Part 1: Project Structure and Key Files

### Directory Layout

```
testpilot/
├── src/testpilot/
│   ├── core/              # Orchestrator, plugin_base, plugin_loader, testbed_config
│   ├── reporting/         # Excel report generation
│   ├── transport/         # Serial, ADB, SSH, network abstractions
│   ├── env/               # Environment modules (roadmap)
│   └── schema/            # YAML case schema validation
├── plugins/
│   └── wifi_llapi/
│       ├── cases/         # Individual test case YAML files (D001 → D413)
│       ├── plugin.py      # WiFi LLAPI plugin implementation
│       ├── agent-config.yaml  # Agent/model policy
│       └── reports/       # Audit reports, evidence, and Excel templates
├── configs/                    # operator-local effective testbed.yaml (auto-staged; git-ignored)
├── docs/
│   ├── audit-todo.md           # Calibration checklist & progress tracker
│   ├── plan.md                 # Master plan, phases, risk gates
│   ├── spec.md                 # System architecture & boundaries
│   ├── todos.md                # Project-wide todo list
│   └── copilot-sdk-hooks-*.md  # Third refactor research
├── scripts/                # Utility scripts for case generation
├── tests/                  # Pytest suite for regression coverage
├── AGENTS.md              # Development guidelines & policies
└── README.md              # Project overview

```

### Key Documentation Files

1. **`docs/audit-todo.md`** (606 lines)
   - **Purpose**: Single source of truth for calibration work
   - **Sections**:
     - Calibration authority (workbook baseline, validation rules)
     - How-to-work procedures and resumption guide
     - Per-case operator loop (7 steps)
     - Current repo handoff snapshot (370/415 calibrated)
     - Master todo list organized by phase (CAL-0 through CAL-7)
   - **Critical Rules**:
     - Read-only verification: find the writable control that drives the read-only value
     - Refresh/trigger rule: identify prerequisite actions before readback
     - Side-effect rule: verify actual behavior, not just API readback
     - Blocker rule: distinguish LLAPI issues from environmental failures
     - Workbook non-pass rule: preserve `To be tested` / `Not Supported` verdicts explicitly

2. **`docs/plan.md`** (160 lines)
   - Master roadmap with 7 phases (P0–P5 historical, R1–R5 current)
   - R4 (Copilot SDK control plane) and R5 (kernel hardening) in progress
   - Agent/model policy: Priority 1=GPT-5.4, Priority 2=Sonnet-4.6, Priority 3=GPT-5-mini
   - Report separation: `xlsx` for Pass/Fail only; `md/json` for detailed diagnostics

3. **`AGENTS.md`** (129 lines)
   - **Audit Report Format Policy** (Section 7):
     - Must use collapsible markdown sections
     - Per-case summary table with: case id, row, API name, verdict, DUT/STA log intervals
     - Fenced code blocks for commands and log excerpts
     - Log line numbers in `Lxxx-Lyyy` format
     - Remove stale `wifi-llapi-rXXX-*` aliases; preserve row identity in `source.row`
   - **Calibration Continuation Policy** (Section 8):
     - Strict **single-case mode** only
     - Sub-agents assist with offline work only
     - Repo handoff documents: `audit-todo.md`, audit reports, `README.md`, `plan.md`
     - Each loop completion: offline survey → live 3-band verification → YAML rewrite → tests → docs sync → commit → next case
   - **Default Lab Baseline Policy** (Section 9):
     - 5G / 2.4G: `WPA2-Personal` + password `00000000`
     - 6G: `WPA3-Personal` + `key_mgmt=SAE` + password `00000000`
     - Non-open baseline required (no open SSIDs)

4. **`plugins/wifi_llapi/reports/audit-report-260313-185447.md`** (488 KB)
   - Current audit report with live evidence for 170+ calibrated cases
   - Structure:
     - Latest repo handoff checkpoint (2026-03-19, 149→157 count progression visible)
     - Per-case detailed sections with command/log evidence
     - Per-case summary table (zh-tw) with verdict verdicts across bands
     - Baseline restore checkpoint with DUT/STA band mapping
     - Individual case evidence blocks (D054–D099)

### Testbed Configuration

**Source**: `plugins/<plugin>/testbed.yaml.example` (auto-staged into `configs/testbed.yaml` whenever the CLI resolves a plugin context)

```yaml
testbed:
  name: lab-bench-1
  devices:
    DUT:
      role: ap
      transport: serial
      serial_port: /dev/ttyUSB0
      baudrate: 115200
    STA:
      role: sta
      transport: adb
      adb_serial: "XXXXXXXX"
    EndpointPC:
      role: endpoint
      transport: ssh
      host: 192.168.1.100
      user: testpilot
  variables:
    SSID_5G, KEY_5G, SSID_6G, KEY_6G, SSID_24G, KEY_24G
```

---

## Part 2: YAML Case Schema

### Case Structure (`src/testpilot/schema/case_schema.py`)

**Required Top-Level Keys**:
- `id` — unique case identifier (e.g., `wifi-llapi-D093-ssidadvertisementenabled`)
- `name` — human-readable case name
- `topology` → `devices` — DUT/STA/Endpoint role definitions
- `steps` — ordered list of test execution steps
- `pass_criteria` — verdict rules

### Example Case: D093_SSIDAdvertisementEnabled

```yaml
id: wifi-llapi-D093-ssidadvertisementenabled
name: "SSIDAdvertisementEnabled — WiFi.AccessPoint.{i}."
version: '1.0'

source:
  report: "0310-BGW720-300_LLAPI_Test_Report.xlsx"
  sheet: Wifi_LLAPI
  row: 95                    # Workbook row reference (critical)
  object: "WiFi.AccessPoint.{i}."
  api: "SSIDAdvertisementEnabled"

platform:
  prplos: 4.0.3
  bdk: 6.3.1

bands: [5g, 6g, 2.4g]        # All 3 bands tested

topology:
  devices:
    DUT:
      role: ap
      transport: serial
      selector: COM0
  links: []

test_environment: |
  Baseline: 5G WPA2-Personal / 6G WPA3-Personal / 2.4G WPA2-Personal
  Notes: SSIDAdvertisementEnabled=1 → hostapd ignore_broadcast_ssid=0 (advertised)
         SSIDAdvertisementEnabled=0 → hostapd ignore_broadcast_ssid=2 (hidden)

steps:
  - id: step1_baseline_5g
    action: exec
    target: DUT
    command: |
      echo "BaselineAdv5g=$(ubus-cli 'WiFi.AccessPoint.1.SSIDAdvertisementEnabled?' | ...)"
      echo "BaselineHapd5g=$(grep 'ignore_broadcast_ssid=' /tmp/wl0_hapd.conf | ...)"
    capture: baseline_5g
  
  - id: step2_set_5g
    action: exec
    target: DUT
    depends_on: step1_baseline_5g
    command: 'ubus-cli WiFi.AccessPoint.1.SSIDAdvertisementEnabled=0'
    capture: set_5g
  
  - id: step3_readback_5g
    action: exec
    target: DUT
    depends_on: step2_set_5g
    command: |
      sleep 3
      echo "GetterAdv5g=..."
      echo "HapdAfterSet5g=..."
    capture: readback_5g
  
  - id: step4_restore_5g
    action: exec
    target: DUT
    depends_on: step3_readback_5g
    command: |
      ubus-cli WiFi.AccessPoint.1.SSIDAdvertisementEnabled=1
      sleep 3
      echo "RestoredAdv5g=..."
    capture: restore_5g
  
  # ... 6G steps (step5–8) ...
  # ... 2.4G steps (step9–12) ...

pass_criteria:
  - field: baseline_5g.BaselineAdv5g
    operator: equals
    value: '1'
    description: '5G baseline should be 1'
  
  - field: readback_5g.GetterAdv5g
    operator: equals
    value: '0'
    description: '5G getter reads back 0 after setter'
  
  - field: readback_5g.HapdAfterSet5g
    operator: equals
    value: '2'
    description: '5G hostapd changes to 2 (hidden)'
  
  - field: restore_5g.RestoredAdv5g
    operator: equals
    value: '1'
    description: '5G restored to 1'
  
  - field: restore_5g.RestoredHapd5g
    operator: equals
    value: '0'
    description: '5G hostapd restored to 0'
  
  # ... 6G pass_criteria (6 items) ...
  # ... 2.4G pass_criteria (6 items) ...

verification_command: |
  grep ignore_broadcast_ssid /tmp/wl0_hapd.conf
  grep ignore_broadcast_ssid /tmp/wl1_hapd.conf
  grep ignore_broadcast_ssid /tmp/wl2_hapd.conf

results_reference:
  v4.0.1:
    5g: Pass
    6g: Pass
    2.4g: Pass
  v4.0.3:
    5g: Pass
    6g: Pass
    2.4g: Pass
    comment: "All 3 bands: setter=0 → ignore_broadcast_ssid 0→2, getter 0; restore=1 → 0, getter 1. Full convergence."
```

**Key Schema Validation Rules** (`case_schema.py`):
- Topology must contain `devices` (non-empty mapping)
- Steps must be a non-empty list with unique `id` values
- Each step requires: `id`, `action`, `target`
- `depends_on` references must be to earlier step IDs
- Pass criteria must be a non-empty list
- Case files starting with `_` are treated as fixtures and excluded from discovery

---

## Part 3: Audit Calibration Methodology

### Calibration Authority & Baseline

**Acceptance Baseline**: `~/0310-BGW720-300_LLAPI_Test_Report.xlsx`
- **Sheet**: `Wifi_LLAPI`
- **Platform**: BCM v4.0.3
- **Result Columns**: L (5G), M (6G), N (2.4G)
- **Interpretation Columns**: O (BCM comment), P (Additional notes)
- **Procedure Columns**: F (Test Steps), G (Command Output)

**Live Validation Source**: Direct serialwrap operations on `COM0` (DUT) and `COM1` (STA)

**Sources NOT Used for Correctness**:
- Run1 existing results
- Old YAML pass/fail conditions that conflict with workbook

### Single-Case Calibration Loop (Strict Mode)

From `docs/audit-todo.md`, **7-step per-case procedure**:

1. **Offline Survey**
   - Read old YAML case file
   - Review workbook row and adjacent cases
   - Identify API characteristics (read-only, setter, method, stats)
   - Check platform documentation and driver interaction

2. **Normalization**
   - Clean workbook column G/H (Test Steps / Command Output)
   - Remove prompt fragments, wrapped lines, sample outputs
   - Identify the authoritative readback source per case
   - Flag rows requiring special infrastructure (Radius, traffic generator, etc.)
   - Flag rows needing prerequisite refresh/trigger actions

3. **Precondition & Environment Setup**
   - Restore DUT/STA baseline to known state
   - Verify single-band connectivity (one band only, not all three)
   - Confirm STA → DUT AP association and DHCP IP
   - Run baseline readback commands

4. **Live Serialwrap Execution**
   - Execute trigger/control commands if needed
   - Run test commands through serialwrap
   - Capture exact output and evidence

5. **Evidence Analysis**
   - Compare live result against workbook expected result (columns L/M/N)
   - For setter/method cases: verify side effects (hostapd state, driver behavior, IP state)
   - For read-only cases: verify the writable control that drives the value
   - Cross-check multiple sources (ubus-cli, hostapd config, driver tool, sysfs)

6. **Decision Logic**
   - **If match**: Proceed to YAML rewrite + regression tests
   - **If mismatch**: Sanitize command flow → source cross-check → rerun
   - **If still mismatch after sanitation**: Record as blocker, do NOT rewrite YAML

7. **Repository Sync**
   - Update YAML to match validated manual flow
   - Add/update regression guards in test suite
   - Run targeted tests: `pytest -k <case_id>`
   - Run full suite: `pytest`
   - Commit changes with case ID and verdict
   - Update `docs/audit-todo.md` and audit report
   - **Immediately proceed to next case** (no stopping after commit)

### Critical Validation Rules

#### Read-Only Verification Rule
For read-only LLAPI properties:
- **DO NOT** treat a direct set command as validation
- Find the **writable LLAPI or external command** that actually drives the value
- Verify the read-only readback **matches** the state change caused by that control
- Example: `SSIDAdvertisementEnabled=0` (read-only perspective) is driven by the setter, verified by reading back `0` and cross-checking hostapd `ignore_broadcast_ssid=2`

#### Refresh / Trigger Rule
Some read paths are only populated after prerequisite actions:
- Example: `AssociatedDevice.*.UplinkRateSpec?` requires `WiFi.AccessPoint.1.getStationStats()` call first
- Identify these trigger steps during calibration
- Write them into YAML as explicit steps before the readback

#### Side-Effect Rule
For setter or method cases:
- LLAPI/ubus readback **alone is NOT enough**
- Verify **actual behavior or downstream state change**
- Examples:
  - Setter → hostapd config change
  - Setter → driver behavior change (e.g., `wl bss up/down`)
  - Method call → STA disconnection or roaming

#### Counter Validation Rule
For statistics/beacon/counter cases without traffic generation:
- Focus on **numeric cross-check and readback consistency**
- Do NOT invent unsupported traffic generation steps
- Record lab limitations explicitly in the audit report
- Example: `TxErrors`, `TxUnicastPacketCount`, `TxMulticastPacketCount` may stay `0` without active traffic

#### Workbook Non-Pass Rule
If workbook marks a row as `To be tested` or `Not Supported`:
- **DO NOT** rewrite YAML to pass-style criteria
- When live evidence is clear and user wants alignment:
  - Update YAML to preserve the non-pass verdict explicitly
  - Add comment explaining the workbook designation
  - Example: `D096 UAPSDEnable` — workbook says "Not Supported" but API fully works; YAML updated as `Pass` with comment

#### DUT / STA Identity Rule
- **Stop using A0/B0 heuristic**
- Rebuild STA interface-to-DUT AP mapping from live MAC/BSSID evidence
- Verified current mapping (from audit report):
  - **DUT (COM0 = B0 class)**:
    - 5G = `wl0` / AP1 / SSID `testpilot5G` / BSSID `2c:59:17:00:19:95`
    - 6G = `wl1` / AP3 / SSID `testpilot6G` / BSSID `2c:59:17:00:19:96`
    - 2.4G = `wl2` / AP5 / SSID `testpilot2G` / BSSID `2c:59:17:00:19:a7`
  - **STA (COM1 = prplOS/B0 class)**:
    - 5G = `wl0` / MAC `2c:59:17:00:04:85`
    - 6G = `wl1` / MAC `2c:59:17:00:04:86`
    - 2.4G = `wl2` / MAC `2c:59:17:00:04:97`

#### Baseline Acceptance Rule
Before starting calibration:
- Verify STA can complete **6G STA→AP connection**
- Verify **DHCP IP acquisition**
- Verify **ping from STA to DUT(AP) succeeds**
- Keep **only one band active** (not all three simultaneously)
- **DO NOT** use open security; enforce non-open baseline
- Current verified baseline:
  - 5G: `testpilot5G` / `WPA2-Personal` / `00000000`
  - 6G: `testpilot6G` / `WPA3-Personal` / `key_mgmt=SAE` / `00000000`
  - 2.4G: `testpilot2G` / `WPA2-Personal` / `00000000`

### Current DUT/STA Mapping & Lab Rules (from audit report)

**Critical Lab Rule**:
- COM1 is a **prplOS/B0 board**, NOT a simple STA dongle
- Before using `ping 192.168.1.1` as DUT reachability evidence:
  - **Move COM1 br-lan off 192.168.1.0/24** (e.g., to 192.168.88.1/24)
  - Otherwise ping is a false-positive self-hit

**Verified Live Baseline** (as of 2026-03-19):
- **DUT COM0**:
  - 5G = `wl0` / `AccessPoint.1` / `SSID.4` / SSID `testpilot5G` / BSSID `2c:59:17:00:19:95` / WPA2 / 00000000
  - 6G = `wl1` / `AccessPoint.3` / `SSID.6` / SSID `testpilot6G` / BSSID `2c:59:17:00:19:96` / WPA3-SAE / 00000000
  - 2.4G = `wl2` / `AccessPoint.5` / `SSID.8` / SSID `testpilot2G` / BSSID `2c:59:17:00:19:a7` / WPA2 / 00000000

- **STA COM1**:
  - 5G `wl0` MAC: `2c:59:17:00:04:85` — reconnects to AP1
  - 6G `wl1` MAC: `2c:59:17:00:04:86` — revalidation pending
  - 2.4G `wl2` MAC: `2c:59:17:00:04:97` — association rerun after reboot

### Blocker vs. Non-Pass Verdicts

**Blockers** (moved outside sequential queue):
- `D035 OperatingStandard` — external environment issue
- `D052 Tx_RetransmissionsFailed` — traffic-dependent, lab constraint
- `D053 TxBytes` — traffic-dependent, lab constraint

**Non-Pass but Aligned** (kept in YAML with explicit verdict):
- `D057 TxUnicastPacketCount` — Fail-shaped mismatch (LLAPI returns 0, driver shows non-zero)
- `D062 VendorOUI` — Fail-shaped mismatch (LLAPI empty, driver shows values)
- `D063 VhtCapabilities` — Fail-shaped mismatch (LLAPI empty, driver shows values)
- `D064 APBridgeDisable` — Not Supported (getter/hostapd/driver diverge)
- `D066 DiscoveryMethodEnabled (FILS)` — Not Supported (FILS writes rejected)
- `D076 QoSMapSet` — Not Supported (collapses to scalar 255)
- `D079 Mode` — Fail (setter returns error even though baseline matches)
- And many others...

---

## Part 4: Audit Report Format & Standards

### Report Structure (from `AGENTS.md` Section 7)

1. **Collapsible Markdown Sections**
   - Use `<details>` and `<summary>` tags
   - Allow readers to expand/collapse evidence

2. **Latest Repo Handoff Checkpoint**
   ```markdown
   <details open>
   <summary>Latest repo handoff checkpoint (2026-03-XX)</summary>
   
   - Current calibrated/remaining counts
   - Active blockers list
   - Blocker handling order
   - Committed case checkpoints with commit hashes
   - Latest validated commands and test results
   - Next repo handoff case
   </details>
   ```

3. **Per-Case Summary Table (zh-tw)**
   - Columns: case id | workbook row | API name | verdict | DUT log interval | STA log interval
   - Example:
     ```
     | `D093` | 95 | SSIDAdvertisementEnabled | Pass | session excerpt | N/A |
     | `D094` | 96 | Status | Pass | session excerpt | N/A |
     ```

4. **Individual Case Evidence Blocks**
   For each calibrated case:
   - **Case ID and Row Reference**: `#### D093 — SSIDAdvertisementEnabled`
   - **Live Evidence** section:
     - Clear statement of verdict
     - List of result for each band (5G/6G/2.4G) if applicable
   - **Commands Block**:
     ```bash
     # STA (if involved)
     <exact commands executed>
     
     # DUT
     <exact commands executed>
     ```
   - **Output Block**:
     ```text
     <exact output from commands>
     ```
   - **Log Interval Reference**:
     - Use `Lxxx-Lyyy` format when known (e.g., `L156-L203`)
     - Or reference as `session excerpt` if not precisely numbered yet

5. **Baseline Restore Checkpoint**
   - Record updated SSID/security/band configurations
   - Validate connectivity after reboot
   - Example with DUT/STA commands and cross-check output

### Mandatory Evidence for Each Aligned Case

From `docs/audit-todo.md` Section "Evidence that must be captured":

- [ ] Workbook row and case id
- [ ] Exact serialwrap commands used
- [ ] Exact trigger/control command if read-only or lazy-populated
- [ ] Before/after readback values
- [ ] Band/interface/MAC/BSSID context when identity matters
- [ ] Side-effect proof for method-style APIs
- [ ] Blocker reason for unaligned cases
- [ ] Hostapd config state (where relevant)
- [ ] Driver state (e.g., `wl` tool output)
- [ ] Network/IP state (where relevant)

### Report File Naming Convention

- Format: `audit-report-<YYMMDD>-<HHMMSS>.md`
- Example: `audit-report-260313-185447.md` (March 13, 2026, 18:54:47 UTC)
- Location: `plugins/wifi_llapi/reports/`

---

## Part 5: Test Case Discovery & Execution

### Case Discovery Convention (from `AGENTS.md`)

1. Official discoverable cases in `plugins/wifi_llapi/cases/`:
   - Named pattern: `D###_lowercase_api_name.yaml` (e.g., `D093_ssidadvertisementenabled.yaml`)
   - Matched by `load_cases_dir()` function
   - Counted in case inventory

2. Legacy/Fixture Cases:
   - Filename starting with `_`: `_template_*.yaml`, `_legacy_*.yaml`
   - Excluded from discovery
   - Used for schema/backward-compat testing only

3. Workbook Row Mapping:
   - Each case has `source.row` pointing to the workbook row
   - Remove stale `wifi-llapi-rXXX-*` aliases
   - Row identity lives only in `source.row` field

### Regression Coverage

**Location**: `tests/test_wifi_llapi_plugin_runtime.py`

**Current Coverage**:
- 521 test cases passing (as of latest full run)
- Guard patterns for each family:
  - AssociatedDevice getters (D009–D027)
  - AccessPoint configuration setters (D065–D097)
  - Security/WPS cases (D087–D107)
  - Stats/counters (D300–D337)
  - Radio/AP getters (D174–D192)

**Test Commands**:
```bash
# Single case
pytest -q tests/test_wifi_llapi_plugin_runtime.py -k 'd093'  # 3 passed

# Family
pytest -q tests/test_wifi_llapi_plugin_runtime.py -k 'radio_getter'  # N passed

# Full suite
pytest -q  # 521 passed (as of 2026-03-20)
```

---

## Part 6: Agent Configuration & Policy

### Plugin Agent Config (from `AGENTS.md` Section 10)

**File**: `plugins/wifi_llapi/agent-config.yaml`

**Model Priority Order** (Third Refactor Target):
1. **Priority 1**: `copilot + gpt-5.4 + high`
2. **Priority 2**: `copilot + sonnet-4.6 + high`
3. **Priority 3**: `copilot + gpt-5-mini + high`

**Execution Strategy**:
- **Granularity**: Case-level (each test case invokes agent)
- **Scheduling**: Sequential (`max_concurrency=1`)
- **Failure Mode**: `retry_then_fail_and_continue`
- **Timeout**: Adjusted per retry attempt

**Phaseout**: Codex CLI compatibility workarounds removed; Copilot SDK is primary target

---

## Part 7: Report Metadata & Reference

### Acceptance Baseline Metadata

**Workbook**: `0310-BGW720-300_LLAPI_Test_Report.xlsx`
- **Platform**: Broadcom BCM v4.0.3
- **DUT**: BGW720-B0 (AP role)
- **STA**: prplOS B0 (STA role)
- **Result Columns**:
  - L: 5G result
  - M: 6G result
  - N: 2.4G result
- **Interpretation Columns**:
  - O: BCM comment
  - P: Additional notes
- **Procedure Columns**:
  - F: Test Steps
  - G: Command Output

### Audit Report Version & Citation

When referencing the current audit report in your guide:

```markdown
**Current Audit Report**: `plugins/wifi_llapi/reports/audit-report-260313-185447.md`
- **Size**: ~488 KB
- **Scope**: Workbook-driven LLAPI calibration evidence
- **Coverage**: 170+ single-case checkpoints with live evidence
- **Format**: Collapsible markdown sections with per-case command/log evidence
- **Latest Checkpoint**: 370 / 415 calibrated (2026-03-20 snapshot)
```

---

## Part 8: Practical Example: How to Write an Audit Entry

### Example Case: D093 SSIDAdvertisementEnabled

```markdown
### D093 SSIDAdvertisementEnabled

**Verdict**: Pass (all 3 bands)

**Workbook Reference**:
- Row 95, API: `WiFi.AccessPoint.{i}.SSIDAdvertisementEnabled`
- Expected: 5G Pass / 6G Pass / 2.4G Pass

**Live Evidence**:

#### STA Command
```bash
# No STA-side commands required; this is AP-only configuration
```

#### DUT Commands
```bash
# 5G Baseline
echo "BaselineAdv5g=$(ubus-cli 'WiFi.AccessPoint.1.SSIDAdvertisementEnabled?' | grep -o 'SSIDAdvertisementEnabled=[0-9]*' | cut -d= -f2)"
echo "BaselineHapd5g=$(grep 'ignore_broadcast_ssid=' /tmp/wl0_hapd.conf | head -1 | cut -d= -f2)"

# 5G Set
ubus-cli WiFi.AccessPoint.1.SSIDAdvertisementEnabled=0

# 5G Readback
sleep 3
echo "GetterAdv5g=$(ubus-cli 'WiFi.AccessPoint.1.SSIDAdvertisementEnabled?' | grep -o 'SSIDAdvertisementEnabled=[0-9]*' | cut -d= -f2)"
echo "HapdAfterSet5g=$(grep 'ignore_broadcast_ssid=' /tmp/wl0_hapd.conf | head -1 | cut -d= -f2)"

# 5G Restore
ubus-cli WiFi.AccessPoint.1.SSIDAdvertisementEnabled=1
sleep 3
echo "RestoredAdv5g=$(ubus-cli 'WiFi.AccessPoint.1.SSIDAdvertisementEnabled?' | grep -o 'SSIDAdvertisementEnabled=[0-9]*' | cut -d= -f2)"
echo "RestoredHapd5g=$(grep 'ignore_broadcast_ssid=' /tmp/wl0_hapd.conf | head -1 | cut -d= -f2)"

# (Repeat for 6G and 2.4G...)
```

#### Output
```text
BaselineAdv5g=1
BaselineHapd5g=0
GetterAdv5g=0
HapdAfterSet5g=2
RestoredAdv5g=1
RestoredHapd5g=0

BaselineAdv6g=1
BaselineHapd6g=0
GetterAdv6g=0
HapdAfterSet6g=2
RestoredAdv6g=1
RestoredHapd6g=0

BaselineAdv24g=1
BaselineHapd24g=0
GetterAdv24g=0
HapdAfterSet24g=2
RestoredAdv24g=1
RestoredHapd24g=0
```

#### Verdict Analysis
- **5G**: Baseline 1 → Set 0 → Readback 0 → hostapd 0→2 → Restore 1 → hostapd 2→0 ✅ **Pass**
- **6G**: Baseline 1 → Set 0 → Readback 0 → hostapd 0→2 → Restore 1 → hostapd 2→0 ✅ **Pass**
- **2.4G**: Baseline 1 → Set 0 → Readback 0 → hostapd 0→2 → Restore 1 → hostapd 2→0 ✅ **Pass**

**Pass Criteria Met**:
- ✅ Baseline SSIDAdvertisementEnabled = 1 on all bands
- ✅ Setter accepted, readback = 0 on all bands
- ✅ Hostapd ignore_broadcast_ssid = 2 (hidden) on all bands
- ✅ Restore to 1, hostapd back to 0 on all bands
- ✅ Full round-trip convergence

**Regression Test**:
```bash
pytest -q tests/test_wifi_llapi_plugin_runtime.py -k 'd093' → 3 passed
pytest -q → 521 passed
```

**Commit**:
```
D093 SSIDAdvertisementEnabled: Pass (all 3 bands, multiband setter round-trip with hostapd convergence)
```

---

## Part 9: Continuation & Resumption

### How to Resume Audit Work (from `docs/audit-todo.md`)

If reopening calibration work in a future session:

1. **Re-read foundations**:
   - This guide (audit doc structure, rules, standards)
   - `docs/audit-todo.md` sections 1–3 (authority, procedures, rules)
   - `AGENTS.md` sections 7–10 (report format, calibration policy, agent config)

2. **Verify acceptance baseline**:
   - Re-open `~/0310-BGW720-300_LLAPI_Test_Report.xlsx`
   - Use columns L/M/N (5G/6G/2.4G results) as truth source
   - Check columns O/P for interpretation notes

3. **Rebuild environment mapping**:
   - Run live MAC/BSSID discovery on DUT/STA if session interrupted
   - Verify current STA 2.4G/5G/6G interfaces and MACs
   - Confirm baseline connectivity (6G association, DHCP, ping)

4. **Identify next case**:
   - Read latest checkpoint in:
     - `docs/audit-todo.md` section "Current repo handoff snapshot"
     - `plugins/wifi_llapi/reports/audit-report-*.md` latest section
   - **DO NOT** rely on session-local SQL or scratchpad
   - Next ready case: typically the one immediately after latest committed case

5. **Verify serialwrap health**:
   - Test `serialwrap COM0 --list` and `serialwrap COM1 --list`
   - Ensure UART/ADB connections are healthy

6. **Execute single case**:
   - Pick the next ready case from handoff snapshot
   - Follow the 7-step per-case loop (Section Part 3)
   - Do NOT stop after commit; proceed to next case
   - Update documents only when docs changes are needed

### Continuation Guard Rails (from audit-todo.md)

- **Only committed YAML / docs count** as trusted handoff state
- **Do NOT infer progress** from local unstaged experiments
- **Reuse prior art** patterns from previous committed cases
- **Blockers are parked separately**, to be revisited after main queue clears
- **Counts are authoritative**: use the numbers in `Current repo handoff snapshot`

---

## Part 10: Key Metrics & Progress Tracking

### Current Status (2026-03-20)

| Metric | Value | Notes |
|--------|-------|-------|
| **Total Official Cases** | 415 | From 0310 workbook |
| **Calibrated Cases** | 370 (89%) | 149→157→370 progression |
| **Remaining Cases** | 186 (26%) | Under sequential calibration |
| **Active Blockers** | 3 | D035, D052, D053 (parked) |
| **Test Suite Coverage** | 521 passed | Full pytest suite |
| **Audit Report Size** | ~488 KB | 170+ per-case sections |
| **Latest Commit** | 2026-03-20 | Snapshot date |
| **DUT Reboot Status** | Baseline rebuilt | 5G/6G/2.4G verified |
| **STA Status** | Partial revalidation | 6G revalidation pending |

### Calibration Phases (from `docs/audit-todo.md`)

| Phase | Status | Notes |
|-------|--------|-------|
| **CAL-PRE** | ✅ Done | DUT/STA band mapping rebuilt |
| **CAL-0** | ⏳ In Progress | Inventory mapping, family tagging |
| **CAL-1** | ✅ 80% Done | Workbook recipe sanitation |
| **CAL-2** | ✅ 70% Done | AssociatedDevice batch |
| **CAL-3** | ⏳ In Progress | AccessPoint method batch |
| **CAL-4** | ⏳ In Progress | Security / SSID / WPS batch |
| **CAL-5** | ⏳ In Progress | Radio / AP / SSID configuration batch |
| **CAL-6** | ✅ 50% Done | Stats and counters batch |
| **CAL-7** | ⏳ Pending | Blocker ledger and closeout |

---

## Part 11: Key Documents & Quick Reference

### Must-Read Documents

1. **`docs/audit-todo.md`** (606 lines)
   - Authoritative source for calibration work
   - Current progress snapshot: 370/415
   - Per-case loop procedure
   - Calibration rules & authority

2. **`docs/plan.md`** (160 lines)
   - Phases R4–R5 roadmap
   - Risk gates and design decisions
   - Report separation policy (xlsx vs. md/json)

3. **`AGENTS.md`** (129 lines)
   - Report format policy
   - Calibration continuation rules
   - Default baseline requirements
   - Plugin agent config

4. **`plugins/wifi_llapi/reports/audit-report-260313-185447.md`** (488 KB)
   - Current live evidence
   - Per-case checkpoints with commits
   - Lab baseline mapping
   - 170+ calibrated case details

### Command Quick Reference

```bash
# List available cases
python -m testpilot.cli list-cases wifi_llapi

# Load and validate a specific case
python -m testpilot.cli run wifi_llapi --case-id wifi-llapi-D093-ssidadvertisementenabled

# Run targeted regression tests
pytest -q tests/test_wifi_llapi_plugin_runtime.py -k 'd093'  # Single case
pytest -q tests/test_wifi_llapi_plugin_runtime.py -k 'radio'  # Family
pytest -q  # Full suite

# Build template report
python -m testpilot.cli wifi-llapi build-template-report --source-xlsx <path>
```

### File Paths Summary

```
Audit Documentation:
  docs/audit-todo.md                             ← Current calibration checklist
  docs/plan.md                                   ← Master roadmap
  AGENTS.md                                      ← Development policies
  plugins/wifi_llapi/reports/audit-report-*.md  ← Live evidence & progress

Schema & Configuration:
  src/testpilot/schema/case_schema.py            ← YAML validation rules
  plugins/<plugin>/testbed.yaml.example          ← Per-plugin testbed template (auto-staged)
  plugins/wifi_llapi/agent-config.yaml           ← Agent/model policy

Test Cases:
  plugins/wifi_llapi/cases/D###_*.yaml           ← 415 test case YAMLs

Regression Tests:
  tests/test_wifi_llapi_plugin_runtime.py        ← 521 regression guards
```

---

## Appendix A: Glossary

| Term | Definition |
|------|-----------|
| **LLAPI** | Local Link API — WiFi control interface |
| **ubus-cli** | uBus command-line client for LLAPI queries/commands |
| **serialwrap** | Test framework transport wrapper for serial/ADB/SSH |
| **hostapd** | HostAPD daemon managing AP configuration on DUT |
| **WPA2-Personal** | WPA2 with pre-shared key (PSK) |
| **WPA3-Personal** | WPA3 with Simultaneous Authentication of Equals (SAE) |
| **Pass Criteria** | Deterministic rules for test verdict (equals, contains, etc.) |
| **Setter** | LLAPI property that accepts a write value |
| **Getter** | LLAPI property that returns a read-only value |
| **Method** | LLAPI operation that performs an action (e.g., `kickStation`) |
| **Verdict** | Test result: Pass / Fail / Not Supported / To be tested |
| **DUT** | Device Under Test (AP role) |
| **STA** | Station device (client role) |
| **AP1/AP3/AP5** | AccessPoint indices for 5G / 6G / 2.4G bands |
| **Handoff** | Documentation checkpoint marking resume point for future sessions |

---

## Appendix B: Workbook Column Reference

| Column | Heading | Purpose |
|--------|---------|---------|
| **A** | ID | Case identifier (D001–D413) |
| **B** | API Path | Full LLAPI object path |
| **C** | Input Type | Setter / Getter / Method |
| **D** | Expected Type | Return data type |
| **E** | Method | If method, the operation name |
| **F** | Test Steps | Manual procedure steps (often wrapped) |
| **G** | Command Output | Sample expected output (often wrapped) |
| **H** | Constraints | Special requirements or topology notes |
| **I** | Preconditions | Setup requirements |
| **J–K** | (Deprecated) | Old reference columns |
| **L** | 5G Result | Verdict for 5G band (workbook authority) |
| **M** | 6G Result | Verdict for 6G band (workbook authority) |
| **N** | 2.4G Result | Verdict for 2.4G band (workbook authority) |
| **O** | BCM Comment | Broadcom interpretation notes |
| **P** | Additional Notes | Implementation-specific hints |

---

## Appendix C: Verdict Categories

| Category | Meaning | YAML Handling |
|----------|---------|---------------|
| **Pass** | API works as specified | `pass_criteria` all match |
| **Fail** | API returns incorrect value or state | Record mismatch in YAML, keep verdict explicit |
| **Not Supported** | LLAPI not implemented on platform | `pass_criteria` checks for expected error/absence |
| **To be tested** | Workbook placeholder, needs live validation | Validate live, keep verdict as `To be tested` if confirmed |
| **Mixed** | Different verdicts per band | Document per-band result in YAML |

---

## Appendix D: Common Blocker Patterns

| Pattern | Example | Resolution Path |
|---------|---------|-----------------|
| **API Not Implemented** | Method returns error 1 (unknown error) | Record as Not Supported if consistent; move to blocker if workbook differs |
| **Setter Accepted But No Side Effect** | `MaxAssociatedDevices=31` accepted, config stays 32 | Investigate driver/hostapd coupling; document as Fail if state diverges |
| **Getter Returns Placeholder** | `EncryptionMode="Default"` hardcoded, hostapd shows actual mode | Document as Not Supported if getter is decorative |
| **Traffic-Dependent Counter** | `TxErrors=0` without active TX traffic | Record as limitation; use numeric cross-check instead of traffic generation |
| **STA Connection Required** | Case requires Radius or multi-band neighbor visibility | Park as blocker if lab cannot support prerequisite |
| **Hostapd Config Mismatch** | Setter accepted northbound, hostapd config unchanged | Classify as Fail; investigate hostapd coupling or driver divergence |

---

## Appendix E: Lab Environment Setup Checklist

- [ ] DUT (COM0) accessible via serial at `/dev/ttyUSB0`, 115200 baud
- [ ] STA (COM1) accessible via ADB or serial
- [ ] DUT firmware version >= 4.0.3 (BGW720-B0)
- [ ] STA firmware compatible with prplOS B0
- [ ] Host machine can reach both DUT and STA (network interfaces)
- [ ] `configs/testbed.yaml` (auto-staged from `plugins/<plugin>/testbed.yaml.example`) edited with correct ports/IPs for this lab
- [ ] Default baseline applied:
  - [ ] 5G SSID `testpilot5G` / WPA2 / `00000000`
  - [ ] 6G SSID `testpilot6G` / WPA3-SAE / `00000000`
  - [ ] 2.4G SSID `testpilot2G` / WPA2 / `00000000`
- [ ] STA can associate to all three bands (one at a time)
- [ ] STA gets DHCP IP from DUT
- [ ] STA can ping DUT(AP)
- [ ] serialwrap is functional on COM0 and COM1
- [ ] pytest runs without errors (baseline: 521 passed)

---

**END OF COMPREHENSIVE AUDIT GUIDE**

---

*This document synthesizes the TestPilot audit framework, project structure, calibration methodology, and reporting standards to provide a complete reference for writing comprehensive audit guides and executing calibration work.*
