from pathlib import Path

from testpilot.core.orchestrator import Orchestrator


class _FakeRunner:
    def __init__(self, payload):
        self.payload = payload

    def run(
        self,
        orchestrator,
        plugin_name,
        case_ids,
        dut_fw_ver,
        provider_config,
    ):
        del orchestrator, plugin_name, case_ids, dut_fw_ver, provider_config
        return self.payload


def test_custom_runner_reports_unsupported_core_cost_path(tmp_path: Path) -> None:
    orchestrator = Orchestrator(project_root=tmp_path)
    payload = orchestrator._run_via_runner(
        plugin=object(),
        runner=_FakeRunner({"status": "ok"}),
        plugin_name="fake",
        case_ids=["D001"],
        dut_fw_ver="FW1",
    )

    assert payload["core_cost_report"] == {
        "status": "unsupported_execution_path",
        "execution_path": "custom_runner",
        "coverage": "core_sdk_calls_only",
        "analysis_status": "unavailable",
    }


def test_custom_runner_non_mapping_payload_is_passed_through(tmp_path: Path) -> None:
    orchestrator = Orchestrator(project_root=tmp_path)
    payload = ["raw", "payload"]

    result = orchestrator._run_via_runner(
        plugin=object(),
        runner=_FakeRunner(payload),
        plugin_name="fake",
        case_ids=None,
        dut_fw_ver=None,
    )

    assert result is payload
