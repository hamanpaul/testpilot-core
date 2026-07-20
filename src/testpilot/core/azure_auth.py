"""Azure OpenAI BYOK runtime helpers."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
import urllib.parse
from typing import Any

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
    provider_type = os.environ.get(AZURE_ENV_VARS["type"], "").strip().lower()
    key = os.environ.get(AZURE_ENV_VARS["api_key"], "").strip()
    endpoint = normalize_azure_base_url(os.environ.get(AZURE_ENV_VARS["base_url"], ""))
    deployment = os.environ.get(AZURE_ENV_VARS["model"], "").strip()
    api_version = os.environ.get(AZURE_ENV_VARS["api_version"], "").strip() or DEFAULT_API_VERSION
    if not key:
        return AzureAgentRuntime(AzureAgentStatus(AzureAgentState.DISABLED_NO_KEY))
    if provider_type not in ("", "azure"):
        return AzureAgentRuntime(
            AzureAgentStatus(
                AzureAgentState.MISCONFIGURED,
                reason_code="provider_type_not_azure",
            )
        )
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
    """Return Azure SDK provider config only when the runtime is ready."""
    runtime = resolve_azure_agent_runtime()
    if runtime.status.state is AzureAgentState.AZURE_READY:
        return runtime.sdk_provider_config()
    return None
