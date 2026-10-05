from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from testpilot.core.prepared_run import PreparedRun
from testpilot.runtime.strict_capture import (
    StrictCaptureError,
    StrictCaptureHarvest,
    StrictCaptureHarvestStatus,
    StrictCapturePosition,
)

from test_public_run_capability_gate import (
    _CASE,
    _SupportedBackend,
    _configure_core_run,
    _make_orchestrator,
    _plugin_type,
)


class _CheckpointFailureBackend(_SupportedBackend):
    def __init__(self, events: list[str], fail_on_call: int) -> None:
        super().__init__(events)
        self.fail_on_call = fail_on_call
        self.checkpoint_calls = 0

    def checkpoint_strict_capture(self, handle: Any) -> StrictCapturePosition:
        del handle
        self.checkpoint_calls += 1
        self.events.append("checkpoint_strict_capture")
        if self.checkpoint_calls == self.fail_on_call:
            raise StrictCaptureError("capture_rpc_unknown", operation_uncertain=True)
        return StrictCapturePosition(10 + self.checkpoint_calls, f"p{self.checkpoint_calls}")

    def harvest_strict_for_handle(
        self,
        handle: Any,
        artifact_dir: Any,
        case_results: Any,
        case_seq_ranges: Any,
    ) -> StrictCaptureHarvest:
        del handle, artifact_dir, case_results, case_seq_ranges
        self.events.append("harvest_strict_for_handle")
        return StrictCaptureHarvest(
            StrictCaptureHarvestStatus.UNKNOWN,
            "capture_operation_unknown",
        )


@pytest.mark.parametrize(
    ("fail_on_call", "expected_rows", "expected_unexecuted"),
    [
        (1, [], ["D001", "D002"]),
        (2, ["D001"], ["D002"]),
    ],
)
def test_unknown_checkpoint_stops_cases_without_legacy_capture_or_fake_rows(
    tmp_path: Path,
    fail_on_call: int,
    expected_rows: list[str],
    expected_unexecuted: list[str],
) -> None:
    events: list[str] = []
    plugin_type = _plugin_type(events)

    def prepare_run(self: Any, case_ids: Any) -> PreparedRun:
        del self
        cases = [dict(_CASE), {**_CASE, "id": "D002"}]
        if case_ids:
            cases = [case for case in cases if case["id"] in case_ids]
        events.append("prepare_run")
        return PreparedRun(cases=cases)

    plugin_type.prepare_run = prepare_run
    orchestrator = _make_orchestrator(tmp_path, plugin_type, events)
    _configure_core_run(orchestrator, events)
    orchestrator.run_backend = _CheckpointFailureBackend(events, fail_on_call)

    payload = orchestrator.run("strict", ["D001", "D002"])

    assert payload["status"] == "aborted"
    assert payload["case_rows"] == expected_rows
    assert payload["run_abort"]["unexecuted_case_ids"] == expected_unexecuted
    assert payload["run_abort"]["core_run_capture"]["status"] == "unknown"
    executed = [event for event in events if event.startswith("execute:")]
    assert executed == (["execute:D001"] if fail_on_call == 2 else [])
    assert events.index("strict_capture_preflight") < events.index("bind_project_root")
    assert events.index("strict_capture_preflight") < events.index("prepare_run")
    assert "start_run_capture" not in events
    assert "mark_position" not in events
    assert "export_run_logs" not in events
    assert "stop_run_capture" not in events
    assert "release_strict_capture" in events
