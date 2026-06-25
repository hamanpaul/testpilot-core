# plugin-sdk-public-api Specification

## Purpose
定義 `testpilot.api` 作為 plugin 的唯一公開契約表面:規範哪些符號對 plugin 承諾穩定、plugin MUST 透過 `testpilot.api`(而非直接 reach 進 core/schema/reporting/transport 內部)取用,並以 boundary 守門測試強制此界線。未經 `testpilot.api` 匯出之符號即為 core 私有,不對 plugin 承諾。此為 Plugin SDK 工程(P1–P4)的公開層基礎。

## Requirements
### Requirement: testpilot.api 為 plugin 的唯一公開契約表面
testpilot SHALL 提供 `testpilot.api` 套件，作為 plugin 唯一被承諾穩定的公開符號來源。`testpilot.api` MUST 匯出以下符號（皆 re-export 自 core/schema/reporting/transport，且須與其原實作為同一物件）：

- 契約核心：`PluginBase`
- 報表：`IReporter`、`MarkdownReporter`、`JsonReporter`、`HtmlReporter`、`generate_reports`
- excel：`reporting.excel_adapter` 之公開符號
- transport：`TransportBase`、`StubTransport`
- case schema：`load_case`、`load_cases_dir`、`CaseValidationError`
- testbed：`TestbedConfig`
- CLI：`CliRegistrar`、`get_orchestrator`、`run_plugin_cases`
- 命令文字 helper：`stringify_step_command`、`step_command_lines`
- case helper：`case_band_results`、`case_matches_requested_ids`、`overall_case_status`、`sanitize_case_id`

凡未經 `testpilot.api` 匯出之符號，即為 core 私有，不對 plugin 承諾穩定。

#### Scenario: 公開符號可由 testpilot.api 匯入
- **WHEN** 對上列每個符號執行 `from testpilot.api import <symbol>`
- **THEN** 匯入成功，且該符號 `is` 其原模組（core/schema/reporting/transport）匯出的同一物件

#### Scenario: testpilot.api 宣告 __all__
- **WHEN** 讀取 `testpilot.api.__all__`
- **THEN** 其內容涵蓋上列所有公開符號，且每個名稱皆能於 `testpilot.api` 命名空間解析

### Requirement: plugin 不得繞過 testpilot.api 直接依賴 core 內部
`plugins/wifi_llapi/` 之 production 模組（排除其自帶 `tests/`、`scripts/`）MUST NOT import `testpilot.core.*`、`testpilot.schema.*`、`testpilot.reporting.*` 或 `testpilot.transport.*` 之內部符號（涵蓋 `from X import ...` 與 plain `import X`），除非該 (模組, 符號) 列於明示之 boundary allow-list。凡有公開等價符號者，MUST 改走 `testpilot.api`。

#### Scenario: wifi_llapi 低風險依賴改走公開層
- **WHEN** 對 `plugins/wifi_llapi/` production 模組（排除 `tests/`、`scripts/`）grep `from testpilot.core.case_utils`、`from testpilot.core.plugin_base`、`from testpilot.schema.case_schema import (load_case|load_cases_dir|CaseValidationError|validate_case)`、`from testpilot.reporting.reporter`、`from testpilot.reporting.excel_adapter`、`from testpilot.transport.base`
- **THEN** 無任何結果（皆已 repoint 至 `testpilot.api`）

#### Scenario: 越界依賴被守門測試阻擋
- **WHEN** `plugins/wifi_llapi/` production 模組出現一筆對 guarded 命名空間（`testpilot.core/schema/reporting/transport`）的 `from`-import 或 plain `import`，且不在 allow-list
- **THEN** boundary 守門測試 FAIL

#### Scenario: 既有未切清洩漏以 allow-list 明列且標註消除路徑
- **WHEN** 檢視 boundary 守門測試之 allow-list
- **THEN** 其僅含 production code 實際殘留之已知洩漏並各標註消除路徑：`core.execution_engine.ExecutionEngine`、`core.orchestrator.build_case_session_plan`、`reporting.log_capture`（皆 P1b reporter↔execution 解耦）、`schema.case_schema._require_non_empty_string`、`schema.case_schema._validate_string_list`（schema 驗證契約另案）；`plugin_loader` / `cli` 僅出現於 wifi_llapi 自帶 tests（不在守門範圍），故不列入 production allow-list

### Requirement: 公開層化不改變 wifi_llapi 對外行為
建立 `testpilot.api` 與 repoint MUST NOT 改變 `testpilot wifi_llapi` 的 CLI UX 與報表輸出（純 import 來源變更）。

#### Scenario: wifi_llapi 既有測試全綠
- **WHEN** 於 repoint 後執行既有 wifi_llapi 測試集（golden 報表、delta、excel、summary 等）
- **THEN** 全數通過，輸出與 repoint 前一致
