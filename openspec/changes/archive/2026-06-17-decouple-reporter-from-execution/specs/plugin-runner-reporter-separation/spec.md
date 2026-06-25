## ADDED Requirements

### Requirement: plugin 執行階段與報表階段分離
plugin 的整-run 執行 MUST 由 runner 負責,報表產出 MUST 由 reporter 負責;runner SHALL 產出結構化 run dataset(`RunResult`),reporter SHALL 僅消費此 dataset 產出報表。reporter MUST NOT 依賴執行引擎或自行驅動 case 執行。

#### Scenario: reporter 不含執行依賴
- **WHEN** 對 `plugins/wifi_llapi/reporting/reporter.py` 靜態掃描 import
- **THEN** 無任何 `testpilot.core.execution_engine`、`testpilot.core.orchestrator`(`build_case_session_plan`)、`testpilot.reporting.log_capture` 之 import(execution import 數=0)

#### Scenario: runner 產出 RunResult、reporter 只吃 RunResult
- **WHEN** runner 執行完一輪測試
- **THEN** 產出 `RunResult`(含每 case 的原始執行結果 + run-level metadata),且 reporter 僅依此 `RunResult` 即能重建 xlsx/md/json/html 報表,無需再讀執行內部

### Requirement: PluginBase 提供 create_runner 委派契約
`PluginBase` SHALL 提供 optional `create_runner()`,default 回傳 `None`。orchestrator 執行 plugin 時 SHALL 委派給 `create_runner()` 回傳的 runner;未提供 runner 的 plugin MUST 維持既有 skeleton 行為(向後相容)。

#### Scenario: 提供 runner 的 plugin 走 runner 委派
- **WHEN** 一個實作 `create_runner()` 的 plugin(wifi_llapi)被執行
- **THEN** orchestrator 呼叫 `runner.run(...)` 完成整-run 與報表,不再經由 `create_reporter().run()`

#### Scenario: 未提供 runner 的 plugin 行為不變
- **WHEN** 一個未覆寫 `create_runner()`(回傳 None)的 plugin 被執行
- **THEN** 走既有 skeleton 路徑,行為與本 change 前相同

### Requirement: 解耦不改變 wifi_llapi 對外行為
runner/reporter 切分 MUST NOT 改變 `testpilot wifi_llapi` 的 CLI UX 與報表輸出。

#### Scenario: wifi_llapi 報表輸出位元級不變
- **WHEN** 解耦前後對相同 case 集執行 wifi_llapi
- **THEN** xlsx/markdown/json/html 報表關鍵欄位與 golden snapshot 一致

#### Scenario: wifi_llapi 既有測試全綠
- **WHEN** 執行既有 wifi_llapi 測試集(golden 報表 / delta / excel / summary / artifacts / reproject / orchestrator)
- **THEN** 全數通過
