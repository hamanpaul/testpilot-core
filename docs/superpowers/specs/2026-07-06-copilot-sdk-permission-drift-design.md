# copilot session permission handler 對齊 SDK 0.1.x 設計

> 日期：2026-07-06 ｜ 對應 issue：#16 ｜ repo：testpilot-core
> 佐證 run：wifi_llapi full-run `20260704T112950138504`（415 案全數 `session_handle.status=failed`）
> 2026-07-17 supersession：一般 session degraded marker 保留，但「整場
> builtin-fallback」已由 core #4 的獨立 tool-denied tier-2 one-shot policy 取代；
> current authority 見 `2026-07-17-tier2-env-recovery-design.md`。

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
2. session 建立失敗仍須 loud 並留下 degraded marker；後續 remediation 依 current
   tier-1/tier-2 policy 執行，不再宣告整場 builtin-fallback。
3. 最小必要變更：只動 `copilot_session.py`、loud-surfacing 掛點、對應測試。

## 元件 1：approve-all permission handler（主修）

`_resolve_permission_handler()` 改為：

- 若 `self.permission_handler` 已注入 → 原樣回傳（現行行為保留）。
- 否則自組 approve-all callable：接收 `(PermissionRequest, dict[str, str])`，回傳
  approve 語意的 `PermissionRequestResult`。
  - **wire shape（adversarial review 確認，0.1.23 `types.py`）**：
    `PermissionRequestResult` 是 `TypedDict(total=False)`，欄位 `kind` / `rules`；
    approve 的唯一正確形狀是 **`{"kind": "approved"}`**。TypedDict 不做 runtime
    validation、SDK `session.py` 直接回送 handler 回傳值——錯欄位（如
    `behavior="allow"`）不會報錯但也不會被視為 approve，**測試必須鎖 wire shape**
    （assert 回傳 dict == `{"kind": "approved"}`），不得只驗 callable 有被呼叫。
  - 回傳值用 sync 形式（SDK 型別容許 Awaitable，自組 handler 不需要）。
- feature-detect 的對象**只有 `PermissionRequestResult` 的可用性**（不再偵測任何
  `approve_all` symbol）：SDK 缺 `PermissionRequestResult` → raise
  `CopilotSDKUnavailableError`，訊息指名缺的 symbol（例：
  `"copilot.PermissionRequestResult is unavailable"`）。

## 元件 2：loud surfacing（degraded 可見性）

- run 內**第一次** session foundation 建立失敗時：`log.warning` 一次（不逐案洗版），
  只含穩定 exception type，不保存 raw provider/SDK exception text。
- **run-level 落點（adversarial review 指出現行結構無此欄位，需新增）**：
  `run_loop` 的回傳 payload 是 `dict[str, Any]`（`run_loop.py::run_plugin_cases`），
  新增 key `agent_session_degraded: {"degraded": bool, "reason": str}`——由
  orchestrator/session 管理層在第一次失敗時設置。此為**小幅 core schema 變更**，
  屬本 change 範圍。
- plugin reporter 是否消費此 key 屬 wifi_llapi 側 follow-up，不在本 change 範圍；
  本 change 的可驗收面是 warning log + run payload key 存在且值正確。
- 每案 selection trace 的 `session_handle` 記錄行為維持不變。

## 測試（TDD）

mock SDK module（不依賴真 `copilot` 安裝）：

1. **0.1.x surface + wire shape lock**：`PermissionHandler` 為 typing alias、
   `PermissionRequestResult` 存在 → `_resolve_permission_handler()` 回傳 callable；
   以 `PermissionRequest` mock 呼叫之，**assert 回傳值精確等於 `{"kind": "approved"}`**
   （防 false-green：只驗「被呼叫」不足）。
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
- 不引入新依賴；不 pin SDK 版本（feature-detect 僅針對 `PermissionRequestResult`
  可用性，與「不留雙軌」原則一致——不偵測、不相容任何 `approve_all` 形式的舊 API）。
- 真機 full-run 端到端驗證（remediation session 實際上工）屬後續批次，不在本 change 範圍。

## 非目標（YAGNI）

- 不做多版本 SDK 相容矩陣。
- 不改 remediation 白名單 / decision 格式。
- 不做 session 內容（prompt/tooling）優化——僅恢復 session foundation 可建立。
