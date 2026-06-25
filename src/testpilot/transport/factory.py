"""Transport factory."""

from __future__ import annotations

from typing import Any

from .adb import AdbTransport
from .base import StubTransport, TransportBase
from .network import NetworkTransport
from .serialwrap import SerialWrapTransport
from .ssh import SshTransport


def create_transport(kind: str, config: dict[str, Any] | None = None) -> TransportBase:
    """Create transport instance by kind."""
    normalized = kind.strip().lower()
    cfg = dict(config or {})

    if normalized in {"serialwrap", "serial"}:
        return SerialWrapTransport(cfg)
    if normalized == "adb":
        return AdbTransport(cfg)
    if normalized == "ssh":
        return SshTransport(cfg)
    if normalized == "network":
        return NetworkTransport(cfg)
    if normalized == "stub":
        return StubTransport()
    raise ValueError(f"unknown transport kind: {kind}")
