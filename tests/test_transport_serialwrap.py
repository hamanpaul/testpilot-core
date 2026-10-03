"""Tests for serialwrap transport."""

from __future__ import annotations

import json
import re
import subprocess
from typing import Any

import pytest

from testpilot.serialwrap_binary import SERIALWRAP_BIN_ENV
from testpilot.transport.serialwrap import SerialWrapCommandError, SerialWrapTransport


def _cp(args: list[str], payload: dict[str, Any], returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=args,
        returncode=returncode,
        stdout=json.dumps(payload),
        stderr="",
    )


@pytest.fixture(autouse=True)
def _clear_serialwrap_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(SERIALWRAP_BIN_ENV, raising=False)


def test_connect_resolves_by_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "testpilot.transport.serialwrap.resolve_serialwrap_binary",
        lambda configured_bin, *, config_label: str(configured_bin),
    )

    def fake_run(
        args: list[str],
        capture_output: bool,
        text: bool,
        check: bool,
        timeout: float | None,
        encoding: str | None = None,
        errors: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        assert capture_output is True
        assert text is True
        assert check is False
        assert timeout is not None
        assert args[0] == "/tmp/serialwrap"
        assert args[1:3] == ["session", "list"]
        return _cp(
            args,
            {
                "ok": True,
                "sessions": [
                    {
                        "alias": "dut-main",
                        "com": "COM7",
                        "session_id": "lab:COM7",
                        "state": "READY",
                    }
                ],
            },
        )

    monkeypatch.setattr("testpilot.transport.serialwrap.subprocess.run", fake_run)
    transport = SerialWrapTransport({"binary": "/tmp/serialwrap", "alias": "dut-main"})
    transport.connect()

    assert transport.is_connected is True
    assert transport.session is not None
    assert transport.session["session_id"] == "lab:COM7"


def test_connect_attaches_when_session_is_attached(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(
        args: list[str],
        capture_output: bool,
        text: bool,
        check: bool,
        timeout: float | None,
        encoding: str | None = None,
        errors: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del capture_output, text, check, timeout, encoding, errors
        op = tuple(args[1:3])

        if op == ("session", "list"):
            return _cp(
                args,
                {
                    "ok": True,
                    "sessions": [
                        {
                            "alias": "dut-main",
                            "com": "COM0",
                            "session_id": "lab:COM0",
                            "state": "ATTACHED",
                        }
                    ],
                },
            )

        if op == ("session", "attach"):
            return _cp(
                args,
                {
                    "ok": True,
                    "session": {
                        "alias": "dut-main",
                        "com": "COM0",
                        "session_id": "lab:COM0",
                        "state": "READY",
                    },
                },
            )

        raise AssertionError(f"unexpected subprocess call: {args}")

    monkeypatch.setattr("testpilot.transport.serialwrap.subprocess.run", fake_run)
    transport = SerialWrapTransport({"binary": "/tmp/serialwrap", "alias": "dut-main"})
    transport.connect()

    assert transport.is_connected is True
    assert transport.session is not None
    assert transport.session["state"] == "READY"


def test_connect_uses_configured_session_timeouts(monkeypatch: pytest.MonkeyPatch) -> None:
    seen_timeouts: list[tuple[tuple[str, str], float | None]] = []

    def fake_run(
        args: list[str],
        capture_output: bool,
        text: bool,
        check: bool,
        timeout: float | None,
        encoding: str | None = None,
        errors: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del capture_output, text, check
        op = tuple(args[1:3])
        seen_timeouts.append((op, timeout))

        if op == ("session", "list"):
            return _cp(
                args,
                {
                    "ok": True,
                    "sessions": [
                        {
                            "alias": "dut-main",
                            "com": "COM0",
                            "session_id": "lab:COM0",
                            "state": "ATTACHED",
                        }
                    ],
                },
            )

        if op == ("session", "attach"):
            return _cp(
                args,
                {
                    "ok": True,
                    "session": {
                        "alias": "dut-main",
                        "com": "COM0",
                        "session_id": "lab:COM0",
                        "state": "READY",
                    },
                },
            )

        raise AssertionError(f"unexpected subprocess call: {args}")

    monkeypatch.setattr("testpilot.transport.serialwrap.subprocess.run", fake_run)
    transport = SerialWrapTransport(
        {
            "binary": "/tmp/serialwrap",
            "alias": "dut-main",
            "session_list_timeout": 12.5,
            "session_attach_timeout": 18.0,
        }
    )
    transport.connect()

    assert seen_timeouts == [
        (("session", "list"), 12.5),
        (("session", "list"), 12.5),
        (("session", "attach"), 18.0),
    ]


def test_connect_retries_after_transient_list_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    state = {"list_calls": 0}

    def fake_run(
        args: list[str],
        capture_output: bool,
        text: bool,
        check: bool,
        timeout: float | None,
        encoding: str | None = None,
        errors: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del capture_output, text, check, timeout, encoding, errors
        op = tuple(args[1:3])

        if op == ("session", "list"):
            state["list_calls"] += 1
            if state["list_calls"] == 1:
                return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="")
            return _cp(
                args,
                {
                    "ok": True,
                    "sessions": [
                        {
                            "alias": "dut-main",
                            "com": "COM0",
                            "session_id": "lab:COM0",
                            "state": "READY",
                        }
                    ],
                },
            )

        raise AssertionError(f"unexpected subprocess call: {args}")

    monkeypatch.setattr("testpilot.transport.serialwrap.subprocess.run", fake_run)
    transport = SerialWrapTransport(
        {
            "binary": "/tmp/serialwrap",
            "alias": "dut-main",
            "connect_attempts": 2,
            "connect_retry_delay": 0.0,
        }
    )
    transport.connect()

    assert transport.is_connected is True
    assert state["list_calls"] == 2


def test_connect_resolves_by_serial_port(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(
        args: list[str],
        capture_output: bool,
        text: bool,
        check: bool,
        timeout: float | None,
        encoding: str | None = None,
        errors: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        assert args[1:3] == ["session", "list"]
        return _cp(
            args,
            {
                "ok": True,
                "sessions": [
                    {
                        "alias": "dut-main",
                        "com": "COM2",
                        "session_id": "lab:COM2",
                        "device_by_id": "/dev/serial/by-id/usb-target-2",
                        "state": "READY",
                    }
                ],
            },
        )

    monkeypatch.setattr("testpilot.transport.serialwrap.subprocess.run", fake_run)
    transport = SerialWrapTransport(
        {
            "binary": "/tmp/serialwrap",
            "serial_port": "/dev/serial/by-id/usb-target-2",
        }
    )
    transport.connect()

    assert transport.is_connected is True
    assert transport.session is not None
    assert transport.session["com"] == "COM2"


def test_execute_submit_poll_and_command_status(monkeypatch: pytest.MonkeyPatch) -> None:
    state = {
        "status_calls": 0,
    }

    def fake_run(
        args: list[str],
        capture_output: bool,
        text: bool,
        check: bool,
        timeout: float | None,
        encoding: str | None = None,
        errors: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del capture_output, text, check, timeout, encoding, errors
        op = tuple(args[1:3])

        if op == ("session", "list"):
            return _cp(
                args,
                {
                    "ok": True,
                    "sessions": [
                        {
                            "alias": "dut-main",
                            "com": "COM0",
                            "session_id": "lab:COM0",
                            "state": "READY",
                        }
                    ],
                },
            )

        if op == ("cmd", "submit"):
            command_text = args[args.index("--cmd") + 1]
            assert command_text == "echo hello"
            return _cp(
                args,
                {
                    "ok": True,
                    "cmd_id": "cmd-001",
                    "status": "accepted",
                },
            )

        if op == ("cmd", "status"):
            state["status_calls"] += 1
            if state["status_calls"] == 1:
                return _cp(
                    args,
                    {
                        "ok": True,
                        "command": {
                            "cmd_id": "cmd-001",
                            "status": "running",
                        },
                    },
                )
            return _cp(
                args,
                {
                    "ok": True,
                    "command": {
                        "cmd_id": "cmd-001",
                        "status": "done",
                        "error_code": None,
                        "stdout": "hello world",
                        "partial": False,
                        "background_capture_id": None,
                        "interactive_session_id": None,
                        "recovery_action": None,
                        "execution_mode": "line",
                        "command": "echo hello",
                    },
                },
            )

        raise AssertionError(f"unexpected subprocess call: {args}")

    monkeypatch.setattr("testpilot.transport.serialwrap.subprocess.run", fake_run)
    transport = SerialWrapTransport(
        {
            "binary": "/tmp/serialwrap",
            "selector": "COM0",
            "poll_interval": 0.0,
        }
    )
    transport.connect()
    result = transport.execute("echo hello", timeout=5.0)

    assert result["returncode"] == 0
    assert "hello world" in result["stdout"]
    assert result["stderr"] == ""
    assert result["elapsed"] >= 0.0
    assert result["cmd_id"] == "cmd-001"
    assert result["execution_mode"] == "line"
    assert result["background_capture_id"] is None
    assert state["status_calls"] >= 2


def test_execute_returns_empty_stdout_when_command_stdout_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = {"status_calls": 0}

    def fake_run(
        args: list[str],
        capture_output: bool,
        text: bool,
        check: bool,
        timeout: float | None,
        encoding: str | None = None,
        errors: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del capture_output, text, check, timeout, encoding, errors
        op = tuple(args[1:3])

        if op == ("session", "list"):
            return _cp(
                args,
                {
                    "ok": True,
                    "sessions": [
                        {
                            "alias": "dut-main",
                            "com": "COM0",
                            "session_id": "lab:COM0",
                            "state": "READY",
                        }
                    ],
                },
            )

        if op == ("cmd", "submit"):
            return _cp(args, {"ok": True, "cmd_id": "cmd-002", "status": "accepted"})

        if op == ("cmd", "status"):
            state["status_calls"] += 1
            return _cp(
                args,
                {
                    "ok": True,
                    "command": {
                        "cmd_id": "cmd-002",
                        "status": "done",
                        "error_code": None,
                        "stdout": "",
                        "partial": False,
                        "background_capture_id": None,
                        "interactive_session_id": None,
                        "recovery_action": None,
                        "execution_mode": "line",
                        "command": "uname -a",
                    },
                },
            )

        raise AssertionError(f"unexpected subprocess call: {args}")

    monkeypatch.setattr("testpilot.transport.serialwrap.subprocess.run", fake_run)
    transport = SerialWrapTransport(
        {
            "binary": "/tmp/serialwrap",
            "selector": "COM0",
            "poll_interval": 0.0,
        }
    )
    transport.connect()
    result = transport.execute("uname -a", timeout=5.0)

    assert result["returncode"] == 0
    assert result["stdout"] == ""
    assert result["stderr"] == ""
    assert state["status_calls"] == 1


def test_execute_treats_interactive_status_as_terminal_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = {"status_calls": 0}

    def fake_run(
        args: list[str],
        capture_output: bool,
        text: bool,
        check: bool,
        timeout: float | None,
        encoding: str | None = None,
        errors: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del capture_output, text, check, timeout, encoding, errors
        op = tuple(args[1:3])

        if op == ("session", "list"):
            return _cp(
                args,
                {
                    "ok": True,
                    "sessions": [
                        {
                            "alias": "dut-main",
                            "com": "COM0",
                            "session_id": "lab:COM0",
                            "state": "READY",
                        }
                    ],
                },
            )

        if op == ("cmd", "submit"):
            return _cp(args, {"ok": True, "cmd_id": "cmd-interactive", "status": "accepted"})

        if op == ("cmd", "status"):
            state["status_calls"] += 1
            return _cp(
                args,
                {
                    "ok": True,
                    "command": {
                        "cmd_id": "cmd-interactive",
                        "status": "interactive",
                        "error_code": None,
                        "stdout": "DriverSmoothedRSSI=-7",
                        "partial": False,
                        "background_capture_id": None,
                        "interactive_session_id": "isess-001",
                        "recovery_action": None,
                        "execution_mode": "interactive",
                        "command": "stateful multiline shell",
                    },
                },
            )

        raise AssertionError(f"unexpected subprocess call: {args}")

    monkeypatch.setattr("testpilot.transport.serialwrap.subprocess.run", fake_run)
    transport = SerialWrapTransport(
        {
            "binary": "/tmp/serialwrap",
            "selector": "COM0",
            "poll_interval": 0.0,
        }
    )
    transport.connect()
    result = transport.execute("stateful multiline shell", timeout=5.0)

    assert result["returncode"] == 0
    assert result["status"] == "interactive"
    assert result["stdout"] == "DriverSmoothedRSSI=-7"
    assert result["stderr"] == ""
    assert result["execution_mode"] == "interactive"
    assert result["interactive_session_id"] == "isess-001"
    assert state["status_calls"] == 1


def test_execute_retries_submit_after_session_not_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    state = {
        "submit_calls": 0,
        "attach_calls": 0,
    }

    def fake_run(
        args: list[str],
        capture_output: bool,
        text: bool,
        check: bool,
        timeout: float | None,
        encoding: str | None = None,
        errors: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del capture_output, text, check, timeout, encoding, errors
        op = tuple(args[1:3])

        if op == ("session", "list"):
            return _cp(
                args,
                {
                    "ok": True,
                    "sessions": [
                        {
                            "alias": "dut-main",
                            "com": "COM0",
                            "session_id": "lab:COM0",
                            "state": "READY",
                        }
                    ],
                },
            )

        if op == ("cmd", "submit"):
            state["submit_calls"] += 1
            if state["submit_calls"] == 1:
                return _cp(
                    args,
                    {
                        "ok": False,
                        "error_code": "SESSION_NOT_READY",
                        "session": {"state": "ATTACHED"},
                    },
                )
            return _cp(args, {"ok": True, "cmd_id": "cmd-004", "status": "accepted"})

        if op == ("session", "attach"):
            state["attach_calls"] += 1
            return _cp(
                args,
                {
                    "ok": True,
                    "session": {
                        "alias": "dut-main",
                        "com": "COM0",
                        "session_id": "lab:COM0",
                        "state": "READY",
                    },
                },
            )

        if op == ("cmd", "status"):
            return _cp(
                args,
                {
                    "ok": True,
                    "command": {
                        "cmd_id": "cmd-004",
                        "status": "done",
                        "error_code": None,
                        "stdout": "ok",
                        "partial": False,
                        "background_capture_id": None,
                        "interactive_session_id": None,
                        "recovery_action": None,
                        "execution_mode": "line",
                        "command": "echo ok",
                    },
                },
            )

        raise AssertionError(f"unexpected subprocess call: {args}")

    monkeypatch.setattr("testpilot.transport.serialwrap.subprocess.run", fake_run)
    transport = SerialWrapTransport(
        {
            "binary": "/tmp/serialwrap",
            "selector": "COM0",
            "poll_interval": 0.0,
        }
    )
    transport.connect()
    result = transport.execute("echo ok", timeout=5.0)

    assert result["returncode"] == 0
    assert result["stdout"] == "ok"
    assert state["attach_calls"] == 1
    assert state["submit_calls"] == 2


def test_repeated_session_not_ready_has_one_attach_retry_and_preserves_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = {"submit_calls": 0, "attach_calls": 0}
    retry_error = {
        "ok": False,
        "error_code": "SESSION_NOT_READY",
        "retryable": True,
        "message": "session still settling",
    }

    def fake_run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        del kwargs
        if args[1:3] == ["cmd", "submit"]:
            state["submit_calls"] += 1
            return _cp(args, retry_error)
        raise AssertionError(f"unexpected subprocess call: {args}")

    transport = SerialWrapTransport.__new__(SerialWrapTransport)
    transport._binary = "/tmp/serialwrap"
    transport._socket = None
    transport._selector = "COM0"

    def fake_attach() -> dict[str, Any]:
        state["attach_calls"] += 1
        return {"ok": True, "session": {"state": "READY"}}

    transport._attach_session = fake_attach
    monkeypatch.setattr("testpilot.transport.serialwrap.subprocess.run", fake_run)

    with pytest.raises(SerialWrapCommandError) as caught:
        transport._run_json(["cmd", "submit", "--selector", "COM0"], timeout=3.0)

    assert caught.value.result == retry_error
    assert state == {"submit_calls": 2, "attach_calls": 1}


@pytest.mark.parametrize(
    "safety_fields",
    [
        {"outcome": "accepted", "retryable": True},
        {"outcome": "unknown", "retryable": True},
        {"ambiguous": True, "retryable": True},
        {"partial": True, "retryable": True},
        {"cmd_id": "cmd-accepted", "retryable": True},
        {"non_replayable": True, "retryable": True},
        {"retryable": False},
    ],
)
def test_session_not_ready_safety_evidence_blocks_attach_retry(
    safety_fields: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    error_payload = {
        "ok": False,
        "error_code": "SESSION_NOT_READY",
        **safety_fields,
    }
    state = {"submit_calls": 0, "attach_calls": 0}

    def fake_run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        del kwargs
        state["submit_calls"] += 1
        return _cp(args, error_payload)

    transport = SerialWrapTransport.__new__(SerialWrapTransport)
    transport._binary = "/tmp/serialwrap"
    transport._socket = None
    transport._selector = "COM0"

    def fake_attach() -> dict[str, Any]:
        state["attach_calls"] += 1
        return {"ok": True, "session": {"state": "READY"}}

    transport._attach_session = fake_attach
    monkeypatch.setattr("testpilot.transport.serialwrap.subprocess.run", fake_run)

    with pytest.raises(SerialWrapCommandError) as caught:
        transport._run_json(["cmd", "submit", "--selector", "COM0"], timeout=3.0)

    assert caught.value.result == error_payload
    assert state == {"submit_calls": 1, "attach_calls": 0}


def test_execute_timeout_preserves_unknown_outcome_without_attach(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = {
        "status_calls": 0,
        "attach_calls": 0,
    }

    def fake_run(
        args: list[str],
        capture_output: bool,
        text: bool,
        check: bool,
        timeout: float | None,
        encoding: str | None = None,
        errors: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del capture_output, text, check, timeout, encoding, errors
        op = tuple(args[1:3])

        if op == ("session", "list"):
            return _cp(
                args,
                {
                    "ok": True,
                    "sessions": [
                        {
                            "alias": "dut-main",
                            "com": "COM0",
                            "session_id": "lab:COM0",
                            "state": "READY",
                        }
                    ],
                },
            )

        if op == ("cmd", "submit"):
            return _cp(args, {"ok": True, "cmd_id": "cmd-timeout", "status": "accepted"})

        if op == ("cmd", "status"):
            state["status_calls"] += 1
            return _cp(
                args,
                {
                    "ok": True,
                    "command": {
                        "cmd_id": "cmd-timeout",
                        "status": "running",
                    },
                },
            )

        if op == ("session", "attach"):
            state["attach_calls"] += 1
            return _cp(
                args,
                {
                    "ok": True,
                    "session": {
                        "alias": "dut-main",
                        "com": "COM0",
                        "session_id": "lab:COM0",
                        "state": "READY",
                    },
                },
            )

        raise AssertionError(f"unexpected subprocess call: {args}")

    monkeypatch.setattr("testpilot.transport.serialwrap.subprocess.run", fake_run)
    transport = SerialWrapTransport(
        {
            "binary": "/tmp/serialwrap",
            "selector": "COM0",
            "poll_interval": 0.0,
        }
    )
    transport.connect()
    result = transport.execute("sleep 10", timeout=0.0)

    assert result["returncode"] == 124
    assert result["status"] == "timeout"
    assert result["cmd_id"] == "cmd-timeout"
    assert result["execution_mode"] == "line"
    assert result["recovery_action"] is None
    assert result["outcome"] == "unknown"
    assert result["non_replayable"] is True
    assert result["retryable"] is False
    assert state["attach_calls"] == 0
    assert "serialwrap cmd status timeout" in result["stderr"]
    assert state["status_calls"] >= 1


def test_execute_normalizes_legacy_mode_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    state = {"submit_mode": None}

    def fake_run(
        args: list[str],
        capture_output: bool,
        text: bool,
        check: bool,
        timeout: float | None,
        encoding: str | None = None,
        errors: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del capture_output, text, check, timeout, encoding, errors
        op = tuple(args[1:3])

        if op == ("session", "list"):
            return _cp(
                args,
                {
                    "ok": True,
                    "sessions": [
                        {
                            "alias": "dut-main",
                            "com": "COM0",
                            "session_id": "lab:COM0",
                            "state": "READY",
                        }
                    ],
                },
            )

        if op == ("cmd", "submit"):
            state["submit_mode"] = args[args.index("--mode") + 1]
            return _cp(args, {"ok": True, "cmd_id": "cmd-003", "status": "accepted"})

        if op == ("cmd", "status"):
            return _cp(
                args,
                {
                    "ok": True,
                    "command": {
                        "cmd_id": "cmd-003",
                        "status": "done",
                        "error_code": None,
                        "stdout": "ok",
                        "partial": False,
                        "background_capture_id": None,
                        "interactive_session_id": None,
                        "recovery_action": None,
                        "execution_mode": "line",
                        "command": "echo ok",
                    },
                },
            )

        raise AssertionError(f"unexpected subprocess call: {args}")

    monkeypatch.setattr("testpilot.transport.serialwrap.subprocess.run", fake_run)
    transport = SerialWrapTransport(
        {
            "binary": "/tmp/serialwrap",
            "selector": "COM0",
            "mode": "fg",
            "poll_interval": 0.0,
        }
    )
    transport.connect()
    result = transport.execute("echo ok", timeout=5.0)

    assert result["returncode"] == 0
    assert state["submit_mode"] == "line"


# ------------------------------------------------------------------
# Tempscript chunking tests
# ------------------------------------------------------------------


def test_sq_chunks_short_command():
    """Short commands produce a single chunk."""
    chunks = SerialWrapTransport._sq_chunks("echo hello")
    assert chunks == ["echo hello"]


def test_sq_chunks_preserves_single_quotes():
    """Single quotes are escaped as '\\'' and never split mid-escape."""
    chunks = SerialWrapTransport._sq_chunks("echo 'hello world'")
    assert len(chunks) >= 1
    # Just verify the escaping is present
    assert "'\\''" in "".join(chunks)


def test_sq_chunks_all_under_serial_limit():
    """Every generated printf command stays under _MAX_SERIAL_LINE_LENGTH."""
    from testpilot.transport.serialwrap import _MAX_SERIAL_LINE_LENGTH

    # 500-char command simulating a long STA_MAC chain
    cmd = "STA_MAC=$(ubus-cli 'WiFi.AccessPoint.1.AssociatedDevice.1.MACAddress?' | " + "A" * 400 + ")"
    chunks = SerialWrapTransport._sq_chunks(cmd)
    assert len(chunks) > 1
    for chunk in chunks:
        full = f"printf '%s\\n' '{chunk}' >> /tmp/_tp_cmd.sh"
        wire_bytes = len(full.encode("utf-8")) + 1
        assert wire_bytes <= _MAX_SERIAL_LINE_LENGTH, (
            f"chunk printf wire line too long: {wire_bytes} > {_MAX_SERIAL_LINE_LENGTH}"
        )


def test_sq_chunks_roundtrip():
    """Reassembled chunks reproduce the original command."""
    cmd = """OUT=$(ubus-cli "WiFi.AccessPoint.1.AssociatedDevice.1.SupportedHe160MCS?" 2>&1); printf '%s\\n' "$OUT"; printf '%s\\n' "$OUT" | sed -n 's/.*failed/error/p'"""
    chunks = SerialWrapTransport._sq_chunks(cmd)
    reassembled = "".join(chunks).replace("'\\''" , "'")
    assert reassembled == cmd


def test_execute_via_tempscript_stages_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Long commands are staged via printf chunks then executed with sh."""
    from testpilot.transport.serialwrap import _MAX_SERIAL_LINE_LENGTH

    submitted: list[str] = []

    def fake_submit(self, command, timeout=30.0, *, preserve_stdout=False):
        del self, timeout
        submitted.append(command)
        marker = re.search(r"TP([A-Za-z0-9_-]{16}):%s", command)
        assert marker is not None
        if ":%s:%s" in command:
            stdout = f"\nTP{marker.group(1)}:0:0\n"
        else:
            stdout = f"\nTP{marker.group(1)}:0\n"
        if not preserve_stdout:
            stdout = stdout.strip()
        return {
            "returncode": 0,
            "stdout": stdout,
            "stderr": "",
            "elapsed": 0.1,
            "cmd_id": "fake",
            "status": "done",
            "partial": False,
            "execution_mode": "line",
            "background_capture_id": None,
            "interactive_session_id": None,
            "recovery_action": None,
        }

    monkeypatch.setattr(SerialWrapTransport, "_submit_and_poll", fake_submit)

    transport = SerialWrapTransport.__new__(SerialWrapTransport)
    transport._connected = True
    transport._selector = "COM0"

    long_cmd = "echo " + "X" * 200
    transport.execute(long_cmd, timeout=10.0)

    # Must have printf staging commands + final sh command
    assert len(submitted) >= 3  # at least 2 chunks + sh
    assert submitted[0].startswith("printf '%s")
    assert " > " in submitted[0]  # first chunk uses >
    for mid in submitted[1:-1]:
        assert mid.startswith("printf '%s")
        assert " >> " in mid  # subsequent chunks use >>
    assert submitted[-1].startswith("(sh /tmp/t")
    assert "; rm -f /tmp/t" in submitted[-1]

    # Every submitted command includes framing within the UTF-8 byte limit.
    for cmd in submitted:
        wire_bytes = len(cmd.encode("utf-8")) + 1
        assert wire_bytes <= _MAX_SERIAL_LINE_LENGTH, (
            f"too long: {wire_bytes}"
        )


@pytest.mark.parametrize(
    "unsafe_fields",
    [
        {"outcome": "accepted"},
        {"outcome": "unknown"},
        {"outcome": "ambiguous"},
        {"ambiguous": True},
    ],
)
def test_execute_via_tempscript_stops_after_unsafe_staging_result(
    unsafe_fields: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    submitted: list[str] = []
    result = {"returncode": 0, "stdout": "", "stderr": "", **unsafe_fields}

    def fake_submit(
        self, command: str, timeout: float = 30.0, *, preserve_stdout: bool = False
    ) -> dict[str, Any]:
        del self, timeout
        del preserve_stdout
        submitted.append(command)
        return result

    monkeypatch.setattr(SerialWrapTransport, "_submit_and_poll", fake_submit)
    transport = SerialWrapTransport.__new__(SerialWrapTransport)
    transport._connected = True
    transport._selector = "COM0"

    actual = transport.execute("x" * 130, timeout=10.0)

    assert actual is not result
    assert actual["returncode"] == 124
    assert actual["outcome"] == "unknown"
    assert actual["non_replayable"] is True
    assert actual["original_broker_result"] == result
    assert len(submitted) == 1
    assert submitted[0].startswith("printf '%s")


@pytest.mark.parametrize(
    ("command", "expected_stage_transactions"),
    [
        ("x" * 120, 4),
        ("x" * 121, 4),
        (
            "pid=$(pgrep -f '/tmp/wl1_hapd.conf' 2>/dev/null | head -n1); "
            'if [ -n "$pid" ]; then kill -HUP "$pid" 2>/dev/null || true; fi',
            4,
        ),
        ("a" * 60 + "\n" + "b" * 60 + "\n" + "c" * 5, 5),
        ("'" * 130, 15),
    ],
)
def test_estimated_execute_budget_matches_submit_transactions(
    command: str,
    expected_stage_transactions: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    submitted_timeouts: list[float] = []

    def fake_submit(self, command, timeout=30.0, *, preserve_stdout=False):
        del self, preserve_stdout
        submitted_timeouts.append(timeout)
        marker = re.search(r"TP([A-Za-z0-9_-]{16}):%s", command)
        if marker is None:
            stdout = ""
        elif ":%s:%s" in command:
            stdout = f"\nTP{marker.group(1)}:0:0\n"
        else:
            stdout = f"\nTP{marker.group(1)}:0\n"
        return {"returncode": 0, "stdout": stdout, "stderr": "", "status": "done", "partial": False}

    monkeypatch.setattr(SerialWrapTransport, "_submit_and_poll", fake_submit)
    transport = SerialWrapTransport.__new__(SerialWrapTransport)
    transport._connected = True
    transport._selector = "COM0"
    transport._poll_interval = 0.25
    transport._session_list_timeout = 7.0
    transport._session_attach_timeout = 10.0

    estimate = transport.estimate_execute_time_budget_s(command, timeout=30.0)
    result = transport.execute(command, timeout=30.0)

    assert result["returncode"] == 0
    assert len(submitted_timeouts) == expected_stage_transactions + 1
    assert submitted_timeouts[:-1] == [10.0] * expected_stage_transactions
    assert submitted_timeouts[-1] == 30.0

    def transaction_budget(timeout: float) -> float:
        submit_timeout = timeout + 2.0
        status_timeout = min(timeout + 1.0, 5.0)
        return (
            submit_timeout
            + timeout
            + 1.0
            + 0.25
            + status_timeout
            + 7.0
            + 10.0
            + submit_timeout
            + 7.0
            + 10.0
            + status_timeout
        )

    assert estimate == pytest.approx(
        sum(transaction_budget(timeout) for timeout in submitted_timeouts)
    )


def test_estimated_execute_budget_includes_bounded_session_recovery() -> None:
    transport = SerialWrapTransport.__new__(SerialWrapTransport)
    transport._poll_interval = 0.25
    transport._session_list_timeout = 7.0
    transport._session_attach_timeout = 10.0

    timeout = 5.0
    estimate = transport.estimate_execute_time_budget_s("echo ok", timeout=timeout)
    submit_timeout = timeout + 2.0
    status_timeout = min(timeout + 1.0, 5.0)
    base = submit_timeout + timeout + 1.0 + 0.25 + status_timeout
    recovery = (
        transport._session_list_timeout
        + transport._session_attach_timeout
        + submit_timeout
        + transport._session_list_timeout
        + transport._session_attach_timeout
        + status_timeout
    )

    assert estimate == pytest.approx(base + recovery)


def test_estimated_execute_budget_includes_possible_device_identity_lookups() -> None:
    transport = SerialWrapTransport.__new__(SerialWrapTransport)
    transport._poll_interval = 0.0
    transport._session_list_timeout = 7.0
    transport._session_attach_timeout = 3.0
    transport._binding_params = {
        "selector": "COM0",
        "serial_port": "/dev/ttyUSB0",
    }

    estimate = transport.estimate_execute_time_budget_s("echo ok", timeout=1.0)
    submit_timeout = 3.0
    status_timeout = 2.0
    base = submit_timeout + 1.0 + 1.0 + status_timeout
    one_attach_retry = 7.0 + 2 * 5.0 + 3.0 + submit_timeout
    final_status_retry = 7.0 + 2 * 5.0 + 3.0 + status_timeout

    assert estimate == pytest.approx(base + one_attach_retry + final_status_retry)


def _public_session(
    *,
    state: str = "READY",
    profile: str | None = "prpl-template",
    device_by_id: str | None = "/dev/serial/by-id/expected-device",
    session_id: str = "prpl-template:COM0",
    com: str = "COM0",
    alias: str = "dut",
) -> dict[str, Any]:
    session: dict[str, Any] = {
        "session_id": session_id,
        "profile": profile,
        "com": com,
        "alias": alias,
        "act_no": None,
        "device_by_id": device_by_id,
        "platform": "linux",
        "profile_source": "operator",
        "command_capable": True,
        "state": state,
        "last_error": None,
        "vtty": "/dev/pts/7",
        "attached_real_path": "/dev/ttyUSB0",
    }
    if profile is None:
        session.pop("profile")
    if device_by_id is None:
        session.pop("device_by_id")
    return session


def _binding_transport(
    monkeypatch: pytest.MonkeyPatch,
    sessions: list[dict[str, Any]],
    *,
    selector: str | None = "COM0",
    serial_port: str = "/dev/serial/by-id/expected-device",
    attach_session: dict[str, Any] | None = None,
    attach_response: dict[str, Any] | None = None,
    devices: list[dict[str, Any]] | None = None,
    not_ready_submits: bool = False,
    device_list_state: dict[str, bool] | None = None,
) -> tuple[SerialWrapTransport, list[tuple[str, ...]]]:
    monkeypatch.setattr(
        "testpilot.transport.serialwrap.resolve_serialwrap_binary",
        lambda configured_bin, *, config_label: str(configured_bin),
    )
    calls: list[tuple[str, ...]] = []

    def fake_run(
        args: list[str],
        capture_output: bool,
        text: bool,
        check: bool,
        timeout: float | None,
        encoding: str | None = None,
        errors: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del capture_output, text, check, timeout, encoding, errors
        operation = tuple(args[1:3])
        calls.append(operation)
        if operation == ("session", "list"):
            return _cp(args, {"ok": True, "sessions": sessions})
        if operation == ("device", "list"):
            if device_list_state and device_list_state.get("not_ready"):
                return _cp(
                    args,
                    {
                        "ok": False,
                        "error_code": "SESSION_NOT_READY",
                        "retryable": True,
                    },
                )
            return _cp(args, {"ok": True, "devices": devices or []})
        if operation == ("session", "recover"):
            return _cp(args, {"ok": True})
        if operation == ("session", "attach") and attach_response is not None:
            return _cp(args, attach_response)
        if operation == ("session", "attach") and attach_session is not None:
            return _cp(args, {"ok": True, "session": attach_session})
        if operation == ("cmd", "submit") and not_ready_submits:
            return _cp(
                args,
                {
                    "ok": False,
                    "error_code": "SESSION_NOT_READY",
                    "retryable": True,
                },
            )
        pytest.fail(f"unexpected mutating or unsupported serialwrap call: {args[1:3]}")

    monkeypatch.setattr("testpilot.transport.serialwrap.subprocess.run", fake_run)
    config = {
        "binary": "/tmp/serialwrap",
        "serial_port": serial_port,
        "profile": "prpl-template",
        "connect_attempts": 1,
        "connect_retry_delay": 0.0,
    }
    if selector is not None:
        config["selector"] = selector
    transport = SerialWrapTransport(config)
    return transport, calls


@pytest.mark.parametrize(
    "session",
    [
        _public_session(
            device_by_id="/dev/serial/by-id/foreign-device",
            profile="prpl-template",
        ),
        _public_session(
            device_by_id="/dev/serial/by-id/expected-device",
            profile="other-profile",
        ),
        _public_session(device_by_id=None, profile="prpl-template"),
        _public_session(
            device_by_id="/dev/serial/by-id/expected-device",
            profile=None,
        ),
    ],
    ids=["foreign-physical-device", "wrong-profile", "missing-device-identity", "missing-profile"],
)
def test_connect_rejects_selector_identity_mismatch_before_any_mutation(
    session: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    transport, calls = _binding_transport(monkeypatch, [session])

    with pytest.raises(RuntimeError):
        transport.connect()

    with pytest.raises(RuntimeError, match="not connected"):
        transport.execute("echo must-not-run")
    with pytest.raises(RuntimeError, match="recover requires resolved selector"):
        transport.recover()
    assert calls == [("session", "list")]
    assert transport.is_connected is False
    assert transport.session is None


def test_connect_rejects_duplicate_selector_matches_before_attach(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, calls = _binding_transport(
        monkeypatch,
        [
            _public_session(session_id="first:COM0"),
            _public_session(session_id="second:COM0"),
        ],
    )

    with pytest.raises(RuntimeError):
        transport.connect()

    assert calls == [("session", "list")]
    assert transport.is_connected is False


def test_connect_accepts_ready_selector_with_matching_physical_device_and_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, calls = _binding_transport(monkeypatch, [_public_session()])

    transport.connect()

    assert transport.is_connected is True
    assert transport.session == _public_session()
    assert calls == [("session", "list")]


@pytest.mark.parametrize("serial_port", ["com0", r"\\.\COM0"])
def test_connect_accepts_matching_windows_com_selector(
    serial_port: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    transport, calls = _binding_transport(
        monkeypatch, [_public_session()], serial_port=serial_port
    )

    transport.connect()

    assert transport.is_connected is True
    assert calls == [("session", "list")]


def test_connect_accepts_matching_attached_selector_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attached = _public_session()
    attached["state"] = "READY"
    transport, calls = _binding_transport(
        monkeypatch,
        [_public_session(state="ATTACHED")],
        attach_session=attached,
    )

    transport.connect()

    assert transport.is_connected is True
    assert transport.session == attached
    assert calls == [
        ("session", "list"),
        ("session", "list"),
        ("session", "attach"),
    ]


def test_connect_rejects_identity_changed_by_attach_and_clears_selector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    foreign = _public_session(
        state="READY",
        profile="other-profile",
        device_by_id="/dev/serial/by-id/foreign-device",
    )
    transport, calls = _binding_transport(
        monkeypatch,
        [_public_session(state="ATTACHED")],
        attach_session=foreign,
    )

    with pytest.raises(RuntimeError):
        transport.connect()

    with pytest.raises(RuntimeError, match="not connected"):
        transport.execute("echo must-not-run")
    with pytest.raises(RuntimeError, match="recover requires resolved selector"):
        transport.recover()
    assert calls == [
        ("session", "list"),
        ("session", "list"),
        ("session", "attach"),
    ]
    assert transport.is_connected is False
    assert transport.session is None


def test_connect_rejects_attach_response_for_different_session_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    changed_session = _public_session(session_id="replacement:COM0")
    transport, calls = _binding_transport(
        monkeypatch,
        [_public_session(state="ATTACHED")],
        attach_session=changed_session,
    )

    with pytest.raises(RuntimeError):
        transport.connect()

    assert calls == [
        ("session", "list"),
        ("session", "list"),
        ("session", "attach"),
    ]
    assert transport.is_connected is False
    assert transport.session is None


def test_failed_reconnect_clears_previous_selector_before_execute_or_recover(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = [_public_session()]
    transport, calls = _binding_transport(
        monkeypatch,
        sessions,
        attach_session=_public_session(),
    )
    transport.connect()
    assert transport.is_connected is True

    sessions[0] = _public_session(device_by_id="/dev/serial/by-id/foreign-device")
    with pytest.raises(RuntimeError):
        transport.connect()

    with pytest.raises(RuntimeError, match="not connected"):
        transport.execute("echo must-not-run")
    with pytest.raises(RuntimeError, match="recover requires resolved selector"):
        transport.recover()
    assert calls == [("session", "list"), ("session", "list")]
    assert transport.is_connected is False
    assert transport.session is None


def test_explicit_selector_resolves_legacy_tty_path_to_expected_by_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, calls = _binding_transport(
        monkeypatch,
        [_public_session()],
        serial_port="/dev/ttyUSB0",
        devices=[
            {
                "by_id": "/dev/serial/by-id/expected-device",
                "real_path": "/dev/ttyUSB0",
                "com": "COM0",
            }
        ],
    )

    transport.connect()

    assert transport.is_connected is True
    assert calls == [("session", "list"), ("device", "list")]


def test_explicit_selector_rejects_ambiguous_tty_to_by_id_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, calls = _binding_transport(
        monkeypatch,
        [_public_session()],
        serial_port="/dev/ttyUSB0",
        devices=[
            {
                "by_id": "/dev/serial/by-id/expected-device",
                "real_path": "/dev/ttyUSB0",
                "com": "COM0",
            },
            {
                "by_id": "/dev/serial/by-id/foreign-device",
                "real_path": "/dev/ttyUSB0",
                "com": "COM1",
            },
        ],
    )

    with pytest.raises(RuntimeError):
        transport.connect()

    assert calls == [("session", "list"), ("device", "list")]
    assert transport.is_connected is False


def test_serial_port_only_legacy_tty_fallback_accepts_unique_com_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, calls = _binding_transport(
        monkeypatch,
        [_public_session()],
        selector=None,
        serial_port="/dev/ttyUSB0",
    )

    transport.connect()

    assert transport.is_connected is True
    assert calls == [("session", "list"), ("device", "list")]


def test_serial_port_only_legacy_tty_fallback_rejects_ambiguous_com_sessions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, calls = _binding_transport(
        monkeypatch,
        [
            _public_session(session_id="first:COM0"),
            _public_session(session_id="second:COM0"),
        ],
        selector=None,
        serial_port="/dev/ttyUSB0",
    )

    with pytest.raises(RuntimeError):
        transport.connect()

    assert calls == [("session", "list"), ("device", "list")]
    assert transport.is_connected is False


def test_recover_rechecks_live_session_before_recovery_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = [_public_session()]
    transport, calls = _binding_transport(
        monkeypatch,
        sessions,
        attach_session=_public_session(),
    )
    transport.connect()
    sessions[0] = _public_session(
        device_by_id="/dev/serial/by-id/foreign-device",
        profile="other-profile",
    )

    # The fake returns the original identity on attach; recovery must reject
    # the changed live binding before issuing either mutating operation.
    with pytest.raises(RuntimeError):
        transport.recover()

    assert calls == [("session", "list"), ("session", "list")]
    assert transport.is_connected is False
    assert transport.session is None
    with pytest.raises(RuntimeError, match="not connected"):
        transport.execute("reboot")
    assert calls == [("session", "list"), ("session", "list")]


@pytest.mark.parametrize(
    ("attach_state", "should_connect"),
    [("READY", True), ("ATTACHED", False)],
)
def test_recover_requires_matching_ready_attach_response(
    attach_state: str,
    should_connect: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, calls = _binding_transport(
        monkeypatch,
        [_public_session()],
        attach_session=_public_session(state=attach_state),
    )
    transport.connect()

    if should_connect:
        transport.recover()
        assert transport.is_connected is True
        assert transport.session == _public_session(state="READY")
    else:
        with pytest.raises(RuntimeError, match="READY session"):
            transport.recover()
        assert transport.is_connected is False
        assert transport.session is None
        with pytest.raises(RuntimeError, match="not connected"):
            transport.execute("reboot")

    assert calls == [
        ("session", "list"),
        ("session", "list"),
        ("session", "recover"),
        ("session", "list"),
        ("session", "attach"),
    ]


def test_session_not_ready_rechecks_binding_before_attach_and_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sessions = [_public_session()]
    transport, calls = _binding_transport(
        monkeypatch,
        sessions,
        attach_session=_public_session(),
        not_ready_submits=True,
    )
    transport.connect()
    sessions[0] = _public_session(
        device_by_id="/dev/serial/by-id/foreign-device",
        profile="other-profile",
    )

    with pytest.raises(RuntimeError):
        transport.execute("echo this-command-must-not-replay")

    assert calls == [
        ("session", "list"),
        ("cmd", "submit"),
        ("session", "list"),
    ]
    assert transport.is_connected is False
    assert transport.session is None
    with pytest.raises(RuntimeError, match="not connected"):
        transport.execute("reboot")
    assert calls == [
        ("session", "list"),
        ("cmd", "submit"),
        ("session", "list"),
    ]


@pytest.mark.parametrize(
    "attach_response",
    [
        {"ok": True},
        {"ok": True, "session": "malformed"},
        {"ok": True, "session": _public_session(state="ATTACHED")},
    ],
    ids=["missing-session", "nonmapping-session", "not-ready-session"],
)
def test_session_not_ready_requires_ready_attach_before_command_replay(
    attach_response: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    transport, calls = _binding_transport(
        monkeypatch,
        [_public_session()],
        attach_response=attach_response,
        not_ready_submits=True,
    )
    transport.connect()

    with pytest.raises(RuntimeError):
        transport.execute("echo must-not-replay-without-ready-attach")

    assert calls == [
        ("session", "list"),
        ("cmd", "submit"),
        ("session", "list"),
        ("session", "attach"),
    ]
    assert transport.is_connected is False
    assert transport.session is None


@pytest.mark.parametrize(
    "attach_session",
    [
        _public_session(profile="other-profile"),
        _public_session(device_by_id="/dev/serial/by-id/foreign-device"),
        _public_session(session_id="replacement:COM0"),
    ],
    ids=["wrong-profile", "wrong-device", "changed-session-id"],
)
def test_safe_retry_rejects_changed_attach_identity_and_clears_transport(
    attach_session: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    transport, calls = _binding_transport(
        monkeypatch,
        [_public_session()],
        attach_session=attach_session,
        not_ready_submits=True,
    )
    transport.connect()

    with pytest.raises(RuntimeError):
        transport.execute("echo must-not-replay-after-foreign-attach")

    assert calls == [
        ("session", "list"),
        ("cmd", "submit"),
        ("session", "list"),
        ("session", "attach"),
    ]
    assert transport.is_connected is False
    assert transport.session is None
    with pytest.raises(RuntimeError, match="not connected"):
        transport.execute("reboot")
    assert calls == [
        ("session", "list"),
        ("cmd", "submit"),
        ("session", "list"),
        ("session", "attach"),
    ]


def test_device_list_not_ready_does_not_trigger_nested_attach_or_command_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    device_list_state = {"not_ready": False}
    transport, calls = _binding_transport(
        monkeypatch,
        [_public_session()],
        serial_port="/dev/ttyUSB0",
        devices=[
            {
                "by_id": "/dev/serial/by-id/expected-device",
                "real_path": "/dev/ttyUSB0",
                "com": "COM0",
            }
        ],
        not_ready_submits=True,
        device_list_state=device_list_state,
    )
    transport.connect()
    device_list_state["not_ready"] = True

    with pytest.raises(RuntimeError):
        transport.execute("echo must-not-replay-after-metadata-error")

    assert calls == [
        ("session", "list"),
        ("device", "list"),
        ("cmd", "submit"),
        ("session", "list"),
        ("device", "list"),
    ]
    assert transport.is_connected is False
    assert transport.session is None
