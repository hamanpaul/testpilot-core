"""Typed, bounded contracts for a strict run-start gate."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import inspect
import re
from typing import Any


_SAFE_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_REASON_CODE_RE = re.compile(r"[a-z][a-z0-9_.-]{0,63}\Z")
_MAX_GATE_EVIDENCE = 16


class RunCapability(str, Enum):
    """Host capabilities a plugin may require before preparing a run."""

    STRICT_CAPTURE_BINDING = "strict_capture_binding"


class RunCapabilityAdmissionOutcome(str, Enum):
    """Finite result of checking a plugin's host-required capabilities."""

    LEGACY = "legacy"
    ADMITTED = "admitted"
    REJECTED = "rejected"


_CAPABILITY_REJECTION_REASONS = frozenset(
    {
        "required_capabilities_invalid",
        "required_capability_unsupported",
        "required_capability_api_invalid",
        "required_capability_api_incompatible",
        "post_capture_gate_missing",
        "capture_capability_unavailable",
    }
)


@dataclass(frozen=True, slots=True)
class RunCapabilityAdmissionResult:
    """Finite, side-effect-free admission result shared by Core entry points."""

    outcome: RunCapabilityAdmissionOutcome
    reason_code: str | None = None

    def __post_init__(self) -> None:
        if type(self.outcome) is not RunCapabilityAdmissionOutcome:
            raise ValueError("capability admission outcome is invalid")
        if self.outcome is RunCapabilityAdmissionOutcome.REJECTED:
            if type(self.reason_code) is not str or self.reason_code not in _CAPABILITY_REJECTION_REASONS:
                raise ValueError("capability admission reason is invalid")
        elif self.reason_code is not None:
            raise ValueError("only rejected capability admission has a reason")


def admit_run_capabilities(
    plugin: Any,
    run_backend: Any,
    *,
    default_gate_hook: Any,
) -> RunCapabilityAdmissionResult:
    """Check declared capabilities without invoking plugin or backend hooks."""
    plugin_type = type(plugin)
    raw_capabilities = inspect.getattr_static(
        plugin_type,
        "required_run_capabilities",
        frozenset(),
    )
    if type(raw_capabilities) is not frozenset:
        return RunCapabilityAdmissionResult(
            RunCapabilityAdmissionOutcome.REJECTED,
            "required_capabilities_invalid",
        )
    if not raw_capabilities:
        return RunCapabilityAdmissionResult(RunCapabilityAdmissionOutcome.LEGACY)
    if any(type(capability) is not RunCapability for capability in raw_capabilities):
        return RunCapabilityAdmissionResult(
            RunCapabilityAdmissionOutcome.REJECTED,
            "required_capabilities_invalid",
        )
    if (
        len(raw_capabilities) != 1
        or next(iter(raw_capabilities)) is not RunCapability.STRICT_CAPTURE_BINDING
    ):
        return RunCapabilityAdmissionResult(
            RunCapabilityAdmissionOutcome.REJECTED,
            "required_capability_unsupported",
        )

    declared_api = inspect.getattr_static(plugin_type, "api_version", None)
    if type(declared_api) is not str or re.fullmatch(r"\d+\.\d+", declared_api) is None:
        return RunCapabilityAdmissionResult(
            RunCapabilityAdmissionOutcome.REJECTED,
            "required_capability_api_invalid",
        )
    api_major, api_minor = (int(part) for part in declared_api.split("."))
    if api_major != 1 or api_minor < 6:
        return RunCapabilityAdmissionResult(
            RunCapabilityAdmissionOutcome.REJECTED,
            "required_capability_api_incompatible",
        )

    hook = inspect.getattr_static(plugin_type, "prepare_run_after_capture", None)
    if not callable(hook) or hook is default_gate_hook:
        return RunCapabilityAdmissionResult(
            RunCapabilityAdmissionOutcome.REJECTED,
            "post_capture_gate_missing",
        )
    provider = inspect.getattr_static(
        type(run_backend),
        "get_strict_capture_context",
        None,
    )
    if not callable(provider):
        return RunCapabilityAdmissionResult(
            RunCapabilityAdmissionOutcome.REJECTED,
            "capture_capability_unavailable",
        )
    return RunCapabilityAdmissionResult(RunCapabilityAdmissionOutcome.ADMITTED)


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
