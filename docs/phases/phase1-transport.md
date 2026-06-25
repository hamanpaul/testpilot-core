# Phase 1：Transport Layer

## Scope

實作可用於 DUT/STA/Endpoint 的 transport：`serial`、`adb`、`ssh`、`network utils`。

## Current Status

1. 僅有 `TransportBase` 與 `StubTransport`。
2. 尚未有實際 serialwrap/adb/ssh/network 實作。

## Gaps

1. 沒有真實連線與命令執行。
2. 沒有統一 timeout/retry/error mapping。

## Acceptance Criteria

1. 每個 transport 均有 connect/execute/disconnect 與錯誤碼策略。
2. 可在同一 case 中混用多 transport。
3. 具備最小單元測試。

## Related Todo IDs

- `P1-01` ~ `P1-04`
