"""run_pipeline keeps outputs index-aligned with commands (empty step output kept)."""

from __future__ import annotations

from typing import Any

from testpilot.core.plugin_base import PluginBase


class _AlignPlugin(PluginBase):
    api_version = "1.0"

    @property
    def name(self) -> str:
        return "align"

    def discover_cases(self, *_a: Any, **_k: Any) -> list[dict[str, Any]]:
        return []

    def setup_env(self, case: Any, topology: Any) -> bool:
        return True

    def verify_env(self, case: Any, topology: Any) -> bool:
        return True

    def execute_step(self, case: Any, step: dict[str, Any], topology: Any) -> dict[str, Any]:
        return {"success": True, "output": step.get("fake_output", "")}

    def evaluate(self, case: Any, results: Any) -> bool:
        return True

    def teardown(self, case: Any, topology: Any) -> None:
        return None


def test_run_pipeline_keeps_empty_step_output_slot():
    plugin = _AlignPlugin()
    case = {
        "id": "c1",
        "steps": [
            {"id": "sta_set_ip", "command": "sta-verb sta_set_ip --band 5g --ip 1.2.3.4", "fake_output": ""},
            {"id": "srv", "command": "iperf3 -s -D -1", "fake_output": "IperfSrv5g=up"},
            {"id": "stats", "command": "printf RxTime5g=0", "fake_output": "RxTime5g=0"},
        ],
    }
    result = plugin.run_pipeline(case, topology=None)
    assert result["commands"] == [s["command"] for s in case["steps"]]
    assert result["outputs"] == ["", "IperfSrv5g=up", "RxTime5g=0"]


def test_run_pipeline_keeps_empty_command_slot_too():
    """A step with no command text still occupies its commands[] slot (Copilot review on #49)."""
    plugin = _AlignPlugin()
    case = {
        "id": "c2",
        "steps": [
            {"id": "bad_step", "fake_output": "x=1"},
            {"id": "ok", "command": "echo ok", "fake_output": "ok=1"},
        ],
    }
    result = plugin.run_pipeline(case, topology=None)
    assert result["commands"] == ["", "echo ok"]
    assert result["outputs"] == ["x=1", "ok=1"]
    assert len(result["commands"]) == len(result["outputs"])


def test_execution_engine_attempt_trace_keeps_slots_aligned(tmp_path):
    """ExecutionEngine.execute_case_once (the agent_trace producer) keeps one slot per
    executed step in both commands[] and outputs[]."""
    from testpilot.core.execution_engine import ExecutionEngine

    plugin = _AlignPlugin()
    case = {
        "id": "c3",
        "steps": [
            {"id": "s1", "command": "sta-verb sta_set_ip --band 5g --ip 1.2.3.4", "fake_output": ""},
            {"id": "s2", "command": "iperf3 -s -D -1", "fake_output": "IperfSrv5g=up"},
            {"id": "s3", "fake_output": "RxTime5g=0"},
        ],
    }
    engine = ExecutionEngine(config=object())
    outcome = engine.execute_case_once(
        plugin,
        case,
        attempt_index=1,
        attempt_timeout_seconds=30.0,
        runner={"provider": "stub", "model": "test"},
    )
    assert outcome["commands"] == [case["steps"][0]["command"], case["steps"][1]["command"], ""]
    assert outcome["outputs"] == ["", "IperfSrv5g=up", "RxTime5g=0"]
