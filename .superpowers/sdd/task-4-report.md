# Task 4 report

Implemented bounded per-case Azure planning in core.

- Added strict prompt builder/parser and trace-safe planning result types.
- Added one-shot `_plan_case()` with no-agent/circuit-breaker fail-soft states.
- Planning runs after runner selection and before deterministic engine execution.
- Preserved selected runner identity and removed core run-loop empty session creation.
- Added purpose-aware sanitized session IDs and redaction of secret-like prompt values.

Verification:

- `uv run pytest -q tests/test_copilot_session.py tests/test_run_loop_session_degraded.py tests/test_orchestrator_retry.py` (41 passed)
- `uv run ruff check src/testpilot/core/case_planning.py src/testpilot/core/orchestrator.py src/testpilot/core/run_loop.py src/testpilot/core/copilot_session.py` (passed)
