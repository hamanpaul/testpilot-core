"""Staged serial commands must report the script's own exit status.

The fake CLI executes submitted shell lines with real Bash or Dash, then models
the broker's terminal ``done`` response as returncode zero. No serial device or
shared broker is used.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
from pathlib import Path
from typing import Any

import pytest

from testpilot.core.execution_engine import ExecutionEngine
from testpilot.transport.serialwrap import SerialWrapTransport


_FAKE_SERIALWRAP = r'''#!/usr/bin/env python3
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

args = sys.argv[1:]
state_path = Path(os.environ["TP_TEST_STATE"])
log_path = Path(os.environ["TP_TEST_LOG"])
target_root = Path(os.environ["TP_TEST_TARGET_ROOT"])
state = json.loads(state_path.read_text()) if state_path.exists() else {"next": 1, "receipts": {}}

def save_state():
    state_path.write_text(json.dumps(state))

def append_log(entry):
    with log_path.open("a") as stream:
        stream.write(json.dumps(entry) + "\n")

if args[:2] == ["cmd", "submit"]:
    command = args[args.index("--cmd") + 1]
    cmd_id = f"fake-{state['next']}"
    state["next"] += 1
    append_log({"cmd_id": cmd_id, "command": command})

    remote = re.search(r"/tmp/t([A-Za-z0-9_-]{16})", command)
    if remote:
        local = target_root / f"t{remote.group(1)}"
        command = command.replace(remote.group(0), str(local))

    mode = os.environ.get("TP_TEST_MODE", "")
    is_stage = command.startswith("printf ")
    marker_match = re.search(r"TP([A-Za-z0-9_-]{16}):%s", command)
    marker = "TP" + marker_match.group(1) if marker_match else None

    if (mode == "unknown-stage" and is_stage) or (mode == "unknown-final" and not is_stage):
        terminal = {
            "status": "timeout", "stdout": "", "stderr": "", "partial": True,
            "outcome": "unknown", "non_replayable": True, "retryable": False,
        }
    else:
        if mode == "stage-redirection-failure" and is_stage:
            write_command, marker_command = command.rsplit("; printf ", 1)
            command = re.sub(
                r" > [^;]+$", " > /missing-parent/target.sh", write_command, count=1
            ) + "; printf " + marker_command
        completed = subprocess.run(
            [os.environ["TP_TEST_SHELL"], "-c", command],
            cwd=target_root,
            capture_output=True,
            check=False,
        )
        stdout = completed.stdout.decode("utf-8")
        stderr = completed.stderr.decode("utf-8")
        if marker and mode == "missing-stage-marker" and is_stage:
            stdout = ""
        elif marker and mode == "spoof-stage-marker" and is_stage:
            stdout = f"noise {marker}:0\n"
        elif marker and mode == "malformed-stage-marker" and is_stage:
            stdout = f"{marker}:not-a-status\n"
        elif marker and mode == "duplicate-stage-marker" and is_stage:
            stdout += f"{marker}:0\n"
        elif marker and mode == "duplicate-final-marker" and not is_stage:
            stdout += f"{marker}:0\n"

        terminal = {
            # Deliberately report broker completion with rc=0 even when the
            # shell producer exited nonzero, matching serialwrap's status API.
            "status": (
                "failed"
                if (
                    mode in {"broker-failed-stage", "uncertain-integrity-stage"} and is_stage
                ) or (mode == "broker-failed-final" and not is_stage)
                else "done"
            ),
            "stdout": stdout, "stderr": stderr,
            "partial": False,
        }
        if mode == "uncertain-integrity-stage" and is_stage:
            terminal["input_integrity"] = "uncertain"

    state["receipts"][cmd_id] = terminal
    save_state()
    print(json.dumps({"ok": True, "cmd_id": cmd_id}))
elif args[:2] == ["cmd", "status"]:
    cmd_id = args[args.index("--cmd-id") + 1]
    print(json.dumps({"ok": True, "command": state["receipts"][cmd_id]}))
else:
    print(json.dumps({"ok": False, "error_code": "unexpected_fake_cli_call"}))
    sys.exit(1)
'''


@pytest.fixture
def staged_transport(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    target_root = tmp_path / "target"
    target_root.mkdir()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_cli = fake_bin / "serialwrap"
    fake_cli.write_text(_FAKE_SERIALWRAP, encoding="utf-8")
    fake_cli.chmod(0o755)
    log_path = tmp_path / "wire.jsonl"
    state_path = tmp_path / "broker.json"

    shell_names = [name for name in ("bash", "dash") if shutil.which(name)]
    if not shell_names:
        pytest.skip("staged shell controls require Bash or Dash")
    shell = shutil.which("dash") or shutil.which("bash")
    assert shell is not None
    (fake_bin / "sh").symlink_to(shell)

    monkeypatch.setenv("TP_TEST_STATE", str(state_path))
    monkeypatch.setenv("TP_TEST_LOG", str(log_path))
    monkeypatch.setenv("TP_TEST_TARGET_ROOT", str(target_root))
    monkeypatch.setenv("TP_TEST_SHELL", shell)
    monkeypatch.setenv("TP_TEST_MODE", "")
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}")

    transport = SerialWrapTransport({"binary": str(fake_cli), "poll_interval": 0.0})
    transport._connected = True
    transport._selector = "fake-target"
    return transport, target_root, fake_bin, log_path


def _logged_commands(log_path: Path) -> list[str]:
    if not log_path.exists():
        return []
    return [json.loads(line)["command"] for line in log_path.read_text().splitlines()]


def _assert_wire_budget(log_path: Path) -> None:
    commands = _logged_commands(log_path)
    assert commands
    assert all(len(command.encode("utf-8")) <= 120 for command in commands), [
        len(command.encode("utf-8")) for command in commands
    ]


def _long_script(body: str) -> str:
    return "#" + ("x" * 140) + "\n" + body


@pytest.mark.parametrize("shell_name", ["bash", "dash"])
def test_staged_shell_status_beats_done_zero_broker_and_engine_fails_on_exit_7(
    staged_transport, monkeypatch: pytest.MonkeyPatch, shell_name: str
) -> None:
    transport, target_root, _fake_bin, log_path = staged_transport
    shell = shutil.which(shell_name)
    if shell is None:
        pytest.skip(f"staged shell control requires {shell_name}")
    monkeypatch.setenv("TP_TEST_SHELL", shell)
    command = _long_script("printf '%s' PASS\nexit 7")

    class Plugin:
        last_transport_result: dict[str, Any] | None = None

        def setup_env(self, case, *, topology):
            return True

        def verify_env(self, case, *, topology):
            return True

        def execute_step(self, case, step, *, topology):
            self.last_transport_result = transport.execute(step["command"])
            result = self.last_transport_result
            return {
                "success": result["returncode"] == 0,
                "output": result["stdout"],
                "command": step["command"],
            }

        def evaluate(self, case, results):
            return all(step.get("success") for step in results.values())

        def teardown(self, case, *, topology):
            pass

    plugin = Plugin()
    result = ExecutionEngine({}).execute_with_retry(
        plugin,
        {"id": "STAGED-RC", "steps": [{"id": "script", "command": command}]},
        runner={},
        execution_policy={"retry": {"max_attempts": 1}},
    )

    assert result.verdict is False
    assert result.attempts_used == 1
    assert plugin.last_transport_result is not None
    assert plugin.last_transport_result["returncode"] == 7
    assert plugin.last_transport_result["producer_returncode"] == 7
    assert plugin.last_transport_result["broker_returncode"] == 0
    assert plugin.last_transport_result["stdout"] == "PASS"
    assert plugin.last_transport_result["original_broker_result"]["status"] == "done"
    paths = {
        match.group(0)
        for command_line in _logged_commands(log_path)
        for match in re.finditer(r"/tmp/t[A-Za-z0-9_-]{16}", command_line)
    }
    assert len(paths) == 1
    assert not (target_root / Path(next(iter(paths))).name).exists()
    _assert_wire_budget(log_path)


@pytest.mark.parametrize("shell_name", ["bash", "dash"])
def test_staged_stdout_preserves_quotes_backslashes_and_no_final_lf(
    staged_transport, monkeypatch: pytest.MonkeyPatch, shell_name: str
) -> None:
    transport, _target_root, _fake_bin, log_path = staged_transport
    shell = shutil.which(shell_name)
    if shell is None:
        pytest.skip(f"staged shell control requires {shell_name}")
    monkeypatch.setenv("TP_TEST_SHELL", shell)
    value = "quoted: 'single' and \"double\"; trailing backslash " + "\\"
    command = _long_script(
        f"VALUE={shlex.quote(value)}\nprintf '%s\\n%s' first \"$VALUE\""
    )

    result = transport.execute(command)

    assert result["returncode"] == 0
    assert result["stdout"] == f"first\n{value}"
    assert not result["stdout"].endswith("\n")
    assert result["producer_returncode"] == 0
    _assert_wire_budget(log_path)


@pytest.mark.parametrize(
    ("format_string", "expected"),
    [
        ("trailing-lf\\n", "trailing-lf\n"),
        ("trailing-cr\\r", "trailing-cr\r"),
        ("trailing-crlf\\r\\n", "trailing-crlf\r\n"),
    ],
)
def test_staged_stdout_retains_real_line_ending_before_frame(
    staged_transport, format_string: str, expected: str
) -> None:
    transport, _target_root, _fake_bin, log_path = staged_transport
    result = transport.execute(_long_script(f"printf '%b' '{format_string}'"))

    assert result["returncode"] == 0
    assert result["stdout"] == expected
    _assert_wire_budget(log_path)


def test_staged_invocations_use_distinct_paths_and_remove_successful_scripts(
    staged_transport,
) -> None:
    transport, target_root, _fake_bin, log_path = staged_transport

    first = transport.execute(_long_script("printf first"))
    second = transport.execute(_long_script("printf second"))

    assert first["stdout"] == "first"
    assert second["stdout"] == "second"
    paths = {
        match.group(0)
        for command_line in _logged_commands(log_path)
        for match in re.finditer(r"/tmp/t[A-Za-z0-9_-]{16}", command_line)
    }
    assert len(paths) == 2
    assert all(not (target_root / Path(path).name).exists() for path in paths)
    _assert_wire_budget(log_path)


def test_utf8_byte_budget_stages_and_splits_without_breaking_characters(
    staged_transport,
) -> None:
    transport, _target_root, _fake_bin, log_path = staged_transport
    # Fewer than 120 Python characters, but over 120 UTF-8 bytes.
    command = "#" + ("界" * 55) + "\nprintf utf8-ok"
    assert len(command) <= 120
    assert len(command.encode("utf-8")) > 120

    result = transport.execute(command)

    assert result["returncode"] == 0
    assert result["stdout"] == "utf8-ok"
    assert len(_logged_commands(log_path)) > 2
    _assert_wire_budget(log_path)


def test_stage_redirection_failure_returns_producer_rc_and_never_runs_script(
    staged_transport, monkeypatch: pytest.MonkeyPatch
) -> None:
    transport, target_root, _fake_bin, log_path = staged_transport
    monkeypatch.setenv("TP_TEST_MODE", "stage-redirection-failure")
    command = _long_script("printf should-not-run > executed.txt")

    result = transport.execute(command)

    assert result["returncode"] != 0
    assert result["producer_phase"] == "stage_write"
    assert result["producer_returncode"] != 0
    assert result["broker_returncode"] == 0
    assert result["original_broker_result"]["status"] == "done"
    assert len(_logged_commands(log_path)) == 1
    assert not (target_root / "executed.txt").exists()
    _assert_wire_budget(log_path)


def test_cleanup_failure_does_not_mask_script_producer_rc(
    staged_transport, monkeypatch: pytest.MonkeyPatch
) -> None:
    transport, target_root, fake_bin, log_path = staged_transport
    cleanup = fake_bin / "rm"
    cleanup.write_text("#!/bin/sh\nprintf 'injected cleanup failure\\n' >&2\nexit 19\n", encoding="utf-8")
    cleanup.chmod(0o755)
    command = _long_script("printf '%s' script-output\nexit 7")

    result = transport.execute(command)

    assert result["returncode"] == 7
    assert result["producer_returncode"] == 7
    assert result["broker_returncode"] == 0
    assert result["stdout"] == "script-output"
    assert "injected cleanup failure" in result["stderr"]
    assert result["original_broker_result"]["returncode"] == 0
    assert result["cleanup_returncode"] == 19
    paths = {
        match.group(0)
        for command_line in _logged_commands(log_path)
        for match in re.finditer(r"/tmp/t[A-Za-z0-9_-]{16}", command_line)
    }
    assert len(paths) == 1
    assert (target_root / Path(next(iter(paths))).name).exists()
    _assert_wire_budget(log_path)


@pytest.mark.parametrize(
    ("mode", "expected_output"),
    [
        ("missing-stage-marker", ""),
        ("spoof-stage-marker", "noise"),
        ("malformed-stage-marker", "malformed"),
        ("duplicate-stage-marker", "duplicate"),
    ],
)
def test_invalid_stage_marker_fails_closed_with_original_receipt(
    staged_transport, monkeypatch: pytest.MonkeyPatch, mode: str, expected_output: str
) -> None:
    transport, target_root, _fake_bin, log_path = staged_transport
    monkeypatch.setenv("TP_TEST_MODE", mode)
    result = transport.execute(_long_script("printf should-not-run > executed.txt"))

    assert result["returncode"] != 0
    assert result["outcome"] == "unknown"
    assert result["non_replayable"] is True
    assert result["retryable"] is False
    assert result["error_code"] == "PRODUCER_STATUS_UNKNOWN"
    assert result["original_broker_result"]["status"] == "done"
    if expected_output == "duplicate":
        assert result["original_broker_result"]["stdout"].count("TP") == 2
    elif expected_output == "noise":
        assert "noise TP" in result["original_broker_result"]["stdout"]
    assert len(_logged_commands(log_path)) == 1
    assert not (target_root / "executed.txt").exists()
    _assert_wire_budget(log_path)


def test_accepted_unknown_stage_receipt_is_kept_without_followup_execution(
    staged_transport, monkeypatch: pytest.MonkeyPatch
) -> None:
    transport, _target_root, _fake_bin, log_path = staged_transport
    monkeypatch.setenv("TP_TEST_MODE", "unknown-stage")
    result = transport.execute(_long_script("printf should-not-run > executed.txt"))

    assert result["outcome"] == "unknown"
    assert result["non_replayable"] is True
    assert result["partial"] is True
    assert result["status"] == "timeout"
    assert result["stdout"] == ""
    assert len(_logged_commands(log_path)) == 1
    _assert_wire_budget(log_path)


def test_accepted_unknown_final_receipt_has_no_cleanup_or_followup_submit(
    staged_transport, monkeypatch: pytest.MonkeyPatch
) -> None:
    transport, _target_root, _fake_bin, log_path = staged_transport
    monkeypatch.setenv("TP_TEST_MODE", "unknown-final")

    result = transport.execute(_long_script("printf should-not-run"))

    commands = _logged_commands(log_path)
    assert result["returncode"] == 124
    assert result["outcome"] == "unknown"
    assert result["non_replayable"] is True
    assert result["original_broker_result"]["status"] == "timeout"
    assert commands[-1].startswith("(sh /tmp/t")
    assert all(command.startswith("printf ") for command in commands[:-1])
    _assert_wire_budget(log_path)


@pytest.mark.parametrize("mode", ["uncertain-integrity-stage", "broker-failed-stage"])
def test_non_success_stage_receipt_stops_before_another_chunk(
    staged_transport, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    transport, _target_root, _fake_bin, log_path = staged_transport
    monkeypatch.setenv("TP_TEST_MODE", mode)

    result = transport.execute(_long_script("printf should-not-run"))

    assert result["returncode"] != 0
    assert len(_logged_commands(log_path)) == 1
    _assert_wire_budget(log_path)


def test_final_broker_failure_is_not_hidden_by_zero_producer_status(
    staged_transport, monkeypatch: pytest.MonkeyPatch
) -> None:
    transport, _target_root, _fake_bin, log_path = staged_transport
    monkeypatch.setenv("TP_TEST_MODE", "broker-failed-final")

    result = transport.execute(_long_script("printf success"))

    assert result["returncode"] != 0
    assert result["producer_returncode"] == 0
    assert result["cleanup_returncode"] == 0
    assert result["broker_returncode"] != 0
    assert result["original_broker_result"]["status"] == "failed"
    _assert_wire_budget(log_path)


def test_duplicate_final_marker_fails_closed_and_retains_complete_receipt(
    staged_transport, monkeypatch: pytest.MonkeyPatch
) -> None:
    transport, _target_root, _fake_bin, log_path = staged_transport
    monkeypatch.setenv("TP_TEST_MODE", "duplicate-final-marker")
    result = transport.execute(_long_script("printf 'done'"))

    assert result["outcome"] == "unknown"
    assert result["non_replayable"] is True
    assert result["retryable"] is False
    assert result["original_broker_result"]["status"] == "done"
    assert len(_logged_commands(log_path)) > 1
    _assert_wire_budget(log_path)


def test_short_command_keeps_direct_unframed_return_semantics(staged_transport) -> None:
    transport, _target_root, _fake_bin, log_path = staged_transport
    result = transport.execute("printf '%s' short")

    assert _logged_commands(log_path) == ["printf '%s' short"]
    assert result["returncode"] == 0
    assert result["stdout"] == "short"
    assert "producer_returncode" not in result
    assert "original_broker_result" not in result
