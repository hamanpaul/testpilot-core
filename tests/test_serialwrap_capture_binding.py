from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys
from typing import Any

import pytest

from testpilot.runtime.serialwrap_capture_binding import (
    MAX_CAPTURE_RUN_STDOUT_BYTES,
    MAX_CAPTURE_REQUEST_BYTES,
    SerialwrapCaptureBindingClient,
    _run_bounded_json_command,
    capture_cli_argv,
)
from testpilot.runtime.strict_capture import StrictCaptureError
from testpilot.runtime import serialwrap_capture_binding as client_module


def test_cli_argv_uses_only_sealed_api_11_routes() -> None:
    base = ["/opt/serialwrap", "--socket", "unix:///run/serialwrap.sock", "capture-binding"]
    assert capture_cli_argv(base[0], base[2], "capabilities") == [
        *base,
        "capabilities",
    ]
    assert capture_cli_argv(base[0], base[2], "begin") == [*base, "begin"]
    assert capture_cli_argv(base[0], base[2], "checkpoint") == [*base, "checkpoint"]
    assert capture_cli_argv(base[0], base[2], "status") == [*base, "status"]
    for action in ("mark", "range", "finish"):
        assert capture_cli_argv(base[0], base[2], action) == [
            *base,
            action,
            "--api-version",
            "1.1",
        ]
    with pytest.raises(ValueError):
        capture_cli_argv(base[0], base[2], "legacy-wal-export")


def _fake_cli(path: Path, body: str) -> str:
    path.write_text(
        f"#!{sys.executable}\nimport sys\n{body}\n",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return os.fspath(path)


def test_client_caps_raw_stdout_before_json_parse(tmp_path: Path) -> None:
    binary = _fake_cli(tmp_path / "fake-serialwrap", "sys.stdout.buffer.write(b'x' * 2048)")
    with pytest.raises(StrictCaptureError) as caught:
        _run_bounded_json_command(
            [binary],
            {},
            timeout=2.0,
            stdout_limit=64,
            stderr_limit=64,
        )
    assert caught.value.operation_uncertain is True
    assert str(caught.value) == "capture_rpc_unknown"


def test_client_rejects_invalid_utf8_and_exhausted_output_budget(tmp_path: Path) -> None:
    binary = _fake_cli(
        tmp_path / "fake-serialwrap",
        "sys.stdout.buffer.write(b'\\xff')",
    )
    with pytest.raises(StrictCaptureError, match="capture_rpc_unknown"):
        _run_bounded_json_command(
            [binary],
            {},
            timeout=2.0,
            stdout_limit=64,
            stderr_limit=64,
        )

    marker = tmp_path / "spawned-after-budget"
    binary = _fake_cli(
        tmp_path / "fake-serialwrap",
        f"from pathlib import Path; Path({str(marker)!r}).write_text('called')",
    )
    client = SerialwrapCaptureBindingClient(binary, "unix:///tmp/strict-fake.sock")
    client._stdout_bytes = MAX_CAPTURE_RUN_STDOUT_BYTES
    with pytest.raises(StrictCaptureError) as caught:
        client.call("status", {"operation_id": "00000000-0000-4000-8000-000000000000"})
    assert str(caught.value) == "capture_run_output_limit"
    assert caught.value.operation_uncertain is False
    assert not marker.exists()


def test_cumulative_stdout_limit_applies_before_json_parse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    binary = _fake_cli(
        tmp_path / "fake-serialwrap",
        "sys.stdout.buffer.write(b'not-json-and-over-the-remaining-budget')",
    )
    client = SerialwrapCaptureBindingClient(binary, "unix:///tmp/strict-fake.sock")
    client._stdout_bytes = MAX_CAPTURE_RUN_STDOUT_BYTES - 1
    parse_called = False

    def unexpected_parse(*args: Any, **kwargs: Any) -> Any:
        nonlocal parse_called
        parse_called = True
        return json.loads(*args, **kwargs)

    monkeypatch.setattr(client_module.json, "loads", unexpected_parse)
    with pytest.raises(StrictCaptureError) as caught:
        client.call("status", {"operation_id": "00000000-0000-4000-8000-000000000000"})

    assert caught.value.operation_uncertain is True
    assert parse_called is False


def test_client_caps_request_before_starting_process(tmp_path: Path) -> None:
    binary = _fake_cli(tmp_path / "fake-serialwrap", "print('{}')")
    client = SerialwrapCaptureBindingClient(binary, "unix:///tmp/strict-fake.sock")
    with pytest.raises(StrictCaptureError, match="capture_request_too_large"):
        client.call("begin", {"value": "x" * MAX_CAPTURE_REQUEST_BYTES})
