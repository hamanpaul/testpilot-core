"""Tests for transport factory — verifies correct instantiation of all transport types."""

from __future__ import annotations

import pytest

from testpilot.transport.base import StubTransport, TransportBase
from testpilot.transport.factory import create_transport
from testpilot.transport.serialwrap import SerialWrapTransport
from testpilot.transport.adb import AdbTransport
from testpilot.transport.ssh import SshTransport
from testpilot.transport.network import NetworkTransport


@pytest.fixture(autouse=True)
def _set_serialwrap_bin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure SERIALWRAP_BIN env var is set for transport factory tests."""
    monkeypatch.setenv("SERIALWRAP_BIN", "/tmp/serialwrap")


@pytest.mark.parametrize(
    "kind, expected_cls",
    [
        ("serialwrap", SerialWrapTransport),
        ("serial", SerialWrapTransport),
        ("adb", AdbTransport),
        ("ssh", SshTransport),
        ("network", NetworkTransport),
        ("stub", StubTransport),
    ],
)
def test_create_transport_returns_correct_type(kind: str, expected_cls: type):
    """Factory returns the expected transport class for each kind."""
    transport = create_transport(kind)
    assert isinstance(transport, expected_cls)
    assert isinstance(transport, TransportBase)


def test_create_transport_case_insensitive():
    """Kind is case-insensitive."""
    assert isinstance(create_transport("SERIALWRAP"), SerialWrapTransport)
    assert isinstance(create_transport("Ssh"), SshTransport)
    assert isinstance(create_transport("  ADB  "), AdbTransport)


def test_create_transport_unknown_kind_raises():
    """Unknown kind raises ValueError."""
    with pytest.raises(ValueError, match="unknown transport kind"):
        create_transport("bluetooth")


def test_create_transport_passes_config():
    """Config dict is forwarded to transport constructor."""
    cfg = {"serial_port": "/dev/ttyUSB0", "alias": "dut"}
    transport = create_transport("serialwrap", cfg)
    assert isinstance(transport, SerialWrapTransport)


def test_create_transport_none_config():
    """None config doesn't crash."""
    transport = create_transport("stub", None)
    assert isinstance(transport, StubTransport)


def test_stub_transport_records_commands():
    """StubTransport records executed commands."""
    stub = create_transport("stub")
    assert isinstance(stub, StubTransport)
    result = stub.execute("echo hello")
    assert isinstance(result, dict)
