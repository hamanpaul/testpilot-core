from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from testpilot.core.azure_auth import AzureAgentRuntime, AzureAgentState, AzureAgentStatus
from testpilot.core.orchestrator import Orchestrator
from testpilot.core.plugin_base import PluginBase
from testpilot.core.run_loop import run as run_core_loop
from testpilot.core.run_start_gate import (
    PrepareRunAfterCaptureContext,
    PrepareRunGateOutcome,
    PrepareRunGateResult,
    RunCapability,
)
from testpilot.core.testbed_config import TestbedConfig


class _StopBeforeCapture(Exception):
    pass


class _Loader:
    def __init__(self, plugin: PluginBase) -> None:
        self.plugin = plugin
        self.load_count = 0

    def load(self, name: str) -> PluginBase:
        assert name == self.plugin.name
        self.load_count += 1
        return self.plugin


class _Reporter:
    def build_reports(self, run_result: Any) -> dict[str, Any]:
        del run_result
        return {"status": "ok"}


class _Plugin(PluginBase):
    api_version = "1.6"

    @property
    def name(self) -> str:
        return "fake"

    def discover_cases(self) -> list[dict[str, Any]]:
        return []

    def execute_step(
        self,
        case: dict[str, Any],
        step: dict[str, Any],
        topology: Any,
    ) -> dict[str, Any]:
        del case, step, topology
        return {"success": True, "output": "", "captured": {}, "timing": 0.0}

    def evaluate(self, case: dict[str, Any], results: dict[str, Any]) -> bool:
        del case, results
        return True


class _StrictPlugin(_Plugin):
    required_run_capabilities = frozenset({RunCapability.STRICT_CAPTURE_BINDING})

    def prepare_run_after_capture(
        self,
        prepared: Any,
        context: PrepareRunAfterCaptureContext,
    ) -> PrepareRunGateResult:
        del prepared, context
        return PrepareRunGateResult(PrepareRunGateOutcome.ACCEPTED, "verified")


def _make_orchestrator(
    tmp_path: Path,
    plugin: PluginBase,
    *,
    config_path: Path | None = None,
) -> Orchestrator:
    project_root = tmp_path / "project"
    project_root.mkdir(exist_ok=True)
    selected_config = config_path or project_root / "selected-testbed.yaml"
    if config_path is None:
        selected_config.write_text("testbed:\n  name: selected\n  devices: {}\n", encoding="utf-8")
    orchestrator = Orchestrator(
        project_root=project_root,
        plugins_dir=project_root / "plugins",
        config_path=selected_config,
        agent_runtime=AzureAgentRuntime(AzureAgentStatus(AzureAgentState.DISABLED_NO_KEY)),
    )
    orchestrator.loader = _Loader(plugin)  # type: ignore[assignment]
    return orchestrator


def test_plugin_base_testbed_binding_default_is_a_noop() -> None:
    plugin = _Plugin()

    assert plugin.bind_testbed_config(object()) is None


def test_public_custom_runner_gets_exact_selected_config_once_per_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    received: list[TestbedConfig] = []

    class Plugin(_Plugin):
        def bind_testbed_config(self, topology: Any) -> None:
            events.append("bind_testbed_config")
            received.append(topology)

        def bind_project_root(self, project_root: Path | str | None) -> None:
            del project_root
            events.append("bind_project_root")

        def create_runner(self) -> Any:
            events.append("create_runner")

            class Runner:
                def run(self, *args: Any) -> dict[str, Any]:
                    del args
                    assert received[-1] is orchestrator.config
                    assert received[-1].name == "selected"
                    return {"status": "ok"}

            return Runner()

    selected = tmp_path / "selected.yaml"
    selected.write_text("testbed:\n  name: selected\n  devices: {}\n", encoding="utf-8")
    cwd = tmp_path / "different-cwd"
    (cwd / "configs").mkdir(parents=True)
    (cwd / "configs" / "testbed.yaml").write_text(
        "testbed:\n  name: cwd-default\n  devices: {}\n", encoding="utf-8"
    )
    plugin = Plugin()
    orchestrator = _make_orchestrator(tmp_path, plugin, config_path=selected)
    selected_object = orchestrator.config
    monkeypatch.chdir(cwd)

    def unexpected_reload(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        pytest.fail("Core reconstructed or reloaded the selected testbed config")

    monkeypatch.setattr(TestbedConfig, "__init__", unexpected_reload)
    monkeypatch.setattr(TestbedConfig, "load", unexpected_reload)

    for _ in range(2):
        assert orchestrator.run("fake")["status"] == "ok"

    assert received == [selected_object, selected_object]
    assert events == [
        "bind_testbed_config",
        "bind_project_root",
        "create_runner",
        "bind_testbed_config",
        "bind_project_root",
        "create_runner",
    ]


def test_public_reporter_fallback_does_not_bind_same_plugin_twice(
    tmp_path: Path,
) -> None:
    events: list[str] = []
    received: list[Any] = []

    class Plugin(_Plugin):
        def bind_testbed_config(self, topology: Any) -> None:
            events.append("bind_testbed_config")
            received.append(topology)

        def bind_project_root(self, project_root: Path | str | None) -> None:
            del project_root
            events.append("bind_project_root")

        def create_reporter(self) -> _Reporter:
            events.append("create_reporter")
            return _Reporter()

        def prepare_run(self, case_ids: Any) -> Any:
            del case_ids
            events.append("prepare_run")
            raise _StopBeforeCapture

    plugin = Plugin()
    orchestrator = _make_orchestrator(tmp_path, plugin)
    selected_object = orchestrator.config

    with pytest.raises(_StopBeforeCapture):
        orchestrator.run("fake", ["D001"])

    assert received == [selected_object]
    assert events == [
        "bind_testbed_config",
        "bind_project_root",
        "create_reporter",
        "bind_project_root",
        "prepare_run",
    ]


def test_public_fallback_binds_a_distinct_reloaded_plugin_instance(
    tmp_path: Path,
) -> None:
    events: list[str] = []
    received: list[tuple[PluginBase, Any]] = []

    class Plugin(_Plugin):
        def __init__(self, label: str) -> None:
            super().__init__()
            self.label = label

        def bind_testbed_config(self, topology: Any) -> None:
            events.append(f"{self.label}:bind_testbed_config")
            received.append((self, topology))

        def bind_project_root(self, project_root: Path | str | None) -> None:
            del project_root
            events.append(f"{self.label}:bind_project_root")

        def create_reporter(self) -> _Reporter:
            events.append(f"{self.label}:create_reporter")
            return _Reporter()

        def prepare_run(self, case_ids: Any) -> Any:
            del case_ids
            events.append(f"{self.label}:prepare_run")
            raise _StopBeforeCapture

    first = Plugin("first")
    second = Plugin("second")

    class _SequencedLoader:
        def __init__(self) -> None:
            self._plugins = iter((first, second))

        def load(self, name: str) -> Plugin:
            assert name == "fake"
            return next(self._plugins)

    orchestrator = _make_orchestrator(tmp_path, first)
    orchestrator.loader = _SequencedLoader()  # type: ignore[assignment]
    selected_object = orchestrator.config

    with pytest.raises(_StopBeforeCapture):
        orchestrator.run("fake", ["D001"])

    assert len(received) == 2
    assert received[0][0] is first
    assert received[1][0] is second
    assert received[0][0] is not received[1][0]
    assert received[0][1] is selected_object
    assert received[1][1] is selected_object
    assert events == [
        "first:bind_testbed_config",
        "first:bind_project_root",
        "first:create_reporter",
        "second:bind_testbed_config",
        "second:bind_project_root",
        "second:prepare_run",
    ]


def test_direct_run_loop_binds_exact_config_before_plugin_preparation(
    tmp_path: Path,
) -> None:
    events: list[str] = []
    config = object()

    class Plugin(_Plugin):
        def bind_testbed_config(self, topology: Any) -> None:
            events.append("bind_testbed_config")
            assert topology is config

        def bind_project_root(self, project_root: Path | str | None) -> None:
            del project_root
            events.append("bind_project_root")

        def prepare_run(self, case_ids: Any) -> Any:
            del case_ids
            events.append("prepare_run")
            raise _StopBeforeCapture

    plugin = Plugin()
    orchestrator = SimpleNamespace(
        root=tmp_path,
        config=config,
        plugins_dir=tmp_path / "plugins",
        loader=_Loader(plugin),
    )

    with pytest.raises(_StopBeforeCapture):
        run_core_loop(orchestrator, "fake", ["D001"], None)

    assert events == ["bind_testbed_config", "bind_project_root", "prepare_run"]


@pytest.mark.parametrize("entry", ["public", "direct"])
def test_unsupported_strict_plugin_is_rejected_before_config_binding(
    tmp_path: Path,
    entry: str,
) -> None:
    events: list[str] = []

    class Plugin(_StrictPlugin):
        def bind_testbed_config(self, topology: Any) -> None:
            del topology
            events.append("bind_testbed_config")

        def prepare_run(self, case_ids: Any) -> Any:
            del case_ids
            events.append("prepare_run")
            raise AssertionError("strict provider rejection must happen first")

    plugin = Plugin()
    if entry == "public":
        orchestrator = _make_orchestrator(tmp_path, plugin)
        payload = orchestrator.run("fake", ["D001"])
    else:
        orchestrator = SimpleNamespace(
            root=tmp_path,
            config=object(),
            plugins_dir=tmp_path / "plugins",
            loader=_Loader(plugin),
            run_backend=object(),
        )
        payload = run_core_loop(orchestrator, "fake", ["D001"], None)

    assert payload["status"] == "aborted"
    assert payload["run_abort"]["reason_code"] == "capture_capability_unavailable"
    assert payload["run_abort"]["capture_status"] == "not_started"
    assert events == []


def test_public_binding_exception_is_sanitized_before_runner_or_io(
    tmp_path: Path,
) -> None:
    secret_detail = "private config exception text"
    config_canary = "TESTBED_CONFIG_VALUE_CANARY_7931"
    events: list[str] = []

    class Plugin(_Plugin):
        def bind_testbed_config(self, topology: Any) -> None:
            events.append("bind_testbed_config")
            raise RuntimeError(f"{secret_detail}: {topology.name}")

        def create_runner(self) -> Any:
            events.append("create_runner")
            raise AssertionError("runner construction must not follow bind failure")

        def prepare_run(self, case_ids: Any) -> Any:
            del case_ids
            events.append("prepare_run")
            raise AssertionError("preparation must not follow bind failure")

    selected = tmp_path / "private-selected.yaml"
    selected.write_text(
        f"testbed:\n  name: {config_canary}\n  devices: {{}}\n",
        encoding="utf-8",
    )
    orchestrator = _make_orchestrator(tmp_path, Plugin(), config_path=selected)

    payload = orchestrator.run("fake", ["D001"])

    assert payload["status"] == "aborted"
    assert payload["run_abort"]["reason_code"] == "testbed_config_binding_failed"
    assert payload["run_abort"]["capture_status"] == "not_started"
    assert payload["run_abort"]["executed_case_count"] == 0
    assert events == ["bind_testbed_config"]
    assert secret_detail not in json.dumps(payload)
    assert config_canary not in json.dumps(payload)
    abort_text = Path(payload["run_abort_path"]).read_text(encoding="utf-8")
    assert secret_detail not in abort_text
    assert config_canary not in abort_text


def test_direct_binding_exception_stops_before_root_binding_and_preparation(
    tmp_path: Path,
) -> None:
    secret_detail = "private config exception text"
    events: list[str] = []

    class Plugin(_Plugin):
        def bind_testbed_config(self, topology: Any) -> None:
            del topology
            events.append("bind_testbed_config")
            raise RuntimeError(secret_detail)

        def bind_project_root(self, project_root: Path | str | None) -> None:
            del project_root
            events.append("bind_project_root")

        def prepare_run(self, case_ids: Any) -> Any:
            del case_ids
            events.append("prepare_run")
            raise AssertionError("preparation must not follow bind failure")

    plugin = Plugin()
    orchestrator = SimpleNamespace(
        root=tmp_path,
        config=object(),
        plugins_dir=tmp_path / "plugins",
        loader=_Loader(plugin),
    )

    payload = run_core_loop(orchestrator, "fake", ["D001"], None)

    assert payload["status"] == "aborted"
    assert payload["run_abort"]["reason_code"] == "testbed_config_binding_failed"
    assert payload["run_abort"]["capture_status"] == "not_started"
    assert events == ["bind_testbed_config"]
    assert secret_detail not in json.dumps(payload)
