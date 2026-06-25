"""Contract tests for entry-points-based plugin discovery (core-in-isolation).

The generic loader mechanism is exercised with fake entry points and the in-repo
SDK template plugin (``plugins/_template``). Plugin-specific registration and
import-hygiene coverage (wifi_llapi / brcm_fw_upgrade) lives in the plugin repos.
"""

from __future__ import annotations

import importlib
import importlib.metadata
from pathlib import Path
import pytest
from types import SimpleNamespace


from testpilot.core.plugin_base import PluginBase
from testpilot.core.plugin_loader import PluginLoader


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_LOADER = ROOT / "src" / "testpilot" / "core" / "plugin_loader.py"
MISSING_PLUGINS_DIR = ROOT / "__missing_plugins_dir__"
# A real, in-repo, importable plugin module that ships with core (the SDK template).
TEMPLATE_ENTRY_POINTS = {
    "template": "plugins._template.plugin:Plugin",
}
LEGACY_LOADER_MARKERS = (
    "spec_from_file_location",
    "sys.path.insert",
    "iterdir",
)


class _FakeEntryPoint:
    def __init__(self, name: str, value: str, *, dist_name: str = "testpilot") -> None:
        self.name = name
        self.value = value
        self.dist = SimpleNamespace(name=dist_name, metadata={"Name": dist_name})

    def load(self):
        module_name, _, attr_name = self.value.partition(":")
        module = importlib.import_module(module_name)
        return getattr(module, attr_name)


def _set_fake_entry_points(monkeypatch, fake_points: list[_FakeEntryPoint]) -> None:
    def fake_entry_points(*, group: str):
        assert group == "testpilot.plugins"
        return fake_points

    monkeypatch.setattr(importlib.metadata, "entry_points", fake_entry_points)

    import testpilot.core.plugin_loader as plugin_loader_module

    if hasattr(plugin_loader_module, "entry_points"):
        monkeypatch.setattr(plugin_loader_module, "entry_points", fake_entry_points)
    if hasattr(plugin_loader_module, "metadata"):
        monkeypatch.setattr(plugin_loader_module.metadata, "entry_points", fake_entry_points)


def _patch_template_entry_points(monkeypatch) -> None:
    fake_points = [
        _FakeEntryPoint(name, value) for name, value in TEMPLATE_ENTRY_POINTS.items()
    ]
    _set_fake_entry_points(monkeypatch, fake_points)


def test_plugin_loader_discovers_plugins_via_entry_points(monkeypatch) -> None:
    _patch_template_entry_points(monkeypatch)

    loader = PluginLoader(MISSING_PLUGINS_DIR)
    names = loader.discover()
    assert set(names) == set(TEMPLATE_ENTRY_POINTS)
    assert "_template" not in names


def test_plugin_loader_rejects_duplicate_entry_point_names(monkeypatch) -> None:
    _set_fake_entry_points(
        monkeypatch,
        [
            _FakeEntryPoint("template", "plugins._template.plugin:Plugin", dist_name="repo-testpilot"),
            _FakeEntryPoint("template", "vendor.extra.plugin:Plugin", dist_name="vendor-plugin-pack"),
        ],
    )

    loader = PluginLoader(MISSING_PLUGINS_DIR)
    with pytest.raises(ValueError, match="duplicate testpilot.plugins entry point names detected") as exc_info:
        loader.discover()
    assert "repo-testpilot" in str(exc_info.value)
    assert "vendor-plugin-pack" in str(exc_info.value)


def test_plugin_loader_loads_plugins_via_entry_points(monkeypatch) -> None:
    _patch_template_entry_points(monkeypatch)

    loader = PluginLoader(MISSING_PLUGINS_DIR)
    assert isinstance(loader.load("template"), PluginBase)


def test_plugin_loader_has_no_legacy_dir_scan_or_sys_path_markers() -> None:
    source = PLUGIN_LOADER.read_text(encoding="utf-8")
    hits = [marker for marker in LEGACY_LOADER_MARKERS if marker in source]
    assert not hits, f"plugin_loader.py still contains legacy markers: {hits}"
