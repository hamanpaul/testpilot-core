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


def test_update_missing_venv_exits_without_mutating(tmp_path: Path) -> None:
    """Wheel model: no managed venv -> clear nonzero exit, runner never invoked.

    (Rewritten from the retired dirty-git-checkout test. ALWAYS patches
    _get_managed_venv and passes a fake runner so the real pip never runs.)
    """
    import testpilot.cli as cli_mod
    from testpilot.cli import _handle_update

    missing_venv = tmp_path / "nope" / ".venv"  # does not exist
    runner_calls: list[list[str]] = []
    installer_calls: list[dict] = []

    with patch.object(cli_mod, "_get_managed_venv", return_value=missing_venv):
        with pytest.raises(SystemExit) as exc_info:
            _handle_update(
                "main",
                runner=lambda args: runner_calls.append(args) or 0,
                installer=lambda env: installer_calls.append(env) or 0,
            )

    assert exc_info.value.code != 0
    assert runner_calls == [], f"runner must not run when venv is missing: {runner_calls}"
    assert installer_calls == [], f"installer must not run when venv is missing: {installer_calls}"


def test_update_unresolvable_manifest_exits_without_uninstall(tmp_path: Path) -> None:
    """Wheel model: venv exists but manifest is unresolvable -> nonzero, no uninstall.

    (Rewritten from the retired nonexistent-managed-src test.) The destructive
    bug was treating an empty manifest as "no plugins" and uninstalling all; an
    unresolvable manifest must touch nothing.
    """
    import testpilot.cli as cli_mod
    from testpilot.cli import _handle_update

    venv = tmp_path / ".venv"
    venv.mkdir()
    runner_calls: list[list[str]] = []
    installer_calls: list[dict] = []

    with patch.object(cli_mod, "_get_managed_venv", return_value=venv):
        with patch.object(cli_mod, "_resolve_manifest", return_value=None):
            with pytest.raises(SystemExit) as exc_info:
                _handle_update(
                    "main",
                    runner=lambda args: runner_calls.append(args) or 0,
                    installer=lambda env: installer_calls.append(env) or 0,
                )

    assert exc_info.value.code != 0
    assert not any("uninstall" in c for c in runner_calls), runner_calls
    assert installer_calls == [], installer_calls


def test_update_reinstalls_manifest_plugins(tmp_path: Path) -> None:
    """_handle_update (wheel model) reinstalls the pinned set via the installer seam.

    Reinstall delegates to the packaged install.sh (NOT pip bare-name), so the
    assertion is that the installer is invoked — not that pip installs a name.
    """
    import testpilot.cli as cli_mod
    from testpilot.cli import _handle_update
    from testpilot.install.manifest import Core, InstallManifest, Plugin

    fake_venv = tmp_path / ".venv"
    fake_venv.mkdir()

    manifest = InstallManifest(
        core=Core(distribution="testpilot-core", version="0.3.0", repo="x/y"),
        plugins=[Plugin(name="wifi_llapi", repo="x/wifi_llapi", version="0.3.0", api_version="1.1")],
    )

    calls: list[list[str]] = []
    installer_calls: list[dict] = []

    with patch.object(cli_mod, "_get_managed_venv", return_value=fake_venv):
        with patch.object(cli_mod, "_probe_installed_plugins", return_value=set()):
            with patch.object(cli_mod, "_resolve_manifest", return_value=manifest):
                with patch.object(cli_mod, "_packaged_manifest_path", return_value=tmp_path / "m.yaml"):
                    rc = _handle_update(
                        "main",
                        runner=lambda args: calls.append(args) or 0,
                        installer=lambda env: installer_calls.append(env) or 0,
                        verifier=lambda: True,
                    )

    assert rc == 0
    assert len(installer_calls) == 1, installer_calls
    # no bare-name pip install
    bare_installs = [c for c in calls if "install" in c and "uninstall" not in c and "-r" not in c]
    assert not bare_installs, f"Unexpected bare-name pip install: {bare_installs}"


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
