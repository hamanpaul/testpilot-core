"""Tests for transport connect/disconnect lifecycle (E08).

Verifies connect/disconnect state transitions, resource cleanup,
and that transport_type is correctly reported.
"""

from __future__ import annotations

from typing import Any

import pytest

from testpilot.transport.base import StubTransport, TransportBase


class TestStubTransportLifecycle:
    """StubTransport state machine: disconnected → connected → disconnected."""

    def test_initial_state_disconnected(self):
        stub = StubTransport()
        assert stub.is_connected is False

    def test_connect_sets_connected(self):
        stub = StubTransport()
        stub.connect()
        assert stub.is_connected is True

    def test_disconnect_clears_connected(self):
        stub = StubTransport()
        stub.connect()
        stub.disconnect()
        assert stub.is_connected is False

    def test_double_connect_is_idempotent(self):
        stub = StubTransport()
        stub.connect()
        stub.connect()
        assert stub.is_connected is True

    def test_double_disconnect_is_idempotent(self):
        stub = StubTransport()
        stub.connect()
        stub.disconnect()
        stub.disconnect()
        assert stub.is_connected is False

    def test_transport_type(self):
        stub = StubTransport()
        assert stub.transport_type == "stub"

    def test_execute_records_commands(self):
        stub = StubTransport()
        stub.execute("echo hello")
        stub.execute("echo world")
        assert stub.history == ["echo hello", "echo world"]

    def test_execute_returns_expected_dict_shape(self):
        stub = StubTransport()
        result = stub.execute("test cmd", timeout=5.0)
        assert "returncode" in result
        assert "stdout" in result
        assert "stderr" in result
        assert "elapsed" in result
        assert result["returncode"] == 0

    def test_execute_stdout_contains_command(self):
        stub = StubTransport()
        result = stub.execute("ubus-cli get foo")
        assert "ubus-cli get foo" in result["stdout"]

    def test_history_starts_empty(self):
        stub = StubTransport()
        assert stub.history == []

    def test_reconnect_preserves_history(self):
        """History persists across connect/disconnect cycles."""
        stub = StubTransport()
        stub.connect()
        stub.execute("cmd1")
        stub.disconnect()
        stub.connect()
        stub.execute("cmd2")
        assert stub.history == ["cmd1", "cmd2"]


class TestTransportBaseABC:
    """Verify TransportBase cannot be instantiated and enforces interface."""

    def test_cannot_instantiate_transport_base(self):
        with pytest.raises(TypeError):
            TransportBase()  # type: ignore[abstract]

    def test_abstract_methods_defined(self):
        expected = {"transport_type", "connect", "disconnect", "execute", "is_connected"}
        assert set(TransportBase.__abstractmethods__) == expected

    def test_stub_is_subclass_of_transport_base(self):
        assert issubclass(StubTransport, TransportBase)
        assert isinstance(StubTransport(), TransportBase)
