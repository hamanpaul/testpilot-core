from __future__ import annotations

from click.testing import CliRunner

import testpilot.cli as cli_module
from testpilot.cli import main
from testpilot.core.azure_auth import AzureAgentRuntime, AzureAgentState, AzureAgentStatus


class _EmptyOrchestrator:
    def discover_plugins(self) -> list[str]:
        return []


def _runtime(state: AzureAgentState, *, reason: str = "") -> AzureAgentRuntime:
    return AzureAgentRuntime(
        AzureAgentStatus(state, deployment="azure-deployment", reason_code=reason)
    )


def test_cli_emits_notice_for_misconfigured_azure(monkeypatch) -> None:
    observed: dict[str, object] = {}

    def _get_orchestrator(ctx, plugin_name=None):
        del plugin_name
        observed["provider_notice"] = ctx.obj["provider_notice"]
        return _EmptyOrchestrator()

    monkeypatch.setattr(
        cli_module,
        "resolve_azure_agent_runtime",
        lambda: _runtime(
            AzureAgentState.MISCONFIGURED,
            reason="missing_endpoint",
        ),
    )
    monkeypatch.setattr(cli_module, "get_orchestrator", _get_orchestrator)

    result = CliRunner().invoke(main, ["list-plugins"])

    assert result.exit_code == 0
    assert (
        "Azure agent support is misconfigured (missing_endpoint); "
        "continuing without agent features."
    ) in result.output
    assert observed["provider_notice"] == "azure_env"


def test_cli_notice_is_absent_without_key(monkeypatch) -> None:
    observed: dict[str, object] = {}

    def _get_orchestrator(ctx, plugin_name=None):
        del plugin_name
        observed["provider_notice"] = ctx.obj["provider_notice"]
        return _EmptyOrchestrator()

    monkeypatch.setattr(
        cli_module,
        "resolve_azure_agent_runtime",
        lambda: _runtime(AzureAgentState.DISABLED_NO_KEY),
    )
    monkeypatch.setattr(cli_module, "get_orchestrator", _get_orchestrator)

    result = CliRunner().invoke(main, ["list-plugins"])

    assert result.exit_code == 0
    assert "Azure agent support is misconfigured" not in result.output
    assert observed["provider_notice"] is None


def test_cli_notice_is_absent_when_ready(monkeypatch) -> None:
    observed: dict[str, object] = {}

    def _get_orchestrator(ctx, plugin_name=None):
        del plugin_name
        observed["provider_notice"] = ctx.obj["provider_notice"]
        return _EmptyOrchestrator()

    monkeypatch.setattr(
        cli_module,
        "resolve_azure_agent_runtime",
        lambda: _runtime(AzureAgentState.AZURE_READY),
    )
    monkeypatch.setattr(cli_module, "get_orchestrator", _get_orchestrator)

    result = CliRunner().invoke(main, ["list-plugins"])

    assert result.exit_code == 0
    assert "Azure agent support is misconfigured" not in result.output
    assert observed["provider_notice"] is None
