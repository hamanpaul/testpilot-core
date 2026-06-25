"""Tests for PluginBase slim interface — verify default implementations."""

from __future__ import annotations

from typing import Any

import pytest

from testpilot.core.plugin_base import PluginBase


class _MinimalPlugin(PluginBase):
    """Implements only the four required abstract members."""

    @property
    def name(self) -> str:
        return "minimal"

    def discover_cases(self) -> list[dict[str, Any]]:
        return []

    def execute_step(
        self, case: dict[str, Any], step: dict[str, Any], topology: Any
    ) -> dict[str, Any]:
        return {"success": True, "output": "", "captured": {}, "timing": 0.0}

    def evaluate(self, case: dict[str, Any], results: dict[str, Any]) -> bool:
        return True


# -- instantiation ----------------------------------------------------------


def test_minimal_plugin_instantiates():
    """A plugin implementing only name, discover_cases, execute_step, evaluate
    can be instantiated without errors."""
    plugin = _MinimalPlugin()
    assert plugin.name == "minimal"


# -- default implementations ------------------------------------------------


def test_default_version():
    """Default version property returns '0.0.0'."""
    plugin = _MinimalPlugin()
    assert plugin.version == "0.0.0"


def test_default_setup_env_returns_true():
    """Default setup_env returns True (no setup needed)."""
    plugin = _MinimalPlugin()
    assert plugin.setup_env({}, None) is True


def test_default_verify_env_returns_true():
    """Default verify_env returns True (no verification needed)."""
    plugin = _MinimalPlugin()
    assert plugin.verify_env({}, None) is True


def test_default_teardown_is_noop():
    """Default teardown does nothing and raises no error."""
    plugin = _MinimalPlugin()
    result = plugin.teardown({}, None)
    assert result is None


def test_run_pipeline_records_list_command_as_multiline_string():
    class _PipelinePlugin(_MinimalPlugin):
        def run_step_results(self) -> dict[str, Any]:
            return {"success": True, "output": "", "captured": {}, "timing": 0.0}

        def execute_step(
            self, case: dict[str, Any], step: dict[str, Any], topology: Any
        ) -> dict[str, Any]:
            return self.run_step_results()

    plugin = _PipelinePlugin()
    case = {
        "id": "D001",
        "steps": [{"id": "s1", "action": "exec", "target": "DUT", "command": ["echo one", "echo two"]}],
        "pass_criteria": [],
    }

    result = plugin.run_pipeline(case, topology=None)

    assert result["commands"] == ["echo one\necho two"]


# -- abstract enforcement ---------------------------------------------------


def test_missing_execute_step_raises():
    """Cannot instantiate without execute_step."""

    class _NoExecuteStep(PluginBase):
        @property
        def name(self) -> str:
            return "no_exec"

        def discover_cases(self) -> list[dict[str, Any]]:
            return []

        def evaluate(self, case: dict[str, Any], results: dict[str, Any]) -> bool:
            return True

    with pytest.raises(TypeError):
        _NoExecuteStep()  # type: ignore[abstract]


def test_missing_evaluate_raises():
    """Cannot instantiate without evaluate."""

    class _NoEvaluate(PluginBase):
        @property
        def name(self) -> str:
            return "no_eval"

        def discover_cases(self) -> list[dict[str, Any]]:
            return []

        def execute_step(
            self, case: dict[str, Any], step: dict[str, Any], topology: Any
        ) -> dict[str, Any]:
            return {}

    with pytest.raises(TypeError):
        _NoEvaluate()  # type: ignore[abstract]


def test_missing_name_raises():
    """Cannot instantiate without name property."""

    class _NoName(PluginBase):
        def discover_cases(self) -> list[dict[str, Any]]:
            return []

        def execute_step(
            self, case: dict[str, Any], step: dict[str, Any], topology: Any
        ) -> dict[str, Any]:
            return {}

        def evaluate(self, case: dict[str, Any], results: dict[str, Any]) -> bool:
            return True

    with pytest.raises(TypeError):
        _NoName()  # type: ignore[abstract]


def test_missing_discover_cases_raises():
    """Cannot instantiate without discover_cases."""

    class _NoDiscover(PluginBase):
        @property
        def name(self) -> str:
            return "no_discover"

        def execute_step(
            self, case: dict[str, Any], step: dict[str, Any], topology: Any
        ) -> dict[str, Any]:
            return {}

        def evaluate(self, case: dict[str, Any], results: dict[str, Any]) -> bool:
            return True

    with pytest.raises(TypeError):
        _NoDiscover()  # type: ignore[abstract]
