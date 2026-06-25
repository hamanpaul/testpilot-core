"""Template plugin — copy this directory to create a new plugin."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from testpilot.api import PluginBase


class Plugin(PluginBase):
    """Minimal plugin template.

    Only the four required abstract methods are implemented here.
    ``version``, ``setup_env``, ``verify_env``, and ``teardown``
    inherit sensible defaults from :class:`PluginBase`.
    Override them when your plugin needs custom behaviour.
    """

    api_version = "1.0"

    @property
    def name(self) -> str:
        return "template"

    @property
    def cases_dir(self) -> Path:
        return Path(__file__).parent / "cases"

    def discover_cases(self) -> list[dict[str, Any]]:
        cases: list[dict[str, Any]] = []
        if not self.cases_dir.is_dir():
            return cases
        for yaml_file in sorted(self.cases_dir.glob("*.yaml")):
            if yaml_file.stem.startswith("_"):
                continue
            import yaml
            data = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("id", yaml_file.stem)
                cases.append(data)
        return cases

    def execute_step(self, case: dict[str, Any], step: dict[str, Any], topology: Any) -> dict[str, Any]:
        return {"success": True, "output": "", "captured": {}, "timing": 0.0}

    def evaluate(self, case: dict[str, Any], results: dict[str, Any]) -> bool:
        return True
