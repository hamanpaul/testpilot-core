"""Tests for the safe wheel-model `testpilot --update` path (C1 + I3).

These lock the destructive-bug fixes:
- unresolvable manifest must NEVER uninstall-all (it must exit nonzero, untouched)
- reinstall delegates to the packaged install.sh (no `pip install <bare-name>`)
- ref is honored as TESTPILOT_REF; packaged manifest path passed as TESTPILOT_MANIFEST
- post-update verify failure rolls back from .last-good.txt
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

import testpilot.cli as cli_mod
from testpilot.cli import _handle_update
from testpilot.install.manifest import Core, InstallManifest, Plugin


def _fake_manifest(plugin_names: list[str]) -> InstallManifest:
    return InstallManifest(
        core=Core(distribution="testpilot-core", version="0.3.0", repo="x/y"),
        plugins=[
            Plugin(name=n, repo=f"x/{n}", version="0.3.0", api_version="1.1")
            for n in plugin_names
        ],
    )


def _setup_venv(tmp_path: Path) -> Path:
    venv = tmp_path / ".venv"
    venv.mkdir()
    return venv


def test_unresolvable_manifest_never_uninstalls(tmp_path: Path) -> None:
    """C1.3: manifest is None -> exit nonzero WITHOUT calling runner/installer."""
    venv = _setup_venv(tmp_path)
    runner_calls: list[list[str]] = []
    installer_calls: list[dict] = []

    with patch.object(cli_mod, "_get_managed_venv", return_value=venv):
        with patch.object(cli_mod, "_resolve_manifest", return_value=None):
            with pytest.raises(SystemExit) as exc:
                _handle_update(
                    "main",
                    runner=lambda args: runner_calls.append(args) or 0,
                    installer=lambda env: installer_calls.append(env) or 0,
                )

    assert exc.value.code != 0
    assert not any("uninstall" in c for c in runner_calls), runner_calls
    assert installer_calls == [], "installer must not run on unresolvable manifest"


def test_update_delegates_to_installer_and_reconciles(tmp_path: Path) -> None:
    """C1.4: resolved {wifi_llapi}, installed {wifi_llapi, old_plugin}.

    Must invoke the installer (mocked) AND uninstall only old_plugin —
    never `pip install <bare-name>`.
    """
    venv = _setup_venv(tmp_path)
    runner_calls: list[list[str]] = []
    installer_calls: list[dict] = []

    with patch.object(cli_mod, "_get_managed_venv", return_value=venv):
        with patch.object(cli_mod, "_resolve_manifest", return_value=_fake_manifest(["wifi_llapi"])):
            with patch.object(cli_mod, "_packaged_manifest_path", return_value=Path("/pkg/install-manifest.yaml")):
                with patch.object(cli_mod, "_probe_installed_plugins", return_value={"wifi_llapi", "old_plugin"}):
                    rc = _handle_update(
                        "v0.4.0",
                        runner=lambda args: runner_calls.append(args) or 0,
                        installer=lambda env: installer_calls.append(env) or 0,
                        verifier=lambda: True,
                    )

    assert rc == 0
    # installer invoked exactly once with ref + manifest env
    assert len(installer_calls) == 1, installer_calls
    env = installer_calls[0]
    assert env.get("TESTPILOT_REF") == "v0.4.0"
    assert env.get("TESTPILOT_MANIFEST") == "/pkg/install-manifest.yaml"
    # uninstall only the dropped plugin
    uninstalls = [c for c in runner_calls if "uninstall" in c]
    assert any("old_plugin" in c for c in uninstalls), runner_calls
    assert not any("wifi_llapi" in c for c in uninstalls), runner_calls
    # NEVER a bare-name pip install
    assert not any("install" in c and "uninstall" not in c and "-r" not in c for c in runner_calls), runner_calls


def test_update_verify_failure_triggers_rollback(tmp_path: Path) -> None:
    """I3: post-update verify failure restores from .last-good.txt and exits nonzero."""
    venv = _setup_venv(tmp_path)
    # Pre-create the snapshot so rollback uses it.
    share = tmp_path / "share"
    share.mkdir()
    last_good = share / ".last-good.txt"
    last_good.write_text("wifi_llapi==0.3.0\n")

    runner_calls: list[list[str]] = []

    with patch.object(cli_mod, "_get_managed_venv", return_value=venv):
        with patch.object(cli_mod, "_resolve_manifest", return_value=_fake_manifest(["wifi_llapi"])):
            with patch.object(cli_mod, "_packaged_manifest_path", return_value=Path("/pkg/m.yaml")):
                with patch.object(cli_mod, "_probe_installed_plugins", return_value={"wifi_llapi"}):
                    with patch.object(cli_mod, "_last_good_path", return_value=last_good):
                        with patch.object(cli_mod, "_snapshot_environment", return_value=None):
                            with pytest.raises(SystemExit) as exc:
                                _handle_update(
                                    "main",
                                    runner=lambda args: runner_calls.append(args) or 0,
                                    installer=lambda env: 0,
                                    verifier=lambda: False,
                                )

    assert exc.value.code != 0
    # rollback: runner called with install -r <last_good>
    assert any("install" in c and "-r" in c and str(last_good) in c for c in runner_calls), runner_calls


def test_resolve_manifest_returns_object_or_none() -> None:
    """C1.2: _resolve_manifest returns a real manifest object in dev checkout."""
    m = cli_mod._resolve_manifest("main")
    assert m is not None
    assert isinstance(m, InstallManifest)
    assert any(p.name == "wifi_llapi" for p in m.plugins)


def test_resolve_manifest_none_when_unresolvable() -> None:
    """C1.2: returns None (NOT empty set) when no manifest can be located."""
    with patch.object(cli_mod, "_packaged_manifest_path", return_value=None):
        assert cli_mod._resolve_manifest("main") is None
