"""Unknown accepted-command outcomes must not trigger writes or case replay."""
import subprocess
from unittest.mock import Mock

import pytest

from testpilot.transport.serialwrap import SerialWrapTransport
from testpilot.core.execution_engine import ExecutionEngine


@pytest.mark.parametrize("error", [TimeoutError("deadline"), OSError("query unavailable"), ValueError("malformed query")])
def test_accepted_poll_timeout_keeps_identity_without_attach(monkeypatch, error):
    transport = SerialWrapTransport({"binary": "/tmp/serialwrap"})
    transport._selector = "COM0"
    monkeypatch.setattr(transport, "_run_json", lambda *a, **k: {"cmd_id": "accepted"})
    monkeypatch.setattr(transport, "_poll_status", Mock(side_effect=error))
    attach = Mock()
    monkeypatch.setattr(transport, "_attach_session", attach)
    result = transport._submit_and_poll("mutate")
    assert result["cmd_id"] == "accepted"
    assert result["outcome"] == "unknown"
    assert result["non_replayable"] is True
    assert result["retryable"] is False
    attach.assert_not_called()


def test_submit_cli_timeout_retains_unknown_outcome(monkeypatch):
    transport = SerialWrapTransport({"binary": "/tmp/serialwrap"})
    monkeypatch.setattr("testpilot.transport.serialwrap.subprocess.run",
                        Mock(side_effect=subprocess.TimeoutExpired("serialwrap", 1)))
    with pytest.raises(RuntimeError) as caught:
        transport._run_json(["cmd", "submit", "--cmd", "mutate"], timeout=1)
    assert caught.value.result["outcome"] == "unknown"
    assert caught.value.result["non_replayable"] is True


@pytest.mark.parametrize("where", ["step", "setup"])
@pytest.mark.parametrize("evidence", [
    {"outcome": "unknown", "non_replayable": True, "retryable": False, "cmd_id": "accepted"},
    {"partial": True, "non_replayable": True, "input_integrity": "uncertain", "cmd_id": "accepted"},
    {"ambiguous": True, "cmd_id": "accepted"},
])
def test_unknown_outcome_stops_retry_and_cleanup(where, evidence):
    class Plugin:
        setups = 0
        teardowns = 0
        def setup_env(self, case, **kw):
            self.setups += 1
            if where == "setup":
                case["_last_failure"] = {
                    "case_id": case["id"],
                    "attempt_index": case["_attempt_index"],
                    "metadata": evidence,
                }
                return False
            return True
        def verify_env(self, *a, **k):
            return True
        def execute_step(self, *a, **k):
            return {"success": False, "output": "pending", **evidence}
        def teardown(self, *a, **k):
            self.teardowns += 1
    plugin = Plugin()
    result = ExecutionEngine({}).execute_with_retry(
        plugin=plugin, case={"id": "D001", "steps": [{"id": "s", "command": "mutate"}]},
        runner={}, execution_policy={"retry": {"max_attempts": 3}})
    assert plugin.setups == 1
    assert plugin.teardowns == 0
    assert result.abort_run is True
    assert result.abort_reason == "command_outcome_unknown"
    assert result.attempts_used == 1


def test_explicitly_rejected_submit_does_not_invent_unknown_outcome(monkeypatch):
    transport = SerialWrapTransport({"binary": "/tmp/serialwrap"})
    from testpilot.transport.serialwrap import SerialWrapCommandError
    error = SerialWrapCommandError("rejected", {"ok": False, "error_code": "AUTOBOOT_QUIET", "non_replayable": False})
    monkeypatch.setattr(transport, "_run_json", Mock(side_effect=error))
    with pytest.raises(SerialWrapCommandError) as caught:
        transport._submit_and_poll("mutate")
    assert caught.value.result["non_replayable"] is False
    assert "outcome" not in caught.value.result


def test_structured_exception_is_retained_in_attempt_and_failure_hook():
    from testpilot.core.hook_policy import HookDispatcher, HookPolicyConfig
    from testpilot.transport.serialwrap import SerialWrapCommandError
    evidence = {"error_code": "AUTOBOOT_QUIET", "retry_after_s": 4,
                "recommended_action": "wait", "non_replayable": False}
    seen = []
    hooks = HookDispatcher(HookPolicyConfig(enabled_hooks={"on_failure"}))
    hooks.register("on_failure", lambda ctx, payload: seen.append(dict(payload)))
    class Plugin:
        def setup_env(self, *a, **kw):
            return True
        verify_env = setup_env
        def execute_step(self, *a, **kw):
            raise SerialWrapCommandError("boot wait", evidence)
        def teardown(self, *a, **kw):
            pass
    result = ExecutionEngine({}, hooks).execute_with_retry(
        plugin=Plugin(), case={"id": "D001", "steps": [{"command": "probe"}]},
        runner={}, execution_policy={"retry": {"max_attempts": 1}})
    assert seen[0]["transport_result"] == evidence
    assert result.attempts[0]["transport_result"] == evidence
    assert result.abort_run is False


def test_ambiguous_not_ready_response_never_attaches_or_resubmits(monkeypatch):
    import json
    transport = SerialWrapTransport({"binary": "/tmp/serialwrap"})
    transport._selector = "COM0"
    response = {"ok": False, "error_code": "SESSION_NOT_READY", "non_replayable": True}
    run = Mock(return_value=subprocess.CompletedProcess([], 0, json.dumps(response), ""))
    monkeypatch.setattr("testpilot.transport.serialwrap.subprocess.run", run)
    attach = Mock()
    monkeypatch.setattr(transport, "_attach_session", attach)
    with pytest.raises(RuntimeError):
        transport._run_json(["cmd", "submit", "--cmd", "mutate"])
    assert run.call_count == 1
    attach.assert_not_called()


@pytest.mark.parametrize("response", [{"ok": True}, None])
def test_missing_submit_receipt_is_unknown(monkeypatch, response):
    transport = SerialWrapTransport({"binary": "/tmp/serialwrap"})
    if response is None:
        monkeypatch.setattr(transport, "_run_json", Mock(side_effect=RuntimeError("empty stdout")))
    else:
        monkeypatch.setattr(transport, "_run_json", lambda *a, **k: response)
    with pytest.raises(RuntimeError) as caught:
        transport._submit_and_poll("mutate")
    assert caught.value.result["outcome"] == "unknown"
    assert caught.value.result["non_replayable"] is True
