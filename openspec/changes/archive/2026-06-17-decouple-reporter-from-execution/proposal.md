## Why

P1(`establish-testpilot-api-public-layer`,PR #75 已 merge)堵了 wifi_llapi 的低風險洩漏,但刻意延後了**最大未知**:`reporting/reporter.py` 的 `WifiLlapiReporter.run()` 其實是一整段執行迴圈(serialwrap、`execute_with_retry`、session plan、trace、log seq),反向 reach `core.execution_engine.ExecutionEngine`、`core.orchestrator.build_case_session_plan`、`reporting.log_capture`(目前以 boundary allow-list 鎖住)。報表模組依賴執行引擎,contract 就不誠實——第三方 plugin 會以為 reporter 該知道怎麼跑測試。本 change(P1b)把執行與報表切開:reporter 變純格式化、execution 依賴歸零。

設計依據:`docs/superpowers/specs/2026-06-17-reporter-execution-decouple-design.md`(brainstorm 已定調)。

## What Changes

- **新增 `WifiLlapiRunner`(`plugins/wifi_llapi/runner.py`)**:接手現 `reporter.run()` 的整-run 執行迴圈(prep + serialwrap + 逐 case `execute_with_retry` + trace + log 匯出);execution import 移至此檔(誠實落點)。
- **新增 raw 粒度 `RunResult` / `CaseRunRecord`(`plugins/wifi_llapi/run_result.py`)**:執行階段「推」給報表階段的結構化交接物;只存值、無執行引擎依賴。
- **改寫 `WifiLlapiReporter`(`reporting/reporter.py`)為純格式化**:`generate(run_result)` 只做 band results / `WifiLlapiCaseResult` 組裝 / fill xlsx / alignment finalize / summary / md·json·html;**移除全部 execution import**。
- **`PluginBase` 加 optional `create_runner()`**(default `None`,向後相容);orchestrator 委派由 `create_reporter().run()` 改為 `create_runner().run()`,無 runner 的 plugin 仍走 skeleton(乾淨切換,不留雙軌)。
- **`plugins/wifi_llapi/plugin.py`** 實作 `create_runner()`。
- **boundary 守門測試新增斷言**:`reporting/reporter.py` 的 execution import 數=0。

## Capabilities

### New Capabilities
- `plugin-runner-reporter-separation`: 規範 plugin 的執行階段(runner)與報表階段(reporter)分離——runner 產出結構化 run dataset、reporter 純消費此 dataset 產出報表且不依賴執行引擎;並定義 `PluginBase.create_runner()` 委派契約。

### Modified Capabilities
<!-- 無:plugin-sdk-public-api 的 allow-list 要求文字不變(洩漏條目仍在,只是 relocate 到 runner);本案以新 capability + 守門新斷言表達 reporter 純淨。 -->

## Impact

- 新增:`plugins/wifi_llapi/runner.py`、`plugins/wifi_llapi/run_result.py`。
- 改寫:`plugins/wifi_llapi/reporting/reporter.py`(去執行化)、`plugins/wifi_llapi/plugin.py`(create_runner)。
- core 小改:`src/testpilot/core/plugin_base.py`(加 hook)、`src/testpilot/core/orchestrator.py`(委派改 runner)。
- 測試:`tests/test_plugin_sdk_api_boundary.py` 加 reporter 純淨斷言;新增 `RunResult` 契約測試;既有 wifi_llapi 報表測試保證行為位元級不變。
- 對外行為:`testpilot wifi_llapi` UX 與報表輸出**不變**。
