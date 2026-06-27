import glob, subprocess, zipfile, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
def test_wheel_has_skill_and_no_run_bundles(tmp_path):
    subprocess.run(["uv", "build", "--wheel", "-o", str(tmp_path)], cwd=ROOT, check=True)
    whl = glob.glob(str(tmp_path / "testpilot_core-*.whl"))[0]
    names = zipfile.ZipFile(whl).namelist()
    assert any("testpilot/_skills/testpilot-normal-test" in n for n in names)
    # no runtime report bundle dirs (e.g. reports/20260627_…) leaked in
    assert not any("/reports/" in n and any(seg[:1].isdigit() for seg in n.split("/")) for n in names)
