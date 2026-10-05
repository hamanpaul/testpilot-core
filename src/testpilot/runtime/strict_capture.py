"""Private, finite contracts for the API 1.1 strict capture consumer."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import math
import re
import zlib
from typing import Any

from testpilot.core.role_plan import EffectiveRolePlan

_SAFE_REASON = re.compile(r"[a-z][a-z0-9_.-]{0,63}\Z")
_OPAQUE_TOKEN = re.compile(r"[A-Za-z0-9_-]{1,256}\Z")
_HEX_64 = re.compile(r"[0-9a-f]{64}\Z")
MAX_CAPTURE_RECORD_BYTES = 65_536
MAX_CAPTURE_TOTAL_RECORDS = 100_000
MAX_CAPTURE_TOTAL_BYTES = 64 * 1024 * 1024
MAX_CAPTURE_PAGES = 100
MAX_JSON_DEPTH = 32


class StrictCaptureError(RuntimeError):
    """Sanitized internal capture failure; never formats provider data."""

    def __init__(self, reason_code: str, *, operation_uncertain: bool = False) -> None:
        if type(reason_code) is not str or not _SAFE_REASON.fullmatch(reason_code):
            reason_code = "capture_protocol_invalid"
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.operation_uncertain = operation_uncertain


@dataclass(frozen=True, slots=True, repr=False)
class StrictCapturePosition:
    """One accepted checkpoint; its opaque token never appears in repr/artifacts."""

    sequence: int
    position_token: str

    def __post_init__(self) -> None:
        if type(self.sequence) is not int or self.sequence < 0:
            raise ValueError("capture sequence is invalid")
        if (
            type(self.position_token) is not str
            or not _OPAQUE_TOKEN.fullmatch(self.position_token)
        ):
            raise ValueError("capture position token is invalid")


class StrictCaptureHarvestStatus(str, Enum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class StrictCaptureHarvest:
    """Sanitized result from a bounded fixed-range harvest."""

    status: StrictCaptureHarvestStatus
    reason_code: str
    start_sequence: int | None = None
    end_sequence: int | None = None
    record_count: int = 0
    page_count: int = 0
    dut_log_path: str = ""
    sta_log_path: str = ""
    manifest_path: str = ""

    def __post_init__(self) -> None:
        if type(self.status) is not StrictCaptureHarvestStatus:
            raise ValueError("capture harvest status is invalid")
        if type(self.reason_code) is not str or not _SAFE_REASON.fullmatch(self.reason_code):
            raise ValueError("capture harvest reason is invalid")
        for value in (self.start_sequence, self.end_sequence):
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError("capture harvest sequence is invalid")
        if type(self.record_count) is not int or not 0 <= self.record_count <= MAX_CAPTURE_TOTAL_RECORDS:
            raise ValueError("capture harvest record count is invalid")
        if type(self.page_count) is not int or not 0 <= self.page_count <= MAX_CAPTURE_PAGES:
            raise ValueError("capture harvest page count is invalid")
        for path in (self.dut_log_path, self.sta_log_path, self.manifest_path):
            if type(path) is not str:
                raise ValueError("capture harvest path is invalid")

    def to_payload(self) -> dict[str, object]:
        """Expose only bounded status/count/path metadata, never capture tokens."""
        return {
            "status": self.status.value,
            "reason_code": self.reason_code,
            "run_seq_start": self.start_sequence,
            "run_seq_end": self.end_sequence,
            "record_count": self.record_count,
            "page_count": self.page_count,
        }


def role_plan_payload(plan: EffectiveRolePlan) -> dict[str, Any]:
    """Create the exact private physical-plan envelope accepted by the provider."""
    if type(plan) is not EffectiveRolePlan:
        raise StrictCaptureError("capture_role_plan_invalid")
    roles: list[dict[str, Any]] = []
    for role in plan.roles:
        row: dict[str, Any] = {
            "role": role.role,
            "selector": role.selector,
            "expected_device_by_id": role.expected_device_by_id,
            "expected_profile": role.expected_profile,
        }
        if role.serial_port is not None:
            row["serial_port"] = role.serial_port
        roles.append(row)
    return {
        "roles": roles,
        "physical_identity_digest": plan.physical_identity_digest,
        "provider_options_digest": plan.provider_options_digest,
        "digest": plan.digest,
    }


def _json_depth(value: Any, depth: int = 0) -> bool:
    if depth > MAX_JSON_DEPTH:
        return False
    if isinstance(value, dict):
        return all(type(key) is str and _json_depth(item, depth + 1) for key, item in value.items())
    if isinstance(value, list):
        return all(_json_depth(item, depth + 1) for item in value)
    if type(value) is float:
        return math.isfinite(value)
    return value is None or type(value) in {str, bool, int}


def validate_capture_row(row: object, *, expected_sequence: int) -> tuple[dict[str, Any], bytes]:
    """Validate one complete API 1.1 WAL envelope, CRC, payload, and ordering."""
    if type(row) is not dict:
        raise StrictCaptureError("capture_row_invalid")
    required_keys = {
        "seq",
        "wal_epoch",
        "mono_ts_ns",
        "wall_ts",
        "com",
        "dir",
        "source",
        "cmd_id",
        "len",
        "crc32",
        "payload_b64",
        "loss_flag",
        "meta",
        "envelope_sha256",
    }
    allowed_keys = required_keys | {
        "rx_binding_token",
        "rx_disposition",
        "rotation_failed",
    }
    if not required_keys.issubset(row) or set(row) - allowed_keys:
        raise StrictCaptureError("capture_row_invalid")
    if ("rx_binding_token" in row) != ("rx_disposition" in row):
        raise StrictCaptureError("capture_row_invalid")
    seq = row.get("seq")
    if type(seq) is not int or seq != expected_sequence:
        raise StrictCaptureError("capture_sequence_gap")
    epoch = row.get("wal_epoch")
    if type(epoch) is not str or not epoch or len(epoch) > 256:
        raise StrictCaptureError("capture_row_invalid")
    if row.get("loss_flag") is not False:
        raise StrictCaptureError("capture_loss_detected")
    rotation_failed = row.get("rotation_failed", False)
    if type(rotation_failed) is not bool or rotation_failed:
        raise StrictCaptureError("capture_loss_detected")

    length = row.get("len")
    if type(length) is not int or not 0 <= length <= MAX_CAPTURE_RECORD_BYTES:
        raise StrictCaptureError("capture_row_invalid")
    payload_b64 = row.get("payload_b64")
    max_encoded = ((MAX_CAPTURE_RECORD_BYTES + 2) // 3) * 4
    if type(payload_b64) is not str or len(payload_b64) > max_encoded:
        raise StrictCaptureError("capture_row_invalid")
    try:
        payload = base64.b64decode(payload_b64, validate=True)
    except (ValueError, TypeError):
        raise StrictCaptureError("capture_payload_invalid") from None
    if len(payload) != length:
        raise StrictCaptureError("capture_payload_invalid")
    crc = row.get("crc32")
    if type(crc) is not str or crc != f"{zlib.crc32(payload) & 0xFFFFFFFF:08x}":
        raise StrictCaptureError("capture_payload_invalid")

    if type(row.get("com")) is not str or not row["com"]:
        raise StrictCaptureError("capture_row_invalid")
    if type(row.get("dir")) is not str or row["dir"] not in {"RX", "TX"}:
        raise StrictCaptureError("capture_row_invalid")
    if type(row.get("source")) is not str or not row["source"]:
        raise StrictCaptureError("capture_row_invalid")
    if type(row.get("mono_ts_ns")) is not int or row["mono_ts_ns"] < 0:
        raise StrictCaptureError("capture_row_invalid")
    if row.get("wall_ts") is not None and type(row["wall_ts"]) is not str:
        raise StrictCaptureError("capture_row_invalid")
    if row.get("cmd_id") is not None and type(row["cmd_id"]) is not str:
        raise StrictCaptureError("capture_row_invalid")
    if type(row.get("meta")) is not dict or not _json_depth(row["meta"]):
        raise StrictCaptureError("capture_row_invalid")

    token = row.get("rx_binding_token")
    disposition = row.get("rx_disposition")
    if row["dir"] == "RX":
        if (
            type(token) is not str
            or not _HEX_64.fullmatch(token)
            or disposition not in {"accepted", "unbound"}
        ):
            raise StrictCaptureError("capture_row_invalid")
    elif "rx_binding_token" in row:
        raise StrictCaptureError("capture_row_invalid")

    envelope = row.get("envelope_sha256")
    if type(envelope) is not str or not _HEX_64.fullmatch(envelope):
        raise StrictCaptureError("capture_row_invalid")
    try:
        material = json.dumps(
            {key: value for key, value in row.items() if key != "envelope_sha256"},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError):
        raise StrictCaptureError("capture_row_invalid") from None
    expected_envelope = hashlib.sha256(b"serialwrap-wal-envelope-v1\0" + material).hexdigest()
    if envelope != expected_envelope:
        raise StrictCaptureError("capture_row_invalid")
    return row, payload
