"""Azure OpenAI BYOK authentication helper.

Handles interactive credential prompting, environment variable export,
and connectivity verification for Azure OpenAI endpoints.
"""

from __future__ import annotations

import logging
import os
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
    provider_type = os.environ.get(AZURE_ENV_VARS["type"], "").strip().lower()
    if provider_type != "azure":
        return None

    base_url = normalize_azure_base_url(os.environ.get(AZURE_ENV_VARS["base_url"], ""))
    api_key = os.environ.get(AZURE_ENV_VARS["api_key"], "").strip()
    if not base_url or not api_key:
        return None

    api_version = (
        os.environ.get(AZURE_ENV_VARS["api_version"], "").strip()
        or DEFAULT_API_VERSION
    )

    return {
        "type": "azure",
        "base_url": base_url,
        "api_key": api_key,
        "wire_api": "completions",
        "azure": {"api_version": api_version},
    }


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
