import pathlib
from testpilot.install.manifest import load_manifest, InstallManifest
ROOT = pathlib.Path(__file__).resolve().parents[1]
def test_load_manifest_parses_components():
    m = load_manifest(ROOT / "install-manifest.yaml")
    assert isinstance(m, InstallManifest)
    assert m.core.distribution == "testpilot-core"
    assert m.core.repo == "hamanpaul/testpilot-core"
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


def _write(tmp_path, text):
    p = tmp_path / "install-manifest.yaml"
    p.write_text(text)
    return p


def test_core_and_plugin_version_optional(tmp_path):
    """core/plugins may omit version (= resolve latest-compatible)."""
    p = _write(
        tmp_path,
        """
core:
  distribution: testpilot-core
  repo: hamanpaul/testpilot-core
  private: true
plugins:
  - name: wifi_llapi
    repo: hamanpaul/wifi_llapi
    api_version: "1.1"
    private: true
serialwrap:
  repo: hamanpaul/serialwrap
  version: "0.2.1"
  private: false
""",
    )
    m = load_manifest(p)
    assert m.core.version is None
    assert next(x for x in m.plugins if x.name == "wifi_llapi").version is None
    assert m.serialwrap.version == "0.2.1"


def test_serialwrap_requires_version(tmp_path):
    """serialwrap stays pinned: a missing serialwrap version is an error."""
    import pytest
    p = _write(
        tmp_path,
        """
core:
  distribution: testpilot-core
  repo: hamanpaul/testpilot-core
plugins: []
serialwrap:
  repo: hamanpaul/serialwrap
  private: false
""",
    )
    with pytest.raises((KeyError, ValueError)):
        load_manifest(p)
