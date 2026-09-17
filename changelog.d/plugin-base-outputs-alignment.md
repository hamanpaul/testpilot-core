---
type: fix
scope: core
---
`PluginBase.run_pipeline` 不再丟掉沒有輸出的 step（例如只做設定、沒有 key=value 的 station verb step），`outputs` 與 `commands` 維持索引對齊；之前 agent_trace 的 `attempts[].outputs` 會整體上移一格，證據被記到錯的 step 上（EIT bench 2026-09-17 D259/D402 trace 判讀誤差）。
