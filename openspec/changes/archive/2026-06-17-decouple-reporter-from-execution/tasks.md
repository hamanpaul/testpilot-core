## 1. RED — 契約測試先紅

- [x] 1.1 擴充 `tests/test_plugin_sdk_api_boundary.py`:新增斷言 `reporting/reporter.py` 的 execution import 數=0(`execution_engine`/`orchestrator.build_case_session_plan`/`reporting.log_capture`)
- [x] 1.2 新增 `tests/test_wifi_llapi_run_result_contract.py`:斷言 `RunResult`/`CaseRunRecord` 欄位齊全、reporter `generate(run_result)` 簽章存在且只吃 RunResult
- [x] 1.3 執行,確認因 reporter 仍含 execution import + RunResult/generate 尚未存在而紅(理由正確),擷取 RED 證據

## 2. GREEN — RunResult dataclass

- [x] 2.1 新增 `plugins/wifi_llapi/run_result.py`:`CaseRunRecord` + `RunResult` dataclass(raw 粒度,只存值、無執行引擎 import)
- [x] 2.2 跑契約測試的 RunResult 結構部分轉綠

## 3. GREEN — runner 接手 run loop

- [x] 3.1 新增 `plugins/wifi_llapi/runner.py`:`WifiLlapiRunner.run(orchestrator, plugin_name, case_ids, dut_fw_ver, provider_config)`,把現 `reporter.run()` 的執行段(prep/serialwrap/逐case execute_with_retry/trace/log seq/log匯出)verbatim 搬入,組 `RunResult`
- [x] 3.2 execution import(`ExecutionEngine`/`build_case_session_plan`/`log_capture`)落在 runner.py;runner 末端呼叫 `WifiLlapiReporter().generate(run_result)` 並回傳結果 dict

## 4. GREEN — reporter 純化

- [x] 4.1 改寫 `reporting/reporter.py`:`generate(run_result)` 做 band results/`WifiLlapiCaseResult` 組裝/fill xlsx/alignment finalize/summary/`generate_reports`
- [x] 4.2 **移除** reporter.py 全部 execution import;保留 testpilot.api 的 case helper/MarkdownReporter/generate_reports/load_case
- [x] 4.3 跑 boundary guard,確認 reporter 純淨斷言轉綠

## 5. GREEN — 委派接線

- [x] 5.1 `src/testpilot/core/plugin_base.py` 加 optional `create_runner()`(default None)
- [x] 5.2 `src/testpilot/core/orchestrator.py`:`_run_via_reporter` → `_run_via_runner`,委派 `create_runner().run()`;無 runner 走 skeleton;移除舊 reporter.run 委派
- [x] 5.3 `plugins/wifi_llapi/plugin.py` 實作 `create_runner()` 回傳 `WifiLlapiRunner()`

## 6. 回歸驗證 — 行為位元級不變

- [x] 6.1 既有 wifi_llapi 測試集全綠(golden/delta/excel/summary/artifacts/reproject/orchestrator)
- [x] 6.2 全套 `pytest` 綠,無回歸
- [x] 6.3 boundary guard:reporter.py execution import=0;allow-list 的 3 筆現由 runner.py 承載

## 7. 收尾(workflow 後段)

- [ ] 7.1 requesting-code-review(多視角:正確性 / 行為保真 / 契約純淨)
- [ ] 7.2 依 review 修正並 re-review 至無 Critical/Important
- [ ] 7.3 openspec archive → policy → conventional commit → push → PR(feature/<slug> + closing keyword,R-12/R-17)
