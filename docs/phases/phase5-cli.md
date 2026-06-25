# Phase 5：CLI & Integration

## Scope

強化 CLI、整合測試與 plugin agent case-level 選擇/降級留痕。

## Current Status

1. CLI 已有 `run/list` 與 `wifi-llapi build-template-report`。
2. Orchestrator 對 `wifi_llapi` 已有專屬流程。
3. `wifi_llapi` 已落地每個 test case 各自呼叫 agent（sequential）。
4. 已落地 retry-aware timeout 與 per-case trace artifact。

## Gaps

1. 非 `wifi_llapi` plugin 仍為 skeleton run。
2. integration tests（mock transport 的 broader coverage）尚未補齊。

## Acceptance Criteria

1. CLI 行為與文件一致。
2. 具備 integration tests（mock transport + 主要流程）。
3. 每個 case 都有獨立的 agent selection/fallback trace 可供稽核。
4. scheduler 可保證 sequential（`max_concurrency=1`）。
5. case failure 採 retry 後 fail and continue，不中止整批 run。

## Related Todo IDs

- `P5-01` ~ `P5-09`
