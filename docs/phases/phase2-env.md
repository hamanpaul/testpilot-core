# Phase 2：Environment Management

## Scope

建立 `topology/provisioner/validator`，支援 YAML 拓撲與環境就緒檢查。

## Current Status

1. `src/testpilot/env/` 目前僅有 `__init__.py`。
2. `testbed_config` 已可解析基本設定與變數。

## Gaps

1. 無拓撲解析與裝置映射邏輯。
2. 無環境佈建與環境 gate。

## Acceptance Criteria

1. 可由 case topology 產生 device binding。
2. 可執行 setup + verify gate，並輸出失敗原因。
3. 支援最小 retry/backoff。

## Related Todo IDs

- `P2-01` ~ `P2-03`
