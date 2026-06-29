from __future__ import annotations
from dataclasses import dataclass, field
from testpilot.core.plugin_loader import _check_api_compat
from testpilot.core.plugin_base import IncompatiblePluginError

@dataclass
class CompatReport:
    ok: bool
    failures: list[str] = field(default_factory=list)

def manifest_compat_report(core_api: str, plugins: list[tuple[str, str]]) -> CompatReport:
    failures: list[str] = []
    for name, plugin_api in plugins:
        try:
            _check_api_compat(name, plugin_api, core_api)
        except IncompatiblePluginError as exc:
            failures.append(str(exc))
    return CompatReport(ok=not failures, failures=failures)
