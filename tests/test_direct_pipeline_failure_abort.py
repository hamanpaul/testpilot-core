from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from testpilot.core.plugin_base import PluginBase


class _DirectAbortPlugin(PluginBase):
    api_version = "1.5"

    def __init__(
        self,
        *,
        phase: str,
        failure: Mapping[str, Any] | None = None,
        cleanup_result: Any = None,
    ) -> None:
        self.phase = phase
        self.failure = dict(failure or {})
        self.cleanup_result = cleanup_result
        self.teardown_calls = 0

    @property
    def name(self) -> str:
        return "direct-pipeline-abort-test"

    def discover_cases(self) -> list[dict[str, Any]]:
        return []

    def _stamp_failure(self, case: dict[str, Any]) -> None:
        case["_last_failure"] = {
            "case_id": case["id"],
            "attempt_index": case["_attempt_index"],
            "category": "environment",
            "reason_code": "device_state_terminal",
            "abort_run": True,
            "abort_reason": "device_state_terminal",
            "skip_teardown": True,
            **self.failure,
        }

    def setup_env(self, case: dict[str, Any], topology: Any) -> bool:
        if self.phase == "setup":
            self._stamp_failure(case)
            return False
        return True

    def verify_env(self, case: dict[str, Any], topology: Any) -> bool:
        if self.phase == "verify":
            self._stamp_failure(case)
            return False
        return True

    def execute_step(
        self, case: dict[str, Any], step: dict[str, Any], topology: Any
    ) -> dict[str, Any]:
        if self.phase == "step":
            self._stamp_failure(case)
            return {"success": False, "output": "step failed"}
        if self.phase == "unknown":
            self._stamp_failure(case)
            return {
                "success": False,
                "output": "receipt pending",
                "outcome": "unknown",
                "non_replayable": True,
            }
        if self.phase == "exception":
            self._stamp_failure(case)
            raise RuntimeError("step failed")
        return {"success": True, "output": "ok"}

    def evaluate(self, case: dict[str, Any], results: dict[str, Any]) -> bool:
        if self.phase == "evaluate":
            self._stamp_failure(case)
            return False
        return True

    def teardown(self, case: dict[str, Any], topology: Any) -> Any:
        self.teardown_calls += 1
        return self.cleanup_result


@pytest.mark.parametrize("phase", ["setup", "verify", "step", "evaluate", "exception"])
def test_direct_pipeline_honors_matching_terminal_abort_and_skips_teardown(
    phase: str,
) -> None:
    plugin = _DirectAbortPlugin(phase=phase)

    result = plugin.run_pipeline(
        {"id": "D036", "steps": [{"id": "probe", "command": "read state"}]},
        topology=None,
    )

    assert result["verdict"] is False
    assert plugin.teardown_calls == 0
    assert result["diagnostic_status"] == "FailEnv"
    assert result["abort_run"] is True
    assert result["abort_reason"] == "device_state_terminal"
    assert result["failure_snapshot"]["case_id"] == "D036"
    assert result["failure_snapshot"]["attempt_index"] == 1
    assert result["failure_snapshot"]["reason_code"] == "device_state_terminal"


@pytest.mark.parametrize(
    "failure",
    [
        {"case_id": "D999", "attempt_index": 1},
        {"case_id": "D036", "attempt_index": 2},
        {"case_id": "D036", "attempt_index": True},
        {"abort_run": 1},
        {"abort_run": "true"},
        {"abort_run": False},
        {"abort_run": None},
        {"abort_run": False, "skip_teardown": True},
    ],
)
def test_direct_pipeline_ignores_unbound_or_nonliteral_abort_directives(
    failure: dict[str, Any],
) -> None:
    plugin = _DirectAbortPlugin(phase="setup", failure=failure)

    result = plugin.run_pipeline(
        {"id": "D036", "steps": []},
        topology=None,
    )

    assert result["verdict"] is False
    assert "abort_run" not in result
    assert "failure_snapshot" not in result
    assert plugin.teardown_calls == 1


def test_direct_pipeline_clears_authored_failure_before_running_hooks() -> None:
    plugin = _DirectAbortPlugin(phase="ordinary")

    result = plugin.run_pipeline(
        {
            "id": "D036",
            "steps": [],
            "_last_failure": {
                "case_id": "D036",
                "attempt_index": 1,
                "abort_run": True,
                "skip_teardown": True,
            },
        },
        topology=None,
    )

    assert result["verdict"] is True
    assert "abort_run" not in result
    assert plugin.teardown_calls == 1


@pytest.mark.parametrize("skip_teardown", [False, 0, 1, "true", None])
def test_direct_pipeline_terminal_abort_without_literal_skip_runs_teardown(
    skip_teardown: Any,
) -> None:
    plugin = _DirectAbortPlugin(
        phase="setup",
        failure={"skip_teardown": skip_teardown},
    )

    result = plugin.run_pipeline({"id": "D036", "steps": []}, topology=None)

    assert result["abort_run"] is True
    assert result["abort_reason"] == "device_state_terminal"
    assert plugin.teardown_calls == 1


@pytest.mark.parametrize(
    ("abort_reason", "expected_reason"),
    [
        ("X" * 512, "X" * 128),
        ("invalid reason", "plugin_failure_abort"),
    ],
)
def test_direct_pipeline_sanitizes_explicit_abort_reason(
    abort_reason: str,
    expected_reason: str,
) -> None:
    plugin = _DirectAbortPlugin(
        phase="setup",
        failure={"abort_reason": abort_reason, "skip_teardown": False},
    )

    result = plugin.run_pipeline({"id": "D036", "steps": []}, topology=None)

    assert result["abort_run"] is True
    assert result["abort_reason"] == expected_reason


def test_direct_pipeline_projects_terminal_transport_evidence() -> None:
    plugin = _DirectAbortPlugin(
        phase="setup",
        failure={
            "transport_result": {
                "cmd_id": "bounded-receipt-id",
                "outcome": "completed",
                "unbounded_plugin_field": "not projected",
            }
        },
    )

    result = plugin.run_pipeline({"id": "D036", "steps": []}, topology=None)

    assert result["transport_result"] == {
        "cmd_id": "bounded-receipt-id",
        "outcome": "completed",
    }


def test_direct_pipeline_unknown_outcome_dominates_plugin_abort() -> None:
    plugin = _DirectAbortPlugin(
        phase="unknown",
        failure={"skip_teardown": False},
    )

    result = plugin.run_pipeline(
        {"id": "D036", "steps": [{"id": "mutate", "command": "change state"}]},
        topology=None,
    )

    assert result["abort_run"] is True
    assert result["abort_reason"] == "command_outcome_unknown"
    assert result["failure_snapshot"]["reason_code"] == "command_outcome_unknown"
    assert plugin.teardown_calls == 0


def test_direct_pipeline_cleanup_failure_keeps_precedence_over_abort_reason() -> None:
    plugin = _DirectAbortPlugin(
        phase="setup",
        failure={"skip_teardown": False},
        cleanup_result={
            "status": "failed",
            "reason_code": "cleanup_restore_failed",
            "comment": "cleanup did not verify",
        },
    )

    result = plugin.run_pipeline({"id": "D036", "steps": []}, topology=None)

    assert result["abort_run"] is True
    assert result["abort_reason"] == "cleanup_restore_failed"
    assert result["failure_snapshot"]["reason_code"] == "cleanup_restore_failed"
    assert plugin.teardown_calls == 1


def test_direct_pipeline_ordinary_completed_failure_keeps_legacy_result_shape() -> None:
    plugin = _DirectAbortPlugin(
        phase="setup",
        failure={"abort_run": False, "skip_teardown": False},
    )

    result = plugin.run_pipeline({"id": "D036", "steps": []}, topology=None)

    assert result["verdict"] is False
    assert "abort_run" not in result
    assert "failure_snapshot" not in result
    assert plugin.teardown_calls == 1
