"""ADB transport implementation."""

from __future__ import annotations

import subprocess
import time
from typing import Any

from .base import TransportBase


class AdbTransport(TransportBase):
    """Minimal ADB transport via subprocess."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = dict(config or {})
        self._binary = str(self._config.get("binary", "adb"))
        self._serial = self._config.get("serial")
        self._connected = False

    @property
    def transport_type(self) -> str:
        return "adb"

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self, **kwargs: Any) -> None:
        params = {**self._config, **kwargs}
        serial = params.get("serial")
        if serial is not None:
            self._serial = str(serial)
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def execute(self, command: str, timeout: float = 30.0) -> dict[str, Any]:
        if not self._connected:
            raise RuntimeError("adb transport is not connected")

        cmd = [self._binary]
        if self._serial:
            cmd.extend(["-s", str(self._serial)])
        cmd.extend(["shell", command])

        start = time.monotonic()
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=max(float(timeout), 0.1),
        )
        return {
            "returncode": int(completed.returncode),
            "stdout": (completed.stdout or "").strip(),
            "stderr": (completed.stderr or "").strip(),
            "elapsed": time.monotonic() - start,
        }
