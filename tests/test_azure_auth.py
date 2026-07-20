"""Unit tests for testpilot.core.azure_auth module."""

from __future__ import annotations

import pytest

from testpilot.core.azure_auth import (
    AZURE_ENV_VARS,
    DEFAULT_API_VERSION,
    normalize_azure_base_url,
    resolve_provider_config,
)


class TestResolveProviderConfig:
    """Tests for resolve_provider_config()."""

    def test_returns_none_when_no_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for var in AZURE_ENV_VARS.values():
            monkeypatch.delenv(var, raising=False)
        assert resolve_provider_config() is None

    def test_returns_none_when_type_not_azure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(AZURE_ENV_VARS["type"], "openai")
        monkeypatch.setenv(AZURE_ENV_VARS["base_url"], "https://example.com")
        monkeypatch.setenv(AZURE_ENV_VARS["api_key"], "key123")
        assert resolve_provider_config() is None

    def test_returns_none_when_missing_base_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(AZURE_ENV_VARS["type"], "azure")
        monkeypatch.setenv(AZURE_ENV_VARS["api_key"], "key123")
        monkeypatch.delenv(AZURE_ENV_VARS["base_url"], raising=False)
        assert resolve_provider_config() is None

    def test_returns_none_when_missing_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(AZURE_ENV_VARS["type"], "azure")
        monkeypatch.setenv(AZURE_ENV_VARS["base_url"], "https://example.com")
        monkeypatch.delenv(AZURE_ENV_VARS["api_key"], raising=False)
        assert resolve_provider_config() is None

    def test_returns_none_when_missing_deployment(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(AZURE_ENV_VARS["type"], "azure")
        monkeypatch.setenv(AZURE_ENV_VARS["base_url"], "https://example.com")
        monkeypatch.setenv(AZURE_ENV_VARS["api_key"], "key123")
        monkeypatch.delenv(AZURE_ENV_VARS["model"], raising=False)
        assert resolve_provider_config() is None

    def test_returns_config_when_all_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(AZURE_ENV_VARS["type"], "azure")
        monkeypatch.setenv(AZURE_ENV_VARS["base_url"], "https://my-resource.openai.azure.com")
        monkeypatch.setenv(AZURE_ENV_VARS["api_key"], "secret-key")
        monkeypatch.setenv(AZURE_ENV_VARS["model"], "gpt-5")
        monkeypatch.delenv(AZURE_ENV_VARS["api_version"], raising=False)

        result = resolve_provider_config()
        assert result is not None
        assert result["type"] == "azure"
        assert result["base_url"] == "https://my-resource.openai.azure.com"
        assert result["api_key"] == "secret-key"
        assert result["wire_api"] == "completions"
        assert result["azure"]["api_version"] == DEFAULT_API_VERSION

    def test_uses_custom_api_version(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(AZURE_ENV_VARS["type"], "azure")
        monkeypatch.setenv(AZURE_ENV_VARS["base_url"], "https://example.com")
        monkeypatch.setenv(AZURE_ENV_VARS["api_key"], "key")
        monkeypatch.setenv(AZURE_ENV_VARS["model"], "gpt-5")
        monkeypatch.setenv(AZURE_ENV_VARS["api_version"], "2025-01-01")

        result = resolve_provider_config()
        assert result is not None
        assert result["azure"]["api_version"] == "2025-01-01"

    def test_normalizes_full_deployment_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(AZURE_ENV_VARS["type"], "azure")
        monkeypatch.setenv(
            AZURE_ENV_VARS["base_url"],
            "https://rs1200ai001.openai.azure.com/openai/deployments/gpt-5/chat/completions?api-version=2025-01-01-preview",
        )
        monkeypatch.setenv(AZURE_ENV_VARS["api_key"], "secret-key")
        monkeypatch.setenv(AZURE_ENV_VARS["model"], "gpt-5")

        result = resolve_provider_config()
        assert result is not None
        assert result["base_url"] == "https://rs1200ai001.openai.azure.com"


class TestNormalizeAzureBaseUrl:
    """Tests for normalize_azure_base_url()."""

    def test_keeps_resource_root_unchanged(self) -> None:
        assert (
            normalize_azure_base_url("https://my-resource.openai.azure.com")
            == "https://my-resource.openai.azure.com"
        )

    def test_extracts_resource_root_from_full_deployment_url(self) -> None:
        assert (
            normalize_azure_base_url(
                "https://rs1200ai001.openai.azure.com/openai/deployments/gpt-5/chat/completions?api-version=2025-01-01-preview"
            )
            == "https://rs1200ai001.openai.azure.com"
        )
