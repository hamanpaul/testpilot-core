# Phase 0：Scaffold

## Scope

建立最小可執行框架：目錄、CLI、plugin base、schema、stub transport、初始文件。

## Current Status

1. 主要 scaffold 皆已存在。
2. `wifi_llapi` plugin 已可被 loader 發現。
3. 基礎測試與文件已可用。

## Gaps

1. GitHub push 未標記完成。
2. 仍需持續維護文件與現況一致性。

## Acceptance Criteria

1. `python -m testpilot.cli list-plugins` 可列出 `wifi_llapi`。
2. `python -m testpilot.cli list-cases wifi_llapi` 可列出 case。
3. `docs/todos.md` 的 Phase 0 項目狀態可追蹤。

## Related Todo IDs

- `P0-01` ~ `P0-10`
