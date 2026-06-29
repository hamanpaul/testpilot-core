from testpilot.cli import _reconcile_plan, ReconcilePlan


def test_reconcile_uninstalls_dropped_plugins():
    plan = _reconcile_plan(installed={"wifi_llapi", "old_plugin"}, manifest={"wifi_llapi", "brcm_fw_upgrade"})
    assert plan.to_uninstall == {"old_plugin"}
    assert plan.to_install == {"brcm_fw_upgrade"}


def test_reconcile_noop_when_aligned():
    plan = _reconcile_plan(installed={"wifi_llapi"}, manifest={"wifi_llapi"})
    assert not plan.to_uninstall and not plan.to_install


def test_update_no_longer_requires_git_checkout(monkeypatch, tmp_path):
    """managed venv exists but NO .git checkout -> must not exit with 'Managed checkout not found'.

    Wheel model: the pinned set is reinstalled via the packaged installer seam
    (NOT pip bare-name); dropped plugins are uninstalled via the pip runner.
    """
    import testpilot.cli as cli_mod
    from testpilot.install.manifest import Core, InstallManifest, Plugin

    # Create a fake managed venv
    fake_venv = tmp_path / ".venv"
    fake_venv.mkdir()

    manifest = InstallManifest(
        core=Core(distribution="testpilot-core", version="0.3.0", repo="x/y"),
        plugins=[Plugin(name="wifi_llapi", repo="x/wifi_llapi", version="0.3.0", api_version="1.1")],
    )

    monkeypatch.setattr(cli_mod, "_get_managed_venv", lambda: fake_venv)
    monkeypatch.setattr(cli_mod, "_probe_installed_plugins", lambda: {"wifi_llapi", "old_plugin"})
    monkeypatch.setattr(cli_mod, "_resolve_manifest", lambda ref: manifest)
    monkeypatch.setattr(cli_mod, "_packaged_manifest_path", lambda: tmp_path / "install-manifest.yaml")

    calls = []
    installer_calls = []
    rc = cli_mod._handle_update(
        None,
        runner=lambda args: calls.append(args) or 0,
        installer=lambda env: installer_calls.append(env) or 0,
        verifier=lambda: True,
    )

    assert rc == 0
    # pinned set reinstalled via the installer seam (not pip bare-name)
    assert len(installer_calls) == 1, installer_calls
    # old_plugin should be uninstalled
    uninstall_calls = [c for c in calls if "uninstall" in c]
    assert any("old_plugin" in str(c) for c in uninstall_calls), f"Expected old_plugin uninstall in {calls}"
    # NEVER a bare-name pip install of wifi_llapi
    bare_installs = [c for c in calls if "install" in c and "uninstall" not in c and "-r" not in c]
    assert not bare_installs, f"Unexpected bare-name pip install: {bare_installs}"
