## Why

wifi_llapi full-run `20260704T112950138504` 全數 415 案的 agent session foundation 建立失敗（`copilot.PermissionHandler.approve_all is unavailable`），remediation 整場 silent 降級到 builtin-fallback——core 寫死的 `PermissionHandler.approve_all` 在實裝 `github-copilot-sdk 0.1.23` 中不存在（`PermissionHandler` 是 typing alias，非 class）。連續兩輪 full-run 都是事後翻 agent_trace 才發現（#16）。

## What Changes

- 重寫 `copilot_session.py::_resolve_permission_handler`：自組 approve-all permission handler callable，回傳 wire shape 正確的 `{"kind": "approved"}`（`PermissionRequestResult` 為 `TypedDict(total=False)`，無 runtime validation，測試鎖 wire shape）
- feature-detect 對象改為 `PermissionRequestResult` 可用性；缺失時 `CopilotSDKUnavailableError` 指名缺的 symbol；**不留任何 `approve_all` 舊 API 雙軌**
- 新增 loud surfacing：run 內第一次 session 建立失敗 → 一次性 `log.warning` + `run_loop` 回傳 payload 新增 `agent_session_degraded` key（小幅 core schema 變更）
- 更新 `tests/test_copilot_session.py` 對 `approve_all` 的假設；新增 wire-shape 鎖定與缺 API 測試
- CHANGELOG `[Unreleased]` entry

## Capabilities

### New Capabilities
- `copilot-session-foundation`: copilot-sdk session foundation 的建立契約——permission handler wire shape、SDK surface feature-detect、建立失敗時的 loud surfacing 與 degraded 標記

### Modified Capabilities

（無——execution loop 的 builtin-fallback 行為與 selection trace 記錄不變）

## Impact

- `src/testpilot/core/copilot_session.py`（主修）
- `src/testpilot/core/run_loop.py` / orchestrator（degraded key 落點）
- `tests/test_copilot_session.py`（更新 + 新增）
- 依賴：`github-copilot-sdk 0.1.x`（不 pin、不新增依賴）
- 下游：wifi_llapi remediation 恢復 agent 決策能力（reporter 消費 degraded key 屬 wifi 側 follow-up，不在本 change）
