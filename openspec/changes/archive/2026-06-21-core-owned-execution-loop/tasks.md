## 1. RED — 契約 + audit-invariant 守門先紅

- [x] 1.1 新增守門測試:`testpilot run` 不修改 `plugins/<plugin>/cases/`(audit-invariant);擴充 boundary 守門斷言 wifi production 不再 import `execution_engine`/`build_case_session_plan`/`log_capture`
- [x] 1.2 新增 `core/run_loop` + `prepare_run` 契約測試(run_loop 可呼叫、prepare_run 唯讀回傳 PreparedRun)
- [x] 1.3 執行確認因 run_loop/prepare_run 未存在 + wifi 仍改檔/仍 import execution 而紅(理由正確),擷取 RED

## 2. GREEN — prepare_run hook(唯讀)

- [x] 2.1 `PluginBase.prepare_run(case_ids) -> PreparedRun`(default = discover + case_ids 過濾)
- [x] 2.2 wifi 實作 `prepare_run`:吸收 `_prepare_alignment` 唯讀邏輯(`align_case` 計算對齊 row、blocked/skipped/summary),**移除 `apply_alignment_mutations` 呼叫、不寫檔**;回傳 runnable(含 `drift` 旗標 + in-memory 對齊 row)+ artifacts

## 3. GREEN — core/run_loop.py

- [x] 3.1 新增 `src/testpilot/core/run_loop.py`:把現 `WifiLlapiRunner.run` 的通用段(RunBackend 生命週期、runner_select、session plan、execute_with_retry、trace、log seq、組 CaseRunRecord/RunResult)搬入;execution import 落 core
- [x] 3.2 `CaseRunRecord` 帶 `drift` 旗標(從 prepared 傳遞);run_loop 末端 `plugin.create_reporter().build_reports(RunResult)`

## 4. GREEN — orchestrator 委派 + wifi 收尾

- [x] 4.1 `orchestrator.run()`:`create_runner()` 非 None → override;否則 → `run_loop`(注入 run_backend + services);移除舊「create_runner→否則 skeleton」邏輯
- [x] 4.2 wifi:解散 `WifiLlapiRunner`;`plugin.py` 移除 `create_runner`、加 `prepare_run`;reporter `build_reports` 加 drift 標記輸出 + 收 xlsx-template 建立
- [x] 4.3 移除 wifi production 對 `ExecutionEngine`/`build_case_session_plan`/`log_capture` 的 import(allow-list 清空)

## 5. 回歸驗證 — 行為位元級不變

- [x] 5.1 守門:run 不改 cases/(跑後 `git status` 乾淨)、wifi allow-list 清空斷言全綠
- [x] 5.2 golden 報表測試全綠(fixture 已對齊無 drift,輸出不變)
- [x] 5.3 drift case 測試:照跑取得 verdict + reason 含 `drift=blocked`
- [x] 5.4 全套 `pytest` 綠;`grep` 確認 wifi production 無 execution/serialwrap/log_capture 具名

## 6. 收尾(workflow 後段)

- [x] 6.1 requesting-code-review(行為保真 / 迴圈正確 / audit-invariant / 契約純淨)
- [x] 6.2 receiving-code-review + re-review 至無 Critical/Important
- [x] 6.3 openspec archive → policy → conventional commit → push → PR(R-12/R-17)
