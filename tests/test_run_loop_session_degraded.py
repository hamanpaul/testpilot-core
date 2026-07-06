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


class _FakeReporter:
    def build_reports(self, run_result: Any) -> dict[str, Any]:
        return {"status": "ok", "cases_count": run_result.cases_count}


class _FakePlugin:
    version = "0.1.0"
    name = "fake"

    def prepare_run(self, case_ids: Any) -> PreparedRun:
        return PreparedRun(cases=[], artifacts={})

    def execution_policy(self, case: Any) -> dict[str, Any]:
        return {}

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

    def __init__(self, plugins_dir: Path, degraded: dict[str, Any]) -> None:
        self.plugins_dir = plugins_dir
        self.loader = _FakeLoader(_FakePlugin())
        self.run_backend = _FakeRunBackend()
        self.runner_selector = _FakeRunnerSelector()
        self.run_handle = None
        self.agent_session_degraded = degraded

    def _start_run_capture(self, run_id: str) -> Path | None:
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


def test_run_payload_degraded_true_when_sessions_fail(tmp_path: Path) -> None:
    # session foundation 在 run 中失敗後 orchestrator.agent_session_degraded 被標記
    # （見 test_orchestrator_session_degraded）；payload 必須原樣攜出。
    orch = _StubOrchestrator(tmp_path, {"degraded": True, "reason": "boom"})
    payload = run_loop.run(orch, "fake", None, None)
    assert payload["agent_session_degraded"]["degraded"] is True
    assert "boom" in payload["agent_session_degraded"]["reason"]
