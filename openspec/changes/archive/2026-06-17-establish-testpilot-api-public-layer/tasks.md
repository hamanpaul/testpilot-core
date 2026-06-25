## 1. RED — boundary 守門測試先紅

- [x] 1.1 新增 `tests/test_plugin_sdk_api_boundary.py`：斷言 `testpilot.api` 匯出全部公開符號（含 `is` 同一物件 + `__all__` 完整）
- [x] 1.2 同檔加入斷言：`plugins/wifi_llapi/**` 不得 import 低風險 6 模組（case_utils / plugin_base / case_schema / reporting.reporter / excel_adapter / transport.base），越界即 FAIL；high-risk 與 P2/P3 符號以 allow-list 放行並標註消除 change
- [x] 1.3 執行測試，確認**因 `testpilot.api` 不存在 + wifi_llapi 仍越界**而紅（紅的理由正確），擷取 RED 輸出為證據

## 2. GREEN — 建立公開層

- [x] 2.1 新增 `src/testpilot/api/__init__.py`：re-export D1/D2 清單之公開符號並宣告 `__all__`（零新邏輯）
- [x] 2.2 執行 1.1 斷言部分，確認公開層匯出檢查轉綠

## 3. GREEN — repoint wifi_llapi 低風險 import

- [x] 3.1 repoint `plugins/wifi_llapi/command_resolver.py` 與 `plugins/wifi_llapi/plugin.py` 的 `core.case_utils` import → `testpilot.api`
- [x] 3.2 repoint `plugins/wifi_llapi/reporting/reporter.py` 的低風險 import（case_utils helper、`MarkdownReporter`、`generate_reports`）→ `testpilot.api`；**保留** ExecutionEngine / build_case_session_plan / log_capture 原樣（allow-list）
- [x] 3.3 repoint 其餘 wifi_llapi 模組對 `core.plugin_base` / `schema.case_schema` / `reporting.excel_adapter` / `transport.base` 的 import → `testpilot.api`
- [x] 3.4 執行 boundary 守門測試，確認全綠（公開層齊全 + wifi_llapi 不越界 allow-list）

## 4. 回歸驗證 — 行為位元級不變

- [x] 4.1 執行既有 wifi_llapi 測試集（golden 報表、delta、excel、summary、artifacts、reproject 等）確認全綠
- [x] 4.2 執行完整 `pytest`（或 repo 既定測試入口）確認無回歸
- [x] 4.3 `grep -rn "from testpilot.core" plugins/wifi_llapi` 結果僅剩 allow-list 條目

## 5. 收尾

- [x] 5.1 requesting-code-review（含 boundary 測試、公開層、repoint diff）
- [x] 5.2 依 review 修正並 re-review 至無 Critical/Important
- [ ] 5.3 policy 檢查 → openspec archive → conventional commit → push → PR（feature/<slug> + closing keyword，R-12/R-17）
