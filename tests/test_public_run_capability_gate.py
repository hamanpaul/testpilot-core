from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from testpilot.api import (
    CaptureRolePlanRequest,
    PluginBase,
    PrepareRunAfterCaptureContext,
    PrepareRunGateOutcome,
)
from testpilot.core.azure_auth import AzureAgentRuntime, AzureAgentState, AzureAgentStatus
from testpilot.core.case_planning import CasePlanningResult
from testpilot.core.execution_engine import RetryResult
from testpilot.core.plugin_loader import PluginLoader
from testpilot.core.prepared_run import PreparedRun
from testpilot.core.run_analysis import RunAnalysisResult
from testpilot.core.run_start_gate import (
    PrepareRunGateEvidence,
    PrepareRunGateResult,
    RunCapability,
    StrictCaptureProviderAdmission,
    StrictCaptureProviderOutcome,
)
from testpilot.core.testbed_config import TestbedConfig
from testpilot.core.orchestrator import Orchestrator
from testpilot.runtime.run_backend import RunHandle
from testpilot.runtime.strict_capture import (
    StrictCaptureHarvest,
    StrictCaptureHarvestStatus,
    StrictCapturePosition,
)


_CASE = {
    "id": "D001",
    "source": {"row": 1},
    "steps": [{"id": "step1", "command": "synthetic target command"}],
    "pass_criteria": ["synthetic success"],
}


class _EntryPoint:
    name = "strict"

    def __init__(self, plugin_type: type[PluginBase], events: list[str]) -> None:
        self.plugin_type = plugin_type
        self.events = events

    def load(self) -> type[PluginBase]:
        self.events.append("entry_point_load")
        return self.plugin_type


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


class _CustomRunner:
    def __init__(self, plugin: PluginBase, events: list[str]) -> None:
        self.plugin = plugin
        self.events = events

    def run(
        self,
        orchestrator: Any,
        plugin_name: str,
        case_ids: list[str] | None,
        dut_fw_ver: str | None,
        provider_config: dict[str, Any] | None,
    ) -> dict[str, Any]:
        del orchestrator, dut_fw_ver, provider_config
        self.events.append("custom_runner_run")
        cases = self.plugin.discover_cases()
        if case_ids:
            cases = [case for case in cases if case["id"] in case_ids]
        rows = []
        for case in cases:
            result = self.plugin.run_pipeline(case, topology=case.get("topology"))
            rows.append({"case_id": case["id"], "verdict": bool(result["verdict"])})
        return {
            "plugin": plugin_name,
            "overall": "PASS" if rows and all(row["verdict"] for row in rows) else "FAIL",
            "results": rows,
        }


class _SupportedBackend:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.markers = iter([0, 0, 1, 2])
        self.positions = iter([0, 1])

    def strict_capture_preflight(
        self,
        run_id: str,
        config: Any,
        request: Any,
        role_plan: Any,
    ) -> StrictCaptureProviderAdmission:
        del run_id, config, request, role_plan
        self.events.append("strict_capture_preflight")
        return StrictCaptureProviderAdmission(StrictCaptureProviderOutcome.SUPPORTED)

    def begin_strict_capture(
        self,
        run_id: str,
        config: Any,
        request: Any,
        role_plan: Any,
    ) -> RunHandle:
        del config, request, role_plan
        self.events.append("begin_strict_capture")
        return RunHandle(run_id=run_id, seq_start=0, meta={"strict_capture": True})

    def mark_position(self, handle: Any) -> int:
        del handle
        self.events.append("mark_position")
        return next(self.markers)

    def get_strict_capture_context(
        self,
        handle: Any,
        *,
        run_id: str,
        run_seq_start: int,
    ) -> PrepareRunAfterCaptureContext:
        del handle
        self.events.append("get_strict_capture_context")
        return PrepareRunAfterCaptureContext(
            run_id=run_id,
            start_sequence=run_seq_start,
            capture_binding_id="fake-bound-capture",
        )

    def checkpoint_strict_capture(self, handle: Any) -> StrictCapturePosition:
        del handle
        self.events.append("checkpoint_strict_capture")
        sequence = next(self.positions)
        return StrictCapturePosition(sequence, f"position{sequence}")

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
            StrictCaptureHarvestStatus.COMPLETE,
            "capture_complete",
        )

    def release_strict_capture(self, handle: Any) -> None:
        del handle
        self.events.append("release_strict_capture")

    def cancel_strict_capture_preflight(self, run_id: str) -> None:
        del run_id
        self.events.append("cancel_strict_capture_preflight")


class _Api10CaptureBackend(_SupportedBackend):
    def strict_capture_preflight(
        self,
        run_id: str,
        config: Any,
        request: Any,
        role_plan: Any,
    ) -> StrictCaptureProviderAdmission:
        del run_id, config, request
        assert [role.role for role in role_plan.roles] == ["dut"]
        self.events.append("strict_capture_preflight")
        return StrictCaptureProviderAdmission(
            StrictCaptureProviderOutcome.REJECTED,
            "capture_provider_unsupported",
        )


class _ExecutionEngine:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def execute_with_retry(self, **kwargs: Any) -> RetryResult:
        self.events.append(f"execute:{kwargs['case']['id']}")
        return RetryResult(
            verdict=True,
            comment="",
            commands=["synthetic target command"],
            outputs=["synthetic success"],
            attempts=[{"verdict": True}],
            attempts_used=1,
            max_attempts=1,
            failure_snapshot={},
        )


def _plugin_type(
    events: list[str],
    *,
    custom_runner: bool = False,
    capabilities: Any = frozenset({RunCapability.STRICT_CAPTURE_BINDING}),
) -> type[PluginBase]:
    class Plugin(PluginBase):
        api_version = "1.6"
        required_run_capabilities = capabilities
        capture_role_plan_request = CaptureRolePlanRequest(roles=("dut",))

        def __init__(self) -> None:
            events.append("plugin_init")

        @property
        def name(self) -> str:
            return "strict"

        def discover_cases(self) -> list[dict[str, Any]]:
            events.append("discover_cases")
            return [dict(_CASE)]

        def bind_project_root(self, project_root: Path | str | None) -> None:
            del project_root
            events.append("bind_project_root")

        def prepare_run(self, case_ids: Any) -> PreparedRun:
            events.append("prepare_run")
            cases = [dict(_CASE)]
            if case_ids:
                cases = [case for case in cases if case["id"] in case_ids]
            return PreparedRun(cases=cases)

        def prepare_run_after_capture(
            self,
            prepared: PreparedRun,
            context: PrepareRunAfterCaptureContext,
        ) -> PrepareRunGateResult:
            del prepared, context
            events.append("prepare_run_after_capture")
            return PrepareRunGateResult(
                PrepareRunGateOutcome.ACCEPTED,
                "identity_verified",
                (
                    PrepareRunGateEvidence(
                        "selected_targets",
                        PrepareRunGateOutcome.ACCEPTED,
                        "same_boot_verified",
                    ),
                ),
            )

        def capture_dut_firmware_version(
            self,
            config: Any,
            cases: list[dict[str, Any]],
        ) -> dict[str, str]:
            del config, cases
            events.append("capture_dut_firmware_version")
            return {"git": "synthetic-fw"}

        def execution_policy(self, case: dict[str, Any]) -> dict[str, Any]:
            del case
            return {"mode": "sequential", "max_concurrency": 1}

        def create_reporter(self) -> _Reporter:
            events.append("create_reporter")
            return _Reporter(events)

        def setup_env(self, case: dict[str, Any], topology: Any) -> bool:
            del case, topology
            events.append("setup_env")
            return True

        def verify_env(self, case: dict[str, Any], topology: Any) -> bool:
            del case, topology
            events.append("verify_env")
            return True

        def execute_step(
            self,
            case: dict[str, Any],
            step: dict[str, Any],
            topology: Any,
        ) -> dict[str, Any]:
            del case, step, topology
            events.append("execute_step")
            return {"success": True, "output": "synthetic success"}

        def evaluate(self, case: dict[str, Any], results: dict[str, Any]) -> bool:
            del case, results
            events.append("evaluate")
            return True

        def teardown(self, case: dict[str, Any], topology: Any) -> None:
            del case, topology
            events.append("teardown")
            return None

    if custom_runner:
        def create_runner(self: Plugin) -> _CustomRunner:
            events.append("create_runner")
            return _CustomRunner(self, events)

        Plugin.create_runner = create_runner
    Plugin.required_run_capabilities = capabilities
    return Plugin


def _make_orchestrator(
    tmp_path: Path,
    plugin_type: type[PluginBase],
    events: list[str],
) -> Orchestrator:
    config_path = tmp_path / "testbed.yaml"
    config_path.write_text(
        "testbed:\n"
        "  devices:\n"
        "    dut:\n"
        "      selector: COM0\n"
        "      expected_device_by_id: /dev/fake-dut\n"
        "      profile: generic-console\n",
        encoding="utf-8",
    )
    orchestrator = Orchestrator(
        project_root=tmp_path,
        plugins_dir=tmp_path / "plugins",
        config_path=config_path,
        agent_runtime=AzureAgentRuntime(
            AzureAgentStatus(AzureAgentState.DISABLED_NO_KEY)
        ),
    )
    orchestrator.loader = PluginLoader.from_entry_points(
        [_EntryPoint(plugin_type, events)]
    )
    return orchestrator


def _configure_core_run(
    orchestrator: Orchestrator,
    events: list[str],
) -> None:
    orchestrator.run_backend = _SupportedBackend(events)
    orchestrator._start_run_capture = lambda run_id: events.append("start_run_capture")
    orchestrator._stop_run_capture = lambda: events.append("stop_run_capture")
    orchestrator._export_run_logs = lambda **kwargs: events.append("export_run_logs") or {}
    orchestrator._build_execution_engine = lambda **kwargs: None
    orchestrator._plan_case = lambda **kwargs: CasePlanningResult(status="skipped_no_agent")
    orchestrator.execution_engine = _ExecutionEngine(events)
    orchestrator.runner_selector.load_agent_config = (
        lambda *args, **kwargs: events.append("load_agent_config") or {}
    )
    orchestrator.runner_selector.build_execution_policy = (
        lambda agent_config: {
            "mode": "sequential",
            "max_concurrency": 1,
            "retry": {"max_attempts": 1},
            "failure_policy": "retry_then_fail_and_continue",
        }
    )
    orchestrator.runner_selector.select_case_runner = (
        lambda **kwargs: events.append("select_case_runner")
        or ({"cli_agent": "fake"}, {"case_id": kwargs["case"]["id"]})
    )
    orchestrator._analyze_run = lambda **kwargs: RunAnalysisResult(status="complete")


def test_public_entry_rejects_strict_custom_runner_before_bind_or_factory(
    tmp_path: Path,
) -> None:
    events: list[str] = []
    plugin_type = _plugin_type(events, custom_runner=True)
    orchestrator = _make_orchestrator(tmp_path, plugin_type, events)
    payload = orchestrator.run("strict", ["D001"])

    assert payload.get("status") == "aborted", (payload, events)
    assert payload["run_abort"]["reason_code"] == "strict_custom_runner_unsupported"
    assert payload["run_abort"]["unexecuted_case_ids"] == ["D001"]
    assert payload["run_abort"]["executed_case_count"] == 0
    assert "case_rows" not in payload
    assert events == ["entry_point_load", "plugin_init"]


def test_public_entry_rejects_legacy_custom_runner_even_with_fake_supported_provider(
    tmp_path: Path,
) -> None:
    events: list[str] = []
    plugin_type = _plugin_type(events, custom_runner=True)
    orchestrator = _make_orchestrator(tmp_path, plugin_type, events)
    orchestrator.run_backend = _SupportedBackend(events)

    payload = orchestrator.run("strict", ["D001"])

    assert payload.get("status") == "aborted", (payload, events)
    assert payload["run_abort"]["reason_code"] == "strict_custom_runner_unsupported"
    assert payload["run_abort"]["unexecuted_case_ids"] == ["D001"]
    assert events == ["entry_point_load", "plugin_init"]


def test_public_entry_rejects_malformed_capabilities_before_bind_or_factory(
    tmp_path: Path,
) -> None:
    events: list[str] = []
    plugin_type = _plugin_type(events, custom_runner=True, capabilities=["strict_capture_binding"])
    orchestrator = _make_orchestrator(tmp_path, plugin_type, events)
    orchestrator.run_backend = _SupportedBackend(events)

    payload = orchestrator.run("strict", ["D001"])

    assert payload.get("status") == "aborted", (payload, events)
    assert payload["run_abort"]["reason_code"] == "required_capabilities_invalid"
    assert payload["run_abort"]["unexecuted_case_ids"] == ["D001"]
    assert events == ["entry_point_load", "plugin_init"]


def test_public_entry_uses_core_context_gate_for_supported_strict_plugin(
    tmp_path: Path,
) -> None:
    events: list[str] = []
    plugin_type = _plugin_type(events)
    orchestrator = _make_orchestrator(tmp_path, plugin_type, events)
    _configure_core_run(orchestrator, events)

    payload = orchestrator.run("strict", ["D001"])

    assert payload["status"] == "ok"
    assert payload["case_rows"] == ["D001"]
    assert events.index("prepare_run_after_capture") < events.index(
        "capture_dut_firmware_version"
    )
    assert events.index("capture_dut_firmware_version") < events.index(
        "select_case_runner"
    )
    assert events.count("plugin_init") == 1
    assert "run_start_gate" in payload["artifacts"]
    assert "begin_strict_capture" in events
    assert events.count("checkpoint_strict_capture") == 2
    assert "harvest_strict_for_handle" in events
    assert "release_strict_capture" in events
    assert "start_run_capture" not in events
    assert "mark_position" not in events
    assert "export_run_logs" not in events
    assert "stop_run_capture" not in events


def test_public_entry_rejects_api10_provider_before_plugin_preparation(
    tmp_path: Path,
) -> None:
    events: list[str] = []
    plugin_type = _plugin_type(events)
    plugin_type.capture_role_plan_request = CaptureRolePlanRequest(roles=("dut",))
    orchestrator = _make_orchestrator(tmp_path, plugin_type, events)
    config_path = tmp_path / "testbed.yaml"
    config_path.write_text(
        "testbed:\n"
        "  devices:\n"
        "    DUT:\n"
        "      selector: COM0\n"
        "      expected_device_by_id: /dev/fake-dut\n"
        "      profile: generic-console\n",
        encoding="utf-8",
    )
    orchestrator.config = TestbedConfig(config_path)
    _configure_core_run(orchestrator, events)
    orchestrator.run_backend = _Api10CaptureBackend(events)

    payload = orchestrator.run("strict", ["D001"])

    assert payload.get("status") == "aborted", (payload, events)
    assert payload["run_abort"]["reason_code"] == "capture_provider_unsupported"
    assert payload["run_abort"]["unexecuted_case_ids"] == ["D001"]
    assert events == ["entry_point_load", "plugin_init", "strict_capture_preflight"]


def test_direct_strict_run_pipeline_rejects_before_setup_step_cleanup_or_verdict() -> None:
    events: list[str] = []
    plugin = _plugin_type(events)()

    with pytest.raises(RuntimeError, match="strict.*Core-owned"):
        plugin.run_pipeline(dict(_CASE), topology={})

    assert events == ["plugin_init"]


def test_legacy_custom_runner_and_direct_pipeline_keep_existing_behavior(
    tmp_path: Path,
) -> None:
    events: list[str] = []
    plugin_type = _plugin_type(
        events,
        custom_runner=True,
        capabilities=frozenset(),
    )
    orchestrator = _make_orchestrator(tmp_path, plugin_type, events)

    payload = orchestrator.run("strict", ["D001"])

    assert payload["overall"] == "PASS"
    assert payload["results"] == [{"case_id": "D001", "verdict": True}]
    assert events.index("bind_project_root") < events.index("create_runner")
    assert events.index("create_runner") < events.index("custom_runner_run")

    legacy_events: list[str] = []
    legacy_plugin = _plugin_type(legacy_events, capabilities=frozenset())()
    result = legacy_plugin.run_pipeline(dict(_CASE), topology={})
    assert result["verdict"] is True
    assert legacy_events == [
        "plugin_init",
        "setup_env",
        "verify_env",
        "execute_step",
        "evaluate",
        "teardown",
    ]
