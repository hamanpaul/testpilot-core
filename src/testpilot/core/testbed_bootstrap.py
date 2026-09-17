"""Stage a plugin's testbed template into the effective configs/testbed.yaml.

Each plugin ships its own ``testbed.yaml.example`` beneath its package root.
When the CLI resolves a plugin context, it stages that template into
``configs/testbed.yaml`` so the runtime always reads a testbed shaped for the
plugin currently being run, with no leakage between plugins.

Staging is **plugin-scoped, not unconditional**: the staged file carries a
marker line naming the plugin it came from, and while that marker matches the
plugin being run the file is left alone — operator edits (bench-specific
``variables`` such as LAN addresses, ``station_driver`` …) survive every run.
Switching plugins, a missing file, or a legacy file without the marker
re-stages from the template.
"""
from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)

PLUGIN_TESTBED_TEMPLATE = "testbed.yaml.example"
EFFECTIVE_TESTBED = "testbed.yaml"
_MARKER_PREFIX = "# testpilot: staged from plugin '"
_MARKER_SUFFIX = "' — operator edits below are kept until the plugin changes\n"


def staged_marker(plugin_name: str) -> str:
    return f"{_MARKER_PREFIX}{plugin_name}{_MARKER_SUFFIX}"


def stage_plugin_testbed(
    plugin_dir: Path,
    plugin_name: str,
    configs_dir: Path,
) -> Path:
    """Stage ``<plugin_root>/testbed.yaml.example`` as ``configs/testbed.yaml``.

    Overwrites the destination only when it is missing, was staged from a
    different plugin, or predates the marker line; otherwise the operator's
    edited file is kept (a differing template is logged so upgrades that add
    new keys are not silent).
    """
    if not plugin_dir.is_dir():
        raise FileNotFoundError(
            f"plugin directory not found: {plugin_dir} (plugin '{plugin_name}')"
        )

    template = plugin_dir / PLUGIN_TESTBED_TEMPLATE
    if not template.is_file():
        raise FileNotFoundError(
            f"plugin '{plugin_name}' is missing {PLUGIN_TESTBED_TEMPLATE} at {template}"
        )

    configs_dir.mkdir(parents=True, exist_ok=True)
    destination = configs_dir / EFFECTIVE_TESTBED
    marker = staged_marker(plugin_name)
    template_text = template.read_text(encoding="utf-8")

    if destination.is_file():
        current = destination.read_text(encoding="utf-8")
        if current.startswith(marker):
            if current != marker + template_text:
                log.info(
                    "configs/testbed.yaml keeps operator edits for plugin '%s' (template: %s)",
                    plugin_name,
                    template,
                )
            return destination

    destination.write_text(marker + template_text, encoding="utf-8")
    return destination
