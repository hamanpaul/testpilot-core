from __future__ import annotations

import base64
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from testpilot.runtime import _serialwrap_log
from testpilot.runtime.direct_tty_backend import DirectTtyBackend
from testpilot.runtime.orchestrator_run_backend_compat import OrchestratorRunBackendCompat
from testpilot.runtime.run_backend import ExportRequest
from testpilot.runtime.run_backend import RunHandle
from testpilot.runtime.serialwrap_backend import SerialwrapBackend


def _record(seq: int, com: str, text: str) -> dict[str, Any]:
    return {
        "seq": seq,
        "com": com,
        "payload_b64": base64.b64encode(text.encode()).decode(),
    }


def test_export_serialwrap_logs_exports_complete_current_run_range(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls: list[dict[str, int | None]] = []
    records = [
        _record(101, "COM0", "dut run start\n"),
        _record(102, "COM1", "sta run start\n"),
        _record(130, "COM0", "dut run end\n"),
    ]

    def export_records(
        *,
        from_seq: int = 1,
        to_seq: int | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        calls.append({"from_seq": from_seq, "to_seq": to_seq, "limit": limit})
        return records

    monkeypatch.setattr(_serialwrap_log, "export_records", export_records)

    backend = SerialwrapBackend()
    request = ExportRequest(
        run_id="run-1",
        artifact_dir=tmp_path,
        case_seq_ranges={"case-1": {"seq_start": 101, "seq_end": 130}},
        case_results=[],
        run_seq_start=100,
        run_seq_end=130,
        dut_com="COM0",
        sta_com="COM1",
    )
    result = backend.export_logs(request)

    assert calls == [{"from_seq": 101, "to_seq": 130, "limit": 0}]
    assert Path(result.paths["dut_log_path"]).read_text(encoding="utf-8") == (
        "dut run start\ndut run end\n"
    )
    assert Path(result.paths["sta_log_path"]).read_text(encoding="utf-8") == "sta run start\n"


def test_start_serialwrap_for_run_degrades_on_bind_failure() -> None:
    class Backend:
        def setup_run(self, run_id: str, config: dict[str, Any]) -> RunHandle:
            return RunHandle(
                run_id=run_id,
                meta={"wal_path": "/logs/raw.ndjson", "bind_sessions": True},
            )

        def bind_sessions(self, handle: RunHandle, devices: list[dict[str, Any]]) -> None:
            raise RuntimeError("bind failed")

        def mark_position(self, handle: RunHandle) -> int | None:
            return 321 if handle.meta.get("wal_path") is None else 999

    class Host(OrchestratorRunBackendCompat):
        pass

    host = Host()
    host.run_backend = Backend()
    host._run_handle = None
    host.config = SimpleNamespace(
        raw={"testbed": {}},
        devices={"dut": {"selector": "COM0", "serial_port": "/dev/ttyUSB0"}},
    )

    try:
        result = host._start_serialwrap_for_run("run-1")
    except RuntimeError as exc:  # pragma: no cover - red phase expectation
        raise AssertionError(f"unexpected bind failure escape: {exc}") from exc

    assert result is None
    assert host._run_handle is not None
    assert host._run_handle.meta["wal_path"] is None
    assert host.run_backend.mark_position(host._run_handle) == 321


def test_start_serialwrap_for_run_reraises_unimplemented_backend() -> None:
    class Host(OrchestratorRunBackendCompat):
        pass

    host = Host()
    host.run_backend = DirectTtyBackend()
    host._run_handle = None
    host.config = SimpleNamespace(raw={"testbed": {"run_backend": "direct_tty"}}, devices={})

    with pytest.raises(NotImplementedError, match="DirectTtyBackend\\.setup_run"):
        host._start_serialwrap_for_run("run-1")

    assert host._run_handle is None


def test_start_run_capture_supports_noarg_override() -> None:
    class Host(OrchestratorRunBackendCompat):
        def _start_serialwrap_for_run(self) -> Path:
            return Path("/logs/noarg.ndjson")

    host = Host()

    assert host._start_run_capture("run-1") == Path("/logs/noarg.ndjson")


def test_start_run_capture_reraises_body_typeerror() -> None:
    class Host(OrchestratorRunBackendCompat):
        def _start_serialwrap_for_run(self, run_id: str = "run") -> Path | None:
            del run_id
            raise TypeError("body exploded")

    host = Host()

    with pytest.raises(TypeError, match="body exploded"):
        host._start_run_capture("run-1")


def test_serialwrap_backend_setup_run_degrades_when_start_daemon_fails(monkeypatch) -> None:
    monkeypatch.setattr(_serialwrap_log, "daemon_status", lambda: None)

    def fail_start(*args, **kwargs):
        raise RuntimeError("daemon start failed")

    monkeypatch.setattr(_serialwrap_log, "start_daemon", fail_start)

    backend = SerialwrapBackend()
    handle = backend.setup_run("run-1", {})

    assert handle.run_id == "run-1"
    assert handle.meta.get("bind_sessions") is False
    assert handle.meta.get("wal_path") is None


def test_serialwrap_backend_setup_run_never_rmtrees_wal_when_status_unknown(monkeypatch) -> None:
    """Issue #36 regression.

    daemon_status() returning None most commonly means the client failed to
    reach an *already-running* daemon (not that no daemon exists at all).
    setup_run's degraded-status branch must never delete the WAL directory —
    only start_daemon() then a best-effort RPC wal_reset() (daemon-owned
    rotation with archiving), never a local rmtree.
    """
    monkeypatch.setattr(_serialwrap_log, "daemon_status", lambda: None)

    rmtree_calls: list[Any] = []
    monkeypatch.setattr(
        "shutil.rmtree",
        lambda *args, **kwargs: rmtree_calls.append((args, kwargs)),
    )

    start_daemon_calls: list[Any] = []
    monkeypatch.setattr(
        _serialwrap_log,
        "start_daemon",
        lambda *args, **kwargs: start_daemon_calls.append((args, kwargs)) or {"pid": 1},
    )

    wal_reset_calls: list[Any] = []
    monkeypatch.setattr(
        _serialwrap_log,
        "wal_reset",
        lambda: wal_reset_calls.append(True) or {"previous_seq": 0},
    )
    monkeypatch.setattr(
        _serialwrap_log,
        "get_wal_path",
        lambda: Path("/tmp/serialwrap/wal/raw.wal.ndjson"),
    )

    backend = SerialwrapBackend()
    handle = backend.setup_run("run-1", {})

    assert rmtree_calls == []
    assert len(start_daemon_calls) == 1
    assert len(wal_reset_calls) == 1
    assert handle.run_id == "run-1"
    assert handle.meta.get("bind_sessions") is True
    assert handle.meta.get("wal_path") == "/tmp/serialwrap/wal/raw.wal.ndjson"


def test_serialwrap_backend_setup_run_survives_wal_reset_failure_after_fresh_start(
    monkeypatch,
) -> None:
    """wal_reset() after a fresh start_daemon() is best-effort: an RPC failure
    (daemon still settling) must not abort setup_run or drop the RunHandle."""
    monkeypatch.setattr(_serialwrap_log, "daemon_status", lambda: None)
    monkeypatch.setattr(
        "shutil.rmtree",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("rmtree must never be called from setup_run")
        ),
    )
    monkeypatch.setattr(_serialwrap_log, "start_daemon", lambda *a, **k: {"pid": 1})

    def failing_wal_reset() -> dict[str, Any]:
        raise RuntimeError("daemon not ready for wal reset yet")

    monkeypatch.setattr(_serialwrap_log, "wal_reset", failing_wal_reset)
    monkeypatch.setattr(
        _serialwrap_log,
        "get_wal_path",
        lambda: Path("/tmp/serialwrap/wal/raw.wal.ndjson"),
    )

    backend = SerialwrapBackend()
    handle = backend.setup_run("run-1", {})

    assert handle.run_id == "run-1"
    assert handle.meta.get("bind_sessions") is True
    assert handle.meta.get("wal_path") == "/tmp/serialwrap/wal/raw.wal.ndjson"


def test_serialwrap_backend_mark_position_reads_explicit_wal_tail(
    tmp_path: Path,
    monkeypatch,
) -> None:
    wal = tmp_path / "raw.wal.ndjson"
    wal.write_text(
        "\n".join(
            [
                json.dumps({"seq": 11, "com": "COM0", "payload_b64": "dGVzdA=="}),
                json.dumps({"seq": 42, "com": "COM1", "payload_b64": "dGVzdA=="}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        _serialwrap_log,
        "wal_current_seq",
        lambda: (_ for _ in ()).throw(AssertionError("RPC path should not be used")),
    )

    backend = SerialwrapBackend()
    handle = RunHandle(run_id="run-1", meta={"wal_path": str(wal)})

    assert backend.mark_position(handle) == 42


def test_serialwrap_backend_mark_position_uses_none_fallback(monkeypatch) -> None:
    monkeypatch.setattr(_serialwrap_log, "wal_current_seq", lambda: 77)

    backend = SerialwrapBackend()
    handle = RunHandle(run_id="run-1", meta={"wal_path": None})

    assert backend.mark_position(handle) == 77
