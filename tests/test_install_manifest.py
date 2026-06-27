import pathlib
from testpilot.install.manifest import load_manifest, InstallManifest
ROOT = pathlib.Path(__file__).resolve().parents[1]
def test_load_manifest_parses_components():
    m = load_manifest(ROOT / "install-manifest.yaml")
    assert isinstance(m, InstallManifest)
    assert m.core.distribution == "testpilot-core"
    assert m.core.version
    names = {p.name for p in m.plugins}
    assert "wifi_llapi" in names
    wifi = next(p for p in m.plugins if p.name == "wifi_llapi")
    assert wifi.api_version
    assert wifi.private is True
    assert m.serialwrap.repo == "hamanpaul/serialwrap"
def test_selected_plugins_subset():
    m = load_manifest(ROOT / "install-manifest.yaml")
    assert [p.name for p in m.selected(["wifi_llapi"])] == ["wifi_llapi"]
def test_plugin_version_override():
    m = load_manifest(ROOT / "install-manifest.yaml")
    sel = m.selected(["wifi_llapi@9.9.9"])
    assert next(p for p in sel if p.name == "wifi_llapi").version == "9.9.9"
def test_unknown_plugin_raises():
    import pytest
    m = load_manifest(ROOT / "install-manifest.yaml")
    with pytest.raises(KeyError):
        m.selected(["does_not_exist"])
