"""Shared CLI support helpers for plugin command registration."""

from __future__ import annotations

from typing import Any

import click
from rich.console import Console

from testpilot.core.orchestrator import Orchestrator
from testpilot.core.plugin_base import IncompatiblePluginError
from testpilot.core.plugin_loader import PluginLoader
from testpilot.core.testbed_bootstrap import stage_plugin_testbed

console = Console()


def run_command_guidance() -> str:
    return (
        "Correct format:\n"
        "  testpilot run <plugin_name> [--case <case_id>] [--dut-fw-ver <fw_ver>]\n\n"
        "Example:\n"
        "  testpilot run wifi_llapi --case wifi-llapi-D004-kickstation --dut-fw-ver BGW720-B0-403\n\n"
        "Tip:\n"
        "  testpilot list-cases wifi_llapi"
    )

class CliRegistrar:
    """Register installed plugin-owned click commands on the testpilot root group."""

    def __init__(self, root: click.Group) -> None:
        self._root = root

    def add_command(self, command: click.Command) -> None:
        self._root.add_command(command)

    def add_group(self, group: click.Group) -> None:
        self._root.add_command(group)


def load_registered_plugin(plugin_name: str) -> Any:
    """Load a plugin from the installed testpilot.plugins entry points."""
    try:
        return PluginLoader.for_entry_points().load(plugin_name)
    except (FileNotFoundError, IncompatiblePluginError, TypeError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc


def get_orchestrator(ctx: Any, plugin_name: str | None = None) -> Orchestrator:
    """Build an Orchestrator, staging a plugin testbed when a plugin is known."""
    root = ctx.obj["root"]
    if plugin_name is not None:
        try:
            plugin = load_registered_plugin(plugin_name)
            stage_plugin_testbed(plugin.plugin_root, plugin_name, root / "configs")
        except FileNotFoundError as exc:
            raise click.ClickException(str(exc)) from exc
    return Orchestrator(project_root=root)


def run_plugin_cases(
    ctx: Any,
    plugin_name: str,
    case_ids: tuple[str, ...],
    dut_fw_ver: str,
) -> None:
    """Run plugin cases through the shared normal-run orchestrator path."""
    orch = get_orchestrator(ctx, plugin_name)
    provider_config = ctx.obj.get("provider_config")
    provider_notice = str(ctx.obj.get("provider_notice") or "")
    if provider_config and provider_notice == "azure_interactive":
        console.print("[green]✓ Azure OpenAI authenticated.[/green]")
    elif provider_config and provider_notice == "azure_env":
        console.print("[green]✓ Azure OpenAI (from env vars).[/green]")
    result = orch.run(
        plugin_name,
        list(case_ids) if case_ids else None,
        dut_fw_ver=dut_fw_ver,
        provider_config=provider_config,
    )
    console.print(result)
