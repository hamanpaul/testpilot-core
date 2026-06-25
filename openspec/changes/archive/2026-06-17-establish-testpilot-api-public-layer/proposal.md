## Why

testpilot 要開放第三方 plugin 生態（`pip install testpilot` + `pip install their-plugin`），就必須對 plugin 承諾一個**公開、穩定、版本化的契約表面**，而非現在這種 plugin 直接 `import testpilot.core.*` 內部符號的隱性耦合。`decouple-core-wifi-llapi`（#71）已讓 core 對 plugin 零具名（解耦階段一）；但反向洩漏仍在——`wifi_llapi` 仍 reach 進 core 內部模組。本 change 是 Plugin SDK 工程 P1 的**第一個可獨立交付切片**：先立起公開界線 `testpilot.api`，並堵掉其中**低風險**的洩漏，把高風險的 reporter↔execution 重設計留給後續、需先量測的 change。

## What Changes

- **新增 `testpilot.api`** public 套件，作為 plugin contract 的唯一公開表面。凡未經 `testpilot.api` 匯出的符號，即為 core 私有、不對 plugin 承諾。本 change 匯出 spec §1 中**已確認存在且穩定**的符號：
  - 契約核心：`PluginBase`（re-export 自 `core.plugin_base`）
  - 報表：`IReporter` / `MarkdownReporter` / `JsonReporter` / `HtmlReporter` / `generate_reports`、`reporting.excel_adapter`
  - transport：`TransportBase` / `StubTransport`（`transport.base`）
  - case schema：`load_case` / `load_cases_dir` / `CaseValidationError`（`schema.case_schema`）
  - testbed：`TestbedConfig`（`core.testbed_config`）
  - **上提**的命令文字 helper：`stringify_step_command` / `step_command_lines`，與 case helper `case_band_results` / `case_matches_requested_ids` / `overall_case_status` / `sanitize_case_id`（皆 re-export 自 `core.case_utils`，作為公開工具）
- **repoint wifi_llapi** 的低風險 import：`plugins/wifi_llapi/**` 中對 `core.case_utils` / `core.plugin_base` / `schema.case_schema` / `reporting.reporter` / `reporting.excel_adapter` / `transport.base` 的 import 全改走 `testpilot.api`。
- **新增 boundary 守門測試**：掃描 `plugins/wifi_llapi/**`，凡 import `testpilot.core.*` / 內部報表 / 內部 schema 而**不在明列 allow-list** 即測試 FAIL；allow-list 每筆標註「由哪個後續 change 移除」。這把「契約切到哪」變成被測試鎖住、不會回退的事實。
- **不在本 change 範圍（由 allow-list 明確隔離，非擱置）**：
  - `core.execution_engine.ExecutionEngine`、`core.orchestrator.build_case_session_plan`、`reporting.log_capture`（`reporter.py` 的執行迴圈洩漏）→ **高風險，spec 開放問題 #1 要求先量測**，另開 change（P1b）。
  - `core.plugin_loader.PluginLoader` → 發現機制，屬 P2（entry_points）。
  - `testpilot.cli.main` → CLI 解耦，屬 P3（#70）。

## Capabilities

### New Capabilities
- `plugin-sdk-public-api`: 定義 `testpilot.api` 作為 plugin 的唯一公開契約表面，規範哪些符號對 plugin 承諾穩定、plugin 不得繞過 `testpilot.api` 直接依賴 core 內部，並以 boundary 守門測試強制此界線（含對既有未切清洩漏的明列 allow-list 與其消除路徑）。

### Modified Capabilities
<!-- 無既有 capability 的 requirement 改變；本 change 純新增公開層，wifi_llapi 對外行為位元級不變。 -->

## Impact

- 新增：`src/testpilot/api/__init__.py`（公開層；以 re-export 為主，不含新邏輯）。
- 修改（去內部依賴）：`plugins/wifi_llapi/command_resolver.py`、`plugins/wifi_llapi/plugin.py`、`plugins/wifi_llapi/reporting/reporter.py`，及其餘 wifi_llapi 模組中對上述 6 模組的 import。
- 測試：新增 `tests/test_plugin_sdk_api_boundary.py`（公開層匯出齊全 + wifi_llapi 不越界 allow-list）；既有 wifi_llapi 測試行為不變（repoint 不改語意）。
- 對外行為：`testpilot wifi_llapi` UX 與報表輸出**位元級不變**（純 import 來源變更）。
- 後續相依：P1b（reporter↔execution 解耦）、P2（entry_points 發現 + versioned contract）、P3（CLI 解耦 #70）、P4（wifi_llapi 物理切出）皆以本公開層為前置。
