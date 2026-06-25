"""Testbed config — parse testbed.yaml and provide device/variable lookup."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)


class TestbedConfig:
    """解析 testbed.yaml，提供裝置設定與變數替換。"""
    __test__ = False

    def __init__(self, config_path: Path | str) -> None:
        self.path = Path(config_path)
        self._raw: dict[str, Any] = {}
        self._data: dict[str, Any] = {}
        self._variables: dict[str, str] = {}
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            log.warning("testbed config not found: %s", self.path)
            return
        with open(self.path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        self._raw = raw if isinstance(raw, dict) else {}
        self._data = self._raw.get("testbed", self._raw)
        self._variables = {
            k: str(v) for k, v in self._data.get("variables", {}).items()
        }

    @property
    def raw(self) -> dict[str, Any]:
        """Return the full parsed YAML dict (before testbed extraction)."""
        return self._raw

    @property
    def name(self) -> str:
        return self._data.get("name", "unnamed")

    @property
    def devices(self) -> dict[str, Any]:
        return self._data.get("devices", {})

    @property
    def variables(self) -> dict[str, str]:
        return dict(self._variables)

    def get_device(self, role: str) -> dict[str, Any]:
        """依角色名稱取得裝置設定。"""
        dev = self.devices.get(role)
        if dev is None:
            raise KeyError(f"device not found: {role}")
        return dev

    def resolve(self, text: str) -> str:
        """替換 {{VAR}} 為 variables 中的值。"""
        def _repl(m: re.Match) -> str:
            key = m.group(1).strip()
            if key in self._variables:
                return self._variables[key]
            log.warning("unresolved variable: {{%s}}", key)
            return m.group(0)
        return re.sub(r"\{\{(.+?)\}\}", _repl, text)
