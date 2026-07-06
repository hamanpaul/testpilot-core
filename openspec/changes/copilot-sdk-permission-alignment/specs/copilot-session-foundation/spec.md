## ADDED Requirements

### Requirement: permission handler SHALL 以 SDK 0.1.x wire shape 自組 approve-all callable

`_resolve_permission_handler()` 在未注入自訂 handler 時，SHALL 回傳一個 callable：接收 `(PermissionRequest, dict[str, str])`、以 sync 形式回傳精確等於 `{"kind": "approved"}` 的 `PermissionRequestResult`。實作 MUST NOT 依賴任何 `PermissionHandler.approve_all` 形式的 API。

#### Scenario: SDK 0.1.x surface 下建立 handler
- **WHEN** `copilot` module 可 import 且 `PermissionRequestResult` 存在
- **THEN** `_resolve_permission_handler()` 回傳 callable
- **AND** 以任意 `PermissionRequest` 呼叫該 callable 回傳 `{"kind": "approved"}`（精確相等）

#### Scenario: 已注入自訂 handler
- **WHEN** `permission_handler` 建構時已注入
- **THEN** 原樣回傳注入值，不觸碰 SDK surface

### Requirement: SDK surface 缺失 SHALL raise 指名 symbol 的錯誤

feature-detect 的對象 SHALL 僅為 `PermissionRequestResult` 的可用性。

#### Scenario: SDK 缺 PermissionRequestResult
- **WHEN** `copilot` module 可 import 但無 `PermissionRequestResult`
- **THEN** raise `CopilotSDKUnavailableError`，訊息含 `"copilot.PermissionRequestResult is unavailable"`

### Requirement: session foundation 建立失敗 SHALL loud surfacing

session foundation 建立失敗 MUST 維持既有 builtin-fallback 行為，且 SHALL 同時：run 內第一次失敗時發出恰一次 `log.warning`（含失敗原因與「remediation 將全程 builtin-fallback」語句）、在 `run_plugin_cases()` 回傳 payload 設置 `agent_session_degraded` key。

#### Scenario: run 內第一次 session 建立失敗
- **WHEN** 任一 case 的 session foundation 建立失敗且該 run 先前無失敗記錄
- **THEN** 發出一次 `log.warning`
- **AND** run payload `agent_session_degraded == {"degraded": true, "reason": <失敗原因>}`

#### Scenario: 同 run 後續 case 再失敗
- **WHEN** 同一 run 內第二個以上 case 的 session 建立失敗
- **THEN** 不再重複 warning
- **AND** per-case selection trace 的 `session_handle` 記錄維持既有行為

#### Scenario: session 全程正常
- **WHEN** 整個 run 無 session 建立失敗
- **THEN** run payload `agent_session_degraded == {"degraded": false, "reason": ""}`（或等價 falsy 慣例，實作時擇一並以測試鎖定）
