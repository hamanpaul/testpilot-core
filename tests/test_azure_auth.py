"""Unit tests for testpilot.core.azure_auth module."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from testpilot.core.azure_auth import (
    AZURE_ENV_VARS,
    DEFAULT_API_VERSION,
    AzureAuthError,
    export_azure_env,
    normalize_azure_base_url,
    resolve_provider_config,
    verify_azure_connectivity,
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

    def test_returns_config_when_all_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(AZURE_ENV_VARS["type"], "azure")
        monkeypatch.setenv(AZURE_ENV_VARS["base_url"], "https://my-resource.openai.azure.com")
        monkeypatch.setenv(AZURE_ENV_VARS["api_key"], "secret-key")
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


class TestExportAzureEnv:
    """Tests for export_azure_env()."""

    def test_sets_all_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for var in AZURE_ENV_VARS.values():
            monkeypatch.delenv(var, raising=False)

        creds = {
            "base_url": "https://test.openai.azure.com",
            "api_key": "test-key",
            "model": "gpt-4o",
        }
        export_azure_env(creds)

        assert os.environ[AZURE_ENV_VARS["type"]] == "azure"
        assert os.environ[AZURE_ENV_VARS["base_url"]] == "https://test.openai.azure.com"
        assert os.environ[AZURE_ENV_VARS["api_key"]] == "test-key"
        assert os.environ[AZURE_ENV_VARS["model"]] == "gpt-4o"
        assert os.environ[AZURE_ENV_VARS["api_version"]] == DEFAULT_API_VERSION

    def test_normalizes_full_deployment_url_before_export(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for var in AZURE_ENV_VARS.values():
            monkeypatch.delenv(var, raising=False)

        creds = {
            "base_url": "https://rs1200ai001.openai.azure.com/openai/deployments/gpt-5/chat/completions?api-version=2025-01-01-preview",
            "api_key": "test-key",
            "model": "gpt-5",
        }
        export_azure_env(creds)

        assert os.environ[AZURE_ENV_VARS["base_url"]] == "https://rs1200ai001.openai.azure.com"


class TestVerifyAzureConnectivity:
    """Tests for verify_azure_connectivity()."""

    @patch("testpilot.core.azure_auth.urllib.request.urlopen")
    def test_returns_true_on_success(self, mock_urlopen: MagicMock) -> None:
        mock_urlopen.return_value = MagicMock()
        assert verify_azure_connectivity("https://example.com") is True

    @patch("testpilot.core.azure_auth.urllib.request.urlopen")
    def test_returns_true_on_http_error(self, mock_urlopen: MagicMock) -> None:
        import urllib.error

        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="", code=401, msg="Unauthorized", hdrs=None, fp=None  # type: ignore[arg-type]
        )
        assert verify_azure_connectivity("https://example.com") is True

    @patch("testpilot.core.azure_auth.urllib.request.urlopen")
    def test_returns_false_on_url_error(self, mock_urlopen: MagicMock) -> None:
        import urllib.error

        mock_urlopen.side_effect = urllib.error.URLError("Network unreachable")
        assert verify_azure_connectivity("https://example.com") is False

    @patch("testpilot.core.azure_auth.urllib.request.urlopen")
    def test_returns_false_on_timeout(self, mock_urlopen: MagicMock) -> None:
        mock_urlopen.side_effect = TimeoutError("timed out")
        assert verify_azure_connectivity("https://example.com") is False

    def test_strips_trailing_slash(self) -> None:
        with patch("testpilot.core.azure_auth.urllib.request.urlopen") as mock:
            mock.return_value = MagicMock()
            verify_azure_connectivity("https://example.com/")
            call_args = mock.call_args
            req = call_args[0][0]
            assert "//openai" not in req.full_url

    def test_normalizes_full_deployment_url_before_probe(self) -> None:
        with patch("testpilot.core.azure_auth.urllib.request.urlopen") as mock:
            mock.return_value = MagicMock()
            verify_azure_connectivity(
                "https://rs1200ai001.openai.azure.com/openai/deployments/gpt-5/chat/completions?api-version=2025-01-01-preview"
            )
            req = mock.call_args[0][0]
            assert req.full_url == (
                "https://rs1200ai001.openai.azure.com/openai/models"
                f"?api-version={DEFAULT_API_VERSION}"
            )
