"""Generic network command transport implementation."""

from __future__ import annotations

import subprocess
import time
from typing import Any

from .base import TransportBase


class NetworkTransport(TransportBase):
    """Minimal network transport using local subprocess command execution."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = dict(config or {})
        self._runner = str(self._config.get("runner", "bash"))
        self._runner_args = self._normalize_args(self._config.get("runner_args", ["-lc"]))
        self._connected = False

    @property
    def transport_type(self) -> str:
        return "network"

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self, **kwargs: Any) -> None:
        params = {**self._config, **kwargs}
        runner = params.get("runner")
        if runner is not None:
            self._runner = str(runner)
        runner_args = params.get("runner_args")
        if runner_args is not None:
            self._runner_args = self._normalize_args(runner_args)
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def execute(self, command: str, timeout: float = 30.0) -> dict[str, Any]:
        if not self._connected:
            raise RuntimeError("network transport is not connected")

        start = time.monotonic()
        completed = subprocess.run(
            [self._runner, *self._runner_args, command],
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

    def _normalize_args(self, value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(v) for v in value]
        if isinstance(value, tuple):
            return [str(v) for v in value]
        return [str(value)]
