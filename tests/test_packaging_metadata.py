import tomllib, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
def test_distribution_named_testpilot_core():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert data["project"]["name"] == "testpilot-core"
def test_version_is_dynamic_from_version_file():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert "version" in data["project"].get("dynamic", [])
    assert data["tool"]["hatch"]["version"]["path"] == "VERSION"
def test_console_script_unchanged():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert data["project"]["scripts"]["testpilot"] == "testpilot.cli:main"
