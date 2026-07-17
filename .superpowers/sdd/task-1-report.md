# Task 1 implementation report

Status: COMPLETE

Implemented Azure-only runtime resolution and packaging in core only:

- Added `AzureAgentState`, `AzureAgentStatus`, `AzureAgentRuntime`, and strict environment resolution.
- Removed the `--azure` interactive flag and OAuth fallback path; CLI injects the resolved runtime automatically.
- Kept provider secrets private to the runtime and out of CLI context/public summaries.
- Added Azure runtime injection to the orchestrator and prevented tier-2 setup when runtime is not Azure-ready.
- Removed the core run loop's eager ordinary-session creation; case planning now receives the Azure runtime and forces deployment/provider.
- Added mandatory `github-copilot-sdk>=0.1.23,<0.2` dependency and refreshed `uv.lock`.

Validation:

```text
uv run ruff check src/testpilot/core/azure_auth.py src/testpilot/core/orchestrator.py src/testpilot/core/copilot_session.py src/testpilot/cli.py src/testpilot/cli_support.py src/testpilot/core/run_loop.py
All checks passed!

uv run pytest -q tests/test_azure_auth.py tests/test_cli_plugin_registration.py tests/test_copilot_session.py tests/test_orchestrator_session_degraded.py tests/test_run_loop_session_degraded.py tests/test_tier2_recovery_integration.py
57 passed

uv run python -c 'from copilot import CopilotSession; assert callable(CopilotSession.send_and_wait); assert callable(CopilotSession.on)'
PASS

uv build --wheel
Successfully built wheel
```

Commit: `feat(agent): 收斂 Azure-only 自動啟用與 SDK runtime`

Concern: existing unrelated `openspec/changes/azure-only-agent-cost-report/` remains untracked and was not included in this task commit.
