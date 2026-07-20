from __future__ import annotations

import pytest

from testpilot.core.azure_auth import (
    AZURE_ENV_VARS,
    DEFAULT_API_VERSION,
    AzureAgentState,
    resolve_azure_agent_runtime,
)


@pytest.mark.parametrize(
    ("env", "expected_state", "expected_reason", "provider_present"),
    [
        ({}, AzureAgentState.DISABLED_NO_KEY, "", False),
        (
            {
                AZURE_ENV_VARS["api_key"]: "secret",
            },
            AzureAgentState.MISCONFIGURED,
            "missing_endpoint_and_deployment",
            False,
        ),
        (
            {
                AZURE_ENV_VARS["api_key"]: "secret",
                AZURE_ENV_VARS["model"]: "deployment",
            },
            AzureAgentState.MISCONFIGURED,
            "missing_endpoint",
            False,
        ),
        (
            {
                AZURE_ENV_VARS["api_key"]: "secret",
                AZURE_ENV_VARS["base_url"]: "https://example.openai.azure.com",
            },
            AzureAgentState.MISCONFIGURED,
            "missing_deployment",
            False,
        ),
        (
            {
                AZURE_ENV_VARS["type"]: "openai",
                AZURE_ENV_VARS["api_key"]: "secret",
                AZURE_ENV_VARS["base_url"]: "https://example.openai.azure.com",
                AZURE_ENV_VARS["model"]: "deployment",
            },
            AzureAgentState.MISCONFIGURED,
            "provider_type_not_azure",
            False,
        ),
        (
            {
                AZURE_ENV_VARS["type"]: " azure ",
                AZURE_ENV_VARS["api_key"]: " secret ",
                AZURE_ENV_VARS["base_url"]: (
                    " https://example.openai.azure.com/openai/deployments/gpt-5/"
                    "chat/completions?api-version=2025-01-01-preview "
                ),
                AZURE_ENV_VARS["model"]: " deployment ",
                AZURE_ENV_VARS["api_version"]: "2025-01-01",
            },
            AzureAgentState.AZURE_READY,
            "",
            True,
        ),
    ],
)
def test_resolve_azure_agent_runtime_states(
    monkeypatch: pytest.MonkeyPatch,
    env: dict[str, str],
    expected_state: AzureAgentState,
    expected_reason: str,
    provider_present: bool,
) -> None:
    for var in AZURE_ENV_VARS.values():
        monkeypatch.delenv(var, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    runtime = resolve_azure_agent_runtime()

    assert runtime.status.state is expected_state
    assert runtime.status.reason_code == expected_reason
    assert (runtime.sdk_provider_config() is not None) is provider_present
    if provider_present:
        provider = runtime.sdk_provider_config()
        assert provider == {
            "type": "azure",
            "base_url": "https://example.openai.azure.com",
            "api_key": "secret",
            "wire_api": "completions",
            "azure": {"api_version": "2025-01-01"},
        }
        assert runtime.status.deployment == "deployment"
        assert runtime.status.api_version == "2025-01-01"
    else:
        assert runtime.status.api_version == DEFAULT_API_VERSION


def test_reset_to_initial_restores_ready_state(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in AZURE_ENV_VARS.values():
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv(AZURE_ENV_VARS["type"], "azure")
    monkeypatch.setenv(AZURE_ENV_VARS["api_key"], "secret")
    monkeypatch.setenv(
        AZURE_ENV_VARS["base_url"],
        "https://example.openai.azure.com/openai/deployments/gpt-5/chat/completions",
    )
    monkeypatch.setenv(AZURE_ENV_VARS["model"], "deployment")

    runtime = resolve_azure_agent_runtime()
    runtime.mark_degraded("CopilotSDKUnavailableError")

    assert runtime.status.state is AzureAgentState.DEGRADED

    runtime.reset_to_initial()

    assert runtime.status.state is AzureAgentState.AZURE_READY
    assert runtime.status.reason_code == ""
    assert runtime.sdk_provider_config() == {
        "type": "azure",
        "base_url": "https://example.openai.azure.com",
        "api_key": "secret",
        "wire_api": "completions",
        "azure": {"api_version": DEFAULT_API_VERSION},
    }
