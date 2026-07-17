"""Tests for run_loop payload carrying agent_session_degraded (#16).

The core run loop must project the orchestrator's run-level
``agent_session_degraded`` status into the report payload so the SDK session
foundation failure is loud (not silent) all the way out to the run result.

These tests drive ``run_loop.run`` with a hermetic stub orchestrator + fake
plugin/reporter (no real run backend / serialwrap) so they stay hardware-free.
The ``_create_case_session`` → ``agent_session_degraded`` wiring itself is
covered by ``tests/test_orchestrator_session_degraded.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from testpilot.core import run_loop
from testpilot.core.prepared_run import PreparedRun
from testpilot.core.usage_ledger import UsageLedger


class _FakeReporter:
    def build_reports(self, run_result: Any) -> dict[str, Any]:
        return {
            "status": "ok",
            "cases_count": run_result.cases_count,
            "fw_ver": run_result.fw_ver,
            "fw_ver_source": run_result.fw_ver_source,
            "version_manifest": dict(run_result.version_manifest),
        }


class _FakePlugin:
    version = "0.1.0"
    name = "fake"

    def __init__(
        self,
        captured_version: Any = None,
        *,
        capture_exception: Exception | None = None,
        events: list[str] | None = None,
    ) -> None:
        self.captured_version = captured_version
        self.capture_exception = capture_exception
        self.capture_calls = 0
        self.events = events

    def prepare_run(self, case_ids: Any) -> PreparedRun:
        return PreparedRun(cases=[], artifacts={})

    def execution_policy(self, case: Any) -> dict[str, Any]:
        return {}

    def capture_dut_firmware_version(self, config: Any, cases: Any) -> Any:
        del config, cases
        self.capture_calls += 1
        if self.events is not None:
            self.events.append("capture_version_manifest")
        if self.capture_exception is not None:
            raise self.capture_exception
        return self.captured_version

    def create_reporter(self) -> _FakeReporter:
        return _FakeReporter()


class _FakeLoader:
    def __init__(self, plugin: _FakePlugin) -> None:
        self._plugin = plugin

    def load(self, name: str) -> _FakePlugin:
        return self._plugin


class _FakeRunBackend:
    def mark_position(self, handle: Any) -> int | None:
        return None


class _FakeRunnerSelector:
    def load_agent_config(self, plugin_name: str, *, plugin: Any) -> dict[str, Any]:
        return {}

    def build_execution_policy(self, agent_config: dict[str, Any]) -> dict[str, Any]:
        return {"mode": "sequential", "max_concurrency": 1}


class _StubOrchestrator:
    """Minimal orchestrator surface exercised by run_loop.run with zero cases."""

    def __init__(
        self,
        plugins_dir: Path,
        degraded: dict[str, Any],
        *,
        plugin: _FakePlugin | None = None,
        events: list[str] | None = None,
    ) -> None:
        self.plugins_dir = plugins_dir
        self.config = {}
        self.loader = _FakeLoader(plugin or _FakePlugin())
        self.run_backend = _FakeRunBackend()
        self.runner_selector = _FakeRunnerSelector()
        self.run_handle = None
        self.agent_session_degraded = degraded
        self.events = events
        self.usage_ledger = UsageLedger()

    def _analyze_run(self, *, run_result: Any, metrics: dict[str, Any], direct_usage: Any) -> Any:
        del run_result, metrics, direct_usage
        if self.events is not None:
            self.events.append("run_analysis")
        return type("Analysis", (), {"to_dict": lambda _self: {"status": "skipped_no_cases"}})()

    def _start_run_capture(self, run_id: str) -> Path | None:
        del run_id
        if self.events is not None:
            self.events.append("start_run_capture")
        return None

    def _stop_run_capture(self) -> None:
        return None

    def _build_execution_engine(self, *, plugin_name: str, plugin: Any, agent_config: dict) -> None:
        return None

    def _export_run_logs(self, **kwargs: Any) -> dict[str, str]:
        return {}


def test_run_payload_carries_agent_session_degraded(tmp_path: Path) -> None:
    orch = _StubOrchestrator(tmp_path, {"degraded": False, "reason": ""})
    payload = run_loop.run(orch, "fake", None, None)
    assert payload["agent_session_degraded"] == {"degraded": False, "reason": ""}
    assert payload["tier2_remediation"] == {
        "agent_recovered_case_ids": [],
        "audit": [],
    }


def test_run_payload_degraded_true_when_sessions_fail(tmp_path: Path) -> None:
    # session foundation 在 run 中失敗後 orchestrator.agent_session_degraded 被標記
    # （見 test_orchestrator_session_degraded）；payload 必須原樣攜出。
    orch = _StubOrchestrator(tmp_path, {"degraded": True, "reason": "boom"})
    payload = run_loop.run(orch, "fake", None, None)
    assert payload["agent_session_degraded"]["degraded"] is True
    assert "boom" in payload["agent_session_degraded"]["reason"]


def test_run_payload_uses_manifest_git_for_naming_and_metadata(tmp_path: Path) -> None:
    plugin = _FakePlugin({"git": "deadbeef", "image": "BGW720"})
    orch = _StubOrchestrator(
        tmp_path,
        {"degraded": False, "reason": ""},
        plugin=plugin,
    )

    payload = run_loop.run(orch, "fake", None, None)

    assert plugin.capture_calls == 1
    assert payload["fw_ver"] == "deadbeef"
    assert payload["fw_ver_source"] == "dut_git_revision"
    assert payload["version_manifest"] == {"git": "deadbeef", "image": "BGW720"}


def test_run_starts_capture_before_version_manifest_probe(tmp_path: Path) -> None:
    events: list[str] = []
    plugin = _FakePlugin({"git": "deadbeef"}, events=events)
    orch = _StubOrchestrator(
        tmp_path,
        {"degraded": False, "reason": ""},
        plugin=plugin,
        events=events,
    )

    run_loop.run(orch, "fake", None, None)

    assert events[:2] == ["start_run_capture", "capture_version_manifest"]


def test_run_analyzes_after_all_cases_and_before_reporter(tmp_path: Path) -> None:
    events: list[str] = []
    plugin = _FakePlugin(events=events)
    reporter = plugin.create_reporter()
    original = reporter.build_reports

    def build_reports(run_result: Any) -> dict[str, Any]:
        events.append("reporter")
        return original(run_result)

    reporter.build_reports = build_reports  # type: ignore[method-assign]
    plugin.create_reporter = lambda: reporter  # type: ignore[method-assign]
    orch = _StubOrchestrator(tmp_path, {"degraded": False, "reason": ""}, plugin=plugin, events=events)

    run_loop.run(orch, "fake", None, None)

    assert events.index("run_analysis") < events.index("reporter")


def test_run_payload_preserves_manifest_when_cli_fw_ver_wins_naming(tmp_path: Path) -> None:
    plugin = _FakePlugin({"git": "deadbeef", "image": "BGW720"})
    orch = _StubOrchestrator(
        tmp_path,
        {"degraded": False, "reason": ""},
        plugin=plugin,
    )

    payload = run_loop.run(orch, "fake", None, "cli-fw-123")

    assert plugin.capture_calls == 1
    assert payload["fw_ver"] == "cli-fw-123"
    assert payload["fw_ver_source"] == "cli"
    assert payload["version_manifest"] == {"git": "deadbeef", "image": "BGW720"}


def test_run_payload_falls_back_when_manifest_has_no_git(tmp_path: Path) -> None:
    plugin = _FakePlugin({"build": "2026.07.08"})
    orch = _StubOrchestrator(
        tmp_path,
        {"degraded": False, "reason": ""},
        plugin=plugin,
    )

    payload = run_loop.run(orch, "fake", None, None)

    assert payload["fw_ver"] == "DUT-FW-VER"
    assert payload["fw_ver_source"] == "fallback_default"
    assert payload["version_manifest"] == {"build": "2026.07.08"}


def test_run_payload_normalizes_legacy_string_version_manifest(tmp_path: Path) -> None:
    plugin = _FakePlugin("legacy-git-sha")
    orch = _StubOrchestrator(
        tmp_path,
        {"degraded": False, "reason": ""},
        plugin=plugin,
    )

    payload = run_loop.run(orch, "fake", None, None)

    assert payload["fw_ver"] == "legacy-git-sha"
    assert payload["fw_ver_source"] == "dut_git_revision"
    assert payload["version_manifest"] == {"git": "legacy-git-sha"}


def test_run_payload_fails_soft_when_manifest_capture_raises_with_cli_override(
    tmp_path: Path,
    caplog: Any,
) -> None:
    plugin = _FakePlugin(
        capture_exception=RuntimeError("capture boom"),
    )
    orch = _StubOrchestrator(
        tmp_path,
        {"degraded": False, "reason": ""},
        plugin=plugin,
    )

    payload = run_loop.run(orch, "fake", None, "cli-fw-123")

    assert plugin.capture_calls == 1
    assert payload["fw_ver"] == "cli-fw-123"
    assert payload["fw_ver_source"] == "cli"
    assert payload["version_manifest"] == {}
    assert "version manifest capture failed" in caplog.text


def test_run_payload_fails_soft_when_manifest_capture_raises_without_cli_override(
    tmp_path: Path,
    caplog: Any,
) -> None:
    plugin = _FakePlugin(
        capture_exception=RuntimeError("capture boom"),
    )
    orch = _StubOrchestrator(
        tmp_path,
        {"degraded": False, "reason": ""},
        plugin=plugin,
    )

    payload = run_loop.run(orch, "fake", None, None)

    assert plugin.capture_calls == 1
    assert payload["fw_ver"] == "DUT-FW-VER"
    assert payload["fw_ver_source"] == "fallback_default"
    assert payload["version_manifest"] == {}
    assert "version manifest capture failed" in caplog.text
