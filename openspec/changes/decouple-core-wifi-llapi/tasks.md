## 1. 基準線（行為不變的安全網）

- [ ] 1.1 跑既有 `test_wifi_llapi_*`、`test_orchestrator_*`、`test_reporter`、`test_plugin_reporter`、`test_html_reporter` 全綠，記錄為基準
- [ ] 1.2 報表輸出薄覆蓋處補 golden snapshot（xlsx/summary/html 關鍵欄位），鎖住「位元級不變」
- [ ] 1.3 加 second-plugin smoke：用 `_template`（或 mock plugin）驗證 core 能對「不認識的 plugin」跑完報表流（目前應通過 default 路徑）

## 2. 擴充 PluginBase（向後相容、不改行為）

- [ ] 2.1 在 `core/plugin_base.py` 加 `validate_case()` / `execution_policy()` / `register_cli()` 三個 optional hook（default no-op / 中性值）
- [ ] 2.2 加 PluginBase 契約測試：default 實作不施加任何約束、不改報表
- [ ] 2.3 全測試綠（行為未變）

## 3. 報表解耦（create_reporter）

- [ ] 3.1 7 個 `reporting/wifi_llapi_*` 模組搬到 `plugins/wifi_llapi/reporting/`，更新對應測試 import
- [ ] 3.2 在 `plugins/wifi_llapi/` 實作 `WifiLlapiReporter`（含 orchestrator 搬出的 alignment/summary/artifacts 流），`plugin.create_reporter()` 回傳它
- [ ] 3.3 `orchestrator` 報表段改 `reporter = plugin.create_reporter() or DefaultReporter(); reporter.generate(...)`；`reporter.py` 改讀 generic `plugin_summary`
- [ ] 3.4 刪 `compare_0401.py`（或移 `plugins/wifi_llapi/scripts/`）
- [ ] 3.5 全測試 + golden snapshot 綠；報表輸出不變

## 4. 驗證 / audit / case-helper 解耦（validate_case）

- [ ] 4.1 `schema.validate_wifi_llapi_case` + `yaml_command_audit.py` + `case_utils` 的 official/D### → 搬到 `plugins/wifi_llapi/`，由 `plugin.validate_case()` 呼叫
- [ ] 4.2 `orchestrator`/`schema` 改呼叫 `plugin.validate_case(case)`，移除具名 import
- [ ] 4.3 全測試綠（BLOCKED/驗證行為不變）

## 5. 執行約束解耦（execution_policy）

- [ ] 5.1 `runner_selector` 的 wifi_llapi sequential/concurrency=1 約束 → wifi_llapi `plugin.execution_policy()`
- [ ] 5.2 `orchestrator` 改問 `plugin.execution_policy(case)`，移除 `_wifi_llapi_*` delegates
- [ ] 5.3 全測試綠（執行選擇行為不變）

## 6. CLI 解耦（register_cli）

- [ ] 6.1 `cli.py` 的 wifi_llapi 命令（reproject/template）→ wifi_llapi `plugin.register_cli(subparsers)`
- [ ] 6.2 `cli.py` 載入 plugin 後動態掛命令；移除 `wifi_llapi_excel`/`reproject` import
- [ ] 6.3 `testpilot wifi_llapi` 端到端 UX 不變（CLI help marker 同步、`test_wifi_llapi_plugin_runtime` 綠）

## 7. 收尾與驗收

- [ ] 7.1 `grep -r wifi_llapi src/testpilot/core src/testpilot/schema src/testpilot/reporting` 為空（加 CI 斷言測試）
- [ ] 7.2 second-plugin smoke 仍綠（core 對未知 plugin 跑完報表/驗證/執行）
- [ ] 7.3 全測試套件綠；`testpilot wifi_llapi` 真實執行輸出與基準一致
- [ ] 7.4 更新 `DESIGN.md` / plugin-dev-guide：報表/驗證/執行/CLI 皆走 hook
