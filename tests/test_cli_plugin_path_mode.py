"""#30: `testpilot /path/to/plugin-project` — path-mode plugin invocation.

Registry mode (`testpilot <name>`) resolves a plugin through the installed
``testpilot.plugins`` entry points. Path mode loads a plugin project directly
from disk so it can be exercised without being installed into the current
environment.

The load-bearing property is that path mode must run the plugin **at that
path** — not a same-named plugin that happens to be installed. Plugin-owned
CLI commands re-resolve themselves by name (``get_orchestrator(ctx, name)``),
so name resolution has to be redirected for the duration of the invocation or
path mode would silently execute the installed copy.
"""

from __future__ import annotations

from pathlib import Path
import sys
import textwrap

import click
from click.testing import CliRunner
import pytest


REPO = Path(__file__).resolve().parents[1]


def _write_plugin_project(
    root: Path,
    *,
    package: str,
    plugin_name: str,
    marker: str,
    entry_points: dict[str, str] | None = None,
) -> Path:
    """Materialize a minimal, importable plugin project on disk.

    The plugin registers a CLI command named after itself (mirroring how real
    plugins expose their run entry) and echoes *marker* so a test can prove
    which copy executed.
    """
    root.mkdir(parents=True, exist_ok=True)
    declared = entry_points or {plugin_name: f"{package}.plugin:Plugin"}
    ep_lines = "\n".join(f'{name} = "{value}"' for name, value in declared.items())
    (root / "pyproject.toml").write_text(
        textwrap.dedent(
            f"""\
            [project]
            name = "{package}"
            version = "0.0.1"

            [project.entry-points."testpilot.plugins"]
            {ep_lines}
            """
        ),
        encoding="utf-8",
    )
    pkg = root / package
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "plugin.py").write_text(
        textwrap.dedent(
            f'''\
            from typing import Any

            import click

            from testpilot.core.plugin_base import PluginBase


            class Plugin(PluginBase):
                api_version = "1.2"

                @property
                def name(self) -> str:
                    return "{plugin_name}"

                @property
                def version(self) -> str:
                    return "9.9.9"

                def discover_cases(self) -> list[dict[str, Any]]:
                    return []

                def execute_step(self, case, step, topology) -> dict[str, Any]:
                    return {{"success": True, "output": "", "captured": {{}}, "timing": 0.0}}

                def evaluate(self, case, results) -> bool:
                    return True

                def register_cli(self, registrar: Any) -> None:
                    @click.command("{plugin_name}")
                    @click.option("--case", "case_ids", multiple=True)
                    @click.option("--plugin-only-flag", is_flag=True, default=False)
                    def _run(case_ids, plugin_only_flag):
                        click.echo("marker={marker}")
                        click.echo(f"cases={{','.join(case_ids)}}")
                        click.echo(f"flag={{plugin_only_flag}}")

                    registrar.add_command(_run)
            '''
        ),
        encoding="utf-8",
    )
    return root


@pytest.fixture(autouse=True)
def _restore_import_state():
    """Path mode mutates sys.path / sys.modules; keep tests isolated."""
    original_path = list(sys.path)
    original_modules = set(sys.modules)
    yield
    sys.path[:] = original_path
    for name in set(sys.modules) - original_modules:
        del sys.modules[name]


def _cli():
    from testpilot.cli import main

    return main


def test_path_mode_runs_plugin_from_project_path(tmp_path: Path) -> None:
    """A plugin project on disk runs without being installed."""
    project = _write_plugin_project(
        tmp_path / "proj", package="pathmode_a", plugin_name="pathmode_a", marker="A"
    )

    result = CliRunner().invoke(_cli(), [str(project)])

    assert result.exit_code == 0, result.output
    assert "marker=A" in result.output


def test_path_mode_forwards_plugin_owned_options(tmp_path: Path) -> None:
    """Parity with registry mode: the plugin's own options still apply."""
    project = _write_plugin_project(
        tmp_path / "proj", package="pathmode_b", plugin_name="pathmode_b", marker="B"
    )

    result = CliRunner().invoke(
        _cli(), [str(project), "--case", "D001", "--plugin-only-flag"]
    )

    assert result.exit_code == 0, result.output
    assert "cases=D001" in result.output
    assert "flag=True" in result.output


def test_path_mode_beats_installed_plugin_of_the_same_name(
    tmp_path: Path, monkeypatch
) -> None:
    """The whole point of path mode: run THAT copy, not the installed one.

    Plugin-owned CLI commands re-resolve themselves by name, so an unguarded
    implementation would load the entry-point copy and silently test the wrong
    tree.

    This mirrors the real collision: the installed distribution and the on-disk
    checkout share the **same package name**, and the installed one is already
    in ``sys.modules`` by the time path mode runs. Prepending the project to
    ``sys.path`` is therefore not enough on its own — ``import_module`` would
    hand back the cached installed module.
    """
    project = _write_plugin_project(
        tmp_path / "proj", package="collidepkg", plugin_name="collide", marker="ONDISK"
    )
    installed = _write_plugin_project(
        tmp_path / "installed",
        package="collidepkg",
        plugin_name="collide",
        marker="INSTALLED",
    )
    sys.path.insert(0, str(installed))

    import testpilot.core.plugin_loader as plugin_loader

    # Import the installed copy first so it occupies sys.modules, exactly as it
    # would in an environment where the plugin is pip-installed.
    import collidepkg.plugin as installed_module

    assert Path(installed_module.__file__).is_relative_to(installed)

    class _FakeEntryPoint:
        name = "collide"

        def load(self):
            return installed_module.Plugin

    monkeypatch.setattr(
        plugin_loader.metadata,
        "entry_points",
        lambda group=None: [_FakeEntryPoint()],
    )

    result = CliRunner().invoke(_cli(), [str(project)])

    assert result.exit_code == 0, result.output
    assert "marker=ONDISK" in result.output
    assert "marker=INSTALLED" not in result.output


def test_registry_mode_is_unchanged(tmp_path: Path, monkeypatch) -> None:
    """A bare plugin name still resolves through the entry-point registry."""
    installed = _write_plugin_project(
        tmp_path / "installed",
        package="pathmode_reg",
        plugin_name="regmode",
        marker="REGISTRY",
    )
    sys.path.insert(0, str(installed))

    from testpilot.cli import _register_plugins
    import testpilot.core.plugin_loader as plugin_loader

    class _FakeEntryPoint:
        name = "regmode"

        def load(self):
            from pathmode_reg.plugin import Plugin

            return Plugin

    monkeypatch.setattr(
        plugin_loader.metadata,
        "entry_points",
        lambda group=None: [_FakeEntryPoint()],
    )

    group = _cli()
    _register_plugins(group)
    try:
        result = CliRunner().invoke(group, ["regmode"])
        assert result.exit_code == 0, result.output
        assert "marker=REGISTRY" in result.output
    finally:
        group.commands.pop("regmode", None)


def test_path_mode_rejects_missing_path(tmp_path: Path) -> None:
    result = CliRunner().invoke(_cli(), [str(tmp_path / "nope")])

    assert result.exit_code != 0
    assert "not found" in result.output.lower()


def test_path_mode_rejects_project_without_entry_point(tmp_path: Path) -> None:
    """A directory that is not a plugin project must say so, not crash."""
    project = tmp_path / "plain"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        '[project]\nname = "plain"\nversion = "0.0.1"\n', encoding="utf-8"
    )

    result = CliRunner().invoke(_cli(), [str(project)])

    assert result.exit_code != 0
    assert "testpilot.plugins" in result.output


def test_path_mode_rejects_directory_without_pyproject(tmp_path: Path) -> None:
    project = tmp_path / "bare"
    project.mkdir()

    result = CliRunner().invoke(_cli(), [str(project)])

    assert result.exit_code != 0
    assert "pyproject.toml" in result.output


def test_path_mode_fails_closed_on_ambiguous_project(tmp_path: Path) -> None:
    """Two declared plugins in one project: refuse rather than guess."""
    project = _write_plugin_project(
        tmp_path / "proj",
        package="pathmode_multi",
        plugin_name="first",
        marker="MULTI",
        entry_points={
            "first": "pathmode_multi.plugin:Plugin",
            "second": "pathmode_multi.plugin:Plugin",
        },
    )

    result = CliRunner().invoke(_cli(), [str(project)])

    assert result.exit_code != 0
    assert "first" in result.output and "second" in result.output


def test_relative_path_is_accepted(tmp_path: Path) -> None:
    project = _write_plugin_project(
        tmp_path / "proj", package="pathmode_rel", plugin_name="pathmode_rel", marker="REL"
    )

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        result = runner.invoke(_cli(), [f"../proj"])

    assert result.exit_code == 0, result.output
    assert "marker=REL" in result.output


def test_help_documents_both_invocation_forms() -> None:
    result = CliRunner().invoke(_cli(), ["--help"])

    assert result.exit_code == 0
    assert "PLUGIN_PATH" in result.output


def test_cli_py_still_names_no_plugin() -> None:
    """The path-mode implementation must stay plugin-agnostic (core guard)."""
    src = (REPO / "src/testpilot/cli.py").read_text(encoding="utf-8")
    for name in ("wifi_llapi", "wifi-llapi", "brcm"):
        assert name not in src
