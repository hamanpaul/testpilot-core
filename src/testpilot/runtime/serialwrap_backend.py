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
from dataclasses import replace
from pathlib import Path
from typing import Any

from testpilot.runtime import _serialwrap_log
from testpilot.runtime.run_backend import (
    ExportRequest,
    ExportResult,
    RunBackend,
    RunHandle,
)
from testpilot.runtime.serialwrap_log_binding import (
    SerialwrapLogBinding,
    resolve_serialwrap_log_binding,
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
        self._run_bindings: dict[str, SerialwrapLogBinding] = {}
        self._run_owners: dict[str, object | None] = {}

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
            dut_line_map = _serialwrap_log.build_seq_to_line_map(records, com_filter=dut_com)
            sta_line_map = _serialwrap_log.build_seq_to_line_map(records, com_filter=sta_com)
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
