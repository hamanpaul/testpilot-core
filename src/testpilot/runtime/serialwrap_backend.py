"""SerialwrapBackend — RunBackend implementation backed by the serialwrap daemon.

All serialwrap-specific logic is encapsulated here.  Core and reporting modules
must not import serialwrap or log_capture directly after Task 4 rewiring.

Behavior → serialwrap-command mapping
--------------------------------------
This table is the single authoritative source for "what backend command is
issued for each high-level behavior". It anchors the behavior→command naming
contract inside the provider, but is intentionally not consumed by the current
per-case trace payload because this change must keep trace/golden output
bit-for-bit unchanged.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path
from threading import RLock
from typing import Any

from testpilot.core.role_plan import (
    CaptureRolePlanRequest,
    EffectiveRolePlan,
    RolePlanError,
    project_capture_role_plan,
)
from testpilot.core.run_start_gate import (
    StrictCaptureProviderAdmission,
    StrictCaptureProviderOutcome,
)
from testpilot.core.run_start_gate import PrepareRunAfterCaptureContext
from testpilot.core.testbed_config import TestbedConfig
from testpilot.runtime import _serialwrap_log
from testpilot.runtime.serialwrap_capture_binding import SerialwrapCaptureBindingClient
from testpilot.runtime.run_backend import (
    ExportRequest,
    ExportResult,
    RunBackend,
    RunHandle,
)
from testpilot.runtime.strict_capture import (
    MAX_CAPTURE_PAGES,
    MAX_CAPTURE_RECORD_BYTES,
    MAX_CAPTURE_TOTAL_BYTES,
    MAX_CAPTURE_TOTAL_RECORDS,
    StrictCaptureError,
    StrictCaptureHarvest,
    StrictCaptureHarvestStatus,
    StrictCapturePosition,
    role_plan_payload,
    validate_capture_row,
)
from testpilot.runtime.serialwrap_log_binding import (
    SerialwrapLogBinding,
    resolve_serialwrap_log_binding,
)

log = logging.getLogger(__name__)

_CAPTURE_EVIDENCE_STRENGTH = "posix_fd_devnode_match_v1"
_DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")
_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{1,256}\Z")
_UUID4_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)


@dataclass(slots=True, repr=False)
class _StrictPreflight:
    run_id: str = field(repr=False)
    config: TestbedConfig = field(repr=False)
    request: CaptureRolePlanRequest = field(repr=False)
    plan: EffectiveRolePlan = field(repr=False)
    binding: SerialwrapLogBinding = field(repr=False)
    client: SerialwrapCaptureBindingClient = field(repr=False)
    owner: object = field(repr=False)
    limits: dict[str, int] = field(repr=False)


@dataclass(slots=True, repr=False)
class _StrictCaptureRecord:
    run_id: str = field(repr=False)
    handle: RunHandle = field(repr=False)
    config: TestbedConfig = field(repr=False)
    request: CaptureRolePlanRequest = field(repr=False)
    plan: EffectiveRolePlan = field(repr=False)
    binding: SerialwrapLogBinding = field(repr=False)
    client: SerialwrapCaptureBindingClient = field(repr=False)
    owner: object = field(repr=False)
    limits: dict[str, int] = field(repr=False)
    capture_id: str = field(repr=False)
    provider_handle: str = field(repr=False)
    wal_epoch_token: str = field(repr=False)
    start_watermark: str = field(repr=False)
    start_sequence: int
    binding_tokens: dict[str, str] = field(repr=False)
    last_position: StrictCapturePosition = field(repr=False)
    mark_attempted: bool = False
    marked: bool = False
    mark_response: dict[str, Any] | None = field(default=None, repr=False)
    finish_attempted: bool = False
    finished: bool = False
    operation_uncertain: bool = False
    provider_io_stopped: bool = False
    pending_operation_id: str | None = field(default=None, repr=False)
    observed_row_epoch: str | None = field(default=None, repr=False)


def _valid_uuid4(value: object) -> bool:
    if type(value) is not str or not _UUID4_RE.fullmatch(value):
        return False
    try:
        return str(uuid.UUID(value)) == value
    except (ValueError, AttributeError):
        return False


def _bounded_int(value: object, *, minimum: int = 0, maximum: int = (1 << 63) - 1) -> bool:
    return type(value) is int and minimum <= value <= maximum


def _safe_token(value: object) -> bool:
    return type(value) is str and bool(_TOKEN_RE.fullmatch(value))


def _valid_capability_response(response: object, role_count: int) -> bool:
    if type(response) is not dict or response.get("ok") is not True:
        return False
    features = response.get("features")
    if type(features) is not dict:
        return False
    capability = features.get("capture_binding_provider")
    if type(capability) is not dict:
        return False
    if (
        capability.get("feature") != "capture_binding_provider"
        or capability.get("api_version") != "1.1"
        or capability.get("schema_version") != "1"
        or capability.get("supported") is not True
        or capability.get("position_checkpoints") is not True
        or capability.get("evidence_strength") != _CAPTURE_EVIDENCE_STRENGTH
    ):
        return False
    limits = capability.get("limits")
    if type(limits) is not dict:
        return False
    upper_bounds = {
        "max_roles": 32,
        "max_request_bytes": 65_536,
        "max_json_depth": 32,
        "max_role_bytes": 256,
        "max_selector_bytes": 16,
        "max_expected_device_by_id_bytes": 4_096,
        "max_expected_profile_bytes": 128,
        "max_serial_port_bytes": 4_096,
        "max_integer_digits": 16,
        "max_range_integer": (1 << 63) - 1,
        "max_page_records": 1_000,
        "max_page_bytes": 1_048_576,
        "page_deadline_ms": 5_000,
        "max_capture_records": MAX_CAPTURE_TOTAL_RECORDS,
        "max_capture_bytes": MAX_CAPTURE_TOTAL_BYTES,
        "max_record_bytes": MAX_CAPTURE_RECORD_BYTES,
        "finish_deadline_ms": 45_000,
        "max_operation_receipts": 128,
        "max_terminal_receipts": 64,
        "ttl_seconds": 86_400,
    }
    for name, maximum in upper_bounds.items():
        if not _bounded_int(limits.get(name), minimum=1, maximum=maximum):
            return False
    return limits["max_roles"] >= role_count


def _capability_limits(response: dict[str, Any]) -> dict[str, int]:
    return dict(response["features"]["capture_binding_provider"]["limits"])


def _role_plan_matches(
    config: TestbedConfig,
    request: CaptureRolePlanRequest,
    plan: EffectiveRolePlan,
) -> bool:
    try:
        projected = project_capture_role_plan(config, request)
    except (RolePlanError, TypeError, ValueError):
        return False
    return projected.digest == plan.digest


def _valid_strict_plan_limits(
    plan: EffectiveRolePlan,
    limits: dict[str, int],
) -> bool:
    if plan.provider_options:
        # Provider-option fields require an explicit Core-owned allowlist. This
        # consumer has none; the plugin's request cannot authorize itself.
        return False
    if len(plan.roles) > limits["max_roles"]:
        return False
    for role in plan.roles:
        values = (
            (role.role, "max_role_bytes"),
            (role.selector, "max_selector_bytes"),
            (role.expected_device_by_id, "max_expected_device_by_id_bytes"),
            (role.expected_profile, "max_expected_profile_bytes"),
        )
        if role.serial_port is not None:
            values += ((role.serial_port, "max_serial_port_bytes"),)
        for value, limit_name in values:
            try:
                encoded_length = len(value.encode("utf-8"))
            except UnicodeEncodeError:
                return False
            if encoded_length > limits[limit_name]:
                return False
    try:
        request_bytes = json.dumps(
            {
                "operation_id": str(uuid.uuid4()),
                "capture_id": str(uuid.uuid4()),
                "role_plan": role_plan_payload(plan),
            },
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError):
        return False
    return len(request_bytes) <= limits["max_request_bytes"]


def _capture_record_identity(
    response: object,
    *,
    operation_id: str,
    handle: str,
    capture_id: str,
    plan_digest: str,
    wal_epoch_token: str,
    start_watermark: str,
    start_sequence: int,
    last_position_token: str | None = None,
    last_sequence: int | None = None,
) -> bool:
    if not _capture_response_ok(response) or type(response) is not dict:
        return False
    expected: dict[str, object] = {
        "operation_id": operation_id,
        "handle": handle,
        "capture_id": capture_id,
        "plan_digest": plan_digest,
        "wal_epoch_token": wal_epoch_token,
        "start_watermark": start_watermark,
        "start_sequence": start_sequence,
    }
    if last_position_token is not None:
        expected["last_position_token"] = last_position_token
    if last_sequence is not None:
        expected["last_sequence"] = last_sequence
    return _echoes(response, expected)


def _provider_error_is_unsupported(response: object) -> bool:
    return type(response) is dict and response.get("error_code") in {
        "CAPTURE_PROVIDER_UNSUPPORTED",
        "CAPTURE_ROLE_PLAN_INVALID",
    }


def _echoes(response: dict[str, Any], anchors: dict[str, Any]) -> bool:
    return all(response.get(name) == value for name, value in anchors.items())


def _capture_response_ok(response: object) -> bool:
    return (
        type(response) is dict
        and response.get("ok") is True
        and response.get("schema_version") == "1"
    )

# ---------------------------------------------------------------------------
# Declarative behavior → serialwrap-command naming contract.
# Trace consumption is deferred so existing per-case trace output stays unchanged.
# ---------------------------------------------------------------------------

BEHAVIOR_COMMAND_MAP: dict[str, list[str]] = {
    "daemon_start":     ["daemon", "start"],
    "daemon_stop":      ["daemon", "stop"],
    "daemon_status":    ["daemon", "status"],
    "wal_reset":        ["wal", "reset"],
    "wal_current_seq":  ["wal", "current-seq"],
    "wal_export":       ["wal", "export", "--from-seq", "<from>", "--to-seq", "<to>", "--limit", "<limit>"],
    "device_list":      ["device", "list"],
    "session_bind":     ["session", "bind", "--selector", "<id>", "--device-by-id", "<by_id>"],
    "alias_set":        ["alias", "set", "--session-id", "<id>", "--alias", "<alias>"],
}


class SerialwrapBackend(RunBackend):
    """RunBackend that drives the serialwrap daemon for log capture.

    Args:
        serialwrap_binary: Optional explicit path to the serialwrap binary.
            Falls back to SERIALWRAP_BIN env var then PATH lookup.
    """

    def __init__(self, serialwrap_binary: str | None = None) -> None:
        self._serialwrap_binary = serialwrap_binary
        self._run_bindings: dict[str, SerialwrapLogBinding] = {}
        self._run_owners: dict[str, object | None] = {}
        self._strict_lock = RLock()
        self._strict_preflights: dict[str, _StrictPreflight] = {}
        self._strict_handles: dict[int, _StrictCaptureRecord] = {}

    # -- Strict capture API 1.1 lifecycle ------------------------------------

    def strict_capture_preflight(
        self,
        run_id: str,
        config: TestbedConfig,
        request: CaptureRolePlanRequest,
        plan: EffectiveRolePlan,
    ) -> StrictCaptureProviderAdmission:
        """Probe the explicitly selected API 1.1 endpoint before plugin prep.

        This performs one read-only capabilities request and reserves only the
        Core process-local logger lease. It never starts/attaches a daemon,
        resets the WAL, or reads target readiness.
        """
        if (
            type(run_id) is not str
            or not run_id
            or not isinstance(config, TestbedConfig)
            or type(request) is not CaptureRolePlanRequest
            or type(plan) is not EffectiveRolePlan
            or not _role_plan_matches(config, request, plan)
        ):
            return StrictCaptureProviderAdmission(
                StrictCaptureProviderOutcome.REJECTED,
                "capture_role_plan_invalid",
            )
        with self._strict_lock:
            if run_id in self._strict_preflights or any(
                record.run_id == run_id for record in self._strict_handles.values()
            ):
                return StrictCaptureProviderAdmission(
                    StrictCaptureProviderOutcome.REJECTED,
                    "capture_lease_busy",
                )

        testbed = config.raw.get("testbed", config.raw)
        if not isinstance(testbed, dict):
            return StrictCaptureProviderAdmission(
                StrictCaptureProviderOutcome.REJECTED,
                "capture_role_plan_invalid",
            )
        backend_binary = self._serialwrap_binary or (
            str(testbed.get("serialwrap_binary"))
            if testbed.get("serialwrap_binary")
            else None
        )
        roles = tuple(role.role for role in plan.roles)
        binding = resolve_serialwrap_log_binding(
            testbed,
            backend_binary=backend_binary,
            roles=roles,
            strict=True,
        )
        if not binding.enabled or not binding.binary or not binding.socket:
            return StrictCaptureProviderAdmission(
                StrictCaptureProviderOutcome.REJECTED,
                "capture_endpoint_invalid",
            )

        owner = object()
        if not _serialwrap_log.configure(
            binary=binding.binary,
            socket=binding.socket,
            enabled=True,
            reason="",
            owner=owner,
        ):
            return StrictCaptureProviderAdmission(
                StrictCaptureProviderOutcome.REJECTED,
                "capture_lease_busy",
            )

        client = SerialwrapCaptureBindingClient(binding.binary, binding.socket)
        try:
            response = client.call("capabilities", {})
        except StrictCaptureError:
            _serialwrap_log.release(owner)
            return StrictCaptureProviderAdmission(
                StrictCaptureProviderOutcome.REJECTED,
                "capture_provider_unavailable",
            )
        if _provider_error_is_unsupported(response) or (
            type(response) is dict
            and type(response.get("features")) is dict
            and type(response["features"].get("capture_binding_provider")) is dict
            and (
                response["features"]["capture_binding_provider"].get("supported") is False
                or response["features"]["capture_binding_provider"].get("api_version") == "1.0"
            )
        ):
            _serialwrap_log.release(owner)
            return StrictCaptureProviderAdmission(
                StrictCaptureProviderOutcome.REJECTED,
                "capture_provider_unsupported",
            )
        if not _valid_capability_response(response, len(plan.roles)):
            _serialwrap_log.release(owner)
            return StrictCaptureProviderAdmission(
                StrictCaptureProviderOutcome.REJECTED,
                "capture_provider_protocol_invalid",
            )
        limits = _capability_limits(response)
        if not _valid_strict_plan_limits(plan, limits):
            _serialwrap_log.release(owner)
            return StrictCaptureProviderAdmission(
                StrictCaptureProviderOutcome.REJECTED,
                "capture_role_plan_invalid",
            )
        preflight = _StrictPreflight(
            run_id=run_id,
            config=config,
            request=request,
            plan=plan,
            binding=binding,
            client=client,
            owner=owner,
            limits=limits,
        )
        with self._strict_lock:
            if run_id in self._strict_preflights or any(
                record.run_id == run_id for record in self._strict_handles.values()
            ):
                _serialwrap_log.release(owner)
                return StrictCaptureProviderAdmission(
                    StrictCaptureProviderOutcome.REJECTED,
                    "capture_lease_busy",
                )
            self._strict_preflights[run_id] = preflight
        return StrictCaptureProviderAdmission(StrictCaptureProviderOutcome.SUPPORTED)

    def begin_strict_capture(
        self,
        run_id: str,
        config: TestbedConfig,
        request: CaptureRolePlanRequest,
        plan: EffectiveRolePlan,
    ) -> RunHandle:
        """Begin one API 1.1 binding using the preflight's same config and plan."""
        with self._strict_lock:
            preflight = self._strict_preflights.get(run_id)
        if (
            preflight is None
            or config is not preflight.config
            or request is not preflight.request
            or plan is not preflight.plan
            or not _role_plan_matches(config, request, plan)
        ):
            raise StrictCaptureError("capture_role_plan_changed")

        operation_id = str(uuid.uuid4())
        capture_id = str(uuid.uuid4())
        request_payload = {
            "operation_id": operation_id,
            "capture_id": capture_id,
            "role_plan": role_plan_payload(plan),
        }
        try:
            response = self._strict_one_shot(
                preflight.client,
                "begin",
                request_payload,
                lambda value: self._valid_begin_response(
                    value,
                    operation_id=operation_id,
                    capture_id=capture_id,
                    plan=plan,
                    limits=preflight.limits,
                ),
            )
        except StrictCaptureError:
            raise

        tokens = response.get("binding_tokens")
        if type(tokens) is not list:
            raise StrictCaptureError("capture_begin_response_invalid", operation_uncertain=True)
        role_tokens = {
            role.selector: token
            for role, token in zip(plan.roles, tokens, strict=True)
        }
        start_sequence = response["start_sequence"]
        position = StrictCapturePosition(start_sequence, response["start_watermark"])
        handle = RunHandle(
            run_id=run_id,
            seq_start=start_sequence,
            meta={"wal_path": None, "bind_sessions": False, "strict_capture": True},
        )
        record = _StrictCaptureRecord(
            run_id=run_id,
            handle=handle,
            config=config,
            request=request,
            plan=plan,
            binding=preflight.binding,
            client=preflight.client,
            owner=preflight.owner,
            limits=preflight.limits,
            capture_id=capture_id,
            provider_handle=response["handle"],
            wal_epoch_token=response["wal_epoch_token"],
            start_watermark=response["start_watermark"],
            start_sequence=start_sequence,
            binding_tokens=role_tokens,
            last_position=position,
        )
        with self._strict_lock:
            if self._strict_preflights.get(run_id) is not preflight:
                _serialwrap_log.release(preflight.owner)
                raise StrictCaptureError("capture_preflight_lost")
            del self._strict_preflights[run_id]
            self._strict_handles[id(handle)] = record
        return handle

    def get_strict_capture_context(
        self,
        handle: RunHandle,
        *,
        run_id: str,
        run_seq_start: int,
    ) -> PrepareRunAfterCaptureContext | None:
        record = self._strict_record_for(handle)
        if (
            record is None
            or record.run_id != run_id
            or record.start_sequence != run_seq_start
        ):
            return None
        return PrepareRunAfterCaptureContext(
            run_id=record.run_id,
            start_sequence=record.start_sequence,
            capture_binding_id=record.capture_id,
        )

    def checkpoint_strict_capture(self, handle: RunHandle) -> StrictCapturePosition:
        record = self._strict_record_for(handle)
        if (
            record is None
            or record.mark_attempted
            or record.finished
            or record.operation_uncertain
            or record.provider_io_stopped
        ):
            raise StrictCaptureError("capture_handle_invalid")
        previous = record.last_position
        operation_id = str(uuid.uuid4())
        anchors = self._record_anchors(record)
        request_payload = {
            "operation_id": operation_id,
            **anchors,
            "previous_position_token": previous.position_token,
            "previous_sequence": previous.sequence,
        }
        record.pending_operation_id = operation_id
        try:
            response = self._strict_one_shot(
                record.client,
                "checkpoint",
                request_payload,
                lambda value: (
                    _capture_response_ok(value)
                    and type(value) is dict
                    and _echoes(value, request_payload)
                    and value.get("capture_status") == "active"
                    and value.get("evidence_strength") == _CAPTURE_EVIDENCE_STRENGTH
                    and _safe_token(value.get("position_token"))
                    and _bounded_int(
                        value.get("sequence"),
                        minimum=previous.sequence,
                        maximum=record.limits["max_range_integer"],
                    )
                ),
            )
        except StrictCaptureError as exc:
            record.operation_uncertain = exc.operation_uncertain
            if not exc.operation_uncertain:
                record.pending_operation_id = None
            raise
        position = StrictCapturePosition(response["sequence"], response["position_token"])
        record.last_position = position
        record.pending_operation_id = None
        return position

    def harvest_strict_for_handle(
        self,
        handle: RunHandle,
        artifact_dir: Path,
        case_results: list[Any],
        case_seq_ranges: dict[str, dict[str, int | None]],
    ) -> StrictCaptureHarvest:
        """Freeze one end and export only a completely validated fixed range."""
        record = self._strict_record_for(handle)
        if record is None:
            return StrictCaptureHarvest(
                StrictCaptureHarvestStatus.UNKNOWN,
                "capture_handle_invalid",
            )
        if (
            record.operation_uncertain
            or record.provider_io_stopped
            or record.pending_operation_id is not None
        ):
            return self._write_strict_harvest(
                record,
                artifact_dir,
                StrictCaptureHarvestStatus.UNKNOWN,
                (
                    "capture_operation_unknown"
                    if record.operation_uncertain or record.pending_operation_id is not None
                    else "capture_provider_io_stopped"
                ),
                None,
                None,
                0,
                0,
            )
        try:
            if not record.mark_attempted:
                self._mark_strict_end(record)
            if not record.marked or record.mark_response is None:
                return self._write_strict_harvest(
                    record,
                    artifact_dir,
                    StrictCaptureHarvestStatus.INCOMPLETE,
                    "capture_end_marker_unavailable",
                    record.start_sequence,
                    None,
                    0,
                    0,
                )
            if self._strict_case_ranges_problem(
                record,
                case_results,
                case_seq_ranges,
            ):
                # This is a local attribution failure. Do not make a provider
                # request after deciding that the interval cannot be trusted.
                record.provider_io_stopped = True
                return self._write_strict_harvest(
                    record,
                    artifact_dir,
                    StrictCaptureHarvestStatus.INCOMPLETE,
                    "case_sequence_range_invalid",
                    record.start_sequence,
                    record.mark_response["end_sequence"],
                    0,
                    0,
                )
            try:
                records, pages, range_complete = self._read_strict_range(record)
            except StrictCaptureError:
                # A range page is read-only and has no operation ID. An
                # invalid, incomplete-nonterminal, capped, or uncertain page
                # cannot be reconciled or followed by finish/status calls.
                record.provider_io_stopped = True
                raise
            if not range_complete:
                finish = self._finish_strict(record)
                status = (
                    StrictCaptureHarvestStatus.INCOMPLETE
                    if finish is False
                    else StrictCaptureHarvestStatus.UNKNOWN
                )
                return self._write_strict_harvest(
                    record,
                    artifact_dir,
                    status,
                    "capture_range_incomplete" if status is StrictCaptureHarvestStatus.INCOMPLETE else "capture_finish_unknown",
                    record.start_sequence,
                    record.mark_response["end_sequence"],
                    len(records),
                    pages,
                )
            finish = self._finish_strict(record)
            if finish is not True:
                return self._write_strict_harvest(
                    record,
                    artifact_dir,
                    StrictCaptureHarvestStatus.INCOMPLETE
                    if finish is False
                    else StrictCaptureHarvestStatus.UNKNOWN,
                    "capture_finish_incomplete" if finish is False else "capture_finish_unknown",
                    record.start_sequence,
                    record.mark_response["end_sequence"],
                    len(records),
                    pages,
                )
            return self._publish_strict_records(
                record,
                artifact_dir,
                case_results,
                case_seq_ranges,
                records,
                pages,
            )
        except StrictCaptureError as exc:
            if exc.operation_uncertain or record.provider_io_stopped:
                if exc.operation_uncertain:
                    record.operation_uncertain = True
                status = StrictCaptureHarvestStatus.UNKNOWN
                reason_code = exc.reason_code
            else:
                status = StrictCaptureHarvestStatus.INCOMPLETE
                reason_code = exc.reason_code
            return self._write_strict_harvest(
                record,
                artifact_dir,
                status,
                reason_code,
                record.start_sequence,
                (
                    record.mark_response.get("end_sequence")
                    if record.mark_response is not None
                    else None
                ),
                0,
                0,
            )

    @staticmethod
    def _strict_case_ranges_problem(
        record: _StrictCaptureRecord,
        case_results: list[Any],
        case_seq_ranges: dict[str, dict[str, int | None]],
    ) -> bool:
        if type(case_results) is not list or type(case_seq_ranges) is not dict:
            return True
        if record.mark_response is None:
            return True
        end_sequence = record.mark_response.get("end_sequence")
        if type(end_sequence) is not int:
            return True
        for result in case_results:
            case_id = getattr(result, "case_id", None)
            if type(case_id) is not str or not case_id:
                return True
            bounds = case_seq_ranges.get(case_id)
            if type(bounds) is not dict:
                return True
            before = bounds.get("seq_start")
            after = bounds.get("seq_end")
            if (
                type(before) is not int
                or type(after) is not int
                or before < record.start_sequence
                or after < before
                or after > end_sequence
            ):
                return True
        return False

    def release_strict_capture(self, handle: RunHandle) -> None:
        """Release only Core-local maps and logger lease; never contact provider."""
        record: _StrictCaptureRecord | None = None
        with self._strict_lock:
            candidate = self._strict_handles.get(id(handle))
            if candidate is not None and candidate.handle is handle:
                record = self._strict_handles.pop(id(handle))
        if record is not None:
            _serialwrap_log.release(record.owner)

    def cancel_strict_capture_preflight(self, run_id: str) -> None:
        """Cancel an unconsumed preflight using local cleanup only."""
        with self._strict_lock:
            preflight = self._strict_preflights.pop(run_id, None)
        if preflight is not None:
            _serialwrap_log.release(preflight.owner)

    def _strict_record_for(self, handle: object) -> _StrictCaptureRecord | None:
        if not isinstance(handle, RunHandle):
            return None
        with self._strict_lock:
            record = self._strict_handles.get(id(handle))
        return record if record is not None and record.handle is handle else None

    @staticmethod
    def _record_anchors(record: _StrictCaptureRecord) -> dict[str, Any]:
        return {
            "handle": record.provider_handle,
            "capture_id": record.capture_id,
            "plan_digest": record.plan.digest,
            "wal_epoch_token": record.wal_epoch_token,
            "start_watermark": record.start_watermark,
        }

    @staticmethod
    def _valid_begin_response(
        response: object,
        *,
        operation_id: str,
        capture_id: str,
        plan: EffectiveRolePlan,
        limits: dict[str, int],
    ) -> bool:
        if not _capture_response_ok(response) or type(response) is not dict:
            return False
        if (
            response.get("operation_id") != operation_id
            or response.get("capture_id") != capture_id
            or response.get("plan_digest") != plan.digest
            or response.get("capture_status") != "active"
            or response.get("evidence_strength") != _CAPTURE_EVIDENCE_STRENGTH
            or not _safe_token(response.get("handle"))
            or not _DIGEST_RE.fullmatch(str(response.get("wal_epoch_token", "")))
            or not _DIGEST_RE.fullmatch(str(response.get("start_watermark", "")))
            or not _bounded_int(
                response.get("start_sequence"),
                maximum=limits["max_range_integer"],
            )
            or not _bounded_int(
                response.get("expires_in_seconds"),
                minimum=1,
                maximum=limits["ttl_seconds"],
            )
            or type(response.get("roles_count")) is not int
            or response["roles_count"] != len(plan.roles)
        ):
            return False
        tokens = response.get("binding_tokens")
        return (
            type(tokens) is list
            and len(tokens) == len(plan.roles)
            and all(type(token) is str and _DIGEST_RE.fullmatch(token) for token in tokens)
        )

    @staticmethod
    def _strict_one_shot(
        client: SerialwrapCaptureBindingClient,
        action: str,
        payload: dict[str, Any],
        validator: Any,
    ) -> dict[str, Any]:
        operation_id = payload.get("operation_id")
        if not _valid_uuid4(operation_id):
            raise StrictCaptureError("capture_operation_invalid")
        try:
            response = client.call(action, payload)
        except StrictCaptureError as exc:
            if not exc.operation_uncertain:
                raise
            response = None
        if response is not None:
            if type(response) is dict and response.get("ok") is False:
                raise StrictCaptureError("capture_operation_rejected")
            if validator(response):
                return response
        try:
            reconciled = client.call("status", {"operation_id": operation_id})
        except StrictCaptureError:
            raise StrictCaptureError(
                "capture_operation_unknown", operation_uncertain=True
            ) from None
        if (
            type(reconciled) is dict
            and reconciled.get("reconciled") is True
            and reconciled.get("operation_id") == operation_id
            and validator(reconciled)
        ):
            return reconciled
        raise StrictCaptureError("capture_operation_unknown", operation_uncertain=True)

    def _mark_strict_end(self, record: _StrictCaptureRecord) -> None:
        if (
            record.mark_attempted
            or record.finished
            or record.operation_uncertain
            or record.provider_io_stopped
        ):
            return
        record.mark_attempted = True
        operation_id = str(uuid.uuid4())
        anchors = self._record_anchors(record)
        last = record.last_position
        payload = {
            "operation_id": operation_id,
            **anchors,
            "last_position_token": last.position_token,
            "last_sequence": last.sequence,
        }
        record.pending_operation_id = operation_id
        try:
            response = self._strict_one_shot(
                record.client,
                "mark",
                payload,
                lambda value: (
                    _capture_response_ok(value)
                    and type(value) is dict
                    and _echoes(value, payload)
                    and value.get("capture_status") == "active"
                    and value.get("evidence_strength") == _CAPTURE_EVIDENCE_STRENGTH
                    and _safe_token(value.get("watermark"))
                    and value.get("start_sequence") == record.start_sequence
                    and _bounded_int(
                        value.get("end_sequence"),
                        minimum=record.start_sequence,
                        maximum=record.limits["max_range_integer"],
                    )
                ),
            )
        except StrictCaptureError as exc:
            record.operation_uncertain = exc.operation_uncertain
            if not exc.operation_uncertain:
                record.pending_operation_id = None
            raise
        record.mark_response = response
        record.marked = True
        record.pending_operation_id = None

    def _read_strict_range(
        self,
        record: _StrictCaptureRecord,
    ) -> tuple[list[dict[str, Any]], int, bool]:
        assert record.mark_response is not None
        end_sequence = record.mark_response["end_sequence"]
        cursor = record.start_sequence + 1
        expected_sequence = cursor
        page_limit = min(record.limits["max_page_records"], 1_000)
        total_bytes = 0
        records: list[dict[str, Any]] = []
        observed_epoch: str | None = None
        page_count = 0
        while True:
            page_count += 1
            if page_count > min(MAX_CAPTURE_PAGES, record.limits["max_capture_records"] + 1):
                raise StrictCaptureError("capture_page_limit_exceeded")
            anchors = {
                **self._record_anchors(record),
                "watermark": record.mark_response["watermark"],
                "start_sequence": record.start_sequence,
                "end_sequence": end_sequence,
                "cursor": cursor,
            }
            response = record.client.call(
                "range",
                {**anchors, "limit": page_limit},
            )
            if type(response) is not dict or response.get("ok") is not True:
                raise StrictCaptureError("capture_range_incomplete")
            if not _capture_response_ok(response) or not _echoes(response, anchors):
                raise StrictCaptureError("capture_range_response_invalid")
            if response.get("evidence_strength") != _CAPTURE_EVIDENCE_STRENGTH:
                raise StrictCaptureError("capture_range_response_invalid")
            capture_status = response.get("capture_status")
            if type(capture_status) is not str or capture_status not in {
                "active",
                "incomplete",
            }:
                raise StrictCaptureError("capture_range_response_invalid")
            page_records = response.get("records")
            missing_ranges = response.get("missing_ranges")
            page_bytes = response.get("serialized_bytes")
            next_cursor = response.get("next_cursor")
            more = response.get("more")
            complete = response.get("complete")
            coverage_complete = response.get("coverage_complete")
            if (
                type(page_records) is not list
                or type(missing_ranges) is not list
                or type(page_bytes) is not int
                or page_bytes < 0
                or page_bytes > record.limits["max_page_bytes"]
                or type(more) is not bool
                or type(complete) is not bool
                or type(coverage_complete) is not bool
                or not _bounded_int(
                    response.get("cursor"),
                    maximum=record.limits["max_range_integer"],
                )
                or (next_cursor is not None and not _bounded_int(
                    next_cursor,
                    minimum=1,
                    maximum=record.limits["max_range_integer"],
                ))
            ):
                raise StrictCaptureError("capture_range_response_invalid")
            if response.get("cursor") != cursor:
                raise StrictCaptureError("capture_range_cursor_invalid")
            total_bytes += page_bytes
            if total_bytes > record.limits["max_capture_bytes"]:
                raise StrictCaptureError("capture_range_byte_limit")
            if len(records) + len(page_records) > record.limits["max_capture_records"]:
                raise StrictCaptureError("capture_range_record_limit")
            for raw_row in page_records:
                row, _payload = validate_capture_row(
                    raw_row,
                    expected_sequence=expected_sequence,
                )
                if observed_epoch is None:
                    observed_epoch = row["wal_epoch"]
                elif row["wal_epoch"] != observed_epoch:
                    raise StrictCaptureError("capture_epoch_changed")
                if row["com"] in record.binding_tokens and row["dir"] == "RX":
                    if (
                        row.get("rx_binding_token") != record.binding_tokens[row["com"]]
                        or row.get("rx_disposition") != "accepted"
                    ):
                        raise StrictCaptureError("capture_role_binding_changed")
                records.append(row)
                expected_sequence += 1

            if capture_status == "incomplete":
                if complete or more or next_cursor is not None or coverage_complete:
                    raise StrictCaptureError("capture_range_nonterminal_incomplete")
                return records, page_count, False
            if not complete:
                raise StrictCaptureError("capture_range_response_invalid")
            if missing_ranges:
                raise StrictCaptureError("capture_range_response_invalid")
            if more:
                if (
                    coverage_complete
                    or next_cursor is None
                    or next_cursor <= cursor
                    or next_cursor != expected_sequence
                ):
                    raise StrictCaptureError("capture_range_cursor_invalid")
                cursor = next_cursor
                continue
            if (
                next_cursor is not None
                or coverage_complete is not True
                or expected_sequence != end_sequence + 1
            ):
                raise StrictCaptureError("capture_range_coverage_incomplete")
            return records, page_count, True

    def _finish_strict(self, record: _StrictCaptureRecord) -> bool | None:
        if record.finished:
            return True
        if (
            record.finish_attempted
            or record.operation_uncertain
            or record.provider_io_stopped
            or record.mark_response is None
        ):
            return None
        record.finish_attempted = True
        operation_id = str(uuid.uuid4())
        payload = {
            "operation_id": operation_id,
            **self._record_anchors(record),
            "watermark": record.mark_response["watermark"],
            "start_sequence": record.start_sequence,
            "end_sequence": record.mark_response["end_sequence"],
        }

        def valid_finish(value: object) -> bool:
            if not _capture_response_ok(value) or type(value) is not dict:
                return False
            return (
                _echoes(value, payload)
                and value.get("complete") is (value.get("capture_status") == "complete")
                and value.get("capture_status") in {"complete", "incomplete"}
                and value.get("evidence_strength") == _CAPTURE_EVIDENCE_STRENGTH
            )

        record.pending_operation_id = operation_id
        try:
            response = self._strict_one_shot(record.client, "finish", payload, valid_finish)
        except StrictCaptureError as exc:
            record.operation_uncertain = exc.operation_uncertain
            if not exc.operation_uncertain:
                record.pending_operation_id = None
            raise
        record.pending_operation_id = None
        record.finished = True
        return response["complete"] is True

    def _publish_strict_records(
        self,
        record: _StrictCaptureRecord,
        artifact_dir: Path,
        case_results: list[Any],
        case_seq_ranges: dict[str, dict[str, int | None]],
        records: list[dict[str, Any]],
        page_count: int,
    ) -> StrictCaptureHarvest:
        dut_role = next((role for role in record.plan.roles if role.role == "dut"), None)
        sta_role = next((role for role in record.plan.roles if role.role == "sta"), None)
        dut_text = (
            _serialwrap_log.decode_log(records, com_filter=dut_role.selector)
            if dut_role is not None
            else ""
        )
        sta_text = (
            _serialwrap_log.decode_log(records, com_filter=sta_role.selector)
            if sta_role is not None
            else ""
        )
        dut_map = (
            _serialwrap_log.build_seq_to_line_span_map(records, com_filter=dut_role.selector)
            if dut_role is not None
            else {}
        )
        sta_map = (
            _serialwrap_log.build_seq_to_line_span_map(records, com_filter=sta_role.selector)
            if sta_role is not None
            else {}
        )
        try:
            artifact_dir.mkdir(parents=True, exist_ok=True)
            dut_path = (
                _serialwrap_log.save_decoded_log(dut_text, artifact_dir / "DUT.log")
                if dut_role is not None
                else None
            )
            sta_path = (
                _serialwrap_log.save_decoded_log(sta_text, artifact_dir / "STA.log")
                if sta_role is not None
                else None
            )
            manifest = self._strict_manifest(
                "complete",
                "capture_complete",
                record.start_sequence,
                record.mark_response["end_sequence"] if record.mark_response else None,
                len(records),
                page_count,
            )
            manifest_path = artifact_dir / "serialwrap-capture-manifest.json"
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except (OSError, ValueError, TypeError):
            return self._write_strict_harvest(
                record,
                artifact_dir,
                StrictCaptureHarvestStatus.INCOMPLETE,
                "capture_artifact_write_failed",
                record.start_sequence,
                record.mark_response["end_sequence"] if record.mark_response else None,
                len(records),
                page_count,
            )

        end_sequence = record.mark_response["end_sequence"] if record.mark_response else None
        for case_result in case_results:
            bounds = case_seq_ranges.get(getattr(case_result, "case_id", ""))
            if not isinstance(bounds, dict):
                continue
            before = bounds.get("seq_start")
            after = bounds.get("seq_end")
            if (
                type(before) is not int
                or type(after) is not int
                or before < record.start_sequence
                or after < before
                or end_sequence is None
                or after > end_sequence
            ):
                continue
            start = before + 1
            case_result.dut_log_lines = _serialwrap_log.seq_range_to_line_range(
                start, after, dut_map
            )
            case_result.sta_log_lines = _serialwrap_log.seq_range_to_line_range(
                start, after, sta_map
            )
        return StrictCaptureHarvest(
            StrictCaptureHarvestStatus.COMPLETE,
            "capture_complete",
            record.start_sequence,
            end_sequence,
            len(records),
            page_count,
            str(dut_path) if dut_path else "",
            str(sta_path) if sta_path else "",
            str(manifest_path),
        )

    @staticmethod
    def _strict_manifest(
        status: str,
        reason_code: str,
        start_sequence: int | None,
        end_sequence: int | None,
        record_count: int,
        page_count: int,
    ) -> dict[str, Any]:
        return {
            "status": status,
            "reason_code": reason_code,
            "coverage_complete": status == "complete",
            "run_seq_start": start_sequence,
            "run_seq_end": end_sequence,
            "record_count": record_count,
            "page_count": page_count,
        }

    def _write_strict_harvest(
        self,
        record: _StrictCaptureRecord,
        artifact_dir: Path,
        status: StrictCaptureHarvestStatus,
        reason_code: str,
        start_sequence: int | None,
        end_sequence: int | None,
        record_count: int,
        page_count: int,
    ) -> StrictCaptureHarvest:
        manifest_path = ""
        try:
            artifact_dir.mkdir(parents=True, exist_ok=True)
            path = artifact_dir / "serialwrap-capture-manifest.json"
            path.write_text(
                json.dumps(
                    self._strict_manifest(
                        status.value,
                        reason_code,
                        start_sequence,
                        end_sequence,
                        record_count,
                        page_count,
                    ),
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            manifest_path = str(path)
        except (OSError, ValueError, TypeError):
            pass
        return StrictCaptureHarvest(
            status,
            reason_code,
            start_sequence,
            end_sequence,
            record_count,
            page_count,
            manifest_path=manifest_path,
        )

    # -- RunBackend interface --------------------------------------------------

    def setup_run(self, run_id: str, config: dict[str, Any]) -> RunHandle:
        """Ensure daemon is running and WAL is clean/reset; return a RunHandle."""
        if run_id in self._run_bindings:
            raise ValueError(f"serialwrap run id already has capture state: {run_id}")
        backend_binary = self._serialwrap_binary or config.get("serialwrap_binary")
        binding = resolve_serialwrap_log_binding(
            config,
            backend_binary=str(backend_binary) if backend_binary else None,
        )
        if not binding.enabled:
            self._run_bindings[run_id] = binding
            self._run_owners[run_id] = None
            return self._disabled_run_handle(run_id, binding)

        owner = object()
        if not _serialwrap_log.configure(
            binary=binding.binary,
            socket=binding.socket,
            enabled=True,
            reason="",
            owner=owner,
        ):
            binding = replace(
                binding,
                enabled=False,
                binary=None,
                socket=None,
                reason="serialwrap logger is already owned by another active run",
            )
            self._run_bindings[run_id] = binding
            self._run_owners[run_id] = None
            return self._disabled_run_handle(run_id, binding)

        self._run_bindings[run_id] = binding
        self._run_owners[run_id] = owner
        binding_meta = binding.to_meta()
        started_fresh = False
        try:
            status = _serialwrap_log.daemon_status()
            if status and status.get("ok"):
                _serialwrap_log.wal_reset()
                wal_path = _serialwrap_log.get_wal_path()
                log.info(
                    "serialwrap daemon already running (pid=%s), WAL reset done",
                    status.get("pid"),
                )
            else:
                # daemon_status() 回 None 最常見的原因是 client 連不到「其實還活著」的
                # daemon（而非真的沒有 daemon）。因此這裡不可再對 WAL 目錄做本地
                # rmtree —— 那會刪掉存活 daemon 仍在寫入的檔案（#36）。start_daemon()
                # 對已在跑的 daemon 是 no-op/冪等；之後改走 RPC wal_reset()
                # 做輪替（daemon 自己保留歸檔，安全），且僅為 best-effort。
                started_fresh = True
                _serialwrap_log.start_daemon()
                try:
                    _serialwrap_log.wal_reset()
                except Exception:
                    log.warning(
                        "serialwrap wal_reset after start_daemon failed; "
                        "continuing without WAL rotation",
                        exc_info=True,
                    )
                wal_path = _serialwrap_log.get_wal_path()
                log.info("serialwrap daemon started, wal_path=%s", wal_path)
            return RunHandle(
                run_id=run_id,
                meta={
                    "wal_path": str(wal_path) if wal_path else None,
                    "bind_sessions": started_fresh,
                    "serialwrap_binding": binding_meta,
                },
            )
        except Exception:
            log.warning("serialwrap setup_run failed; logs will be unavailable", exc_info=True)
            return RunHandle(
                run_id=run_id,
                meta={
                    "bind_sessions": False,
                    "serialwrap_binding": binding_meta,
                },
            )

    @staticmethod
    def _disabled_run_handle(run_id: str, binding: SerialwrapLogBinding) -> RunHandle:
        log.warning("serialwrap run logging disabled: %s", binding.reason)
        return RunHandle(
            run_id=run_id,
            meta={
                "wal_path": None,
                "bind_sessions": False,
                "serialwrap_binding": binding.to_meta(),
            },
        )

    def bind_sessions(
        self,
        handle: RunHandle,
        devices: list[dict[str, Any]],
    ) -> None:
        """Bind serialwrap sessions to the listed devices."""
        binding = self._run_bindings.get(handle.run_id)
        if binding is None or not binding.enabled:
            return
        if handle.meta.get("serialwrap_binding", {}).get("enabled") is False:
            return
        _serialwrap_log.setup_sessions(devices)
        log.debug("bind_sessions: bound %d device(s) for run %s", len(devices), handle.run_id)

    def mark_position(self, handle: RunHandle) -> int | None:
        """Return the current WAL seq number."""
        binding = self._run_bindings.get(handle.run_id)
        if binding is None or not binding.enabled:
            return None
        if handle.meta.get("serialwrap_binding", {}).get("enabled") is False:
            return None
        try:
            # WAL paths returned by a broker may be remote filesystem paths.
            # Query the bound daemon by RPC and never borrow a same-named local
            # WAL if that endpoint is unavailable.
            return _serialwrap_log.get_current_seq(same_host_wal_path=False)
        except Exception:
            log.debug("mark_position failed for run %s", handle.run_id)
            return None

    def export_logs(self, request: ExportRequest) -> ExportResult:
        """Export WAL records, decode DUT/STA logs, and annotate case results.

        Exports the requested fixed sequence range in bounded pages. Case line
        references are attached only when the manifest proves complete coverage.
        """
        binding = self._run_bindings.get(request.run_id)
        if binding is None:
            return self._write_incomplete_export(request, "binding_missing")
        if not binding.enabled:
            return self._write_incomplete_export(
                request,
                "logging_disabled",
                binding=binding,
            )
        if request.run_seq_end is None:
            return self._write_incomplete_export(
                request,
                "end_marker_missing",
                binding=binding,
            )

        # serialwrap wal.range uses an exclusive --from-seq cursor. Retain the
        # marker itself here so the first record after it is not skipped.
        from_seq = 0 if request.run_seq_start is None else max(int(request.run_seq_start), 0)
        try:
            export = _serialwrap_log.export_records_with_metadata(
                from_seq=from_seq,
                to_seq=request.run_seq_end,
                limit=0,
            )
        except Exception as exc:
            export_path = Path(request.artifact_dir) / "serialwrap-wal-export.json"
            export_path.parent.mkdir(parents=True, exist_ok=True)
            manifest = {
                "requested_from_seq_exclusive": from_seq,
                "requested_to_seq_inclusive": request.run_seq_end,
                "record_count": 0,
                "pages_fetched": 0,
                "available_from_seq": None,
                "rotated_out": False,
                "continuity_kind": "content_anchor",
                "generation_available": False,
                "continuity_note": _serialwrap_log._WAL_CONTINUITY_NOTE,
                "complete": False,
                "incomplete_reasons": ["export_error"],
                "missing_sequence_ranges": [],
                "error_type": type(exc).__name__,
                "records": [],
            }
            manifest["binding"] = binding.to_meta()
            export_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            log.warning("serialwrap WAL export failed (%s)", type(exc).__name__)
            return ExportResult(paths={"wal_export_path": str(export_path)})
        records = export.records
        export_path = Path(request.artifact_dir) / "serialwrap-wal-export.json"
        export_path.parent.mkdir(parents=True, exist_ok=True)
        manifest = export.to_dict()
        manifest["binding"] = binding.to_meta()
        export_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if not records:
            return ExportResult(paths={"wal_export_path": str(export_path)})

        dut_com = request.dut_com
        sta_com = request.sta_com

        dut_text = _serialwrap_log.decode_log(records, com_filter=dut_com)
        sta_text = _serialwrap_log.decode_log(records, com_filter=sta_com)
        dut_log_path = _serialwrap_log.save_decoded_log(
            dut_text, Path(request.artifact_dir) / "DUT.log"
        )
        sta_log_path = _serialwrap_log.save_decoded_log(
            sta_text, Path(request.artifact_dir) / "STA.log"
        )

        if export.complete:
            dut_line_map = _serialwrap_log.build_seq_to_line_span_map(records, com_filter=dut_com)
            sta_line_map = _serialwrap_log.build_seq_to_line_span_map(records, com_filter=sta_com)
            for cr in request.case_results:
                seq_range = request.case_seq_ranges.get(cr.case_id)
                if not seq_range:
                    continue
                s, e = seq_range.get("seq_start"), seq_range.get("seq_end")
                cr.dut_log_lines = _serialwrap_log.seq_range_to_line_range(s, e, dut_line_map)
                cr.sta_log_lines = _serialwrap_log.seq_range_to_line_range(s, e, sta_line_map)
        else:
            log.warning(
                "serialwrap WAL export is incomplete: reasons=%s, missing_ranges=%s",
                export.incomplete_reasons,
                export.missing_sequence_ranges[:20],
            )

        log.info("serialwrap logs saved: %s, %s", dut_log_path, sta_log_path)
        return ExportResult(paths={
            "dut_log_path": str(dut_log_path),
            "sta_log_path": str(sta_log_path),
            "wal_export_path": str(export_path),
        })

    def teardown_run(self, handle: RunHandle) -> None:
        """Keep the daemon alive but clear the run-scoped client target."""
        owner = self._run_owners.pop(handle.run_id, None)
        self._run_bindings.pop(handle.run_id, None)
        if owner is not None:
            _serialwrap_log.release(owner)
        log.debug("teardown_run: daemon kept alive for run %s", handle.run_id)

    @staticmethod
    def _write_incomplete_export(
        request: ExportRequest,
        reason: str,
        *,
        binding: SerialwrapLogBinding | None = None,
    ) -> ExportResult:
        export_path = Path(request.artifact_dir) / "serialwrap-wal-export.json"
        export_path.parent.mkdir(parents=True, exist_ok=True)
        from_seq = (
            0
            if request.run_seq_start is None
            else max(int(request.run_seq_start), 0)
        )
        manifest: dict[str, Any] = {
            "requested_from_seq_exclusive": from_seq,
            "requested_to_seq_inclusive": request.run_seq_end,
            "record_count": 0,
            "pages_fetched": 0,
            "available_from_seq": None,
            "rotated_out": False,
            "continuity_kind": "content_anchor",
            "generation_available": False,
            "continuity_note": _serialwrap_log._WAL_CONTINUITY_NOTE,
            "complete": False,
            "incomplete_reasons": [reason],
            "missing_sequence_ranges": [],
            "records": [],
        }
        if binding is not None:
            manifest["binding"] = binding.to_meta()
        export_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return ExportResult(paths={"wal_export_path": str(export_path)})
