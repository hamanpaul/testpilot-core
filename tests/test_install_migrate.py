"""Tests for the wired-in legacy migration (I1).

`testpilot install-migrate` must execute the detected migration actions via an
injectable runner/remover, and do nothing on a clean machine.
"""

from __future__ import annotations

from unittest.mock import patch

from click.testing import CliRunner

import testpilot.cli as cli_mod
from testpilot.cli import main


def test_install_migrate_executes_actions_for_dirty_probe(monkeypatch) -> None:
    runner_calls: list[list[str]] = []
    removed: list = []
    probe = {"user_site_testpilot": True, "pipx_testpilot": False, "legacy_src": True}

    # Avoid the post-migration stray-import warn touching a real interpreter.
    monkeypatch.setattr(cli_mod, "_system_python_outside", lambda venv_bin: None)

    rc = cli_mod._handle_install_migrate(
        probe=probe,
        runner=lambda cmd: runner_calls.append(cmd) or 0,
        remover=lambda p: removed.append(p),
    )

    assert rc == 0
    # user-site uninstall: python -m pip uninstall -y testpilot testpilot-core
    assert any(
        "pip" in c and "uninstall" in c and "testpilot" in c and "testpilot-core" in c
        for c in runner_calls
    ), runner_calls
    # legacy src checkout removed (the src, not the venv)
    assert removed, "legacy src checkout should be removed"
    assert all("src" in str(p) for p in removed), removed
    # pipx NOT invoked (probe said no pipx install)
    assert not any("pipx" in c for c in runner_calls), runner_calls


def test_install_migrate_handles_pipx(monkeypatch) -> None:
    runner_calls: list[list[str]] = []
    probe = {"user_site_testpilot": False, "pipx_testpilot": True, "legacy_src": False}
    monkeypatch.setattr(cli_mod, "_system_python_outside", lambda venv_bin: None)

    rc = cli_mod._handle_install_migrate(
        probe=probe,
        runner=lambda cmd: runner_calls.append(cmd) or 0,
        remover=lambda p: None,
    )

    assert rc == 0
    assert any("pipx" in c and "uninstall" in c for c in runner_calls), runner_calls


def test_install_migrate_noop_on_clean_probe() -> None:
    runner_calls: list[list[str]] = []
    removed: list = []
    probe = {"user_site_testpilot": False, "pipx_testpilot": False, "legacy_src": False}

    rc = cli_mod._handle_install_migrate(
        probe=probe,
        runner=lambda cmd: runner_calls.append(cmd) or 0,
        remover=lambda p: removed.append(p),
    )

    assert rc == 0
    assert runner_calls == [], runner_calls
    assert removed == [], removed


def test_probe_legacy_src_respects_testpilot_home(tmp_path, monkeypatch) -> None:
    """I-important3: the legacy-src probe must target _get_managed_src().

    Regression: the probe checked the hardcoded ``~/.local/share/testpilot/src``
    while removal used ``_get_managed_src()`` (TESTPILOT_HOME-aware), so under a
    custom TESTPILOT_HOME detection and removal pointed at different paths.
    """
    home = tmp_path / "custom-home"
    (home / "src").mkdir(parents=True)
    monkeypatch.setenv("TESTPILOT_HOME", str(home))

    probe = cli_mod._probe_legacy_installs()

    assert probe["legacy_src"] is True, (
        "probe must detect the legacy src under TESTPILOT_HOME"
    )
    # The detected path is exactly what removal would target.
    assert cli_mod._get_managed_src() == home / "src"


def test_probe_legacy_src_absent_under_clean_testpilot_home(
    tmp_path, monkeypatch
) -> None:
    """No legacy src under a fresh TESTPILOT_HOME -> probe reports False."""
    home = tmp_path / "clean-home"
    home.mkdir()
    monkeypatch.setenv("TESTPILOT_HOME", str(home))

    probe = cli_mod._probe_legacy_installs()

    assert probe["legacy_src"] is False


def test_install_migrate_command_registered_and_hidden() -> None:
    # The command must exist (invokable) but be hidden from --help so the README
    # CLI-help marker stays valid.
    runner = CliRunner()
    with patch.object(cli_mod, "_handle_install_migrate", return_value=0) as mock:
        result = runner.invoke(main, ["install-migrate"])
    assert result.exit_code == 0
    mock.assert_called_once()

    help_result = runner.invoke(main, ["--help"])
    assert "install-migrate" not in help_result.output, "install-migrate must be hidden"
