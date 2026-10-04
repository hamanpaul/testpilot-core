"""versioned plugin contract（change versioned-plugin-contract）。"""

from __future__ import annotations

import re
from typing import Any

import click
import pytest


def test_api_version_is_semver():
    from testpilot.api import API_VERSION

    assert re.fullmatch(r"\d+\.\d+", API_VERSION)
    assert API_VERSION == "1.7"


def test_tier2_recovery_contract_types_are_exported():
    from testpilot.api import Tier2RecoveryAudit, Tier2RecoveryContext

    assert Tier2RecoveryContext.__name__ == "Tier2RecoveryContext"
    assert Tier2RecoveryAudit.__name__ == "Tier2RecoveryAudit"


def test_prepared_run_no_io_is_public_and_opt_in():
    from testpilot.api import PreparedRun

    assert PreparedRun(cases=[]).no_io is False
    assert PreparedRun(cases=[], no_io=True).no_io is True
    assert PreparedRun(cases=[]).run_start_gate is None


def test_run_start_gate_contract_types_are_public_and_frozen():
    from dataclasses import FrozenInstanceError

    from testpilot.api import (
        PrepareRunAfterCaptureContext,
        PrepareRunGateEvidence,
        PrepareRunGateOutcome,
        PrepareRunGateResult,
        RunCapability,
    )

    context = PrepareRunAfterCaptureContext("run-1", 0, "binding-1")
    result = PrepareRunGateResult(
        PrepareRunGateOutcome.ACCEPTED,
        "identity_verified",
        (PrepareRunGateEvidence("dut_identity", PrepareRunGateOutcome.ACCEPTED, "same_boot"),),
    )

    assert RunCapability.STRICT_CAPTURE_BINDING.value == "strict_capture_binding"
    assert context.start_sequence == 0
    assert result.to_payload() == {
        "outcome": "accepted",
        "reason_code": "identity_verified",
        "evidence": [
            {"check": "dut_identity", "outcome": "accepted", "reason_code": "same_boot"}
        ],
    }
    with pytest.raises(FrozenInstanceError):
        result.reason_code = "changed"


def test_incompatible_error_exported():
    from testpilot.api import IncompatiblePluginError

    assert issubclass(IncompatiblePluginError, Exception)


@pytest.mark.parametrize(
    ("declared", "api", "ok"),
    [
        ("1.0", "1.0", True),
        ("1.0", "1.3", True),
        ("1.3", "1.4", True),
        ("1.4", "1.5", True),
        ("1.5", "1.5", True),
        ("1.5", "1.6", True),
        ("1.6", "1.7", True),
        ("1.7", "1.7", True),
        ("1.4", "1.3", False),
        ("1.5", "1.4", False),
        ("1.6", "1.5", False),
        ("1.7", "1.6", False),
        ("1.3", "1.0", False),
        ("2.0", "1.6", False),
        (None, "1.0", False),
    ],
)
def test_compat_matrix(declared, api, ok):
    from testpilot.api import IncompatiblePluginError
    from testpilot.core.plugin_loader import _check_api_compat

    if ok:
        _check_api_compat("dummy", declared, api)
    else:
        with pytest.raises(IncompatiblePluginError):
            _check_api_compat("dummy", declared, api)


def test_malformed_sdk_api_version_reports_sdk_side_error():
    from testpilot.api import IncompatiblePluginError
    from testpilot.core.plugin_loader import _check_api_compat

    with pytest.raises(
        IncompatiblePluginError,
        match=r"testpilot SDK API version 'bad'.*major\.minor",
    ):
        _check_api_compat("dummy", "1.0", "bad")


class _FakeEntryPoint:
    def __init__(self, name: str, plugin_cls: type) -> None:
        self.name = name
        self._plugin_cls = plugin_cls

    def load(self):
        return self._plugin_cls


def _plugin_class(name: str, api_version: Any) -> type:
    from testpilot.core.plugin_base import PluginBase

    class Plugin(PluginBase):
        @property
        def name(self) -> str:
            return name

        def discover_cases(self) -> list[dict[str, Any]]:
            return []

        def execute_step(
            self,
            case: dict[str, Any],
            step: dict[str, Any],
            topology: Any,
        ) -> dict[str, Any]:
            return {}

        def evaluate(self, case: dict[str, Any], results: dict[str, Any]) -> bool:
            return True

    Plugin.api_version = api_version
    return Plugin


@pytest.mark.parametrize("declared", ["1.3", "1.4"])
def test_loader_accepts_compatible_plugin_and_caches_it(declared):
    from testpilot.core.plugin_loader import PluginLoader

    loader = PluginLoader.from_entry_points([
        _FakeEntryPoint("dummy", _plugin_class("dummy", declared)),
    ])

    plugin = loader.load("dummy")

    assert plugin.name == "dummy"
    assert loader.loaded == {"dummy": plugin}


def test_loader_rejects_api_14_plugin_on_api_13_host(monkeypatch):
    import testpilot.api

    from testpilot.api import IncompatiblePluginError
    from testpilot.core.plugin_loader import PluginLoader

    monkeypatch.setattr(testpilot.api, "API_VERSION", "1.3")
    loader = PluginLoader.from_entry_points([
        _FakeEntryPoint("dummy", _plugin_class("dummy", "1.4")),
    ])

    with pytest.raises(IncompatiblePluginError):
        loader.load("dummy")

    assert loader.loaded == {}


def test_loader_rejects_api_15_plugin_on_api_14_host(monkeypatch):
    import testpilot.api

    from testpilot.api import IncompatiblePluginError
    from testpilot.core.plugin_loader import PluginLoader

    monkeypatch.setattr(testpilot.api, "API_VERSION", "1.4")
    loader = PluginLoader.from_entry_points([
        _FakeEntryPoint("dummy", _plugin_class("dummy", "1.5")),
    ])

    with pytest.raises(IncompatiblePluginError):
        loader.load("dummy")

    assert loader.loaded == {}


def test_loader_accepts_api_15_plugin_on_api_16_host():
    from testpilot.core.plugin_loader import PluginLoader

    loader = PluginLoader.from_entry_points([
        _FakeEntryPoint("dummy", _plugin_class("dummy", "1.5")),
    ])

    assert loader.load("dummy").name == "dummy"


def test_loader_accepts_api_17_plugin_on_api_17_host(monkeypatch):
    import testpilot.api

    from testpilot.core.plugin_loader import PluginLoader

    monkeypatch.setattr(testpilot.api, "API_VERSION", "1.7")
    loader = PluginLoader.from_entry_points([
        _FakeEntryPoint("dummy", _plugin_class("dummy", "1.7")),
    ])

    assert loader.load("dummy").name == "dummy"


def test_loader_rejects_api_17_plugin_on_api_16_host_before_instantiation(monkeypatch):
    import testpilot.api

    from testpilot.api import IncompatiblePluginError, PluginBase
    from testpilot.core.plugin_loader import PluginLoader

    class Api17Plugin(PluginBase):
        api_version = "1.7"
        initialized = False

        def __init__(self) -> None:
            type(self).initialized = True

        @property
        def name(self) -> str:
            return "dummy"

        def discover_cases(self) -> list[dict[str, Any]]:
            return []

        def execute_step(
            self,
            case: dict[str, Any],
            step: dict[str, Any],
            topology: Any,
        ) -> dict[str, Any]:
            return {}

        def evaluate(self, case: dict[str, Any], results: dict[str, Any]) -> bool:
            return True

    monkeypatch.setattr(testpilot.api, "API_VERSION", "1.6")
    loader = PluginLoader.from_entry_points([
        _FakeEntryPoint("dummy", Api17Plugin),
    ])

    with pytest.raises(IncompatiblePluginError):
        loader.load("dummy")

    assert Api17Plugin.initialized is False
    assert loader.loaded == {}


@pytest.mark.parametrize("declared", [None, "1", 1.0, "1.8", "2.0"])
def test_loader_rejects_incompatible_plugin_without_caching(declared):
    from testpilot.api import IncompatiblePluginError
    from testpilot.core.plugin_loader import PluginLoader

    loader = PluginLoader.from_entry_points([
        _FakeEntryPoint("dummy", _plugin_class("dummy", declared)),
    ])

    with pytest.raises(IncompatiblePluginError):
        loader.load("dummy")

    assert loader.loaded == {}


def test_loader_rejects_incompatible_plugin_before_instantiation():
    from testpilot.api import IncompatiblePluginError, PluginBase
    from testpilot.core.plugin_loader import PluginLoader

    class IncompatiblePlugin(PluginBase):
        api_version = "2.0"
        initialized = False

        def __init__(self) -> None:
            type(self).initialized = True

        @property
        def name(self) -> str:
            return "dummy"

        def discover_cases(self) -> list[dict[str, Any]]:
            return []

        def execute_step(
            self,
            case: dict[str, Any],
            step: dict[str, Any],
            topology: Any,
        ) -> dict[str, Any]:
            return {}

        def evaluate(self, case: dict[str, Any], results: dict[str, Any]) -> bool:
            return True

    loader = PluginLoader.from_entry_points([
        _FakeEntryPoint("dummy", IncompatiblePlugin),
    ])

    with pytest.raises(IncompatiblePluginError):
        loader.load("dummy")

    assert IncompatiblePlugin.initialized is False
    assert loader.loaded == {}


def test_loader_rejects_non_plugin_base_class_before_instantiation():
    from testpilot.core.plugin_loader import PluginLoader

    class NotAPlugin:
        api_version = "1.0"
        initialized = False

        def __init__(self) -> None:
            type(self).initialized = True

    loader = PluginLoader.from_entry_points([
        _FakeEntryPoint("dummy", NotAPlugin),
    ])

    with pytest.raises(TypeError, match="Plugin class must inherit PluginBase"):
        loader.load("dummy")

    assert NotAPlugin.initialized is False
    assert loader.loaded == {}


def test_load_all_rejects_incompatible_plugin_explicitly():
    from testpilot.api import IncompatiblePluginError
    from testpilot.core.plugin_loader import PluginLoader

    loader = PluginLoader.from_entry_points([
        _FakeEntryPoint("dummy", _plugin_class("dummy", "2.0")),
    ])

    with pytest.raises(IncompatiblePluginError):
        loader.load_all()

    assert loader.loaded == {}


def test_cli_wraps_incompatible_plugin_error(monkeypatch):
    from testpilot.api import IncompatiblePluginError
    from testpilot.cli_support import load_registered_plugin

    def raise_incompatible(self, name):
        del self, name
        raise IncompatiblePluginError("plugin 'dummy' must declare api_version")

    monkeypatch.setattr(
        "testpilot.core.plugin_loader.PluginLoader.load",
        raise_incompatible,
    )

    with pytest.raises(click.ClickException, match="api_version"):
        load_registered_plugin("dummy")
