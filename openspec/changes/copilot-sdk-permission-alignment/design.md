## Context

`copilot_session.py::_resolve_permission_handler`（L194-204）以 `getattr(sdk.PermissionHandler, "approve_all")` 取得 permission handler；`github-copilot-sdk 0.1.23` 的 `PermissionHandler` 是 typing alias（`Callable[[PermissionRequest, dict[str, str]], PermissionRequestResult | Awaitable[...]]`），`approve_all` 恆為 `None` → 每次 session 建立必然 raise → execution engine 每案 fallback 到 builtin classifier，且僅記錄於 per-case selection trace（silent）。

設計基準與完整需求見 `docs/superpowers/specs/2026-07-06-copilot-sdk-permission-drift-design.md`（已過 codex 對抗性審查一輪 + 修正）。

## Goals / Non-Goals

**Goals:**
- session foundation 在 SDK 0.1.x 下可成功建立（approve-all wire shape 正確）
- 建立失敗時 loud：一次性 warning + run-level degraded 標記
- SDK 契約 guard tests（wire shape 鎖定）

**Non-Goals:**
- 不做多版本 SDK 相容矩陣、不 pin 版本
- 不改 builtin-fallback 語意與 remediation 白名單
- wifi_llapi reporter 消費 degraded key（wifi 側 follow-up）
- 真機 full-run 端到端驗證（後續批次）

## Decisions

1. **只支援 0.1.x、不留雙軌**（使用者 2026-07-06 拍板）：自組 callable 回傳 `{"kind": "approved"}`；替代方案「feature-detect 雙軌 shim」被否決（多維護一條死路徑，違反不留雙軌原則）。
2. **wire shape 以測試鎖定**：`PermissionRequestResult` 是 `TypedDict(total=False)`（欄位 `kind`/`rules`），SDK `session.py` 直接回送 handler 回傳值、無 runtime validation——錯欄位不報錯也不生效。故測試必須 assert 回傳 dict 精確等於 `{"kind": "approved"}`，不得只驗 callable 被呼叫（防 false-green；codex review Critical finding）。
3. **degraded 落點 = `run_loop` 回傳 payload**：`run_plugin_cases()` 回傳 `dict[str, Any]`，新增 `agent_session_degraded: {"degraded": bool, "reason": str}` key。替代方案「寫進 RunResult/reporter meta」需動更多 schema 與 plugin 介面，超出最小必要變更。
4. **feature-detect 僅針對 `PermissionRequestResult` 可用性**：缺失 → `CopilotSDKUnavailableError("copilot.PermissionRequestResult is unavailable")`；不偵測任何 `approve_all` 形式。

## Risks / Trade-offs

- [SDK 0.2+ 再次 drift] → guard test 鎖 wire shape，drift 時測試紅（明確訊號），屆時再議
- [warning 只打一次可能被 log 洪水淹沒] → 同步落 run payload key，報表層可後續消費
- [`{"kind": "approved"}` 語意過寬（全部核准）] → 與原 `approve_all` 意圖一致；session 用途為 remediation 決策諮詢，工具權限邊界由 plugin 白名單另行把關

## Migration Plan

單 PR：改 `copilot_session.py` + `run_loop.py` degraded key + 測試 + CHANGELOG。無資料遷移；rollback = revert commit。合併後由下一次 wifi_llapi run 的 agent_trace 驗證 `session_handle.status` 不再是 failed。
