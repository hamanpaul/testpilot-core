import json
from pathlib import Path
import pytest

from testpilot.core.azure_auth import AzureAgentRuntime, AzureAgentState, AzureAgentStatus
from testpilot.core.orchestrator import (
    AgentCallSkipped,
    AgentProviderCallError,
    AgentResponseValidationError,
    Orchestrator,
)
import testpilot.core.orchestrator as orchestrator_module


def _runtime():
    return AzureAgentRuntime(
        AzureAgentStatus(AzureAgentState.AZURE_READY, deployment="azure-deployment"),
        {"type": "azure", "base_url": "https://azure.example", "api_key": "secret"},
    )


class _Manager:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def send_one_shot(self, request, prompt, *, timeout_seconds):
        self.calls += 1
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def _orch(manager):
    orch = Orchestrator(
        project_root=Path(__file__).resolve().parents[1],
        agent_runtime=AzureAgentRuntime(AzureAgentStatus(AzureAgentState.DISABLED_NO_KEY)),
    )
    orch.agent_runtime = _runtime()
    orch.session_manager = manager
    return orch


def _invoke(
    orch,
    case_id,
    validate=json.loads,
    *,
    prompt='{"ok": true}',
    timeout_seconds=30,
):
    return orch._invoke_agent_one_shot(
        run_id="run-1", case_id=case_id, purpose="case_planning",
        session_id=f"session-{case_id}", prompt=prompt,
        timeout_seconds=timeout_seconds, validate=validate,
    )


def test_malformed_response_does_not_open_circuit():
    orch = _orch(_Manager(["not-json", '{"ok": true}']))
    with pytest.raises(AgentResponseValidationError):
        _invoke(orch, "D001")
    _invoke(orch, "D002")
    assert orch.agent_circuit_open is False


def test_provider_failure_opens_circuit_and_skips_later_call():
    manager = _Manager([TimeoutError("opaque-secret")])
    orch = _orch(manager)
    with pytest.raises(AgentProviderCallError):
        _invoke(orch, "D001")
    with pytest.raises(AgentCallSkipped) as skipped:
        _invoke(orch, "D002")
    assert skipped.value.reason == "circuit_breaker"
    assert manager.calls == 1
    assert orch.agent_runtime.status.state is AzureAgentState.DEGRADED
    assert "opaque-secret" not in str(orch.agent_runtime.public_summary())


def test_local_request_validation_does_not_open_circuit():
    manager = _Manager(['{"ok": true}'])
    orch = _orch(manager)

    with pytest.raises(AgentResponseValidationError):
        _invoke(orch, "D001", validate=lambda raw: raw, prompt="x" * 64_001)

    _, parsed = _invoke(orch, "D002")

    assert parsed == {"ok": True}
    assert manager.calls == 1
    assert orch.agent_circuit_open is False
    assert orch.agent_runtime.status.state is AzureAgentState.AZURE_READY


def test_disabled_runtime_skips_without_starting_invocation():
    runtime = AzureAgentRuntime(AzureAgentStatus(AzureAgentState.DISABLED_NO_KEY))
    orch = Orchestrator(project_root=Path(__file__).resolve().parents[1], agent_runtime=runtime)
    with pytest.raises(AgentCallSkipped) as skipped:
        _invoke(orch, "D001")
    assert skipped.value.reason == "no_agent"
    assert orch.usage_ledger.snapshot().invocations == ()


def test_ready_runtime_initializes_session_manager_and_keeps_one_shot_callable(
    monkeypatch,
):
    class ProbeManager:
        def __init__(self):
            self.probed = False
            self.calls = 0

        def _load_sdk(self):
            self.probed = True

        def send_one_shot(self, request, prompt, *, timeout_seconds):
            self.calls += 1
            return '{"ok": true}'

    monkeypatch.setattr(orchestrator_module, "CopilotSessionManager", ProbeManager)
    orch = Orchestrator(
        project_root=Path(__file__).resolve().parents[1], agent_runtime=_runtime()
    )

    assert isinstance(orch.session_manager, ProbeManager)
    assert orch.session_manager.probed is True
    _, parsed = _invoke(orch, "D001")
    assert parsed == {"ok": True}
    assert orch.session_manager.calls == 1


def test_agent_recovery_invocations_keep_distinct_retry_session_ids():
    orch = _orch(_Manager(['{"ok": true}', '{"ok": true}']))

    orch._invoke_agent_one_shot(
        run_id="run-1",
        case_id="D001",
        purpose="agent_recovery",
        session_id="run-1-case-D001-remediate-1",
        prompt='{"ok": true}',
        timeout_seconds=30,
        validate=json.loads,
    )
    orch._invoke_agent_one_shot(
        run_id="run-1",
        case_id="D001",
        purpose="agent_recovery",
        session_id="run-1-case-D001-remediate-2",
        prompt='{"ok": true}',
        timeout_seconds=30,
        validate=json.loads,
    )

    invocations = [
        row for row in orch.usage_ledger.snapshot().invocations if row.purpose == "agent_recovery"
    ]

    assert [row.session_id for row in invocations] == [
        "run-1-case-D001-remediate-1",
        "run-1-case-D001-remediate-2",
    ]
    assert all(row.status == "completed" for row in invocations)
