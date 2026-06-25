"""Helpers for resolving the serialwrap CLI binary."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

SERIALWRAP_BIN_ENV = "SERIALWRAP_BIN"


def _normalize_candidate(value: str | None) -> str | None:
    raw = str(value).strip() if value is not None else ""
    if not raw:
        return None
    return os.path.expandvars(os.path.expanduser(raw))


def _resolve_candidate(value: str | None) -> str | None:
    candidate = _normalize_candidate(value)
    if not candidate:
        return None

    if os.path.sep in candidate or candidate.startswith("."):
        path = Path(candidate)
        if path.is_file():
            return str(path)
        return None

    return shutil.which(candidate)


def resolve_serialwrap_binary(
    configured_bin: str | None = None,
    *,
    config_label: str,
) -> str:
    """Resolve serialwrap binary using env, config, then PATH fallback."""
    env_bin = os.environ.get(SERIALWRAP_BIN_ENV)

    for candidate in (env_bin, configured_bin, "serialwrap"):
        resolved = _resolve_candidate(candidate)
        if resolved:
            return resolved

    details: list[str] = ["serialwrap binary not found."]
    if env_bin:
        details.append(
            f"{SERIALWRAP_BIN_ENV}={_normalize_candidate(env_bin)!r} does not exist."
        )
    if configured_bin:
        details.append(f"{config_label}={_normalize_candidate(configured_bin)!r} does not exist.")
    details.append(
        f"Set {SERIALWRAP_BIN_ENV}, configure {config_label}, or install 'serialwrap' on PATH."
    )
    raise FileNotFoundError(" ".join(details))
