"""Boundary tests: control flow (hooks, retry, timeout) × verdict determination."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, call

import pytest

from testpilot.core.case_utils import band_results, overall_case_status
from testpilot.core.execution_engine import ExecutionEngine, RetryResult
from testpilot.core.hook_policy import (
    HookContext,
    HookDispatcher,
    HookPolicyConfig,
    HookResult,
)


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

def _make_case(case_id: str = "D999", steps: int = 2) -> dict[str, Any]:
    return {
        "id": case_id,
        "steps": [{"id": f"step_{i}", "command": f"cmd_{i}"} for i in range(steps)],
        "pass_criteria": [],
    }


def _make_plugin(
    *,
    setup_ok: bool = True,
    verify_ok: bool = True,
    step_ok: bool = True,
    evaluate_ok: bool = True,
) -> MagicMock:
    plugin = MagicMock()
    plugin.setup_env.return_value = setup_ok
    plugin.verify_env.return_value = verify_ok
    plugin.execute_step.return_value = {"success": step_ok, "output": "mock"}
    plugin.evaluate.return_value = evaluate_ok
    plugin.teardown.return_value = None
    return plugin


_RUNNER: dict[str, Any] = {"provider": "stub", "model": "test"}

_DEFAULT_POLICY: dict[str, Any] = {
    "retry": {"max_attempts": 1},
    "failure_policy": "retry_then_fail_and_continue",
    "timeout": {
        "base_seconds": 120.0,
        "per_step_seconds": 45.0,
        "retry_multiplier": 1.25,
        "max_seconds": 900.0,
    },
}


def _policy_with(overrides: dict[str, Any]) -> dict[str, Any]:
    """Deep-merge *overrides* into the default execution policy."""
    p: dict[str, Any] = {
        "retry": dict(_DEFAULT_POLICY["retry"]),
        "failure_policy": _DEFAULT_POLICY["failure_policy"],
        "timeout": dict(_DEFAULT_POLICY["timeout"]),
    }
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(p.get(k), dict):
            p[k].update(v)
        else:
            p[k] = v
    return p


@pytest.fixture()
def engine() -> ExecutionEngine:
    """Engine with hooks disabled (default policy)."""
    return ExecutionEngine(config=MagicMock())


@pytest.fixture()
def hooked_engine() -> tuple[ExecutionEngine, HookDispatcher]:
    """Engine with all hooks enabled and its dispatcher."""
    policy = HookPolicyConfig(
        enabled_hooks={"pre_case", "post_case", "pre_step", "post_step", "on_failure", "on_retry"},
        fail_open=True,
    )
    dispatcher = HookDispatcher(policy)
    eng = ExecutionEngine(config=MagicMock(), hook_dispatcher=dispatcher)
    return eng, dispatcher


# ===================================================================
# 1. Hook-verdict interaction
# ===================================================================

class TestHookVerdictInteraction:
    """Hooks that affect or observe verdict outcomes."""

    def test_pre_step_hook_halts_verdict_false(self, hooked_engine: tuple[ExecutionEngine, HookDispatcher]) -> None:
        eng, dispatcher = hooked_engine
        dispatcher.register(
            "pre_step",
            lambda ctx, data: HookResult(proceed=False, advice="safety halt"),
        )
        plugin = _make_plugin()
        result = eng.execute_case_once(
            plugin=plugin,
            case=_make_case(),
            attempt_index=1,
            attempt_timeout_seconds=120.0,
            runner=_RUNNER,
        )
        assert result["verdict"] is False
        assert "hook" in result["comment"].lower()
        assert "safety halt" in result["comment"]
        plugin.execute_step.assert_not_called()

    def test_on_failure_hook_does_not_prevent_retry(self, hooked_engine: tuple[ExecutionEngine, HookDispatcher]) -> None:
        eng, dispatcher = hooked_engine
        on_failure_calls: list[dict[str, Any]] = []
        dispatcher.register(
            "on_failure",
            lambda ctx, data: (on_failure_calls.append(data), HookResult(proceed=True))[1],
        )

        call_count = 0

        def step_side_effect(case: Any, step: Any, topology: Any) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            # Attempt 1 step_0 fails (call 1); attempt 2 steps succeed (calls 2+)
            if call_count <= 1:
                return {"success": False, "output": "fail"}
            return {"success": True, "output": "ok"}

        plugin = _make_plugin()
        plugin.execute_step.side_effect = step_side_effect
        plugin.evaluate.return_value = True

        policy = _policy_with({"retry": {"max_attempts": 2}})
        result = eng.execute_with_retry(
            plugin=plugin, case=_make_case(steps=2), runner=_RUNNER, execution_policy=policy,
        )
        assert len(on_failure_calls) >= 1
        assert result.verdict is True

    @pytest.mark.parametrize(
        ("plugin_kwargs", "expected_phase"),
        [
            ({"setup_ok": False}, "setup_env"),
            ({"verify_ok": False}, "verify_env"),
            ({"evaluate_ok": False}, "evaluate"),
        ],
    )
    def test_on_failure_hook_receives_non_step_failures(
        self,
        hooked_engine: tuple[ExecutionEngine, HookDispatcher],
        plugin_kwargs: dict[str, Any],
        expected_phase: str,
    ) -> None:
        eng, dispatcher = hooked_engine
        phases: list[str] = []
        dispatcher.register(
            "on_failure",
            lambda ctx, data: (phases.append(str(data.get("phase", ""))), HookResult())[1],
        )
        plugin = _make_plugin(**plugin_kwargs)
        result = eng.execute_case_once(
            plugin=plugin,
            case=_make_case(),
            attempt_index=1,
            attempt_timeout_seconds=120.0,
            runner=_RUNNER,
        )
        assert result["verdict"] is False
        assert phases == [expected_phase]

    def test_post_case_hook_receives_correct_verdict(self, hooked_engine: tuple[ExecutionEngine, HookDispatcher]) -> None:
        eng, dispatcher = hooked_engine
        captured: list[dict[str, Any]] = []
        dispatcher.register("post_case", lambda ctx, data: (captured.append(data), HookResult())[1])

        plugin = _make_plugin(evaluate_ok=True)
        eng.execute_with_retry(
            plugin=plugin, case=_make_case(), runner=_RUNNER, execution_policy=_DEFAULT_POLICY,
        )
        assert len(captured) == 1
        assert captured[0]["verdict"] is True

        captured.clear()
        plugin2 = _make_plugin(evaluate_ok=False)
        eng.execute_with_retry(
            plugin=plugin2, case=_make_case(), runner=_RUNNER, execution_policy=_DEFAULT_POLICY,
        )
        assert len(captured) == 1
        assert captured[0]["verdict"] is False

    def test_hooks_disabled_execution_proceeds(self, engine: ExecutionEngine) -> None:
        plugin = _make_plugin(evaluate_ok=True)
        result = engine.execute_case_once(
            plugin=plugin,
            case=_make_case(),
            attempt_index=1,
            attempt_timeout_seconds=120.0,
            runner=_RUNNER,
        )
        assert result["verdict"] is True
        assert result["comment"] == ""

    def test_execute_case_once_records_resolved_step_commands(self, engine: ExecutionEngine) -> None:
        plugin = _make_plugin(evaluate_ok=True)
        plugin.execute_step.side_effect = [
            {"success": True, "output": "ok-1", "command": "resolved_cmd_1"},
            {"success": True, "output": "ok-2", "command": "resolved_cmd_2"},
        ]

        result = engine.execute_case_once(
            plugin=plugin,
            case=_make_case(steps=2),
            attempt_index=1,
            attempt_timeout_seconds=120.0,
            runner=_RUNNER,
        )

        assert result["commands"] == ["resolved_cmd_1", "resolved_cmd_2"]

    def test_execute_case_once_stringifies_list_step_command_when_plugin_omits_command(
        self, engine: ExecutionEngine
    ) -> None:
        plugin = _make_plugin(evaluate_ok=True)
        plugin.execute_step.return_value = {"success": True, "output": "ok"}
        case = {
            "id": "D999",
            "steps": [{"id": "step_0", "command": ["echo one", "echo two"]}],
            "pass_criteria": [],
        }

        result = engine.execute_case_once(
            plugin=plugin,
            case=case,
            attempt_index=1,
            attempt_timeout_seconds=120.0,
            runner=_RUNNER,
        )

        assert result["commands"] == ["echo one\necho two"]


# ===================================================================
# 2. Retry-verdict boundary
# ===================================================================

class TestRetryVerdictBoundary:
    """Retry logic and how it affects final verdict / comment."""

    def test_first_attempt_fails_retry_succeeds(self, engine: ExecutionEngine) -> None:
        call_count = 0

        def eval_side_effect(case: Any, results: Any) -> bool:
            nonlocal call_count
            call_count += 1
            return call_count >= 2

        plugin = _make_plugin()
        plugin.evaluate.side_effect = eval_side_effect

        policy = _policy_with({"retry": {"max_attempts": 3}})
        result = engine.execute_with_retry(
            plugin=plugin, case=_make_case(), runner=_RUNNER, execution_policy=policy,
        )
        assert result.verdict is True
        assert result.attempts_used == 2
        assert "retry" in result.comment.lower()

    def test_all_attempts_fail(self, engine: ExecutionEngine) -> None:
        plugin = _make_plugin(evaluate_ok=False)
        policy = _policy_with({"retry": {"max_attempts": 3}})
        result = engine.execute_with_retry(
            plugin=plugin, case=_make_case(), runner=_RUNNER, execution_policy=policy,
        )
        assert result.verdict is False
        assert result.attempts_used == 3
        assert "3/3" in result.comment

    def test_max_attempts_one_no_retry(self, engine: ExecutionEngine) -> None:
        plugin = _make_plugin(evaluate_ok=False)
        policy = _policy_with({"retry": {"max_attempts": 1}})
        result = engine.execute_with_retry(
            plugin=plugin, case=_make_case(), runner=_RUNNER, execution_policy=policy,
        )
        assert result.verdict is False
        assert result.attempts_used == 1
        assert result.max_attempts == 1

    def test_fail_fast_no_retry(self, engine: ExecutionEngine) -> None:
        plugin = _make_plugin(evaluate_ok=False)
        policy = _policy_with({
            "retry": {"max_attempts": 5},
            "failure_policy": "fail_fast",
        })
        result = engine.execute_with_retry(
            plugin=plugin, case=_make_case(), runner=_RUNNER, execution_policy=policy,
        )
        assert result.verdict is False
        assert result.attempts_used == 1
        assert result.max_attempts == 5


# ===================================================================
# 3. Timeout-verdict boundary
# ===================================================================

class TestTimeoutVerdictBoundary:
    """Timeout escalation and caps."""

    def test_timeout_escalation_across_attempts(self) -> None:
        policy: dict[str, Any] = {
            "timeout": {
                "base_seconds": 100.0,
                "per_step_seconds": 0.0,
                "retry_multiplier": 2.0,
                "max_seconds": 10000.0,
            },
        }
        t1 = ExecutionEngine.attempt_timeout_seconds(steps_count=0, attempt_index=1, execution_policy=policy)
        t2 = ExecutionEngine.attempt_timeout_seconds(steps_count=0, attempt_index=2, execution_policy=policy)
        t3 = ExecutionEngine.attempt_timeout_seconds(steps_count=0, attempt_index=3, execution_policy=policy)
        assert t1 == pytest.approx(100.0)
        assert t2 == pytest.approx(200.0)
        assert t3 == pytest.approx(400.0)
        assert t2 > t1
        assert t3 > t2

    def test_per_step_seconds_affects_timeout(self) -> None:
        policy: dict[str, Any] = {
            "timeout": {
                "base_seconds": 10.0,
                "per_step_seconds": 50.0,
                "retry_multiplier": 1.0,
                "max_seconds": 10000.0,
            },
        }
        t_0 = ExecutionEngine.attempt_timeout_seconds(steps_count=0, attempt_index=1, execution_policy=policy)
        t_3 = ExecutionEngine.attempt_timeout_seconds(steps_count=3, attempt_index=1, execution_policy=policy)
        assert t_0 == pytest.approx(10.0)
        assert t_3 == pytest.approx(10.0 + 3 * 50.0)

    def test_max_seconds_caps_timeout(self) -> None:
        policy: dict[str, Any] = {
            "timeout": {
                "base_seconds": 500.0,
                "per_step_seconds": 500.0,
                "retry_multiplier": 10.0,
                "max_seconds": 60.0,
            },
        }
        t = ExecutionEngine.attempt_timeout_seconds(steps_count=5, attempt_index=3, execution_policy=policy)
        assert t == pytest.approx(60.0)


# ===================================================================
# 4. Band-results boundary (case_utils)
# ===================================================================

class TestBandResultsBoundary:
    """Pure band_results / overall_case_status edge cases."""

    def test_verdict_true_multiband_all_pass(self) -> None:
        r5, r6, r24 = band_results("Pass", ["5g", "6g", "2.4g"])
        assert (r5, r6, r24) == ("Pass", "Pass", "Pass")

    def test_verdict_false_multiband_all_fail(self) -> None:
        r5, r6, r24 = band_results("Fail", ["5g", "6g", "2.4g"])
        assert (r5, r6, r24) == ("Fail", "Fail", "Fail")

    def test_verdict_true_with_unsupported_bands(self) -> None:
        r5, r6, r24 = band_results("Pass", ["5g"])
        assert r5 == "Pass"
        assert r6 == "N/A"
        assert r24 == "N/A"

    def test_overall_case_status_mixed(self) -> None:
        assert overall_case_status("Pass", "Fail", "N/A") == "Fail"
        assert overall_case_status("Pass", "Pass", "N/A") == "Pass"
        assert overall_case_status("N/A", "N/A", "N/A") == "Pass"
        assert overall_case_status("Fail", "Fail", "Fail") == "Fail"
        assert overall_case_status("Pass", "Pass", "Pass") == "Pass"
