from __future__ import annotations

from pathlib import Path
from typing import Any

from testpilot.core.orchestrator import Orchestrator
from testpilot.core.plugin_base import PluginBase


class _SkeletonOnlyPlugin(PluginBase):
    """A registered plugin that provides neither a runner nor a reporter.

    Such plugins must keep the orchestrator's skeleton (dry-run) behavior.
    """

    api_version = "1.0"

    @property
    def name(self) -> str:
        return "skeleton_only"

    @property
    def version(self) -> str:
        return "0.1.0"

    def discover_cases(self) -> list[dict[str, Any]]:
        return [{"id": "case-001", "steps": []}]

    def execute_step(self, case: dict[str, Any], step: dict[str, Any], topology: Any) -> dict[str, Any]:
        return {"success": True, "output": "", "captured": {}, "timing": 0.0}

    def evaluate(self, case: dict[str, Any], results: dict[str, Any]) -> bool:
        return True


def test_orchestrator_run_keeps_skeleton_fallback_for_registered_non_core_loop_plugin() -> None:
    root = Path(__file__).resolve().parents[1]
    orchestrator = Orchestrator(project_root=root)

    # Inject a registered plugin with no runner/reporter so run() exercises the
    # generic skeleton fallback path without depending on an installed plugin.
    orchestrator.loader._plugins["skeleton_only"] = _SkeletonOnlyPlugin()

    result = orchestrator.run("skeleton_only")

    assert result["plugin"] == "skeleton_only"
    assert result["status"] == "skeleton — not yet implemented"
