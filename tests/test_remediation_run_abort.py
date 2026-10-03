"""A failed reboot recovery stops the run without inventing later verdicts."""
import json
from pathlib import Path

from testpilot.core import run_loop
from testpilot.core.execution_engine import ExecutionEngine, RetryResult
from testpilot.core.hook_policy import HookDispatcher, HookPolicyConfig, HookResult
from testpilot.core.remediation import RuntimeRemediationCoordinator, RemediationDecision
from testpilot.core.hook_policy import HookContext
from test_run_loop_abort import _Plugin, _ExecutionEngine, _AbortOrchestrator


def test_coordinator_preserves_executor_run_abort():
    class Plugin:
        def execute_remediation(self, *a):
            return {"success": False, "verify_after": False, "actions": [],
                    "abort_run": True, "abort_reason": "dut_reboot_readiness_failed"}
    coordinator = RuntimeRemediationCoordinator(plugin=Plugin(), topology={}, policy={})
    result = coordinator._execute_decision(case={"id": "D001"}, decision=RemediationDecision(case_id="D001", attempt_index=2, summary="recover"))
    assert result["abort_run"] is True
    assert result["abort_reason"] == "dut_reboot_readiness_failed"


def test_coordinator_halts_retry_before_another_environment_attempt():
    class Plugin:
        def execute_remediation(self, *a):
            return {"success": False, "verify_after": False, "actions": [],
                    "abort_run": True, "abort_reason": "dut_reboot_readiness_failed"}
    coordinator = RuntimeRemediationCoordinator(plugin=Plugin(), topology={}, policy={"enabled": True})
    state = coordinator._case_state("D001")
    state["pending_decision"] = RemediationDecision(case_id="D001", attempt_index=2, summary="recover")
    data = {"case": {"id": "D001"}}
    hook = coordinator.handle_on_retry(HookContext(hook_name="on_retry", case_id="D001", plugin_name="fake", attempt_index=2), data)
    assert hook.proceed is False
    assert data["abort_run"] is True
    assert len(data["remediation_history"]) == 1
    assert data["remediation_history"][0]["applied"] is False


def test_retry_abort_retains_first_attempt_and_does_not_execute_second(monkeypatch):
    dispatcher = HookDispatcher(HookPolicyConfig(enabled_hooks={"on_retry"}))
    def abort(ctx, data):
        data.update(abort_run=True, abort_reason="dut_reboot_readiness_failed")
        return HookResult(proceed=False, advice="DUT did not recover")
    dispatcher.register("on_retry", abort)
    engine = ExecutionEngine({}, dispatcher)
    calls = []
    def execute(**kw):
        calls.append(kw["attempt_index"])
        return {"verdict": False, "commands": ["original"], "outputs": ["failed"], "comment": "env failure"}
    monkeypatch.setattr(engine, "execute_case_once", execute)
    result = engine.execute_with_retry(plugin=object(), case={"id": "D001", "steps": []}, runner={},
                                       execution_policy={"retry": {"max_attempts": 3}})
    assert calls == [1]
    assert result.abort_run is True
    assert result.abort_reason == "dut_reboot_readiness_failed"
    assert result.outputs == ["failed"]


def test_run_abort_reports_only_executed_cases_and_retains_evidence(tmp_path: Path):
    plugin = _Plugin([{"id": x, "steps": [], "pass_criteria": [], "source": {"row": i}}
                      for i, x in enumerate(["D001", "D002", "D003"], 1)])
    failed = RetryResult(verdict=False, comment="DUT did not recover", commands=["probe"],
                         outputs=["not ready"], attempts=[{"verdict": False}], attempts_used=1,
                         max_attempts=2, abort_run=True, abort_reason="dut_reboot_readiness_failed")
    engine = _ExecutionEngine([failed])
    orch = _AbortOrchestrator(tmp_path, plugin, engine)
    captured = []
    class Reporter:
        def build_reports(self, result):
            captured.append(result)
            return {"status": "ok"}
    plugin.create_reporter = lambda: Reporter()
    payload = run_loop.run(orch, "fake", None, None)
    assert [r.case_id for r in captured[0].cases] == ["D001"]
    assert payload["status"] == "aborted"
    assert payload["run_abort"]["unexecuted_case_ids"] == ["D002", "D003"]
    artifact = captured[0].artifact_dir / "run-abort.json"
    assert json.loads(artifact.read_text())["reason"] == "dut_reboot_readiness_failed"
    trace = json.loads(Path(captured[0].cases[0].trace_path).read_text())
    assert trace["final"]["abort_run"] is True
