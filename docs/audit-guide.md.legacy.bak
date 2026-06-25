# TestPilot Audit Guide

本文件定義 TestPilot 專案中，針對 plugin test case 進行 **workbook 校正（calibration audit）** 的完整架構、流程、產出物格式與行為準則。

TestPilot 並非 wifi_llapi 專屬；本指南以 wifi_llapi 的 0310-BGW720-300 calibration campaign 作為具體範例。

---

## 1. Audit 概述

### 1.1 什麼是 Calibration Audit

Calibration Audit 是將 **workbook（Excel 試算表）中的 API 測試項目** 逐筆與 **live DUT 硬體** 對齊的流程。每一筆 workbook row 對應一個 YAML test case，透過 live probe 取得真實 DUT 回應，並記錄 verdict（Pass / Fail / Skip / Not Supported / Blocked）。

### 1.2 Audit 前置準備

進行 audit 前，操作者必須提供以下資訊：

| 項目 | 說明 | wifi_llapi 範例 |
|------|------|----------------|
| **Workbook** | Excel 試算表，定義所有 API 測試項目 | `~/0310-BGW720-300_LLAPI_Test_Report.xlsx` → `Wifi_LLAPI` sheet |
| **Source code repo** | TestPilot 專案路徑 | `/home/paul_chen/prj_pri/testpilot` |
| **Plugin** | 目標 plugin 名稱 | `wifi_llapi` |
| **DUT 設備** | Device Under Test 的型號、韌體版本、連線方式 | BGW720-300, FW 0310, serial via COM0 |
| **STA 設備**（若需要） | Station 端設備與連線方式 | STA via COM1（需要 AssociatedDevice 類 case） |
| **Testbed 配置** | 頻段/SSID/Security/密碼 | 見 §2.3 |
| **Transport 工具** | 與 DUT/STA 通訊的工具 | serialwrap broker + MCP |

### 1.3 wifi_llapi 範例環境

```
DUT:  BGW720-300 (FW 0310)
      serial console via serialwrap COM0
      三頻 WiFi AP

STA:  測試用 station
      serial console via serialwrap COM1
      可連接 DUT 的三個頻段

Testbed 三頻 baseline:
  5G   → AP1 / wl0 / Radio.1 / SSID.4 / testpilot5G / WPA2-Personal / 00000000
  6G   → AP3 / wl1 / Radio.2 / SSID.6 / testpilot6G / WPA3-Personal(SAE) / 00000000
  2.4G → AP5 / wl2 / Radio.3 / SSID.8 / testpilot2G / WPA2-Personal / 00000000
```

---

## 2. 專案結構

### 2.1 關鍵路徑

```
testpilot/
├── plugins/<plugin>/
│   ├── cases/                  # YAML test case 檔案
│   │   ├── D001_xxx.yaml       # official discoverable case
│   │   └── _legacy_fixture.yaml # underscore prefix = excluded from discovery
│   ├── reports/                # audit 產出物
│   │   ├── audit-report-*.md   # 校正報告（collapsible markdown）
│   │   ├── agent_trace/        # agent 執行 trace
│   │   └── templates/          # 報表模板
│   ├── plugin.py               # plugin 主邏輯
│   └── agent-config.yaml       # agent/model policy
├── configs/
│   └── testbed.yaml            # testbed 配置（git-ignored）
├── docs/
│   ├── audit-guide.md          # ← 本文件
│   ├── audit-todo.md           # 校正進度追蹤
│   ├── plan.md                 # 開發計畫
│   └── todos.md                # 開發待辦
├── tests/
│   └── test_<plugin>_plugin_runtime.py  # 回歸測試
└── src/testpilot/
    └── schema/case_schema.py   # YAML case schema 驗證
```

### 2.2 YAML Case 格式

每個 test case 對應 workbook 中的一行：

```yaml
id: d394-getradiostats-bytesreceived        # 唯一識別碼
name: D394 getRadioStats BytesReceived       # 人類可讀名稱
source:
  row: 289                                   # workbook 行號
  object: "WiFi.Radio.{i}."                  # data model 物件路徑
  api: "getRadioStats()"                     # API 名稱
  baseline: 0310-BGW720-300                  # 校正所用的韌體版本
bands:                                       # 適用頻段
- 5g
- 6g
- 2.4g
llapi_support: Support                       # Support / Not Supported
results_reference:                           # 校正結果
  v4.0.3:                                    # workbook 版本
    5g: Pass
    6g: Pass
    2.4g: Pass
topology:
  devices:
    DUT:
      role: ap
      transport: serial
      selector: COM0
steps:                                       # 測試步驟
- id: step_5g_stats
  target: dut
  action: read                               # read / write / skip
  capture: stats_5g                          # 捕獲輸出到此 key
  command: 'ubus-cli "WiFi.Radio.1.getRadioStats()"'
  expected: getRadioStats() 回傳有效值
  description: Radio.1 (5g) getRadioStats()
pass_criteria:                               # 判定條件
- field: stats_5g.BytesReceived
  operator: regex                            # regex / equals / exists
  value: '^\d+$'
```

### 2.3 Testbed 配置

```yaml
# configs/testbed.yaml
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
  variables:
    SSID_5G: TestPilot_5G
    KEY_5G: testpilot5g
```

---

## 3. 校正流程

### 3.1 整體流程

```
1. 環境確認
   ├── workbook 載入 & row 清單建立
   ├── DUT/STA 連線 & self-test
   └── testbed baseline 確認

2. 逐筆校正（per-case calibration）
   ├── 2a. Survey：分析 workbook row 的 API、object、預期行為
   ├── 2b. Live Probe：透過 serialwrap 在 DUT 上執行命令
   ├── 2c. Evidence 收集：記錄命令輸出、log 區間
   ├── 2d. Verdict 判定：比對 live 結果與 workbook 預期
   ├── 2e. YAML 撰寫/更新：填入 steps、pass_criteria、results_reference
   └── 2f. 測試驗證：新增/更新 parametrized test entry

3. 批次提交
   ├── pytest 全過
   ├── 更新 docs（audit-todo.md, README.md）
   └── git commit
```

### 3.2 單案校正流程（Single-Case Mode）

每一個 case 的校正步驟：

#### Step 1: Survey

- 從 workbook 讀取該 row 的：API 路徑、預期行為、workbook verdict
- 確認 YAML 檔案是否已存在（`plugins/<plugin>/cases/D<NNN>_*.yaml`）
- 確認該 API 的 data model 物件類型：
  - **Radio 層**：`WiFi.Radio.{i}.` — DUT-only, 三頻
  - **AP 層**：`WiFi.AccessPoint.{i}.` — DUT-only, 三頻
  - **AssociatedDevice 層**：`WiFi.AccessPoint.{i}.AssociatedDevice.{i}.` — 需要 STA 連線
  - **SSID 層**：`WiFi.SSID.{i}.` — DUT-only
  - **Method call**：`getRadioStats()`, `getSSIDStats()` 等

#### Step 2: Live Probe

透過 serialwrap 提交命令到 DUT：

```bash
# 健康檢查
serialwrap session self-test --selector COM0

# Getter probe
serialwrap cmd submit --selector COM0 \
  --cmd 'ubus-cli "WiFi.Radio.1.Noise?"' \
  --source agent:audit --mode line --cmd-timeout 15

# Method call probe
serialwrap cmd submit --selector COM0 \
  --cmd 'ubus-cli "WiFi.Radio.1.getRadioStats()"' \
  --source agent:audit --mode line --cmd-timeout 30

# Setter probe（需 restore）
serialwrap cmd submit --selector COM0 \
  --cmd 'ubus-cli "WiFi.AccessPoint.1.Enable=0"' \
  --source agent:audit --mode line --cmd-timeout 15
# ... verify change ...
serialwrap cmd submit --selector COM0 \
  --cmd 'ubus-cli "WiFi.AccessPoint.1.Enable=1"' \
  --source agent:audit --mode line --cmd-timeout 15
```

**三頻 probe 注意事項：**

| 頻段 | Radio | AP | SSID | wl interface |
|------|-------|----|------|-------------|
| 5G | Radio.1 | AP.1 | SSID.4 | wl0 |
| 6G | Radio.2 | AP.3 | SSID.6 | wl1 |
| 2.4G | Radio.3 | AP.5 | SSID.8 | wl2 |

**serialwrap 實務注意：**
- 每批不超過 ~5 條 ubus-cli 命令，避免 PROMPT_TIMEOUT
- 卡住時：`session clear` → `sleep 3` → `session self-test`
- 慢速子樹（如 IEEE80211ax）使用 `?` wildcard tree dump 比逐一 getter 更可靠

#### Step 3: Verdict 判定

| Verdict | 條件 |
|---------|------|
| **Pass** | Live 值符合 workbook 預期，getter/setter/driver 全鏈路收斂 |
| **Fail** | Live 值與 workbook 預期不符（e.g. northbound 接受但 driver 不跟隨） |
| **Skip** | Workbook 標記 Skip 或 API 不適用於該頻段 |
| **Not Supported** | API 回傳 error 4 / parameter not found，或 getter 固定回傳無效值 |
| **Blocked** | 需要特定前置條件但目前無法建立（記錄 blocker 原因） |

#### Step 4: YAML 更新

根據 verdict 更新 YAML 的 `results_reference` 與 `pass_criteria`。

#### Step 5: Test Entry

在 `tests/test_<plugin>_plugin_runtime.py` 新增 parametrized test entry：

```python
# 在對應的 _CASES table 新增 tuple
_RADIO_GETTER_CASES = [
    # (yaml_file, row, live_5g, live_6g, live_24g, path_template)
    ("D381_noise_radio.yaml", 284, "-100", "-97", "-79", "WiFi.Radio.{r}.Noise"),
    ...
]
```

### 3.3 批次校正流程（Batch Mode）

當多個 case 屬於同一 pattern（如同一 method call 的不同 field），可批次處理：

1. **分組**：依 API pattern 分組（getter / method stats / WMM / WiFi7 等）
2. **批次 probe**：一次 probe 取得所有 field 值
3. **批次 YAML rewrite**：使用 sub-agent 依 template pattern 批次產生
4. **批次 validate**：`load_case()` 驗證全部通過
5. **批次 test entry**：新增到對應 parametrized table
6. **一次 commit**：`uv run pytest -q` 全過後提交

### 3.4 Sub-Agent 使用策略

| Agent 類型 | 用途 | 注意事項 |
|-----------|------|---------|
| **explore** | 離線 survey、source tracing、code review | Stateless，每次需給完整 context |
| **task** | 建構/測試執行 | 短生命週期 |
| **general-purpose** | 批次 YAML rewrite | 需提供完整 template + evidence |
| **serialwrap MCP** | DUT/STA live probe | 透過 serialwrap broker |

---

## 4. 產出物格式

### 4.1 Audit Report（`plugins/<plugin>/reports/audit-report-*.md`）

```markdown
# Wifi_LLAPI Calibration Audit Report

- Report path: `plugins/wifi_llapi/reports/audit-report-260313-185447.md`
- Scope: workbook-driven LLAPI calibration evidence
- Acceptance baseline: `~/0310-BGW720-300_LLAPI_Test_Report.xlsx` ...

<details open>
<summary>Latest repo handoff checkpoint (YYYY-MM-DD)</summary>

- Trusted/calibrated official cases: **NNN / 415**
- Remaining official cases: **MMM**
- Current blockers: ...
</details>
```

格式規則（來自 AGENTS.md）：

1. 使用 collapsible markdown sections (`<details>`)
2. 每個已校正 case 必須包含 `Per-case 摘要表（zh-tw）`
3. 摘要表至少包含：case id、workbook row、API 名稱、verdict、DUT log interval、STA log interval
4. 每個 case 附上 fenced code blocks：STA 指令、DUT 指令、判定 pass 的 log 摘錄
5. log 行號區間使用 `Lxxx-Lyyy` 表示法

### 4.2 Audit Todo（`docs/audit-todo.md`）

追蹤校正進度的文件：

```markdown
- Trusted/calibrated official cases: **370 / 415**
- Blockers: D035, D052, D053
- Pending: D051
```

### 4.3 Test File（`tests/test_<plugin>_plugin_runtime.py`）

每個已校正 case 必須有對應的 parametrized test entry，提供三層 regression guard：

| Test | 驗證內容 |
|------|---------|
| `test_*_contract` | YAML 載入、row 正確、bands/steps/criteria 結構 |
| `test_*_setup_env` | setup_env() 不 raise |
| `test_*_evaluate` | 以 live evidence 構造的 mock output 通過 evaluate() |

現有 parametrized tables：

| Table | 適用 pattern | Tuple 格式 |
|-------|-------------|-----------|
| `_RADIO_GETTER_CASES` | Radio/AP/IEEE80211ax property getter | `(yaml, row, live_5g, live_6g, live_24g, path_tpl)` |
| `_METHOD_STATS_CASES` | getRadioStats / getSSIDStats fields | `(yaml, row, method, field, live_5g, live_6g, live_24g)` |
| `_SSID_STATS_CASES` | SSID getSSIDStats fields | `(yaml, row, field, verdict)` |
| `_SCAN_RESULTS_CASES` | getScanResults fields | `(yaml, row, field)` |
| `_ACTION_METHOD_CASES` | Action method calls (void) | `(yaml, row, method, verdict)` |
| `_WMM_STATS_CASES` | Radio WMM stats | `(yaml, row, wmm_sub, field, live_5g, live_6g, live_24g)` |
| `_WIFI7_CAPS_CASES` | WiFi7 AP/STA role capabilities | `(yaml, row, role, prop)` |

---

## 5. YAML Case Pattern 分類

### Pattern A: Property Getter（3-band read）

適用：Radio / AP / IEEE80211ax / SSID 層的 read-only property

```yaml
steps:
- id: step_5g_getter
  target: dut
  action: read
  capture: getter_5g
  command: 'ubus-cli "WiFi.Radio.1.PropertyName?"'
pass_criteria:
- field: getter_5g.PropertyName
  operator: regex         # or equals
  value: 'expected_pattern'
```

### Pattern B: Method Call Stats（3-band getRadioStats/getSSIDStats）

適用：method call 回傳的統計欄位

```yaml
steps:
- id: step_5g_stats
  target: dut
  action: read
  capture: stats_5g
  command: 'ubus-cli "WiFi.Radio.1.getRadioStats()"'
pass_criteria:
- field: stats_5g.FieldName
  operator: regex
  value: '^\d+$'
```

### Pattern C: WMM Stats（grep filter）

適用：WMM 子物件（需 grep 避免 suffix matching 歧義）

```yaml
steps:
- id: step_5g_stats
  target: dut
  action: read
  capture: stats_5g
  command: 'ubus-cli "WiFi.Radio.1.getRadioStats()" | grep AC_BE_Stats'
pass_criteria:
- field: stats_5g.WmmBytesReceived
  operator: regex
  value: '^\d+$'
```

### Pattern D: Setter（write + verify + restore）

適用：可寫入的 property

```yaml
steps:
- id: step_5g_baseline
  target: dut
  action: read
  capture: baseline_5g
  command: 'ubus-cli "WiFi.AccessPoint.1.Enable?"'
- id: step_5g_setter
  target: dut
  action: write
  command: 'ubus-cli "WiFi.AccessPoint.1.Enable=0"'
  depends_on: step_5g_baseline
- id: step_5g_verify
  target: dut
  action: read
  capture: verify_5g
  command: 'ubus-cli "WiFi.AccessPoint.1.Enable?"'
  depends_on: step_5g_setter
- id: step_5g_restore
  target: dut
  action: write
  command: 'ubus-cli "WiFi.AccessPoint.1.Enable=1"'
  depends_on: step_5g_verify
```

### Pattern E: Skip / Not Supported

```yaml
steps:
- id: step_note
  target: dut
  action: skip
  description: MBOAssocDisallowReason Skip — workbook 標記 Skip
pass_criteria:
- field: step_note
  operator: equals
  value: skip
```

### Pattern F: WiFi7 Capabilities（3-band read, equals "1"）

```yaml
steps:
- id: step_5g_getter
  target: dut
  action: read
  capture: getter_5g
  command: 'ubus-cli "WiFi.Radio.1.Capabilities.WiFi7APRole.PropertyName?"'
pass_criteria:
- field: getter_5g.PropertyName
  operator: equals
  value: '1'
```

---

## 6. 行為準則

### 6.1 校正策略

1. **Single-case mode**：未經特別授權時，逐案校正，不批次跳過 evidence 驗證
2. **Batch mode**：僅限同 pattern 且已有 live evidence 的 case group
3. **Sub-agent 限制**：sub-agent 只可協助 offline survey、source tracing、code review；最終 live serialwrap 操作與 verdict 仍由主操作者手動收斂

### 6.2 Repo Handoff 規則

每次完成單案或批次校正後，repo handoff 文件至少同步：

- `docs/audit-todo.md`：calibrated / remaining counts
- `plugins/<plugin>/reports/audit-report-*.md`：最新 checkpoint 區塊
- `README.md`：calibrated count
- `docs/plan.md`：進度更新

### 6.3 Commit 規範

使用 Conventional Commit 格式：

```
test(wifi-llapi): 固化 Batch N — M 筆 <描述>

<群組清單與每筆 verdict>

驗證：uv run pytest -q → NNN passed
進度：A → B / 415

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
```

### 6.4 Case 命名慣例

- 檔名格式：`D<NNN>_<api_name_snake_case>.yaml`
- D-number 為 workbook 中的序號（非 row number）
- `_` prefix 的檔名為 legacy fixture，不參與 discovery

---

## 7. Log 與 Evidence 路徑

### 7.1 serialwrap 日誌

serialwrap 的 RAW log 與 WAL 檔位於 serialwrap daemon 的 data directory 下：

```
~/.serialwrap/data/
├── sessions/
│   ├── COM0/
│   │   └── raw.log          # DUT 原始 UART log
│   └── COM1/
│       └── raw.log          # STA 原始 UART log
└── wal/
    └── wal-<timestamp>.db   # Write-Ahead Log
```

可透過以下方式取回 log：

```bash
serialwrap log tail-raw --selector COM0 --lines 100
serialwrap wal export --from <timestamp> --to <timestamp>
```

### 7.2 Audit Report 中的 Log 引用

使用 `Lxxx-Lyyy` 格式標記 log 行號區間：

```markdown
- DUT log interval: L1234-L1256
- STA log interval: L789-L812
```

### 7.3 Agent Trace

plugin agent 的執行 trace 存放在：

```
plugins/<plugin>/reports/agent_trace/
```

### 7.4 Generated Excel Reports

自動產生的 Excel 報表存放在：

```
plugins/<plugin>/reports/
├── YYYYMMDD_<DUT>_wifi_LLAPI_<timestamp>.xlsx
```

---

## 8. 常見問題

### Q: 如何判斷 case 屬於哪個 test table？

依據 YAML 的 `source.object` 和 `source.api`：
- `WiFi.Radio.{i}.PropertyName` → `_RADIO_GETTER_CASES`
- `WiFi.Radio.{i}.getRadioStats()` + top-level field → `_METHOD_STATS_CASES`
- `WiFi.Radio.{i}.Stats.Wmm*` → `_WMM_STATS_CASES`
- `WiFi.Radio.{i}.Capabilities.WiFi7*` → `_WIFI7_CAPS_CASES`
- `WiFi.SSID.{i}.Stats.*` → `_SSID_STATS_CASES`
- `WiFi.Radio.{i}.getScanResults()` → `_SCAN_RESULTS_CASES`
- Setter 類或複雜 case → standalone test function

### Q: Row collision（多個 D-number 共用同一 workbook row）怎麼辦？

Workbook 有時對同一 row 定義不同 API 欄位。每個 D-number 維持獨立 YAML，`source.row` 允許重複。

### Q: WMM field path 為何需要 grep？

`getRadioStats()` 回傳的 key 是完整 dotted path（如 `WiFi.Radio.1.Stats.AC_BE_Stats.WmmBytesReceived`）。`_resolve_field` 使用 suffix matching，當有多個 AC category 同時出現時會產生歧義。加上 `| grep AC_XX_Stats` 讓輸出只剩單一 AC 的行，即可避免衝突。

### Q: 什麼情況下標記 Blocked？

當 case 需要特定前置條件但目前無法建立時（如需要可靠的 retry exhaustion workload 但無現成方法），標記 Blocked 並記錄原因。Blocked case 在其餘 sequential 校正完成後再回頭處理。

---

## 9. wifi_llapi 校正進度摘要

截至 2026-03-23：

| 狀態 | 筆數 | 說明 |
|------|------|------|
| **已校正（有 test coverage）** | 317 | 包含 Pass/Fail/Skip/Not Supported |
| **已校正（YAML 完成，缺 test）** | 103 | YAML 骨架存在，需 live probe 補齊 verdict |
| **Known Blockers** | 4 | D035, D051, D052, D053 |
| **Total YAML on disk** | 420 | |

已校正 case 的群組分佈：

- AssociatedDevice properties (D004-D053)
- AP properties & setters (D064-D096, D103-D148)
- Radio properties (D174-D251, D189-D385, D404-D405, D461, D467)
- getRadioStats (D267-D276, D394-D403, D477)
- getRadioAirStats (D256-D266)
- getScanResults (D277-D290)
- getSSIDStats (D300-D337)
- SSID properties (D294-D299, D308-D320)
- Action methods (D352-D360)
- IEEE80211ax (D363-D371)
- WMM Radio stats (D478-D493)
- WiFi7 Capabilities (D593-D600)
- AffiliatedSTA / MLO (D575-D588)

---

## 10. 延伸：新 Plugin Audit 啟動清單

若要對新 plugin 啟動 calibration audit：

1. [ ] 準備 workbook（Excel）並確認 sheet / column mapping
2. [ ] 建立 `plugins/<new_plugin>/cases/` 目錄
3. [ ] 設定 `configs/testbed.yaml` 中的 DUT/STA 設備
4. [ ] 確認 serialwrap daemon 啟動、serial device 可見、且 session READY
5. [ ] 建立初始 YAML template（依 §5 的 Pattern A-F）
6. [ ] 建立 `tests/test_<new_plugin>_plugin_runtime.py` 並加入 parametrized table
7. [ ] 開始 single-case mode 逐筆校正
8. [ ] 每批校正後更新 `docs/audit-todo.md` 並 commit
