"""Plugin cleanup results must affect the same attempt before retry/run decisions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from testpilot.core.execution_engine import ExecutionEngine
from testpilot.core.hook_policy import HookDispatcher, HookPolicyConfig, HookResult
from testpilot.core.plugin_base import PluginBase


class _CleanupPlugin(PluginBase):
    api_version = "1.5"

    def __init__(
        self,
        *,
        cleanup_result: Any = None,
        setup_ok: bool = True,
        verify_ok: bool = True,
        step_results: list[bool] | None = None,
    ) -> None:
        self.cleanup_result = cleanup_result
        self.setup_ok = setup_ok
        self.verify_ok = verify_ok
        self.step_results = list(step_results or [True])
        self.setup_calls = 0
        self.verify_calls = 0
        self.step_calls = 0
        self.evaluate_calls = 0
        self.teardown_calls = 0

    @property
    def name(self) -> str:
        return "cleanup-result-test"

    def discover_cases(self) -> list[dict[str, Any]]:
        return []

    def setup_env(self, case: dict[str, Any], topology: Any) -> bool:
        self.setup_calls += 1
        return self.setup_ok

    def verify_env(self, case: dict[str, Any], topology: Any) -> bool:
        self.verify_calls += 1
        return self.verify_ok

    def execute_step(
        self, case: dict[str, Any], step: dict[str, Any], topology: Any
    ) -> dict[str, Any]:
        self.step_calls += 1
        success = self.step_results[min(self.step_calls - 1, len(self.step_results) - 1)]
        return {"success": success, "output": "ok" if success else "failed"}

    def evaluate(self, case: dict[str, Any], results: dict[str, Any]) -> bool:
        self.evaluate_calls += 1
        return True

    def teardown(
        self, case: dict[str, Any], topology: Any
    ) -> dict[str, Any] | None:
        self.teardown_calls += 1
        if isinstance(self.cleanup_result, BaseException):
            raise self.cleanup_result
        return self.cleanup_result


def _cleanup_failure(status: str = "failed") -> dict[str, Any]:
    return {
        "status": status,
        "reason_code": "cleanup_restore_failed" if status == "failed" else "cleanup_restore_unknown",
        "comment": "restore did not reach the saved mode",
        "transport_result": {"outcome": "unknown"} if status == "unknown" else {"status": "rejected"},
    }


def _wrapped_unknown_cleanup_failure() -> dict[str, Any]:
    return {
        "status": "failed",
        "reason_code": "restore_failed",
        "comment": "restore did not verify",
        "transport_result": {
            "metadata": {
                "outcome": "unknown",
                "cmd_id": "receipt-1",
                "api_key": "synthetic-secret-value",
            }
        },
    }


def _run_retry(plugin: _CleanupPlugin, *, max_attempts: int = 3):
    return ExecutionEngine({}).execute_with_retry(
        plugin=plugin,
        case={"id": "D036", "steps": [{"id": "probe", "command": "read state"}]},
        runner={"provider": "stub", "model": "test"},
        execution_policy={
            "retry": {"max_attempts": max_attempts},
            "failure_policy": "retry_then_fail_and_continue",
        },
    )


def test_normalizer_preserves_only_allowlisted_nested_uncertainty() -> None:
    from testpilot.core.cleanup_result import normalize_cleanup_result

    normalized = normalize_cleanup_result(_wrapped_unknown_cleanup_failure())

    assert normalized is not None
    assert normalized["status"] == "unknown"
    assert normalized["reason_code"] == "cleanup_outcome_unknown"
    assert normalized["transport_result"] == {
        "outcome": "unknown",
        "cmd_id": "receipt-1",
    }
    assert "synthetic-secret-value" not in str(normalized)


def test_engine_wrapped_unknown_cleanup_is_terminal_and_core_stamped() -> None:
    result = _run_retry(_CleanupPlugin(cleanup_result=_wrapped_unknown_cleanup_failure()))

    assert result.verdict is False
    assert result.diagnostic_status == "FailEnv"
    assert result.abort_run is True
    assert result.abort_reason == "cleanup_outcome_unknown"
    assert result.attempts_used == 1
    assert result.failure_snapshot["case_id"] == "D036"
    assert result.failure_snapshot["attempt_index"] == 1
    assert result.failure_snapshot["category"] == "environment"
    assert result.failure_snapshot["reason_code"] == "cleanup_outcome_unknown"
    assert result.failure_snapshot["cleanup_status"] == "unknown"
    assert result.failure_snapshot["transport_result"] == {
        "outcome": "unknown",
        "cmd_id": "receipt-1",
    }
    assert "synthetic-secret-value" not in str(result.failure_snapshot)


def test_direct_pipeline_wrapped_unknown_cleanup_is_terminal_and_core_stamped() -> None:
    plugin = _CleanupPlugin(cleanup_result=_wrapped_unknown_cleanup_failure())

    result = plugin.run_pipeline(
        {"id": "D036", "steps": [{"id": "probe", "command": "read state"}]},
        topology=None,
    )

    assert result["verdict"] is False
    assert result["diagnostic_status"] == "FailEnv"
    assert result["abort_run"] is True
    assert result["abort_reason"] == "cleanup_outcome_unknown"
    assert result["failure_snapshot"]["case_id"] == "D036"
    assert result["failure_snapshot"]["attempt_index"] == 1
    assert result["failure_snapshot"]["category"] == "environment"
    assert result["failure_snapshot"]["reason_code"] == "cleanup_outcome_unknown"
    assert result["failure_snapshot"]["cleanup_status"] == "unknown"
    assert result["transport_result"] == {
        "outcome": "unknown",
        "cmd_id": "receipt-1",
    }
    assert "synthetic-secret-value" not in str(result)


@pytest.mark.parametrize("plugin_api", ["1.4", "1.5"])
def test_none_cleanup_keeps_legacy_pass_behavior(plugin_api: str) -> None:
    plugin = _CleanupPlugin()
    plugin.api_version = plugin_api

    result = _run_retry(plugin)

    assert result.verdict is True
    assert result.abort_run is False
    assert result.attempts_used == 1
    assert plugin.teardown_calls == 1


@pytest.mark.parametrize("previous_step_success", [True, False])
def test_cleanup_failure_overrides_attempt_and_aborts_before_retry(
    previous_step_success: bool,
) -> None:
    plugin = _CleanupPlugin(
        cleanup_result=_cleanup_failure(),
        step_results=[previous_step_success],
    )

    result = _run_retry(plugin)

    assert result.verdict is False
    assert result.diagnostic_status == "FailEnv"
    assert result.abort_run is True
    assert result.abort_reason == "cleanup_restore_failed"
    assert result.attempts_used == 1
    assert result.attempts[0]["failure_snapshot"]["case_id"] == "D036"
    assert result.attempts[0]["failure_snapshot"]["attempt_index"] == 1
    assert result.attempts[0]["failure_snapshot"]["category"] == "environment"
    assert plugin.teardown_calls == 1


def test_unknown_cleanup_result_aborts_with_environment_snapshot() -> None:
    plugin = _CleanupPlugin(cleanup_result=_cleanup_failure("unknown"))

    result = _run_retry(plugin)

    assert result.verdict is False
    assert result.diagnostic_status == "FailEnv"
    assert result.abort_run is True
    assert result.abort_reason == "cleanup_restore_unknown"
    assert result.attempts_used == 1
    assert result.failure_snapshot["cleanup_status"] == "unknown"


def test_uncertain_cleanup_transport_overrides_claimed_known_failure() -> None:
    plugin = _CleanupPlugin(
        cleanup_result={
            **_cleanup_failure(),
            "transport_result": {
                "outcome": "unknown",
                "non_replayable": True,
                "cmd_id": "safe-test-id",
            },
        }
    )

    result = _run_retry(plugin)

    assert result.abort_run is True
    assert result.abort_reason == "cleanup_outcome_unknown"
    assert result.attempts_used == 1
    assert result.failure_snapshot["cleanup_status"] == "unknown"
    assert result.failure_snapshot["transport_result"]["outcome"] == "unknown"


def test_cleanup_mapping_cannot_supply_core_failure_identity() -> None:
    result = _run_retry(
        _CleanupPlugin(
            cleanup_result={
                **_cleanup_failure(),
                "case_id": "D999",
                "attempt_index": 99,
                "category": "test",
                "abort_run": False,
            }
        )
    )

    assert result.abort_run is True
    assert result.failure_snapshot["case_id"] == "D036"
    assert result.failure_snapshot["attempt_index"] == 1
    assert result.failure_snapshot["category"] == "environment"
    assert result.abort_reason == "cleanup_result_invalid"


def test_known_step_failure_with_successful_cleanup_keeps_retry_policy() -> None:
    plugin = _CleanupPlugin(step_results=[False, True])

    result = _run_retry(plugin)

    assert result.verdict is True
    assert result.abort_run is False
    assert result.attempts_used == 2
    assert plugin.teardown_calls == 2


@pytest.mark.parametrize(
    "invalid_result",
    [
        True,
        {"status": "success"},
        {"status": "failed"},
        {
            **_cleanup_failure(),
            "transport_result": {"cmd_id": object()},
        },
    ],
)
def test_malformed_cleanup_result_fails_closed(
    invalid_result: Any,
) -> None:
    result = _run_retry(_CleanupPlugin(cleanup_result=invalid_result))

    assert result.verdict is False
    assert result.diagnostic_status == "FailEnv"
    assert result.abort_run is True
    assert result.abort_reason == "cleanup_result_invalid"
    assert result.attempts_used == 1


def test_teardown_exception_fails_closed_before_retry() -> None:
    result = _run_retry(_CleanupPlugin(cleanup_result=RuntimeError("private detail")))

    assert result.verdict is False
    assert result.diagnostic_status == "FailEnv"
    assert result.abort_run is True
    assert result.abort_reason == "cleanup_exception"
    assert result.attempts_used == 1


@pytest.mark.parametrize(
    ("setup_ok", "verify_ok", "step_results"),
    [(True, True, [True]), (False, True, [True]), (True, False, [True])],
)
def test_run_pipeline_reports_cleanup_failure_after_every_early_exit(
    setup_ok: bool,
    verify_ok: bool,
    step_results: list[bool],
) -> None:
    plugin = _CleanupPlugin(
        cleanup_result=_cleanup_failure(),
        setup_ok=setup_ok,
        verify_ok=verify_ok,
        step_results=step_results,
    )
    case = {"id": "D036", "steps": [{"id": "probe", "command": "read state"}]}

    result = plugin.run_pipeline(case, topology=None)

    assert result["verdict"] is False
    assert result["diagnostic_status"] == "FailEnv"
    assert result["abort_run"] is True
    assert result["failure_snapshot"]["case_id"] == "D036"
    assert result["failure_snapshot"]["category"] == "environment"
    assert plugin.teardown_calls == 1


def test_cleanup_abort_stops_later_cases_in_real_run_loop(tmp_path: Path) -> None:
    from test_remediation_run_abort import _AbortOrchestrator, _Plugin

    class RunPlugin(_Plugin):
        def __init__(self) -> None:
            super().__init__(
                [
                    {"id": "D036", "steps": [{"id": "probe", "command": "read state"}], "source": {"row": 1}},
                    {"id": "D037", "steps": [{"id": "later", "command": "must not run"}], "source": {"row": 2}},
                ]
            )
            self.setup_calls = 0
            self.step_calls = 0
            self.teardown_calls = 0

        def setup_env(self, case: dict[str, Any], topology: Any) -> bool:
            self.setup_calls += 1
            return True

        def verify_env(self, case: dict[str, Any], topology: Any) -> bool:
            return True

        def execute_step(self, case: dict[str, Any], step: dict[str, Any], topology: Any) -> dict[str, Any]:
            self.step_calls += 1
            return {"success": True, "output": "ok"}

        def evaluate(self, case: dict[str, Any], results: dict[str, Any]) -> bool:
            return True

        def teardown(self, case: dict[str, Any], topology: Any) -> dict[str, Any] | None:
            self.teardown_calls += 1
            return _cleanup_failure()

    from testpilot.core import run_loop

    plugin = RunPlugin()
    orchestrator = _AbortOrchestrator(
        tmp_path,
        plugin,
        ExecutionEngine({}),
    )

    payload = run_loop.run(orchestrator, "fake", None, None)

    assert payload["status"] == "aborted"
    assert payload["run_abort"]["case_id"] == "D036"
    assert payload["run_abort"]["unexecuted_case_ids"] == ["D037"]
    assert plugin.setup_calls == 1
    assert plugin.step_calls == 1
    assert plugin.teardown_calls == 1


@pytest.mark.parametrize(("halt_on", "expected_restores"), [(1, 0), (2, 1)])
def test_pre_step_halt_restores_only_if_an_earlier_step_mutated(
    halt_on: int,
    expected_restores: int,
) -> None:
    class StatefulPlugin(_CleanupPlugin):
        def __init__(self) -> None:
            super().__init__()
            self.mutated = False
            self.restore_calls = 0

        def execute_step(self, case: dict[str, Any], step: dict[str, Any], topology: Any) -> dict[str, Any]:
            self.mutated = True
            return {"success": True, "output": "changed"}

        def teardown(self, case: dict[str, Any], topology: Any) -> dict[str, Any] | None:
            self.teardown_calls += 1
            if self.mutated:
                self.restore_calls += 1
            return None

    plugin = StatefulPlugin()
    pre_step_count = 0
    hooks = HookDispatcher(HookPolicyConfig(enabled_hooks={"pre_step"}))

    def halt_after_selected_steps(_ctx: Any, _data: dict[str, Any]) -> HookResult:
        nonlocal pre_step_count
        pre_step_count += 1
        if pre_step_count == halt_on:
            return HookResult(proceed=False, advice="halt for safety")
        return HookResult()

    hooks.register("pre_step", halt_after_selected_steps)
    result = ExecutionEngine({}, hooks).execute_with_retry(
        plugin=plugin,
        case={
            "id": "D036",
            "steps": [
                {"id": "first", "command": "mutate"},
                {"id": "second", "command": "mutate"},
            ],
        },
        runner={"provider": "stub", "model": "test"},
        execution_policy={"retry": {"max_attempts": 1}},
    )

    assert result.attempts_used == 1
    assert plugin.teardown_calls == 1
    assert plugin.restore_calls == expected_restores


def test_unknown_failure_snapshot_suppresses_teardown_during_cancellation() -> None:
    class CancelDuringMutation(_CleanupPlugin):
        def execute_step(self, case: dict[str, Any], step: dict[str, Any], topology: Any) -> dict[str, Any]:
            case["_last_failure"] = {
                "case_id": case["id"],
                "attempt_index": case["_attempt_index"],
                "category": "environment",
                "reason_code": "command_outcome_unknown",
                "metadata": {"outcome": "unknown", "non_replayable": True},
            }
            raise KeyboardInterrupt()

    plugin = CancelDuringMutation()

    with pytest.raises(KeyboardInterrupt):
        _run_retry(plugin)

    assert plugin.teardown_calls == 0


def test_teardown_cancellation_propagates_without_retry() -> None:
    plugin = _CleanupPlugin(cleanup_result=KeyboardInterrupt())

    with pytest.raises(KeyboardInterrupt):
        _run_retry(plugin)

    assert plugin.step_calls == 1
    assert plugin.teardown_calls == 1


def test_direct_pipeline_unknown_step_does_not_run_teardown() -> None:
    class UnknownStepPlugin(_CleanupPlugin):
        def execute_step(self, case: dict[str, Any], step: dict[str, Any], topology: Any) -> dict[str, Any]:
            self.step_calls += 1
            return {
                "success": False,
                "output": "pending",
                "outcome": "unknown",
                "non_replayable": True,
            }

    plugin = UnknownStepPlugin()
    result = plugin.run_pipeline(
        {"id": "D036", "steps": [{"id": "mutate", "command": "change state"}]},
        topology=None,
    )

    assert result["verdict"] is False
    assert result["diagnostic_status"] == "FailEnv"
    assert result["abort_run"] is True
    assert result["abort_reason"] == "command_outcome_unknown"
    assert plugin.teardown_calls == 0


def test_direct_pipeline_ignores_stale_unknown_failure_snapshot() -> None:
    plugin = _CleanupPlugin()
    case = {
        "id": "D036",
        "steps": [{"id": "probe", "command": "read state"}],
        "_last_failure": {
            "case_id": "D036",
            "attempt_index": 1,
            "metadata": {"outcome": "unknown", "non_replayable": True},
        },
    }

    result = plugin.run_pipeline(case, topology=None)

    assert result["verdict"] is True
    assert result.get("abort_run") is not True
    assert plugin.teardown_calls == 1
    assert case["_last_failure"]["metadata"]["outcome"] == "unknown"
