from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from testpilot.core.cleanup_result import (
    has_unknown_transport_outcome,
    normalize_cleanup_result,
    project_transport_evidence,
)
from testpilot.core.execution_engine import ExecutionEngine
from testpilot.core.plugin_base import PluginBase


class _AcceptedReceiptPlugin(PluginBase):
    api_version = "1.5"

    def __init__(self, *, phase: str, receipt: Mapping[str, Any]) -> None:
        self.phase = phase
        self.receipt = dict(receipt)
        self.step_calls = 0
        self.evaluate_calls = 0
        self.teardown_calls = 0

    @property
    def name(self) -> str:
        return "accepted-receipt-test"

    def discover_cases(self) -> list[dict[str, Any]]:
        return []

    def setup_env(self, case: dict[str, Any], topology: Any) -> bool:
        if self.phase == "setup":
            case["_last_failure"] = {
                "case_id": case["id"],
                "attempt_index": case["_attempt_index"],
                "category": "environment",
                "reason_code": "command_outcome_unknown",
                "metadata": dict(self.receipt),
            }
            return False
        return True

    def execute_step(
        self, case: dict[str, Any], step: dict[str, Any], topology: Any
    ) -> dict[str, Any]:
        self.step_calls += 1
        if self.phase == "step":
            return {"success": False, "output": "accepted receipt", **self.receipt}
        if self.phase == "exception":
            error = RuntimeError("safe synthetic failure")
            error.result = {
                "outcome": "completed",
                "returncode": 0,
                "cmd_id": "outer-exception-id",
            }
            error.transport_result = dict(self.receipt)
            raise error
        if self.phase == "accepted-success":
            return {"success": True, "output": "accepted receipt", **self.receipt}
        if self.phase == "completed-failure":
            return {
                "success": False,
                "output": "known failure",
                "status": "completed",
                "outcome": "completed",
                "returncode": 1,
            }
        return {
            "success": True,
            "output": "completed",
            "status": "completed",
            "outcome": "completed",
            "returncode": 0,
        }

    def evaluate(self, case: dict[str, Any], results: dict[str, Any]) -> bool:
        self.evaluate_calls += 1
        return True

    def teardown(self, case: dict[str, Any], topology: Any) -> Any:
        self.teardown_calls += 1
        if self.phase == "teardown":
            return {
                "status": "failed",
                "reason_code": "cleanup_restore_failed",
                "comment": "cleanup did not verify",
                "transport_result": dict(self.receipt),
            }
        return None


def _execute_with_retry(plugin: _AcceptedReceiptPlugin):
    steps = [{"id": "probe", "command": "read state"}]
    if plugin.phase == "accepted-success":
        steps.append({"id": "followup", "command": "read again"})
    return ExecutionEngine({}).execute_with_retry(
        plugin=plugin,
        case={"id": "D036", "steps": steps},
        runner={"provider": "stub", "model": "test"},
        execution_policy={
            "retry": {"max_attempts": 2},
            "failure_policy": "retry_then_fail_and_continue",
        },
    )


@pytest.mark.parametrize(
    "receipt",
    [
        {"outcome": "accepted", "cmd_id": "accepted-outcome-id"},
        {"status": "accepted", "cmd_id": "accepted-status-id"},
    ],
)
def test_accepted_outcome_or_status_is_uncertain_and_survives_projection(
    receipt: dict[str, str],
) -> None:
    assert has_unknown_transport_outcome(receipt) is True
    assert project_transport_evidence(receipt) == receipt


@pytest.mark.parametrize("accepted_first", [True, False])
def test_accepted_alternate_surface_dominates_benign_completion_and_keeps_identity(
    accepted_first: bool,
) -> None:
    accepted = {
        "outcome": "accepted",
        "status": "accepted",
        "cmd_id": "accepted-receipt-id",
    }
    completed = {
        "outcome": "completed",
        "status": "completed",
        "returncode": 0,
        "cmd_id": "outer-completion-id",
    }
    values = (accepted, completed) if accepted_first else (completed, accepted)

    assert has_unknown_transport_outcome(*values) is True
    assert project_transport_evidence(*values) == accepted
    assert ExecutionEngine._merge_transport_evidence(*values) == accepted


@pytest.mark.parametrize("accepted_in", ["result", "transport_result"])
def test_nested_accepted_receipt_and_exception_surfaces_are_inspected(
    accepted_in: str,
) -> None:
    nested = {
        "outcome": "completed",
        "status": "completed",
        "cmd_id": "outer-id",
        "result": {
            "metadata": {
                "status": "accepted",
                "cmd_id": "nested-accepted-id",
            }
        },
    }
    assert has_unknown_transport_outcome(nested) is True
    assert project_transport_evidence(nested) == {
        "outcome": "completed",
        "status": "accepted",
        "cmd_id": "nested-accepted-id",
    }
    assert ExecutionEngine._merge_transport_evidence(nested) == {
        "outcome": "completed",
        "status": "accepted",
        "cmd_id": "nested-accepted-id",
    }

    error = RuntimeError("safe synthetic failure")
    benign = {"outcome": "completed", "returncode": 0, "cmd_id": "outer-error-id"}
    accepted = {"status": "accepted", "cmd_id": "exception-accepted-id"}
    error.result = accepted if accepted_in == "result" else benign
    error.transport_result = benign if accepted_in == "result" else accepted
    assert has_unknown_transport_outcome(error) is True
    assert project_transport_evidence(error) == {
        "outcome": "completed",
        "status": "accepted",
        "cmd_id": "exception-accepted-id",
    }
    assert ExecutionEngine._merge_transport_evidence(error) == {
        "outcome": "completed",
        "status": "accepted",
        "cmd_id": "exception-accepted-id",
    }


def test_cleanup_result_promotes_nested_accepted_receipt_to_unknown() -> None:
    normalized = normalize_cleanup_result(
        {
            "status": "failed",
            "reason_code": "cleanup_restore_failed",
            "comment": "cleanup did not verify",
            "transport_result": {
                "status": "completed",
                "cmd_id": "outer-cleanup-id",
                "metadata": {
                    "status": "accepted",
                    "cmd_id": "accepted-cleanup-id",
                },
            },
        }
    )

    assert normalized == {
        "status": "unknown",
        "reason_code": "cleanup_outcome_unknown",
        "comment": "cleanup did not verify",
        "transport_result": {
            "status": "accepted",
            "cmd_id": "accepted-cleanup-id",
        },
    }


def test_accepted_cleanup_projection_does_not_relax_result_validation() -> None:
    normalized = normalize_cleanup_result(
        {
            "status": "failed",
            "reason_code": "cleanup_restore_failed",
            "comment": "cleanup did not verify",
            "transport_result": {"status": "accepted", "cmd_id": object()},
        }
    )

    assert normalized == {
        "status": "unknown",
        "reason_code": "cleanup_result_invalid",
        "comment": "plugin teardown returned an invalid cleanup result",
        "transport_result": {},
    }


@pytest.mark.parametrize("phase", ["setup", "step", "exception", "teardown"])
def test_direct_pipeline_stops_after_accepted_receipt(phase: str) -> None:
    plugin = _AcceptedReceiptPlugin(
        phase=phase,
        receipt={"status": "accepted", "cmd_id": f"direct-{phase}-id"},
    )

    result = plugin.run_pipeline(
        {"id": "D036", "steps": [{"id": "probe", "command": "read state"}]},
        topology=None,
    )

    assert result["verdict"] is False
    assert result["abort_run"] is True
    assert result["abort_reason"] in {"command_outcome_unknown", "cleanup_outcome_unknown"}
    assert result["transport_result"]["status"] == "accepted"
    assert result["transport_result"]["cmd_id"] == f"direct-{phase}-id"
    assert plugin.step_calls == (0 if phase == "setup" else 1)
    assert plugin.teardown_calls == (1 if phase == "teardown" else 0)


def test_engine_accepted_step_stops_before_teardown_retry_or_next_command() -> None:
    plugin = _AcceptedReceiptPlugin(
        phase="step",
        receipt={"outcome": "accepted", "cmd_id": "engine-accepted-id"},
    )

    result = _execute_with_retry(plugin)

    assert result.verdict is False
    assert result.abort_run is True
    assert result.abort_reason == "command_outcome_unknown"
    assert result.attempts_used == 1
    assert result.attempts[0]["transport_result"]["outcome"] == "accepted"
    assert result.attempts[0]["transport_result"]["cmd_id"] == "engine-accepted-id"
    assert plugin.step_calls == 1
    assert plugin.teardown_calls == 0


@pytest.mark.parametrize(
    "receipt",
    [
        {"outcome": "accepted", "cmd_id": "accepted-success-outcome-id"},
        {"status": "accepted", "cmd_id": "accepted-success-status-id"},
    ],
)
def test_engine_accepted_receipt_overrides_success_flag_before_followup_step(
    receipt: dict[str, str],
) -> None:
    plugin = _AcceptedReceiptPlugin(
        phase="accepted-success",
        receipt=receipt,
    )

    result = _execute_with_retry(plugin)

    assert result.verdict is False
    assert result.abort_run is True
    assert result.abort_reason == "command_outcome_unknown"
    assert result.attempts_used == 1
    assert result.attempts[0]["transport_result"]["cmd_id"] == receipt["cmd_id"]
    assert result.attempts[0]["transport_result"].get("outcome") == receipt.get("outcome")
    assert result.attempts[0]["transport_result"].get("status") == receipt.get("status")
    assert plugin.step_calls == 1
    assert plugin.evaluate_calls == 0
    assert plugin.teardown_calls == 0


def test_engine_accepted_exception_surface_stops_before_retry_or_teardown() -> None:
    plugin = _AcceptedReceiptPlugin(
        phase="exception",
        receipt={"status": "accepted", "cmd_id": "exception-accepted-id"},
    )

    result = _execute_with_retry(plugin)

    assert result.verdict is False
    assert result.abort_run is True
    assert result.abort_reason == "command_outcome_unknown"
    assert result.attempts_used == 1
    assert result.attempts[0]["transport_result"]["status"] == "accepted"
    assert result.attempts[0]["transport_result"]["cmd_id"] == "exception-accepted-id"
    assert plugin.step_calls == 1
    assert plugin.teardown_calls == 0


def test_engine_accepted_setup_stops_before_step_teardown_or_retry() -> None:
    plugin = _AcceptedReceiptPlugin(
        phase="setup",
        receipt={"status": "accepted", "cmd_id": "setup-accepted-id"},
    )

    result = _execute_with_retry(plugin)

    assert result.abort_run is True
    assert result.abort_reason == "command_outcome_unknown"
    assert result.attempts_used == 1
    assert result.attempts[0]["transport_result"]["status"] == "accepted"
    assert result.attempts[0]["transport_result"]["cmd_id"] == "setup-accepted-id"
    assert plugin.step_calls == 0
    assert plugin.teardown_calls == 0


def test_engine_accepted_cleanup_stops_before_retry() -> None:
    plugin = _AcceptedReceiptPlugin(
        phase="teardown",
        receipt={"status": "accepted", "cmd_id": "cleanup-accepted-id"},
    )

    result = _execute_with_retry(plugin)

    assert result.verdict is False
    assert result.abort_run is True
    assert result.abort_reason == "cleanup_outcome_unknown"
    assert result.attempts_used == 1
    assert result.failure_snapshot["cleanup_status"] == "unknown"
    assert result.failure_snapshot["transport_result"]["status"] == "accepted"
    assert plugin.step_calls == 1
    assert plugin.teardown_calls == 1


@pytest.mark.parametrize(
    ("phase", "expected_attempts", "expected_verdict"),
    [
        ("completed-success", 1, True),
        ("completed-failure", 2, False),
    ],
)
def test_known_completed_rc0_and_rc1_keep_existing_retry_and_cleanup_behavior(
    phase: str,
    expected_attempts: int,
    expected_verdict: bool,
) -> None:
    plugin = _AcceptedReceiptPlugin(phase=phase, receipt={})

    result = _execute_with_retry(plugin)

    assert result.verdict is expected_verdict
    assert result.abort_run is False
    assert result.attempts_used == expected_attempts
    assert plugin.step_calls == expected_attempts
    assert plugin.teardown_calls == expected_attempts
