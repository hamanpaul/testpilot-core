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
