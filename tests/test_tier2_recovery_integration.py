"""Hermetic core run-loop coverage for tier-2 environment recovery."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from testpilot.core import run_loop
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


class _Tier2Plugin:
    name = "fake"
    version = "0.1.0"

    def __init__(self) -> None:
        self.verify_results = [False, False, True, True]
        self.tier1_results = [
            {"success": False, "verify_after": False},
            {"success": False, "verify_after": False},
        ]
        self.tier1_calls = 0
        self.tier2_calls = 0

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
            ],
        )

    def execution_policy(self, case: Any) -> dict[str, Any]:
        del case
        return {"mode": "sequential", "max_concurrency": 1}

    def setup_env(self, case: dict[str, Any], *, topology: Any) -> bool:
        del case, topology
        return True

    def verify_env(self, case: dict[str, Any], *, topology: Any) -> bool:
        del topology
        result = self.verify_results.pop(0)
        if not result:
            case["_last_failure"] = {
                "case_id": case["id"],
                "attempt_index": case.get("_attempt_index", 0),
                "phase": "verify_env",
                "comment": "environment not ready",
                "category": "environment",
                "reason_code": "not_ready",
            }
        return result

    def execute_step(
        self,
        case: dict[str, Any],
        step: dict[str, Any],
        *,
        topology: Any,
    ) -> dict[str, Any]:
        del case, topology
        return {
            "success": True,
            "command": step["command"],
            "output": "ok",
        }

    def evaluate(self, case: dict[str, Any], results: dict[str, Any]) -> bool:
        del case, results
        return True

    def teardown(self, case: dict[str, Any], *, topology: Any) -> None:
        del case, topology

    def build_remediation_decision(
        self,
        case: dict[str, Any],
        failure_snapshot: Any,
        topology: Any,
        *,
        runner: dict[str, Any] | None = None,
        remediation_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del case, topology, runner, remediation_policy
        self.tier1_calls += 1
        return {
            "case_id": failure_snapshot.case_id,
            "attempt_index": failure_snapshot.attempt_index,
            "summary": "deterministic environment repair",
            "actions": [{"executor_key": "tier1_repair"}],
        }

    def execute_remediation(
        self,
        case: dict[str, Any],
        decision: Any,
        topology: Any,
    ) -> dict[str, Any]:
        del case, decision, topology
        return self.tier1_results.pop(0)

    def build_tier2_remediation_context(
        self,
        case: dict[str, Any],
        failure_snapshot: Any,
        topology: Any,
        *,
        runner: dict[str, Any] | None = None,
        remediation_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        del case, failure_snapshot, topology, runner, remediation_policy
        return {
            "diagnosis": "readiness probe remains down",
            "log_excerpt": ["probe rc=1"],
            "capabilities": [
                {
                    "executor_key": "target_env_repair",
                    "description": "repair target environment",
                    "execution_boundary": "fake isolated target",
                    "params_schema": {},
                }
            ],
            "verify_env_definition": "readiness probe succeeds",
        }

    def execute_tier2_remediation(
        self,
        case: dict[str, Any],
        plan: dict[str, Any],
        topology: Any,
    ) -> dict[str, Any]:
        del case, plan, topology
        self.tier2_calls += 1
        return {
            "success": True,
            "comment": "tier-2 repair applied",
            "actions": [
                {"executor_key": "target_env_repair", "success": True}
            ],
        }

    def create_reporter(self) -> _Reporter:
        return _Reporter()


class _OpaqueCallbackTier2Plugin(_Tier2Plugin):
    def __init__(self, failure_phase: str) -> None:
        super().__init__()
        self.failure_phase = failure_phase
        self.verify_call_count = 0

    def verify_env(self, case: dict[str, Any], *, topology: Any) -> bool:
        self.verify_call_count += 1
        if self.failure_phase == "verify" and self.verify_call_count == 3:
            raise RuntimeError("opaque-plugin-secret-sentinel")
        return super().verify_env(case, topology=topology)

    def build_tier2_remediation_context(
        self,
        case: dict[str, Any],
        failure_snapshot: Any,
        topology: Any,
        *,
        runner: dict[str, Any] | None = None,
        remediation_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self.failure_phase == "context":
            raise RuntimeError("opaque-plugin-secret-sentinel")
        return super().build_tier2_remediation_context(
            case,
            failure_snapshot,
            topology,
            runner=runner,
            remediation_policy=remediation_policy,
        )

    def execute_tier2_remediation(
        self,
        case: dict[str, Any],
        plan: dict[str, Any],
        topology: Any,
    ) -> dict[str, Any]:
        if self.failure_phase == "execute":
            raise RuntimeError("opaque-plugin-secret-sentinel")
        return super().execute_tier2_remediation(case, plan, topology)


class _Loader:
    def __init__(self, plugin: _Tier2Plugin) -> None:
        self.plugin = plugin

    def load(self, name: str) -> _Tier2Plugin:
        del name
        return self.plugin


class _RunBackend:
    def mark_position(self, handle: Any) -> None:
        del handle
        return None


class _RunnerSelector:
    def __init__(
        self,
        *,
        timeout_seconds: float = 12.5,
        max_invocations_per_case: int = 1,
        max_total_attempts: int = 4,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_invocations_per_case = max_invocations_per_case
        self.max_total_attempts = max_total_attempts

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
                "enabled": True,
                "allowed_actions": ["tier1_repair"],
                "tier2": {
                    "enabled": True,
                    "escalate_after_tier1_failures": 2,
                    "max_invocations_per_case": self.max_invocations_per_case,
                    "max_actions": 2,
                    "max_total_attempts": self.max_total_attempts,
                    "timeout_seconds": self.timeout_seconds,
                },
            },
        }

    def build_execution_policy(self, agent_config: dict[str, Any]) -> dict[str, Any]:
        del agent_config
        return {
            "mode": "sequential",
            "max_concurrency": 1,
            "retry": {"max_attempts": 2},
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


class _OneShotManager:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, str, float]] = []

    def send_one_shot(
        self,
        request: Any,
        prompt: str,
        *,
        timeout_seconds: float,
    ) -> str:
        self.calls.append((request, prompt, timeout_seconds))
        if prompt.startswith("Return only JSON matching the fixed run-analysis schema."):
            return json.dumps(
                {
                    "summary": "analysis complete",
                    "benefit_assessment": ["tier-2 recovered the case"],
                    "cost_observations": ["one analysis batch"],
                    "case_findings": [
                        {
                            "case_id": "D001",
                            "assessment": "agent recovery restored readiness",
                            "evidence": ["final pass", "verify gate passed"],
                        }
                    ],
                }
            )
        return json.dumps(
            {
                "summary": "repair target environment",
                "rationale": "tier-1 did not restore readiness",
                "actions": [{"executor_key": "target_env_repair"}],
            }
        )


class _FailingOneShotManager(_OneShotManager):
    def send_one_shot(
        self,
        request: Any,
        prompt: str,
        *,
        timeout_seconds: float,
    ) -> str:
        self.calls.append((request, prompt, timeout_seconds))
        raise RuntimeError("opaque-one-shot-secret-sentinel")


class _InvalidOneShotManager(_OneShotManager):
    def send_one_shot(
        self,
        request: Any,
        prompt: str,
        *,
        timeout_seconds: float,
    ) -> str:
        self.calls.append((request, prompt, timeout_seconds))
        return "not-json"


class _IntegrationOrchestrator(Orchestrator):
    def __init__(
        self,
        root: Path,
        plugin: _Tier2Plugin,
        *,
        runner_selector: _RunnerSelector | None = None,
    ) -> None:
        self.root = root
        self.plugins_dir = root
        self.config = object()
        self.loader = _Loader(plugin)
        self.runner_selector = runner_selector or _RunnerSelector()
        self.run_backend = _RunBackend()
        self._run_handle = None
        self.session_manager = _OneShotManager()
        self.agent_runtime = AzureAgentRuntime(
            AzureAgentStatus(AzureAgentState.AZURE_READY, deployment="azure-deployment"),
            {"type": "azure", "base_url": "https://example.invalid", "api_key": "secret"},
        )
        self.usage_ledger = UsageLedger()
        self.agent_circuit_open = False
        self.agent_circuit_error_type = ""
        self.agent_recovery_support = {}
        self.agent_session_degraded = {"degraded": False, "reason": ""}

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


def test_core_run_loop_wires_one_shot_and_projects_bounded_audit(
    tmp_path: Path,
) -> None:
    plugin = _Tier2Plugin()
    orchestrator = _IntegrationOrchestrator(tmp_path, plugin)
    provider_config = {
        "type": "azure",
        "base_url": "https://example.invalid",
        "api_key": "provider-super-secret",
    }

    payload = run_loop.run(
        orchestrator,
        "fake",
        None,
        None,
        provider_config=provider_config,
    )

    assert plugin.tier1_calls == 2
    assert plugin.tier2_calls == 1
    assert payload["tier2_remediation"]["agent_recovered_case_ids"] == ["D001"]
    assert payload["tier2_remediation"]["audit"][0]["status"] == "verified"
    assert payload["core_agent_analysis"]["status"] == "complete"
    assert payload["core_cost_report"]["status"] == "complete"

    one_shot_calls = orchestrator.session_manager.calls
    recovery_calls = [item for item in one_shot_calls if "-remediate-" in item[0].session_id]
    assert len(recovery_calls) == 1
    request, prompt, timeout = recovery_calls[0]
    assert request.session_id.endswith("-case-D001-remediate-1")
    assert request.model == "azure-deployment"
    assert request.reasoning_effort == "high"
    assert request.provider["api_key"] == "secret"
    assert "test steps" in prompt
    assert timeout == 12.5

    trace_path = next(tmp_path.glob("fake/reports/*/agent_trace/D001.json"))
    trace_text = trace_path.read_text(encoding="utf-8")
    trace = json.loads(trace_text)
    assert [
        item["decision_source"] for item in trace["remediation_history"]
    ] == ["tier1-deterministic", "tier1-deterministic", "tier2-agent"]
    assert trace["tier2_audit"][0]["verify_gate"]["passed"] is True
    assert trace["agent_recovered"] is True
    assert "provider_config" not in trace["selection_trace"]
    assert "provider-super-secret" not in trace_text
    assert "https://example.invalid" not in trace_text


def test_one_shot_failure_is_loud_audited_redacted_and_fail_closed(
    tmp_path: Path,
    caplog: Any,
) -> None:
    plugin = _Tier2Plugin()
    plugin.verify_results = [False, False]
    orchestrator = _IntegrationOrchestrator(tmp_path, plugin)
    orchestrator.session_manager = _FailingOneShotManager()

    payload = run_loop.run(
        orchestrator,
        "fake",
        None,
        None,
        provider_config={"api_key": "provider-super-secret"},
    )

    assert payload["agent_session_degraded"]["degraded"] is True
    assert "provider-super-secret" not in json.dumps(payload)
    assert "opaque-one-shot-secret-sentinel" not in json.dumps(payload)
    assert "provider-super-secret" not in caplog.text
    assert "opaque-one-shot-secret-sentinel" not in caplog.text
    assert payload["tier2_remediation"]["agent_recovered_case_ids"] == []
    assert payload["tier2_remediation"]["audit"] == []
    assert plugin.tier2_calls == 0
    trace_path = next(tmp_path.glob("fake/reports/*/agent_trace/D001.json"))
    assert "opaque-one-shot-secret-sentinel" not in trace_path.read_text(
        encoding="utf-8"
    )


def test_invalid_one_shot_plan_degrades_session_and_is_rejected(
    tmp_path: Path,
) -> None:
    plugin = _Tier2Plugin()
    plugin.verify_results = [False, False]
    orchestrator = _IntegrationOrchestrator(tmp_path, plugin)
    orchestrator.session_manager = _InvalidOneShotManager()

    payload = run_loop.run(orchestrator, "fake", None, None)

    assert payload["agent_session_degraded"]["degraded"] is False
    assert payload["tier2_remediation"]["audit"][0]["status"] == "rejected"
    assert payload["tier2_remediation"]["audit"][0]["raw_response"] == ""
    assert plugin.tier2_calls == 0


def test_tier2_timeout_is_clamped_without_degrading_run(tmp_path: Path) -> None:
    plugin = _Tier2Plugin()
    orchestrator = _IntegrationOrchestrator(
        tmp_path,
        plugin,
        runner_selector=_RunnerSelector(timeout_seconds=3600),
    )

    payload = run_loop.run(orchestrator, "fake", None, None)

    recovery_calls = [
        item for item in orchestrator.session_manager.calls
        if "-remediate-" in item[0].session_id
    ]
    assert len(recovery_calls) == 1
    assert recovery_calls[0][2] == 600.0
    assert payload["agent_session_degraded"] == {"degraded": False, "reason": ""}
    assert payload["tier2_remediation"]["audit"][0]["warnings"]


@pytest.mark.parametrize(
    ("failure_phase", "expected_status"),
    [
        ("context", "rejected"),
        ("execute", "failed"),
        ("verify", "failed"),
    ],
)
def test_plugin_callback_exception_is_opaque_in_payload_and_trace(
    tmp_path: Path,
    caplog: Any,
    failure_phase: str,
    expected_status: str,
) -> None:
    plugin = _OpaqueCallbackTier2Plugin(failure_phase)
    orchestrator = _IntegrationOrchestrator(tmp_path, plugin)

    payload = run_loop.run(orchestrator, "fake", None, None)

    payload_text = json.dumps(payload)
    audit = payload["tier2_remediation"]["audit"][0]
    trace_path = next(tmp_path.glob("fake/reports/*/agent_trace/D001.json"))
    trace_text = trace_path.read_text(encoding="utf-8")

    assert audit["status"] == expected_status
    assert "RuntimeError" in audit["error"]
    assert "opaque-plugin-secret-sentinel" not in payload_text
    assert "opaque-plugin-secret-sentinel" not in trace_text
    assert "opaque-plugin-secret-sentinel" not in caplog.text
