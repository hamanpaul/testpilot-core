## 1. TDD RED — SDK 契約測試先行

- [x] 1.1 建 mock SDK module fixture：`PermissionHandler` 為 typing alias、`PermissionRequestResult` 為 `TypedDict(total=False)`（比照 0.1.23 surface）
- [x] 1.2 RED test：`_resolve_permission_handler()` 回傳 callable 且以 `PermissionRequest` mock 呼叫回傳精確 `{"kind": "approved"}`（現行實作應 fail：raise approve_all unavailable）
- [x] 1.3 RED test：mock SDK 移除 `PermissionRequestResult` → raise `CopilotSDKUnavailableError` 且訊息含 `copilot.PermissionRequestResult is unavailable`
- [x] 1.4 RED test：注入 `permission_handler` 時原樣回傳、不觸 SDK
- [x] 1.5 清點 `tests/test_copilot_session.py` 既有 `approve_all` 假設測試，標記待改清單

## 2. 實作 — permission handler 對齊

- [x] 2.1 重寫 `_resolve_permission_handler()`：feature-detect `PermissionRequestResult` → 自組 approve-all callable（回傳 `{"kind": "approved"}`）
- [x] 2.2 移除 `PermissionHandler.approve_all` 相關程式碼與錯誤訊息（不留雙軌）
- [x] 2.3 更新 1.5 清單中的既有測試至新契約；1.1–1.4 測試轉綠

## 3. 實作 — loud surfacing

- [x] 3.1 RED test：run 內第一次 session 建立失敗 → 恰一次 `log.warning`；後續失敗不重複
- [x] 3.2 RED test：`run_plugin_cases()` 回傳 payload 含 `agent_session_degraded`（失敗 run = `{"degraded": true, "reason": ...}`；正常 run 的 falsy 形狀以測試鎖定）
- [x] 3.3 實作 orchestrator/run_loop 的 degraded 狀態追蹤與 payload key；3.1–3.2 轉綠

## 4. 收尾

- [x] 4.1 smoke：在裝有 `github-copilot-sdk 0.1.23` 的環境 import 真 SDK，`_resolve_permission_handler()` 成功回傳 callable
- [x] 4.2 全套件測試綠（core repo 測試指令）
- [x] 4.3 CHANGELOG `[Unreleased]` entry；PR body `Closes #16`
- [x] 4.4 檢查 R-18：README/docs 是否需同步（純內部行為修復，預期 `policy-exempt:docs-sync` 或無需變更）
