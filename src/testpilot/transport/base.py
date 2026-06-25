"""Transport base — abstract interface for device communication."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class TransportBase(ABC):
    """裝置通訊抽象介面。

    所有 transport（serial, adb, ssh, network）繼承此類別。
    """

    @property
    @abstractmethod
    def transport_type(self) -> str:
        """Transport 類型名稱，如 'serial', 'adb', 'ssh'。"""

    @abstractmethod
    def connect(self, **kwargs: Any) -> None:
        """建立連線。"""

    @abstractmethod
    def disconnect(self) -> None:
        """關閉連線。"""

    @abstractmethod
    def execute(self, command: str, timeout: float = 30.0) -> dict[str, Any]:
        """執行指令並回傳結果。

        Returns:
            dict with: returncode (int), stdout (str), stderr (str), elapsed (float)
        """

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """連線狀態。"""


class StubTransport(TransportBase):
    """Stub transport for testing — records commands without executing."""

    def __init__(self) -> None:
        self._connected = False
        self.history: list[str] = []

    @property
    def transport_type(self) -> str:
        return "stub"

    def connect(self, **kwargs: Any) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def execute(self, command: str, timeout: float = 30.0) -> dict[str, Any]:
        self.history.append(command)
        return {
            "returncode": 0,
            "stdout": f"[stub] {command}",
            "stderr": "",
            "elapsed": 0.0,
        }

    @property
    def is_connected(self) -> bool:
        return self._connected
