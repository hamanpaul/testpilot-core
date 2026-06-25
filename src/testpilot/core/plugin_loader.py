"""PluginLoader — discover and load plugins from package entry points."""

from __future__ import annotations

from collections.abc import Iterable
from importlib import metadata
import logging
from pathlib import Path
import re
from typing import Any

from testpilot.core.plugin_base import IncompatiblePluginError, PluginBase

log = logging.getLogger(__name__)


def _parse_api_version(plugin_name: str, version: object, *, role: str) -> tuple[int, int]:
    subject = (
        f"plugin {plugin_name!r} {role} SDK API version"
        if role == "requested"
        else "testpilot SDK API version"
    )
    if not isinstance(version, str):
        raise IncompatiblePluginError(
            f"invalid {subject} {version!r}; expected major.minor"
        )
    match = re.fullmatch(r"(\d+)\.(\d+)", version)
    if not match:
        raise IncompatiblePluginError(
            f"invalid {subject} {version!r}; expected major.minor"
        )
    return int(match.group(1)), int(match.group(2))


def _check_api_compat(name: str, declared: object, api: object) -> None:
    """Validate plugin-declared SDK API compatibility."""
    if declared is None:
        raise IncompatiblePluginError(f"plugin {name!r} must declare api_version")

    plugin_major, plugin_minor = _parse_api_version(name, declared, role="requested")
    api_major, api_minor = _parse_api_version(name, api, role="provided")
    if plugin_major != api_major or api_minor < plugin_minor:
        raise IncompatiblePluginError(
            f"plugin {name!r} requested SDK API version {declared}, "
            f"but testpilot provides SDK API version {api}"
        )


def _entry_point_distribution_name(entry_point: Any) -> str:
    dist = getattr(entry_point, "dist", None)
    if dist is None:
        return "<unknown distribution>"
    dist_name = getattr(dist, "name", None)
    if isinstance(dist_name, str) and dist_name.strip():
        return dist_name
    dist_metadata = getattr(dist, "metadata", None)
    getter = getattr(dist_metadata, "get", None)
    if callable(getter):
        metadata_name = getter("Name")
        if isinstance(metadata_name, str) and metadata_name.strip():
            return metadata_name
    return str(dist)


class PluginLoader:
    """動態發現並載入 ``testpilot.plugins`` entry point 宣告的 plugin。"""

    ENTRY_POINT_GROUP = "testpilot.plugins"

    @classmethod
    def for_entry_points(cls) -> "PluginLoader":
        """Construct a loader for entry-point-only discovery."""
        return cls(Path())

    @classmethod
    def from_entry_points(cls, entry_points: Iterable[Any]) -> "PluginLoader":
        """Construct a loader from an explicit entry-point iterable."""
        loader = cls(Path())
        loader._entry_points = cls._normalize_entry_points(entry_points)
        return loader

    def __init__(self, plugins_dir: Path | str) -> None:
        self.plugins_dir = Path(plugins_dir)
        self._plugins: dict[str, PluginBase] = {}
        self._entry_points: dict[str, Any] | None = None

    @staticmethod
    def _normalize_entry_points(entry_points: Iterable[Any]) -> dict[str, Any]:
        grouped_entry_points: dict[str, list[Any]] = {}
        for entry_point in entry_points:
            grouped_entry_points.setdefault(entry_point.name, []).append(entry_point)
        duplicate_names = []
        for name, named_entry_points in sorted(grouped_entry_points.items()):
            if len(named_entry_points) < 2:
                continue
            distributions = ", ".join(
                sorted({_entry_point_distribution_name(entry_point) for entry_point in named_entry_points})
            )
            duplicate_names.append(f"{name}: {distributions}")
        if duplicate_names:
            raise ValueError(
                "duplicate testpilot.plugins entry point names detected: "
                + "; ".join(duplicate_names)
            )
        return {
            name: named_entry_points[0]
            for name, named_entry_points in grouped_entry_points.items()
        }

    def _discover_entry_points(self) -> dict[str, Any]:
        if self._entry_points is None:
            self._entry_points = self._normalize_entry_points(
                metadata.entry_points(group=self.ENTRY_POINT_GROUP)
            )
        return dict(self._entry_points)

    def discover(self) -> list[str]:
        """回傳已註冊的 plugin 名稱列表。"""
        return sorted(self._discover_entry_points())

    def load(self, name: str) -> PluginBase:
        """載入指定 plugin 並回傳其實例。"""
        if name in self._plugins:
            return self._plugins[name]

        entry_points = self._discover_entry_points()
        entry_point = entry_points.get(name)
        if entry_point is None:
            raise FileNotFoundError(f"plugin not found: {name}")

        plugin_cls: Any = entry_point.load()
        if not isinstance(plugin_cls, type) or not issubclass(plugin_cls, PluginBase):
            raise TypeError(f"Plugin class must inherit PluginBase: {plugin_cls}")

        from testpilot.api import API_VERSION

        _check_api_compat(name, getattr(plugin_cls, "api_version", None), API_VERSION)
        instance = plugin_cls()
        self._plugins[name] = instance
        log.info("loaded plugin: %s v%s", instance.name, instance.version)
        return instance

    def load_all(self) -> dict[str, PluginBase]:
        """載入所有已發現的 plugins。"""
        for name in self.discover():
            try:
                self.load(name)
            except IncompatiblePluginError:
                raise
            except Exception:
                log.exception("failed to load plugin: %s", name)
        return dict(self._plugins)

    @property
    def loaded(self) -> dict[str, PluginBase]:
        return dict(self._plugins)
