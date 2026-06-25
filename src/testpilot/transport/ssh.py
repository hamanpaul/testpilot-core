"""SSH transport implementation."""

from __future__ import annotations

import subprocess
import time
from typing import Any

from .base import TransportBase


class SshTransport(TransportBase):
    """Minimal SSH transport via subprocess."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = dict(config or {})
        self._binary = str(self._config.get("binary", "ssh"))
        self._host = self._config.get("host")
        self._user = self._config.get("user")
        self._port = int(self._config.get("port", 22))
        self._identity_file = self._config.get("identity_file")
        self._extra_args = self._normalize_extra_args(self._config.get("extra_args"))
        self._connected = False

    @property
    def transport_type(self) -> str:
        return "ssh"

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self, **kwargs: Any) -> None:
        params = {**self._config, **kwargs}
        host = params.get("host")
        if host:
            self._host = str(host)
        user = params.get("user")
        if user is not None:
            self._user = str(user)
        port = params.get("port")
        if port is not None:
            self._port = int(port)
        identity_file = params.get("identity_file")
        if identity_file is not None:
            self._identity_file = str(identity_file)
        extra_args = params.get("extra_args")
        if extra_args is not None:
            self._extra_args = self._normalize_extra_args(extra_args)

        if not self._host:
            raise ValueError("ssh transport requires host")
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def execute(self, command: str, timeout: float = 30.0) -> dict[str, Any]:
        if not self._connected or not self._host:
            raise RuntimeError("ssh transport is not connected")

        target = f"{self._user}@{self._host}" if self._user else str(self._host)
        cmd = [self._binary, "-p", str(self._port)]
        if self._identity_file:
            cmd.extend(["-i", str(self._identity_file)])
        cmd.extend(self._extra_args)
        cmd.extend([target, command])

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

    def _normalize_extra_args(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(v) for v in value]
        if isinstance(value, tuple):
            return [str(v) for v in value]
        return [str(value)]
