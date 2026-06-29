import zipfile, glob, subprocess, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
def test_skill_shipped_in_wheel(tmp_path):
    subprocess.run(["uv", "build", "--wheel", "-o", str(tmp_path)], cwd=ROOT, check=True)
    whl = glob.glob(str(tmp_path / "testpilot_core-*.whl"))[0]
    names = zipfile.ZipFile(whl).namelist()
    assert any("testpilot/_skills/testpilot-normal-test" in n for n in names), names[:30]
