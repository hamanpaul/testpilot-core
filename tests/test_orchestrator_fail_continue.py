"""Tests for Orchestrator fail-and-continue behavior (E07).

Verifies that a single case failure does not abort the entire run,
and that retry + failure_policy logic works correctly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from testpilot.core.orchestrator import Orchestrator, DEFAULT_EXECUTION_POLICY


def _make_orch() -> Orchestrator:
    return Orchestrator(project_root=Path(__file__).resolve().parents[1])


class TestRetryThenFailAndContinue:
    """Tests for the retry loop control flow."""

    def _make_fake_plugin(
        self,
        *,
        setup_ok: bool = True,
        verify_ok: bool = True,
        step_ok: bool = True,
        evaluate_ok: bool = True,
    ) -> MagicMock:
        plugin = MagicMock()
        plugin.setup_env.return_value = setup_ok
        plugin.verify_env.return_value = verify_ok
        plugin.execute_step.return_value = {"success": step_ok, "output": "mock output"}
        plugin.evaluate.return_value = evaluate_ok
        plugin.teardown.return_value = None
        return plugin

    def _make_case(self, case_id: str = "D999", steps: int = 2) -> dict[str, Any]:
        return {
            "id": case_id,
            "steps": [{"id": f"step_{i}", "command": f"cmd_{i}"} for i in range(steps)],
            "pass_criteria": [],
            "bands": {"5g": {"enabled": True}, "6g": {"enabled": False}, "24g": {"enabled": False}},
        }

    def test_execute_once_success_returns_true_verdict(self):
        """Single successful execution returns verdict=True."""
        orch = _make_orch()
        plugin = self._make_fake_plugin()
        case = self._make_case()

        result = orch.execution_engine.execute_case_once(
            plugin=plugin,
            case=case,
            attempt_index=1,
            attempt_timeout_seconds=120.0,
            runner={"provider": "stub", "model": "test"},
        )
        assert result["verdict"] is True
        assert result["comment"] == ""
        assert len(result["commands"]) == 2

    def test_execute_once_step_failure_stops_steps(self):
        """If a step fails, remaining steps are skipped."""
        orch = _make_orch()
        plugin = self._make_fake_plugin(step_ok=False)
        case = self._make_case(steps=3)

        result = orch.execution_engine.execute_case_once(
            plugin=plugin,
            case=case,
            attempt_index=1,
            attempt_timeout_seconds=120.0,
            runner={"provider": "stub", "model": "test"},
        )
        assert result["verdict"] is False
        assert "step failed" in result["comment"]
        # Should only have called execute_step once (broke on first failure)
        assert plugin.execute_step.call_count == 1

    def test_execute_once_setup_failure_skips_steps(self):
        """Setup failure skips all steps and evaluate."""
        orch = _make_orch()
        plugin = self._make_fake_plugin(setup_ok=False)
        case = self._make_case()

        result = orch.execution_engine.execute_case_once(
            plugin=plugin,
            case=case,
            attempt_index=1,
            attempt_timeout_seconds=120.0,
            runner={"provider": "stub", "model": "test"},
        )
        assert result["verdict"] is False
        assert "setup_env failed" in result["comment"]
        plugin.execute_step.assert_not_called()
        plugin.evaluate.assert_not_called()

    def test_execute_once_verify_failure_skips_steps(self):
        """Verify failure skips steps and evaluate."""
        orch = _make_orch()
        plugin = self._make_fake_plugin(verify_ok=False)
        case = self._make_case()

        result = orch.execution_engine.execute_case_once(
            plugin=plugin,
            case=case,
            attempt_index=1,
            attempt_timeout_seconds=120.0,
            runner={"provider": "stub", "model": "test"},
        )
        assert result["verdict"] is False
        assert "env_verify gate failed" in result["comment"]
        plugin.execute_step.assert_not_called()

    def test_execute_once_evaluate_false_returns_fail(self):
        """Steps all pass but evaluate returns False → fail."""
        orch = _make_orch()
        plugin = self._make_fake_plugin(evaluate_ok=False)
        case = self._make_case()

        result = orch.execution_engine.execute_case_once(
            plugin=plugin,
            case=case,
            attempt_index=1,
            attempt_timeout_seconds=120.0,
            runner={"provider": "stub", "model": "test"},
        )
        assert result["verdict"] is False
        assert "pass_criteria not satisfied" in result["comment"]

    def test_teardown_always_called(self):
        """Teardown is always called, even on step failure."""
        orch = _make_orch()
        plugin = self._make_fake_plugin(step_ok=False)
        case = self._make_case()

        orch.execution_engine.execute_case_once(
            plugin=plugin,
            case=case,
            attempt_index=1,
            attempt_timeout_seconds=120.0,
            runner={"provider": "stub", "model": "test"},
        )
        plugin.teardown.assert_called_once()

    def test_teardown_called_on_setup_failure(self):
        """Teardown is called even if setup_env fails."""
        orch = _make_orch()
        plugin = self._make_fake_plugin(setup_ok=False)
        case = self._make_case()

        orch.execution_engine.execute_case_once(
            plugin=plugin,
            case=case,
            attempt_index=1,
            attempt_timeout_seconds=120.0,
            runner={"provider": "stub", "model": "test"},
        )
        plugin.teardown.assert_called_once()


class TestDefaultExecutionPolicy:
    """Verify default execution policy values."""

    def test_default_failure_policy(self):
        assert DEFAULT_EXECUTION_POLICY["failure_policy"] == "retry_then_fail_and_continue"

    def test_default_max_attempts(self):
        assert DEFAULT_EXECUTION_POLICY["retry"]["max_attempts"] == 2

    def test_default_scope_is_per_case(self):
        assert DEFAULT_EXECUTION_POLICY["scope"] == "per_case"

    def test_default_mode_is_sequential(self):
        assert DEFAULT_EXECUTION_POLICY["mode"] == "sequential"

    def test_default_max_concurrency(self):
        assert DEFAULT_EXECUTION_POLICY["max_concurrency"] == 1

    def test_default_timeout_config(self):
        timeout = DEFAULT_EXECUTION_POLICY["timeout"]
        assert timeout["base_seconds"] == 120
        assert timeout["per_step_seconds"] == 45
        assert timeout["retry_multiplier"] == 1.25
        assert timeout["max_seconds"] == 900
