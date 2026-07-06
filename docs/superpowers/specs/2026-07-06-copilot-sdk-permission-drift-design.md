# copilot session permission handler 對齊 SDK 0.1.x 設計

> 日期：2026-07-06 ｜ 對應 issue：#16 ｜ repo：testpilot-core
> 佐證 run：wifi_llapi full-run `20260704T112950138504`（415 案全數 `session_handle.status=failed`）

## 問題背景（root cause）

`src/testpilot/core/copilot_session.py::_resolve_permission_handler`（L194-204）hard-code 依賴
`copilot.PermissionHandler.approve_all`。實際安裝的 `github-copilot-sdk 0.1.23` 中
`PermissionHandler` 是 **typing alias**：

```
Callable[[PermissionRequest, dict[str, str]], PermissionRequestResult | Awaitable[PermissionRequestResult]]
```

不是帶 `approve_all` classmethod 的 class → `getattr(..., "approve_all")` 恆為 `None` →
每次 session foundation 建立必然 raise `CopilotSDKUnavailableError` → 全 run remediation
無聲降級到 `builtin-fallback`（連續兩輪 full-run 都是事後翻 agent_trace 才發現）。

## 設計原則

1. **只支援現行 0.1.x API，不留雙軌**（使用者 2026-07-06 拍板）：移除舊 API 假設，不做
   class-式/callable-式 feature-detect shim。
2. session 建立失敗 → builtin-fallback 的既有安全策略**不變**；本設計只讓「失敗」變 loud、
   且在 0.1.x 下不再必然失敗。
3. 最小必要變更：只動 `copilot_session.py`、loud-surfacing 掛點、對應測試。

## 元件 1：approve-all permission handler（主修）

`_resolve_permission_handler()` 改為：

- 若 `self.permission_handler` 已注入 → 原樣回傳（現行行為保留）。
- 否則自組 approve-all callable：接收 `(PermissionRequest, dict[str, str])`，回傳
  approve 語意的 `PermissionRequestResult`。
  - `PermissionRequestResult` 的實際建構簽名（欄位名 / kind 值）於實作前對
    `github-copilot-sdk 0.1.23` 原始碼確認，**不得憑空猜欄位**。
  - 回傳值同時容許 sync 形式（SDK 型別本身容許 Awaitable，自組 handler 用 sync 即可）。
- 若 SDK 缺 `PermissionRequestResult`（或建構必要 surface 缺失）→ 仍 raise
  `CopilotSDKUnavailableError`，訊息**指名缺的 symbol**（例：
  `"copilot.PermissionRequestResult is unavailable"`）。

## 元件 2：loud surfacing（degraded 可見性）

- run 內**第一次** session foundation 建立失敗時：`log.warning` 一次（不逐案洗版），
  內容含失敗原因與「remediation 將全程 builtin-fallback」的明確語句。
- run-level metadata 增加 degraded 標記（如 `agent_session_degraded: true` + 原因字串），
  落點在 core 已有的 run summary / trace metadata 結構，供 plugin 報表與人工檢視。
- 每案 selection trace 的 `session_handle` 記錄行為維持不變。

## 測試（TDD）

mock SDK module（不依賴真 `copilot` 安裝）：

1. **0.1.x surface**：`PermissionHandler` 為 typing alias、`PermissionRequestResult` 存在
   → `_resolve_permission_handler()` 回傳 callable；以 `PermissionRequest` mock 呼叫之，
   回傳 approve 語意結果。
2. **缺 API surface**：移除 `PermissionRequestResult` → raise `CopilotSDKUnavailableError`
   且訊息指名缺的 symbol。
3. **注入 handler 優先**：`permission_handler` 已注入時不碰 SDK。
4. **loud surfacing**：第一次失敗 warning 恰好一次；degraded 標記寫入 run metadata。
5. 更新既有 `tests/test_copilot_session.py` 中對 `approve_all` 的假設。

## 驗收標準

- [ ] unit tests 全綠（含上列新測試）。
- [ ] smoke：在裝有 `github-copilot-sdk 0.1.23` 的環境 import 真 SDK，
      `_resolve_permission_handler()` 成功回傳 callable（不 raise）。
- [ ] 失敗路徑 warning 只出現一次且訊息可讀。
- [ ] CHANGELOG `[Unreleased]` 有 entry；PR body `Closes #16`。

## 約束

- 不動 execution loop 的 fallback 語意（`execution_engine` 的 builtin classifier 路徑）。
- 不引入新依賴；不 pin SDK 版本（feature-detect symbol 存在與否即可）。
- 真機 full-run 端到端驗證（remediation session 實際上工）屬後續批次，不在本 change 範圍。

## 非目標（YAGNI）

- 不做多版本 SDK 相容矩陣。
- 不改 remediation 白名單 / decision 格式。
- 不做 session 內容（prompt/tooling）優化——僅恢復 session foundation 可建立。
