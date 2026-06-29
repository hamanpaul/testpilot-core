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
    """I3 + CRITICAL: post-update verify failure restores from .last-good.txt
    using an OFFLINE pip invocation (never a public index) and exits nonzero."""
    venv = _setup_venv(tmp_path)
    # Pre-create the snapshot so rollback uses it.
    share = tmp_path / "share"
    share.mkdir()
    last_good = share / ".last-good.txt"
    last_good.write_text("wifi_llapi==0.3.0\n")
    wheel_cache = share / ".wheel-cache"
    wheel_cache.mkdir()

    runner_calls: list[list[str]] = []

    with patch.object(cli_mod, "_get_managed_venv", return_value=venv):
        with patch.object(cli_mod, "_resolve_manifest", return_value=_fake_manifest(["wifi_llapi"])):
            with patch.object(cli_mod, "_packaged_manifest_path", return_value=Path("/pkg/m.yaml")):
                with patch.object(cli_mod, "_probe_installed_plugins", return_value={"wifi_llapi"}):
                    with patch.object(cli_mod, "_last_good_path", return_value=last_good):
                        with patch.object(cli_mod, "_wheel_cache_path", return_value=wheel_cache):
                            with patch.object(cli_mod, "_snapshot_environment", return_value=None):
                                with pytest.raises(SystemExit) as exc:
                                    _handle_update(
                                        "main",
                                        runner=lambda args: runner_calls.append(args) or 0,
                                        installer=lambda env: 0,
                                        verifier=lambda: False,
                                    )

    assert exc.value.code != 0
    rollback = [c for c in runner_calls if "install" in c and "-r" in c]
    assert rollback, f"rollback install not invoked: {runner_calls}"
    rb = rollback[0]
    # CRITICAL: rollback must be offline-only — never reachable to public PyPI.
    assert "--no-index" in rb, f"rollback must use --no-index: {rb}"
    assert "--find-links" in rb, f"rollback must use --find-links: {rb}"
    assert str(wheel_cache) in rb, f"rollback must point --find-links at the wheel cache: {rb}"
    assert str(last_good) in rb
    # No pip install anywhere in the flow may omit --no-index (would risk a
    # public-index reach / dependency confusion for private packages).
    for c in runner_calls:
        if "install" in c and "uninstall" not in c:
            assert "--no-index" in c, f"every install must be offline-only: {c}"


def test_rollback_failure_prints_manual_recovery_and_exits_nonzero(
    tmp_path: Path, capsys
) -> None:
    """CRITICAL: when offline rollback fails (wheels unavailable), print a clear
    manual-recovery message and exit nonzero — never silently retry online."""
    venv = _setup_venv(tmp_path)
    share = tmp_path / "share"
    share.mkdir()
    last_good = share / ".last-good.txt"
    last_good.write_text("wifi_llapi==0.3.0\n")
    wheel_cache = share / ".wheel-cache"
    wheel_cache.mkdir()

    runner_calls: list[list[str]] = []

    def _runner(args: list[str]) -> int:
        runner_calls.append(args)
        # Rollback install fails (e.g. cached wheels missing for some deps).
        if "install" in args and "-r" in args:
            return 1
        return 0

    with patch.object(cli_mod, "_get_managed_venv", return_value=venv):
        with patch.object(cli_mod, "_resolve_manifest", return_value=_fake_manifest(["wifi_llapi"])):
            with patch.object(cli_mod, "_packaged_manifest_path", return_value=Path("/pkg/m.yaml")):
                with patch.object(cli_mod, "_probe_installed_plugins", return_value={"wifi_llapi"}):
                    with patch.object(cli_mod, "_last_good_path", return_value=last_good):
                        with patch.object(cli_mod, "_wheel_cache_path", return_value=wheel_cache):
                            with patch.object(cli_mod, "_snapshot_environment", return_value=None):
                                with pytest.raises(SystemExit) as exc:
                                    _handle_update(
                                        "main",
                                        runner=_runner,
                                        installer=lambda env: 0,
                                        verifier=lambda: False,
                                    )

    assert exc.value.code != 0
    err = capsys.readouterr().err
    assert "install.sh --offline" in err, f"missing manual-recovery guidance: {err!r}"
    # The offline rollback attempt still must have used --no-index.
    rollback = [c for c in runner_calls if "install" in c and "-r" in c]
    assert rollback and "--no-index" in rollback[0]


def test_wheel_cache_path_respects_testpilot_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The offline rollback wheel cache lives under TESTPILOT_HOME."""
    home = tmp_path / "custom-home"
    monkeypatch.setenv("TESTPILOT_HOME", str(home))

    path = cli_mod._wheel_cache_path()

    assert path == home / ".wheel-cache"
    assert path.parent == cli_mod._get_managed_venv().parent


def test_last_good_path_respects_testpilot_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """I-important2: the rollback snapshot must live under TESTPILOT_HOME.

    Regression: ``_last_good_path()`` hardcoded ``~/.local/share/testpilot`` even
    though ``_get_managed_venv()`` honors TESTPILOT_HOME, so the snapshot and the
    venv it describes could diverge.
    """
    home = tmp_path / "custom-home"
    monkeypatch.setenv("TESTPILOT_HOME", str(home))

    path = cli_mod._last_good_path()

    assert path == home / ".last-good.txt"
    # And it shares the same base as the managed venv it snapshots.
    assert path.parent == cli_mod._get_managed_venv().parent


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
