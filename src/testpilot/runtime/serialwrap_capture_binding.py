"""Bounded API 1.1 serialwrap capture-binding CLI client.

This module is intentionally separate from the legacy buffered serialwrap
logger reader.  It accepts only the explicit strict routes and never retries
or falls back to an API 1.0 range method.
"""

from __future__ import annotations

import json
import math
import subprocess
from threading import Event, Thread
from typing import Any

from testpilot.runtime.strict_capture import (
    MAX_CAPTURE_TOTAL_BYTES,
    MAX_JSON_DEPTH,
    StrictCaptureError,
)

MAX_CAPTURE_REQUEST_BYTES = 65_536
MAX_CAPTURE_PAGE_STDOUT_BYTES = 8 * 1024 * 1024
MAX_CAPTURE_STDERR_BYTES = 65_536
MAX_CAPTURE_RUN_STDOUT_BYTES = 64 * 1024 * 1024
MAX_CAPABILITY_STDOUT_BYTES = 65_536

_STRICT_API_ACTIONS = frozenset({"mark", "range", "finish"})
_ACTION_TIMEOUTS = {
    "capabilities": 5.0,
    "begin": 45.0,
    "checkpoint": 5.0,
    "mark": 45.0,
    "range": 5.0,
    "finish": 45.0,
    "status": 5.0,
}


def capture_cli_argv(
    binary: str,
    socket: str,
    action: str,
) -> list[str]:
    """Build the sealed explicit API route; endpoint values stay out of logs."""
    if action not in _ACTION_TIMEOUTS:
        raise ValueError("capture action is unsupported")
    argv = [binary]
    if socket:
        argv.extend(["--socket", socket])
    argv.extend(["capture-binding", action])
    if action in _STRICT_API_ACTIONS:
        argv.extend(["--api-version", "1.1"])
    return argv


def _reject_constant(_value: str) -> None:
    raise ValueError("non-finite JSON number")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _bounded_depth(value: Any, depth: int = 0) -> bool:
    if depth > MAX_JSON_DEPTH:
        return False
    if type(value) is dict:
        return all(type(key) is str and _bounded_depth(item, depth + 1) for key, item in value.items())
    if type(value) is list:
        return all(_bounded_depth(item, depth + 1) for item in value)
    if type(value) is float:
        return math.isfinite(value)
    return value is None or type(value) in {str, bool, int, float}


def _read_bounded_pipe(
    stream: Any,
    *,
    limit: int,
    overflow: Event,
    process: subprocess.Popen[bytes],
) -> bytearray:
    captured = bytearray()
    try:
        while True:
            chunk = stream.read(4096)
            if not chunk:
                break
            remaining = limit - len(captured)
            if len(chunk) > remaining:
                if remaining > 0:
                    captured.extend(chunk[:remaining])
                overflow.set()
                try:
                    process.kill()
                except OSError:
                    pass
                break
            captured.extend(chunk)
    except (OSError, ValueError):
        overflow.set()
        try:
            process.kill()
        except OSError:
            pass
    finally:
        try:
            stream.close()
        except OSError:
            pass
    return captured


def _run_bounded_json_command(
    argv: list[str],
    payload: dict[str, Any],
    *,
    timeout: float,
    stdout_limit: int,
    stderr_limit: int = MAX_CAPTURE_STDERR_BYTES,
) -> tuple[dict[str, Any], int]:
    try:
        request = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError):
        raise StrictCaptureError("capture_request_invalid") from None
    if len(request) > MAX_CAPTURE_REQUEST_BYTES:
        raise StrictCaptureError("capture_request_too_large")

    try:
        process = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
    except (OSError, ValueError):
        raise StrictCaptureError("capture_rpc_unknown", operation_uncertain=True) from None
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None
    stdout_overflow = Event()
    stderr_overflow = Event()
    stdout_data = bytearray()
    stderr_data = bytearray()

    stdout_thread = Thread(
        target=lambda: stdout_data.extend(
            _read_bounded_pipe(
                process.stdout,
                limit=stdout_limit,
                overflow=stdout_overflow,
                process=process,
            )
        ),
        daemon=True,
    )
    stderr_thread = Thread(
        target=lambda: stderr_data.extend(
            _read_bounded_pipe(
                process.stderr,
                limit=stderr_limit,
                overflow=stderr_overflow,
                process=process,
            )
        ),
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()
    write_failed = Event()

    def write_request() -> None:
        try:
            process.stdin.write(request)
            process.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            write_failed.set()
        finally:
            try:
                process.stdin.close()
            except OSError:
                pass

    writer_thread = Thread(target=write_request, daemon=True)
    writer_thread.start()

    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except OSError:
            pass
        try:
            process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            pass
        stdout_thread.join(timeout=1.0)
        stderr_thread.join(timeout=1.0)
        writer_thread.join(timeout=1.0)
        raise StrictCaptureError("capture_rpc_unknown", operation_uncertain=True) from None
    stdout_thread.join(timeout=1.0)
    stderr_thread.join(timeout=1.0)
    writer_thread.join(timeout=1.0)

    if (
        write_failed.is_set()
        or stdout_overflow.is_set()
        or stderr_overflow.is_set()
        or stdout_thread.is_alive()
        or stderr_thread.is_alive()
        or writer_thread.is_alive()
    ):
        raise StrictCaptureError("capture_rpc_unknown", operation_uncertain=True)
    try:
        stdout_text = bytes(stdout_data).decode("utf-8", errors="strict")
        decoded = json.loads(
            stdout_text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
        raise StrictCaptureError("capture_rpc_unknown", operation_uncertain=True) from None
    if type(decoded) is not dict or not _bounded_depth(decoded):
        raise StrictCaptureError("capture_rpc_unknown", operation_uncertain=True)
    if process.returncode != 0 and decoded.get("ok") is not False:
        raise StrictCaptureError("capture_rpc_unknown", operation_uncertain=True)
    # stderr is retained only within its fixed cap; it is never decoded,
    # logged, or included in a public exception/artifact.
    return decoded, len(stdout_data)


class SerialwrapCaptureBindingClient:
    """One explicit trusted endpoint and a cumulative bounded stdout budget."""

    def __init__(self, binary: str, socket: str) -> None:
        if type(binary) is not str or not binary or type(socket) is not str or not socket:
            raise ValueError("strict capture requires an explicit provider target")
        self._binary = binary
        self._socket = socket
        self._stdout_bytes = 0

    def call(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        timeout = _ACTION_TIMEOUTS.get(action)
        if timeout is None:
            raise StrictCaptureError("capture_protocol_invalid")
        stdout_limit = (
            MAX_CAPABILITY_STDOUT_BYTES
            if action == "capabilities"
            else MAX_CAPTURE_PAGE_STDOUT_BYTES
        )
        remaining_budget = min(MAX_CAPTURE_RUN_STDOUT_BYTES, MAX_CAPTURE_TOTAL_BYTES) - self._stdout_bytes
        if remaining_budget <= 0:
            raise StrictCaptureError("capture_run_output_limit")
        response, raw_bytes = _run_bounded_json_command(
            capture_cli_argv(self._binary, self._socket, action),
            payload,
            timeout=timeout,
            stdout_limit=min(stdout_limit, remaining_budget),
        )
        self._stdout_bytes += raw_bytes
        return response
