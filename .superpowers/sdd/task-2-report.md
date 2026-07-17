# Task 2 report

## Scope

Implemented the core-only append-only SDK usage ledger in `src/testpilot/core/usage_ledger.py` and its SDK-shaped tests in `tests/test_usage_ledger.py`.

## Behavior

- Tracks every started invocation, including setup/provider failures with zero or unavailable usage.
- Accepts only `assistant.usage` token events; `session.usage_info` is reconciliation-only.
- Uses `(session_id, api_call_id)` dedupe, with event id as a separate fallback namespace.
- Normalizes finite non-negative integral token counts and optional provider cost/duration without persisting secrets or raw payloads.
- Separates direct case allocation from shared run-analysis allocation.
- Freezes to immutable tuples and deterministic JSON journal lines; later mutation is rejected.

## Verification

- `uv run pytest -q tests/test_usage_ledger.py` — 10 passed
- `uv run ruff check src/testpilot/core/usage_ledger.py tests/test_usage_ledger.py` — passed
- `git diff --check` — passed
