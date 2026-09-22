---
type: fix
scope: core
---
`PluginBase.run_pipeline` 與 `ExecutionEngine.execute_case_once`（agent_trace 的實際產生路徑）每個 step 在 `commands` / `outputs` 都保留一格（無指令文字或無輸出者留空字串），不再因 `if cmd:` / `if out:` 略過而錯位；之前 agent_trace 的 `attempts[].outputs` 會整體上移一格，證據被記到錯的 step 上（EIT bench 2026-09-17 D259/D402 trace 判讀誤差）。
