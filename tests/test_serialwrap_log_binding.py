from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from testpilot.core.azure_auth import AzureAgentRuntime, AzureAgentState, AzureAgentStatus
from testpilot.core.orchestrator import Orchestrator
from testpilot.runtime import _serialwrap_log
from testpilot.runtime.run_backend import ExportRequest
from testpilot.runtime.serialwrap_backend import SerialwrapBackend
from testpilot.runtime.serialwrap_log_binding import resolve_serialwrap_log_binding
from testpilot.transport.serialwrap import SerialWrapTransport


def _orchestrator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    dut_socket: str,
    sta_socket: str,
) -> tuple[Orchestrator, Path]:
    monkeypatch.delenv("SERIALWRAP_BIN", raising=False)
    monkeypatch.delenv("SERIALWRAP_ENDPOINT", raising=False)
    binary = tmp_path / "serialwrap-fake"
    binary.write_text("fake cli path", encoding="utf-8")
    config_path = tmp_path / "testbed.yaml"
    config_path.write_text(
        "\n".join(
            [
                "testbed:",
                "  name: fake-binding-test",
                "  devices:",
                "    DUT:",
                "      transport: serial",
                "      binary: " + str(binary),
                "      socket: " + dut_socket,
                "      selector: COM0",
                "    STA:",
                "      transport: serialwrap",
                "      binary: " + str(binary),
                "      socket: " + sta_socket,
                "      selector: COM1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    orchestrator = Orchestrator(
        config_path=config_path,
        agent_runtime=AzureAgentRuntime(
            AzureAgentStatus(AzureAgentState.DISABLED_NO_KEY)
        ),
    )
    return orchestrator, binary


def _setup_bound_backend(
    backend: SerialwrapBackend,
    run_id: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Any:
    binary = tmp_path / f"{run_id}-serialwrap"
    binary.write_text("fake", encoding="utf-8")
    monkeypatch.setattr(_serialwrap_log, "daemon_status", lambda: {"ok": True, "pid": 123})
    monkeypatch.setattr(_serialwrap_log, "wal_reset", lambda: {"ok": True})
    monkeypatch.setattr(
        _serialwrap_log,
        "get_wal_path",
        lambda: Path("/tmp/serialwrap/raw.wal.ndjson"),
    )
    return backend.setup_run(
        run_id,
        {
            "devices": {
                "DUT": {
                    "transport": "serialwrap",
                    "binary": str(binary),
                    "socket": str(tmp_path / f"{run_id}.sock"),
                    "selector": "COM0",
                }
            }
        },
    )


def test_orchestrator_binds_logger_to_unanimous_device_binary_and_socket(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    socket = str(tmp_path / "serialwrap.sock")
    orchestrator, binary = _orchestrator(
        tmp_path, monkeypatch, dut_socket=socket, sta_socket=socket
    )
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> SimpleNamespace:
        del kwargs
        calls.append(cmd)
        if cmd[-2:] == ["daemon", "status"]:
            payload = {"ok": True, "pid": 123, "wal_path": "/wal/raw.wal.ndjson"}
        elif cmd[-2:] == ["wal", "reset"]:
            payload = {"ok": True, "previous_seq": 0}
        else:  # pragma: no cover - unexpected command guard
            raise AssertionError(cmd)
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(_serialwrap_log.subprocess, "run", fake_run)

    orchestrator._start_serialwrap_for_run("run-bind")

    assert len(calls) == 3
    assert all(call[:3] == [str(binary), "--socket", socket] for call in calls)
    assert [call[3:] for call in calls] == [
        ["daemon", "status"],
        ["wal", "reset"],
        ["daemon", "status"],
    ]
    binding = orchestrator._run_handle.meta["serialwrap_binding"]
    assert binding["enabled"] is True
    assert binding["binary_source"] == "device_config"
    assert binding["socket_source"] == "device_config"
    assert binding["device_count"] == 2
    orchestrator._stop_serialwrap()


def test_orchestrator_disables_capture_for_mismatched_device_endpoints(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orchestrator, _ = _orchestrator(
        tmp_path,
        monkeypatch,
        dut_socket=str(tmp_path / "dut.sock"),
        sta_socket=str(tmp_path / "sta.sock"),
    )
    calls: list[list[str]] = []
    monkeypatch.setattr(
        _serialwrap_log.subprocess,
        "run",
        lambda cmd, **kwargs: calls.append(list(cmd)),
    )

    assert orchestrator._start_serialwrap_for_run("run-mismatch") is None

    handle = orchestrator._run_handle
    assert handle is not None
    binding = handle.meta["serialwrap_binding"]
    assert binding["enabled"] is False
    assert binding["reason"] == "serialwrap device endpoints differ"
    assert handle.meta["bind_sessions"] is False
    assert calls == []
    assert orchestrator.run_backend.mark_position(handle) is None
    orchestrator._stop_serialwrap()


def test_orchestrator_accepts_flat_testbed_config_for_run_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SERIALWRAP_BIN", raising=False)
    monkeypatch.delenv("SERIALWRAP_ENDPOINT", raising=False)
    binary = tmp_path / "serialwrap-flat"
    binary.write_text("fake cli path", encoding="utf-8")
    socket = str(tmp_path / "serialwrap.sock")
    config_path = tmp_path / "flat-testbed.yaml"
    config_path.write_text(
        "\n".join(
            [
                "name: flat-binding-test",
                "run_backend: serialwrap",
                "serialwrap_binary: " + str(binary),
                "devices:",
                "  DUT:",
                "    transport: serial",
                "    binary: " + str(binary),
                "    socket: " + socket,
                "    selector: COM0",
                "  STA:",
                "    transport: serialwrap",
                "    binary: " + str(binary),
                "    socket: " + socket,
                "    selector: COM1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    orchestrator = Orchestrator(
        config_path=config_path,
        agent_runtime=AzureAgentRuntime(
            AzureAgentStatus(AzureAgentState.DISABLED_NO_KEY)
        ),
    )
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> SimpleNamespace:
        del kwargs
        calls.append(cmd)
        if cmd[-2:] == ["daemon", "status"]:
            payload = {"ok": True, "pid": 123, "wal_path": "/wal/raw.wal.ndjson"}
        elif cmd[-2:] == ["wal", "reset"]:
            payload = {"ok": True, "previous_seq": 0}
        else:  # pragma: no cover - unexpected command guard
            raise AssertionError(cmd)
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(_serialwrap_log.subprocess, "run", fake_run)

    orchestrator._start_serialwrap_for_run("run-flat")

    assert orchestrator.run_backend._serialwrap_binary == str(binary)
    assert len(calls) == 3
    assert all(call[:3] == [str(binary), "--socket", socket] for call in calls)
    assert orchestrator._run_handle.meta["serialwrap_binding"]["enabled"] is True
    orchestrator._stop_serialwrap()


def test_tcp_environment_endpoint_does_not_alias_a_unix_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SERIALWRAP_BIN", raising=False)
    monkeypatch.setenv("SERIALWRAP_ENDPOINT", "tcp://127.0.0.1:48700")
    binary = tmp_path / "serialwrap-fake"
    binary.write_text("fake", encoding="utf-8")
    # This path is the accidental filesystem normalization of the TCP URI.
    # The DUT explicitly targets a Unix socket while STA inherits the TCP URI.
    colliding_unix_path = str(Path.cwd() / "tcp:" / "127.0.0.1:48700")

    binding = resolve_serialwrap_log_binding(
        {
            "devices": {
                "DUT": {
                    "transport": "serial",
                    "binary": str(binary),
                    "socket": colliding_unix_path,
                },
                "STA": {"transport": "serialwrap", "binary": str(binary)},
            }
        }
    )

    assert binding.enabled is False
    assert binding.reason == "serialwrap device endpoints differ"


def test_overlapping_backends_cannot_retarget_or_release_active_logger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SERIALWRAP_BIN", raising=False)
    monkeypatch.delenv("SERIALWRAP_ENDPOINT", raising=False)
    binary_a = tmp_path / "serialwrap-a"
    binary_b = tmp_path / "serialwrap-b"
    binary_a.write_text("fake A", encoding="utf-8")
    binary_b.write_text("fake B", encoding="utf-8")
    socket_a = str(tmp_path / "a.sock")
    socket_b = str(tmp_path / "b.sock")
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> SimpleNamespace:
        del kwargs
        calls.append(cmd)
        if cmd[-2:] == ["daemon", "status"]:
            payload = {"ok": True, "pid": 123, "wal_path": "/wal/raw.wal.ndjson"}
        elif cmd[-2:] == ["wal", "reset"]:
            payload = {"ok": True, "previous_seq": 0}
        elif cmd[-2:] == ["wal", "current-seq"]:
            payload = {"ok": True, "seq": 55}
        else:  # pragma: no cover - unexpected command guard
            raise AssertionError(cmd)
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(_serialwrap_log.subprocess, "run", fake_run)
    config_a = {
        "devices": {
            "DUT": {
                "transport": "serialwrap",
                "binary": str(binary_a),
                "socket": socket_a,
                "selector": "COM0",
            }
        }
    }
    config_b = {
        "devices": {
            "DUT": {
                "transport": "serialwrap",
                "binary": str(binary_b),
                "socket": socket_b,
                "selector": "COM0",
            }
        }
    }
    backend_a = SerialwrapBackend()
    backend_b = SerialwrapBackend()

    handle_a = backend_a.setup_run("run-a", config_a)
    calls_after_a_setup = len(calls)
    handle_b = backend_b.setup_run("run-b", config_b)

    assert calls_after_a_setup == 3
    assert len(calls) == calls_after_a_setup
    assert handle_b.meta["serialwrap_binding"]["enabled"] is False
    assert "already owned" in handle_b.meta["serialwrap_binding"]["reason"]
    assert backend_b.mark_position(handle_b) is None
    assert backend_a.mark_position(handle_a) == 55
    blocked_result = backend_b.export_logs(
        ExportRequest(
            run_id="run-b",
            artifact_dir=tmp_path / "blocked-artifacts",
            case_seq_ranges={},
            run_seq_start=0,
            run_seq_end=10,
        )
    )
    blocked_manifest = json.loads(
        Path(blocked_result.paths["wal_export_path"]).read_text(encoding="utf-8")
    )
    assert blocked_manifest["incomplete_reasons"] == ["logging_disabled"]
    backend_b.teardown_run(handle_b)
    assert backend_a.mark_position(handle_a) == 55
    assert all(call[:3] == [str(binary_a), "--socket", socket_a] for call in calls)

    backend_a.teardown_run(handle_a)
    handle_b_retry = backend_b.setup_run("run-b-retry", config_b)

    assert handle_b_retry.meta["serialwrap_binding"]["enabled"] is True
    assert all(
        call[:3] == [str(binary_b), "--socket", socket_b]
        for call in calls[calls_after_a_setup + 2:]
    )
    backend_b.teardown_run(handle_b_retry)


def test_missing_final_marker_exports_unknown_boundary_without_wal_rpc(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SERIALWRAP_BIN", raising=False)
    monkeypatch.delenv("SERIALWRAP_ENDPOINT", raising=False)
    binary = tmp_path / "serialwrap-fake"
    binary.write_text("fake", encoding="utf-8")
    socket = str(tmp_path / "serialwrap.sock")

    def fake_run(cmd: list[str], **kwargs: Any) -> SimpleNamespace:
        del kwargs
        if cmd[-2:] == ["daemon", "status"]:
            payload = {"ok": True, "pid": 123, "wal_path": "/wal/raw.wal.ndjson"}
        elif cmd[-2:] == ["wal", "reset"]:
            payload = {"ok": True, "previous_seq": 0}
        else:  # pragma: no cover - unexpected command guard
            raise AssertionError(cmd)
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(_serialwrap_log.subprocess, "run", fake_run)
    monkeypatch.setattr(
        _serialwrap_log,
        "export_records_with_metadata",
        lambda **kwargs: pytest.fail("unknown run boundary must not trigger WAL export"),
    )
    backend = SerialwrapBackend()
    handle = backend.setup_run(
        "run-no-end",
        {
            "devices": {
                "DUT": {
                    "transport": "serialwrap",
                    "binary": str(binary),
                    "socket": socket,
                    "selector": "COM0",
                }
            }
        },
    )
    case_result = SimpleNamespace(case_id="D001", dut_log_lines="", sta_log_lines="")
    result = backend.export_logs(
        ExportRequest(
            run_id="run-no-end",
            artifact_dir=tmp_path / "artifacts",
            case_seq_ranges={"D001": {"seq_start": 1, "seq_end": 2}},
            case_results=[case_result],
            run_seq_start=0,
            run_seq_end=None,
        )
    )

    manifest = json.loads(Path(result.paths["wal_export_path"]).read_text(encoding="utf-8"))
    assert manifest["complete"] is False
    assert manifest["requested_to_seq_inclusive"] is None
    assert manifest["incomplete_reasons"] == ["end_marker_missing"]
    assert case_result.dut_log_lines == ""
    assert case_result.sta_log_lines == ""
    backend.teardown_run(handle)


def test_backend_binary_conflict_with_device_binary_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SERIALWRAP_BIN", raising=False)
    device_binary = tmp_path / "device-cli"
    backend_binary = tmp_path / "backend-cli"
    device_binary.write_text("device", encoding="utf-8")
    backend_binary.write_text("backend", encoding="utf-8")

    binding = resolve_serialwrap_log_binding(
        {
            "devices": {
                "DUT": {"transport": "serial", "binary": str(device_binary)},
                "STA": {"transport": "serial", "binary": str(device_binary)},
            }
        },
        backend_binary=str(backend_binary),
    )

    assert binding.enabled is False
    assert binding.reason == "run backend binary conflicts with serialwrap device binary"


def test_no_selected_serial_device_disables_logger_before_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(
        _serialwrap_log.subprocess,
        "run",
        lambda cmd, **kwargs: calls.append(list(cmd)),
    )
    backend = SerialwrapBackend()

    handle = backend.setup_run("run-no-device", {})

    assert handle.meta["serialwrap_binding"]["enabled"] is False
    assert handle.meta["serialwrap_binding"]["reason"] == (
        "no serialwrap DUT/STA transport is configured"
    )
    assert handle.meta["bind_sessions"] is False
    assert calls == []
    backend.teardown_run(handle)


def test_environment_binary_and_endpoint_override_both_transport_configs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device_binary_a = tmp_path / "device-a"
    device_binary_b = tmp_path / "device-b"
    env_binary = tmp_path / "env-cli"
    for path in (device_binary_a, device_binary_b, env_binary):
        path.write_text("fake", encoding="utf-8")
    env_socket = str(tmp_path / "shared.sock")
    monkeypatch.setenv("SERIALWRAP_BIN", str(env_binary))
    monkeypatch.setenv("SERIALWRAP_ENDPOINT", f"unix://{env_socket}")

    config = {
        "devices": {
            "DUT": {
                "transport": "serial",
                "binary": str(device_binary_a),
                "socket": env_socket,
            },
            "STA": {
                "transport": "serialwrap",
                "binary": str(device_binary_b),
            },
        }
    }
    binding = resolve_serialwrap_log_binding(
        config,
        backend_binary=str(device_binary_b),
    )
    dut_transport = SerialWrapTransport(config["devices"]["DUT"])
    sta_transport = SerialWrapTransport(config["devices"]["STA"])

    assert binding.enabled is True
    assert binding.binary == str(env_binary)
    assert binding.binary_source == "SERIALWRAP_BIN"
    assert binding.socket == env_socket
    assert binding.socket_source == "device_config"
    assert dut_transport._build_cli(["daemon", "status"]) == [
        str(env_binary), "--socket", env_socket, "daemon", "status"
    ]
    assert sta_transport._build_cli(["daemon", "status"]) == [
        str(env_binary), "daemon", "status"
    ]


def test_export_records_paginates_with_fixed_inclusive_end_and_keeps_loss_markers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> SimpleNamespace:
        del kwargs
        calls.append(cmd)
        from_seq = int(cmd[cmd.index("--from-seq") + 1])
        limit = int(cmd[cmd.index("--limit") + 1])
        assert cmd[cmd.index("--to-seq") + 1] == "2005"
        records = [
            {"seq": seq, "loss_flag": seq == 1001, "payload_b64": ""}
            for seq in range(from_seq + 1, min(from_seq + limit, 2005) + 1)
        ]
        payload = {
            "ok": True,
            "records": records,
            "available_from_seq": 1,
            "rotated_out": False,
        }
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(_serialwrap_log.subprocess, "run", fake_run)
    monkeypatch.setattr(_serialwrap_log, "_configured_bin", "/fake/serialwrap")
    monkeypatch.setattr(_serialwrap_log, "_configured_socket", None, raising=False)
    monkeypatch.setattr(_serialwrap_log, "_configured_enabled", True, raising=False)
    monkeypatch.setattr(_serialwrap_log, "_resolve_bin", lambda: "/fake/serialwrap")

    result = _serialwrap_log.export_records_with_metadata(
        from_seq=0, to_seq=2005, page_size=1000, max_records=3000
    )

    assert [
        (int(call[call.index("--from-seq") + 1]), int(call[call.index("--limit") + 1]))
        for call in calls
    ] == [(0, 1000), (999, 1000), (1998, 1000), (0, 1), (2004, 1)]
    assert all(
        call[call.index("--to-seq") + 1] == "2005"
        for call in calls
    )
    assert [record["seq"] for record in result.records] == list(range(1, 2006))
    assert result.records[1000]["loss_flag"] is True
    assert result.complete is False
    assert "loss_flag" in result.incomplete_reasons
    metadata = result.to_dict()
    assert metadata["continuity_kind"] == "content_anchor"
    assert metadata["generation_available"] is False
    assert "no WAL generation token" in metadata["continuity_note"]


def test_export_records_marks_sequence_holes_rotations_and_bound_exhaustion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> SimpleNamespace:
        del kwargs
        calls.append(cmd)
        from_seq = int(cmd[cmd.index("--from-seq") + 1])
        limit = int(cmd[cmd.index("--limit") + 1])
        records = [
            {"seq": seq, "loss_flag": False}
            for seq in range(1, 11)
            if seq != 2 and seq > from_seq
        ][:limit]
        payload = {
            "ok": True,
            "records": records,
            "available_from_seq": 2,
            "rotated_out": from_seq == 0,
        }
        return SimpleNamespace(returncode=0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(_serialwrap_log.subprocess, "run", fake_run)
    monkeypatch.setattr(_serialwrap_log, "_configured_bin", "/fake/serialwrap")
    monkeypatch.setattr(_serialwrap_log, "_configured_enabled", True)
    monkeypatch.setattr(_serialwrap_log, "_configured_reason", "")
    monkeypatch.setattr(_serialwrap_log, "_resolve_bin", lambda: "/fake/serialwrap")

    result = _serialwrap_log.export_records_with_metadata(
        from_seq=0, to_seq=10, page_size=3, max_records=4
    )

    assert len(calls) == 3
    assert all(call[call.index("--to-seq") + 1] == "10" for call in calls)
    assert result.complete is False
    assert {"rotated_out", "sequence_gap", "record_limit"}.issubset(
        set(result.incomplete_reasons)
    )
    assert result.requested_to_seq == 10


def _wal_row(seq: int, generation: str) -> dict[str, Any]:
    return {
        "seq": seq,
        "mono_ts_ns": seq * 10 + (0 if generation == "A" else 1000),
        "wall_ts": f"2026-10-03T00:00:{seq:02d}+00:00",
        "com": "COM0",
        "dir": "rx",
        "source": "reader",
        "cmd_id": None,
        "len": 1,
        "crc32": "00000000",
        "payload_b64": "eA==",
        "loss_flag": False,
        "meta": {"generation": generation},
    }


def _set_export_cli(monkeypatch: pytest.MonkeyPatch, fake_run: Any) -> None:
    monkeypatch.setattr(_serialwrap_log, "_run_sw", fake_run)
    monkeypatch.setattr(_serialwrap_log, "_configured_bin", "/fake/serialwrap")
    monkeypatch.setattr(_serialwrap_log, "_configured_socket", None, raising=False)
    monkeypatch.setattr(_serialwrap_log, "_configured_enabled", True, raising=False)
    monkeypatch.setattr(_serialwrap_log, "_configured_reason", "", raising=False)
    monkeypatch.setattr(_serialwrap_log, "_resolve_bin", lambda: "/fake/serialwrap")


def test_export_records_rejects_reset_and_regrowth_between_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page_calls = 0

    def fake_run(cmd: list[str], **kwargs: Any) -> dict[str, Any]:
        nonlocal page_calls
        del kwargs
        from_seq = int(cmd[cmd.index("--from-seq") + 1])
        to_seq = int(cmd[cmd.index("--to-seq") + 1])
        limit = int(cmd[cmd.index("--limit") + 1])
        if limit > 1:
            page_calls += 1
            generation = "A" if page_calls == 1 else "B"
        else:
            generation = "B" if page_calls > 1 else "A"
        rows = [
            _wal_row(seq, generation)
            for seq in range(from_seq + 1, min(from_seq + limit, to_seq) + 1)
        ]
        return {"ok": True, "records": rows, "available_from_seq": 1, "rotated_out": False}

    _set_export_cli(monkeypatch, fake_run)
    result = _serialwrap_log.export_records_with_metadata(
        from_seq=0, to_seq=4, page_size=2, max_records=10
    )

    assert [row["seq"] for row in result.records] == [1, 2]
    assert result.complete is False
    assert "page_overlap_anchor_changed" in result.incomplete_reasons
    assert result.to_dict()["generation_available"] is False


def test_export_records_rechecks_first_and_end_anchors_after_final_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page_calls = 0

    def fake_run(cmd: list[str], **kwargs: Any) -> dict[str, Any]:
        nonlocal page_calls
        del kwargs
        from_seq = int(cmd[cmd.index("--from-seq") + 1])
        to_seq = int(cmd[cmd.index("--to-seq") + 1])
        limit = int(cmd[cmd.index("--limit") + 1])
        if limit > 1:
            page_calls += 1
            generation = "A"
        else:
            generation = "B" if page_calls >= 2 else "A"
        rows = [
            _wal_row(seq, generation)
            for seq in range(from_seq + 1, min(from_seq + limit, to_seq) + 1)
        ]
        return {"ok": True, "records": rows, "available_from_seq": 1, "rotated_out": False}

    _set_export_cli(monkeypatch, fake_run)
    result = _serialwrap_log.export_records_with_metadata(
        from_seq=0, to_seq=4, page_size=2, max_records=10
    )

    assert [row["seq"] for row in result.records] == [1, 2, 3, 4]
    assert result.complete is False
    assert {"range_first_anchor_changed", "range_end_anchor_changed"}.issubset(
        set(result.incomplete_reasons)
    )


def test_export_records_marks_pruned_first_anchor_incomplete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(cmd: list[str], **kwargs: Any) -> dict[str, Any]:
        del kwargs
        from_seq = int(cmd[cmd.index("--from-seq") + 1])
        to_seq = int(cmd[cmd.index("--to-seq") + 1])
        limit = int(cmd[cmd.index("--limit") + 1])
        if limit == 1 and from_seq == 0:
            rows: list[dict[str, Any]] = []
        else:
            rows = [
                _wal_row(seq, "A")
                for seq in range(from_seq + 1, min(from_seq + limit, to_seq) + 1)
            ]
        return {"ok": True, "records": rows, "available_from_seq": 1, "rotated_out": False}

    _set_export_cli(monkeypatch, fake_run)
    result = _serialwrap_log.export_records_with_metadata(
        from_seq=0, to_seq=4, page_size=2, max_records=10
    )

    assert result.complete is False
    assert "range_first_anchor_missing" in result.incomplete_reasons


def test_export_records_marks_missing_page_overlap_anchor_incomplete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page_calls = 0

    def fake_run(cmd: list[str], **kwargs: Any) -> dict[str, Any]:
        nonlocal page_calls
        del kwargs
        from_seq = int(cmd[cmd.index("--from-seq") + 1])
        to_seq = int(cmd[cmd.index("--to-seq") + 1])
        limit = int(cmd[cmd.index("--limit") + 1])
        page_calls += int(limit > 1)
        # Simulate the previous overlap row being pruned before page two.
        rows = [
            _wal_row(seq, "A")
            for seq in range(from_seq + 1, min(from_seq + limit, to_seq) + 1)
            if not (page_calls == 2 and seq == 2)
        ]
        return {"ok": True, "records": rows, "available_from_seq": 1, "rotated_out": False}

    _set_export_cli(monkeypatch, fake_run)
    result = _serialwrap_log.export_records_with_metadata(
        from_seq=0, to_seq=4, page_size=2, max_records=10
    )

    assert result.complete is False
    assert "page_overlap_anchor_missing" in result.incomplete_reasons


@pytest.mark.parametrize("page_size", [1, 2])
def test_export_records_accepts_append_after_fixed_end_anchor(
    monkeypatch: pytest.MonkeyPatch,
    page_size: int,
) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> dict[str, Any]:
        del kwargs
        calls.append(cmd)
        from_seq = int(cmd[cmd.index("--from-seq") + 1])
        to_seq = int(cmd[cmd.index("--to-seq") + 1])
        limit = int(cmd[cmd.index("--limit") + 1])
        # The current WAL has appended 5 and 6 since the fixed range was chosen,
        # but wal.range must continue to return only the captured 1..4 interval.
        current_rows = [_wal_row(seq, "A") for seq in range(1, 7)]
        rows = [
            row
            for row in current_rows
            if from_seq < row["seq"] <= to_seq
        ][:limit]
        return {"ok": True, "records": rows, "available_from_seq": 1, "rotated_out": False}

    _set_export_cli(monkeypatch, fake_run)
    result = _serialwrap_log.export_records_with_metadata(
        from_seq=0, to_seq=4, page_size=page_size, max_records=10
    )

    assert [row["seq"] for row in result.records] == [1, 2, 3, 4]
    assert result.complete is True
    assert result.to_dict()["continuity_kind"] == "content_anchor"
    assert all(call[call.index("--to-seq") + 1] == "4" for call in calls)


def test_export_records_rejects_rpc_error_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        _serialwrap_log,
        "_run_sw",
        lambda *args, **kwargs: {"ok": False, "error_code": "WAL_MISSING"},
    )

    with pytest.raises(RuntimeError, match="WAL_MISSING"):
        _serialwrap_log.export_records_with_metadata(from_seq=0, to_seq=1)


def test_export_records_rejects_response_without_explicit_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        _serialwrap_log,
        "_run_sw",
        lambda *args, **kwargs: {"records": [{"seq": 1}]},
    )

    with pytest.raises(RuntimeError, match="INVALID_RESPONSE"):
        _serialwrap_log.export_records_with_metadata(from_seq=0, to_seq=1)


def test_export_records_rejects_server_page_over_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: Any) -> dict[str, Any]:
        del kwargs
        calls.append(cmd)
        return {
            "ok": True,
            "records": [{"seq": seq} for seq in range(1, 5)],
        }

    monkeypatch.setattr(_serialwrap_log, "_run_sw", fake_run)
    result = _serialwrap_log.export_records_with_metadata(
        from_seq=0, to_seq=4, page_size=3, max_records=10
    )

    assert len(calls) == 1
    assert result.records == []
    assert result.complete is False
    assert "page_limit_exceeded" in result.incomplete_reasons


@pytest.mark.parametrize(
    "payload",
    [
        {"ok": False, "error_code": "WAL_UNAVAILABLE"},
        {"ok": True},
        {"seq": 1},
        {"ok": True, "seq": "0"},
        {"ok": True, "seq": True},
    ],
)
def test_current_seq_rejects_failed_or_malformed_rpc_without_zero_fallback(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, Any],
) -> None:
    monkeypatch.setattr(_serialwrap_log, "_run_sw", lambda *args, **kwargs: payload)

    with pytest.raises(RuntimeError):
        _serialwrap_log.wal_current_seq()


def test_current_seq_preserves_legitimate_zero_from_successful_rpc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        _serialwrap_log,
        "_run_sw",
        lambda *args, **kwargs: {"ok": True, "seq": 0},
    )

    assert _serialwrap_log.wal_current_seq() == 0


def test_incomplete_export_preserves_raw_loss_record_without_case_line_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = {"seq": 1, "com": "COM0", "payload_b64": "bG9zcw==", "loss_flag": True}
    monkeypatch.setattr(
        _serialwrap_log,
        "export_records_with_metadata",
        lambda **kwargs: SimpleNamespace(
            records=[record],
            complete=False,
            incomplete_reasons=["loss_flag"],
            missing_sequence_ranges=[],
            to_dict=lambda: {
                "complete": False,
                "incomplete_reasons": ["loss_flag"],
                "records": [record],
            },
        ),
    )
    case_result = SimpleNamespace(case_id="D001", dut_log_lines="", sta_log_lines="")
    backend = SerialwrapBackend()
    handle = _setup_bound_backend(backend, "run-loss", tmp_path, monkeypatch)

    result = backend.export_logs(
        ExportRequest(
            run_id="run-loss",
            artifact_dir=tmp_path,
            case_seq_ranges={"D001": {"seq_start": 1, "seq_end": 1}},
            case_results=[case_result],
            run_seq_start=0,
            run_seq_end=1,
        )
    )

    saved = json.loads(Path(result.paths["wal_export_path"]).read_text(encoding="utf-8"))
    assert saved["complete"] is False
    assert saved["records"][0]["loss_flag"] is True
    assert case_result.dut_log_lines == ""
    assert case_result.sta_log_lines == ""
    backend.teardown_run(handle)


def test_export_rpc_failure_writes_incomplete_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_export(**kwargs: Any) -> None:
        del kwargs
        raise TimeoutError("remote wrapper unavailable")

    monkeypatch.setattr(_serialwrap_log, "export_records_with_metadata", fail_export)
    backend = SerialwrapBackend()
    handle = _setup_bound_backend(backend, "run-export-error", tmp_path, monkeypatch)

    result = backend.export_logs(
        ExportRequest(
            run_id="run-export-error",
            artifact_dir=tmp_path,
            case_seq_ranges={},
            run_seq_start=12,
            run_seq_end=34,
        )
    )

    saved = json.loads(Path(result.paths["wal_export_path"]).read_text(encoding="utf-8"))
    assert saved["complete"] is False
    assert saved["incomplete_reasons"] == ["export_error"]
    assert saved["error_type"] == "TimeoutError"
    assert saved["requested_from_seq_exclusive"] == 12
    assert saved["requested_to_seq_inclusive"] == 34
    backend.teardown_run(handle)


def test_backend_socket_conflict_writes_disabled_export_provenance_without_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binary = tmp_path / "serialwrap-fake"
    binary.write_text("fake cli path", encoding="utf-8")
    monkeypatch.setattr(
        _serialwrap_log.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("ambiguous target must not call serialwrap")
        ),
    )
    backend = SerialwrapBackend()
    handle = backend.setup_run(
        "run-mismatch",
        {
            "devices": {
                "DUT": {"transport": "serial", "binary": str(binary), "socket": "/tmp/dut.sock"},
                "STA": {"transport": "serial", "binary": str(binary), "socket": "/tmp/sta.sock"},
            }
        },
    )

    assert handle.meta["serialwrap_binding"]["enabled"] is False
    result = backend.export_logs(
        ExportRequest(
            run_id="run-mismatch",
            artifact_dir=tmp_path / "artifacts",
            case_seq_ranges={},
            run_seq_start=12,
            run_seq_end=34,
        )
    )

    saved = json.loads(Path(result.paths["wal_export_path"]).read_text(encoding="utf-8"))
    assert saved["complete"] is False
    assert saved["requested_from_seq_exclusive"] == 12
    assert saved["requested_to_seq_inclusive"] == 34
    assert saved["incomplete_reasons"] == ["logging_disabled"]
    assert saved["binding"]["reason"] == "serialwrap device endpoints differ"
    backend.teardown_run(handle)
