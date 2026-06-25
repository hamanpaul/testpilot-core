# Phase 3：Core Engine

## Scope

完整化 test runner、monitor、reporter 與判讀合併策略。

## Current Status

1. Orchestrator 內已有 `wifi_llapi` 專屬 run loop。
2. Wifi_LLAPI Excel reporter 已落地。
3. monitor 與 verdict merge 尚未實作。

## Gaps

1. 缺乏獨立 monitor 子系統。
2. 缺少 `plugin.evaluate + agent audit` 合併裁決流程。
3. 缺少 post-run remediation loop。

## Acceptance Criteria

1. 可追蹤每步執行事件與異常。
2. 可輸出最終裁決 `Pass/Fail/Inconclusive`。
3. 支援測後修正與重測入口。

## Related Todo IDs

- `P3-01` ~ `P3-05`
