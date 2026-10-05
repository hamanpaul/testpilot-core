from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import zlib

import pytest

from testpilot.api import CaptureRolePlanRequest
from testpilot.core.run_start_gate import StrictCaptureProviderOutcome
from testpilot.core.role_plan import project_capture_role_plan
from testpilot.core.run_start_gate import PrepareRunAfterCaptureContext
from testpilot.core.testbed_config import TestbedConfig
from testpilot.runtime import serialwrap_backend as backend_module
from testpilot.runtime import _serialwrap_log
from testpilot.runtime.run_backend import RunHandle
from testpilot.runtime.serialwrap_log_binding import SerialwrapLogBinding
from testpilot.runtime.strict_capture import StrictCaptureError, StrictCaptureHarvestStatus


_LIMITS = {
    "max_roles": 32,
    "max_request_bytes": 65_536,
    "max_json_depth": 32,
    "max_role_bytes": 256,
    "max_selector_bytes": 16,
    "max_expected_device_by_id_bytes": 4096,
    "max_expected_profile_bytes": 128,
    "max_serial_port_bytes": 4096,
    "max_integer_digits": 16,
    "max_range_integer": (1 << 63) - 1,
    "max_page_records": 1000,
    "max_page_bytes": 1_048_576,
    "page_deadline_ms": 5000,
    "max_capture_records": 100_000,
    "max_capture_bytes": 64 * 1024 * 1024,
    "max_record_bytes": 65_536,
    "finish_deadline_ms": 45_000,
    "max_operation_receipts": 128,
    "max_terminal_receipts": 64,
    "ttl_seconds": 86_400,
}


def _capability(api_version: str = "1.1", *, supported: bool = True) -> dict[str, object]:
    return {
        "ok": True,
        "features": {
            "capture_binding_provider": {
                "feature": "capture_binding_provider",
                "api_version": api_version,
                "schema_version": "1",
                "supported": supported,
                "position_checkpoints": api_version == "1.1" and supported,
                "evidence_strength": (
                    "posix_fd_devnode_match_v1" if supported else "unsupported"
                ),
                "limits": dict(_LIMITS),
            }
        },
    }


def _config(tmp_path: Path) -> TestbedConfig:
    path = tmp_path / "testbed.yaml"
    path.write_text(
        "testbed:\n"
        "  devices:\n"
        "    dut:\n"
        "      selector: COM0\n"
        "      expected_device_by_id: /dev/fake-dut\n"
        "      profile: generic-console\n",
        encoding="utf-8",
    )
    return TestbedConfig(path)


def _row(sequence: int, text: str) -> dict[str, object]:
    payload = text.encode("utf-8")
    row: dict[str, object] = {
        "seq": sequence,
        "wal_epoch": "epoch-row-1",
        "mono_ts_ns": sequence * 100,
        "wall_ts": "2026-10-05T00:00:00+00:00",
        "com": "COM0",
        "dir": "TX",
        "source": "console",
        "cmd_id": None,
        "len": len(payload),
        "crc32": f"{zlib.crc32(payload) & 0xFFFFFFFF:08x}",
        "payload_b64": base64.b64encode(payload).decode("ascii"),
        "loss_flag": False,
        "meta": {},
    }
    material = json.dumps(
        row,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    row["envelope_sha256"] = hashlib.sha256(
        b"serialwrap-wal-envelope-v1\0" + material
    ).hexdigest()
    return row


class _FakeClient:
    def __init__(
        self,
        capability: dict[str, object] | None = None,
        *,
        range_complete: bool = True,
        range_more: bool = False,
        range_bad_anchor: bool = False,
        range_unknown: bool = False,
        finish_complete: bool = True,
        status_unresolved: bool = False,
    ) -> None:
        self.capability = capability or _capability()
        self.range_complete = range_complete
        self.range_more = range_more
        self.range_bad_anchor = range_bad_anchor
        self.range_unknown = range_unknown
        self.finish_complete = finish_complete
        self.status_unresolved = status_unresolved
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.checkpoint_sequence = 10
        self.saved_operations: dict[str, dict[str, object]] = {}
        self.lose_next_checkpoint_reply = False
        self.pages = [_row(11, "first\n"), _row(12, "second\n")]

    @staticmethod
    def _anchors(request: dict[str, object]) -> dict[str, object]:
        return {
            key: request[key]
            for key in (
                "operation_id",
                "handle",
                "capture_id",
                "plan_digest",
                "wal_epoch_token",
                "start_watermark",
                "previous_position_token",
                "previous_sequence",
            )
            if key in request
        }

    def call(self, action: str, request: dict[str, object]) -> dict[str, object]:
        self.calls.append((action, dict(request)))
        if action == "capabilities":
            return self.capability
        if action == "begin":
            return {
                "ok": True,
                "schema_version": "1",
                "capture_status": "active",
                "operation_id": request["operation_id"],
                "capture_id": request["capture_id"],
                "handle": "opaque-handle-1",
                "plan_digest": request["role_plan"]["digest"],
                "evidence_strength": "posix_fd_devnode_match_v1",
                "roles_count": len(request["role_plan"]["roles"]),
                "binding_tokens": ["f" * 64],
                "daemon_token": "d" * 64,
                "wal_epoch_token": "b" * 64,
                "start_watermark": "a" * 64,
                "start_sequence": 10,
                "expires_in_seconds": 86_400,
            }
        if action == "checkpoint":
            self.checkpoint_sequence += 1
            response = {
                "ok": True,
                "schema_version": "1",
                "capture_status": "active",
                **self._anchors(request),
                "evidence_strength": "posix_fd_devnode_match_v1",
                "position_token": f"{self.checkpoint_sequence:064x}",
                "sequence": self.checkpoint_sequence,
            }
            self.saved_operations[str(request["operation_id"])] = dict(response)
            if self.lose_next_checkpoint_reply:
                self.lose_next_checkpoint_reply = False
                raise StrictCaptureError("capture_rpc_unknown", operation_uncertain=True)
            return response
        if action == "status":
            if self.status_unresolved:
                return {"ok": False, "error_code": "OPERATION_UNKNOWN"}
            response = dict(self.saved_operations[str(request["operation_id"])])
            response["reconciled"] = True
            return response
        if action == "mark":
            return {
                "ok": True,
                "schema_version": "1",
                "capture_status": "active",
                **request,
                "evidence_strength": "posix_fd_devnode_match_v1",
                "watermark": "c" * 64,
                "start_sequence": 10,
                "end_sequence": 12,
            }
        if action == "range":
            if self.range_unknown:
                raise StrictCaptureError("capture_rpc_unknown", operation_uncertain=True)
            response = {
                "ok": True,
                "schema_version": "1",
                "capture_status": "active" if self.range_complete else "incomplete",
                **request,
                "evidence_strength": "posix_fd_devnode_match_v1",
                "complete": self.range_complete,
                "more": self.range_more,
                "coverage_complete": self.range_complete,
                "next_cursor": 13 if self.range_more else None,
                "serialized_bytes": (
                    sum(len(json.dumps(row)) for row in self.pages)
                    if self.range_complete
                    else 0
                ),
                "missing_ranges": [] if self.range_complete else [{"start": 11, "end": 12}],
                "records": list(self.pages) if self.range_complete else [],
            }
            if self.range_bad_anchor:
                response["plan_digest"] = "0" * 64
            return response
        if action == "finish":
            return {
                "ok": True,
                "schema_version": "1",
                "capture_status": "complete" if self.finish_complete else "incomplete",
                **request,
                "complete": self.finish_complete,
                "evidence_strength": "posix_fd_devnode_match_v1",
            }
        raise AssertionError(f"unexpected provider route: {action}")


def _backend_with_fake(
    monkeypatch: pytest.MonkeyPatch,
    fake: _FakeClient,
) -> backend_module.SerialwrapBackend:
    binding = SerialwrapLogBinding(
        enabled=True,
        binary="/opt/fake-serialwrap",
        socket="unix:///tmp/fake-serialwrap.sock",
        binary_source="device_config",
        socket_source="device_config",
        device_count=1,
    )
    monkeypatch.setattr(
        backend_module,
        "resolve_serialwrap_log_binding",
        lambda *args, **kwargs: binding,
    )
    monkeypatch.setattr(
        backend_module,
        "SerialwrapCaptureBindingClient",
        lambda binary, socket: fake,
    )
    return backend_module.SerialwrapBackend()


def test_api_10_provider_is_rejected_during_read_only_preflight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeClient(_capability("1.0"))
    backend = _backend_with_fake(monkeypatch, fake)
    config = _config(tmp_path)
    request = CaptureRolePlanRequest(roles=("dut",))
    plan = project_capture_role_plan(config, request)

    admission = backend.strict_capture_preflight("run-1", config, request, plan)

    assert admission.outcome is StrictCaptureProviderOutcome.REJECTED
    assert admission.reason_code == "capture_provider_unsupported"
    assert [action for action, _ in fake.calls] == ["capabilities"]
    assert backend._strict_preflights == {}
    assert _serialwrap_log._configured_owner is None


def test_strict_backend_uses_one_bound_handle_and_complete_only_case_lines(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeClient()
    fake.lose_next_checkpoint_reply = True
    backend = _backend_with_fake(monkeypatch, fake)
    config = _config(tmp_path)
    request = CaptureRolePlanRequest(roles=("dut",))
    plan = project_capture_role_plan(config, request)

    admission = backend.strict_capture_preflight("run-2", config, request, plan)
    assert admission.outcome is StrictCaptureProviderOutcome.SUPPORTED
    with pytest.raises(StrictCaptureError, match="capture_role_plan_changed"):
        backend.begin_strict_capture(
            "run-2", config, request, project_capture_role_plan(config, request)
        )

    handle = backend.begin_strict_capture("run-2", config, request, plan)
    context = backend.get_strict_capture_context(
        handle,
        run_id="run-2",
        run_seq_start=10,
    )
    assert type(context) is PrepareRunAfterCaptureContext
    assert context.start_sequence == 10
    assert context.capture_binding_id == fake.calls[1][1]["capture_id"]

    forged = RunHandle(run_id="run-2", seq_start=10)
    with pytest.raises(StrictCaptureError, match="capture_handle_invalid"):
        backend.checkpoint_strict_capture(forged)
    before = backend.checkpoint_strict_capture(handle)
    after = backend.checkpoint_strict_capture(handle)
    assert (before.sequence, after.sequence) == (11, 12)
    assert [action for action, _ in fake.calls].count("checkpoint") == 2
    assert [action for action, _ in fake.calls].count("status") == 1

    case_result = SimpleNamespace(case_id="D001", dut_log_lines="", sta_log_lines="")
    case_ranges = {"D001": {"seq_start": before.sequence, "seq_end": after.sequence}}
    harvest = backend.harvest_strict_for_handle(
        handle,
        tmp_path / "artifacts",
        [case_result],
        case_ranges,
    )

    assert harvest.status is StrictCaptureHarvestStatus.COMPLETE
    assert case_result.dut_log_lines == "L2-L2"
    assert (tmp_path / "artifacts" / "DUT.log").read_text(encoding="utf-8") == "first\nsecond\n"
    manifest = json.loads((tmp_path / "artifacts" / "serialwrap-capture-manifest.json").read_text())
    assert manifest["coverage_complete"] is True
    assert "capture_id" not in manifest
    assert "handle" not in manifest
    assert all(action not in {"mark", "range", "finish"} for action, _ in fake.calls[:-3])

    calls_before_release = len(fake.calls)
    backend.release_strict_capture(handle)
    assert len(fake.calls) == calls_before_release
    assert _serialwrap_log._configured_owner is None


def test_known_incomplete_range_is_terminalized_without_publishing_logs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeClient(range_complete=False, finish_complete=False)
    backend = _backend_with_fake(monkeypatch, fake)
    config = _config(tmp_path)
    request = CaptureRolePlanRequest(roles=("dut",))
    plan = project_capture_role_plan(config, request)

    admission = backend.strict_capture_preflight("run-incomplete", config, request, plan)
    assert admission.outcome is StrictCaptureProviderOutcome.SUPPORTED
    handle = backend.begin_strict_capture("run-incomplete", config, request, plan)
    harvest = backend.harvest_strict_for_handle(handle, tmp_path / "incomplete", [], {})

    assert harvest.status is StrictCaptureHarvestStatus.INCOMPLETE
    assert harvest.reason_code == "capture_range_incomplete"
    assert [action for action, _ in fake.calls] == [
        "capabilities",
        "begin",
        "mark",
        "range",
        "finish",
    ]
    assert not (tmp_path / "incomplete" / "DUT.log").exists()
    manifest = json.loads(
        (tmp_path / "incomplete" / "serialwrap-capture-manifest.json").read_text()
    )
    assert manifest["coverage_complete"] is False


def test_nonterminal_incomplete_range_stops_without_finish_or_another_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeClient(range_complete=False, range_more=True)
    backend = _backend_with_fake(monkeypatch, fake)
    config = _config(tmp_path)
    request = CaptureRolePlanRequest(roles=("dut",))
    plan = project_capture_role_plan(config, request)

    admission = backend.strict_capture_preflight("run-nonterminal-range", config, request, plan)
    assert admission.outcome is StrictCaptureProviderOutcome.SUPPORTED
    handle = backend.begin_strict_capture("run-nonterminal-range", config, request, plan)
    harvest = backend.harvest_strict_for_handle(
        handle,
        tmp_path / "nonterminal-range",
        [],
        {},
    )

    assert harvest.status is StrictCaptureHarvestStatus.UNKNOWN
    assert harvest.reason_code == "capture_range_nonterminal_incomplete"
    assert [action for action, _ in fake.calls] == ["capabilities", "begin", "mark", "range"]
    assert not (tmp_path / "nonterminal-range" / "DUT.log").exists()


def test_uncertain_checkpoint_allows_only_same_operation_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeClient(status_unresolved=True)
    fake.lose_next_checkpoint_reply = True
    backend = _backend_with_fake(monkeypatch, fake)
    config = _config(tmp_path)
    request = CaptureRolePlanRequest(roles=("dut",))
    plan = project_capture_role_plan(config, request)

    admission = backend.strict_capture_preflight("run-unknown", config, request, plan)
    assert admission.outcome is StrictCaptureProviderOutcome.SUPPORTED
    handle = backend.begin_strict_capture("run-unknown", config, request, plan)
    with pytest.raises(StrictCaptureError, match="capture_operation_unknown"):
        backend.checkpoint_strict_capture(handle)
    result = SimpleNamespace(case_id="D001", dut_log_lines="", sta_log_lines="")
    harvest = backend.harvest_strict_for_handle(handle, tmp_path / "unknown", [result], {})

    assert harvest.status is StrictCaptureHarvestStatus.UNKNOWN
    assert [action for action, _ in fake.calls] == ["capabilities", "begin", "checkpoint", "status"]
    assert result.dut_log_lines == ""
    assert result.sta_log_lines == ""


def test_invalid_case_interval_stops_provider_io_without_exporting_logs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeClient()
    backend = _backend_with_fake(monkeypatch, fake)
    config = _config(tmp_path)
    request = CaptureRolePlanRequest(roles=("dut",))
    plan = project_capture_role_plan(config, request)

    admission = backend.strict_capture_preflight("run-bad-case-range", config, request, plan)
    assert admission.outcome is StrictCaptureProviderOutcome.SUPPORTED
    handle = backend.begin_strict_capture("run-bad-case-range", config, request, plan)
    result = SimpleNamespace(case_id="D001", dut_log_lines="", sta_log_lines="")
    harvest = backend.harvest_strict_for_handle(
        handle,
        tmp_path / "bad-case-range",
        [result],
        {"D001": {"seq_start": 12, "seq_end": 11}},
    )

    assert harvest.status is StrictCaptureHarvestStatus.INCOMPLETE
    assert harvest.reason_code == "case_sequence_range_invalid"
    assert [action for action, _ in fake.calls] == ["capabilities", "begin", "mark"]
    assert result.dut_log_lines == ""
    assert result.sta_log_lines == ""
    assert not (tmp_path / "bad-case-range" / "DUT.log").exists()


def test_wrong_range_anchor_stops_without_status_or_finish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeClient(range_bad_anchor=True)
    backend = _backend_with_fake(monkeypatch, fake)
    config = _config(tmp_path)
    request = CaptureRolePlanRequest(roles=("dut",))
    plan = project_capture_role_plan(config, request)

    backend.strict_capture_preflight("run-wrong-range-anchor", config, request, plan)
    handle = backend.begin_strict_capture("run-wrong-range-anchor", config, request, plan)
    result = SimpleNamespace(case_id="D001", dut_log_lines="", sta_log_lines="")
    harvest = backend.harvest_strict_for_handle(
        handle,
        tmp_path / "wrong-range-anchor",
        [result],
        {"D001": {"seq_start": 10, "seq_end": 12}},
    )

    assert harvest.status is StrictCaptureHarvestStatus.UNKNOWN
    assert harvest.reason_code == "capture_range_response_invalid"
    assert [action for action, _ in fake.calls] == ["capabilities", "begin", "mark", "range"]
    assert result.dut_log_lines == ""
    assert result.sta_log_lines == ""


def test_uncertain_readonly_range_stops_without_status_or_finish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeClient(range_unknown=True)
    backend = _backend_with_fake(monkeypatch, fake)
    config = _config(tmp_path)
    request = CaptureRolePlanRequest(roles=("dut",))
    plan = project_capture_role_plan(config, request)

    backend.strict_capture_preflight("run-range-unknown", config, request, plan)
    handle = backend.begin_strict_capture("run-range-unknown", config, request, plan)
    result = SimpleNamespace(case_id="D001", dut_log_lines="", sta_log_lines="")
    harvest = backend.harvest_strict_for_handle(
        handle,
        tmp_path / "range-unknown",
        [result],
        {"D001": {"seq_start": 10, "seq_end": 12}},
    )

    assert harvest.status is StrictCaptureHarvestStatus.UNKNOWN
    assert [action for action, _ in fake.calls] == ["capabilities", "begin", "mark", "range"]
    assert result.dut_log_lines == ""
    assert result.sta_log_lines == ""
