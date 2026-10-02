from __future__ import annotations

from pathlib import Path

import click
from click.testing import CliRunner

import testpilot.cli as cli_module
from testpilot.core.azure_auth import AzureAgentRuntime, AzureAgentState, AzureAgentStatus
from testpilot.core.orchestrator import Orchestrator


def test_installed_cli_defaults_project_root_to_operator_cwd(
    tmp_path: Path,
    monkeypatch,
) -> None:
    operator_root = tmp_path / "operator-project"
    operator_root.mkdir()
    package_cli = tmp_path / "venv" / "site-packages" / "testpilot" / "cli.py"
    monkeypatch.setattr(cli_module, "__file__", str(package_cli))
    monkeypatch.chdir(operator_root)

    @click.command("root-probe")
    @click.pass_context
    def root_probe(ctx: click.Context) -> None:
        click.echo(ctx.obj["root"])

    monkeypatch.setitem(cli_module.main.commands, "root-probe", root_probe)

    result = CliRunner().invoke(cli_module.main, ["root-probe"])

    assert result.exit_code == 0, result.output
    assert Path(result.output.strip()) == operator_root


def test_cli_preserves_explicit_project_root(
    tmp_path: Path,
    monkeypatch,
) -> None:
    caller_root = tmp_path / "caller-cwd"
    explicit_root = tmp_path / "selected-project"
    caller_root.mkdir()
    explicit_root.mkdir()
    monkeypatch.chdir(caller_root)

    @click.command("root-probe")
    @click.pass_context
    def root_probe(ctx: click.Context) -> None:
        click.echo(ctx.obj["root"])

    monkeypatch.setitem(cli_module.main.commands, "root-probe", root_probe)

    result = CliRunner().invoke(
        cli_module.main,
        ["--root", str(explicit_root), "root-probe"],
    )

    assert result.exit_code == 0, result.output
    assert Path(result.output.strip()) == explicit_root


def test_orchestrator_without_project_root_uses_operator_cwd(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    orchestrator = Orchestrator(
        agent_runtime=AzureAgentRuntime(AzureAgentStatus(AzureAgentState.DISABLED_NO_KEY)),
    )

    assert orchestrator.root == tmp_path
