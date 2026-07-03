"""Test TestbedConfig loading and variable resolution.

These tests supply their own minimal testbed via a tmp_path fixture instead of
reading the git-ignored ``configs/testbed.yaml`` (which only CI's bootstrap step
materializes), so a fresh clone ``pytest`` is green. The inline testbed is
deliberately credential-free (name + one device + one SSID variable only) to
keep the R-21 secret scan clean.
"""

import textwrap
from pathlib import Path

import pytest

from testpilot.core.testbed_config import TestbedConfig

# Minimal, credential-free testbed matching the CI bootstrap shape.
_MINIMAL_TESTBED = textwrap.dedent(
    """\
    testbed:
      name: lab-bench-1
      devices:
        DUT:
          role: ap
          transport: serial
          selector: COM0
      variables:
        SSID_5G: testpilot5G
    """
)


@pytest.fixture
def cfg(tmp_path: Path) -> TestbedConfig:
    path = tmp_path / "testbed.yaml"
    path.write_text(_MINIMAL_TESTBED, encoding="utf-8")
    return TestbedConfig(path)


def test_load_config(cfg: TestbedConfig) -> None:
    assert cfg.name == "lab-bench-1"
    assert "DUT" in cfg.devices


def test_variable_resolve(cfg: TestbedConfig) -> None:
    assert "testpilot5G" in cfg.resolve("SSID is {{SSID_5G}}")


def test_missing_variable(cfg: TestbedConfig) -> None:
    assert "{{NONEXIST}}" in cfg.resolve("{{NONEXIST}}")
