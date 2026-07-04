"""Boundary guard: sample production code may only reach testpilot via
``testpilot.api`` — never core/schema/reporting/transport/runtime internals.

The core repo's tests/test_plugin_sdk_api_boundary.py only scans plugins/,
so examples/ needs its own guard.
"""
from __future__ import annotations

import ast
import pathlib

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "testpilot_sample_echo"
GUARDED_PREFIXES = (
    "testpilot.core",
    "testpilot.schema",
    "testpilot.reporting",
    "testpilot.transport",
    "testpilot.runtime",
    "testpilot.serialwrap_binary",
)


def _guarded(module: str | None) -> bool:
    if not module:
        return False
    return any(module == p or module.startswith(p + ".") for p in GUARDED_PREFIXES)


def test_sample_production_code_only_imports_testpilot_api():
    violations: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and _guarded(node.module):
                violations.append(f"{path.name}: from {node.module}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if _guarded(alias.name):
                        violations.append(f"{path.name}: import {alias.name}")
    assert not violations, f"guarded imports in sample production code: {violations}"
