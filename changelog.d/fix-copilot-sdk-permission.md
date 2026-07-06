---
type: fix
scope: core
---
copilot session foundation 對齊 `github-copilot-sdk` 0.1.x：實裝的 0.1.23 `PermissionHandler` 是 typing alias（非帶 `approve_all` 的 class），使每次 session 建立必然 raise → remediation silent 降級 builtin-fallback。改為 feature-detect `PermissionRequestResult` 自組 approve-all handler（wire shape `{"kind": "approved"}`，測試鎖形狀防 false-green），移除舊 `approve_all` 雙軌；session 建立失敗改一次性 loud warning + `run_loop` payload `agent_session_degraded` key（run-scoped，`run()` 入口重置）。(#16)
