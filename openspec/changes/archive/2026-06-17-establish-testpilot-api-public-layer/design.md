## Context

來源設計 spec：`docs/superpowers/specs/2026-06-17-testpilot-plugin-sdk-design.md`（Plugin SDK，P1–P4 母 spec）。

現況：`decouple-core-wifi-llapi`（#71，解耦階段一）已讓 `src/testpilot/{core,schema,reporting}` 對 plugin 零具名。但**反向洩漏**仍在——`plugins/wifi_llapi/**` 仍直接 `import testpilot.core.*` 內部符號。盤點 wifi_llapi 對 `testpilot.*` 的依賴後分為三層：

- **低風險**（spec §1 已列為公開契約符號，re-export / 上提即可）：`core.case_utils` 的 6 個 helper、`core.plugin_base.PluginBase`、`schema.case_schema`、`reporting.reporter` 報表類、`reporting.excel_adapter`、`transport.base`。
- **高風險**：`reporting/reporter.py` 的 `WifiLlapiReporter.run()` 內含**完整執行迴圈**，reach 進 `core.execution_engine.ExecutionEngine`、`core.orchestrator.build_case_session_plan`、`reporting.log_capture`。此為 spec 標記之「最大未知」，須先量測 reporter 真正需要哪些資料才能重設計。
- **非本工程層**：`core.plugin_loader.PluginLoader`（發現機制→P2）、`testpilot.cli.main`（CLI→P3）。

本 change 只處理低風險層，並用守門測試把高風險層與非本工程層明確隔離。

## Goals / Non-Goals

**Goals:**
- 立起 `testpilot.api` 作為 plugin 的唯一公開契約表面。
- 上提 / re-export 低風險公開符號，並 repoint wifi_llapi 至 `testpilot.api`。
- 以 boundary 守門測試把「契約切到哪」鎖成不可回退的事實，並明列剩餘洩漏的消除路徑。
- wifi_llapi 對外行為（CLI UX、報表輸出）位元級不變。

**Non-Goals:**
- 不重設計 reporter↔execution 邊界（高風險，另案 P1b，須先量測）。
- 不改發現機制為 entry_points（P2）、不改 CLI 解耦（P3）、不物理移出 wifi_llapi（P4）。
- 不對 `PluginBase` 加 API 版本宣告（P2）。
- 不改任何 wifi_llapi 測試語意 / case 格式。

## Decisions

### D1：`testpilot.api` 以「薄 re-export 層」實作，零新邏輯
公開層只 re-export 既有符號，不搬移實作、不加包裝邏輯。
- **理由**：搬移實作會擴大 diff 與風險，且讓「公開層 = 契約宣告」的語意混入實作變更。re-export 讓 core 私有實作可獨立演進，只要公開符號簽章不變。
- **替代方案**：把實作物理搬進 `testpilot/api/`。否決——範圍爆炸、與「最小必要變更」相違，且 core 自身仍需這些符號。
- **case_utils 的「上提」語意**：spec 說「上提為公開工具」。實作上 = `testpilot.api` re-export 該 helper，core 內部沿用原位置；公開承諾的是 `testpilot.api.stringify_step_command` 等名稱，而非 `core.case_utils` 路徑。

### D2：公開表面只收「已確認存在且穩定」的符號，不預先固化未驗證契約
本 change 匯出清單 = spec §1 與 wifi_llapi 實際消費的交集，且全部已驗證存在。
- **理由**：spec 風險「contract 過早固化」——單一 consumer 易使契約偏頗。先收已被 dogfood 消費、確認穩定者；版本化（P2）再談相容策略。

### D3：剩餘洩漏用 allow-list 守門測試隔離，而非靜默留著
boundary 測試掃 `plugins/wifi_llapi/**`，禁止 import `testpilot.core.*` / 內部報表 / 內部 schema，除非該 (模組, 符號) 在明列 allow-list。allow-list 每筆註明消除它的後續 change（P1b/P2/P3）。
- **理由**：符合使用者「不留雙軌或語意模糊地帶」取捨——剩餘洩漏是被記錄、被測試鎖定、有消除路徑的「已知債」，不是模糊地帶。新洩漏（不在 allow-list）會立即 FAIL。
- **替代方案**：不加守門測試，靠 review 把關。否決——無法防回退，契約淪為建議。

### D4：repoint 範圍 = 低風險 6 模組的所有 wifi_llapi import
凡 `plugins/wifi_llapi/**` import 自 `core.case_utils` / `core.plugin_base` / `schema.case_schema` / `reporting.reporter`（報表類與 `generate_reports`）/ `reporting.excel_adapter` / `transport.base` 者，一律改為 `from testpilot.api import ...`。
- **注意**：`reporter.py` 同時有低風險 import（case_utils、MarkdownReporter、generate_reports、load_case）與高風險 import（ExecutionEngine、build_case_session_plan、log_capture）。本 change 只 repoint 前者；後者保留原樣並登錄 allow-list。

## Risks / Trade-offs

- **[公開表面選得太小或太大]** → 緩解：以 spec §1 ∩ dogfood 實際消費為準，且全部驗證存在；版本與擴充延至 P2。
- **[repoint 漏改或改錯造成行為變動]** → 緩解：repoint 為純 import 來源變更（符號相同物件），由既有 wifi_llapi 測試（golden 報表、delta、excel 等）保證行為位元級不變；boundary 測試保證沒漏改。
- **[allow-list 變成永久藉口]** → 緩解：每筆 allow-list 標註負責消除的後續 change 名稱；P1b/P2/P3 完成時對應條目須移除，否則該 change 不算完成。
- **[reporter.py 高低風險 import 混在同檔，repoint 時誤動高風險]** → 緩解：TDD 守門測試先紅後綠；高風險符號明列於 allow-list，誤刪會讓 wifi_llapi 匯入失敗、被既有測試抓到。

## Migration Plan

1. 建 `src/testpilot/api/__init__.py`（re-export 公開符號 + `__all__`）。
2. repoint wifi_llapi 低風險 import → `testpilot.api`。
3. boundary 守門測試紅→綠。
4. 回歸：既有 wifi_llapi 測試全綠（行為不變）。
- **Rollback**：純加法 + import 來源變更，revert commit 即可；core 私有實作未動。

## Open Questions

- 無阻擋本 change 的開放問題。reporter↔execution 重設計的量測問題（spec 開放問題 #1）屬 P1b，刻意排除於本 change。
