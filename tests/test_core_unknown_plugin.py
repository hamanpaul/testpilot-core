"""Smoke test: core pipeline works for a plugin core has no hardcoded knowledge of (Task 1.3).

Proves that after the decouple refactor — which removes wifi_llapi-specific
branches from the core Orchestrator — the core ``PluginBase.run_pipeline``
path still completes setup→steps→evaluate→teardown for any arbitrary plugin.

If this test fails after the refactor it means core accidentally broke the
generic plugin contract, not just the wifi_llapi-specific code.
"""

from __future__ import annotations

from typing import Any

import pytest

from testpilot.core.plugin_base import PluginBase


# ---------------------------------------------------------------------------
# Minimal unknown plugin — core has zero hardcoded knowledge of this type
# ---------------------------------------------------------------------------

class _UnknownPlugin(PluginBase):
    """Absolutely minimal plugin that core knows nothing about.

    Records which lifecycle phases were visited so the test can assert
    the full pipeline ran in order.
    """

    def __init__(self) -> None:
        self.visited: list[str] = []

    @property
    def name(self) -> str:
        return "unknown_smoke"

    def discover_cases(self) -> list[dict[str, Any]]:
        return []

    def setup_env(self, case: dict[str, Any], topology: Any) -> bool:
        self.visited.append("setup")
        return True

    def verify_env(self, case: dict[str, Any], topology: Any) -> bool:
        self.visited.append("verify")
        return True

    def execute_step(
        self, case: dict[str, Any], step: dict[str, Any], topology: Any
    ) -> dict[str, Any]:
        self.visited.append(f"step:{step.get('id', 'anon')}")
        return {"success": True, "output": "ok", "captured": {}, "timing": 0.0}

    def evaluate(self, case: dict[str, Any], results: dict[str, Any]) -> bool:
        self.visited.append("evaluate")
        return True

    def teardown(self, case: dict[str, Any], topology: Any) -> None:
        self.visited.append("teardown")


# ---------------------------------------------------------------------------
# Smoke tests
# ---------------------------------------------------------------------------

class TestUnknownPluginCorePath:
    """Drive an unknown plugin through PluginBase.run_pipeline without core needing
    any wifi_llapi-specific branch."""

    def test_pipeline_completes_no_steps(self) -> None:
        """Empty-step case: setup→verify→evaluate→teardown, verdict=True."""
        plugin = _UnknownPlugin()
        case: dict[str, Any] = {"id": "SMOKE-001", "steps": []}

        result = plugin.run_pipeline(case, topology=None)

        assert result["verdict"] is True, f"unexpected verdict: {result}"
        assert result["comment"] == ""
        assert "setup" in plugin.visited
        assert "verify" in plugin.visited
        assert "evaluate" in plugin.visited
        assert "teardown" in plugin.visited

    def test_pipeline_executes_steps_in_order(self) -> None:
        """Multi-step case: each step is executed in sequence."""
        plugin = _UnknownPlugin()
        case: dict[str, Any] = {
            "id": "SMOKE-002",
            "steps": [
                {"id": "s1", "command": "echo hello"},
                {"id": "s2", "command": "echo world"},
            ],
        }

        result = plugin.run_pipeline(case, topology=None)

        assert result["verdict"] is True
        assert plugin.visited == ["setup", "verify", "step:s1", "step:s2", "evaluate", "teardown"]
        assert result["commands"] == ["echo hello", "echo world"]

    def test_pipeline_teardown_runs_even_when_step_fails(self) -> None:
        """Teardown is guaranteed even on step failure (finally-block contract)."""

        class _FailingPlugin(_UnknownPlugin):
            def execute_step(
                self, case: dict[str, Any], step: dict[str, Any], topology: Any
            ) -> dict[str, Any]:
                self.visited.append(f"step:{step.get('id', 'anon')}")
                return {"success": False, "output": "boom", "captured": {}, "timing": 0.0}

        plugin = _FailingPlugin()
        case: dict[str, Any] = {"id": "SMOKE-003", "steps": [{"id": "bad_step"}]}

        result = plugin.run_pipeline(case, topology=None)

        assert result["verdict"] is False
        assert "step failed" in result["comment"]
        assert "teardown" in plugin.visited  # guaranteed by finally block

    def test_pipeline_teardown_runs_when_exception_raised(self) -> None:
        """Teardown runs even when execute_step raises an unexpected exception."""

        class _ExplodingPlugin(_UnknownPlugin):
            def execute_step(
                self, case: dict[str, Any], step: dict[str, Any], topology: Any
            ) -> dict[str, Any]:
                raise RuntimeError("unexpected hardware error")

        plugin = _ExplodingPlugin()
        case: dict[str, Any] = {"id": "SMOKE-004", "steps": [{"id": "explode"}]}

        result = plugin.run_pipeline(case, topology=None)

        assert result["verdict"] is False
        assert "exception" in result["comment"]
        assert "teardown" in plugin.visited

    def test_setup_failure_short_circuits_pipeline(self) -> None:
        """setup_env returning False stops the pipeline before steps."""

        class _BadSetupPlugin(_UnknownPlugin):
            def setup_env(self, case: dict[str, Any], topology: Any) -> bool:
                self.visited.append("setup")
                return False  # signal failure

        plugin = _BadSetupPlugin()
        case: dict[str, Any] = {"id": "SMOKE-005", "steps": [{"id": "s1"}]}

        result = plugin.run_pipeline(case, topology=None)

        assert result["verdict"] is False
        assert "setup_env failed" in result["comment"]
        # steps and evaluate must NOT have run
        assert not any(v.startswith("step:") for v in plugin.visited)
        assert "evaluate" not in plugin.visited

    def test_plugin_name_is_unknown_to_core(self) -> None:
        """Sanity: our smoke plugin's name is not a core-hardcoded plugin type."""
        plugin = _UnknownPlugin()
        # core only has hardcoded knowledge of 'wifi_llapi'
        assert plugin.name not in {"wifi_llapi", "qos_llapi", "sigma_qt"}

    def test_core_does_not_import_wifi_llapi_to_run_unknown_plugin(self) -> None:
        """run_pipeline on an unknown plugin must not touch wifi_llapi modules.

        After the decouple refactor this becomes the primary correctness guard:
        the core path must not have any wifi_llapi-specific imports gated on
        plugin name.
        """
        import sys

        wifi_llapi_modules_before = {k for k in sys.modules if "wifi_llapi" in k}

        plugin = _UnknownPlugin()
        plugin.run_pipeline({"id": "SMOKE-006", "steps": []}, topology=None)

        wifi_llapi_modules_after = {k for k in sys.modules if "wifi_llapi" in k}
        newly_imported = wifi_llapi_modules_after - wifi_llapi_modules_before
        assert not newly_imported, (
            f"run_pipeline for unknown plugin imported wifi_llapi modules: {newly_imported}. "
            "Core must not have hardcoded wifi_llapi branches."
        )
