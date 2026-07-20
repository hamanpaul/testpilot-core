## ADDED Requirements

### Requirement: core 擁有預設 test-case run 迴圈
testpilot core SHALL 提供預設的 test-case run 迴圈(`core/run_loop.py`),寫在 `RunBackend`(裝置存取)與 plugin hooks 之上,產出 `RunResult`。當 plugin 未提供 `create_runner()` override 時,orchestrator SHALL 走此 core 迴圈;plugin 僅透過 hook(`prepare_run` / `capture_dut_firmware_version` / `execution_policy` / `execute_step` / `create_reporter`)接入,MUST NOT 自帶整-run 迴圈。Core-owned run SHALL select the plugin runner without changing its identity, perform Azure-ready advisory planning before each deterministic case, preserve plugin-owned tier-1 remediation and capability-gated tier-2 recovery during retries, then perform bounded core analysis and write core artifacts after all final verdicts but before the unchanged plugin reporter is called.

#### Scenario: wifi_llapi 走 core 預設迴圈
- **WHEN** 執行 `testpilot wifi_llapi`(未提供 create_runner)
- **THEN** orchestrator 走 core `run_loop`,經 wifi 的 hooks 完成執行並產 `RunResult`,交 `create_reporter().build_reports()` 產報表,且 core cost report 以 additive pointer 附加在 reporter payload 之後

#### Scenario: Azure-ready case ordering
- **WHEN** a core-loop plugin case is selected on an Azure-ready run
- **THEN** core records planning before deterministic execution, preserves selected runner metadata, executes any permitted tier-2 recovery only through the plugin contract, and analyzes only after every case has a final verdict

#### Scenario: wifi production 不再依賴 core 執行內部
- **WHEN** 對 `plugins/wifi_llapi/` production(排除 tests/scripts)掃描 import
- **THEN** 無 `testpilot.core.execution_engine` / `testpilot.core.orchestrator`(build_case_session_plan)/ `testpilot.reporting.log_capture`(boundary allow-list 之 production 條目清空;執行邏輯已歸 core 迴圈)

### Requirement: prepare_run 為唯讀 hook
`PluginBase` SHALL 提供 `prepare_run(case_ids) -> PreparedRun`,default 實作為 `discover_cases` 後依 case_ids 過濾。`prepare_run` MUST 為唯讀:MUST NOT 修改 `plugins/<plugin>/cases/` 任何檔案。回傳 SHALL 含可執行 case 集與報表 artifacts。

#### Scenario: 未覆寫 prepare_run 的 plugin
- **WHEN** 一個未覆寫 `prepare_run` 的 plugin 被執行
- **THEN** 使用 default(discover + case_ids 過濾),不施加額外處理

#### Scenario: prepare_run 不寫 case 檔
- **WHEN** 任何 plugin 的 `prepare_run` 被呼叫(含 wifi alignment)
- **THEN** `plugins/<plugin>/cases/` 無任何檔案被新增/改寫/重命名

### Requirement: run 路徑不得修改 case YAML(alignment 唯讀)
`testpilot run` 路徑 MUST NOT 修改 `plugins/<plugin>/cases/*.yaml`(符合 audit-mode spec)。wifi alignment 於 run 路徑 SHALL 唯讀:in-memory 計算對齊 row 供報表落點,MUST NOT 呼叫 `apply_alignment_mutations` 或寫檔。drift(未對齊)case SHALL 照常執行並取得 pass/fail;reporter SHALL 於該 case 的 reason/comment(不論 pass/fail)標記 `drift=blocked`(需 audit)。case YAML 的持久化對齊 SHALL 僅由 `testpilot audit apply` 進行。

#### Scenario: 正常 run 不改 case 檔
- **WHEN** 執行 `testpilot wifi_llapi`(含存在 drift case 的情形)
- **THEN** `plugins/wifi_llapi/cases/` 無任何檔案變更(`git status` 乾淨)

#### Scenario: drift case 照跑且報表標記
- **WHEN** 一個 drift（未對齊）case 被執行
- **THEN** 該 case 取得正常 pass/fail 結果,且報表 reason/comment 含 `drift=blocked`(需 audit)標記

#### Scenario: 守門測試存在
- **WHEN** 檢視測試集
- **THEN** 存在一個斷言「`testpilot run` 不修改 `plugins/<plugin>/cases/`」的守門測試(補上原先缺失、被 skip 的 full-run 整合測試漏掉的這條不變式)
