from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from testpilot.core import run_loop
from testpilot.core.azure_auth import AzureAgentRuntime, AzureAgentState, AzureAgentStatus
from testpilot.core.case_planning import CasePlanningResult
from testpilot.core.execution_engine import RetryResult
from testpilot.core.prepared_run import PreparedRun
from testpilot.core.run_analysis import RunAnalysisResult
from testpilot.core.plugin_base import IncompatiblePluginError, PluginBase
from testpilot.core.plugin_loader import PluginLoader
from testpilot.core.run_start_gate import (
    PrepareRunAfterCaptureContext,
    PrepareRunGateEvidence,
    PrepareRunGateOutcome,
    PrepareRunGateResult,
    RunCapability,
)
from testpilot.core.usage_ledger import UsageLedger


_CASES = [
    {
        "id": "D001",
        "source": {"row": 1},
        "steps": [{"command": "synthetic"}],
        "pass_criteria": ["synthetic success"],
    },
    {
        "id": "D002",
        "source": {"row": 2},
        "steps": [{"command": "synthetic"}],
        "pass_criteria": ["synthetic success"],
    },
]


class _Plugin:
    name = "fake"
    version = "0.1.0"
    api_version = "1.6"
    required_run_capabilities = frozenset({RunCapability.STRICT_CAPTURE_BINDING})

    def __init__(self, events: list[str], gate_result: Any = None) -> None:
        self.events = events
        self.gate_result = gate_result

    def bind_project_root(self, project_root: Path | str | None) -> None:
        del project_root
        self.events.append("bind_project_root")

    def prepare_run(self, case_ids: list[str] | None) -> PreparedRun:
        self.events.append("prepare_run")
        if case_ids:
            selected = [case for case in _CASES if case["id"] in case_ids]
        else:
            selected = list(_CASES)
        return PreparedRun(cases=selected)

    def prepare_run_after_capture(self, prepared: PreparedRun, context: Any) -> Any:
        del prepared, context
        self.events.append("prepare_run_after_capture")
        if isinstance(self.gate_result, BaseException):
            raise self.gate_result
        return self.gate_result

    def capture_dut_firmware_version(self, config: Any, cases: list[dict[str, Any]]) -> dict[str, str]:
        del config, cases
        self.events.append("capture_dut_firmware_version")
        return {"git": "synthetic-fw"}

    def execution_policy(self, case: dict[str, Any]) -> dict[str, Any]:
        del case
        return {"mode": "sequential", "max_concurrency": 1}

    def create_reporter(self) -> _Reporter:
        return _Reporter(self.events)


class _Reporter:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def build_reports(self, run_result: Any) -> dict[str, Any]:
        self.events.append("build_reports")
        return {
            "status": "ok",
            "cases_count": run_result.cases_count,
            "case_rows": [record.case_id for record in run_result.cases],
            "artifacts": dict(run_result.artifacts),
        }


class _Loader:
    def __init__(self, plugin: _Plugin, events: list[str]) -> None:
        self.plugin = plugin
        self.events = events

    def load(self, name: str) -> _Plugin:
        assert name == "fake"
        self.events.append("load_plugin")
        return self.plugin


class _Backend:
    def __init__(
        self,
        events: list[str],
        markers: list[Any],
        context: Any = None,
    ) -> None:
        self.events = events
        self.markers = list(markers)
        self.context = context

    def mark_position(self, handle: Any) -> Any:
        del handle
        self.events.append("mark_position")
        marker = self.markers.pop(0) if self.markers else 99
        if isinstance(marker, BaseException):
            raise marker
        return marker

    def get_strict_capture_context(
        self,
        handle: Any,
        *,
        run_id: str,
        run_seq_start: int,
    ) -> Any:
        del handle
        self.events.append("get_strict_capture_context")
        return self.context if self.context is not None else PrepareRunAfterCaptureContext(
            run_id=run_id,
            start_sequence=run_seq_start,
            capture_binding_id="fake-bound-capture",
        )


class _BackendWithoutStrictContext:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def mark_position(self, handle: Any) -> int:
        del handle
        self.events.append("mark_position")
        return 0


class _RunnerSelector:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def load_agent_config(self, plugin_name: str, *, plugin: Any) -> dict[str, Any]:
        del plugin_name, plugin
        self.events.append("load_agent_config")
        return {}

    def build_execution_policy(self, agent_config: dict[str, Any]) -> dict[str, Any]:
        del agent_config
        return {
            "mode": "sequential",
            "max_concurrency": 1,
            "retry": {"max_attempts": 1},
            "failure_policy": "retry_then_fail_and_continue",
        }

    def select_case_runner(
        self,
        *,
        plugin_name: str,
        case: dict[str, Any],
        agent_config: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        del plugin_name, agent_config
        self.events.append(f"select_runner:{case['id']}")
        return {"cli_agent": "fake"}, {"case_id": case["id"]}


class _Engine:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.calls = 0

    def execute_with_retry(self, **kwargs: Any) -> RetryResult:
        case_id = kwargs["case"]["id"]
        self.events.append(f"execute:{case_id}")
        self.calls += 1
        return RetryResult(
            verdict=True,
            comment="",
            commands=[],
            outputs=[],
            attempts=[{"verdict": True}],
            attempts_used=1,
            max_attempts=1,
            failure_snapshot={},
        )


class _Orchestrator:
    def __init__(self, root: Path, plugin: _Plugin, events: list[str], markers: list[Any]) -> None:
        self.root = root
        self.plugins_dir = root / "plugins"
        self.config = {}
        self.loader = _Loader(plugin, events)
        self.run_backend = _Backend(events, markers)
        self.run_handle = None
        self.runner_selector = _RunnerSelector(events)
        self.execution_engine = _Engine(events)
        self.agent_session_degraded = {"degraded": False, "reason": ""}
        self.usage_ledger = UsageLedger()
        self.agent_runtime = AzureAgentRuntime(
            AzureAgentStatus(AzureAgentState.DISABLED_NO_KEY)
        )
        self.agent_recovery_support = {}
        self.events = events
        self.export_requests: list[dict[str, Any]] = []

    def _start_run_capture(self, run_id: str) -> None:
        del run_id
        self.events.append("start_run_capture")

    def _stop_run_capture(self) -> None:
        self.events.append("stop_run_capture")

    def _export_run_logs(self, **kwargs: Any) -> dict[str, str]:
        self.events.append("export_run_logs")
        self.export_requests.append(dict(kwargs))
        return {}

    def _plan_case(self, **kwargs: Any) -> CasePlanningResult:
        del kwargs
        self.events.append("plan_case")
        return CasePlanningResult(status="skipped_no_agent")

    def _build_execution_engine(self, **kwargs: Any) -> None:
        del kwargs
        self.events.append("build_execution_engine")

    def _analyze_run(self, **kwargs: Any) -> RunAnalysisResult:
        del kwargs
        self.events.append("analyze_run")
        return RunAnalysisResult(status="complete")


def test_strict_capture_capability_is_checked_before_prepare_run(tmp_path: Path) -> None:
    events: list[str] = []
    plugin = _Plugin(events)
    # The backend deliberately has no strict capture-context provider.
    orchestrator = _Orchestrator(tmp_path, plugin, events, markers=[0])
    orchestrator.run_backend = _BackendWithoutStrictContext(events)

    payload = run_loop.run(orchestrator, "fake", ["D001"], None)

    assert payload["status"] == "aborted"
    assert payload["run_abort"]["reason_code"] == "capture_capability_unavailable"
    assert payload["run_abort"]["unexecuted_case_ids"] == ["D001"]
    assert events == ["load_plugin"]


def test_required_gate_rejects_inherited_default_hook_before_prepare_run(
    tmp_path: Path,
) -> None:
    events: list[str] = []

    class MissingGatePlugin(_Plugin):
        prepare_run_after_capture = PluginBase.prepare_run_after_capture

    plugin = MissingGatePlugin(events)
    orchestrator = _Orchestrator(tmp_path, plugin, events, markers=[0])

    payload = run_loop.run(orchestrator, "fake", ["D001"], None)

    assert payload["status"] == "aborted"
    assert payload["run_abort"]["reason_code"] == "post_capture_gate_missing"
    assert payload["run_abort"]["unexecuted_case_ids"] == ["D001"]
    assert events == ["load_plugin"]


@pytest.mark.parametrize(
    ("api_version", "required_run_capabilities", "reason_code"),
    [
        ("1.6", frozenset({"strict_capture_binding"}), "required_capabilities_invalid"),
        (
            "2.0",
            frozenset({RunCapability.STRICT_CAPTURE_BINDING}),
            "required_capability_api_incompatible",
        ),
    ],
)
def test_malformed_or_incompatible_strict_capability_is_rejected_before_prepare(
    tmp_path: Path,
    api_version: str,
    required_run_capabilities: frozenset[Any],
    reason_code: str,
) -> None:
    events: list[str] = []

    class InvalidCapabilityPlugin(_Plugin):
        pass

    InvalidCapabilityPlugin.api_version = api_version
    InvalidCapabilityPlugin.required_run_capabilities = required_run_capabilities

    plugin = InvalidCapabilityPlugin(events)
    orchestrator = _Orchestrator(tmp_path, plugin, events, markers=[0])

    payload = run_loop.run(orchestrator, "fake", ["D001"], None)

    assert payload["status"] == "aborted"
    assert payload["run_abort"]["reason_code"] == reason_code
    assert payload["run_abort"]["unexecuted_case_ids"] == ["D001"]
    assert events == ["load_plugin"]


def test_missing_strict_run_start_marker_aborts_before_gate_version_and_cases(
    tmp_path: Path,
) -> None:
    events: list[str] = []
    plugin = _Plugin(events)
    orchestrator = _Orchestrator(tmp_path, plugin, events, markers=[None])

    payload = run_loop.run(orchestrator, "fake", None, None)

    assert payload["status"] == "aborted"
    assert payload["run_abort"]["reason_code"] == "run_start_marker_unavailable"
    assert payload["run_abort"]["unexecuted_case_ids"] == ["D001", "D002"]
    assert "prepare_run_after_capture" not in events
    assert "capture_dut_firmware_version" not in events
    assert not any(event.startswith("execute:") for event in events)
    assert "stop_run_capture" not in events
    assert payload.get("case_rows", []) == []


def test_strict_run_start_marker_exception_is_terminal_without_cleanup_io(
    tmp_path: Path,
) -> None:
    events: list[str] = []
    plugin = _Plugin(events)
    orchestrator = _Orchestrator(
        tmp_path,
        plugin,
        events,
        markers=[RuntimeError("private marker failure")],
    )

    payload = run_loop.run(orchestrator, "fake", ["D001"], None)

    assert payload["status"] == "aborted"
    assert payload["run_abort"]["reason_code"] == "run_start_marker_unavailable"
    assert payload["run_abort"]["unexecuted_case_ids"] == ["D001"]
    assert payload["run_abort"]["capture_status"] == "incomplete"
    assert "private marker failure" not in Path(payload["run_abort_path"]).read_text(
        encoding="utf-8"
    )
    assert "prepare_run_after_capture" not in events
    assert "capture_dut_firmware_version" not in events
    assert not any(event.startswith("execute:") for event in events)
    assert "stop_run_capture" not in events
    assert "export_run_logs" not in events


@pytest.mark.parametrize("partial_binding", [False, True])
def test_strict_capture_setup_exception_is_terminal_without_followup_io(
    tmp_path: Path,
    partial_binding: bool,
) -> None:
    events: list[str] = []
    plugin = _Plugin(events)
    orchestrator = _Orchestrator(tmp_path, plugin, events, markers=[0])

    def fail_during_setup(run_id: str) -> None:
        events.append("start_run_capture")
        if partial_binding:
            orchestrator.run_handle = object()
        raise RuntimeError("private partial capture setup detail")

    orchestrator._start_run_capture = fail_during_setup

    payload = run_loop.run(orchestrator, "fake", ["D002"], None)

    assert payload["status"] == "aborted"
    assert payload["run_abort"]["reason_code"] == "capture_setup_failed"
    assert payload["run_abort"]["unexecuted_case_ids"] == ["D002"]
    assert payload["run_abort"]["capture_status"] == "incomplete"
    assert "private partial capture setup detail" not in Path(
        payload["run_abort_path"]
    ).read_text(encoding="utf-8")
    assert "mark_position" not in events
    assert "prepare_run_after_capture" not in events
    assert "capture_dut_firmware_version" not in events
    assert not any(event.startswith("execute:") for event in events)
    assert "stop_run_capture" not in events
    assert "export_run_logs" not in events


def test_strict_no_io_selection_aborts_without_capture_or_case_execution(
    tmp_path: Path,
) -> None:
    events: list[str] = []

    class NoIoPlugin(_Plugin):
        def prepare_run(self, case_ids: list[str] | None) -> PreparedRun:
            prepared = super().prepare_run(case_ids)
            prepared.no_io = True
            return prepared

    plugin = NoIoPlugin(events)
    orchestrator = _Orchestrator(tmp_path, plugin, events, markers=[0])

    payload = run_loop.run(orchestrator, "fake", ["D002"], None)

    assert payload["status"] == "aborted"
    assert payload["run_abort"]["reason_code"] == "required_capture_disabled"
    assert payload["run_abort"]["unexecuted_case_ids"] == ["D002"]
    assert "start_run_capture" not in events
    assert "prepare_run_after_capture" not in events
    assert "capture_dut_firmware_version" not in events
    assert not any(event.startswith("execute:") for event in events)
    assert "export_run_logs" not in events


def test_strict_capture_context_must_match_actual_run_and_marker(tmp_path: Path) -> None:
    events: list[str] = []
    plugin = _Plugin(events)
    wrong_context = PrepareRunAfterCaptureContext("other-run", 0, "fake-bound-capture")
    orchestrator = _Orchestrator(tmp_path, plugin, events, markers=[0])
    orchestrator.run_backend = _Backend(events, markers=[0], context=wrong_context)

    payload = run_loop.run(orchestrator, "fake", ["D001"], None)

    assert payload["status"] == "aborted"
    assert payload["run_abort"]["reason_code"] == "capture_context_invalid"
    assert payload["run_abort"]["unexecuted_case_ids"] == ["D001"]
    assert "prepare_run_after_capture" not in events
    assert "capture_dut_firmware_version" not in events
    assert "stop_run_capture" not in events
    assert "export_run_logs" not in events


def test_forged_capture_context_is_terminal_before_plugin_gate(tmp_path: Path) -> None:
    events: list[str] = []
    plugin = _Plugin(events)
    forged_context = object.__new__(PrepareRunAfterCaptureContext)
    orchestrator = _Orchestrator(tmp_path, plugin, events, markers=[0])
    orchestrator.run_backend = _Backend(events, markers=[0], context=forged_context)

    payload = run_loop.run(orchestrator, "fake", ["D001"], None)

    assert payload["status"] == "aborted"
    assert payload["run_abort"]["reason_code"] == "capture_context_invalid"
    assert "prepare_run_after_capture" not in events
    assert "capture_dut_firmware_version" not in events
    assert "stop_run_capture" not in events
    assert "export_run_logs" not in events


def test_zero_start_marker_and_accepted_gate_precede_version_and_cases(tmp_path: Path) -> None:
    events: list[str] = []
    plugin = _Plugin(
        events,
        PrepareRunGateResult(
            outcome=PrepareRunGateOutcome.ACCEPTED,
            reason_code="identity_verified",
            evidence=(
                PrepareRunGateEvidence(
                    check="dut_identity",
                    outcome=PrepareRunGateOutcome.ACCEPTED,
                    reason_code="same_boot_verified",
                ),
            ),
        ),
    )
    orchestrator = _Orchestrator(tmp_path, plugin, events, markers=[0, 0, 0, 0, 0, 0])

    payload = run_loop.run(orchestrator, "fake", ["D001"], None)

    assert payload["status"] == "ok"
    assert payload["case_rows"] == ["D001"]
    assert events.index("get_strict_capture_context") < events.index("prepare_run_after_capture")
    assert events.index("prepare_run_after_capture") < events.index("capture_dut_firmware_version")
    assert events.index("capture_dut_firmware_version") < events.index("select_runner:D001")
    assert payload["artifacts"]["run_start_gate"]["reason_code"] == "identity_verified"
    assert orchestrator.export_requests[0]["run_seq_start"] == 0
    assert orchestrator.export_requests[0]["run_seq_end"] == 0


@pytest.mark.parametrize(
    ("marker", "reason_code"),
    [
        (None, "run_start_marker_unavailable"),
        (True, "run_start_marker_invalid"),
        (-1, "run_start_marker_invalid"),
        ("0", "run_start_marker_invalid"),
    ],
)
def test_invalid_strict_start_marker_is_terminal_before_capture_context_and_target_calls(
    tmp_path: Path,
    marker: Any,
    reason_code: str,
) -> None:
    events: list[str] = []
    plugin = _Plugin(events)
    orchestrator = _Orchestrator(tmp_path, plugin, events, markers=[marker])

    payload = run_loop.run(orchestrator, "fake", None, None)

    assert payload["status"] == "aborted"
    assert payload["run_abort"]["reason_code"] == reason_code
    assert payload["run_abort"]["capture_status"] == "incomplete"
    assert "get_strict_capture_context" not in events
    assert "prepare_run_after_capture" not in events
    assert "capture_dut_firmware_version" not in events
    assert not any(event.startswith("execute:") for event in events)
    assert "stop_run_capture" not in events
    assert "export_run_logs" not in events


@pytest.mark.parametrize(
    ("gate_result", "reason_code", "outcome"),
    [
        (None, "post_capture_gate_result_missing", "unknown"),
        ({"outcome": "accepted"}, "post_capture_gate_result_invalid", "unknown"),
        (
            object.__new__(PrepareRunGateResult),
            "post_capture_gate_result_invalid",
            "unknown",
        ),
        (RuntimeError("private transport detail"), "post_capture_gate_exception", "unknown"),
        (
            PrepareRunGateResult(
                PrepareRunGateOutcome.FAILED,
                "identity_mismatch",
                (PrepareRunGateEvidence("dut_identity", PrepareRunGateOutcome.FAILED, "boot_id_mismatch"),),
            ),
            "identity_mismatch",
            "failed",
        ),
        (
            PrepareRunGateResult(
                PrepareRunGateOutcome.UNKNOWN,
                "identity_unavailable",
                (PrepareRunGateEvidence("sta_identity", PrepareRunGateOutcome.UNKNOWN, "readback_timeout"),),
            ),
            "identity_unavailable",
            "unknown",
        ),
    ],
)
def test_nonaccepted_strict_gate_is_terminal_without_version_case_or_cleanup_io(
    tmp_path: Path,
    gate_result: Any,
    reason_code: str,
    outcome: str,
) -> None:
    events: list[str] = []
    plugin = _Plugin(events, gate_result)
    orchestrator = _Orchestrator(tmp_path, plugin, events, markers=[0])

    payload = run_loop.run(orchestrator, "fake", ["D002"], None)

    assert payload["status"] == "aborted"
    assert payload["run_abort"]["outcome"] == outcome
    assert payload["run_abort"]["reason_code"] == reason_code
    assert payload["run_abort"]["unexecuted_case_ids"] == ["D002"]
    assert payload["run_abort"]["executed_case_count"] == 0
    assert "case_rows" not in payload
    assert "capture_dut_firmware_version" not in events
    assert "load_agent_config" not in events
    assert not any(event.startswith("execute:") for event in events)
    assert "stop_run_capture" not in events
    assert "export_run_logs" not in events
    abort_artifact = json.loads(Path(payload["run_abort_path"]).read_text(encoding="utf-8"))
    assert abort_artifact["unexecuted_case_ids"] == ["D002"]
    if isinstance(gate_result, PrepareRunGateResult) and hasattr(gate_result, "reason_code"):
        assert abort_artifact["gate"]["reason_code"] == reason_code
    else:
        assert "private transport detail" not in Path(payload["run_abort_path"]).read_text(encoding="utf-8")


def test_accepted_outcome_with_unknown_subcheck_is_not_accepted(tmp_path: Path) -> None:
    events: list[str] = []
    plugin = _Plugin(
        events,
        PrepareRunGateResult(
            PrepareRunGateOutcome.ACCEPTED,
            "identity_verified",
            (PrepareRunGateEvidence("sta_identity", PrepareRunGateOutcome.UNKNOWN, "readback_missing"),),
        ),
    )
    orchestrator = _Orchestrator(tmp_path, plugin, events, markers=[0])

    payload = run_loop.run(orchestrator, "fake", ["D001"], None)

    assert payload["status"] == "aborted"
    assert payload["run_abort"]["reason_code"] == "post_capture_gate_result_invalid"
    assert "capture_dut_firmware_version" not in events


def test_invalid_strict_end_marker_marks_capture_incomplete_without_export(tmp_path: Path) -> None:
    events: list[str] = []
    accepted = PrepareRunGateResult(PrepareRunGateOutcome.ACCEPTED, "identity_verified")
    plugin = _Plugin(events, accepted)
    orchestrator = _Orchestrator(tmp_path, plugin, events, markers=[0, 0, 0, None])

    payload = run_loop.run(orchestrator, "fake", ["D001"], None)

    assert payload["status"] == "ok"
    assert payload["case_rows"] == ["D001"]
    assert payload["artifacts"]["core_run_capture"] == {
        "status": "incomplete",
        "reason_code": "run_end_marker_invalid",
        "run_seq_start": 0,
        "run_seq_end": None,
    }
    assert orchestrator.export_requests == []
    assert "stop_run_capture" in events


def test_invalid_strict_case_range_marks_capture_incomplete_without_export(
    tmp_path: Path,
) -> None:
    events: list[str] = []
    accepted = PrepareRunGateResult(PrepareRunGateOutcome.ACCEPTED, "identity_verified")
    plugin = _Plugin(events, accepted)
    orchestrator = _Orchestrator(
        tmp_path,
        plugin,
        events,
        markers=[0, None, 1, 2],
    )

    payload = run_loop.run(orchestrator, "fake", ["D001"], None)

    assert payload["status"] == "ok"
    assert payload["case_rows"] == ["D001"]
    assert payload["artifacts"]["core_run_capture"] == {
        "status": "incomplete",
        "reason_code": "case_sequence_range_invalid",
        "run_seq_start": 0,
        "run_seq_end": 2,
    }
    assert orchestrator.export_requests == []


def test_legacy_plugin_does_not_call_new_context_or_gate_hooks(tmp_path: Path) -> None:
    events: list[str] = []

    class LegacyPlugin(_Plugin):
        required_run_capabilities = frozenset()

    plugin = LegacyPlugin(events, gate_result=None)
    orchestrator = _Orchestrator(tmp_path, plugin, events, markers=[4, 4, 5, 5, 5, 6])

    payload = run_loop.run(orchestrator, "fake", ["D001"], None)

    assert payload["status"] == "ok"
    assert payload["case_rows"] == ["D001"]
    assert "get_strict_capture_context" not in events
    assert "prepare_run_after_capture" not in events
    assert events.index("capture_dut_firmware_version") < events.index("select_runner:D001")


def test_api_15_host_rejects_api_16_plugin_before_instantiation_or_prepare(
    monkeypatch: Any,
) -> None:
    import testpilot.api

    events: list[str] = []

    class _EntryPoint:
        name = "hybrid"

        def load(self) -> type[Any]:
            events.append("entry_point_load")
            return _Api16Plugin

    class _Api16Plugin(PluginBase):
        api_version = "1.6"

        def __init__(self) -> None:
            events.append("plugin_init")

        @property
        def name(self) -> str:
            return "hybrid"

        def discover_cases(self) -> list[dict[str, Any]]:
            return []

        def execute_step(self, case: dict[str, Any], step: dict[str, Any], topology: Any) -> dict[str, Any]:
            del case, step, topology
            events.append("execute_step")
            return {}

        def evaluate(self, case: dict[str, Any], results: dict[str, Any]) -> bool:
            del case, results
            return True

        def prepare_run(self, case_ids: Any) -> PreparedRun:
            del case_ids
            events.append("prepare_run")
            return PreparedRun(cases=[])

    monkeypatch.setattr(testpilot.api, "API_VERSION", "1.5")
    loader = PluginLoader.from_entry_points([_EntryPoint()])

    try:
        run_loop.run(SimpleNamespace(loader=loader), "hybrid", ["D001"], None)
    except IncompatiblePluginError as exc:
        assert "requested SDK API version 1.6" in str(exc)
    else:
        raise AssertionError("API 1.5 host accepted an API 1.6 plugin")

    assert events == ["entry_point_load"]
