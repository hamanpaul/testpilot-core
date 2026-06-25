# P1b: reporter↔execution 解耦 — 設計 spec

> 制定日期:2026-06-17
> 狀態:草案(brainstorm 已定調,待 review)
> 上游:`docs/superpowers/specs/2026-06-17-testpilot-plugin-sdk-design.md`(Plugin SDK 母 spec)P1b
> 前置:`establish-testpilot-api-public-layer`(P1 公開層,已 merge PR #75)

## Goal

把 wifi_llapi `reporting/reporter.py` 內**偽裝成 reporter 的整-run 執行迴圈**拆開:執行歸 runner、格式化歸 reporter,執行階段以結構化 `RunResult` **推**資料給 reporter。結束後 **reporter 對 execution 的依賴=0**,消滅 spec 母案標記的「最大未知」洩漏。

## Motivation(量測結論,回答母 spec 開放問題 #1)

呼叫鏈現為 `Orchestrator.run()` → `_run_via_reporter()` → `plugin.create_reporter().run(orchestrator, …)`:orchestrator 把自己整個交給「reporter」,reporter 再驅動全程。`WifiLlapiReporter.run()` ≈ **90% 執行編排 + 10% 報表**:

| reporter.run() 實際做的 | 性質 | 依賴 |
|---|---|---|
| serialwrap 起停/匯出 | 執行 | `orchestrator._start/_export/_stop_serialwrap` |
| 逐 case runner 選擇 | 執行 | `orchestrator.runner_selector` |
| session plan | 執行 | `build_case_session_plan`(core.copilot_session,選用) |
| `execute_with_retry`(真正跑測試) | 執行 | `orchestrator.execution_engine` |
| session 建立/清理 | 執行 | `orchestrator._create/_cleanup_case_session` |
| log seq 追蹤 | 執行 | `log_capture` |
| trace 寫檔 | 執行 | `ExecutionEngine.write_case_trace` |
| 填 xlsx / alignment / summary / md·json·html | 報表 | (純格式化) |

3 筆 allow-list 洩漏(`ExecutionEngine` / `build_case_session_plan` / `log_capture`)與整個 `orchestrator.*` 服務物件耦合,全因 run loop 物理塞在 plugin 的「reporter」裡。`execute_with_retry` 回傳結構化 `RetryResult`,故「執行產出 dataset → 推給 reporter」資料上可行。

## Scope

- 新增 `WifiLlapiRunner`(整-run 執行迴圈)與 raw 粒度 `RunResult` dataclass。
- `WifiLlapiReporter` 改為純格式化,**移除全部 execution import**,只吃 `RunResult`。
- `PluginBase` 加 optional `create_runner()`;orchestrator 委派改走它。
- 行為(CLI UX、xlsx/md/json/html 報表輸出)**位元級不變**。

## Non-goals

- 不把執行迴圈上移進 core(execution 暫留 plugin-side runner;母 spec 的 core-owned execution 另議)。
- 不把 execution primitive(`ExecutionEngine` 等)提為 public `testpilot.api`(P2/P4 再決定;P1b 仍以 allow-list 承載,但 relocate 到 runner)。
- 不改 case 格式 / 測試語意 / 報表內容。
- 不碰 entry_points(P2)、CLI 解耦(P3)、物理切出(P4)。

## Architecture

```
Orchestrator.run() ──委派──► WifiLlapiRunner.run(services,…)
                                 │  prep(alignment→runnable_cases, template)
                                 │  serialwrap 起停
                                 │  逐 case: select runner / session plan /
                                 │           execute_with_retry / trace / log seq
                                 ▼
                            RunResult (raw dataclass)
                                 │ push
                                 ▼
                      WifiLlapiReporter.generate(run_result)   ← 純格式化, ZERO execution import
                        band results / WifiLlapiCaseResult 組裝 / fill xlsx /
                        alignment finalize / summary / md·json·html
```

### 元件 / 檔案

1. **`plugins/wifi_llapi/run_result.py`(新)** — `RunResult` + `CaseRunRecord` dataclass(raw 粒度):
   - `CaseRunRecord`:`case: dict`、`retry: RetryResult`(verdict/comment/commands/outputs/attempts/attempts_used/diagnostic_status/remediation_history/failure_snapshot)、`source_row: int`、`trace_path: str`、`seq_start/seq_end: int|None`、`started_at/finished_at: str`、`duration_seconds: float`。
   - `RunResult`:`cases: list[CaseRunRecord]`、`run_id`、`run_date`、`plugin_name`、`fw_ver`、`fw_ver_source`、`artifact_dir: Path`、`template_path: Path`、`report_path: Path`、`agent_trace_dir: Path`、`dut_log_path`、`sta_log_path`、`timing_rows: list[dict]`、`alignment_prep: WifiLlapiAlignmentPrep`、`execution_policy: dict`。
   - 純資料,無 testpilot.core import(`RetryResult` 經由 runner 提供;dataclass 只存值,型別標註用 `Any`/字串避免 import execution)。

2. **`plugins/wifi_llapi/runner.py`(新)** — `WifiLlapiRunner`:
   - `run(orchestrator, plugin_name, case_ids, dut_fw_ver, provider_config) -> dict`:現 `reporter.run()` body 搬入(verbatim 為主)——prep、serialwrap、逐 case execute_with_retry + trace + log seq、log 匯出 → 組 `RunResult` → 呼叫 `WifiLlapiReporter().generate(run_result)` 取得最終 paths → 回傳結果 dict。
   - execution imports(`ExecutionEngine` / `build_case_session_plan` / `log_capture`)**落在此檔**(誠實落點)。

3. **`plugins/wifi_llapi/reporting/reporter.py`(改寫)** — `WifiLlapiReporter` 純格式化:
   - `generate(run_result: RunResult) -> dict[str, str]`:band results / `WifiLlapiCaseResult` 組裝 / fill xlsx / alignment finalize / summary / `generate_reports`(md·json·html);回傳 paths。
   - **移除** `ExecutionEngine` / `build_case_session_plan` / `log_capture` import。保留 `testpilot.api` 的 case helper、`MarkdownReporter`/`generate_reports`/`load_case`。

4. **`src/testpilot/core/plugin_base.py`** — 加 optional `create_runner(self) -> Any`(default `None`)。

5. **`src/testpilot/core/orchestrator.py`** — `_run_via_reporter` → `_run_via_runner`:`runner = plugin.create_runner(); if runner: return runner.run(self,…)`;無 runner 的 plugin 仍走既有 skeleton 路徑。乾淨切換,移除舊 `reporter.run()` 委派(不留雙軌)。

6. **`plugins/wifi_llapi/plugin.py`** — 實作 `create_runner()` 回傳 `WifiLlapiRunner()`。

## Boundary / allow-list 效果

- reporter.py 的 3 筆 execution import **消失**(reporter 變乾淨)。
- 同 3 筆 relocate 到 runner.py,仍登錄 allow-list(key=module+symbol,不變;由 P2/P4 決定是否升 public api)。
- 守門測試**新增斷言**:`reporting/reporter.py` 模組 execution import = 0(把「reporter 純淨」鎖成測試事實)。

## Data flow / 不變式

- runner 產出 `RunResult` 後,reporter 僅從 `RunResult` 重建現有報表;凡 reporter 現在用到的值,皆須在 `RunResult` 中。
- band results / overall_status / `WifiLlapiCaseResult` 由 reporter 從 `CaseRunRecord`(case dict + retry verdict)計算 —— 不在 runner。
- attempt-level status 充實(trace 用)留在 runner(屬執行 trace)。

## Testing(TDD)

- **RED**:`RunResult` 契約測試 — runner 產出 `RunResult` 欄位齊全;reporter 只吃 `RunResult` 即能產出報表。reporter 純淨斷言(execution import=0,擴充既有 boundary guard)。
- **安全網**:既有 wifi_llapi 測試(golden 報表 / delta / excel / summary / artifacts / reproject / orchestrator)位元級不變 —— 邏輯儘量 verbatim 搬移。
- 全套 `pytest` 綠。

## Risks

- **行為變動**(最大):~200 行迴圈搬遷易引入差異。緩解:golden 測試 + 逐段 verbatim 搬移 + `RunResult` 契約測試;先紅後綠。
- **RunResult 欄位遺漏**:reporter 需要但 runner 沒放。緩解:以現 `reporter.run()` 尾段(494–582)所引用的每個值反推欄位清單。
- **orchestrator 委派切換**:確認無 reporter/runner 的 plugin(brcm)不走此路徑(已驗:僅 wifi_llapi 實作 create_reporter)。

## 開放問題

- prep(alignment)是否該獨立為第三相?本案先併入 runner(prep 決定 runnable_cases=執行輸入);若日後 core-owned execution,再抽出。
