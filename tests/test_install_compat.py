import pathlib
import pytest
from testpilot.install.compat import manifest_compat_report

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_compatible_pair_ok():
    rep = manifest_compat_report(core_api="1.1", plugins=[("wifi_llapi", "1.1")])
    assert rep.ok and not rep.failures


def test_minor_too_new_fails():
    rep = manifest_compat_report(core_api="1.1", plugins=[("wifi_llapi", "1.2")])
    assert not rep.ok and any("wifi_llapi" in f for f in rep.failures)


def test_major_mismatch_fails():
    rep = manifest_compat_report(core_api="1.1", plugins=[("brcm_fw_upgrade", "2.0")])
    assert not rep.ok


def test_install_doctor_command_passes_on_repo_manifest():
    from click.testing import CliRunner
    from testpilot.cli import main

    runner = CliRunner()
    result = runner.invoke(main, ["install-doctor", "--manifest", str(ROOT / "install-manifest.yaml")])
    assert result.exit_code == 0, f"install-doctor failed:\n{result.output}"
