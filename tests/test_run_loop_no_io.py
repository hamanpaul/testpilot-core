from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from testpilot.core.azure_auth import AzureAgentRuntime, AzureAgentState, AzureAgentStatus
from testpilot.core.execution_engine import RetryResult
from testpilot.core.orchestrator import Orchestrator
from testpilot.core.prepared_run import PreparedRun
from testpilot.runtime import _serialwrap_log
from testpilot.runtime.run_backend import ExportRequest, ExportResult, RunBackend, RunHandle
from testpilot.transport.serialwrap import SerialWrapTransport


_CASE = {
    "id": "D001",
    "steps": [{"command": "safe fake step"}],
    "pass_criteria": ["synthetic success"],
    "source": {"row": 1},
}


class _Plugin:
    name = "fake"
    version = "0.1.0"

    def __init__(
        self,
        cases: list[dict[str, Any]],
        *,
        no_io: bool = False,
        forbid_version_capture: bool = False,
    ) -> None:
        self.cases = cases
        self.no_io = no_io
        self.forbid_version_capture = forbid_version_capture
        self.version_capture_calls = 0

    def bind_project_root(self, project_root: Path | str | None) -> None:
        del project_root

    def prepare_run(self, case_ids: list[str] | None) -> PreparedRun:
        del case_ids
        if self.no_io:
            return PreparedRun(cases=self.cases, no_io=True)
        return PreparedRun(cases=self.cases)

    def capture_dut_firmware_version(
        self,
        config: Any,
        cases: list[dict[str, Any]],
    ) -> dict[str, str]:
        del config, cases
        self.version_capture_calls += 1
        if self.forbid_version_capture:
            raise AssertionError("firmware-version hardware query was forbidden")
        return {"git": "synthetic-fw"}

    def execution_policy(self, case: dict[str, Any]) -> dict[str, Any]:
        del case
        return {"mode": "sequential", "max_concurrency": 1}

    def create_reporter(self) -> _Reporter:
        return _Reporter()


class _Reporter:
    def build_reports(self, run_result: Any) -> dict[str, Any]:
        return {"status": "ok", "cases_count": run_result.cases_count}


class _Loader:
    def __init__(self, plugin: _Plugin) -> None:
        self.plugin = plugin

    def load(self, name: str) -> _Plugin:
        assert name == "fake"
        return self.plugin


class _NoIoBackend(RunBackend):
    @staticmethod
    def _forbidden(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise AssertionError("run backend I/O was forbidden")

    setup_run = _forbidden
    bind_sessions = _forbidden
    mark_position = _forbidden
    export_logs = _forbidden
    teardown_run = _forbidden


class _CountingBackend(RunBackend):
    def __init__(self) -> None:
        self.setup_calls = 0
        self.mark_calls = 0
        self.export_calls = 0
        self.teardown_calls = 0

    def setup_run(self, run_id: str, config: dict[str, Any]) -> RunHandle:
        del config
        self.setup_calls += 1
        return RunHandle(run_id=run_id, meta={"wal_path": None, "bind_sessions": False})

    def bind_sessions(self, handle: RunHandle, devices: list[dict[str, Any]]) -> None:
        del handle, devices

    def mark_position(self, handle: RunHandle) -> int:
        del handle
        self.mark_calls += 1
        return self.mark_calls

    def export_logs(self, request: ExportRequest) -> ExportResult:
        del request
        self.export_calls += 1
        return ExportResult()

    def teardown_run(self, handle: RunHandle) -> None:
        del handle
        self.teardown_calls += 1


class _Engine:
    def __init__(self) -> None:
        self.calls = 0

    def execute_with_retry(
        self,
        *,
        plugin: Any,
        case: dict[str, Any],
        runner: dict[str, Any],
        execution_policy: dict[str, Any],
    ) -> RetryResult:
        del plugin, case, runner, execution_policy
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


def _real_orchestrator(
    tmp_path: Path,
    plugin: _Plugin,
    backend: RunBackend,
    monkeypatch: pytest.MonkeyPatch,
) -> Orchestrator:
    config_path = tmp_path / "testbed.yaml"
    config_path.write_text("testbed: {}\n", encoding="utf-8")
    orchestrator = Orchestrator(
        project_root=tmp_path,
        plugins_dir=tmp_path / "plugins",
        config_path=config_path,
        agent_runtime=AzureAgentRuntime(
            AzureAgentStatus(AzureAgentState.DISABLED_NO_KEY)
        ),
    )
    orchestrator.loader = _Loader(plugin)
    orchestrator.run_backend = backend
    orchestrator.execution_engine = _Engine()
    monkeypatch.setattr(orchestrator, "_build_execution_engine", lambda **kwargs: None)
    monkeypatch.setattr(
        orchestrator.runner_selector,
        "load_agent_config",
        lambda *args, **kwargs: {},
    )
    monkeypatch.setattr(
        orchestrator.runner_selector,
        "build_execution_policy",
        lambda agent_config: {
            "mode": "sequential",
            "max_concurrency": 1,
            "retry": {"max_attempts": 1},
            "failure_policy": "retry_then_fail_and_continue",
        },
    )
    monkeypatch.setattr(
        orchestrator.runner_selector,
        "select_case_runner",
        lambda **kwargs: (
            {"cli_agent": "fake", "model": "fake", "effort": "low"},
            {"selected": "fake"},
        ),
    )
    return orchestrator


def _forbid_transport_rpc(*args: Any, **kwargs: Any) -> None:
    del args, kwargs
    raise AssertionError("serialwrap transport RPC was forbidden")


@pytest.mark.parametrize(
    ("cases", "no_io"),
    [([], False), ([_CASE], True)],
    ids=["empty-selection", "explicit-no-io-selection"],
)
def test_no_io_prepared_run_skips_all_hardware_capture_and_version_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cases: list[dict[str, Any]],
    no_io: bool,
) -> None:
    plugin = _Plugin(cases, no_io=no_io, forbid_version_capture=True)
    orchestrator = _real_orchestrator(tmp_path, plugin, _NoIoBackend(), monkeypatch)
    engine = orchestrator.execution_engine
    monkeypatch.setattr(_serialwrap_log, "_run_sw", _forbid_transport_rpc)
    monkeypatch.setattr(SerialWrapTransport, "execute", _forbid_transport_rpc)

    payload = orchestrator.run("fake")

    assert payload["status"] == "ok"
    assert payload["cases_count"] == len(cases)
    assert plugin.version_capture_calls == 0
    assert engine.calls == len(cases)


def test_mixed_prepared_run_keeps_normal_capture_and_version_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = _Plugin([_CASE], no_io=False)
    backend = _CountingBackend()
    orchestrator = _real_orchestrator(tmp_path, plugin, backend, monkeypatch)

    payload = orchestrator.run("fake")

    assert payload["status"] == "ok"
    assert payload["cases_count"] == 1
    assert plugin.version_capture_calls == 1
    assert backend.setup_calls == 1
    assert backend.mark_calls == 4
    assert backend.export_calls == 1
    assert backend.teardown_calls == 1
