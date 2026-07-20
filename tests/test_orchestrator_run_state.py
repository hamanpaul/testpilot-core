from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import testpilot.core.orchestrator as orchestrator_module
from testpilot.core.azure_auth import AzureAgentRuntime, AzureAgentState, AzureAgentStatus
from testpilot.core.orchestrator import Orchestrator
from testpilot.core.prepared_run import PreparedRun
from testpilot.core.usage_ledger import UsageLedger


class _Reporter:
    def build_reports(self, run_result: Any) -> dict[str, Any]:
        return {
            "status": "ok",
            "cases_count": run_result.cases_count,
        }


class _Plugin:
    name = "fake"
    version = "0.1.0"

    def prepare_run(self, case_ids: Any) -> PreparedRun:
        del case_ids
        return PreparedRun(
            cases=[
                {
                    "id": "D001",
                    "steps": [{"id": "step-1", "command": "probe"}],
                    "pass_criteria": ["probe succeeds"],
                    "source": {"row": 1},
                }
            ]
        )

    def execution_policy(self, case: Any) -> dict[str, Any]:
        del case
        return {"mode": "sequential", "max_concurrency": 1}

    def setup_env(self, case: dict[str, Any], *, topology: Any) -> bool:
        del case, topology
        return True

    def verify_env(self, case: dict[str, Any], *, topology: Any) -> bool:
        del case, topology
        return True

    def execute_step(
        self,
        case: dict[str, Any],
        step: dict[str, Any],
        *,
        topology: Any,
    ) -> dict[str, Any]:
        del case, topology
        return {"success": True, "command": step["command"], "output": "ok"}

    def evaluate(self, case: dict[str, Any], results: dict[str, Any]) -> bool:
        del case, results
        return True

    def teardown(self, case: dict[str, Any], *, topology: Any) -> None:
        del case, topology

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
    def load_agent_config(
        self,
        plugin_name: str,
        *,
        plugin: Any,
    ) -> dict[str, Any]:
        del plugin_name, plugin
        return {
            "hooks": {
                "enabled_hooks": [
                    "pre_case",
                    "on_failure",
                    "on_retry",
                    "post_case",
                ],
                "fail_open": False,
            },
            "remediation": {
                "enabled": False,
                "tier2": {"enabled": False},
            },
        }

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
        runner = {
            "cli_agent": "copilot",
            "model": "gpt-5.4",
            "effort": "high",
        }
        return runner, {"case_id": case["id"], "selected": dict(runner)}


class _SessionManager:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def send_one_shot(
        self,
        request: Any,
        prompt: str,
        *,
        timeout_seconds: float,
    ) -> str:
        del timeout_seconds
        self.calls.append((request.session_id, prompt))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class _RunStateOrchestrator(Orchestrator):
    def __init__(
        self,
        root: Path,
        plugin: _Plugin,
        *,
        agent_runtime: AzureAgentRuntime,
        session_manager: _SessionManager | None,
    ) -> None:
        self.root = root
        self.plugins_dir = root
        self.config = object()
        self.run_backend = _RunBackend()
        self._run_handle = None
        self.loader = _Loader(plugin)
        self.runner_selector = _RunnerSelector()
        self.execution_engine = None
        self.agent_runtime = agent_runtime
        self.session_manager = session_manager
        self.agent_session_degraded = {"degraded": False, "reason": ""}
        self.usage_ledger = UsageLedger()
        self.agent_circuit_open = False
        self.agent_circuit_error_type = ""
        self.agent_recovery_support = {}

    def _start_run_capture(self, run_id: str) -> None:
        del run_id
        return None

    def _stop_run_capture(self) -> None:
        return None

    def _cleanup_case_session(self, session_id: str | None) -> None:
        del session_id

    def _export_run_logs(self, **kwargs: Any) -> dict[str, str]:
        del kwargs
        return {}


def _ready_runtime() -> AzureAgentRuntime:
    return AzureAgentRuntime(
        AzureAgentStatus(AzureAgentState.AZURE_READY, deployment="azure-deployment"),
        {"type": "azure", "base_url": "https://example.invalid", "api_key": "secret"},
    )


def _planning_payload() -> str:
    return json.dumps(
        {
            "risk_summary": "watch the initial probe",
            "attention_points": ["probe output"],
            "expected_observations": ["pass on first attempt"],
        }
    )


def _analysis_payload() -> str:
    return json.dumps(
        {
            "summary": "analysis complete",
            "benefit_assessment": ["planning succeeded"],
            "cost_observations": ["one batch"],
            "case_findings": [
                {
                    "case_id": "D001",
                    "assessment": "run completed",
                    "evidence": ["final pass"],
                }
            ],
        }
    )


def test_run_resets_circuit_runtime_and_ledger_between_runs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        orchestrator_module,
        "build_case_session_plan",
        lambda run_id, case_id, _runner, agent_runtime: {
            "session_id": f"{run_id}-{case_id}",
            "model": agent_runtime.status.deployment,
            "reasoning_effort": "high",
        },
    )
    orchestrator = _RunStateOrchestrator(
        tmp_path,
        _Plugin(),
        agent_runtime=_ready_runtime(),
        session_manager=_SessionManager(
            [
                TimeoutError("first run fails"),
                _planning_payload(),
                _analysis_payload(),
            ]
        ),
    )

    payload1 = orchestrator.run("fake")
    first_ledger = orchestrator.usage_ledger

    assert payload1["core_agent_analysis"]["status"] == "skipped_circuit_breaker"
    assert payload1["agent_session_degraded"]["degraded"] is True
    assert orchestrator.agent_circuit_open is True
    assert orchestrator.agent_runtime.status.state is AzureAgentState.DEGRADED

    payload2 = orchestrator.run("fake")
    report2 = json.loads(
        Path(payload2["core_cost_report"]["json_path"]).read_text(encoding="utf-8")
    )

    assert orchestrator.usage_ledger is not first_ledger
    assert payload2["core_agent_analysis"]["status"] == "complete"
    assert payload2["agent_session_degraded"] == {"degraded": False, "reason": ""}
    assert payload2["core_cost_report"]["status"] == "complete"
    assert report2["agent_state"]["initial_agent_state"] == "azure_ready"
    assert report2["agent_state"]["final_agent_state"] == "azure_ready"
    assert orchestrator.agent_runtime.status.state is AzureAgentState.AZURE_READY
    assert orchestrator.agent_circuit_open is False


def test_run_marks_ready_runtime_degraded_when_sdk_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        orchestrator_module,
        "build_case_session_plan",
        lambda run_id, case_id, _runner, agent_runtime: {
            "session_id": f"{run_id}-{case_id}",
            "model": agent_runtime.status.deployment,
            "reasoning_effort": "high",
        },
    )
    orchestrator = _RunStateOrchestrator(
        tmp_path,
        _Plugin(),
        agent_runtime=_ready_runtime(),
        session_manager=None,
    )
    monkeypatch.setattr(orchestrator, "_try_init_session_manager", lambda: None)

    payload = orchestrator.run("fake")
    report = json.loads(
        Path(payload["core_cost_report"]["json_path"]).read_text(encoding="utf-8")
    )

    assert payload["core_agent_analysis"]["status"] == "skipped_circuit_breaker"
    assert report["agent_state"]["final_agent_state"] == "degraded"
    assert payload["agent_session_degraded"]["degraded"] is False
    assert orchestrator.agent_circuit_open is True
    assert orchestrator.agent_circuit_error_type == "CopilotSDKUnavailableError"
    assert orchestrator.agent_runtime.status.state is AzureAgentState.DEGRADED
