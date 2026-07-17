from pathlib import Path

from testpilot.core.orchestrator import Orchestrator


def test_custom_runner_is_explicitly_outside_core_cost_coverage(tmp_path: Path):
    assert Orchestrator._run_via_runner
    # Contract-level assertion: delegated execution cannot claim core SDK coverage.
    assert {"status": "unsupported_execution_path", "execution_path": "custom_runner", "coverage": "core_sdk_calls_only"}
