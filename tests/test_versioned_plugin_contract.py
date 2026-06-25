"""versioned plugin contract（change versioned-plugin-contract）。"""

from __future__ import annotations

import re
from typing import Any

import click
import pytest


def test_api_version_is_semver():
    from testpilot.api import API_VERSION

    assert re.fullmatch(r"\d+\.\d+", API_VERSION)


def test_incompatible_error_exported():
    from testpilot.api import IncompatiblePluginError

    assert issubclass(IncompatiblePluginError, Exception)


@pytest.mark.parametrize(
    ("declared", "api", "ok"),
    [
        ("1.0", "1.0", True),
        ("1.0", "1.3", True),
        ("1.3", "1.0", False),
        ("2.0", "1.5", False),
        (None, "1.0", False),
    ],
)
def test_compat_matrix(declared, api, ok):
    from testpilot.api import IncompatiblePluginError
    from testpilot.core.plugin_loader import _check_api_compat

    if ok:
        _check_api_compat("dummy", declared, api)
    else:
        with pytest.raises(IncompatiblePluginError):
            _check_api_compat("dummy", declared, api)


def test_malformed_sdk_api_version_reports_sdk_side_error():
    from testpilot.api import IncompatiblePluginError
    from testpilot.core.plugin_loader import _check_api_compat

    with pytest.raises(
        IncompatiblePluginError,
        match=r"testpilot SDK API version 'bad'.*major\.minor",
    ):
        _check_api_compat("dummy", "1.0", "bad")


class _FakeEntryPoint:
    def __init__(self, name: str, plugin_cls: type) -> None:
        self.name = name
        self._plugin_cls = plugin_cls

    def load(self):
        return self._plugin_cls


def _plugin_class(name: str, api_version: Any) -> type:
    from testpilot.core.plugin_base import PluginBase

    class Plugin(PluginBase):
        @property
        def name(self) -> str:
            return name

        def discover_cases(self) -> list[dict[str, Any]]:
            return []

        def execute_step(
            self,
            case: dict[str, Any],
            step: dict[str, Any],
            topology: Any,
        ) -> dict[str, Any]:
            return {}

        def evaluate(self, case: dict[str, Any], results: dict[str, Any]) -> bool:
            return True

    Plugin.api_version = api_version
    return Plugin


def test_loader_accepts_compatible_plugin_and_caches_it():
    from testpilot.core.plugin_loader import PluginLoader

    loader = PluginLoader.from_entry_points([
        _FakeEntryPoint("dummy", _plugin_class("dummy", "1.0")),
    ])

    plugin = loader.load("dummy")

    assert plugin.name == "dummy"
    assert loader.loaded == {"dummy": plugin}


@pytest.mark.parametrize("declared", [None, "1", 1.0, "1.3", "2.0"])
def test_loader_rejects_incompatible_plugin_without_caching(declared):
    from testpilot.api import IncompatiblePluginError
    from testpilot.core.plugin_loader import PluginLoader

    loader = PluginLoader.from_entry_points([
        _FakeEntryPoint("dummy", _plugin_class("dummy", declared)),
    ])

    with pytest.raises(IncompatiblePluginError):
        loader.load("dummy")

    assert loader.loaded == {}


def test_loader_rejects_incompatible_plugin_before_instantiation():
    from testpilot.api import IncompatiblePluginError, PluginBase
    from testpilot.core.plugin_loader import PluginLoader

    class IncompatiblePlugin(PluginBase):
        api_version = "2.0"
        initialized = False

        def __init__(self) -> None:
            type(self).initialized = True

        @property
        def name(self) -> str:
            return "dummy"

        def discover_cases(self) -> list[dict[str, Any]]:
            return []

        def execute_step(
            self,
            case: dict[str, Any],
            step: dict[str, Any],
            topology: Any,
        ) -> dict[str, Any]:
            return {}

        def evaluate(self, case: dict[str, Any], results: dict[str, Any]) -> bool:
            return True

    loader = PluginLoader.from_entry_points([
        _FakeEntryPoint("dummy", IncompatiblePlugin),
    ])

    with pytest.raises(IncompatiblePluginError):
        loader.load("dummy")

    assert IncompatiblePlugin.initialized is False
    assert loader.loaded == {}


def test_loader_rejects_non_plugin_base_class_before_instantiation():
    from testpilot.core.plugin_loader import PluginLoader

    class NotAPlugin:
        api_version = "1.0"
        initialized = False

        def __init__(self) -> None:
            type(self).initialized = True

    loader = PluginLoader.from_entry_points([
        _FakeEntryPoint("dummy", NotAPlugin),
    ])

    with pytest.raises(TypeError, match="Plugin class must inherit PluginBase"):
        loader.load("dummy")

    assert NotAPlugin.initialized is False
    assert loader.loaded == {}


def test_load_all_rejects_incompatible_plugin_explicitly():
    from testpilot.api import IncompatiblePluginError
    from testpilot.core.plugin_loader import PluginLoader

    loader = PluginLoader.from_entry_points([
        _FakeEntryPoint("dummy", _plugin_class("dummy", "2.0")),
    ])

    with pytest.raises(IncompatiblePluginError):
        loader.load_all()

    assert loader.loaded == {}


def test_cli_wraps_incompatible_plugin_error(monkeypatch):
    from testpilot.api import IncompatiblePluginError
    from testpilot.cli_support import load_registered_plugin

    def raise_incompatible(self, name):
        del self, name
        raise IncompatiblePluginError("plugin 'dummy' must declare api_version")

    monkeypatch.setattr(
        "testpilot.core.plugin_loader.PluginLoader.load",
        raise_incompatible,
    )

    with pytest.raises(click.ClickException, match="api_version"):
        load_registered_plugin("dummy")
