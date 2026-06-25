## Why

P1b 把 wifi_llapi 的整-run 執行迴圈獨立成 `WifiLlapiRunner`(plugin-side),經 `create_runner` 委派。但「plugin host 框架」的願景是 **core 主導執行、plugin 提供 hook**,而非每個 plugin 自帶迴圈。B2 把迴圈**上移進 core**(寫在 B1 的 `RunBackend` + plugin hooks 上):wifi 走 core 預設路徑(dogfood),`create_runner` 收斂為「本質不同工作」(brcm firmware 燒錄)的契約認可 override。完成後 **wifi production 對 core/schema/reporting/transport 內部依賴歸零**(boundary allow-list 清空)。

同時修正一個現行 **audit-invariant 違規**:正常 run 路徑 `runner._prepare_alignment → apply_alignment_mutations` 改寫/重命名 `plugins/wifi_llapi/cases/*.yaml`,違反 audit-mode spec「`testpilot run` SHALL NOT 修改 plugin/cases/」。本 change 將 run 路徑 alignment **唯讀化**。

設計:`docs/superpowers/specs/2026-06-18-core-owned-execution-loop-design.md`;路線圖:`docs/superpowers/plugin-sdk-decoupling-MOC.md`。前置:B1(`RunBackend`)。

## What Changes

- **新增 `src/testpilot/core/run_loop.py`**:core-owned 標準 test-case 迴圈,寫在 `RunBackend`(B1)+ plugin hooks 上,產出 `RunResult`。execution import(`ExecutionEngine`/`build_case_session_plan`)落在 core。
- **`orchestrator.run()` 委派調整**:`create_runner()` 非 None → plugin override(brcm);否則 → core `run_loop`(wifi)。**預設不再是 skeleton**。
- **新增 `PluginBase.prepare_run(case_ids) -> PreparedRun`(唯讀)**:default = `discover_cases` + case_ids 過濾;wifi 實作吸收 alignment 的**唯讀**邏輯。
- **alignment 唯讀化**:run 路徑 **不呼叫 `apply_alignment_mutations`、不寫 case 檔**;drift(原 `auto_aligned`)case **照跑**,用 in-memory 對齊 row 落點;reporter 於該 case reason **不論 pass/fail 標 `drift=blocked(需 audit)`**;持久化對齊只留 `testpilot audit apply`。
- **wifi**:`WifiLlapiRunner` 解散 → 改提供 hooks;reporter 沿用 `build_reports(run_result)` + drift 標記 + 收 xlsx-template 建立;**清掉對 `ExecutionEngine`/`build_case_session_plan`/`log_capture` 的 import**(allow-list 清空)。
- **brcm**:不動(自有 CLI + run_cases;`create_runner` 為其日後 override)。
- **守門**:補 `testpilot run` 不修改 `plugins/<plugin>/cases/` 測試;wifi production allow-list 清空斷言。
- **不改** B1 `RunBackend` / `Transport` / case YAML 格式 / 報表內容(drift 標記除外)/ audit 模組。

## Capabilities

### New Capabilities
- `core-owned-execution-loop`: 規範 core 擁有預設 test-case run 迴圈(寫在 `RunBackend` + plugin hooks 上、產 `RunResult`);plugin 透過 `prepare_run`(唯讀)等 hook 接入;run 路徑 MUST NOT 修改 case YAML(alignment 唯讀,drift 於報表標記、持久化只走 audit apply)。

### Modified Capabilities
- `plugin-runner-reporter-separation`: `create_runner` 由「主要委派路徑」改為「override」——預設改走 core run loop,而非 skeleton。

## Impact

- 新增:`src/testpilot/core/run_loop.py`、`PluginBase.prepare_run`。
- 改寫:`src/testpilot/core/orchestrator.py`(委派)、`plugins/wifi_llapi/runner.py`(解散→hooks)、`plugins/wifi_llapi/reporting/reporter.py`(drift 標記 + template)、`plugins/wifi_llapi/plugin.py`(prepare_run hook、移除 create_runner)。
- 測試:run 不改 cases/ 守門;allow-list 清空斷言;RunResult 契約;既有 golden/report 保證行為不變。
- 對外行為:`testpilot wifi_llapi` UX 與報表輸出**不變**(僅 drift case 多 reason 標記;golden fixture 已對齊不受影響)。
- 後續:B2 完成後 wifi allow-list 清空,P4 物理切出前置(連同 P2 entry_points / P3 CLI)。
