"""Case utility functions — pure helpers for case filtering, band mapping, and ID handling."""

from __future__ import annotations

import re
from typing import Any

_CASE_NUMBER_RE = re.compile(r"(?:^|-)D\d{3}(?=$|[-_])", re.IGNORECASE)


def safe_int(value: Any, default: int) -> int:
    """Convert *value* to int, falling back to *default*."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def safe_float(value: Any, default: float) -> float:
    """Convert *value* to float, falling back to *default*."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def sanitize_case_id(case_id: str) -> str:
    """Return a filesystem-safe variant of *case_id*."""
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "_", case_id.strip())
    return normalized or "case"


def normalize_step_command(value: Any) -> str | list[str]:
    """Normalize a step command while preserving `str | list[str]` semantics."""
    if isinstance(value, list):
        commands: list[str] = []
        for item in value:
            text = str(item).strip()
            if text:
                commands.append(text)
        return commands
    return str(value or "").strip()


def step_command_lines(value: Any) -> list[str]:
    """Return the step command as a list of executable command strings."""
    normalized = normalize_step_command(value)
    if isinstance(normalized, list):
        return normalized
    return [normalized] if normalized else []


def stringify_step_command(value: Any) -> str:
    """Return a display string for `str | list[str]` step commands."""
    normalized = normalize_step_command(value)
    if isinstance(normalized, list):
        return "\n".join(normalized).strip()
    return normalized


def case_aliases(case: dict[str, Any]) -> list[str]:
    """Extract the list of alias strings from *case*."""
    raw_aliases = case.get("aliases")
    if not isinstance(raw_aliases, list):
        return []
    aliases: list[str] = []
    for item in raw_aliases:
        alias = str(item).strip()
        if alias:
            aliases.append(alias)
    return aliases


def case_d_number(value: str) -> str:
    """Return the D### selector embedded in a case id, if any."""
    match = _CASE_NUMBER_RE.search(value.strip())
    if not match:
        return ""
    return match.group(0).lstrip("-").upper()


def case_matches_requested_ids(
    case: dict[str, Any],
    requested_ids: set[str],
) -> bool:
    """Return True if *case* id or any alias is in *requested_ids*."""
    if not requested_ids:
        return False
    case_ids = {str(case.get("id", "")).strip(), *case_aliases(case)}
    case_ids.discard("")
    if case_ids & requested_ids:
        return True

    requested_d_numbers = {
        token
        for requested in requested_ids
        if (token := case_d_number(str(requested)))
    }
    if not requested_d_numbers:
        return False
    return any(case_d_number(case_id) in requested_d_numbers for case_id in case_ids)


def band_results(status: str, bands: list[str] | None) -> tuple[str, str, str]:
    """Map a *status* string to per-band (5g, 6g, 2.4g) results."""
    if not bands:
        return status, status, status
    normalized = {b.strip().lower() for b in bands}
    r5 = status if "5g" in normalized else "N/A"
    r6 = status if "6g" in normalized else "N/A"
    r24 = status if "2.4g" in normalized else "N/A"
    return r5, r6, r24


def case_band_results(case: dict[str, Any], verdict: bool) -> tuple[str, str, str]:
    """Compute per-band results for *case* given an evaluation *verdict*."""
    status = "Pass" if verdict else "Fail"
    return band_results(status, case.get("bands"))


def overall_case_status(result_5g: str, result_6g: str, result_24g: str) -> str:
    """Return ``'Fail'`` if any band failed, otherwise ``'Pass'``."""
    return "Fail" if "Fail" in {result_5g, result_6g, result_24g} else "Pass"
