from __future__ import annotations

from typing import Any

import pytest

from testpilot.core.execution_engine import ExecutionEngine
from testpilot.core.hook_policy import HookDispatcher, HookPolicyConfig
from testpilot.core.remediation import RuntimeRemediationCoordinator


@pytest.mark.parametrize("phase", ["setup", "verify", "step", "evaluate"])
@pytest.mark.parametrize("max_attempts", [1, 2])
def test_explicit_terminal_failure_aborts_on_first_or_final_attempt(
    phase: str,
    max_attempts: int,
) -> None:
    class Plugin:
        def __init__(self) -> None:
            self.attempts: list[int] = []
            self.teardowns = 0

        @staticmethod
        def _fail(case: dict[str, Any]) -> None:
            attempt = int(case["_attempt_index"])
            case["_last_failure"] = {
                "case_id": "D001",
                "attempt_index": attempt,
                "category": "environment",
                "reason_code": "dut_serial_wedged",
                "abort_run": attempt == max_attempts,
                "abort_reason": "dut_serial_wedged",
                "skip_teardown": attempt == max_attempts,
            }

        def setup_env(self, case: dict[str, Any], **_kwargs: Any) -> bool:
            attempt = int(case["_attempt_index"])
            self.attempts.append(attempt)
            if phase == "setup":
                self._fail(case)
                return False
            return True

        def verify_env(self, case: dict[str, Any], **_kwargs: Any) -> bool:
            if phase == "verify":
                self._fail(case)
                return False
            return True

        def execute_step(self, case: dict[str, Any], step: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
            if phase == "step":
                self._fail(case)
                return {"success": False, "command": step["command"], "output": "failed"}
            return {"success": True, "command": step["command"], "output": "ok"}

        def evaluate(self, case: dict[str, Any], _results: dict[str, Any]) -> bool:
            if phase == "evaluate":
                self._fail(case)
                return False
            return True

        def teardown(self, *_args: Any, **_kwargs: Any) -> None:
            self.teardowns += 1

    plugin = Plugin()
    result = ExecutionEngine({}).execute_with_retry(
        plugin=plugin,
        case={"id": "D001", "steps": [{"id": "step-1", "command": "read-only"}]},
        runner={},
        execution_policy={
            "retry": {"max_attempts": max_attempts},
            "failure_policy": "retry_then_fail_and_continue",
        },
    )

    assert result.abort_run is True
    assert result.abort_reason == "dut_serial_wedged"
    assert result.attempts_used == max_attempts
    assert plugin.attempts == list(range(1, max_attempts + 1))
    # The earlier ordinary failure cleans up; the terminal failure explicitly
    # requests that teardown be skipped because it may write over serial.
    assert plugin.teardowns == max_attempts - 1


@pytest.mark.parametrize("phase", ["setup", "verify", "step", "evaluate"])
def test_explicit_failure_abort_preserves_normal_cleanup_when_not_requested(phase: str) -> None:
    class Plugin:
        teardowns = 0

        def _fail(self, case: dict[str, Any]) -> None:
            case["_last_failure"] = {
                "case_id": "D001",
                "attempt_index": 1,
                "category": "environment",
                "reason_code": "terminal_failure",
                "abort_run": True,
                "abort_reason": "T" * 512,
                "skip_teardown": False,
            }

        def setup_env(self, case: dict[str, Any], **_kwargs: Any) -> bool:
            if phase == "setup":
                self._fail(case)
                return False
            return True

        def verify_env(self, case: dict[str, Any], **_kwargs: Any) -> bool:
            if phase == "verify":
                self._fail(case)
                return False
            return True

        def execute_step(self, case: dict[str, Any], step: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
            if phase == "step":
                self._fail(case)
                return {"success": False, "command": step["command"], "output": "failed"}
            return {"success": True, "command": step["command"], "output": "ok"}

        def evaluate(self, case: dict[str, Any], _results: dict[str, Any]) -> bool:
            if phase == "evaluate":
                self._fail(case)
                return False
            return True

        def teardown(self, *_args: Any, **_kwargs: Any) -> None:
            self.teardowns += 1

    plugin = Plugin()
    result = ExecutionEngine({}).execute_with_retry(
        plugin=plugin,
        case={"id": "D001", "steps": [{"id": "step-1", "command": "read-only"}]},
        runner={},
        execution_policy={"retry": {"max_attempts": 3}},
    )

    assert result.abort_run is True
    assert result.abort_reason == "T" * 128
    assert result.attempts_used == 1
    assert plugin.teardowns == 1


@pytest.mark.parametrize(
    "failure_identity",
    [
        {},
        {"case_id": "D002", "attempt_index": 1},
        {"case_id": "D001", "attempt_index": 2},
    ],
)
def test_abort_directive_requires_current_case_and_attempt_identity(
    failure_identity: dict[str, Any],
) -> None:
    class Plugin:
        teardowns = 0

        def setup_env(self, case: dict[str, Any], **_kwargs: Any) -> bool:
            case["_last_failure"] = {
                **failure_identity,
                "category": "environment",
                "reason_code": "dut_serial_wedged",
                "abort_run": True,
                "abort_reason": "dut_serial_wedged",
                "skip_teardown": True,
            }
            return False

        def teardown(self, *_args: Any, **_kwargs: Any) -> None:
            self.teardowns += 1

    plugin = Plugin()
    result = ExecutionEngine({}).execute_with_retry(
        plugin=plugin,
        case={"id": "D001", "steps": []},
        runner={},
        execution_policy={"retry": {"max_attempts": 1}},
    )

    assert result.abort_run is False
    assert result.abort_reason == ""
    assert plugin.teardowns == 1


def test_stale_failure_abort_from_input_case_is_cleared_before_execution() -> None:
    class Plugin:
        teardowns = 0

        def setup_env(self, _case: dict[str, Any], **_kwargs: Any) -> bool:
            return False

        def teardown(self, *_args: Any, **_kwargs: Any) -> None:
            self.teardowns += 1

    plugin = Plugin()
    result = ExecutionEngine({}).execute_with_retry(
        plugin=plugin,
        case={
            "id": "D001",
            "steps": [],
            "_last_failure": {
                "abort_run": True,
                "abort_reason": "stale_previous_case",
                "skip_teardown": True,
            },
        },
        runner={},
        execution_policy={"retry": {"max_attempts": 1}},
    )

    assert result.abort_run is False
    assert result.abort_reason == ""
    assert plugin.teardowns == 1


@pytest.mark.parametrize(
    "failure_identity",
    [
        {},
        {"case_id": "D002", "attempt_index": 1},
        {"case_id": "D001", "attempt_index": 2},
    ],
)
def test_stale_or_mismatched_failure_metadata_cannot_abort_or_suppress_cleanup(
    failure_identity: dict[str, Any],
) -> None:
    class Plugin:
        teardowns = 0

        def setup_env(self, case: dict[str, Any], **_kwargs: Any) -> bool:
            case["_last_failure"] = {
                **failure_identity,
                "metadata": {
                    "outcome": "unknown",
                    "non_replayable": True,
                    "cmd_id": "unmatched-receipt",
                },
            }
            return False

        def teardown(self, *_args: Any, **_kwargs: Any) -> None:
            self.teardowns += 1

    plugin = Plugin()
    result = ExecutionEngine({}).execute_with_retry(
        plugin=plugin,
        case={"id": "D001", "steps": []},
        runner={},
        execution_policy={"retry": {"max_attempts": 1}},
    )

    assert result.abort_run is False
    assert result.abort_reason == ""
    assert result.attempts[0]["transport_result"] == {}
    assert plugin.teardowns == 1


def test_disabled_failure_hooks_preserve_validated_terminal_snapshot() -> None:
    snapshot = {
        "case_id": "D001",
        "attempt_index": 1,
        "phase": "setup_env",
        "category": "environment",
        "reason_code": "dut_serial_wedged",
        "abort_run": True,
        "abort_reason": "dut_serial_wedged",
        "skip_teardown": True,
        "metadata": {
            "serial_health": {"classification": "dut_serial_wedged", "state": "ATTACHED"},
        },
    }

    class Plugin:
        teardowns = 0

        def setup_env(self, case: dict[str, Any], **_kwargs: Any) -> bool:
            case["_last_failure"] = dict(snapshot)
            return False

        def teardown(self, *_args: Any, **_kwargs: Any) -> None:
            self.teardowns += 1

    plugin = Plugin()
    hooks = HookDispatcher(HookPolicyConfig(enabled_hooks=set()))
    result = ExecutionEngine({}, hooks).execute_with_retry(
        plugin=plugin,
        case={"id": "D001", "steps": []},
        runner={},
        execution_policy={"retry": {"max_attempts": 1}},
    )

    assert result.abort_run is True
    assert result.abort_reason == "dut_serial_wedged"
    assert result.diagnostic_status == "FailEnv"
    assert result.failure_snapshot == snapshot
    assert result.attempts[0]["failure_snapshot"] == snapshot
    assert plugin.teardowns == 0


@pytest.mark.parametrize(
    "failure_identity",
    [
        {"case_id": "D001", "attempt_index": 1},
        {"case_id": "D002", "attempt_index": 0},
    ],
)
def test_mismatched_failure_snapshot_is_removed_before_remediation_hooks(
    failure_identity: dict[str, Any],
) -> None:
    class Plugin:
        setups: list[int] = []
        teardown_calls = 0
        decisions: list[tuple[str, str]] = []
        executed: list[str] = []

        def setup_env(self, case: dict[str, Any], **_kwargs: Any) -> bool:
            attempt = int(case["_attempt_index"])
            self.setups.append(attempt)
            case["_last_failure"] = {
                **failure_identity,
                "phase": "setup_env",
                "category": "environment",
                "reason_code": "serial_session_not_ready",
                "abort_run": True,
                "abort_reason": "stale_abort",
                "skip_teardown": True,
            }
            return False

        def build_remediation_decision(
            self,
            case: dict[str, Any],
            failure_snapshot: Any,
            _topology: Any,
            **_kwargs: Any,
        ) -> dict[str, Any] | None:
            reason = str(getattr(failure_snapshot, "reason_code", ""))
            self.decisions.append((str(case.get("id", "")), reason))
            if reason != "serial_session_not_ready":
                return None
            return {
                "case_id": str(case["id"]),
                "attempt_index": int(case.get("_attempt_index", 1)),
                "summary": "stale recovery must not run",
                "actions": [{"executor_key": "serial_session_recover", "device": "DUT"}],
            }

        def execute_remediation(self, _case: dict[str, Any], decision: Any, _topology: Any) -> dict[str, Any]:
            self.executed.extend(action.executor_key for action in decision.actions)
            return {"success": True, "verify_after": True, "comment": "ran stale recovery"}

        def teardown(self, *_args: Any, **_kwargs: Any) -> None:
            self.teardown_calls += 1

    plugin = Plugin()
    hooks = HookDispatcher(
        HookPolicyConfig(enabled_hooks={"pre_case", "on_failure", "on_retry"}, fail_open=False)
    )
    coordinator = RuntimeRemediationCoordinator(
        plugin=plugin,
        topology=object(),
        policy={"enabled": True, "allowed_actions": ["serial_session_recover"]},
    )
    hooks.register("pre_case", coordinator.handle_pre_case)
    hooks.register("on_failure", coordinator.handle_on_failure)
    hooks.register("on_retry", coordinator.handle_on_retry)

    result = ExecutionEngine({}, hooks).execute_with_retry(
        plugin=plugin,
        case={"id": "D002", "steps": []},
        runner={},
        execution_policy={
            "retry": {"max_attempts": 2},
            "failure_policy": "retry_then_fail_and_continue",
        },
    )

    assert result.abort_run is False
    assert result.attempts_used == 2
    assert plugin.setups == [1, 2]
    assert plugin.decisions == [("D002", ""), ("D002", "")]
    assert plugin.executed == []
    # Mismatched skip_teardown is also ignored; the core runs ordinary cleanup.
    assert plugin.teardown_calls == 2


@pytest.mark.parametrize("phase", ["setup", "verify", "step", "evaluate"])
@pytest.mark.parametrize("terminal_attempt", [1, 2])
def test_generic_exception_receipt_aborts_in_every_failure_phase_and_attempt(
    phase: str,
    terminal_attempt: int,
) -> None:
    class Plugin:
        setups = 0
        teardowns = 0

        @staticmethod
        def _raise_unknown(case: dict[str, Any]) -> None:
            case["_last_failure"] = {
                "case_id": "D001",
                "attempt_index": case["_attempt_index"],
                "metadata": {
                    # These older/plugin-projected values must not erase the
                    # stronger receipt attached to the generic exception.
                    "outcome": "completed",
                    "ambiguous": False,
                    "non_replayable": False,
                    "retryable": True,
                    "partial": True,
                    "input_integrity": "uncertain",
                },
            }
            error = RuntimeError("accepted command status unavailable")
            error.result = {
                "outcome": "unknown",
                "non_replayable": True,
                "retryable": False,
                "cmd_id": "accepted-command-17",
            }
            error.transport_result = {
                "ambiguous": True,
                "non_replayable": True,
            }
            raise error

        def setup_env(self, case: dict[str, Any], **_kwargs: Any) -> bool:
            self.setups += 1
            if phase == "setup":
                if case["_attempt_index"] == terminal_attempt:
                    self._raise_unknown(case)
                return False
            return True

        def verify_env(self, case: dict[str, Any], **_kwargs: Any) -> bool:
            if phase == "verify":
                if case["_attempt_index"] == terminal_attempt:
                    self._raise_unknown(case)
                return False
            return True

        def execute_step(self, case: dict[str, Any], step: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
            if phase == "step":
                if case["_attempt_index"] == terminal_attempt:
                    self._raise_unknown(case)
                return {"success": False, "command": step["command"], "output": "failed"}
            return {"success": True, "command": step["command"], "output": "ok"}

        def evaluate(self, case: dict[str, Any], _results: dict[str, Any]) -> bool:
            if phase == "evaluate":
                if case["_attempt_index"] == terminal_attempt:
                    self._raise_unknown(case)
                return False
            return True

        def teardown(self, *_args: Any, **_kwargs: Any) -> None:
            self.teardowns += 1

    plugin = Plugin()
    result = ExecutionEngine({}).execute_with_retry(
        plugin=plugin,
        case={"id": "D001", "steps": [{"id": "step-1", "command": "mutate"}]},
        runner={},
        execution_policy={
            "retry": {"max_attempts": terminal_attempt},
            "failure_policy": "retry_then_fail_and_continue",
        },
    )

    assert result.abort_run is True
    assert result.abort_reason == "command_outcome_unknown"
    assert result.attempts_used == terminal_attempt
    assert plugin.setups == terminal_attempt
    assert plugin.teardowns == terminal_attempt - 1
    receipt = result.attempts[-1]["transport_result"]
    assert receipt["cmd_id"] == "accepted-command-17"
    assert receipt["outcome"] == "unknown"
    assert receipt["ambiguous"] is True
    assert receipt["non_replayable"] is True
    assert receipt["retryable"] is False
    assert receipt["partial"] is True
    assert receipt["input_integrity"] == "uncertain"


@pytest.mark.parametrize("phase", ["setup", "verify", "step", "evaluate"])
def test_current_failure_metadata_unknown_markers_survive_benign_phase_result(phase: str) -> None:
    class Plugin:
        teardowns = 0

        @staticmethod
        def _unknown_metadata(case: dict[str, Any]) -> None:
            case["_last_failure"] = {
                "case_id": "D001",
                "attempt_index": case["_attempt_index"],
                "metadata": {
                    "outcome": "unknown",
                    "ambiguous": True,
                    "non_replayable": True,
                    "retryable": False,
                    "partial": True,
                    "input_integrity": "uncertain",
                    "cmd_id": "accepted-from-plugin-snapshot",
                },
            }

        def setup_env(self, case: dict[str, Any], **_kwargs: Any) -> bool:
            if phase == "setup":
                self._unknown_metadata(case)
                return False
            return True

        def verify_env(self, case: dict[str, Any], **_kwargs: Any) -> bool:
            if phase == "verify":
                self._unknown_metadata(case)
                return False
            return True

        def execute_step(self, case: dict[str, Any], step: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
            if phase == "step":
                self._unknown_metadata(case)
                return {
                    "success": False,
                    "command": step["command"],
                    "outcome": "completed",
                    "ambiguous": False,
                    "non_replayable": False,
                    "retryable": True,
                }
            return {"success": True, "command": step["command"], "output": "ok"}

        def evaluate(self, case: dict[str, Any], _results: dict[str, Any]) -> bool:
            if phase == "evaluate":
                self._unknown_metadata(case)
                return False
            return True

        def teardown(self, *_args: Any, **_kwargs: Any) -> None:
            self.teardowns += 1

    plugin = Plugin()
    result = ExecutionEngine({}).execute_with_retry(
        plugin=plugin,
        case={"id": "D001", "steps": [{"id": "step-1", "command": "mutate"}]},
        runner={},
        execution_policy={"retry": {"max_attempts": 3}},
    )

    assert result.abort_run is True
    assert result.abort_reason == "command_outcome_unknown"
    assert result.attempts_used == 1
    assert plugin.teardowns == 0
    receipt = result.attempts[0]["transport_result"]
    assert receipt["outcome"] == "unknown"
    assert receipt["ambiguous"] is True
    assert receipt["non_replayable"] is True
    assert receipt["retryable"] is False
    assert receipt["partial"] is True
    assert receipt["input_integrity"] == "uncertain"
    assert receipt["cmd_id"] == "accepted-from-plugin-snapshot"
