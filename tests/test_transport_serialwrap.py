"""Tests for serialwrap transport."""

from __future__ import annotations

import json
import subprocess
from typing import Any

import pytest

from testpilot.serialwrap_binary import SERIALWRAP_BIN_ENV
from testpilot.transport.serialwrap import SerialWrapTransport


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
    ) -> subprocess.CompletedProcess[str]:
        del capture_output, text, check, timeout
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
    ) -> subprocess.CompletedProcess[str]:
        del capture_output, text, check, timeout
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
    ) -> subprocess.CompletedProcess[str]:
        del capture_output, text, check, timeout
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
    ) -> subprocess.CompletedProcess[str]:
        del capture_output, text, check, timeout
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
    ) -> subprocess.CompletedProcess[str]:
        del capture_output, text, check, timeout
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
    ) -> subprocess.CompletedProcess[str]:
        del capture_output, text, check, timeout
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


def test_execute_timeout_attaches_and_returns_recovery_action(
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
    ) -> subprocess.CompletedProcess[str]:
        del capture_output, text, check, timeout
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
    assert result["recovery_action"] == "ATTACH"
    assert "serialwrap cmd status timeout" in result["stderr"]
    assert state["attach_calls"] == 1
    assert state["status_calls"] >= 1


def test_execute_normalizes_legacy_mode_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    state = {"submit_mode": None}

    def fake_run(
        args: list[str],
        capture_output: bool,
        text: bool,
        check: bool,
        timeout: float | None,
    ) -> subprocess.CompletedProcess[str]:
        del capture_output, text, check, timeout
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
    reassembled = "".join(chunks).replace("'\\'", "").replace("''", "")
    # Just verify the escaping is present
    assert "'\\''" in "".join(chunks)


def test_sq_chunks_all_under_serial_limit():
    """Every generated printf command stays under _MAX_SERIAL_LINE_LENGTH."""
    from testpilot.transport.serialwrap import _MAX_SERIAL_LINE_LENGTH, _TEMPSCRIPT

    # 500-char command simulating a long STA_MAC chain
    cmd = "STA_MAC=$(ubus-cli 'WiFi.AccessPoint.1.AssociatedDevice.1.MACAddress?' | " + "A" * 400 + ")"
    chunks = SerialWrapTransport._sq_chunks(cmd)
    assert len(chunks) > 1
    for chunk in chunks:
        full = f"printf '%s\\n' '{chunk}' >> {_TEMPSCRIPT}"
        assert len(full) <= _MAX_SERIAL_LINE_LENGTH, (
            f"chunk printf command too long: {len(full)} > {_MAX_SERIAL_LINE_LENGTH}"
        )


def test_sq_chunks_roundtrip():
    """Reassembled chunks reproduce the original command."""
    cmd = """OUT=$(ubus-cli "WiFi.AccessPoint.1.AssociatedDevice.1.SupportedHe160MCS?" 2>&1); printf '%s\\n' "$OUT"; printf '%s\\n' "$OUT" | sed -n 's/.*failed/error/p'"""
    chunks = SerialWrapTransport._sq_chunks(cmd)
    reassembled = "".join(chunks).replace("'\\''" , "'")
    assert reassembled == cmd


def test_execute_via_tempscript_stages_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Long commands are staged via printf chunks then executed with sh."""
    from testpilot.transport.serialwrap import _MAX_SERIAL_LINE_LENGTH, _TEMPSCRIPT

    submitted: list[str] = []

    def fake_submit(self, command, timeout=30.0):
        submitted.append(command)
        return {
            "returncode": 0,
            "stdout": "",
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
    assert submitted[-1].startswith(f"sh {_TEMPSCRIPT}")

    # All printf commands must be under the serial limit
    for cmd in submitted[:-1]:
        assert len(cmd) <= _MAX_SERIAL_LINE_LENGTH, f"too long: {len(cmd)}"
