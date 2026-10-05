"""Direct PluginBase pipeline classifies transport receipts before rendering."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

from testpilot.core.plugin_base import PluginBase


_CASE = {
    "id": "D036",
    "steps": [{"id": "probe", "command": "submitted command"}],
}


class _UnstringifiableOutput:
    def __str__(self) -> str:
        raise RuntimeError("DIRECT_OUTPUT_STRING_CANARY")


class _OutputLookupTrap(Mapping[str, Any]):
    def __init__(self, receipt: Mapping[str, Any]) -> None:
        self._values = {"success": True, "metadata": receipt}

    def __getitem__(self, key: str) -> Any:
        if key == "output":
            raise RuntimeError("DIRECT_OUTPUT_LOOKUP_CANARY")
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter((*self._values, "output"))

    def __len__(self) -> int:
        return len(self._values) + 1


class _DirectPlugin(PluginBase):
    api_version = "1.5"

    def __init__(self, step_result: Any = None, step_error: Exception | None = None) -> None:
        self.step_result = step_result or {"success": True, "output": "read complete"}
        self.step_error = step_error
        self.step_calls = 0
        self.evaluate_calls = 0
        self.teardown_calls = 0

    @property
    def name(self) -> str:
        return "direct-receipt-render-test"

    def discover_cases(self) -> list[dict[str, Any]]:
        return []

    def execute_step(
        self, case: dict[str, Any], step: dict[str, Any], topology: Any
    ) -> Any:
        self.step_calls += 1
        if self.step_error is not None:
            raise self.step_error
        return self.step_result

    def evaluate(self, case: dict[str, Any], results: dict[str, Any]) -> bool:
        self.evaluate_calls += 1
        return True

    def teardown(self, case: dict[str, Any], topology: Any) -> None:
        self.teardown_calls += 1


def _accepted_receipt() -> dict[str, str]:
    return {"status": "accepted", "cmd_id": "direct-safe-receipt-id"}


def _assert_terminal_unknown(result: dict[str, Any], plugin: _DirectPlugin) -> None:
    assert result["verdict"] is False
    assert result["diagnostic_status"] == "FailEnv"
    assert result["comment"] == "command outcome unknown: probe"
    assert result["abort_run"] is True
    assert result["abort_reason"] == "command_outcome_unknown"
    assert result["commands"] == ["submitted command"]
    assert result["outputs"] == [""]
    assert result["failure_snapshot"]["reason_code"] == "command_outcome_unknown"
    assert result["failure_snapshot"]["transport_result"]["status"] == "accepted"
    assert (
        result["failure_snapshot"]["transport_result"]["cmd_id"]
        == "direct-safe-receipt-id"
    )
    assert plugin.step_calls == 1
    assert plugin.evaluate_calls == 0
    assert plugin.teardown_calls == 0


def test_direct_pipeline_classifies_receipt_before_stringifying_output() -> None:
    plugin = _DirectPlugin(
        {
            "success": True,
            "metadata": _accepted_receipt(),
            "output": _UnstringifiableOutput(),
        }
    )

    result = plugin.run_pipeline(_CASE, topology=None)

    _assert_terminal_unknown(result, plugin)
    assert "DIRECT_OUTPUT_STRING_CANARY" not in repr(result)


def test_direct_pipeline_classifies_receipt_before_output_mapping_lookup() -> None:
    plugin = _DirectPlugin(_OutputLookupTrap(_accepted_receipt()))

    result = plugin.run_pipeline(_CASE, topology=None)

    _assert_terminal_unknown(result, plugin)
    assert "DIRECT_OUTPUT_LOOKUP_CANARY" not in repr(result)


def test_direct_pipeline_preserves_completed_success_and_failure_behavior() -> None:
    success = _DirectPlugin({"success": True, "output": "  read complete  "})
    success_result = success.run_pipeline(_CASE, topology=None)

    assert success_result["verdict"] is True
    assert success_result["outputs"] == ["read complete"]
    assert success.evaluate_calls == 1
    assert success.teardown_calls == 1

    completed_failure = _DirectPlugin(
        {
            "success": False,
            "output": "completed command failed",
            "metadata": {"outcome": "completed", "returncode": 1},
        }
    )
    failure_result = completed_failure.run_pipeline(_CASE, topology=None)

    assert failure_result["verdict"] is False
    assert failure_result["comment"] == "step failed: probe"
    assert "abort_run" not in failure_result
    assert completed_failure.evaluate_calls == 0
    assert completed_failure.teardown_calls == 1


def test_direct_pipeline_preserves_local_exception_behavior_without_receipt() -> None:
    plugin = _DirectPlugin(step_error=RuntimeError("ordinary local failure"))

    result = plugin.run_pipeline(_CASE, topology=None)

    assert result["verdict"] is False
    assert result["comment"] == "exception: ordinary local failure"
    assert "diagnostic_status" not in result
    assert plugin.evaluate_calls == 0
    assert plugin.teardown_calls == 1
