"""Private validation and projection for SDK API 1.5 plugin cleanup results."""

from __future__ import annotations

from collections.abc import Mapping
import math
import re
from typing import Any

_RESULT_FIELDS = frozenset({"status", "reason_code", "comment", "transport_result"})
_TRANSPORT_FIELDS = frozenset(
    {
        "error_code",
        "retry_after_s",
        "recommended_action",
        "cmd_id",
        "outcome",
        "ambiguous",
        "non_replayable",
        "retryable",
        "partial",
        "status",
        "input_integrity",
        "tx_bytes",
        "sent_chars",
        "acked_chars",
        "newline_sent",
        "session_recovered",
        "recovery_error",
    }
)
_REASON_CODE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_INVALID_RESULT = {
    "status": "unknown",
    "reason_code": "cleanup_result_invalid",
    "comment": "plugin teardown returned an invalid cleanup result",
    "transport_result": {},
}
_EXCEPTION_RESULT = {
    "status": "unknown",
    "reason_code": "cleanup_exception",
    "comment": "plugin teardown raised before cleanup could be verified",
    "transport_result": {},
}


def has_unknown_transport_outcome(*values: Any) -> bool:
    """Find an explicit uncertain receipt on a result or its known wrappers."""
    pending = list(values)
    seen: set[int] = set()
    while pending:
        value = pending.pop()
        if isinstance(value, BaseException):
            if id(value) in seen:
                continue
            seen.add(id(value))
            try:
                pending.extend(
                    item
                    for item in (
                        getattr(value, "result", None),
                        getattr(value, "transport_result", None),
                    )
                    if isinstance(item, Mapping)
                )
            except Exception:
                return True
            continue
        if not isinstance(value, Mapping):
            continue
        if id(value) in seen:
            continue
        seen.add(id(value))
        try:
            pending.extend(
                item
                for item in (
                    value.get("result"),
                    value.get("transport_result"),
                    value.get("metadata"),
                )
                if isinstance(item, Mapping)
            )
            if (
                str(value.get("outcome") or "").strip().lower()
                in {"unknown", "ambiguous"}
                or value.get("ambiguous") is True
                or value.get("non_replayable") is True
                or value.get("partial") is True
                or str(value.get("input_integrity") or "").strip().lower()
                == "uncertain"
                or str(value.get("error_code") or "").strip().upper()
                == "COMMAND_OUTCOME_UNKNOWN"
            ):
                return True
        except Exception:
            # An unreadable receipt cannot justify follow-up cleanup I/O.
            return True
    return False


def project_transport_evidence(*values: Any) -> dict[str, Any]:
    """Keep only bounded transport fields from result and failure wrappers."""
    pending = list(values)
    seen: set[int] = set()
    projected_evidence: dict[str, Any] = {}
    while pending:
        value = pending.pop(0)
        if isinstance(value, BaseException):
            if id(value) in seen:
                continue
            seen.add(id(value))
            try:
                pending.extend(
                    item
                    for item in (
                        getattr(value, "result", None),
                        getattr(value, "transport_result", None),
                    )
                    if isinstance(item, Mapping)
                )
            except Exception:
                return {}
            continue
        if not isinstance(value, Mapping) or id(value) in seen:
            continue
        seen.add(id(value))
        try:
            projected = _project_transport_result(value)
            if projected is None:
                return {}
            for key, item in projected.items():
                projected_evidence.setdefault(key, item)
            pending.extend(
                item
                for item in (
                    value.get("result"),
                    value.get("transport_result"),
                    value.get("metadata"),
                )
                if isinstance(item, Mapping)
            )
        except Exception:
            return {}
    return projected_evidence


def _safe_text(value: Any, *, max_length: int) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and len(value) <= max_length
        and all(ord(char) >= 0x20 and ord(char) != 0x7F for char in value)
    )


def _project_transport_result(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    projected: dict[str, Any] = {}
    for key, item in value.items():
        if key not in _TRANSPORT_FIELDS:
            continue
        if item is None or isinstance(item, bool):
            projected[key] = item
        elif isinstance(item, int):
            projected[key] = item
        elif isinstance(item, float) and math.isfinite(item):
            projected[key] = item
        elif _safe_text(item, max_length=512):
            projected[key] = item
        else:
            return None
    return projected


def _project_wrapped_transport_result(value: Mapping[str, Any]) -> dict[str, Any] | None:
    """Flatten known receipt wrappers while retaining only allowlisted fields."""
    pending: list[Mapping[str, Any]] = [value]
    seen: set[int] = set()
    projected_evidence: dict[str, Any] = {}
    while pending:
        source = pending.pop(0)
        if id(source) in seen:
            continue
        seen.add(id(source))
        projected = _project_transport_result(source)
        if projected is None:
            return None
        for key, item in projected.items():
            projected_evidence.setdefault(key, item)
        try:
            pending.extend(
                item
                for item in (
                    source.get("result"),
                    source.get("transport_result"),
                    source.get("metadata"),
                )
                if isinstance(item, Mapping)
            )
        except Exception:
            return None
    return projected_evidence


def normalize_cleanup_result(value: Any) -> dict[str, Any] | None:
    """Return a safe terminal cleanup result, or ``None`` for legacy success.

    The mapping intentionally accepts only failure states. Core synthesizes the
    attempt identity, environment category, verdict, and abort decision.
    """
    if value is None:
        return None
    if not isinstance(value, Mapping):
        return dict(_INVALID_RESULT)
    try:
        keys = set(value.keys())
        status = value.get("status")
        reason_code = value.get("reason_code")
        comment = value.get("comment")
        raw_transport_result = value.get("transport_result", {})
    except Exception:
        return dict(_INVALID_RESULT)

    if (
        not keys.issubset(_RESULT_FIELDS)
        or not {"status", "reason_code", "comment"}.issubset(keys)
        or not isinstance(status, str)
        or status not in {"failed", "unknown"}
        or not isinstance(reason_code, str)
        or _REASON_CODE_RE.fullmatch(reason_code) is None
        or not _safe_text(comment, max_length=512)
    ):
        return dict(_INVALID_RESULT)

    if not isinstance(raw_transport_result, Mapping):
        return dict(_INVALID_RESULT)
    # Inspect wrapper metadata before the projection discards those keys, then
    # retain only the known scalar receipt fields from recognized wrappers.
    unknown_transport_outcome = has_unknown_transport_outcome(raw_transport_result)
    try:
        transport_result = _project_wrapped_transport_result(raw_transport_result)
    except Exception:
        return dict(_INVALID_RESULT)
    if transport_result is None:
        return dict(_INVALID_RESULT)
    return {
        "status": "unknown" if status == "unknown" or unknown_transport_outcome else status,
        "reason_code": (
            "cleanup_outcome_unknown"
            if unknown_transport_outcome and status == "failed"
            else reason_code
        ),
        "comment": comment.strip(),
        "transport_result": transport_result,
    }


def cleanup_exception_result() -> dict[str, Any]:
    """Produce a message-free fail-closed result for a teardown exception."""
    return dict(_EXCEPTION_RESULT)


def cleanup_failure_snapshot(
    cleanup_result: Mapping[str, Any],
    *,
    case_id: Any,
    attempt_index: int,
) -> dict[str, Any]:
    """Stamp a validated cleanup failure with identity owned by Core."""
    return {
        "case_id": str(case_id),
        "attempt_index": attempt_index,
        "category": "environment",
        "reason_code": str(cleanup_result["reason_code"]),
        "comment": str(cleanup_result["comment"]),
        "cleanup_status": str(cleanup_result["status"]),
        "transport_result": dict(cleanup_result["transport_result"]),
    }
