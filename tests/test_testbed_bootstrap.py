"""Tests for stage_plugin_testbed helper."""
from __future__ import annotations

from pathlib import Path

import pytest

from testpilot.core.testbed_bootstrap import stage_plugin_testbed


def _make_plugin(plugin_dir: Path, body: str) -> None:
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "testbed.yaml.example").write_text(body, encoding="utf-8")


def test_stage_copies_plugin_example_into_configs(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugin-assets" / "wifi_llapi"
    configs_dir = tmp_path / "configs"
    configs_dir.mkdir()
    _make_plugin(plugin_dir, "testbed:\n  name: wifi-bench\n")

    result = stage_plugin_testbed(plugin_dir, "wifi_llapi", configs_dir)

    assert result == configs_dir / "testbed.yaml"
    assert result.read_text(encoding="utf-8") == "testbed:\n  name: wifi-bench\n"


def test_stage_overwrites_existing_configs_testbed(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugin-assets" / "wifi_llapi"
    configs_dir = tmp_path / "configs"
    configs_dir.mkdir()
    (configs_dir / "testbed.yaml").write_text("stale: true\n", encoding="utf-8")
    _make_plugin(plugin_dir, "testbed:\n  name: fresh\n")

    stage_plugin_testbed(plugin_dir, "wifi_llapi", configs_dir)

    assert (configs_dir / "testbed.yaml").read_text(encoding="utf-8") == "testbed:\n  name: fresh\n"


def test_stage_isolates_between_plugins(tmp_path: Path) -> None:
    plugin_a_dir = tmp_path / "plugin-assets" / "wifi_llapi"
    plugin_b_dir = tmp_path / "other-assets" / "brcm_fw_upgrade"
    configs_dir = tmp_path / "configs"
    configs_dir.mkdir()
    _make_plugin(plugin_a_dir, "testbed:\n  name: wifi\n")
    _make_plugin(plugin_b_dir, "testbed:\n  name: brcm\n")

    stage_plugin_testbed(plugin_a_dir, "wifi_llapi", configs_dir)
    assert (configs_dir / "testbed.yaml").read_text(encoding="utf-8") == "testbed:\n  name: wifi\n"

    stage_plugin_testbed(plugin_b_dir, "brcm_fw_upgrade", configs_dir)
    assert (configs_dir / "testbed.yaml").read_text(encoding="utf-8") == "testbed:\n  name: brcm\n"


def test_stage_creates_configs_dir_if_missing(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugin-assets" / "wifi_llapi"
    configs_dir = tmp_path / "configs"  # not created
    _make_plugin(plugin_dir, "testbed:\n  name: x\n")

    stage_plugin_testbed(plugin_dir, "wifi_llapi", configs_dir)

    assert (configs_dir / "testbed.yaml").exists()


def test_stage_raises_when_plugin_dir_missing(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugin-assets" / "missing"
    configs_dir = tmp_path / "configs"
    configs_dir.mkdir()

    with pytest.raises(FileNotFoundError) as exc:
        stage_plugin_testbed(plugin_dir, "nonexistent", configs_dir)
    assert "nonexistent" in str(exc.value)


def test_stage_raises_when_plugin_example_missing(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "plugin-assets" / "wifi_llapi"
    plugin_dir.mkdir(parents=True)  # plugin dir exists but no example
    configs_dir = tmp_path / "configs"
    configs_dir.mkdir()

    with pytest.raises(FileNotFoundError) as exc:
        stage_plugin_testbed(plugin_dir, "wifi_llapi", configs_dir)
    assert "testbed.yaml.example" in str(exc.value)
