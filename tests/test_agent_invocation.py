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
    orch = Orchestrator(project_root=Path(__file__).resolve().parents[1], agent_runtime=_runtime())
    orch.session_manager = manager
    orch.agent_runtime.status = AzureAgentStatus(
        AzureAgentState.AZURE_READY, deployment="azure-deployment"
    )
    orch.agent_circuit_open = False
    return orch


def _invoke(orch, case_id, validate=json.loads):
    return orch._invoke_agent_one_shot(
        run_id="run-1", case_id=case_id, purpose="case_planning",
        session_id=f"session-{case_id}", prompt='{"ok": true}',
        timeout_seconds=30, validate=validate,
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


def test_disabled_runtime_skips_without_starting_invocation():
    runtime = AzureAgentRuntime(AzureAgentStatus(AzureAgentState.DISABLED_NO_KEY))
    orch = Orchestrator(project_root=Path(__file__).resolve().parents[1], agent_runtime=runtime)
    with pytest.raises(AgentCallSkipped) as skipped:
        _invoke(orch, "D001")
    assert skipped.value.reason == "no_agent"
    assert orch.usage_ledger.snapshot().invocations == ()
