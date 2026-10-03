"""Serialwrap RAW log capture and decoding — backend-private helper."""

from __future__ import annotations

import base64
import json
import logging
import subprocess
import os
import time
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any

from testpilot.serialwrap_binary import resolve_serialwrap_binary

logger = logging.getLogger(__name__)

# get_wal_path() 的 best-effort 顯示用 fallback（daemon_status() 拿不到
# wal_path 時才會用到）。這**不是**刪除/清理操作的目標路徑 —— #36 之後
# WAL 目錄的清理/輪替只能透過 daemon 自己的 RPC `wal reset` 進行，本檔
# 不再對任何 WAL 路徑做本地 rmtree。
_WAL_PATH_FALLBACK = Path("/tmp/serialwrap/wal/raw.wal.ndjson")

_configured_bin: str | None = None
_configured_socket: str | None = None
_configured_enabled = True
_configured_reason = ""
_configured_owner: object | None = None
_configured_lock = RLock()


def configure(
    *,
    binary: str | None,
    socket: str | None,
    owner: object,
    enabled: bool = True,
    reason: str = "",
) -> bool:
    """Set the run logger target unless another run currently owns it."""
    global _configured_bin, _configured_socket, _configured_enabled, _configured_reason, _configured_owner  # noqa: PLW0603
    with _configured_lock:
        if _configured_owner is not None and _configured_owner is not owner:
            return False
        _configured_bin = binary
        _configured_socket = socket
        _configured_enabled = bool(enabled)
        _configured_reason = str(reason)
        _configured_owner = owner
        return True


def release(owner: object) -> bool:
    """Clear the run target only when called by its current owner."""
    global _configured_bin, _configured_socket, _configured_enabled, _configured_reason, _configured_owner  # noqa: PLW0603
    with _configured_lock:
        if _configured_owner is not owner:
            return False
        _configured_bin = None
        _configured_socket = None
        _configured_enabled = False
        _configured_reason = "run capture is closed"
        _configured_owner = None
        return True


def _cli_prefix() -> list[str]:
    with _configured_lock:
        if not _configured_enabled:
            raise RuntimeError(
                "serialwrap run logging is disabled: "
                + (_configured_reason or "device target could not be resolved")
            )
        command = [_resolve_bin()]
        if _configured_socket:
            command.extend(["--socket", _configured_socket])
        return command


def _resolve_bin() -> str:
    """Resolve serialwrap binary: ENV → configure() value → PATH."""
    with _configured_lock:
        if not _configured_enabled:
            raise RuntimeError(
                "serialwrap run logging is disabled: "
                + (_configured_reason or "device target could not be resolved")
            )
        return resolve_serialwrap_binary(
            _configured_bin,
            config_label="'serialwrap_binary' in testbed config",
        )


def _run_sw(args: list[str], timeout: float = 10.0) -> dict[str, Any]:
    """Run a serialwrap CLI command and return parsed JSON response."""
    cmd = [*_cli_prefix(), *args]
    # serialwrap always emits UTF-8; never fall back to the host locale (#51).
    completed = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
        check=False, timeout=timeout,
    )
    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        stdout_trimmed = (completed.stdout or "").strip()[:500]
        suffix = f" | rc={completed.returncode}"
        if stdout_trimmed:
            suffix += f" | stdout={stdout_trimmed}"
        raise RuntimeError(f"serialwrap failed: {' '.join(args)}: {stderr}{suffix}")
    stdout = (completed.stdout or "").strip()
    if not stdout:
        raise RuntimeError(f"serialwrap empty response: {' '.join(args)}")
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"serialwrap JSON decode error: {stdout[:200]}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"serialwrap unexpected response type: {type(payload)}")
    return payload


# ---------------------------------------------------------------------------
# Daemon lifecycle
# ---------------------------------------------------------------------------

def start_daemon(
    profile_dir: str | Path | None = None,
    settle_delay: float = 3.0,
) -> dict[str, Any]:
    """Start serialwrap daemon and return status (contains wal_path).

    A short *settle_delay* after start allows the daemon to finish
    device discovery before subsequent ``session bind`` calls.
    """
    args = ["daemon", "start"]
    if profile_dir:
        args.extend(["--profile-dir", str(profile_dir)])
    payload = _run_sw(args, timeout=15.0)
    logger.info("serialwrap daemon started: pid=%s", payload.get("pid"))
    if settle_delay > 0:
        time.sleep(settle_delay)
    return payload


def stop_daemon() -> None:
    """Stop serialwrap daemon. Silently ignores if not running."""
    try:
        _run_sw(["daemon", "stop"], timeout=10.0)
        logger.info("serialwrap daemon stopped")
    except Exception:
        logger.debug("serialwrap daemon stop ignored (may not be running)")


def daemon_status() -> dict[str, Any] | None:
    """Return daemon status dict, or None when status is unavailable.

    ``None`` only means this client could not obtain a status — the daemon
    may genuinely not be running, **or** it may be alive but unreachable
    from here (mismatched socket path, permissions, transient failure).
    Callers must NOT treat ``None`` as proof the daemon is down, and in
    particular must never use it to justify destructive cleanup of daemon
    state (that misread is exactly how issue #36 destroyed a live WAL).
    """
    try:
        return _run_sw(["daemon", "status"], timeout=5.0)
    except Exception:
        return None


def wal_reset() -> dict[str, Any]:
    """輪替 WAL 檔案並重設 seq，不需重啟 daemon。"""
    payload = _run_sw(["wal", "reset"], timeout=10.0)
    logger.info("wal reset: previous_seq=%s", payload.get("previous_seq"))
    return payload


def wal_current_seq() -> int:
    """透過 RPC 取得目前 WAL seq。"""
    payload = _run_sw(["wal", "current-seq"], timeout=5.0)
    if payload.get("ok") is not True:
        code = payload.get("error_code") or payload.get("message") or "RPC_ERROR"
        raise RuntimeError(f"serialwrap WAL current-seq failed: {code}")
    seq = payload.get("seq")
    if isinstance(seq, bool) or not isinstance(seq, int) or seq < 0:
        raise RuntimeError("serialwrap WAL current-seq returned an invalid sequence")
    return seq


def _list_devices() -> list[dict[str, Any]]:
    """Return discovered USB serial devices from the daemon."""
    payload = _run_sw(["device", "list"], timeout=5.0)
    return payload.get("devices", [])


def _is_windows() -> bool:
    return os.name == "nt"


def _normalize_com_name(value: str) -> str:
    """``COM5`` / ``\\\\.\\COM5`` / ``com5`` → ``COM5`` (#50).

    On Windows serialwrap reports ``real_path`` as ``\\\\.\\COMn`` while a testbed
    normally spells ``serial_port: COMn``; ``Path.resolve()`` turns the bare name
    into ``<cwd>\\COMn`` so the two never compared equal.
    """
    name = value.strip().replace("/", "\\")
    if name.startswith("\\\\.\\"):
        name = name[4:]
    return name.upper()


def _match_device_by_id(
    devices: list[dict[str, Any]],
    serial_port: str,
) -> str | None:
    """Find device_by_id for a given serial port path (e.g. /dev/ttyUSB0)."""
    if _is_windows():
        wanted = _normalize_com_name(serial_port)
        for dev in devices:
            if _normalize_com_name(str(dev.get("real_path", ""))) == wanted:
                return str(dev.get("by_id", ""))
        return None
    rp = Path(serial_port).resolve()
    for dev in devices:
        dev_rp = Path(dev.get("real_path", "")).resolve()
        if dev_rp == rp:
            return str(dev.get("by_id", ""))
    return None


def setup_sessions(
    devices: list[dict[str, Any]],
    *,
    bind_timeout: float = 60.0,
    settle_delay: float = 3.0,
) -> None:
    """Attach explicitly selected sessions or bind legacy devices, then set aliases.

    Each device dict should have:
      - profile: str (e.g. "prpl-template")
      - com: str (e.g. "COM0")
      - alias: str (e.g. "dut")
      - serial_port: str (e.g. "/dev/ttyUSB0") — used to auto-discover device_by_id
      - selector: str (optional) — an existing, operator-bound session identity;
        when supplied, serial_port and enumeration order cannot rebind it

    Explicit selectors are all validated before any attach/bind. Attach and
    legacy bind operations run concurrently with a shared *bind_timeout*.
    """
    # Validate every explicit selector before starting any attach/bind. Logical
    # identities must never be reassigned by ttyUSB order or a stale fallback.
    selected: dict[str, dict[str, Any]] = {}
    explicit = [str(dev["selector"]) for dev in devices if dev.get("selector")]
    if explicit:
        payload = _run_sw(["session", "list"])
        sessions = payload.get("sessions")
        if payload.get("ok") is False or not isinstance(sessions, list):
            raise RuntimeError("cannot verify explicit serialwrap selectors; session list failed")
        identities: set[str] = set()
        for selector in explicit:
            matches = [s for s in sessions if isinstance(s, dict) and selector in
                       {s.get("session_id"), s.get("com"), s.get("alias")}]
            if len(matches) != 1 or not matches[0].get("device_by_id"):
                raise RuntimeError(f"serialwrap selector {selector} must be explicitly bound by the operator")
            session = matches[0]
            identity = str(session.get("session_id") or selector)
            if identity in identities:
                raise RuntimeError(f"duplicate serialwrap selector identity: {selector}")
            identities.add(identity)
            selected[selector] = session
    hw_devices = _list_devices() if len(explicit) != len(devices) else []

    # Phase 1: launch all bind processes concurrently
    bind_procs: list[tuple[str, str, str, subprocess.Popen[str]]] = []
    for dev in devices:
        profile = dev.get("profile", "prpl-template")
        com = dev.get("com", "")
        alias = dev.get("alias", "")
        serial_port = dev.get("serial_port", "")
        session_id = f"{profile}:{com}"

        selector = str(dev.get("selector") or "")
        if selector:
            session = selected[selector]
            session_id = str(session.get("session_id") or selector)
            by_id = str(session["device_by_id"])
            command = [*_cli_prefix(), "session", "attach", "--selector", session_id]
        else:
            by_id = _match_device_by_id(hw_devices, serial_port) if serial_port else None
        if not by_id and not selector:
            idx = int(com.replace("COM", "")) if com.startswith("COM") else 0
            if idx < len(hw_devices):
                by_id = hw_devices[idx].get("by_id", "")

        if not by_id:
            logger.warning("no device_by_id found for %s (%s), skipping bind", com, serial_port)
            continue

        if not selector:
            command = [*_cli_prefix(), "session", "bind", "--selector", session_id, "--device-by-id", by_id]

        proc = subprocess.Popen(
            command,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace",
        )
        bind_procs.append((session_id, alias, by_id, proc))

    # Phase 2: wait for all bind processes (concurrent)
    deadline = time.monotonic() + bind_timeout
    for session_id, alias, by_id, proc in bind_procs:
        remaining = max(0.1, deadline - time.monotonic())
        try:
            stdout, stderr = proc.communicate(timeout=remaining)
            if proc.returncode == 0:
                logger.info("bound session %s → %s", session_id, by_id)
            else:
                logger.warning("bind %s failed (rc=%d): %s", session_id, proc.returncode, stderr.strip())
                continue
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            logger.warning("bind %s timed out after %.0fs", session_id, bind_timeout)
            continue

        # Phase 3: set alias
        if alias:
            try:
                _run_sw(
                    ["alias", "set", "--session-id", session_id, "--alias", alias],
                    timeout=5.0,
                )
                logger.info("alias %s → %s", alias, session_id)
            except Exception:
                logger.warning("alias set failed for %s", alias, exc_info=True)


# ---------------------------------------------------------------------------
# Seq tracking
# ---------------------------------------------------------------------------

def get_wal_path() -> Path:
    """Return the WAL ndjson file path, preferring the daemon-reported one.

    Asks ``daemon status`` first; when that is unavailable (or carries no
    ``wal_path``), falls back to the historical default location
    (``_WAL_PATH_FALLBACK``) purely for display/logging purposes — the
    returned path is NOT guaranteed to be the live daemon's actual WAL.
    """
    status = daemon_status()
    if status and status.get("wal_path"):
        return Path(status["wal_path"])
    return _WAL_PATH_FALLBACK


def get_current_seq(
    wal_path: Path | None = None,
    *,
    same_host_wal_path: bool = False,
) -> int | None:
    """Return the current seq by RPC, optionally falling back to a local file.

    A daemon-reported WAL path can be on a remote host behind a serialwrap
    wrapper. Run-level tracking therefore uses RPC only. Local file access
    requires the caller to attest that the supplied path is same-host.
    """
    if same_host_wal_path and wal_path is not None:
        # This flag is an explicit caller assertion, not inferred from the path.
        path = wal_path
    else:
        try:
            return wal_current_seq()
        except Exception:
            if not same_host_wal_path or wal_path is None:
                return None
        # RPC failed for a caller that explicitly accepts this supplied path.
        path = wal_path
    if not path.is_file():
        return None
    try:
        completed = subprocess.run(
            ["tail", "-1", str(path)],
            capture_output=True, text=True, check=False, timeout=3.0,
        )
        line = (completed.stdout or "").strip()
        if not line:
            return None
        record = json.loads(line)
        return int(record["seq"])
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Log export & decode
# ---------------------------------------------------------------------------

_WAL_EXPORT_PAGE_SIZE = 1000
_WAL_EXPORT_MAX_RECORDS = 100_000


@dataclass(frozen=True)
class WalExportResult:
    """Bounded WAL export plus explicit coverage and loss provenance."""

    records: list[dict[str, Any]]
    requested_from_seq: int
    requested_to_seq: int
    pages_fetched: int
    available_from_seq: int | None
    rotated_out: bool
    missing_sequence_ranges: list[tuple[int, int]]
    incomplete_reasons: list[str]

    @property
    def complete(self) -> bool:
        return not self.incomplete_reasons

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested_from_seq_exclusive": self.requested_from_seq,
            "requested_to_seq_inclusive": self.requested_to_seq,
            "record_count": len(self.records),
            "pages_fetched": self.pages_fetched,
            "available_from_seq": self.available_from_seq,
            "rotated_out": self.rotated_out,
            "complete": self.complete,
            "incomplete_reasons": list(self.incomplete_reasons),
            "missing_sequence_ranges": [list(item) for item in self.missing_sequence_ranges],
            "records": self.records,
        }


def export_records_with_metadata(
    from_seq: int = 0,
    to_seq: int | None = None,
    limit: int | None = 0,
    *,
    page_size: int = _WAL_EXPORT_PAGE_SIZE,
    max_records: int = _WAL_EXPORT_MAX_RECORDS,
) -> WalExportResult:
    """Export a fixed sequence range with bounded pages and coverage evidence.

    ``from_seq`` is the exclusive cursor used by serialwrap's ``wal.range``;
    ``to_seq`` is inclusive. A zero or omitted limit means the configured hard
    cap, not a request for an unbounded RPC response. The service currently
    defaults a zero RPC limit to 1000, so every page sends an explicit positive
    limit and advances from the last returned sequence.
    """
    if from_seq < 0:
        raise ValueError("from_seq must be a non-negative exclusive cursor")
    if page_size <= 0:
        raise ValueError("page_size must be positive")
    page_size = min(int(page_size), _WAL_EXPORT_PAGE_SIZE)
    hard_cap = min(max(int(max_records), 0), _WAL_EXPORT_MAX_RECORDS)
    if limit is not None and int(limit) > 0:
        hard_cap = min(hard_cap, int(limit))

    if to_seq is None:
        # Freeze the moving end before the first page; each page below then
        # carries the exact same inclusive --to-seq value.
        to_seq = wal_current_seq()
    requested_to_seq = int(to_seq)
    if requested_to_seq < 0:
        raise ValueError("to_seq must be a non-negative inclusive end")

    records: list[dict[str, Any]] = []
    reasons: set[str] = set()
    cursor = int(from_seq)
    pages_fetched = 0
    available_from_seq: int | None = None
    rotated_out = False
    if requested_to_seq < from_seq:
        reasons.add("sequence_range_reversed")

    while cursor < requested_to_seq:
        remaining = hard_cap - len(records)
        if remaining <= 0:
            reasons.add("record_limit")
            break
        request_limit = min(page_size, remaining)
        payload = _run_sw(
            [
                "wal",
                "export",
                "--from-seq",
                str(cursor),
                "--to-seq",
                str(requested_to_seq),
                "--limit",
                str(request_limit),
            ],
            timeout=60.0,
        )
        pages_fetched += 1
        if payload.get("ok") is not True:
            code = payload.get("error_code") or payload.get("message") or "INVALID_RESPONSE"
            raise RuntimeError(f"serialwrap WAL export failed: {code}")

        candidate_available = payload.get("available_from_seq")
        if (
            available_from_seq is None
            and isinstance(candidate_available, int)
            and not isinstance(candidate_available, bool)
        ):
            available_from_seq = candidate_available
        rotated_out = rotated_out or payload.get("rotated_out") is True
        if rotated_out:
            reasons.add("rotated_out")

        page_records = payload.get("records")
        if not isinstance(page_records, list):
            reasons.add("malformed_records_response")
            break
        if len(page_records) > request_limit:
            # Do not let a daemon/wrapper that ignored --limit defeat the
            # client-side record bound or produce a complete-looking export.
            reasons.add("page_limit_exceeded")
            break

        prior_cursor = cursor
        last_seq = cursor
        for record in page_records:
            if not isinstance(record, dict):
                reasons.add("malformed_record")
                continue
            seq = record.get("seq")
            if isinstance(seq, bool) or not isinstance(seq, int):
                reasons.add("malformed_sequence")
                records.append(record)
                continue
            if seq <= last_seq or seq > requested_to_seq:
                reasons.add("out_of_range_sequence")
                records.append(record)
                continue
            records.append(record)
            last_seq = seq
            cursor = seq
            if record.get("loss_flag") is True:
                reasons.add("loss_flag")

        if cursor <= prior_cursor:
            # Avoid an infinite retry loop if a remote response contains no
            # valid sequence advancement.
            break
        if len(page_records) < request_limit and payload.get("truncated") is not True:
            break

    valid_sequences = sorted(
        {
            record["seq"]
            for record in records
            if isinstance(record.get("seq"), int)
            and not isinstance(record.get("seq"), bool)
            and from_seq < record["seq"] <= requested_to_seq
        }
    )
    missing_ranges: list[tuple[int, int]] = []
    next_expected = from_seq + 1
    for seq in valid_sequences:
        if seq > next_expected:
            missing_ranges.append((next_expected, seq - 1))
        next_expected = max(next_expected, seq + 1)
    if next_expected <= requested_to_seq:
        missing_ranges.append((next_expected, requested_to_seq))
    if missing_ranges:
        reasons.add("sequence_gap")
    if cursor < requested_to_seq and len(records) >= hard_cap:
        reasons.add("record_limit")

    return WalExportResult(
        records=records,
        requested_from_seq=int(from_seq),
        requested_to_seq=requested_to_seq,
        pages_fetched=pages_fetched,
        available_from_seq=available_from_seq,
        rotated_out=rotated_out,
        missing_sequence_ranges=missing_ranges,
        incomplete_reasons=sorted(reasons),
    )


def export_records(
    from_seq: int = 0,
    to_seq: int | None = None,
    limit: int | None = 0,
) -> list[dict[str, Any]]:
    """Compatibility wrapper returning the bounded, paginated records only."""
    return export_records_with_metadata(from_seq, to_seq, limit).records


def decode_log(
    records: list[dict[str, Any]],
    com_filter: str | None = None,
) -> str:
    """Decode base64 payloads from records into plain text.

    Args:
        records: WAL records from export_records().
        com_filter: If set, only include records from this COM port (e.g. "COM0").

    Returns:
        Decoded text with each record's payload joined by newlines.
    """
    lines: list[str] = []
    for rec in records:
        if com_filter and rec.get("com") != com_filter:
            continue
        payload_b64 = rec.get("payload_b64", "")
        if not payload_b64:
            continue
        try:
            text = base64.b64decode(payload_b64).decode("utf-8", errors="replace")
        except Exception:
            continue
        lines.append(text)
    return "".join(lines)


def save_decoded_log(text: str, path: Path) -> Path:
    """Write decoded log text to file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    logger.info("saved decoded log: %s (%d bytes)", path, len(text))
    return path


def build_seq_to_line_map(
    records: list[dict[str, Any]],
    com_filter: str | None = None,
) -> dict[int, int]:
    """Build a mapping from seq number to the first line number in decoded output.

    Line numbers are 1-based. A record with multi-line payload maps to its
    first line. Records from other COM ports are skipped.

    Returns:
        {seq: first_line_number, ...}
    """
    mapping: dict[int, int] = {}
    current_line = 1
    for rec in records:
        if com_filter and rec.get("com") != com_filter:
            continue
        seq = rec.get("seq")
        payload_b64 = rec.get("payload_b64", "")
        if not payload_b64:
            continue
        try:
            text = base64.b64decode(payload_b64).decode("utf-8", errors="replace")
        except Exception:
            continue
        if seq is not None:
            mapping[int(seq)] = current_line
        line_count = text.count("\n")
        if not text.endswith("\n") and text:
            line_count += 1
        current_line += line_count
    return mapping


def seq_range_to_line_range(
    seq_start: int | None,
    seq_end: int | None,
    seq_to_line: dict[int, int],
) -> str:
    """Convert a seq range to line range string (e.g. 'L123-L456').

    Returns empty string if mapping is insufficient.
    """
    if seq_start is None or seq_end is None:
        return ""
    if not seq_to_line:
        return ""

    start_line = seq_to_line.get(seq_start)
    end_line = seq_to_line.get(seq_end)

    if start_line is None:
        seqs_at_or_after = [s for s in seq_to_line if s >= seq_start]
        if seqs_at_or_after:
            start_line = seq_to_line[min(seqs_at_or_after)]
    if end_line is None:
        seqs_at_or_before = [s for s in seq_to_line if s <= seq_end]
        if seqs_at_or_before:
            end_line = seq_to_line[max(seqs_at_or_before)]

    if start_line is None or end_line is None:
        return ""
    if start_line > end_line:
        start_line, end_line = end_line, start_line
    return f"L{start_line}-L{end_line}"
