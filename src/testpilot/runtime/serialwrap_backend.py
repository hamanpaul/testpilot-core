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

import logging
from pathlib import Path
from typing import Any

from testpilot.runtime import _serialwrap_log
from testpilot.runtime.run_backend import (
    ExportRequest,
    ExportResult,
    RunBackend,
    RunHandle,
)

log = logging.getLogger(__name__)

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

    # -- RunBackend interface --------------------------------------------------

    def setup_run(self, run_id: str, config: dict[str, Any]) -> RunHandle:
        """Ensure daemon is running and WAL is clean/reset; return a RunHandle."""
        if self._serialwrap_binary:
            _serialwrap_log.configure(binary=self._serialwrap_binary)
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
                started_fresh = True
                _serialwrap_log.clean_wal()
                _serialwrap_log.start_daemon()
                wal_path = _serialwrap_log.get_wal_path()
                log.info("serialwrap daemon started, wal_path=%s", wal_path)
            return RunHandle(
                run_id=run_id,
                meta={
                    "wal_path": str(wal_path) if wal_path else None,
                    "bind_sessions": started_fresh,
                },
            )
        except Exception:
            log.warning("serialwrap setup_run failed; logs will be unavailable", exc_info=True)
            return RunHandle(run_id=run_id, meta={"bind_sessions": False})

    def bind_sessions(
        self,
        handle: RunHandle,
        devices: list[dict[str, Any]],
    ) -> None:
        """Bind serialwrap sessions to the listed devices."""
        _serialwrap_log.setup_sessions(devices)
        log.debug("bind_sessions: bound %d device(s) for run %s", len(devices), handle.run_id)

    def mark_position(self, handle: RunHandle) -> int | None:
        """Return the current WAL seq number."""
        try:
            wal_path = handle.meta.get("wal_path")
            return _serialwrap_log.get_current_seq(Path(wal_path) if wal_path else None)
        except Exception:
            log.debug("mark_position failed for run %s", handle.run_id)
            return None

    def export_logs(self, request: ExportRequest) -> ExportResult:
        """Export WAL records, decode DUT/STA logs, and annotate case results.

        Replicates the behavior of ``Orchestrator._export_serialwrap_logs``
        verbatim; the log sequence / line-range semantics are preserved.
        """
        from_seq = (
            1 if request.run_seq_start is None
            else max(int(request.run_seq_start) + 1, 1)
        )
        records = _serialwrap_log.export_records(
            from_seq=from_seq,
            to_seq=request.run_seq_end,
            limit=0,
        )
        if not records:
            return ExportResult(paths={})

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

        dut_line_map = _serialwrap_log.build_seq_to_line_map(records, com_filter=dut_com)
        sta_line_map = _serialwrap_log.build_seq_to_line_map(records, com_filter=sta_com)

        for cr in request.case_results:
            seq_range = request.case_seq_ranges.get(cr.case_id)
            if not seq_range:
                continue
            s, e = seq_range.get("seq_start"), seq_range.get("seq_end")
            cr.dut_log_lines = _serialwrap_log.seq_range_to_line_range(s, e, dut_line_map)
            cr.sta_log_lines = _serialwrap_log.seq_range_to_line_range(s, e, sta_line_map)

        log.info("serialwrap logs saved: %s, %s", dut_log_path, sta_log_path)
        return ExportResult(paths={
            "dut_log_path": str(dut_log_path),
            "sta_log_path": str(sta_log_path),
        })

    def teardown_run(self, handle: RunHandle) -> None:
        """Keep daemon alive for console coexistence (no-op intentionally)."""
        log.debug("teardown_run: daemon kept alive for run %s", handle.run_id)
