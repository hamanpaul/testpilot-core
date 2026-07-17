"""Azure OpenAI BYOK authentication helper.

Handles interactive credential prompting, environment variable export,
and connectivity verification for Azure OpenAI endpoints.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from enum import Enum
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

AZURE_ENV_VARS = {
    "type": "COPILOT_PROVIDER_TYPE",
    "base_url": "COPILOT_PROVIDER_BASE_URL",
    "api_key": "COPILOT_PROVIDER_API_KEY",
    "model": "COPILOT_MODEL",
    "api_version": "COPILOT_PROVIDER_AZURE_API_VERSION",
}

DEFAULT_API_VERSION = "2024-10-21"


class AzureAgentState(str, Enum):
    DISABLED_NO_KEY = "disabled_no_key"
    MISCONFIGURED = "misconfigured"
    AZURE_READY = "azure_ready"
    DEGRADED = "degraded"


@dataclass(frozen=True)
class AzureAgentStatus:
    state: AzureAgentState
    deployment: str = ""
    api_version: str = DEFAULT_API_VERSION
    reason_code: str = ""

    @property
    def ready(self) -> bool:
        return self.state is AzureAgentState.AZURE_READY


@dataclass
class AzureAgentRuntime:
    status: AzureAgentStatus
    _provider_config: dict[str, Any] | None = field(default=None, repr=False)
    _initial_state: AzureAgentState = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._initial_state = self.status.state

    def sdk_provider_config(self) -> dict[str, Any] | None:
        return dict(self._provider_config) if self._provider_config else None

    def public_summary(self) -> dict[str, str]:
        return {
            "initial_agent_state": self._initial_state.value,
            "final_agent_state": self.status.state.value,
            "deployment": self.status.deployment,
            "api_version": self.status.api_version,
            "reason_code": self.status.reason_code,
        }

    def mark_degraded(self, reason_code: str) -> None:
        self.status = AzureAgentStatus(
            state=AzureAgentState.DEGRADED,
            deployment=self.status.deployment,
            api_version=self.status.api_version,
            reason_code=str(reason_code),
        )

    def reset_to_initial(self) -> None:
        """Restore the environment-derived status for a new run."""
        self.status = AzureAgentStatus(
            state=self._initial_state,
            deployment=self.status.deployment,
            api_version=self.status.api_version,
            reason_code="" if self._initial_state is AzureAgentState.AZURE_READY else self.status.reason_code,
        )


def resolve_azure_agent_runtime() -> AzureAgentRuntime:
    key = os.environ.get(AZURE_ENV_VARS["api_key"], "").strip()
    endpoint = normalize_azure_base_url(os.environ.get(AZURE_ENV_VARS["base_url"], ""))
    deployment = os.environ.get(AZURE_ENV_VARS["model"], "").strip()
    api_version = os.environ.get(AZURE_ENV_VARS["api_version"], "").strip() or DEFAULT_API_VERSION
    if not key:
        return AzureAgentRuntime(AzureAgentStatus(AzureAgentState.DISABLED_NO_KEY))
    if not endpoint and not deployment:
        reason = "missing_endpoint_and_deployment"
    elif not endpoint:
        reason = "missing_endpoint"
    elif not deployment:
        reason = "missing_deployment"
    else:
        config = {
            "type": "azure", "base_url": endpoint, "api_key": key,
            "wire_api": "completions", "azure": {"api_version": api_version},
        }
        return AzureAgentRuntime(
            AzureAgentStatus(AzureAgentState.AZURE_READY, deployment, api_version),
            config,
        )
    return AzureAgentRuntime(AzureAgentStatus(AzureAgentState.MISCONFIGURED, reason_code=reason))


class AzureAuthError(RuntimeError):
    """Raised when Azure OpenAI authentication or connectivity fails."""


def normalize_azure_base_url(base_url: str) -> str:
    """Normalize Azure URLs to the resource root."""
    raw = str(base_url).strip().rstrip("/")
    if not raw:
        return ""

    parsed = urllib.parse.urlsplit(raw)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return raw


def resolve_provider_config() -> dict[str, Any] | None:
    """Build provider config dict from COPILOT_PROVIDER_* env vars.

    Returns None if no Azure provider env vars are set.
    """
    runtime = resolve_azure_agent_runtime()
    if runtime.status.state is AzureAgentState.AZURE_READY:
        return runtime.sdk_provider_config()
    # Legacy source-compatible helper: callers that only need transport
    # configuration may omit COPILOT_MODEL; runtime readiness remains strict.
    if os.environ.get(AZURE_ENV_VARS["type"], "").strip().lower() not in ("", "azure"):
        return None
    key = os.environ.get(AZURE_ENV_VARS["api_key"], "").strip()
    endpoint = normalize_azure_base_url(os.environ.get(AZURE_ENV_VARS["base_url"], ""))
    if not key or not endpoint:
        return None
    version = os.environ.get(AZURE_ENV_VARS["api_version"], "").strip() or DEFAULT_API_VERSION
    return {"type": "azure", "base_url": endpoint, "api_key": key,
            "wire_api": "completions", "azure": {"api_version": version}}


def prompt_azure_credentials() -> dict[str, str]:
    """Interactively prompt user for Azure OpenAI credentials.

    Returns dict with keys: base_url, api_key, model.
    """
    import click

    click.echo()
    click.secho("─── Azure OpenAI Configuration ───", fg="cyan", bold=True)
    click.echo()

    base_url = click.prompt(
        "  Azure Endpoint URL (e.g. https://your-resource.openai.azure.com)",
        type=str,
    ).strip().rstrip("/")

    api_key = click.prompt(
        "  Azure API Key",
        type=str,
        hide_input=True,
    ).strip()

    model = click.prompt(
        "  Deployment Name (model)",
        type=str,
        default="gpt-4o",
        show_default=True,
    ).strip()

    return {"base_url": base_url, "api_key": api_key, "model": model}


def export_azure_env(creds: dict[str, str]) -> None:
    """Export Azure credentials as COPILOT_PROVIDER_* environment variables."""
    os.environ[AZURE_ENV_VARS["type"]] = "azure"
    os.environ[AZURE_ENV_VARS["base_url"]] = normalize_azure_base_url(creds["base_url"])
    os.environ[AZURE_ENV_VARS["api_key"]] = creds["api_key"]
    os.environ[AZURE_ENV_VARS["model"]] = creds["model"]
    os.environ[AZURE_ENV_VARS["api_version"]] = DEFAULT_API_VERSION
    logger.info("Azure OpenAI env vars exported (COPILOT_PROVIDER_*)")


def verify_azure_connectivity(base_url: str) -> bool:
    """Verify that the Azure endpoint is reachable.

    Returns True if HTTP response is received (any status code).
    """
    normalized_base_url = normalize_azure_base_url(base_url)
    url = normalized_base_url + "/openai/models?api-version=" + DEFAULT_API_VERSION
    req = urllib.request.Request(url, method="GET")
    try:
        urllib.request.urlopen(req, timeout=10)
        return True
    except urllib.error.HTTPError:
        # 401/403/404 still means the endpoint is reachable
        return True
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        logger.warning("Azure endpoint unreachable: %s — %s", normalized_base_url, exc)
        return False


def setup_azure_auth() -> dict[str, Any] | None:
    """Full interactive Azure auth flow: prompt → export → verify → return provider config.

    Returns provider config dict on success, None on failure.
    """
    import click

    creds = prompt_azure_credentials()

    click.echo()
    click.echo("  Verifying connectivity... ", nl=False)

    if not verify_azure_connectivity(creds["base_url"]):
        click.secho("FAILED", fg="red", bold=True)
        click.secho(
            f"  Cannot reach {creds['base_url']}\n"
            "  Please check the endpoint URL and network connectivity.",
            fg="red",
        )
        return None

    click.secho("OK", fg="green", bold=True)
    click.echo()

    export_azure_env(creds)
    return resolve_provider_config()
