"""Explicit logical selectors must never bind by physical port enumeration."""
from unittest.mock import Mock

import pytest

from testpilot.runtime import _serialwrap_log as capture


def test_explicit_selector_ignores_swapped_serial_port(monkeypatch):
    calls = []
    monkeypatch.setattr(capture, "_list_devices", lambda: [{"real_path": "/dev/ttyUSB0", "by_id": "WRONG"}])
    monkeypatch.setattr(capture, "_resolve_bin", lambda: "serialwrap")
    monkeypatch.setattr(capture, "_run_sw", lambda args, **kw: {"ok": True, "sessions": [
        {"com": "COM0", "session_id": "prpl-template:COM0", "device_by_id": "DUT-STABLE"}]})
    proc = Mock(returncode=0)
    proc.communicate.return_value = ('{"ok":true}', '')
    monkeypatch.setattr(capture.subprocess, "Popen", lambda args, **kw: calls.append(args) or proc)
    capture.setup_sessions([{"selector": "COM0", "com": "COM0", "serial_port": "/dev/ttyUSB0"}], settle_delay=0)
    assert len(calls) == 1
    assert calls[0][1:3] == ["session", "attach"]
    assert "--device-by-id" not in calls[0]
    assert "prpl-template:COM0" in calls[0]


def test_unknown_explicit_selector_fails_before_any_write(monkeypatch):
    monkeypatch.setattr(capture, "_list_devices", lambda: [{"by_id": "first"}])
    monkeypatch.setattr(capture, "_run_sw", lambda *a, **kw: {"ok": True, "sessions": []})
    writes = Mock()
    monkeypatch.setattr(capture.subprocess, "Popen", writes)
    with pytest.raises(RuntimeError, match="selector.*COM0"):
        capture.setup_sessions([{"selector": "COM0", "com": "COM0", "serial_port": "/dev/ttyUSB0"}], settle_delay=0)
    writes.assert_not_called()
