from __future__ import annotations

from pathlib import Path

from testpilot.core.azure_auth import AzureAgentState, AzureAgentStatus, AzureAgentRuntime
from testpilot.core.orchestrator import Orchestrator


def test_orchestrator_does_not_probe_sdk_without_azure(monkeypatch, tmp_path: Path) -> None:
    import testpilot.core.orchestrator as orchestrator_module

    class ExplodingManager:
        def __init__(self) -> None:
            raise AssertionError("SDK session manager must not initialize without Azure")

    monkeypatch.setattr(orchestrator_module, "CopilotSessionManager", ExplodingManager)
    runtime = AzureAgentRuntime(AzureAgentStatus(AzureAgentState.DISABLED_NO_KEY))

    orch = Orchestrator(project_root=tmp_path, agent_runtime=runtime)

    assert orch.session_manager is None


def test_plugin_context_does_not_hold_private_agent_runtime() -> None:
    source = (Path(__file__).resolve().parents[1] / "src/testpilot/cli.py").read_text(
        encoding="utf-8"
    )

    assert 'ctx.obj["agent_runtime"]' not in source
    assert 'ctx.obj["provider_config"] = None' in source
