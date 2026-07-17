"""Focused core-only tests for Azure tier-2 recovery gating."""

from __future__ import annotations

from testpilot.core.azure_auth import (
    AzureAgentRuntime,
    AzureAgentState,
    AzureAgentStatus,
)
from testpilot.core.remediation import tier2_support


class _DefaultPlugin:
    pass


class _ContextOnlyPlugin:
    def build_tier2_remediation_context(self, *args, **kwargs):
        del args, kwargs
        return {}


class _Tier2Plugin(_ContextOnlyPlugin):
    def execute_tier2_remediation(self, *args, **kwargs):
        del args, kwargs
        return {"success": True}


def _policy(*, enabled: bool = True, tier2_enabled: bool = True) -> dict:
    return {"enabled": enabled, "tier2": {"enabled": tier2_enabled}}


def test_tier2_support_requires_both_plugin_overrides_and_policy() -> None:
    assert tier2_support(_DefaultPlugin(), _policy()).reason == "plugin_capability_unavailable"
    assert tier2_support(_ContextOnlyPlugin(), _policy()).reason == "plugin_executor_unavailable"
    assert tier2_support(_Tier2Plugin(), _policy(tier2_enabled=False)).reason == "tier2_policy_disabled"
    assert tier2_support(_Tier2Plugin(), _policy()).supported is True


def test_no_agent_runtime_is_never_tier2_ready() -> None:
    runtime = AzureAgentRuntime(AzureAgentStatus(AzureAgentState.DISABLED_NO_KEY))
    assert runtime.status.ready is False


def test_recovery_model_is_runtime_deployment_not_runner_model() -> None:
    runtime = AzureAgentRuntime(
        AzureAgentStatus(AzureAgentState.AZURE_READY, deployment="azure-deployment")
    )
    assert runtime.status.deployment != "plugin-model"
