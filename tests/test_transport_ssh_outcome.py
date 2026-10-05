"""SSH exit uncertainty is terminal for the current Engine attempt."""

from __future__ import annotations

import signal
import subprocess
import traceback
from unittest.mock import Mock

import pytest

from testpilot.core.execution_engine import ExecutionEngine
from testpilot.core.hook_policy import HookDispatcher, HookPolicyConfig
from testpilot.transport.ssh import SshCommandOutcomeUnknown, SshTransport


_SECRET_COMMAND = "synthetic-secret-command"
_SECRET_HOST = "synthetic-secret-host"
_SECRET_IDENTITY = "/synthetic-secret/identity"


def _transport() -> SshTransport:
    transport = SshTransport(
        {
            "binary": "synthetic-secret-ssh-binary",
            "host": _SECRET_HOST,
            "user": "synthetic-secret-user",
            "port": 22,
            "identity_file": _SECRET_IDENTITY,
        }
    )
    transport.connect()
    return transport


class _TransportPlugin:
    def __init__(self, transport: SshTransport) -> None:
        self.transport = transport
        self.setups = 0
        self.executions = 0
        self.teardowns = 0

    def setup_env(self, *_args, **_kwargs) -> bool:
        self.setups += 1
        return True

    def verify_env(self, *_args, **_kwargs) -> bool:
        return True

    def execute_step(self, _case, step, **_kwargs):
        self.executions += 1
        result = self.transport.execute(step["command"], timeout=step.get("timeout", 1.0))
        return {
            "success": result["returncode"] == 0,
            "command": step["command"],
            "output": result["stdout"],
        }

    def evaluate(self, *_args, **_kwargs) -> bool:
        return True

    def teardown(self, *_args, **_kwargs) -> None:
        self.teardowns += 1


def _engine_result(transport: SshTransport, retry_hook: Mock):
    hooks = HookDispatcher(HookPolicyConfig(enabled_hooks={"on_retry"}))

    def _record_retry(*_args, **_kwargs):
        retry_hook()
        return None

    hooks.register("on_retry", _record_retry)
    plugin = _TransportPlugin(transport)
    result = ExecutionEngine({}, hooks).execute_with_retry(
        plugin=plugin,
        case={
            "id": "SSH-OUTCOME",
            "steps": [{"id": "run", "command": _SECRET_COMMAND, "timeout": 0.25}],
        },
        runner={},
        execution_policy={"retry": {"max_attempts": 3}},
    )
    return result, plugin


@pytest.mark.parametrize(
    ("returncode", "stdout", "stderr"),
    [
        (0, "  ok output  ", "  "),
        (1, "  known failure  ", "  expected  "),
        (254, "  upper known failure  ", "  expected  "),
    ],
)
def test_completed_ssh_results_keep_existing_four_fields(
    monkeypatch, returncode: int, stdout: str, stderr: str
) -> None:
    run = Mock(
        return_value=subprocess.CompletedProcess(
            args=["ssh"], returncode=returncode, stdout=stdout, stderr=stderr
        )
    )
    monkeypatch.setattr("testpilot.transport.ssh.subprocess.run", run)
    transport = _transport()

    result = transport.execute(_SECRET_COMMAND)

    assert set(result) == {"returncode", "stdout", "stderr", "elapsed"}
    assert result["returncode"] == returncode
    assert result["stdout"] == stdout.strip()
    assert result["stderr"] == stderr.strip()
    assert isinstance(result["elapsed"], float)
    run.assert_called_once()


@pytest.mark.parametrize("captured", [b"partial bytes", "partial text"])
def test_timeout_raises_redacted_unknown_with_partial_output(monkeypatch, captured) -> None:
    timeout_error = subprocess.TimeoutExpired(
        cmd=[_SECRET_IDENTITY, _SECRET_HOST, _SECRET_COMMAND],
        timeout=0.25,
        output=captured,
        stderr=captured,
    )
    run = Mock(side_effect=timeout_error)
    monkeypatch.setattr("testpilot.transport.ssh.subprocess.run", run)
    transport = _transport()

    with pytest.raises(SshCommandOutcomeUnknown) as caught:
        transport.execute(_SECRET_COMMAND, timeout=0.25)

    evidence = caught.value.transport_result
    assert caught.value.result is evidence
    assert evidence["outcome"] == "unknown"
    assert evidence["status"] == "unknown"
    assert evidence["error_code"] == "COMMAND_OUTCOME_UNKNOWN"
    assert evidence["non_replayable"] is True
    assert evidence["retryable"] is False
    assert evidence["ambiguous"] is True
    assert "returncode" not in evidence
    expected = captured.decode() if isinstance(captured, bytes) else captured
    assert evidence["stdout"] == expected
    assert evidence["stderr"] == expected
    assert isinstance(evidence["elapsed"], float)

    formatted = "".join(traceback.format_exception(caught.value))
    for secret in (_SECRET_COMMAND, _SECRET_HOST, _SECRET_IDENTITY, "synthetic-secret-user"):
        assert secret not in str(caught.value)
        assert secret not in repr(caught.value)
        assert secret not in formatted
    run.assert_called_once()


@pytest.mark.parametrize("returncode", [255, -signal.SIGTERM])
def test_ambiguous_ssh_returncodes_raise_unknown_with_local_receipt(
    monkeypatch, returncode: int
) -> None:
    run = Mock(
        return_value=subprocess.CompletedProcess(
            args=["ssh"], returncode=returncode, stdout="partial stdout", stderr="local diagnostic"
        )
    )
    monkeypatch.setattr("testpilot.transport.ssh.subprocess.run", run)
    transport = _transport()

    with pytest.raises(SshCommandOutcomeUnknown) as caught:
        transport.execute(_SECRET_COMMAND)

    evidence = caught.value.transport_result
    assert evidence["outcome"] == "unknown"
    assert evidence["error_code"] == "COMMAND_OUTCOME_UNKNOWN"
    assert evidence["returncode"] == returncode
    assert evidence["stdout"] == "partial stdout"
    assert evidence["stderr"] == "local diagnostic"
    assert isinstance(evidence["elapsed"], float)
    assert evidence["non_replayable"] is True
    assert evidence["retryable"] is False
    assert evidence["ambiguous"] is True
    run.assert_called_once()


@pytest.mark.parametrize(
    "failure",
    [
        "timeout",
        "ssh_exit_255",
        "local_signal",
    ],
)
def test_engine_stops_after_ssh_unknown_without_retry_or_teardown(
    monkeypatch, failure: str
) -> None:
    if failure == "timeout":
        event = subprocess.TimeoutExpired(
            cmd=["ssh", _SECRET_HOST, _SECRET_COMMAND],
            timeout=0.25,
            output=b"partial",
            stderr=b"deadline",
        )
    else:
        returncode = 255 if failure == "ssh_exit_255" else -signal.SIGTERM
        event = subprocess.CompletedProcess(
            args=["ssh"], returncode=returncode, stdout="partial", stderr="diagnostic"
        )
    run = Mock(side_effect=event) if isinstance(event, BaseException) else Mock(return_value=event)
    monkeypatch.setattr("testpilot.transport.ssh.subprocess.run", run)
    retries = Mock()

    result, plugin = _engine_result(_transport(), retries)

    assert result.abort_run is True
    assert result.abort_reason == "command_outcome_unknown"
    assert result.attempts_used == 1
    assert result.attempts[0]["transport_result"]["outcome"] == "unknown"
    assert result.attempts[0]["transport_result"]["error_code"] == "COMMAND_OUTCOME_UNKNOWN"
    assert result.attempts[0]["transport_result"]["non_replayable"] is True
    assert result.attempts[0]["transport_result"]["retryable"] is False
    for secret in (_SECRET_COMMAND, _SECRET_HOST, _SECRET_IDENTITY, "synthetic-secret-user"):
        assert secret not in result.comment
        assert secret not in repr(result.attempts[0])
    assert plugin.setups == 1
    assert plugin.executions == 1
    assert plugin.teardowns == 0
    retries.assert_not_called()
    run.assert_called_once()


def test_known_nonzero_ssh_exit_remains_retryable(monkeypatch) -> None:
    run = Mock(
        side_effect=[
            subprocess.CompletedProcess(args=["ssh"], returncode=1, stdout="", stderr="known"),
            subprocess.CompletedProcess(args=["ssh"], returncode=0, stdout="ok", stderr=""),
        ]
    )
    monkeypatch.setattr("testpilot.transport.ssh.subprocess.run", run)
    retries = Mock()

    result, plugin = _engine_result(_transport(), retries)

    assert result.verdict is True
    assert result.abort_run is False
    assert result.attempts_used == 2
    assert plugin.setups == 2
    assert plugin.executions == 2
    assert plugin.teardowns == 2
    retries.assert_called_once()
    assert run.call_count == 2


def test_missing_ssh_binary_remains_a_local_pre_dispatch_error(monkeypatch) -> None:
    run = Mock(side_effect=FileNotFoundError("synthetic ssh binary missing"))
    monkeypatch.setattr("testpilot.transport.ssh.subprocess.run", run)
    transport = _transport()

    with pytest.raises(FileNotFoundError) as caught:
        transport.execute(_SECRET_COMMAND)

    assert not hasattr(caught.value, "result")
    assert not hasattr(caught.value, "transport_result")
    run.assert_called_once()
