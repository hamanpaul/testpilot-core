import glob, subprocess, zipfile, pathlib
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def wheel_names(tmp_path_factory):
    out = tmp_path_factory.mktemp("wheel")
    subprocess.run(["uv", "build", "--wheel", "-o", str(out)], cwd=ROOT, check=True)
    whl = glob.glob(str(out / "testpilot_core-*.whl"))[0]
    return zipfile.ZipFile(whl).namelist()


def test_wheel_has_skill_and_no_run_bundles(wheel_names):
    assert any("testpilot/_skills/testpilot-normal-test" in n for n in wheel_names)
    # no runtime report bundle dirs (e.g. reports/20260627_…) leaked in
    assert not any("/reports/" in n and any(seg[:1].isdigit() for seg in n.split("/")) for n in wheel_names)


def test_wheel_ships_install_manifest_and_installer(wheel_names):
    # C1.1: the authoritative manifest + installer must ship inside the wheel so
    # `testpilot --update` can resolve them in a real (non-checkout) install.
    assert any("testpilot/_install/install-manifest.yaml" in n for n in wheel_names), wheel_names
    assert any("testpilot/_install/install.sh" in n for n in wheel_names), wheel_names
