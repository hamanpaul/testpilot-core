"""A rejected serial command must preserve broker decision evidence."""
import json
import subprocess

import pytest

from testpilot.transport.serialwrap import SerialWrapTransport


@pytest.mark.parametrize("rc", [0, 1])
def test_broker_rejection_keeps_structured_gate_fields(monkeypatch, rc):
    payload = {
        "ok": False, "error_code": "AUTOBOOT_QUIET",
        "retry_after_s": 3.5, "recommended_action": "wait",
        "non_replayable": False, "message": "boot quiet window",
    }
    monkeypatch.setattr(
        "testpilot.transport.serialwrap.subprocess.run",
        lambda *a, **kw: subprocess.CompletedProcess(a[0], rc, json.dumps(payload), ""),
    )
    transport = SerialWrapTransport({"binary": "/tmp/serialwrap"})
    with pytest.raises(RuntimeError) as caught:
        transport._run_json(["cmd", "submit", "--cmd", "echo marker"])
    assert caught.value.result["error_code"] == "AUTOBOOT_QUIET"
    assert caught.value.result["retry_after_s"] == 3.5
    assert caught.value.result["recommended_action"] == "wait"
    assert caught.value.result["non_replayable"] is False


def test_terminal_command_error_keeps_non_replayable_outcome(monkeypatch):
    terminal = {
        "status": "error", "error_code": "RX_BUSY",
        "stdout": "partial output", "partial": True,
        "non_replayable": True, "input_integrity": "uncertain",
        "recommended_action": "inspect", "tx_bytes": 19,
    }
    transport = SerialWrapTransport({"binary": "/tmp/serialwrap"})
    transport._selector = "COM0"
    monkeypatch.setattr(transport, "_run_json", lambda *a, **kw: {"cmd_id": "accepted"})
    monkeypatch.setattr(transport, "_poll_status", lambda *a: {"command": terminal})
    result = transport._submit_and_poll("echo marker")
    assert result["returncode"] != 0
    for field in ("error_code", "non_replayable", "input_integrity", "recommended_action", "tx_bytes"):
        assert result[field] == terminal[field]


def test_failed_script_stage_prevents_execution_of_partial_script(monkeypatch):
    transport = SerialWrapTransport({"binary": "/tmp/serialwrap"})
    calls = []
    def submit(command, timeout, *, preserve_stdout=False):
        del timeout, preserve_stdout
        calls.append(command)
        return {"returncode": 1, "status": "error", "error_code": "RX_BUSY", "non_replayable": True}
    monkeypatch.setattr(transport, "_submit_and_poll", submit)
    result = transport._execute_via_tempscript("echo " + "x" * 200, 30)
    assert result["returncode"] == 124
    assert result["outcome"] == "unknown"
    assert result["original_broker_result"]["error_code"] == "RX_BUSY"
    assert len(calls) == 1
    assert result["error_code"] == "RX_BUSY"
