"""Load a plugin straight from an on-disk project directory (path mode, #30).

Registry mode resolves a plugin through the installed ``testpilot.plugins``
entry points. Path mode instead points at a plugin **project root** — the
directory holding ``pyproject.toml`` — and loads the plugin it declares,
without requiring that project to be installed into the current environment.

The project's own ``[project.entry-points."testpilot.plugins"]`` table is the
single source of truth for the plugin's name and import target, so path mode
and registry mode agree on identity; only the resolution route differs.
"""

from __future__ import annotations

import importlib
import logging
from pathlib import Path
import sys
import tomllib
from typing import Any

from testpilot.core.plugin_base import PluginBase

log = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "testpilot.plugins"
PYPROJECT_NAME = "pyproject.toml"


class PluginProjectError(Exception):
    """Raised when a path does not resolve to a loadable plugin project."""


def resolve_project_root(path: str | Path) -> Path:
    """Normalize *path* to an existing plugin-project directory."""
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    try:
        candidate = candidate.resolve()
    except OSError as exc:  # pragma: no cover - defensive
        raise PluginProjectError(f"plugin project path not found: {path} ({exc})") from exc

    if not candidate.exists():
        raise PluginProjectError(f"plugin project path not found: {path}")
    if not candidate.is_dir():
        raise PluginProjectError(
            f"plugin project path is not a directory: {candidate}"
        )
    return candidate


def read_project_entry_points(project_root: Path) -> dict[str, str]:
    """Return the project's declared ``testpilot.plugins`` entry points."""
    pyproject = project_root / PYPROJECT_NAME
    if not pyproject.is_file():
        raise PluginProjectError(
            f"{project_root} is not a plugin project: no {PYPROJECT_NAME}"
        )
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise PluginProjectError(f"cannot parse {pyproject}: {exc}") from exc

    declared = (
        data.get("project", {}).get("entry-points", {}).get(ENTRY_POINT_GROUP, {})
    )
    entry_points = {
        name.strip(): value.strip()
        for name, value in (declared.items() if isinstance(declared, dict) else [])
        if isinstance(name, str)
        and name.strip()
        and not name.startswith("_")
        and isinstance(value, str)
        and value.strip()
    }
    if not entry_points:
        raise PluginProjectError(
            f"{project_root} declares no {ENTRY_POINT_GROUP} entry point in "
            f"{PYPROJECT_NAME}; it is not a TestPilot plugin project"
        )
    return entry_points


def _import_from_project(module_name: str, project_root: Path) -> Any:
    """Import *module_name* so that the copy under *project_root* wins.

    Prepending the project to ``sys.path`` is not sufficient on its own: if the
    same distribution is also pip-installed, its top-level package is already in
    ``sys.modules`` and ``import_module`` would hand back that cached copy —
    path mode would silently exercise the installed tree instead of the one the
    operator pointed at. So the stale top-level package (and its submodules) is
    evicted first, and the result is verified to actually live under the
    project root before it is used.
    """
    root_text = str(project_root)
    if sys.path and sys.path[0] == root_text:
        pass
    else:
        while root_text in sys.path:
            sys.path.remove(root_text)
        sys.path.insert(0, root_text)

    top_level = module_name.split(".")[0]
    cached = sys.modules.get(top_level)
    if cached is not None and not _module_is_under(cached, project_root):
        for name in [
            name
            for name in sys.modules
            if name == top_level or name.startswith(f"{top_level}.")
        ]:
            del sys.modules[name]
    importlib.invalidate_caches()

    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise PluginProjectError(
            f"cannot import {module_name!r} from {project_root}: {exc}"
        ) from exc

    if not _module_is_under(module, project_root):
        located = getattr(module, "__file__", None) or "<unknown location>"
        raise PluginProjectError(
            f"refusing to run: {module_name!r} resolved to {located}, which is "
            f"outside the requested project {project_root}"
        )
    return module


def _module_is_under(module: Any, project_root: Path) -> bool:
    module_file = getattr(module, "__file__", None)
    if not module_file:
        # Namespace packages have no __file__; fall back to their search paths.
        search_paths = list(getattr(module, "__path__", []) or [])
        return any(
            Path(entry).resolve().is_relative_to(project_root) for entry in search_paths
        )
    try:
        return Path(module_file).resolve().is_relative_to(project_root)
    except OSError:  # pragma: no cover - defensive
        return False


def load_plugin_project(path: str | Path) -> tuple[str, PluginBase]:
    """Load the single plugin declared by the project at *path*.

    Returns ``(plugin_name, instance)``. Raises :class:`PluginProjectError`
    when the path is not a plugin project, when the project declares more than
    one plugin (ambiguous — refuse rather than guess), or when the declared
    entry point does not resolve to a usable :class:`PluginBase` subclass.
    """
    project_root = resolve_project_root(path)
    entry_points = read_project_entry_points(project_root)
    if len(entry_points) > 1:
        names = ", ".join(sorted(entry_points))
        raise PluginProjectError(
            f"{project_root} declares multiple {ENTRY_POINT_GROUP} entry points "
            f"({names}); path mode needs exactly one — install the project and "
            f"select by name instead"
        )

    name, target = next(iter(entry_points.items()))
    module_name, separator, attribute = target.partition(":")
    module_name = module_name.strip()
    attribute = attribute.strip()
    if not separator or not module_name or not attribute:
        raise PluginProjectError(
            f"invalid {ENTRY_POINT_GROUP} entry point for {name!r}: {target!r} "
            f"(expected 'module:Attribute')"
        )

    module = _import_from_project(module_name, project_root)
    plugin_cls = getattr(module, attribute, None)
    if plugin_cls is None:
        raise PluginProjectError(
            f"{module_name!r} does not define {attribute!r} (declared by {name!r})"
        )
    if not isinstance(plugin_cls, type) or not issubclass(plugin_cls, PluginBase):
        raise PluginProjectError(
            f"plugin class must inherit PluginBase: {plugin_cls!r}"
        )

    # Same SDK-compat contract as registry mode — path mode must not become a
    # way to sidestep the API version gate.
    from testpilot.api import API_VERSION
    from testpilot.core.plugin_loader import _check_api_compat

    _check_api_compat(name, getattr(plugin_cls, "api_version", None), API_VERSION)

    try:
        instance = plugin_cls()
    except Exception as exc:
        raise PluginProjectError(
            f"cannot instantiate plugin {name!r} from {project_root}: {exc}"
        ) from exc

    log.info(
        "loaded plugin from project path: %s v%s (%s)",
        instance.name,
        instance.version,
        project_root,
    )
    return name, instance
