"""testpilot.core.api_entry — ctx-free public entry points for programmatic use.

These functions are re-exported through ``testpilot.api`` and must not depend
on click context or any CLI infrastructure.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from testpilot.core.orchestrator import Orchestrator
from testpilot.runtime.run_backend import RunBackend


def run_one_case(
    plugin: str,
    case_id: str,
    *,
    repo_root: Path | None = None,
    run_backend: RunBackend | None = None,
) -> dict[str, Any]:
    """Run a single test case without a click context.

    Parameters
    ----------
    plugin:
        Plugin name (e.g. ``"my_plugin"``).
    case_id:
        Case identifier (e.g. ``"D001"``).
    repo_root:
        Project root path.  Defaults to ``Path.cwd()`` when *None*.
    run_backend:
        Optional :class:`~testpilot.api.RunBackend` to inject (dependency
        injection).  When provided it overrides the testbed-configured backend
        on the orchestrator, enabling deterministic replay-driven runs in CI
        without live hardware.  Defaults to the testbed-configured backend.

    Returns
    -------
    dict
        The result dict returned by :meth:`Orchestrator.run`.
    """
    root = repo_root if repo_root is not None else Path.cwd()
    orch = Orchestrator(project_root=root)
    if run_backend is not None:
        orch.run_backend = run_backend
    return orch.run(plugin, case_ids=[case_id])
