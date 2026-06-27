"""Tests for _verify_install_wheel_mode (Task 5 — wheel-mode verify-install)."""

from testpilot.cli import _verify_install_wheel_mode  # new pure function


def test_wheel_mode_reports_entrypoint_plugins():
    rows = _verify_install_wheel_mode(probe={
        "wrapper_ok": True, "core_version": "0.3.0",
        "plugins": [{"name": "wifi_llapi", "version": "0.3.0", "loads": True, "api": "1.1"}],
        "serialwrap": True, "skill_packaged": True, "stray_import": None,
    })
    assert all(ok for ok, _ in rows)


def test_wheel_mode_fails_on_incompatible_plugin():
    rows = _verify_install_wheel_mode(probe={
        "wrapper_ok": True, "core_version": "0.3.0",
        "plugins": [{"name": "wifi_llapi", "version": "0.3.0", "loads": False, "api": "2.0",
                     "error": "IncompatiblePluginError"}],
        "serialwrap": True, "skill_packaged": True, "stray_import": None,
    })
    assert any(not ok and "wifi_llapi" in msg for ok, msg in rows)


def test_wheel_mode_warns_on_stray_import():
    rows = _verify_install_wheel_mode(probe={
        "wrapper_ok": True, "core_version": "0.3.0", "plugins": [],
        "serialwrap": True, "skill_packaged": True,
        "stray_import": "/home/u/.local/lib/python3.12/site-packages/testpilot",
    })
    assert any("WARN" in msg and "managed" in msg.lower() for _, msg in rows)


def test_wheel_mode_fails_when_core_not_importable():
    rows = _verify_install_wheel_mode(probe={
        "wrapper_ok": True, "core_version": None, "plugins": [],
        "serialwrap": False, "skill_packaged": True, "stray_import": None,
    })
    assert any(not ok and "core" in msg.lower() for ok, msg in rows)
