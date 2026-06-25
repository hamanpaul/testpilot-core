"""Test PluginLoader discovery and loading (core-in-isolation).

Plugin-specific discovery/load coverage (wifi_llapi / brcm_fw_upgrade) lives in
the plugin repos' CI. Here we only exercise the generic loader mechanism using
the in-repo SDK template plugin (``plugins/_template``), which ships with core.
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace

from testpilot.core.plugin_base import PluginBase
from testpilot.core.plugin_loader import PluginLoader


class _FakeEntryPoint:
    def __init__(self, name: str, value: str, *, dist_name: str = "testpilot") -> None:
        self.name = name
        self.value = value
        self.dist = SimpleNamespace(name=dist_name, metadata={"Name": dist_name})

    def load(self):
        module_name, _, attr_name = self.value.partition(":")
        module = importlib.import_module(module_name)
        return getattr(module, attr_name)


def _template_loader() -> PluginLoader:
    return PluginLoader.from_entry_points(
        [_FakeEntryPoint("template", "plugins._template.plugin:Plugin")]
    )


def test_discover_registered_plugins_excludes_template_skeleton():
    """entry-point discovery 列出已註冊 plugin；未註冊的 _template 骨架不出現。"""
    loader = _template_loader()
    names = loader.discover()
    assert names == ["template"]
    assert "_template" not in names


def test_load_returns_plugin_base_instance():
    """已註冊 plugin 應可正常載入並回傳 PluginBase 實例。"""
    loader = _template_loader()
    plugin = loader.load("template")
    assert isinstance(plugin, PluginBase)
    assert plugin.name == "template"


def test_discover_cases_reads_template_cases():
    """載入後的 plugin 應能從自身 cases/ 目錄發現至少一條 case。"""
    loader = _template_loader()
    plugin = loader.load("template")
    cases = plugin.discover_cases()
    assert len(cases) >= 1
    assert all("id" in case for case in cases)
