"""Private validation and projection for SDK API 1.5 plugin cleanup results."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from inspect import getattr_static
import itertools
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
_TRANSPORT_WRAPPER_FIELDS = ("result", "transport_result", "metadata")
_TRANSPORT_FIELD_ORDER = tuple(sorted(_TRANSPORT_FIELDS))
_MAX_TRANSPORT_RECEIPT_NODES = 64
_MAX_CLEANUP_RESULT_KEYS = 16
_MISSING = object()
_UNREADABLE_RECEIPT = {
    "outcome": "unknown",
    "non_replayable": True,
    "error_code": "COMMAND_OUTCOME_UNKNOWN",
}
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


def _receipt_text(value: Any) -> str:
    return value.strip().lower() if type(value) is str else ""


def _receipt_source_is_uncertain(source: Mapping[str, Any]) -> bool:
    outcome = _receipt_text(source.get("outcome"))
    status = _receipt_text(source.get("status"))
    return (
        outcome in {"unknown", "ambiguous", "accepted"}
        or status == "accepted"
        or source.get("ambiguous") is True
        or source.get("non_replayable") is True
        or source.get("partial") is True
        or _receipt_text(source.get("input_integrity")) == "uncertain"
        or _receipt_text(source.get("error_code")).upper()
        == "COMMAND_OUTCOME_UNKNOWN"
    )


def _capture_transport_sources(*values: Any) -> tuple[list[dict[str, Any]], bool]:
    """Read a bounded snapshot of receipt mappings and their named wrappers."""
    pending: deque[Any] = deque(values)
    sources: list[dict[str, Any]] = []
    keepalive: list[Any] = []
    seen: set[int] = set()
    unreadable = False

    while pending:
        value = pending.popleft()
        if isinstance(value, BaseException):
            if id(value) in seen:
                continue
            seen.add(id(value))
            keepalive.append(value)
            for name in ("result", "transport_result"):
                try:
                    static_value = getattr_static(value, name, _MISSING)
                except Exception:
                    static_value = _MISSING
                    unreadable = True
                try:
                    child = getattr(value, name, _MISSING)
                except Exception:
                    unreadable = True
                    continue
                if child is _MISSING:
                    if static_value is not _MISSING:
                        unreadable = True
                    continue
                if isinstance(child, Mapping):
                    pending.append(child)
            continue

        if not isinstance(value, Mapping) or id(value) in seen:
            continue
        if len(sources) >= _MAX_TRANSPORT_RECEIPT_NODES:
            unreadable = True
            break

        seen.add(id(value))
        keepalive.append(value)
        source: dict[str, Any] = {}
        for name in (*_TRANSPORT_WRAPPER_FIELDS, *_TRANSPORT_FIELD_ORDER):
            try:
                child = Mapping.get(value, name, _MISSING)
            except Exception:
                unreadable = True
                continue
            if child is _MISSING:
                continue
            source[name] = child
            if name in _TRANSPORT_WRAPPER_FIELDS and isinstance(child, Mapping):
                pending.append(child)
        sources.append(source)

    # Keep visited objects alive until their identities have been fully checked.
    del keepalive
    return sources, unreadable


def _project_transport_sources(
    sources: list[dict[str, Any]],
) -> tuple[dict[str, Any], bool]:
    evidence: dict[str, Any] = {}
    projected_sources: list[dict[str, Any]] = []
    invalid_field = False

    for source in sources:
        projected: dict[str, Any] = {}
        for key in _TRANSPORT_FIELD_ORDER:
            if key not in source:
                continue
            item = source[key]
            if item is None or type(item) in {bool, int}:
                projected[key] = item
            elif type(item) is float and math.isfinite(item):
                projected[key] = item
            elif type(item) is str and _safe_text(item, max_length=512):
                projected[key] = item
            else:
                invalid_field = True
        projected_sources.append(projected)
        for key, item in projected.items():
            evidence.setdefault(key, item)

    uncertain_sources = [
        source for source in projected_sources if _receipt_source_is_uncertain(source)
    ]
    for source in uncertain_sources:
        cmd_id = source.get("cmd_id")
        if type(cmd_id) is str and cmd_id:
            evidence["cmd_id"] = cmd_id
            break

    for key in ("ambiguous", "non_replayable", "partial"):
        if any(source.get(key) is True for source in projected_sources):
            evidence[key] = True

    outcomes = [_receipt_text(source.get("outcome")) for source in projected_sources]
    if "unknown" in outcomes:
        evidence["outcome"] = "unknown"
    elif "ambiguous" in outcomes:
        evidence["outcome"] = "ambiguous"
    elif "accepted" in outcomes:
        evidence["outcome"] = "accepted"

    if any(_receipt_text(source.get("status")) == "accepted" for source in projected_sources):
        evidence["status"] = "accepted"

    error_codes = [_receipt_text(source.get("error_code")).upper() for source in projected_sources]
    if "COMMAND_OUTCOME_UNKNOWN" in error_codes:
        evidence["error_code"] = "COMMAND_OUTCOME_UNKNOWN"

    integrity_values = [
        _receipt_text(source.get("input_integrity")) for source in projected_sources
    ]
    if "uncertain" in integrity_values:
        evidence["input_integrity"] = "uncertain"

    if any(source.get("retryable") is False for source in projected_sources):
        evidence["retryable"] = False

    return evidence, invalid_field


def _fail_closed_receipt(evidence: dict[str, Any]) -> dict[str, Any]:
    evidence = dict(evidence)
    evidence.update(_UNREADABLE_RECEIPT)
    return evidence


def _is_unknown_evidence(evidence: Mapping[str, Any]) -> bool:
    return _receipt_source_is_uncertain(evidence)


def has_unknown_transport_outcome(*values: Any) -> bool:
    """Find uncertain evidence; unreadable or excessive receipt graphs fail closed."""
    sources, unreadable = _capture_transport_sources(*values)
    evidence, invalid_field = _project_transport_sources(sources)
    return unreadable or invalid_field or _is_unknown_evidence(evidence)


def project_transport_evidence(*values: Any) -> dict[str, Any]:
    """Return sanitized receipt fields from a bounded wrapper traversal."""
    sources, unreadable = _capture_transport_sources(*values)
    evidence, invalid_field = _project_transport_sources(sources)
    if unreadable or invalid_field:
        return _fail_closed_receipt(evidence)
    return evidence


def _safe_text(value: Any, *, max_length: int) -> bool:
    return (
        type(value) is str
        and bool(value.strip())
        and len(value) <= max_length
        and all(ord(char) >= 0x20 and ord(char) != 0x7F for char in value)
    )


def _project_wrapped_transport_result(value: Mapping[str, Any]) -> dict[str, Any] | None:
    """Flatten known receipt wrappers while retaining only allowlisted fields."""
    sources, unreadable = _capture_transport_sources(value)
    evidence, invalid_field = _project_transport_sources(sources)
    if unreadable:
        return _fail_closed_receipt(evidence)
    if invalid_field:
        return None
    return evidence


def _bounded_cleanup_result_keys(value: Mapping[str, Any]) -> set[str] | None:
    try:
        keys = list(
            itertools.islice(iter(Mapping.keys(value)), _MAX_CLEANUP_RESULT_KEYS + 1)
        )
    except Exception:
        return None
    if len(keys) > _MAX_CLEANUP_RESULT_KEYS or any(type(key) is not str for key in keys):
        return None
    return set(keys)


def normalize_cleanup_result(value: Any) -> dict[str, Any] | None:
    """Return a safe terminal cleanup result, or ``None`` for legacy success.

    The mapping intentionally accepts only failure states. Core synthesizes the
    attempt identity, environment category, verdict, and abort decision.
    """
    if value is None:
        return None
    if not isinstance(value, Mapping):
        return dict(_INVALID_RESULT)
    keys = _bounded_cleanup_result_keys(value)
    if keys is None:
        return dict(_INVALID_RESULT)
    try:
        status = Mapping.get(value, "status")
        reason_code = Mapping.get(value, "reason_code")
        comment = Mapping.get(value, "comment")
        raw_transport_result = Mapping.get(value, "transport_result", {})
    except Exception:
        return dict(_INVALID_RESULT)

    if (
        not keys.issubset(_RESULT_FIELDS)
        or not {"status", "reason_code", "comment"}.issubset(keys)
        or type(status) is not str
        or status not in {"failed", "unknown"}
        or type(reason_code) is not str
        or _REASON_CODE_RE.fullmatch(reason_code) is None
        or not _safe_text(comment, max_length=512)
    ):
        return dict(_INVALID_RESULT)

    if not isinstance(raw_transport_result, Mapping):
        return dict(_INVALID_RESULT)
    # Flatten recognized wrappers into allowlisted scalar evidence before dropping
    # the raw wrapper objects.
    try:
        transport_result = _project_wrapped_transport_result(raw_transport_result)
    except Exception:
        return dict(_INVALID_RESULT)
    if transport_result is None:
        return dict(_INVALID_RESULT)
    unknown_transport_outcome = has_unknown_transport_outcome(transport_result)
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
