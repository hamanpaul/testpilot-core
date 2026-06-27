"""Tests for pre-dispatch --update [REF] and --verify-install handling.

These tests verify that --update and --verify-install intercept sys.argv before
normal Click routing and never fall through into the regular command group.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from testpilot.cli import main


# ---------------------------------------------------------------------------
# --update pre-dispatch tests
# ---------------------------------------------------------------------------


def test_update_no_ref_defaults_to_main() -> None:
    """--update with no ref should call the update handler with ref='main'."""
    runner = CliRunner()
    captured: list[str | None] = []

    def _fake_update(ref: str | None) -> None:
        captured.append(ref)

    with patch("testpilot.cli._handle_update", side_effect=_fake_update):
        result = runner.invoke(main, ["--update"])

    assert captured == ["main"], f"expected ref='main', got {captured}"
    assert result.exit_code == 0


def test_update_with_explicit_ref() -> None:
    """--update v0.2.0 should call the update handler with ref='v0.2.0'."""
    runner = CliRunner()
    captured: list[str | None] = []

    def _fake_update(ref: str | None) -> None:
        captured.append(ref)

    with patch("testpilot.cli._handle_update", side_effect=_fake_update):
        result = runner.invoke(main, ["--update", "v0.2.0"])

    assert captured == ["v0.2.0"], f"expected ref='v0.2.0', got {captured}"
    assert result.exit_code == 0


def test_update_does_not_enter_click_commands() -> None:
    """--update must not try to dispatch into list-plugins or other commands."""
    runner = CliRunner()

    with patch("testpilot.cli._handle_update") as mock_update:
        result = runner.invoke(main, ["--update", "list-plugins"])

    # "list-plugins" is treated as the ref, not as a subcommand
    mock_update.assert_called_once_with("list-plugins")
    assert result.exit_code == 0


def test_update_dirty_checkout_exits_nonzero(tmp_path: Path) -> None:
    """_handle_update should exit non-zero when managed checkout is dirty."""
    from testpilot.cli import _handle_update

    # Create a real managed_src dir so the exists() guard passes.
    managed_src = tmp_path / "managed" / "src"
    managed_src.mkdir(parents=True)

    def _dirty_git_run(cmd, **kwargs):
        class _R:
            returncode = 0
            stdout = ""

        if "status" in cmd and "--porcelain" in cmd:
            _R.stdout = " M some-file.py\n"
        return _R()

    with patch("testpilot.cli._get_managed_src", return_value=managed_src):
        with patch("testpilot.cli._git_run", side_effect=_dirty_git_run):
            with pytest.raises(SystemExit) as exc_info:
                _handle_update("main")
    assert exc_info.value.code != 0


def test_update_nonexistent_managed_src_exits_nonzero() -> None:
    """_handle_update must fail clearly when no managed checkout exists."""
    from testpilot.cli import _handle_update

    git_calls: list[list[str]] = []

    def _tracking_git_run(cmd, **kwargs):
        git_calls.append(list(cmd))

        class _R:
            returncode = 0
            stdout = ""

        return _R()

    nonexistent = Path("/nonexistent/managed/src/that/does/not/exist")
    with patch("testpilot.cli._get_managed_src", return_value=nonexistent):
        with patch("testpilot.cli._git_run", side_effect=_tracking_git_run):
            with pytest.raises(SystemExit) as exc_info:
                _handle_update("main")

    assert exc_info.value.code != 0
    status_calls = [c for c in git_calls if "status" in c and "--porcelain" in c]
    assert not status_calls, f"git status was called unexpectedly: {status_calls}"


def test_update_reinstalls_manifest_plugins(tmp_path: Path) -> None:
    """_handle_update (wheel model) reinstalls all manifest plugins via runner."""
    import testpilot.cli as cli_mod
    from testpilot.cli import _handle_update

    fake_venv = tmp_path / ".venv"
    fake_venv.mkdir()

    calls: list[list[str]] = []

    with patch.object(cli_mod, "_get_managed_venv", return_value=fake_venv):
        with patch.object(cli_mod, "_probe_installed_plugins", return_value=set()):
            with patch.object(cli_mod, "_resolve_manifest", return_value={"wifi_llapi"}):
                rc = _handle_update("main", runner=lambda args: calls.append(args) or 0)

    assert rc == 0
    install_calls = [c for c in calls if "install" in c and "uninstall" not in c]
    assert any("wifi_llapi" in str(c) for c in install_calls), f"Expected wifi_llapi install in {calls}"


def test_update_missing_venv_exits_nonzero(tmp_path: Path) -> None:
    """_handle_update must exit non-zero when no managed venv exists (wheel model)."""
    import testpilot.cli as cli_mod
    from testpilot.cli import _handle_update

    missing_venv = tmp_path / "nonexistent" / ".venv"

    with patch.object(cli_mod, "_get_managed_venv", return_value=missing_venv):
        with pytest.raises(SystemExit) as exc_info:
            _handle_update("main")

    assert exc_info.value.code != 0


# ---------------------------------------------------------------------------
# --verify-install pre-dispatch tests
# ---------------------------------------------------------------------------


def test_verify_install_dispatches_before_click() -> None:
    """--verify-install must not enter normal Click command parsing."""
    runner = CliRunner()

    with patch("testpilot.cli._handle_verify_install") as mock_verify:
        mock_verify.return_value = None
        result = runner.invoke(main, ["--verify-install"])

    mock_verify.assert_called_once()
    assert result.exit_code == 0


def test_verify_install_missing_skill_exits_nonzero(tmp_path: Path) -> None:
    """_handle_verify_install should exit non-zero when skill dir is missing.

    A managed_src directory is provided so the function enters checkout-mode,
    where a missing skill at skills_root is a hard failure.  In wheel-mode
    (no managed_src) a missing packaged skill is only a WARN.
    """
    from testpilot.cli import _handle_verify_install

    fake_home = tmp_path / "home"
    fake_home.mkdir()

    # Create a managed_src to trigger checkout-mode (skill absence = FAIL there).
    managed_src = tmp_path / "managed_src"
    managed_src.mkdir()

    with patch("testpilot.cli._get_managed_src", return_value=managed_src):
        with patch("testpilot.cli._get_skills_root", return_value=fake_home / ".agents" / "skills"):
            with pytest.raises(SystemExit) as exc_info:
                _handle_verify_install()
    assert exc_info.value.code != 0


def test_verify_install_healthy_exits_zero(tmp_path: Path) -> None:
    """_handle_verify_install should exit 0 and print OK when skill dir is present."""
    from testpilot.cli import _handle_verify_install

    skill_root = tmp_path / ".agents" / "skills"
    skill_dir = skill_root / "testpilot-normal-test"
    skill_dir.mkdir(parents=True)

    mock_console = MagicMock()
    with patch("testpilot.cli._get_skills_root", return_value=skill_root):
        with patch("testpilot.cli.console", mock_console):
            _handle_verify_install()  # must not raise

    printed = " ".join(str(c) for c in mock_console.print.call_args_list)
    assert "OK" in printed or "passed" in printed.lower()


def test_update_help_is_reachable() -> None:
    """testpilot --help should describe the --update flag."""
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert "--update" in result.output
    assert result.exit_code == 0
