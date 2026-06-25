"""Test TestbedConfig loading and variable resolution."""

from pathlib import Path

from testpilot.core.testbed_config import TestbedConfig


def test_load_config():
    root = Path(__file__).resolve().parents[1]
    cfg = TestbedConfig(root / "configs" / "testbed.yaml")
    assert cfg.name == "lab-bench-1"
    assert "DUT" in cfg.devices


def test_variable_resolve():
    root = Path(__file__).resolve().parents[1]
    cfg = TestbedConfig(root / "configs" / "testbed.yaml")
    result = cfg.resolve("SSID is {{SSID_5G}}")
    assert "testpilot5G" in result


def test_missing_variable():
    root = Path(__file__).resolve().parents[1]
    cfg = TestbedConfig(root / "configs" / "testbed.yaml")
    result = cfg.resolve("{{NONEXIST}}")
    assert "{{NONEXIST}}" in result
