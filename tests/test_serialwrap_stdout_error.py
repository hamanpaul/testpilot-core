"""Tests for issue #33: serialwrap non-zero exit errors must surface stdout.

serialwrap CLI failures are frequently reported on stdout (as an error JSON
payload) while stderr is empty — e.g. when systemd gates a daemon start.
Both ``_run_sw`` (runtime/_serialwrap_log.py) and ``_run_json``
(transport/serialwrap.py) previously only included stderr in the raised
``RuntimeError``, silently dropping the stdout payload.
"""

from __future__ import annotations

import subprocess

import pytest

from testpilot.runtime import _serialwrap_log
from testpilot.transport.serialwrap import SerialWrapTransport


@pytest.fixture(autouse=True)
def _set_serialwrap_bin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERIALWRAP_BIN", "/tmp/serialwrap")


# ---------------------------------------------------------------------------
# runtime/_serialwrap_log.py::_run_sw
# ---------------------------------------------------------------------------


def test_run_sw_error_includes_stdout_when_stderr_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(cmd, capture_output, text, check, timeout):  # noqa: ANN001
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=2,
            stdout='{"ok": false, "error_code": "DAEMON_GATE_DENIED"}',
            stderr="",
        )

    monkeypatch.setattr(_serialwrap_log.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError) as exc_info:
        _serialwrap_log._run_sw(["daemon", "start"])

    message = str(exc_info.value)
    assert "DAEMON_GATE_DENIED" in message
    assert "rc=2" in message


def test_run_sw_error_keeps_stderr_prefix_when_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(cmd, capture_output, text, check, timeout):  # noqa: ANN001
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=1,
            stdout="",
            stderr="permission denied",
        )

    monkeypatch.setattr(_serialwrap_log.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError) as exc_info:
        _serialwrap_log._run_sw(["daemon", "start"])

    message = str(exc_info.value)
    assert message.startswith("serialwrap failed: daemon start: permission denied")


# ---------------------------------------------------------------------------
# transport/serialwrap.py::_run_json
# ---------------------------------------------------------------------------


def _make_transport(monkeypatch: pytest.MonkeyPatch) -> SerialWrapTransport:
    monkeypatch.setattr(
        "testpilot.transport.serialwrap.resolve_serialwrap_binary",
        lambda configured_bin, *, config_label: str(configured_bin),
    )
    return SerialWrapTransport({"binary": "/tmp/serialwrap"})


def test_run_json_error_includes_stdout_when_stderr_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _make_transport(monkeypatch)

    def fake_run(args, capture_output, text, check, timeout):  # noqa: ANN001
        return subprocess.CompletedProcess(
            args=args,
            returncode=2,
            stdout='{"ok": false, "error_code": "DAEMON_GATE_DENIED"}',
            stderr="",
        )

    monkeypatch.setattr("testpilot.transport.serialwrap.subprocess.run", fake_run)

    with pytest.raises(RuntimeError) as exc_info:
        transport._run_json(["daemon", "start"])

    message = str(exc_info.value)
    assert "DAEMON_GATE_DENIED" in message
    assert "rc=2" in message


def test_run_json_error_keeps_stderr_prefix_when_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _make_transport(monkeypatch)

    def fake_run(args, capture_output, text, check, timeout):  # noqa: ANN001
        return subprocess.CompletedProcess(
            args=args,
            returncode=1,
            stdout="",
            stderr="permission denied",
        )

    monkeypatch.setattr("testpilot.transport.serialwrap.subprocess.run", fake_run)

    with pytest.raises(RuntimeError) as exc_info:
        transport._run_json(["daemon", "start"])

    message = str(exc_info.value)
    assert message.startswith(
        "serialwrap command failed: daemon start: permission denied"
    )
