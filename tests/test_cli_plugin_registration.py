"""CLI decoupling guards for change decouple-cli-register-cli."""

from __future__ import annotations

from pathlib import Path

import click
from click.testing import CliRunner

REPO = Path(__file__).resolve().parents[1]


def test_cli_py_has_no_plugin_names() -> None:
    src = (REPO / "src/testpilot/cli.py").read_text(encoding="utf-8")
    for name in ("wifi_llapi", "wifi-llapi", "brcm"):
        assert name not in src, f"cli.py still names {name}"


def test_api_exports_cli_registrar() -> None:
    from testpilot.api import CliRegistrar

    assert hasattr(CliRegistrar, "add_command")
    assert hasattr(CliRegistrar, "add_group")


def test_broken_plugin_does_not_brick_cli(monkeypatch, capsys) -> None:
    import testpilot.core.plugin_loader as plugin_loader
    from testpilot.cli import _register_plugins

    class BrokenPlugin:
        def register_cli(self, registrar) -> None:
            del registrar
            raise RuntimeError("boom")

    class FakeLoader:
        def __init__(self, plugins_dir: Path) -> None:
            del plugins_dir

        def discover(self) -> list[str]:
            return ["broken"]

        def load(self, name: str) -> BrokenPlugin:
            assert name == "broken"
            return BrokenPlugin()

    monkeypatch.setattr(plugin_loader, "PluginLoader", FakeLoader)
    group = click.Group()

    _register_plugins(group)

    captured = capsys.readouterr()
    assert "WARN: skipped plugin 'broken' CLI: boom" in captured.err
    result = CliRunner().invoke(group, ["--help"])
    assert result.exit_code == 0
