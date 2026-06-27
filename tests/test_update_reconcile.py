from testpilot.cli import _reconcile_plan, ReconcilePlan


def test_reconcile_uninstalls_dropped_plugins():
    plan = _reconcile_plan(installed={"wifi_llapi", "old_plugin"}, manifest={"wifi_llapi", "brcm_fw_upgrade"})
    assert plan.to_uninstall == {"old_plugin"}
    assert plan.to_install == {"brcm_fw_upgrade"}


def test_reconcile_noop_when_aligned():
    plan = _reconcile_plan(installed={"wifi_llapi"}, manifest={"wifi_llapi"})
    assert not plan.to_uninstall and not plan.to_install


def test_update_no_longer_requires_git_checkout(monkeypatch, tmp_path):
    """managed venv exists but NO .git checkout -> must not exit with 'Managed checkout not found'"""
    import testpilot.cli as cli_mod

    # Create a fake managed venv
    fake_venv = tmp_path / ".venv"
    fake_venv.mkdir()

    monkeypatch.setattr(cli_mod, "_get_managed_venv", lambda: fake_venv)
    monkeypatch.setattr(cli_mod, "_probe_installed_plugins", lambda: {"wifi_llapi", "old_plugin"})
    monkeypatch.setattr(cli_mod, "_resolve_manifest", lambda ref: {"wifi_llapi"})

    calls = []
    rc = cli_mod._handle_update(None, runner=lambda args: calls.append(args) or 0)

    # Should not raise SystemExit
    # old_plugin should be uninstalled
    uninstall_calls = [c for c in calls if "uninstall" in c]
    assert any("old_plugin" in str(c) for c in uninstall_calls), f"Expected old_plugin uninstall in {calls}"
    # wifi_llapi should be (re)installed
    install_calls = [c for c in calls if "install" in c and "uninstall" not in c]
    assert any("wifi_llapi" in str(c) for c in install_calls), f"Expected wifi_llapi install in {calls}"
