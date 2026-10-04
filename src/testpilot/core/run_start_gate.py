"""Typed, bounded contracts for a strict run-start gate."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re


_SAFE_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_REASON_CODE_RE = re.compile(r"[a-z][a-z0-9_.-]{0,63}\Z")
_MAX_GATE_EVIDENCE = 16


class RunCapability(str, Enum):
    """Host capabilities a plugin may require before preparing a run."""

    STRICT_CAPTURE_BINDING = "strict_capture_binding"


class PrepareRunGateOutcome(str, Enum):
    """Finite outcomes for ``prepare_run_after_capture``."""

    ACCEPTED = "accepted"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class PrepareRunGateEvidence:
    """A sanitized check label and finite outcome; never carries raw values."""

    check: str
    outcome: PrepareRunGateOutcome
    reason_code: str

    def __post_init__(self) -> None:
        if type(self.check) is not str or not _SAFE_TOKEN_RE.fullmatch(self.check):
            raise ValueError("gate evidence check must be a safe token")
        if type(self.outcome) is not PrepareRunGateOutcome:
            raise ValueError("gate evidence outcome is invalid")
        if type(self.reason_code) is not str or not _REASON_CODE_RE.fullmatch(self.reason_code):
            raise ValueError("gate evidence reason_code must be sanitized")


@dataclass(frozen=True, slots=True)
class PrepareRunAfterCaptureContext:
    """Capture proof passed to a plugin after the strict run-start marker.

    ``capture_binding_id`` is an opaque host-generated token. It must be
    derived from the active capture handle, never copied from operator config.
    The context deliberately excludes endpoints, credentials, and device IDs.
    """

    run_id: str
    start_sequence: int
    capture_binding_id: str

    def __post_init__(self) -> None:
        if type(self.run_id) is not str or not _SAFE_TOKEN_RE.fullmatch(self.run_id):
            raise ValueError("run_id must be a safe token")
        if not is_valid_sequence_marker(self.start_sequence):
            raise ValueError("start_sequence must be a non-negative integer")
        if (
            type(self.capture_binding_id) is not str
            or not _SAFE_TOKEN_RE.fullmatch(self.capture_binding_id)
        ):
            raise ValueError("capture_binding_id must be a safe token")


@dataclass(frozen=True, slots=True)
class PrepareRunGateResult:
    """Frozen plugin gate result with bounded, sanitized evidence."""

    outcome: PrepareRunGateOutcome
    reason_code: str
    evidence: tuple[PrepareRunGateEvidence, ...] = ()

    def __post_init__(self) -> None:
        if type(self.outcome) is not PrepareRunGateOutcome:
            raise ValueError("gate outcome is invalid")
        if type(self.reason_code) is not str or not _REASON_CODE_RE.fullmatch(self.reason_code):
            raise ValueError("gate reason_code must be sanitized")
        if type(self.evidence) is not tuple or len(self.evidence) > _MAX_GATE_EVIDENCE:
            raise ValueError("gate evidence must be a bounded tuple")
        if any(type(item) is not PrepareRunGateEvidence for item in self.evidence):
            raise ValueError("gate evidence item is invalid")

    def to_payload(self) -> dict[str, object]:
        """Return the finite public projection suitable for run artifacts."""
        return {
            "outcome": self.outcome.value,
            "reason_code": self.reason_code,
            "evidence": [
                {
                    "check": item.check,
                    "outcome": item.outcome.value,
                    "reason_code": item.reason_code,
                }
                for item in self.evidence
            ],
        }


def is_valid_sequence_marker(value: object) -> bool:
    """Accept zero and positive integer sequence markers, but not bools."""
    return type(value) is int and value >= 0


def is_valid_capture_context(
    value: object,
    *,
    run_id: str,
    start_sequence: int,
) -> bool:
    """Validate a context returned by the active RunBackend handle."""
    if type(value) is not PrepareRunAfterCaptureContext:
        return False
    try:
        return (
            type(value.run_id) is str
            and bool(_SAFE_TOKEN_RE.fullmatch(value.run_id))
            and value.run_id == run_id
            and is_valid_sequence_marker(value.start_sequence)
            and value.start_sequence == start_sequence
            and type(value.capture_binding_id) is str
            and bool(_SAFE_TOKEN_RE.fullmatch(value.capture_binding_id))
        )
    except Exception:
        return False


def is_valid_gate_result(value: object) -> bool:
    """Validate results again at the host boundary, including forged objects."""
    if type(value) is not PrepareRunGateResult:
        return False
    try:
        if type(value.outcome) is not PrepareRunGateOutcome:
            return False
        if (
            type(value.reason_code) is not str
            or not _REASON_CODE_RE.fullmatch(value.reason_code)
        ):
            return False
        if type(value.evidence) is not tuple or len(value.evidence) > _MAX_GATE_EVIDENCE:
            return False
        evidence_is_valid = all(
            type(item) is PrepareRunGateEvidence
            and type(item.check) is str
            and bool(_SAFE_TOKEN_RE.fullmatch(item.check))
            and type(item.outcome) is PrepareRunGateOutcome
            and type(item.reason_code) is str
            and bool(_REASON_CODE_RE.fullmatch(item.reason_code))
            for item in value.evidence
        )
        if not evidence_is_valid:
            return False
        return value.outcome is not PrepareRunGateOutcome.ACCEPTED or all(
            item.outcome is PrepareRunGateOutcome.ACCEPTED for item in value.evidence
        )
    except Exception:
        return False
