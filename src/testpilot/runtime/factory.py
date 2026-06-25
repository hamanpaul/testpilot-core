"""Factory for RunBackend instances.

Usage::

    from testpilot.runtime.factory import create_run_backend

    backend = create_run_backend(None, {})           # default: serialwrap
    backend = create_run_backend("serialwrap", cfg)  # explicit serialwrap
    backend = create_run_backend("direct_tty", cfg)  # stub (NotImplemented)
    backend = create_run_backend("ttyusb", cfg)      # alias for direct_tty
"""

from __future__ import annotations

from typing import Any

from testpilot.runtime.run_backend import RunBackend


def create_run_backend(
    kind: str | None,
    config: dict[str, Any],
) -> RunBackend:
    """Instantiate and return the appropriate RunBackend.

    Args:
        kind: Backend identifier. Normalized aliases:
              ``None``/``""``/``"serial"``/``"serialwrap"`` → serialwrap,
              ``"direct_tty"``/``"ttyusb"`` → direct_tty.
        config: Provider-specific config dict.  For serialwrap the key
                ``"serialwrap_binary"`` is forwarded if present.
    """
    normalized = (kind or "serialwrap").strip().lower()

    if normalized in ("", "serial", "serialwrap"):
        from testpilot.runtime.serialwrap_backend import SerialwrapBackend
        return SerialwrapBackend(
            serialwrap_binary=config.get("serialwrap_binary") if config else None,
        )
    if normalized in ("direct_tty", "ttyusb"):
        from testpilot.runtime.direct_tty_backend import DirectTtyBackend
        return DirectTtyBackend()
    raise ValueError(f"Unknown RunBackend kind: {kind!r}")
