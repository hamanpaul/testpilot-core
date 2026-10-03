"""Serialwrap transport implementation."""

from __future__ import annotations

import json
import math
import re
import secrets
import subprocess
import time
from typing import Any

from testpilot.serialwrap_binary import resolve_serialwrap_binary

from .base import TransportBase

TERMINAL_STATUSES = {
    "done",
    "failed",
    "error",
    "timeout",
    "cancelled",
    "canceled",
    "interactive",
}
MODE_ALIASES = {"fg": "line", "bg": "background"}

# Serial terminals have limited line buffers.  Commands longer than this
# threshold are automatically staged to a temp script on the device and
# executed via ``sh``, avoiding truncation.
_MAX_SERIAL_LINE_LENGTH = 120
_TEMPSCRIPT_PREFIX = "/tmp/t"
_DEVICE_LIST_TIMEOUT = 5.0
# Overhead for the legacy quote-chunk unit-test helper. Production staging
# computes its exact framed command length in UTF-8 bytes below.
_PRINTF_OVERHEAD = 39

# Preserve broker safety and readiness evidence at the transport boundary.
_BROKER_RESULT_FIELDS = (
    "outcome", "ambiguous",
    "error_code", "message", "hint", "retry_after_s", "recommended_action",
    "non_replayable", "retryable", "input_integrity", "tx_bytes",
    "sent_chars", "acked_chars", "newline_sent", "session_recovered",
    "recovery_error", "daemon_reachable", "daemon_busy",
)


class SerialWrapCommandError(RuntimeError):
    """CLI/RPC failure retaining the structured broker response."""

    def __init__(self, message: str, result: dict[str, Any]) -> None:
        super().__init__(message)
        self.result = dict(result)
        self.transport_result = self.result


def _resolve_serialwrap_binary(config: dict[str, Any]) -> str:
    cfg_bin = config.get("binary")
    binary = resolve_serialwrap_binary(
        str(cfg_bin) if cfg_bin is not None else None,
        config_label="'binary' in transport config",
    )
    if not cfg_bin:
        config["binary"] = binary
    return binary


class SerialWrapTransport(TransportBase):
    """Transport backed by serialwrap CLI."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = dict(config or {})
        self._binary = _resolve_serialwrap_binary(self._config)
        self._socket = self._config.get("socket")
        self._source = str(self._config.get("source", "agent:testpilot"))
        self._mode = self._normalize_mode(str(self._config.get("mode", "line")))
        self._priority = int(self._config.get("priority", 10))
        self._poll_interval = float(self._config.get("poll_interval", 0.2))
        connect_timeout = float(self._config.get("connect_timeout", 10.0))
        self._connect_attempts = max(1, int(self._config.get("connect_attempts", 2)))
        self._connect_retry_delay = max(
            0.0, float(self._config.get("connect_retry_delay", 0.5))
        )
        self._session_list_timeout = float(
            self._config.get("session_list_timeout", connect_timeout)
        )
        self._session_attach_timeout = float(
            self._config.get("session_attach_timeout", connect_timeout)
        )
        self._connected = False
        self._selector: str | None = None
        self._session: dict[str, Any] | None = None
        self._binding_params: dict[str, Any] = {}

    @property
    def transport_type(self) -> str:
        return "serialwrap"

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def session(self) -> dict[str, Any] | None:
        if self._session is None:
            return None
        return dict(self._session)

    def connect(self, **kwargs: Any) -> None:
        params = {**self._config, **kwargs}
        # A failed reconnect must not leave an earlier selector usable for a
        # command or recovery attempt under the newly requested identity.
        self._connected = False
        self._selector = None
        self._session = None
        self._binding_params = dict(params)
        last_error: Exception | None = None
        for attempt in range(1, self._connect_attempts + 1):
            try:
                sessions = self._list_sessions()
                selector, session = self._resolve_session(params, sessions)
                self._validate_session_binding(params, session)
                self._session = session
                session = self._ensure_ready_session(selector, session)
            except Exception as exc:
                last_error = exc
                self._connected = False
                self._selector = None
                self._session = None
                if attempt >= self._connect_attempts:
                    self._binding_params = {}
                    raise
                if self._connect_retry_delay > 0.0:
                    time.sleep(self._connect_retry_delay)
                continue

            self._selector = str(
                session.get("session_id") or session.get("com") or session.get("alias") or selector
            )
            self._session = session
            self._connected = True
            return

        if last_error is not None:
            raise last_error

    def disconnect(self) -> None:
        self._connected = False
        self._selector = None
        self._session = None

    def recover(self, timeout: float | None = None) -> None:
        if not self._selector:
            raise RuntimeError("serialwrap recover requires resolved selector")
        self._check_current_session_binding()
        recover_timeout = float(timeout if timeout is not None else self._session_attach_timeout)
        self._run_json(
            [
                "session",
                "recover",
                "--selector",
                self._selector,
                "--timeout",
                f"{recover_timeout:.3f}",
            ],
            timeout=recover_timeout + 2.0,
        )
        self._require_ready_attached_session(self._attach_session(), "recover")

    def execute(self, command: str, timeout: float = 30.0) -> dict[str, Any]:
        if not self._connected or not self._selector:
            raise RuntimeError("serialwrap transport is not connected")

        if self._serial_wire_bytes(command) > _MAX_SERIAL_LINE_LENGTH:
            return self._execute_via_tempscript(command, timeout)

        return self._submit_and_poll(command, timeout)

    def estimate_execute_time_budget_s(self, command: str, timeout: float) -> float:
        """Estimate the timeout-derived wall budget for one ``execute`` call.

        The estimate follows the same threshold, newline/chunk staging, stage
        timeout, and final-command timeout as :meth:`execute`. Each submitted
        transaction is budgeted for its submit CLI timeout, status-poll
        deadline, one final status RPC that may cross that deadline, and one
        configured poll interval. A submit and the final status RPC may each
        incur one known-safe ``SESSION_NOT_READY`` attach and retry, including
        the fresh session-list check and possible physical device-list checks
        before and after attach. Unknown, accepted, partial, ambiguous, or
        otherwise non-replayable receipts are never retried. OS subprocess
        start/termination/reap and scheduler latency are outside this
        timeout-derived estimate.

        This pure estimate is intended for callers that must fit a whole
        transport call into a larger deadline.  It does not submit commands or
        require an attached session.
        """
        if not isinstance(command, str):
            raise TypeError("command must be a string")
        try:
            timeout_s = max(float(timeout), 0.1)
            poll_interval_s = float(self._poll_interval)
            attach_timeout_s = float(self._session_attach_timeout)
            config = getattr(self, "_config", {})
            session_list_timeout_s = float(
                getattr(
                    self,
                    "_session_list_timeout",
                    config.get("session_list_timeout", config.get("connect_timeout", 10.0)),
                )
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "timeout, poll interval, and serialwrap CLI timeouts must be numeric"
            ) from exc
        if not math.isfinite(timeout_s):
            raise ValueError("timeout must be finite")
        if not math.isfinite(poll_interval_s) or poll_interval_s < 0:
            raise ValueError("poll interval must be finite and non-negative")
        if not math.isfinite(attach_timeout_s) or attach_timeout_s < 0:
            raise ValueError("session attach timeout must be finite and non-negative")
        if not math.isfinite(session_list_timeout_s) or session_list_timeout_s < 0:
            raise ValueError("session list timeout must be finite and non-negative")

        binding_params = getattr(self, "_binding_params", None) or config
        serial_port = str(binding_params.get("serial_port") or "").strip()
        has_explicit_selector = any(
            binding_params.get(field) for field in ("selector", "alias", "session_id")
        )
        needs_device_lookup = bool(
            serial_port
            and has_explicit_selector
            and not self._is_by_id_path(serial_port)
            and not self._normalize_com_name(serial_port)
        )
        # Binding validation may resolve a physical tty path both before the
        # attach and again against its response. Budget both bounded device
        # list reads as well as the fresh session-list read.
        attach_binding_check_budget_s = session_list_timeout_s + (
            2 * _DEVICE_LIST_TIMEOUT if needs_device_lookup else 0.0
        )

        def transaction_budget(transaction_timeout_s: float) -> float:
            submit_cli_timeout_s = transaction_timeout_s + 2.0
            status_cli_timeout_s = min(transaction_timeout_s + 1.0, 5.0)
            # `_run_json(cmd submit)` gets t+2. `_poll_status` has a fresh
            # t+1 deadline, can sleep once past it, and then may run one last
            # status CLI call whose timeout is min(t+1, 5). Either that final
            # status request or the submit may receive one known-safe
            # SESSION_NOT_READY response and incur one binding preflight,
            # attach, and retry. The preflight refreshes session-list metadata
            # and may perform two device-list lookups for an explicit physical
            # tty path (before attach and on its response).
            return (
                submit_cli_timeout_s
                + transaction_timeout_s
                + 1.0
                + poll_interval_s
                + status_cli_timeout_s
                + attach_binding_check_budget_s
                + attach_timeout_s
                + submit_cli_timeout_s
                + attach_binding_check_budget_s
                + attach_timeout_s
                + status_cli_timeout_s
            )

        if self._serial_wire_bytes(command) <= _MAX_SERIAL_LINE_LENGTH:
            return transaction_budget(timeout_s)

        nonce = "A" * 16
        script_path = self._tempscript_path(nonce)
        stage_transactions = sum(
            len(self._sq_chunks(line, script_path=script_path, nonce=nonce))
            for line in command.split("\n")
        )
        setup_timeout_s = min(timeout_s, 10.0)
        return (
            stage_transactions * transaction_budget(setup_timeout_s)
            + transaction_budget(timeout_s)
        )

    # ------------------------------------------------------------------
    # Long-command handler: stage to temp script, execute via ``sh``
    # ------------------------------------------------------------------

    def _execute_via_tempscript(self, command: str, timeout: float) -> dict[str, Any]:
        """Write *command* to a unique temp script, then execute it.

        Each staging printf and the final script shell report their producer
        status through one unpredictable terminal marker. Unknown or malformed
        receipts stop without replaying or executing a possibly partial file.
        """
        lines = command.split("\n")
        setup_timeout = min(timeout, 10.0)
        nonce = secrets.token_urlsafe(12)
        if not re.fullmatch(r"[A-Za-z0-9_-]{16}", nonce):
            raise RuntimeError("failed to generate a safe staged-command nonce")
        script_path = self._tempscript_path(nonce)
        marker = f"TP{nonce}"
        first = True
        staged_write_count = 0

        for line in lines:
            chunks = self._sq_chunks(line, script_path=script_path, nonce=nonce)
            for chunk_idx, chunk in enumerate(chunks):
                stage_command = self._stage_write_command(
                    chunk,
                    script_path=script_path,
                    nonce=nonce,
                    append=not first,
                    finish_line=chunk_idx == len(chunks) - 1,
                )
                if self._serial_wire_bytes(stage_command) > _MAX_SERIAL_LINE_LENGTH:
                    raise RuntimeError("generated staged write exceeds serial line byte limit")
                first = False
                staged = self._submit_and_poll(
                    stage_command, setup_timeout, preserve_stdout=True,
                )
                if self._receipt_is_uncertain(staged):
                    # Keep the raw receipt while making the transport result
                    # fail closed; never run the script after an uncertain write.
                    return self._uncertain_producer_result(
                        staged,
                        phase="stage_write",
                        staged_write_count=staged_write_count,
                    )

                parsed = self._parse_producer_frame(staged.get("stdout"), marker, fields=1)
                if parsed is None:
                    return self._producer_status_unknown(
                        staged,
                        phase="stage_write",
                        staged_write_count=staged_write_count,
                    )
                producer_rc, _cleanup_rc, clean_stdout = parsed
                staged_write_count += 1
                framed_stage = self._producer_result(
                    staged,
                    phase="stage_write",
                    producer_rc=producer_rc,
                    cleanup_rc=None,
                    clean_stdout=clean_stdout,
                    staged_write_count=staged_write_count,
                )
                if framed_stage["returncode"] != 0:
                    # Keep the uniquely owned partial file and do not execute it.
                    return framed_stage

        final_command = self._final_script_command(script_path=script_path, nonce=nonce)
        if self._serial_wire_bytes(final_command) > _MAX_SERIAL_LINE_LENGTH:
            raise RuntimeError("generated staged execution exceeds serial line byte limit")
        result = self._submit_and_poll(final_command, timeout, preserve_stdout=True)
        if self._receipt_is_uncertain(result):
            return self._uncertain_producer_result(
                result,
                phase="script",
                staged_write_count=staged_write_count,
            )

        parsed = self._parse_producer_frame(result.get("stdout"), marker, fields=2)
        if parsed is None:
            return self._producer_status_unknown(
                result,
                phase="script",
                staged_write_count=staged_write_count,
            )
        producer_rc, cleanup_rc, clean_stdout = parsed
        return self._producer_result(
            result,
            phase="script",
            producer_rc=producer_rc,
            cleanup_rc=cleanup_rc,
            clean_stdout=clean_stdout,
            staged_write_count=staged_write_count,
        )

    @staticmethod
    def _tempscript_path(nonce: str) -> str:
        """Build a unique path separate from the legacy shared temp file."""
        return f"{_TEMPSCRIPT_PREFIX}{nonce}"

    @staticmethod
    def _serial_wire_bytes(command: str) -> int:
        """Count UTF-8 bytes sent by ``Bridge.send_command``, including LF."""
        payload = command.encode("utf-8")
        return len(payload) if payload.endswith(b"\n") else len(payload) + 1

    @staticmethod
    def _stage_write_command(
        chunk: str,
        *,
        script_path: str,
        nonce: str,
        append: bool,
        finish_line: bool,
    ) -> str:
        fmt = "%s\\n" if finish_line else "%s"
        redirection = ">>" if append else ">"
        return (
            f"printf '{fmt}' '{chunk}' {redirection} {script_path}; "
            f"printf '\\nTP%s:%s\\n' '{nonce}' \"$?\""
        )

    @staticmethod
    def _final_script_command(*, script_path: str, nonce: str) -> str:
        # The subshell keeps its short status variables out of the caller.
        # The split literal keeps the complete marker out of UART command echo.
        # Capture script status before cleanup; printf's second status argument
        # expands to the cleanup command's status.
        return (
            f"(sh {script_path}; s=$?; rm -f {script_path}; "
            f"printf '\\nTP%s:%s:%s\\n' '{nonce}' \"$s\" \"$?\")"
        )

    @staticmethod
    def _receipt_is_uncertain(result: dict[str, Any]) -> bool:
        outcome = str(result.get("outcome") or "").strip().lower()
        status = str(result.get("status") or "").strip().lower()
        error_code = str(result.get("error_code") or "").strip().upper()
        input_integrity = str(result.get("input_integrity") or "").strip().lower()
        return bool(
            result.get("partial") is True
            or result.get("non_replayable") is True
            or result.get("ambiguous") is True
            or outcome in {"accepted", "unknown", "ambiguous"}
            or status in {"accepted", "running", "timeout", "unknown"}
            or error_code == "COMMAND_OUTCOME_UNKNOWN"
            or input_integrity == "uncertain"
        )

    @staticmethod
    def _parse_producer_frame(
        stdout: Any, marker: str, *, fields: int
    ) -> tuple[int, int | None, str] | None:
        """Parse exactly one complete terminal marker and remove its separator."""
        if not isinstance(stdout, str) or fields not in {1, 2}:
            return None
        lines = stdout.splitlines(keepends=True)
        if not lines:
            return None

        status_pattern = re.compile(
            rf"{re.escape(marker)}:([0-9]{{1,3}})"
            + (r":([0-9]{1,3})" if fields == 2 else "")
        )
        matches: list[tuple[int, re.Match[str]]] = []
        for index, line in enumerate(lines):
            content = line
            if content.endswith("\n"):
                content = content[:-1]
                if content.endswith("\r"):
                    content = content[:-1]
            elif content.endswith("\r"):
                content = content[:-1]
            if content.startswith(marker):
                match = status_pattern.fullmatch(content)
                if match is None:
                    return None
                matches.append((index, match))

        if len(matches) != 1 or matches[0][0] != len(lines) - 1:
            return None
        _, match = matches[0]
        producer_rc = int(match.group(1))
        cleanup_rc = int(match.group(2)) if fields == 2 else None
        if producer_rc > 255 or (cleanup_rc is not None and cleanup_rc > 255):
            return None

        clean_stdout = "".join(lines[:-1])
        if clean_stdout.endswith("\n"):
            # Remove only the newline injected before our frame. A preceding
            # CR may belong to the command's real output and must be retained.
            clean_stdout = clean_stdout[:-1]
        else:
            return None
        return producer_rc, cleanup_rc, clean_stdout

    @staticmethod
    def _producer_status_unknown(
        broker_result: dict[str, Any],
        *,
        phase: str,
        staged_write_count: int,
    ) -> dict[str, Any]:
        result = dict(broker_result)
        result.update(
            returncode=124,
            outcome="unknown",
            non_replayable=True,
            retryable=False,
            error_code="PRODUCER_STATUS_UNKNOWN",
            producer_status="unknown",
            producer_phase=phase,
            producer_returncode=None,
            cleanup_returncode=None,
            broker_returncode=broker_result.get("returncode"),
            staged_write_count=staged_write_count,
            original_broker_result=dict(broker_result),
        )
        return result

    @staticmethod
    def _uncertain_producer_result(
        broker_result: dict[str, Any],
        *,
        phase: str,
        staged_write_count: int,
    ) -> dict[str, Any]:
        """Fail closed while retaining the exact uncertain broker receipt."""
        result = dict(broker_result)
        result.update(
            returncode=124,
            outcome="unknown",
            non_replayable=True,
            retryable=False,
            producer_status="unknown",
            producer_phase=phase,
            producer_returncode=None,
            cleanup_returncode=None,
            broker_returncode=broker_result.get("returncode"),
            staged_write_count=staged_write_count,
            original_broker_result=dict(broker_result),
        )
        if not result.get("error_code"):
            result["error_code"] = "COMMAND_OUTCOME_UNKNOWN"
        return result

    @staticmethod
    def _producer_result(
        broker_result: dict[str, Any],
        *,
        phase: str,
        producer_rc: int,
        cleanup_rc: int | None,
        clean_stdout: str,
        staged_write_count: int,
    ) -> dict[str, Any]:
        result = dict(broker_result)
        broker_rc = broker_result.get("returncode", 0)
        if not isinstance(broker_rc, int):
            broker_rc = 0
        if producer_rc != 0:
            effective_rc = producer_rc
        elif cleanup_rc not in {None, 0}:
            effective_rc = cleanup_rc
        else:
            effective_rc = broker_rc
        result.update(
            returncode=effective_rc,
            stdout=clean_stdout,
            producer_status="known",
            producer_phase=phase,
            producer_returncode=producer_rc,
            cleanup_returncode=cleanup_rc,
            broker_returncode=broker_result.get("returncode"),
            staged_write_count=staged_write_count,
            original_broker_result=dict(broker_result),
        )
        return result

    @classmethod
    def _sq_chunks(
        cls,
        line: str,
        *,
        script_path: str | None = None,
        nonce: str | None = None,
    ) -> list[str]:
        """Split a shell line into safely quoted chunks within the wire budget."""
        if (script_path is None) != (nonce is None):
            raise ValueError("script_path and nonce must be provided together")
        if script_path is None or nonce is None:
            max_content_bytes = max(
                0, _MAX_SERIAL_LINE_LENGTH - _PRINTF_OVERHEAD - 1
            )
        else:
            framing_overhead = max(
                cls._serial_wire_bytes(
                    cls._stage_write_command(
                        "",
                        script_path=script_path,
                        nonce=nonce,
                        append=append,
                        finish_line=finish_line,
                    )
                )
                for append in (False, True)
                for finish_line in (False, True)
            )
            max_content_bytes = _MAX_SERIAL_LINE_LENGTH - framing_overhead

        chunks: list[str] = []
        current: list[str] = []
        current_bytes = 0

        for char in line:
            piece = "'\\''" if char == "'" else char
            piece_bytes = len(piece.encode("utf-8"))
            if current_bytes + piece_bytes > max_content_bytes and current:
                chunks.append("".join(current))
                current = []
                current_bytes = 0
            if piece_bytes > max_content_bytes:
                raise ValueError("one UTF-8 character exceeds staged serial command budget")
            current.append(piece)
            current_bytes += piece_bytes

        if current:
            chunks.append("".join(current))
        return chunks or [""]
    # ------------------------------------------------------------------
    # Low-level submit + poll
    # ------------------------------------------------------------------

    def _submit_and_poll(
        self,
        command: str,
        timeout: float = 30.0,
        *,
        preserve_stdout: bool = False,
    ) -> dict[str, Any]:
        timeout_s = max(float(timeout), 0.1)
        start = time.monotonic()
        submit_args = [
            "cmd", "submit", "--selector", self._selector,
            "--cmd", command, "--source", self._source,
            "--mode", self._mode, "--priority", str(self._priority),
            "--cmd-timeout", f"{timeout_s:.3f}",
        ]
        try:
            submit_payload = self._run_json(submit_args, timeout=timeout_s + 2.0)
        except SerialWrapCommandError as exc:
            code = exc.result.get("error_code")
            if (
                exc.result.get("ok") is False
                and isinstance(code, str) and code and code != "TIMEOUT"
                and not exc.result.get("cmd_id")
            ):
                raise
            evidence = dict(exc.result)
            evidence.update(outcome="unknown", non_replayable=True, retryable=False)
            raise SerialWrapCommandError("serialwrap submit outcome is unknown", evidence) from exc
        except (RuntimeError, OSError) as exc:
            raise SerialWrapCommandError(
                "serialwrap submit response unavailable; command acceptance is unknown",
                {"error_code": "COMMAND_OUTCOME_UNKNOWN", "outcome": "unknown",
                 "non_replayable": True, "retryable": False},
            ) from exc

        cmd_id = submit_payload.get("cmd_id")
        if not isinstance(cmd_id, str) or not cmd_id:
            raise SerialWrapCommandError(
                "serialwrap cmd submit response missing cmd_id; acceptance is unknown",
                {"error_code": "COMMAND_OUTCOME_UNKNOWN", "outcome": "unknown",
                 "non_replayable": True, "retryable": False},
            )

        try:
            status_payload = self._poll_status(cmd_id, timeout_s)
        except Exception as exc:
            # Submission was accepted. A failed status read cannot prove the
            # command stopped, so do not inject attach/recovery bytes or replay.
            return {
                "returncode": 124, "stdout": "", "stderr": str(exc),
                "elapsed": time.monotonic() - start, "cmd_id": cmd_id,
                "status": "timeout", "partial": True, "outcome": "unknown",
                "error_code": "COMMAND_OUTCOME_UNKNOWN",
                "non_replayable": True, "retryable": False,
                "execution_mode": self._mode, "background_capture_id": None,
                "interactive_session_id": None, "recovery_action": None,
            }

        command_status = status_payload.get("command", {})
        raw_stdout = str(command_status.get("stdout", "") or "")
        stdout = raw_stdout if preserve_stdout else raw_stdout.strip()
        returncode = self._status_to_returncode(
            str(command_status.get("status", "")), command_status.get("error_code"),
        )
        stderr = self._build_stderr(command_status)
        result = {
            "returncode": returncode, "stdout": stdout, "stderr": stderr,
            "elapsed": time.monotonic() - start, "cmd_id": cmd_id,
            "status": command_status.get("status"),
            "partial": bool(command_status.get("partial", False)),
            "execution_mode": command_status.get("execution_mode"),
            "background_capture_id": command_status.get("background_capture_id"),
            "interactive_session_id": command_status.get("interactive_session_id"),
            "recovery_action": command_status.get("recovery_action"),
            **{key: command_status[key] for key in _BROKER_RESULT_FIELDS if key in command_status},
        }
        if str(command_status.get("status", "")).lower() == "timeout":
            result.update(outcome="unknown", non_replayable=True, retryable=False)
        return result

    def _build_cli(self, args: list[str]) -> list[str]:
        cmd = [self._binary]
        if self._socket:
            cmd.extend(["--socket", str(self._socket)])
        cmd.extend(args)
        return cmd

    def _run_json(
        self,
        args: list[str],
        timeout: float | None = None,
        *,
        _attach_retry_count: int = 0,
    ) -> dict[str, Any]:
        try:
            completed = subprocess.run(
                self._build_cli(args),
                capture_output=True,
                text=True,
                encoding="utf-8",  # serialwrap output is UTF-8 regardless of host locale (#51)
                errors="replace",
                check=False,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            if args[:2] != ["cmd", "submit"]:
                raise
            raise SerialWrapCommandError(
                "serialwrap submit CLI timed out; command acceptance is unknown",
                {"error_code": "COMMAND_OUTCOME_UNKNOWN", "outcome": "unknown",
                 "non_replayable": True, "retryable": False, "partial": True},
            ) from exc
        stdout = (completed.stdout or "").strip()
        payload = None
        if stdout:
            try:
                decoded = json.loads(stdout)
            except json.JSONDecodeError:
                pass
            else:
                if isinstance(decoded, dict):
                    payload = decoded
        if completed.returncode != 0:
            stderr = (completed.stderr or "").strip()
            stdout_trimmed = (completed.stdout or "").strip()[:500]
            suffix = f" | rc={completed.returncode}"
            if stdout_trimmed:
                suffix += f" | stdout={stdout_trimmed}"
            raise SerialWrapCommandError(
                f"serialwrap command failed: {' '.join(args)}: {stderr}{suffix}",
                payload if payload is not None else {"returncode": completed.returncode, "stderr": stderr},
            )

        if not stdout:
            raise RuntimeError(f"serialwrap command returned empty stdout: {' '.join(args)}")

        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"serialwrap JSON decode failed: {stdout!r}") from exc

        if not isinstance(payload, dict):
            raise RuntimeError(f"serialwrap response must be JSON object: {stdout!r}")
        if payload.get("ok") is False:
            if (
                _attach_retry_count < 1
                and self._should_retry_with_attach(args, payload)
            ):
                self._require_ready_attached_session(
                    self._attach_session(), "command retry"
                )
                return self._run_json(
                    args,
                    timeout=timeout,
                    _attach_retry_count=_attach_retry_count + 1,
                )
            raise SerialWrapCommandError(f"serialwrap command not ok: {' '.join(args)}: {stdout}", payload)
        return payload

    def _ensure_ready_session(self, selector: str, session: dict[str, Any]) -> dict[str, Any]:
        state = str(session.get("state", "")).upper()
        if state == "READY":
            return session

        self._selector = str(
            session.get("session_id") or session.get("com") or session.get("alias") or selector
        )
        payload = self._attach_session()
        attached = payload.get("session")
        if not isinstance(attached, dict):
            raise RuntimeError(f"serialwrap attach returned no session payload: {selector}")
        attached_state = str(attached.get("state", "")).upper()
        if attached_state != "READY":
            raise RuntimeError(f"serialwrap session not READY: {selector} ({attached_state})")
        return attached

    def _attach_session(self) -> dict[str, Any]:
        selector = self._selector
        if not selector:
            raise RuntimeError("serialwrap attach requires resolved selector")
        try:
            self._check_current_session_binding()
            payload = self._run_json(
                ["session", "attach", "--selector", selector],
                timeout=self._session_attach_timeout,
            )
            session = payload.get("session")
            if not isinstance(session, dict):
                raise RuntimeError("serialwrap attach returned no session payload")
            if selector not in {
                str(session.get("session_id", "")),
                str(session.get("com", "")),
                str(session.get("alias", "")),
            }:
                raise RuntimeError("serialwrap attach returned a different session identity")
            self._validate_session_binding(
                getattr(self, "_binding_params", {}), session
            )
            cached_session = self._session
            if not isinstance(cached_session, dict):
                raise RuntimeError("serialwrap cached session identity is unavailable")
            self._validate_same_session_identity(cached_session, session)
            self._session = session
            return payload
        except Exception:
            self._clear_session_binding()
            raise

    def _require_ready_attached_session(
        self, payload: dict[str, Any], context: str
    ) -> dict[str, Any]:
        session = payload.get("session")
        if not isinstance(session, dict) or str(session.get("state", "")).upper() != "READY":
            self._clear_session_binding()
            raise RuntimeError(f"serialwrap {context} attach did not return a READY session")
        return session

    def _should_retry_with_attach(self, args: list[str], payload: dict[str, Any]) -> bool:
        outcome = str(payload.get("outcome") or "").strip().lower()
        if (
            payload.get("non_replayable") is True
            or payload.get("partial") is True
            or payload.get("ambiguous") is True
            or outcome in {"accepted", "unknown", "ambiguous"}
            or payload.get("cmd_id")
            or payload.get("retryable") is False
        ):
            return False
        if len(args) >= 2 and args[:2] == ["session", "attach"]:
            return False
        if not self._selector:
            return False
        if payload.get("error_code") != "SESSION_NOT_READY":
            return False
        if len(args) < 2 or args[:2] in (
            ["session", "list"],
            ["device", "list"],
        ):
            return False
        return True

    def _list_sessions(self) -> list[dict[str, Any]]:
        payload = self._run_json(["session", "list"], timeout=self._session_list_timeout)
        sessions = payload.get("sessions", [])
        if not isinstance(sessions, list):
            raise RuntimeError("serialwrap session list response missing sessions")
        return [s for s in sessions if isinstance(s, dict)]

    def _resolve_session(
        self, params: dict[str, Any], sessions: list[dict[str, Any]]
    ) -> tuple[str, dict[str, Any]]:
        selector = params.get("selector")
        alias = params.get("alias")
        session_id = params.get("session_id")
        serial_port = params.get("serial_port")

        if selector:
            matches = [
                session
                for session in sessions
                if str(selector)
                in {
                    str(session.get("session_id", "")),
                    str(session.get("alias", "")),
                    str(session.get("com", "")),
                }
            ]
            if len(matches) != 1:
                raise RuntimeError(f"serialwrap selector lookup failed: {selector}")
            return str(selector), matches[0]

        if alias:
            selected = self._find_one(sessions, "alias", str(alias))
            return str(alias), selected

        if session_id:
            selected = self._find_one(sessions, "session_id", str(session_id))
            return str(session_id), selected

        if serial_port:
            serial_port_str = str(serial_port)
            candidates = [
                session
                for session in sessions
                if serial_port_str
                in {
                    str(session.get("device_by_id", "")),
                    str(session.get("vtty", "")),
                    str(session.get("com", "")),
                }
            ]
            if len(candidates) == 1:
                return serial_port_str, candidates[0]

            by_id = self._resolve_by_id_from_real_path(serial_port_str)
            if by_id:
                by_id_candidates = [
                    session
                    for session in sessions
                    if str(session.get("device_by_id", "")) == by_id
                ]
                if len(by_id_candidates) == 1:
                    return serial_port_str, by_id_candidates[0]

            com = self._resolve_com_from_serial_port(serial_port_str)
            if com:
                selected = self._find_by_selector(com, sessions)
                if selected is not None:
                    return com, selected

            raise RuntimeError(f"serialwrap serial_port lookup failed: {serial_port}")

        ready_sessions = [s for s in sessions if str(s.get("state", "")).upper() == "READY"]
        if len(ready_sessions) == 1:
            only = ready_sessions[0]
            fallback = str(only.get("session_id") or only.get("com") or only.get("alias") or "")
            if not fallback:
                raise RuntimeError("serialwrap READY session missing selector fields")
            return fallback, only

        raise RuntimeError(
            "serialwrap connect requires selector/alias/session_id/serial_port "
            "when READY sessions are not unique"
        )

    def _validate_session_binding(
        self, params: dict[str, Any], session: dict[str, Any]
    ) -> None:
        requested_profile = params.get("profile")
        if requested_profile:
            actual_profile = session.get("profile")
            if not actual_profile or str(actual_profile) != str(requested_profile):
                raise RuntimeError("serialwrap session profile does not match configuration")

        serial_port = str(params.get("serial_port") or "").strip()
        if not serial_port:
            return

        explicitly_selected = any(
            params.get(field) for field in ("selector", "alias", "session_id")
        )
        if not explicitly_selected and not self._is_by_id_path(serial_port):
            # Preserve serial_port-only legacy discovery, including the
            # ttyUSB-to-COM fallback in _resolve_session().
            return

        if self._session_matches_serial_port(serial_port, session):
            return
        raise RuntimeError("serialwrap session physical identity does not match configuration")

    def _check_current_session_binding(self) -> None:
        selector = self._selector
        cached_session = self._session
        if not selector or not isinstance(cached_session, dict):
            raise RuntimeError("serialwrap current session identity is unavailable")

        params = getattr(self, "_binding_params", {})
        selector_params = dict(params)
        selector_params["selector"] = selector
        selector_params.pop("alias", None)
        selector_params.pop("session_id", None)
        try:
            sessions = self._list_sessions()
            _, current_session = self._resolve_session(selector_params, sessions)
            self._validate_session_binding(params, current_session)
            self._validate_same_session_identity(cached_session, current_session)
        except Exception:
            self._clear_session_binding()
            raise

    def _validate_same_session_identity(
        self, expected_session: dict[str, Any], actual_session: dict[str, Any]
    ) -> None:
        for field in ("session_id", "profile", "device_by_id", "platform", "com", "alias"):
            expected = expected_session.get(field)
            if expected in (None, ""):
                continue
            actual = actual_session.get(field)
            if actual is None or str(actual) != str(expected):
                raise RuntimeError("serialwrap current session identity changed")

    def _clear_session_binding(self) -> None:
        # Once daemon metadata or an attach response disagrees with the
        # accepted session, cached selectors are no longer safe to use.
        self._connected = False
        self._selector = None
        self._session = None

    def _session_matches_serial_port(
        self, serial_port: str, session: dict[str, Any]
    ) -> bool:
        by_id = str(session.get("device_by_id") or "").strip()
        if self._is_by_id_path(serial_port):
            return bool(by_id and by_id == serial_port)

        vtty = str(session.get("vtty") or "").strip()
        if vtty and vtty == serial_port:
            return True

        requested_com = self._normalize_com_name(serial_port)
        actual_com = self._normalize_com_name(str(session.get("com") or ""))
        if requested_com and requested_com == actual_com:
            return True

        resolved_by_id = self._resolve_unique_by_id_from_real_path(serial_port)
        return bool(resolved_by_id and by_id and resolved_by_id == by_id)

    @staticmethod
    def _is_by_id_path(value: str) -> bool:
        return value.startswith("/dev/serial/by-id/")

    @staticmethod
    def _normalize_com_name(value: str) -> str | None:
        normalized = value.strip()
        if normalized.startswith("\\\\.\\"):
            normalized = normalized[4:]
        if re.fullmatch(r"COM\d+", normalized, flags=re.IGNORECASE):
            return normalized.upper()
        return None

    def _find_by_selector(
        self, selector: str, sessions: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        matches = [
            session
            for session in sessions
            if selector
            in {
                str(session.get("session_id", "")),
                str(session.get("alias", "")),
                str(session.get("com", "")),
            }
        ]
        if len(matches) != 1:
            return None
        return matches[0]

    def _find_one(
        self, sessions: list[dict[str, Any]], field: str, expected: str
    ) -> dict[str, Any]:
        candidates = [session for session in sessions if str(session.get(field, "")) == expected]
        if len(candidates) != 1:
            raise RuntimeError(f"serialwrap {field} lookup failed: {expected}")
        return candidates[0]

    def _poll_status(self, cmd_id: str, timeout: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout + 1.0
        last_payload: dict[str, Any] = {}
        while True:
            last_payload = self._run_json(
                ["cmd", "status", "--cmd-id", cmd_id],
                timeout=min(timeout + 1.0, 5.0),
            )
            command_payload = last_payload.get("command", {})
            if not isinstance(command_payload, dict):
                raise RuntimeError("serialwrap command status response is malformed")
            status = str(command_payload.get("status", "")).lower()
            if status in TERMINAL_STATUSES:
                return last_payload
            if time.monotonic() >= deadline:
                raise TimeoutError(f"serialwrap cmd status timeout: {cmd_id}")
            if self._poll_interval > 0:
                time.sleep(self._poll_interval)

    def _status_to_returncode(self, status: str, error_code: Any) -> int:
        status_lower = status.lower()
        if status_lower in {"done", "interactive"} and not error_code:
            return 0
        if status_lower == "timeout":
            return 124
        if status_lower in {"cancelled", "canceled"}:
            return 130
        return 1

    def _build_stderr(self, command_status: dict[str, Any]) -> str:
        details: list[str] = []
        stderr = str(command_status.get("stderr", "") or "").strip()
        error_code = command_status.get("error_code")
        status = str(command_status.get("status", ""))

        if stderr:
            details.append(stderr)
        if error_code:
            details.append(str(error_code))
        if status and status.lower() not in {"done", "running", "accepted", "interactive"}:
            details.append(f"status={status}")
        return "; ".join(details)

    @staticmethod
    def _normalize_mode(mode: str) -> str:
        normalized = MODE_ALIASES.get(mode.strip().lower(), mode.strip().lower())
        if normalized not in {"line", "background", "interactive"}:
            return "line"
        return normalized

    def _resolve_by_id_from_real_path(self, serial_port: str) -> str | None:
        try:
            payload = self._run_json(
                ["device", "list"], timeout=_DEVICE_LIST_TIMEOUT
            )
        except Exception:
            return None
        devices = payload.get("devices", [])
        if not isinstance(devices, list):
            return None
        for item in devices:
            if not isinstance(item, dict):
                continue
            if str(item.get("real_path", "")) != serial_port:
                continue
            by_id = str(item.get("by_id", "")).strip()
            if by_id:
                return by_id
        return None

    def _resolve_unique_by_id_from_real_path(self, serial_port: str) -> str | None:
        try:
            payload = self._run_json(
                ["device", "list"], timeout=_DEVICE_LIST_TIMEOUT
            )
        except Exception:
            return None
        devices = payload.get("devices", [])
        if not isinstance(devices, list):
            return None
        matches: set[str] = set()
        for item in devices:
            if not isinstance(item, dict):
                continue
            by_id = item.get("by_id")
            if (
                isinstance(by_id, str)
                and by_id.strip()
                and str(item.get("real_path", "")) == serial_port
            ):
                matches.add(by_id.strip())
        if len(matches) != 1:
            return None
        return next(iter(matches))

    @staticmethod
    def _resolve_com_from_serial_port(serial_port: str) -> str | None:
        match = re.search(r"ttyUSB(\d+)$", serial_port)
        if not match:
            return None
        return f"COM{match.group(1)}"
