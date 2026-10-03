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
from testpilot.core.usage_ledger import UsageLedger
import testpilot.reporting.usage_reporter as usage_reporter
from testpilot.runtime import _serialwrap_log
from testpilot.runtime.orchestrator_run_backend_compat import OrchestratorRunBackendCompat
from testpilot.runtime.serialwrap_backend import SerialwrapBackend


def _retry_result(*, verdict: bool) -> RetryResult:
    return RetryResult(
        verdict=verdict,
        comment="",
        commands=[],
        outputs=[],
        attempts=[{"verdict": verdict}],
        attempts_used=1,
        max_attempts=1,
        failure_snapshot={},
    )


class _Reporter:
    def build_reports(self, run_result: Any) -> dict[str, Any]:
        return {
            "status": "ok",
            "cases_count": run_result.cases_count,
        }


class _Plugin:
    version = "0.1.0"
    name = "fake"

    def __init__(self, cases: list[dict[str, Any]]) -> None:
        self._cases = cases

    def prepare_run(self, case_ids: Any) -> PreparedRun:
        del case_ids
        return PreparedRun(cases=self._cases, artifacts={})

    def execution_policy(self, case: Any) -> dict[str, Any]:
        del case
        return {"mode": "sequential", "max_concurrency": 1}

    def create_reporter(self) -> _Reporter:
        return _Reporter()


class _Loader:
    def __init__(self, plugin: _Plugin) -> None:
        self.plugin = plugin

    def load(self, name: str) -> _Plugin:
        del name
        return self.plugin


class _RunBackend:
    def mark_position(self, handle: Any) -> None:
        del handle
        return None


class _RunnerSelector:
    def load_agent_config(self, plugin_name: str, *, plugin: Any) -> dict[str, Any]:
        del plugin_name, plugin
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
        plugin_name: str,
        case: dict[str, Any],
        agent_config: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        del plugin_name, agent_config
        runner = {"cli_agent": "copilot", "model": "gpt-5.4", "effort": "high"}
        return runner, {"case_id": case["id"], "selected": dict(runner)}


class _ExecutionEngine:
    def __init__(self, results: list[Any]) -> None:
        self.results = list(results)

    def execute_with_retry(
        self,
        *,
        plugin: Any,
        case: dict[str, Any],
        runner: dict[str, Any],
        execution_policy: dict[str, Any],
    ) -> RetryResult:
        del plugin, case, runner, execution_policy
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


class _AbortOrchestrator:
    def __init__(self, root: Path, plugin: _Plugin, engine: _ExecutionEngine) -> None:
        self.plugins_dir = root
        self.config = {}
        self.loader = _Loader(plugin)
        self.run_backend = _RunBackend()
        self.runner_selector = _RunnerSelector()
        self.run_handle = None
        self.execution_engine = engine
        self.agent_session_degraded = {"degraded": False, "reason": ""}
        self.usage_ledger = UsageLedger()
        self.agent_runtime = AzureAgentRuntime(AzureAgentStatus(AzureAgentState.DISABLED_NO_KEY))
        self.agent_recovery_support = {}

    def _plan_case(self, **kwargs: Any) -> CasePlanningResult:
        del kwargs
        return CasePlanningResult(status="skipped_no_agent")

    def _build_execution_engine(self, **kwargs: Any) -> None:
        del kwargs
        return None

    def _analyze_run(self, *, run_result: Any, metrics: dict[str, Any], direct_usage: Any) -> Any:
        del run_result, metrics, direct_usage
        return SimpleNamespace(
            status="complete",
            to_dict=lambda: {"status": "complete", "summary": "ok"},
        )

    def _start_run_capture(self, run_id: str) -> None:
        del run_id
        return None

    def _stop_run_capture(self) -> None:
        return None

    def _export_run_logs(self, **kwargs: Any) -> dict[str, str]:
        del kwargs
        return {}


class _RecordingSerialwrapBackend(SerialwrapBackend):
    def __init__(self) -> None:
        super().__init__()
        self.setup_metadata: list[dict[str, Any]] = []

    def setup_run(self, run_id: str, config: dict[str, Any]) -> Any:
        handle = super().setup_run(run_id, config)
        self.setup_metadata.append(dict(handle.meta.get("serialwrap_binding", {})))
        return handle


class _LeaseAbortOrchestrator(_AbortOrchestrator, OrchestratorRunBackendCompat):
    def _start_run_capture(self, run_id: str) -> Any:
        return OrchestratorRunBackendCompat._start_run_capture(self, run_id)

    def _stop_run_capture(self) -> None:
        OrchestratorRunBackendCompat._stop_run_capture(self)

    def _export_run_logs(self, **kwargs: Any) -> dict[str, str]:
        return OrchestratorRunBackendCompat._export_run_logs(self, **kwargs)


def test_run_writes_aborted_cost_artifacts_before_reraising(tmp_path: Path) -> None:
    plugin = _Plugin(
        [
            {"id": "D001", "steps": [{"command": "ok"}], "pass_criteria": ["pass"], "source": {"row": 1}},
            {"id": "D002", "steps": [{"command": "boom"}], "pass_criteria": ["pass"], "source": {"row": 2}},
            {"id": "D003", "steps": [{"command": "skip"}], "pass_criteria": ["pass"], "source": {"row": 3}},
        ]
    )
    orchestrator = _AbortOrchestrator(
        tmp_path,
        plugin,
        _ExecutionEngine([_retry_result(verdict=True), RuntimeError("boom on case 2")]),
    )

    with pytest.raises(RuntimeError, match="boom on case 2") as exc_info:
        run_loop.run(orchestrator, "fake", None, None)

    cost_payload = exc_info.value.core_cost_report
    assert cost_payload["status"] == "aborted"
    assert cost_payload["analysis_status"] == "skipped_aborted"
    assert Path(cost_payload["json_path"]).is_file()
    assert Path(cost_payload["markdown_path"]).is_file()
    analysis_path = Path(cost_payload["json_path"]).with_name("run-analysis.json")
    assert json.loads(analysis_path.read_text(encoding="utf-8"))["status"] == "skipped_aborted"


def test_run_survives_core_cost_report_builder_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plugin = _Plugin(
        [
            {"id": "D001", "steps": [{"command": "ok"}], "pass_criteria": ["pass"], "source": {"row": 1}},
        ]
    )
    orchestrator = _AbortOrchestrator(
        tmp_path,
        plugin,
        _ExecutionEngine([_retry_result(verdict=True)]),
    )

    monkeypatch.setattr(
        usage_reporter,
        "build_core_cost_report",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("report exploded")),
    )

    payload = run_loop.run(orchestrator, "fake", None, None)

    assert payload["status"] == "ok"
    assert payload["core_cost_report"]["status"] == "failed"
    assert payload["core_cost_report"]["error_type"] == "RuntimeError"


def test_pre_case_setup_failure_releases_serialwrap_owner_for_next_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    binary = tmp_path / "serialwrap-fake"
    binary.write_text("fake cli", encoding="utf-8")
    device = {
        "transport": "serialwrap",
        "binary": str(binary),
        "socket": str(tmp_path / "serialwrapd.sock"),
    }
    testbed = {
        "serialwrap_binary": str(binary),
        "devices": {"DUT": dict(device), "STA": dict(device)},
    }
    plugin = _Plugin([])
    backend = _RecordingSerialwrapBackend()
    orchestrator = _LeaseAbortOrchestrator(
        tmp_path,
        plugin,
        _ExecutionEngine([]),
    )
    orchestrator.run_backend = backend
    orchestrator._run_handle = None
    orchestrator.config = SimpleNamespace(raw={"testbed": testbed}, devices=testbed["devices"])

    monkeypatch.delenv("SERIALWRAP_BIN", raising=False)
    monkeypatch.delenv("SERIALWRAP_ENDPOINT", raising=False)
    monkeypatch.setattr(_serialwrap_log, "daemon_status", lambda: {"ok": True, "pid": 123})
    monkeypatch.setattr(_serialwrap_log, "wal_reset", lambda: {"ok": True})
    monkeypatch.setattr(_serialwrap_log, "get_wal_path", lambda: tmp_path / "raw.wal.ndjson")
    monkeypatch.setattr(
        _serialwrap_log,
        "get_current_seq",
        lambda **kwargs: 0,
    )

    load_calls = 0

    def fail_once(*args: Any, **kwargs: Any) -> dict[str, Any]:
        nonlocal load_calls
        del args, kwargs
        load_calls += 1
        if load_calls == 1:
            raise RuntimeError("pre-case setup failed")
        return {}

    monkeypatch.setattr(orchestrator.runner_selector, "load_agent_config", fail_once)
    with pytest.raises(RuntimeError, match="pre-case setup failed"):
        run_loop.run(orchestrator, "fake", None, None)

    assert backend.setup_metadata[0]["enabled"] is True
    assert _serialwrap_log._configured_owner is None
    assert backend._run_bindings == {}

    payload = run_loop.run(orchestrator, "fake", None, None)

    assert payload["status"] == "ok"
    assert len(backend.setup_metadata) == 2
    assert backend.setup_metadata[1]["enabled"] is True
    assert _serialwrap_log._configured_owner is None
