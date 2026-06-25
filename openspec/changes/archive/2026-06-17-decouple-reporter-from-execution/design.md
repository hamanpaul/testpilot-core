## Context

來源設計:`docs/superpowers/specs/2026-06-17-reporter-execution-decouple-design.md`(brainstorm 已定調)。前置 P1 公開層已 merge(PR #75)。

量測結論:`WifiLlapiReporter.run()` ≈ 90% 執行編排 + 10% 報表;`Orchestrator.run()` 把自己整個交給 reporter 驅動全程。3 筆 execution 洩漏 + `orchestrator.*` 服務耦合皆因 run loop 物理塞在「reporter」內。`execute_with_retry` 回傳結構化 `RetryResult`,故執行→推資料給 reporter 可行。

## Goals / Non-Goals

**Goals:**
- runner(執行)/ reporter(格式化)切兩塊,raw `RunResult` 當交接。
- reporter 對 execution 依賴=0(spec 母案最大未知洩漏消滅)。
- 行為位元級不變。

**Non-Goals:**
- 不上移執行迴圈進 core。
- 不把 execution primitive 提為 public `testpilot.api`(P2/P4 再議;暫以 allow-list 承載,relocate 到 runner)。
- 不碰 entry_points(P2)/CLI(P3)/物理切出(P4)/case 格式。

## Decisions

### D1:runner 持有整-run 迴圈,reporter 純格式化,raw 粒度交接
runner 做 prep+serialwrap+逐case執行+log匯出,組 raw `RunResult`(case dict + `RetryResult` + trace_path + log seq + timing + run-level),再呼叫 `reporter.generate(run_result)`。reporter 從 raw 資料自行算 band results/status/`WifiLlapiCaseResult` 與所有報表。
- **理由**:reporter 完全脫離執行;runner 近乎通用執行驅動(為日後 core-owned execution 鋪路)。raw 粒度讓 wifi 格式邏輯全留 reporter,邊界最乾淨。
- **替代**:RunResult 帶已組裝的 `WifiLlapiCaseResult`(粒度粗)。否決——runner 會沾 wifi 格式邏輯,切不乾淨。

### D2:execution import relocate 到 runner,不升 public api
`ExecutionEngine` / `build_case_session_plan` / `log_capture` 從 reporter.py 移到 runner.py,仍登錄 boundary allow-list。
- **理由**:runner 跑東西本就該用 execution(誠實落點);是否升 public 屬 P2/P4(版本化契約),此時升級會過早固化。符合 [[feedback-testpilot-core-value]] 不留模糊地帶——洩漏被測試鎖定、有消除路徑。

### D3:核心委派改 `create_runner()`,乾淨切換
`PluginBase` 加 optional `create_runner()`(default None);`orchestrator._run_via_reporter` → `_run_via_runner`。舊 `create_reporter().run()` 委派移除(不留雙軌)。
- **理由**:`create_reporter()` 回傳的 reporter 應只實作 `IReporter`(格式化),不該帶 `run()` 執行入口。`create_runner()` 是「整-run 執行」的正確契約位置。
- **相容**:無 runner 的 plugin(如 brcm,未實作 create_reporter)仍走 skeleton 路徑;已驗證僅 wifi_llapi 走此委派。

## Risks / Trade-offs

- **[行為變動(最大)]** ~200 行迴圈搬遷 → 緩解:逐段 verbatim 搬移 + 既有 golden/report 測試把關 + 先紅後綠。
- **[RunResult 欄位遺漏]** reporter 需要但 runner 沒放 → 緩解:以現 `reporter.run()` 尾段(494–582)引用的每個值反推欄位清單,RunResult 契約測試斷言齊全。
- **[委派切換誤傷其他 plugin]** → 緩解:`create_runner` default None + skeleton fallback;brcm 不走此路徑(已驗)。

## Migration Plan

1. 建 `run_result.py`(dataclass)。
2. 建 `runner.py`:搬入 run loop(execution import 落此)+ 組 RunResult + 呼叫 reporter.generate。
3. 改寫 reporter.py:`generate(run_result)` 純格式化、移除 execution import。
4. `PluginBase.create_runner()` + wifi plugin 實作 + orchestrator 委派。
5. boundary guard 加 reporter 純淨斷言;RunResult 契約測試;全套回歸。
- **Rollback**:單一 change,revert commit 即可。

## Open Questions

- prep(alignment)是否獨立第三相:本案併入 runner;日後 core-owned execution 再抽。
