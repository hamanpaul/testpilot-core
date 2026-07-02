"""Static-content assertions for scripts/install.sh.

These tests encode the contract for the rewritten installer:
- No token leaked into URLs
- Uses GH_TOKEN env var (not set -x)
- No editable plugin paths
- Has --offline branch with --no-index
- Installs core first, then plugins with --no-deps
"""
import pathlib

SH = (pathlib.Path(__file__).resolve().parents[1] / "scripts" / "install.sh").read_text()


def test_no_token_in_url_pattern():
    assert "x-access-token:" not in SH


def test_uses_gh_token_env_and_no_set_x():
    assert "GH_TOKEN" in SH
    assert "set -x" not in SH


def test_askpass_helper_reads_token_from_env_not_literal():
    # I5(a): the GIT_ASKPASS helper must read the token from the EXPORTED env at
    # call time, NOT have the literal secret substituted into the helper file.
    assert "GIT_ASKPASS" in SH
    # The old leaky pattern wrote the token via printf %s substitution:
    #   printf '#!/bin/sh\necho "%s"\n' "$GH_TOKEN"
    assert 'echo "%s"' not in SH, "askpass helper still substitutes the literal token"
    # The helper body must reference $GH_TOKEN (resolved when git calls it).
    assert "exec printf" in SH
    assert '"$GH_TOKEN"' in SH


def test_askpass_helper_cleaned_by_exit_trap():
    # I5(b): the helper must be removed via an EXIT trap so it is cleaned even
    # when pip fails under set -euo pipefail (a RETURN trap would not fire).
    assert "ASKPASS_HELPER" in SH
    exit_trap_lines = [
        line for line in SH.splitlines() if "trap" in line and "EXIT" in line
    ]
    assert any("ASKPASS_HELPER" in line for line in exit_trap_lines), exit_trap_lines


def test_no_editable_plugins_path():
    assert "plugins/wifi_llapi" not in SH and "plugins/brcm_fw_upgrade" not in SH


def test_has_offline_branch():
    assert "--offline" in SH and "--no-index" in SH


def test_installs_core_then_plugins_no_deps():
    assert "--no-deps" in SH


def test_invokes_legacy_migration():
    # I1: install.sh must wire in the legacy-migration command (best-effort).
    assert "install-migrate" in SH
    # best-effort: the migration call must not abort the install (|| true)
    assert "install-migrate || true" in SH


def test_serialwrap_installed_with_deps():
    # I4: serialwrap is public and does NOT depend on testpilot-core, so it must
    # be installed WITH its dependencies. The install helper takes a `with_deps`
    # flag; serialwrap must request deps (true), unlike plugins.
    import re

    sw_call = re.search(
        r'_install_pkg_online\s+"\$SERIALWRAP_REPO"\s+"\$SERIALWRAP_VERSION"\s+"serialwrap"\s+"(\w+)"',
        SH,
    )
    assert sw_call is not None, "serialwrap install call not found"
    assert sw_call.group(1) == "true", (
        f"serialwrap must be installed WITH deps (with_deps=true), got {sw_call.group(1)!r}"
    )

    # Plugins must still use the no-deps path.
    plugin_call = re.search(
        r'_install_pkg_online\s+"\$prepo"\s+"\$USE_VER"\s+"plugin:\$\{pname\}"\s+"(\w+)"',
        SH,
    )
    assert plugin_call is not None and plugin_call.group(1) == "false", (
        "plugins must keep the no-deps (with_deps=false) path"
    )
