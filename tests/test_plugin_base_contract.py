"""Tests for PluginBase contract — verifies abstract interface enforcement."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from testpilot.core.plugin_base import PluginBase


def test_cannot_instantiate_bare_plugin_base():
    """PluginBase is abstract — cannot be instantiated directly."""
    with pytest.raises(TypeError):
        PluginBase()  # type: ignore[abstract]


def test_partial_implementation_missing_methods():
    """Subclass missing abstract methods cannot be instantiated."""

    class IncompletePlugin(PluginBase):
        @property
        def name(self) -> str:
            return "incomplete"

        @property
        def version(self) -> str:
            return "0.1"

    with pytest.raises(TypeError):
        IncompletePlugin()  # type: ignore[abstract]


def test_full_implementation_instantiates():
    """Subclass implementing all abstract methods can be instantiated."""

    class FullPlugin(PluginBase):
        @property
        def name(self) -> str:
            return "full"

        @property
        def version(self) -> str:
            return "1.0"

        def discover_cases(self) -> list[dict[str, Any]]:
            return []

        def setup_env(self, case: dict[str, Any], topology: Any) -> bool:
            return True

        def verify_env(self, case: dict[str, Any], topology: Any) -> bool:
            return True

        def execute_step(self, case: dict[str, Any], step: dict[str, Any], topology: Any) -> dict[str, Any]:
            return {"success": True, "output": ""}

        def evaluate(self, case: dict[str, Any], results: dict[str, Any]) -> bool:
            return True

        def teardown(self, case: dict[str, Any], topology: Any) -> None:
            pass

    plugin = FullPlugin()
    assert plugin.name == "full"
    assert plugin.version == "1.0"
    assert plugin.discover_cases() == []
    assert plugin.setup_env({}, None) is True
    assert plugin.verify_env({}, None) is True
    assert plugin.execute_step({}, {}, None) == {"success": True, "output": ""}
    assert plugin.evaluate({}, {}) is True


def test_cases_dir_default_property():
    """Default cases_dir points to plugin_base's parent / cases."""

    class MinPlugin(PluginBase):
        @property
        def name(self) -> str:
            return "min"

        @property
        def version(self) -> str:
            return "0.1"

        def discover_cases(self) -> list[dict[str, Any]]:
            return []

        def setup_env(self, case: dict[str, Any], topology: Any) -> bool:
            return True

        def verify_env(self, case: dict[str, Any], topology: Any) -> bool:
            return True

        def execute_step(self, case: dict[str, Any], step: dict[str, Any], topology: Any) -> dict[str, Any]:
            return {}

        def evaluate(self, case: dict[str, Any], results: dict[str, Any]) -> bool:
            return True

        def teardown(self, case: dict[str, Any], topology: Any) -> None:
            pass

    plugin = MinPlugin()
    assert isinstance(plugin.cases_dir, Path)
    assert plugin.cases_dir.name == "cases"


def test_abstract_method_set_is_complete():
    """PluginBase defines exactly the expected abstract methods."""
    expected_abstract = {"name", "discover_cases", "execute_step", "evaluate"}
    actual_abstract = set(PluginBase.__abstractmethods__)
    assert actual_abstract == expected_abstract
