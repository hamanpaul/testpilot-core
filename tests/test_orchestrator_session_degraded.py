"""Tests for orchestrator SDK session foundation loud surfacing (#16).

When the SDK session foundation fails, the orchestrator must warn exactly once
(loud, not silent) and expose a degraded status so the run payload can carry it.
"""

from __future__ import annotations

import logging
from pathlib import Path

from testpilot.core.orchestrator import Orchestrator


class _FailingSessionManager:
    def create_session(self, request):
        raise RuntimeError("boom")


def _orchestrator_with_failing_sessions() -> Orchestrator:
    # 比照 tests/test_orchestrator_retry.py:19 的既有建構方式
    orch = Orchestrator(project_root=Path(__file__).resolve().parents[1])
    orch.session_manager = _FailingSessionManager()
    return orch


def test_session_failure_warns_once_and_sets_degraded(caplog):
    orch = _orchestrator_with_failing_sessions()
    plan = {"session_id": "s1", "model": "m", "reasoning_effort": "high"}
    with caplog.at_level(logging.WARNING):
        h1 = orch._create_case_session(dict(plan))
        h2 = orch._create_case_session(dict(plan))
    assert h1["status"] == "failed" and h2["status"] == "failed"  # 既有 per-case 行為不變
    warnings = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and "builtin-fallback" in r.getMessage()
    ]
    assert len(warnings) == 1  # 一次性 loud warning
    assert orch.agent_session_degraded == {"degraded": True, "reason": "boom"}


def test_no_failure_keeps_degraded_false():
    orch = Orchestrator(project_root=Path(__file__).resolve().parents[1])
    assert orch.agent_session_degraded == {"degraded": False, "reason": ""}


def test_reset_run_state_clears_stale_degraded():
    # degraded 語意應綁單次 run，非實例壽命：run 入口重置，避免同一實例
    # 被 reuse 跑第二次 run 時，前一次的 degraded=True 漏進第二次 payload。
    orch = Orchestrator(project_root=Path(__file__).resolve().parents[1])
    orch.agent_session_degraded = {"degraded": True, "reason": "prev-run"}
    orch._reset_run_state()
    assert orch.agent_session_degraded == {"degraded": False, "reason": ""}
