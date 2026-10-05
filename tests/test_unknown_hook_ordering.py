"""Unknown transport outcomes stop action-capable lifecycle hooks and retries."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from typing import Any, Mapping

import pytest

from testpilot.core.execution_engine import ExecutionEngine
from testpilot.core.hook_policy import HookContext, HookDispatcher, HookPolicyConfig, HookResult
from testpilot.core.plugin_base import PluginBase


_CANARY = "unknown-hook-private-canary-c016"
_ALL_HOOKS = {
    "pre_case",
    "post_case",
    "pre_step",
    "post_step",
    "on_failure",
    "on_retry",
}


def _redact(value: Any) -> Any:
    if type(value) is str:
        return value.replace(_CANARY, "[private]")
    if isinstance(value, Mapping):
        return {
            (str(key).replace(_CANARY, "[private]") if type(key) is str else key): _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact(item) for item in value)
    return deepcopy(value)


def _unknown_receipt(cmd_id: str) -> dict[str, Any]:
    return {
        "cmd_id": cmd_id,
        "status": "accepted",
        "outcome": "unknown",
        "non_replayable": True,
        "retryable": False,
    }


class _UnknownTransportError(RuntimeError):
    def __init__(self) -> None:
        self.transport_result = _unknown_receipt("safe-exception-id")
        super().__init__(f"private error {_CANARY}")


class _OutcomePlugin(PluginBase):
    api_version = "1.7"

    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.setup_calls = 0
        self.verify_calls = 0
        self.step_calls = 0
        self.evaluate_calls = 0
        self.teardown_calls = 0
        self.projected_envelopes: list[tuple[str, dict[str, Any]]] = []

    @property
    def name(self) -> str:
        return "unknown-order-test"

    def discover_cases(self) -> list[dict[str, Any]]:
        return []

    def _mark_unknown(self, case: dict[str, Any], cmd_id: str) -> None:
        case["_last_failure"] = {
            "case_id": case["id"],
            "attempt_index": case["_attempt_index"],
            "category": "environment",
            "phase": self.mode,
            "reason_code": "command_outcome_unknown",
            "comment": f"hidden detail {_CANARY}",
            "output": _CANARY,
            "metadata": _unknown_receipt(cmd_id),
        }

    def setup_env(self, case: dict[str, Any], topology: Any) -> bool:
        self.setup_calls += 1
        if self.mode == "setup":
            self._mark_unknown(case, "safe-setup-id")
            return False
        if self.mode == "snapshot_after_setup":
            self._mark_unknown(case, "safe-snapshot-id")
        return True

    def verify_env(self, case: dict[str, Any], topology: Any) -> bool:
        self.verify_calls += 1
        if self.mode == "verify":
            self._mark_unknown(case, "safe-verify-id")
            return False
        return True

    def execute_step(
        self, case: dict[str, Any], step: dict[str, Any], topology: Any
    ) -> dict[str, Any]:
        self.step_calls += 1
        attempt = case["_attempt_index"]
        if self.mode == "execute_unknown":
            return {
                "success": False,
                "command": f"read {_CANARY}",
                "output": _CANARY,
                "transport_result": _unknown_receipt("safe-execute-id"),
            }
        if self.mode == "exception_unknown":
            raise _UnknownTransportError()
        if self.mode == "snapshot_after_step":
            self._mark_unknown(case, "safe-step-snapshot-id")
            return {"success": True, "output": f"ok {_CANARY}"}
        if self.mode == "known_retry" and attempt == 1:
            return {
                "success": False,
                "output": "completed rc 7",
                "transport_result": {
                    "cmd_id": "known-completed-id",
                    "status": "complete",
                    "outcome": "completed",
                },
            }
        if self.mode == "evaluate_unknown":
            return {"success": True, "output": "step completed"}
        return {"success": True, "output": f"ok {_CANARY}"}

    def evaluate(self, case: dict[str, Any], results: dict[str, Any]) -> bool:
        self.evaluate_calls += 1
        if self.mode == "evaluate_unknown":
            self._mark_unknown(case, "safe-evaluate-id")
        return self.mode != "known_retry" or case["_attempt_index"] > 1

    def teardown(self, case: dict[str, Any], topology: Any) -> Mapping[str, Any] | None:
        self.teardown_calls += 1
        if self.mode == "teardown_unknown":
            return {
                "status": "unknown",
                "reason_code": "cleanup_result_unknown",
                "comment": f"cleanup detail {_CANARY}",
                "transport_result": _unknown_receipt("safe-cleanup-id"),
            }
        return None

    def project_hook_payload(
        self, hook_name: str, payload: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        self.projected_envelopes.append((hook_name, deepcopy(dict(payload))))
        return {"data": _redact(payload["data"]), "context": _redact(payload["context"])}


def _case() -> dict[str, Any]:
    return {
        "id": "D171",
        "_plugin": "unknown-order-test",
        "steps": [
            {"id": "probe", "command": f"read {_CANARY}"},
            {"id": "must-not-run", "command": "read again"},
        ],
        "pass_criteria": [],
    }


def _execute(mode: str, callback=None):
    events: list[tuple[str, dict[str, Any]]] = []
    dispatcher = HookDispatcher(HookPolicyConfig(enabled_hooks=set(_ALL_HOOKS)))

    def record(ctx: HookContext, data: dict[str, Any]) -> HookResult:
        events.append((ctx.hook_name, deepcopy(data)))
        if callback is not None:
            return callback(ctx, data)
        return HookResult()

    for hook_name in sorted(_ALL_HOOKS):
        dispatcher.register(hook_name, record)
    plugin = _OutcomePlugin(mode)
    result = ExecutionEngine({}, dispatcher).execute_with_retry(
        plugin=plugin,
        case=_case(),
        runner={"provider": "stub", "model": "test"},
        execution_policy={
            "retry": {"max_attempts": 3},
            "failure_policy": "retry_then_fail_and_continue",
        },
    )
    return plugin, result, [name for name, _ in events], events


@pytest.mark.parametrize(
    ("mode", "expected_events", "expected_setup", "expected_verify", "expected_steps", "cmd_id"),
    [
        ("setup", ["pre_case"], 1, 0, 0, "safe-setup-id"),
        ("verify", ["pre_case"], 1, 1, 0, "safe-verify-id"),
        ("snapshot_after_setup", ["pre_case"], 1, 0, 0, "safe-snapshot-id"),
        ("execute_unknown", ["pre_case", "pre_step"], 1, 1, 1, "safe-execute-id"),
        ("exception_unknown", ["pre_case", "pre_step"], 1, 1, 1, "safe-exception-id"),
        ("snapshot_after_step", ["pre_case", "pre_step"], 1, 1, 1, "safe-step-snapshot-id"),
        (
            "evaluate_unknown",
            ["pre_case", "pre_step", "post_step", "pre_step", "post_step"],
            1,
            1,
            2,
            "safe-evaluate-id",
        ),
    ],
)
def test_unknown_outcome_suppresses_later_action_hooks_cleanup_and_replay(
    mode: str,
    expected_events: list[str],
    expected_setup: int,
    expected_verify: int,
    expected_steps: int,
    cmd_id: str,
) -> None:
    plugin, result, events, _ = _execute(mode)

    assert result.verdict is False
    assert result.abort_run is True
    assert result.abort_reason == "command_outcome_unknown"
    assert result.attempts_used == 1
    assert events == expected_events
    assert plugin.setup_calls == expected_setup
    assert plugin.verify_calls == expected_verify
    assert plugin.step_calls == expected_steps
    assert plugin.teardown_calls == 0
    assert not {"on_failure", "on_retry", "post_case"}.intersection(events)
    assert _CANARY not in str(asdict(result))
    assert result.attempts[0]["transport_result"]["cmd_id"] == cmd_id
    assert result.attempts[0]["transport_result"]["outcome"] == "unknown"
    if mode in {"execute_unknown", "snapshot_after_step"}:
        assert result.attempts[0]["commands"] == ["read [private]"]
    elif mode == "exception_unknown":
        assert result.attempts[0]["commands"] == []
    elif mode == "evaluate_unknown":
        assert result.attempts[0]["commands"] == ["read [private]", "read again"]
    else:
        assert result.attempts[0]["commands"] == []


def test_unknown_cleanup_result_stops_case_without_post_case_or_retry() -> None:
    plugin, result, events, _ = _execute("teardown_unknown")

    assert result.verdict is False
    assert result.abort_run is True
    assert result.abort_reason == "cleanup_result_unknown"
    assert result.attempts_used == 1
    assert events == [
        "pre_case",
        "pre_step",
        "post_step",
        "pre_step",
        "post_step",
    ]
    assert plugin.step_calls == 2
    assert plugin.evaluate_calls == 1
    assert plugin.teardown_calls == 1
    assert result.attempts[0]["transport_result"]["cmd_id"] == "safe-cleanup-id"
    assert result.attempts[0]["transport_result"]["outcome"] == "unknown"
    assert "post_case" not in events
    assert _CANARY not in str(asdict(result))


def test_unknown_returned_by_on_failure_control_stops_before_teardown_and_retry() -> None:
    def unknown_on_failure(ctx: HookContext, data: dict[str, Any]) -> HookResult:
        if ctx.hook_name == "on_failure":
            data["transport_result"] = _unknown_receipt("safe-on-failure-id")
        return HookResult()

    plugin, result, events, _ = _execute("known_retry", unknown_on_failure)

    assert result.abort_run is True
    assert result.abort_reason == "command_outcome_unknown"
    assert result.attempts_used == 1
    assert events == ["pre_case", "pre_step", "post_step", "on_failure"]
    assert plugin.step_calls == 1
    assert plugin.teardown_calls == 0
    assert result.attempts[0]["transport_result"]["cmd_id"] == "safe-on-failure-id"
    assert result.attempts[0]["transport_result"]["outcome"] == "unknown"


def test_unknown_returned_by_retry_hook_stops_before_second_attempt_and_post_case() -> None:
    def unknown_on_retry(ctx: HookContext, data: dict[str, Any]) -> HookResult:
        if ctx.hook_name == "on_retry":
            data["failure_snapshot"] = {
                "category": "environment",
                "phase": "retry_gate",
                "metadata": _unknown_receipt("safe-on-retry-id"),
            }
        return HookResult()

    plugin, result, events, _ = _execute("known_retry", unknown_on_retry)

    assert result.verdict is False
    assert result.abort_run is True
    assert result.abort_reason == "command_outcome_unknown"
    assert result.attempts_used == 1
    assert events == [
        "pre_case",
        "pre_step",
        "post_step",
        "on_failure",
        "on_retry",
    ]
    assert plugin.setup_calls == 1
    assert plugin.step_calls == 1
    assert plugin.teardown_calls == 1
    assert result.attempts[0]["transport_result"]["cmd_id"] == "safe-on-retry-id"
    assert result.attempts[0]["transport_result"]["outcome"] == "unknown"
    assert _CANARY not in str(asdict(result))


def test_known_completed_nonzero_step_still_runs_hooks_and_configured_retry() -> None:
    plugin, result, events, _ = _execute("known_retry")

    assert result.verdict is True
    assert result.abort_run is False
    assert result.attempts_used == 2
    assert plugin.setup_calls == 2
    assert plugin.step_calls == 3
    assert plugin.teardown_calls == 2
    assert "post_step" in events
    assert "on_failure" in events
    assert "on_retry" in events
    assert "post_case" in events
