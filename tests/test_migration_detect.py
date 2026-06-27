from testpilot.cli import _detect_legacy_installs


def test_detects_user_site_and_legacy_src():
    actions = _detect_legacy_installs({"user_site_testpilot": True, "pipx_testpilot": False, "legacy_src": True})
    assert "uninstall_user_site" in actions
    assert "remove_legacy_src" in actions
    assert "uninstall_pipx" not in actions


def test_clean_machine_no_actions():
    assert _detect_legacy_installs({"user_site_testpilot": False, "pipx_testpilot": False, "legacy_src": False}) == []


def test_detects_pipx():
    actions = _detect_legacy_installs({"user_site_testpilot": False, "pipx_testpilot": True, "legacy_src": False})
    assert "uninstall_pipx" in actions
    assert "uninstall_user_site" not in actions
    assert "remove_legacy_src" not in actions
