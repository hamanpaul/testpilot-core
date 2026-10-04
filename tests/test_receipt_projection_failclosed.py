from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

import pytest

from testpilot.core.cleanup_result import (
    has_unknown_transport_outcome,
    normalize_cleanup_result,
    project_transport_evidence,
)
from testpilot.core.execution_engine import ExecutionEngine
from testpilot.core.hook_policy import HookDispatcher, HookPolicyConfig, HookResult
from testpilot.core.plugin_base import PluginBase


class _UnreadableMapping(Mapping[str, Any]):
    def __getitem__(self, key: str) -> Any:
        raise RuntimeError("synthetic receipt access failure with secret-marker")

    def __iter__(self) -> Iterator[str]:
        return iter(("status", "cmd_id"))

    def __len__(self) -> int:
        return 2


class _RaisingResultProperty(RuntimeError):
    @property
    def result(self) -> Mapping[str, Any]:
        raise RuntimeError("synthetic receipt property failure with secret-marker")


class _RaisingTransportResultProperty(RuntimeError):
    @property
    def result(self) -> None:
        return None

    @property
    def transport_result(self) -> Mapping[str, Any]:
        raise RuntimeError("synthetic receipt property failure with secret-marker")


class _FreshChildMapping(Mapping[str, Any]):
    created = 0

    def __init__(self, depth: int, max_depth: int) -> None:
        self.depth = depth
        self.max_depth = max_depth
        type(self).created += 1

    def __getitem__(self, key: str) -> Any:
        if key != "metadata" or self.depth >= self.max_depth:
            raise KeyError(key)
        return type(self)(self.depth + 1, self.max_depth)

    def __iter__(self) -> Iterator[str]:
        return iter(("metadata",))

    def __len__(self) -> int:
        return 1


class _InfiniteKeyMapping(Mapping[str, Any]):
    iterated = 0
    length_calls = 0

    def __getitem__(self, key: str) -> Any:
        if key == "status":
            return "accepted"
        if key == "cmd_id":
            return "iter-control-id"
        raise KeyError(key)

    def get(self, key: str, default: Any = None) -> Any:
        raise RuntimeError("custom get should not be used")

    def __iter__(self) -> Iterator[str]:
        while True:
            type(self).iterated += 1
            yield f"unexpected-{type(self).iterated}"

    def __len__(self) -> int:
        type(self).length_calls += 1
        return 2


class _UnrenderableAcceptedResult(Mapping[str, Any]):
    def __getitem__(self, key: str) -> Any:
        if key == "metadata":
            return {"status": "accepted", "cmd_id": "accepted-render-id"}
        if key in {"command", "output"}:
            raise RuntimeError("synthetic command/output rendering secret-marker")
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return iter(("success", "metadata", "command", "output"))

    def __len__(self) -> int:
        return 4


class _UnstringifiableReceiptValue:
    def __str__(self) -> str:
        raise AssertionError("receipt value must not be stringified")


class _ReceiptPlugin(PluginBase):
    api_version = "1.5"

    def __init__(
        self,
        *,
        receipt: Any = None,
        wrapper: str = "metadata",
        success: bool = True,
        exception: Exception | None = None,
    ) -> None:
        self.receipt = receipt
        self.wrapper = wrapper
        self.success = success
        self.exception = exception
        self.step_calls = 0
        self.evaluate_calls = 0
        self.teardown_calls = 0

    @property
    def name(self) -> str:
        return "receipt-projection-test"

    def discover_cases(self) -> list[dict[str, Any]]:
        return []

    def setup_env(self, case: dict[str, Any], topology: Any) -> bool:
        return True

    def execute_step(
        self, case: dict[str, Any], step: dict[str, Any], topology: Any
    ) -> dict[str, Any]:
        self.step_calls += 1
        if self.exception is not None:
            raise self.exception
        result: dict[str, Any] = {"success": self.success, "output": "synthetic"}
        if self.receipt is not None:
            result[self.wrapper] = self.receipt
        return result

    def evaluate(self, case: dict[str, Any], results: dict[str, Any]) -> bool:
        self.evaluate_calls += 1
        return True

    def teardown(self, case: dict[str, Any], topology: Any) -> None:
        self.teardown_calls += 1


def _run(plugin: _ReceiptPlugin, dispatcher: HookDispatcher | None = None):
    return ExecutionEngine({}, dispatcher).execute_with_retry(
        plugin=plugin,
        case={
            "id": "D036",
            "steps": [
                {"id": "probe", "command": "read state"},
                {"id": "followup", "command": "read again"},
            ],
        },
        runner={"provider": "stub", "model": "test"},
        execution_policy={
            "retry": {"max_attempts": 2},
            "failure_policy": "retry_then_fail_and_continue",
        },
    )


class _UnrenderableResultPlugin(_ReceiptPlugin):
    def execute_step(
        self, case: dict[str, Any], step: dict[str, Any], topology: Any
    ) -> Mapping[str, Any]:
        self.step_calls += 1
        return _UnrenderableAcceptedResult()


@pytest.mark.parametrize("wrapper", ["metadata", "transport_result"])
@pytest.mark.parametrize("success", [True, False])
def test_unreadable_nested_mapping_aborts_engine_without_followup_io(
    wrapper: str,
    success: bool,
) -> None:
    plugin = _ReceiptPlugin(receipt=_UnreadableMapping(), wrapper=wrapper, success=success)

    result = _run(plugin)

    assert result.verdict is False
    assert result.abort_run is True
    assert result.abort_reason == "command_outcome_unknown"
    assert result.attempts_used == 1
    assert result.attempts[0]["transport_result"] == {
        "outcome": "unknown",
        "non_replayable": True,
        "error_code": "COMMAND_OUTCOME_UNKNOWN",
    }
    assert result.attempts[0]["commands"] == ["read state"]
    assert result.attempts[0]["outputs"] == [""]
    assert plugin.step_calls == 1
    assert plugin.evaluate_calls == 0
    assert plugin.teardown_calls == 0
    assert "secret-marker" not in result.comment
    assert "secret-marker" not in str(result.attempts[0]["transport_result"])


@pytest.mark.parametrize(
    "exception",
    [
        _RaisingResultProperty("synthetic local error"),
        _RaisingTransportResultProperty("synthetic local error"),
    ],
)
def test_throwing_exception_receipt_property_aborts_without_leaking_message(
    exception: Exception,
) -> None:
    plugin = _ReceiptPlugin(exception=exception)
    hook_payloads: list[dict[str, Any]] = []
    dispatcher = HookDispatcher(HookPolicyConfig(enabled_hooks={"on_failure"}))
    dispatcher.register(
        "on_failure",
        lambda ctx, data: (hook_payloads.append(dict(data)) or HookResult()),
    )

    result = _run(plugin, dispatcher)

    assert result.verdict is False
    assert result.abort_run is True
    assert result.abort_reason == "command_outcome_unknown"
    assert result.comment == "command outcome unknown"
    assert result.attempts_used == 1
    assert result.attempts[0]["transport_result"] == {
        "outcome": "unknown",
        "non_replayable": True,
        "error_code": "COMMAND_OUTCOME_UNKNOWN",
    }
    assert plugin.step_calls == 1
    assert plugin.evaluate_calls == 0
    assert plugin.teardown_calls == 0
    assert "secret-marker" not in result.comment
    assert "synthetic local error" not in result.comment
    assert "secret-marker" not in str(result.attempts[0]["transport_result"])
    assert hook_payloads == []


def test_direct_pipeline_keeps_unreadable_receipt_fail_closed() -> None:
    plugin = _ReceiptPlugin(receipt=_UnreadableMapping())

    result = plugin.run_pipeline(
        {"id": "D036", "steps": [{"id": "probe", "command": "read state"}]},
        topology=None,
    )

    assert result["verdict"] is False
    assert result["abort_run"] is True
    assert result["abort_reason"] == "command_outcome_unknown"
    assert result["comment"] == "command outcome unknown: probe"
    assert result["transport_result"] == {
        "outcome": "unknown",
        "non_replayable": True,
        "error_code": "COMMAND_OUTCOME_UNKNOWN",
    }
    assert plugin.step_calls == 1
    assert plugin.teardown_calls == 0
    assert "secret-marker" not in result["comment"]


def test_unreadable_receipt_is_classified_before_result_rendering() -> None:
    plugin = _UnrenderableResultPlugin()
    hook_payloads: list[dict[str, Any]] = []
    dispatcher = HookDispatcher(HookPolicyConfig(enabled_hooks={"on_failure"}))
    dispatcher.register(
        "on_failure",
        lambda ctx, data: (hook_payloads.append(dict(data)) or HookResult()),
    )
    result = ExecutionEngine({}, dispatcher).execute_with_retry(
        plugin=plugin,
        case={
            "id": "D036",
            "steps": [{"id": "probe", "command": "read state"}],
        },
        runner={"provider": "stub", "model": "test"},
        execution_policy={"retry": {"max_attempts": 2}},
    )

    assert result.abort_run is True
    assert result.attempts_used == 1
    assert result.attempts[0]["commands"] == ["read state"]
    assert result.attempts[0]["outputs"] == [""]
    assert plugin.step_calls == 1
    assert plugin.teardown_calls == 0
    assert "secret-marker" not in result.comment
    assert hook_payloads == []
    assert result.attempts[0]["transport_result"] == {
        "status": "accepted",
        "cmd_id": "accepted-render-id",
    }


def test_fresh_child_mapping_exhaustion_is_bounded_and_terminal() -> None:
    _FreshChildMapping.created = 0
    receipt = _FreshChildMapping(0, max_depth=1000)
    plugin = _ReceiptPlugin(receipt=receipt)

    result = _run(plugin)

    assert result.verdict is False
    assert result.abort_run is True
    assert result.abort_reason == "command_outcome_unknown"
    assert result.attempts_used == 1
    assert result.attempts[0]["transport_result"]["outcome"] == "unknown"
    assert result.attempts[0]["transport_result"]["non_replayable"] is True
    assert _FreshChildMapping.created < 100
    assert plugin.step_calls == 1
    assert plugin.evaluate_calls == 0
    assert plugin.teardown_calls == 0


def test_ordinary_exception_without_receipt_keeps_local_retry_behavior() -> None:
    plugin = _ReceiptPlugin(exception=RuntimeError("ordinary local failure"))

    result = _run(plugin)

    assert result.verdict is False
    assert result.abort_run is False
    assert result.attempts_used == 2
    assert "ordinary local failure" in result.comment
    assert plugin.step_calls == 2
    assert plugin.evaluate_calls == 0
    assert plugin.teardown_calls == 2


def test_cyclic_receipt_wrapper_terminates_and_preserves_known_marker() -> None:
    receipt: dict[str, Any] = {"outcome": "completed", "cmd_id": "cycle-control"}
    receipt["metadata"] = receipt

    assert project_transport_evidence(receipt) == {
        "outcome": "completed",
        "cmd_id": "cycle-control",
    }
    assert has_unknown_transport_outcome(receipt) is False


def test_cleanup_projection_marks_unreadable_nested_receipt_non_replayable() -> None:
    normalized = normalize_cleanup_result(
        {
            "status": "failed",
            "reason_code": "cleanup_restore_failed",
            "comment": "cleanup could not be verified",
            "transport_result": {"metadata": _UnreadableMapping()},
        }
    )

    assert normalized == {
        "status": "unknown",
        "reason_code": "cleanup_outcome_unknown",
        "comment": "cleanup could not be verified",
        "transport_result": {
            "outcome": "unknown",
            "non_replayable": True,
            "error_code": "COMMAND_OUTCOME_UNKNOWN",
        },
    }


def test_transport_projection_avoids_mapping_iteration_and_length() -> None:
    _InfiniteKeyMapping.iterated = 0
    _InfiniteKeyMapping.length_calls = 0
    receipt = _InfiniteKeyMapping()

    assert project_transport_evidence(receipt) == {
        "status": "accepted",
        "cmd_id": "iter-control-id",
    }
    assert has_unknown_transport_outcome(receipt) is True
    assert _InfiniteKeyMapping.iterated == 0
    assert _InfiniteKeyMapping.length_calls == 0


def test_invalid_receipt_value_is_not_stringified_and_fails_closed() -> None:
    evidence = project_transport_evidence(
        {"outcome": _UnstringifiableReceiptValue(), "cmd_id": "safe-command-id"}
    )

    assert evidence == {
        "cmd_id": "safe-command-id",
        "outcome": "unknown",
        "non_replayable": True,
        "error_code": "COMMAND_OUTCOME_UNKNOWN",
    }


def test_cleanup_result_key_iteration_has_a_finite_bound() -> None:
    _InfiniteKeyMapping.iterated = 0
    _InfiniteKeyMapping.length_calls = 0

    result = normalize_cleanup_result(_InfiniteKeyMapping())

    assert result is not None
    assert result["status"] == "unknown"
    assert result["reason_code"] == "cleanup_result_invalid"
    assert _InfiniteKeyMapping.iterated == 17
    assert _InfiniteKeyMapping.length_calls == 0
