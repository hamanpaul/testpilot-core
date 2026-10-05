"""Runtime behavior for detached Core hook payload projection."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

import pytest

from testpilot.core import run_loop
from testpilot.core.case_planning import CasePlanningResult
from testpilot.core.execution_engine import ExecutionEngine
from testpilot.core.hook_policy import HookContext, HookDispatcher, HookPolicyConfig, HookResult
from testpilot.core.plugin_base import PluginBase
from testpilot.core.prepared_run import PreparedRun
from testpilot.core.usage_ledger import UsageLedger


_CANARY = "private-hook-canary-7f14"
_RUNNER = {"provider": "stub", "model": "test", "private": _CANARY}
_ALL_HOOKS = {
    "pre_case",
    "post_case",
    "pre_step",
    "post_step",
    "on_failure",
    "on_retry",
}
_INTERNAL_HOOK_RESULT = "__testpilot_hook_result__"
_STRICT_ALLOWLIST_FIELDS = frozenset(
    {
        "execution_policy",
        "max_attempts",
        "step",
        "result",
        "verdict",
        "attempts_used",
        "comment",
        "diagnostic_status",
        "remediation_history",
        "failure_snapshot",
        "tier2_audit",
        "agent_recovered",
        "transport_result",
        "abort_run",
        "abort_reason",
        "case",
        "phase",
        "remediation_decision",
        "remediation_trace_entry",
        "previous_attempts",
        "attempt_index",
        _INTERNAL_HOOK_RESULT,
    }
)


def _redact(value: Any) -> Any:
    if type(value) is str:
        return value.replace(_CANARY, "[private]")
    if isinstance(value, Mapping):
        return {
            (str(key).replace(_CANARY, "[private]") if type(key) is str else key): _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact(item) for item in value)
    return deepcopy(value)


class _ProjectionPlugin(PluginBase):
    api_version = "1.7"

    def __init__(
        self,
        *,
        fail_first_step: bool = False,
        evaluate_success: bool = True,
        projector_mode: str = "redact",
        raise_execute_exception: bool = False,
        events: list[tuple[str, str]] | None = None,
    ) -> None:
        self.fail_first_step = fail_first_step
        self.evaluate_success = evaluate_success
        self.projector_mode = projector_mode
        self.raise_execute_exception = raise_execute_exception
        self.events = events if events is not None else []
        self.projected_envelopes: list[tuple[str, dict[str, Any]]] = []
        self.evaluation_captures: list[dict[str, Any]] = []
        self.step_calls = 0
        self.setup_calls = 0
        self.verify_calls = 0
        self.teardown_calls = 0

    @property
    def name(self) -> str:
        return "projection-test"

    def discover_cases(self) -> list[dict[str, Any]]:
        return []

    def setup_env(self, case: dict[str, Any], topology: Any) -> bool:
        self.events.append(("setup", case["id"]))
        self.setup_calls += 1
        return True

    def verify_env(self, case: dict[str, Any], topology: Any) -> bool:
        self.events.append(("verify", case["id"]))
        self.verify_calls += 1
        return True

    def execute_step(
        self, case: dict[str, Any], step: dict[str, Any], topology: Any
    ) -> dict[str, Any]:
        self.events.append(("step", case["id"]))
        self.step_calls += 1
        if self.raise_execute_exception:
            raise RuntimeError(f"private execution detail {_CANARY}")
        failed = self.fail_first_step and case["_attempt_index"] == 1
        return {
            "success": not failed,
            "command": f"read {_CANARY}",
            "output": f"stdout {_CANARY}",
            "captured": {"private_value": _CANARY, "nested": {"value": _CANARY}},
            "transport_result": {"outcome": "completed", "cmd_id": "safe-step-id"},
        }

    def evaluate(self, case: dict[str, Any], results: dict[str, Any]) -> bool:
        self.events.append(("evaluate", case["id"]))
        step = results["steps"]["probe"]
        self.evaluation_captures.append(deepcopy(step["captured"]))
        assert case["nested"]["keep"] == "source-case-value"
        matches_private_capture = step["captured"]["private_value"] == _CANARY
        if not self.evaluate_success:
            case["_last_failure"] = {
                "case_id": case["id"],
                "attempt_index": case["_attempt_index"],
                "category": "test",
                "phase": "evaluate",
                "comment": f"criterion mismatch {_CANARY}",
                "output": _CANARY,
                "metadata": {"private": _CANARY},
            }
        return matches_private_capture and self.evaluate_success

    def teardown(self, case: dict[str, Any], topology: Any) -> None:
        self.events.append(("teardown", case["id"]))
        self.teardown_calls += 1
        return None

    def project_hook_payload(
        self, hook_name: str, payload: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        self.projected_envelopes.append((hook_name, deepcopy(dict(payload))))
        if self.projector_mode == "raises" or (
            self.projector_mode == "raises-on-failure" and hook_name == "on_failure"
        ):
            raise RuntimeError(f"projection failed with {_CANARY}")
        if self.projector_mode == "wrong-shape":
            return {"data": {"safe": True}}
        if self.projector_mode in {
            "strict-allowlist",
            "strict-allowlist-drops-carrier",
        }:
            data = _redact(payload["data"])
            allowed_fields = set(_STRICT_ALLOWLIST_FIELDS)
            if (
                self.projector_mode == "strict-allowlist-drops-carrier"
                and hook_name == "post_case"
            ):
                allowed_fields.discard(_INTERNAL_HOOK_RESULT)
            return {
                "data": {key: value for key, value in data.items() if key in allowed_fields},
                "context": _redact(payload["context"]),
            }
        return {"data": _redact(payload["data"]), "context": _redact(payload["context"])}


class _LegacyPlugin(_ProjectionPlugin):
    """An API 1.6-style plugin that inherits the base identity projector."""

    api_version = "1.6"


def _case() -> dict[str, Any]:
    return {
        "id": "D171",
        "_plugin": "projection-test",
        "nested": {"keep": "source-case-value", "private": _CANARY},
        "steps": [{"id": "probe", "command": f"read {_CANARY}"}],
        "pass_criteria": [],
    }


def _run(
    plugin: PluginBase,
    dispatcher: HookDispatcher,
    *,
    max_attempts: int = 1,
):
    return ExecutionEngine({}, dispatcher).execute_with_retry(
        plugin=plugin,
        case=_case(),
        runner=_RUNNER,
        execution_policy={
            "retry": {"max_attempts": max_attempts},
            "failure_policy": "retry_then_fail_and_continue",
        },
    )


def test_projected_hook_envelopes_are_detached_and_private_capture_stays_evaluable() -> None:
    dispatcher = HookDispatcher(HookPolicyConfig(enabled_hooks=set(_ALL_HOOKS)))
    seen: dict[str, list[tuple[HookContext, dict[str, Any]]]] = {}

    def observe(ctx: HookContext, data: dict[str, Any]) -> HookResult:
        seen.setdefault(ctx.hook_name, []).append((deepcopy(ctx), deepcopy(data)))
        if ctx.hook_name == "pre_case":
            data["max_attempts"] = 2
        if ctx.hook_name == "post_step":
            data["result"]["captured"]["private_value"] = "observer-write"
            data["result"]["output"] = "observer-write"
            data["result"]["success"] = True
            data["step"]["command"] = "observer-write"
            ctx.runner["provider"] = "observer-write"
            ctx.extra["private"] = "observer-write"
        if ctx.hook_name == "on_failure":
            data["remediation_decision"] = {"source": "synthetic-hook"}
        if ctx.hook_name == "on_retry":
            data["case"]["nested"]["keep"] = "observer-write"
            data["previous_attempts"][0]["outputs"][0] = "observer-write"
            data["remediation_trace_entry"] = {
                "decision_source": "synthetic-hook",
                "applied": False,
            }
        return HookResult()

    for hook_name in sorted(_ALL_HOOKS):
        dispatcher.register(hook_name, observe)

    plugin = _ProjectionPlugin(fail_first_step=True)
    result = _run(plugin, dispatcher, max_attempts=1)

    # The pre_case hook's explicit retry-budget control is honored. It turns the
    # first completed nonzero step into a normal retry, which then evaluates.
    assert result.max_attempts == 2
    assert result.attempts_used == 2
    assert result.verdict is True
    assert plugin.evaluation_captures[-1] == {
        "private_value": _CANARY,
        "nested": {"value": _CANARY},
    }
    assert set(seen) == _ALL_HOOKS
    assert {name for name, _ in plugin.projected_envelopes} >= _ALL_HOOKS

    expected_context_fields = {
        "hook_name",
        "case_id",
        "plugin_name",
        "attempt_index",
        "step_id",
        "runner",
        "extra",
    }
    for hook_name, envelope in plugin.projected_envelopes:
        assert set(envelope) == {"data", "context"}
        assert set(envelope["context"]) == expected_context_fields
        assert envelope["context"]["hook_name"] == hook_name

    for hook_name, calls in seen.items():
        for ctx, data in calls:
            assert ctx.runner == {"provider": "stub", "model": "test", "private": "[private]"}
            assert ctx.extra == {}
            assert _CANARY not in str(data)
            assert _CANARY not in str(asdict(ctx))

    # Mutating projected step output, captures, case, or prior attempts must not
    # rewrite either evaluator input or the result retained by Core.
    assert result.attempts[0]["outputs"] == ["stdout [private]"]
    assert result.attempts[1]["outputs"] == ["stdout [private]"]
    assert result.attempts[0]["commands"] == ["read [private]"]
    assert result.attempts[1]["commands"] == ["read [private]"]
    assert result.remediation_history == [
        {"decision_source": "synthetic-hook", "applied": False}
    ]
    assert result.attempts[0]["remediation_decision"] == {"source": "synthetic-hook"}
    assert _CANARY not in str(asdict(result))


@pytest.mark.parametrize("evaluate_success", [True, False])
def test_private_capture_remains_visible_to_pass_and_fail_criteria(evaluate_success: bool) -> None:
    dispatcher = HookDispatcher(HookPolicyConfig(enabled_hooks={"on_failure", "post_case"}))
    plugin = _ProjectionPlugin(evaluate_success=evaluate_success)

    result = _run(plugin, dispatcher)

    assert result.verdict is evaluate_success
    assert plugin.evaluation_captures == [
        {"private_value": _CANARY, "nested": {"value": _CANARY}}
    ]
    assert _CANARY not in str(asdict(result))
    if not evaluate_success:
        assert result.failure_snapshot["comment"] == "criterion mismatch [private]"
        assert result.failure_snapshot["output"] == "[private]"


@pytest.mark.parametrize("projector_mode", ["raises", "wrong-shape"])
def test_projection_failure_aborts_with_finite_reason_and_no_plugin_execution(
    projector_mode: str,
) -> None:
    dispatcher = HookDispatcher(HookPolicyConfig(enabled_hooks={"pre_case", "post_case"}))
    called: list[str] = []
    dispatcher.register("pre_case", lambda _ctx, _data: (called.append("pre_case"), HookResult())[1])
    dispatcher.register("post_case", lambda _ctx, _data: (called.append("post_case"), HookResult())[1])
    plugin = _ProjectionPlugin(projector_mode=projector_mode)

    result = _run(plugin, dispatcher, max_attempts=3)

    assert result.verdict is False
    assert result.abort_run is True
    assert result.abort_reason == "hook_payload_projection_failed"
    assert result.attempts == []
    assert called == []
    assert plugin.setup_calls == 0
    assert plugin.step_calls == 0
    assert plugin.teardown_calls == 0
    assert _CANARY not in str(asdict(result))


def test_legacy_identity_projector_keeps_supported_retry_controls() -> None:
    dispatcher = HookDispatcher(HookPolicyConfig(enabled_hooks={"pre_case"}))

    def increase_attempts(_ctx: HookContext, data: dict[str, Any]) -> HookResult:
        data["max_attempts"] = 2
        return HookResult()

    dispatcher.register("pre_case", increase_attempts)
    plugin = _LegacyPlugin(evaluate_success=False)
    result = _run(plugin, dispatcher, max_attempts=1)

    assert plugin.project_hook_payload("pre_case", {"data": {"max_attempts": 1}, "context": {}}) == {
        "data": {"max_attempts": 1},
        "context": {},
    }
    assert result.max_attempts == 2
    assert result.attempts_used == 2
    assert plugin.step_calls == 2


class _Uncopyable:
    def __deepcopy__(self, memo: dict[int, Any]) -> Any:
        raise RuntimeError(f"copy failed with {_CANARY}")


def test_deepcopy_failure_is_private_and_fails_closed_before_case_execution() -> None:
    plugin = _ProjectionPlugin()
    dispatcher = HookDispatcher(HookPolicyConfig(enabled_hooks={"pre_case"}))
    engine = ExecutionEngine({}, dispatcher)

    result = engine.execute_with_retry(
        plugin=plugin,
        case=_case(),
        runner={"provider": "stub", "copy_probe": _Uncopyable()},
        execution_policy={"retry": {"max_attempts": 2}},
    )

    assert result.abort_run is True
    assert result.abort_reason == "hook_payload_projection_failed"
    assert result.attempts == []
    assert plugin.setup_calls == 0
    assert plugin.teardown_calls == 0
    assert _CANARY not in str(asdict(result))


def test_plugin_exception_is_projected_before_it_reaches_public_comment() -> None:
    dispatcher = HookDispatcher(HookPolicyConfig(enabled_hooks={"on_failure"}))
    plugin = _ProjectionPlugin(raise_execute_exception=True)

    result = _run(plugin, dispatcher)

    assert result.verdict is False
    assert result.attempts_used == 1
    assert result.abort_run is False
    assert result.comment == "exception: private execution detail [private]"
    assert plugin.teardown_calls == 1
    assert _CANARY not in str(asdict(result))


def test_projector_failure_while_handling_plugin_exception_is_finite_and_stops() -> None:
    dispatcher = HookDispatcher(HookPolicyConfig(enabled_hooks={"on_failure", "post_case"}))
    called: list[str] = []
    dispatcher.register("on_failure", lambda _ctx, _data: (called.append("on_failure"), HookResult())[1])
    dispatcher.register("post_case", lambda _ctx, _data: (called.append("post_case"), HookResult())[1])
    plugin = _ProjectionPlugin(
        projector_mode="raises-on-failure",
        raise_execute_exception=True,
    )

    result = _run(plugin, dispatcher)

    assert result.verdict is False
    assert result.abort_run is True
    assert result.abort_reason == "hook_payload_projection_failed"
    assert result.comment == "hook_payload_projection_failed"
    assert result.attempts_used == 1
    assert result.attempts[0]["comment"] == "hook_payload_projection_failed"
    assert plugin.teardown_calls == 0
    assert called == []
    assert _CANARY not in str(asdict(result))


@pytest.mark.parametrize("evaluate_success", [True, False])
def test_private_hook_halt_advice_is_projected_and_never_logged(
    evaluate_success: bool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    dispatcher = HookDispatcher(HookPolicyConfig(enabled_hooks={"post_case"}))
    dispatcher.register(
        "post_case",
        lambda _ctx, _data: HookResult(
            proceed=False,
            advice=f"halted by private evidence {_CANARY}",
        ),
    )
    plugin = _ProjectionPlugin(evaluate_success=evaluate_success)

    result = _run(plugin, dispatcher)

    assert result.verdict is evaluate_success
    assert plugin.evaluation_captures == [
        {"private_value": _CANARY, "nested": {"value": _CANARY}}
    ]
    assert "hook post_case halted execution" in caplog.text
    assert _CANARY not in caplog.text
    assert _CANARY not in str(asdict(result))


def test_halted_hook_advice_remains_a_projected_execution_control(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    dispatcher = HookDispatcher(HookPolicyConfig(enabled_hooks={"pre_case"}))
    dispatcher.register(
        "pre_case",
        lambda _ctx, _data: HookResult(
            proceed=False,
            advice=f"halted by private evidence {_CANARY}",
        ),
    )
    plugin = _ProjectionPlugin()

    result = _run(plugin, dispatcher)

    assert result.verdict is False
    assert result.comment == "halted by private evidence [private]"
    assert result.attempts == []
    assert plugin.setup_calls == 0
    assert "hook pre_case halted execution" in caplog.text
    assert _CANARY not in caplog.text
    assert _CANARY not in str(asdict(result))


@pytest.mark.parametrize("fail_open", [True, False])
def test_private_handler_exception_is_not_logged_before_engine_projection(
    fail_open: bool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    dispatcher = HookDispatcher(
        HookPolicyConfig(enabled_hooks={"pre_case"}, fail_open=fail_open)
    )

    def fail_with_private_message(_ctx: HookContext, _data: dict[str, Any]) -> HookResult:
        raise RuntimeError(f"handler failed with private evidence {_CANARY}")

    dispatcher.register("pre_case", fail_with_private_message)
    plugin = _ProjectionPlugin()

    result = _run(plugin, dispatcher)

    assert _CANARY not in caplog.text
    assert _CANARY not in str(asdict(result))
    expected_log = (
        "hook pre_case failed (fail_open=True)"
        if fail_open
        else "hook pre_case failed (fail_open=False)"
    )
    assert expected_log in caplog.text
    if fail_open:
        assert result.verdict is True
        assert plugin.evaluation_captures == [
            {"private_value": _CANARY, "nested": {"value": _CANARY}}
        ]
    else:
        assert result.verdict is False
        assert result.comment == "hook error: handler failed with private evidence [private]"
        assert result.attempts == []
        assert plugin.setup_calls == 0


def _accepted_unknown_receipt(cmd_id: str) -> dict[str, Any]:
    return {
        "cmd_id": cmd_id,
        "status": "accepted",
        "outcome": "unknown",
        "non_replayable": True,
        "retryable": False,
    }


class _RunLoopProjectionPlugin(_ProjectionPlugin):
    def __init__(self, events: list[tuple[str, str]]) -> None:
        super().__init__(projector_mode="strict-allowlist", events=events)
        self.events = events
        self.run_result: Any = None
        self.version_capture_calls = 0

    def prepare_run(self, case_ids: list[str] | None) -> PreparedRun:
        del case_ids
        cases = [_case(), _case()]
        cases[0]["id"] = "D171"
        cases[1]["id"] = "D172"
        self.events.append(("prepare_run", "D171,D172"))
        return PreparedRun(cases=cases, artifacts={}, no_io=True)

    def capture_dut_firmware_version(
        self, config: Any, cases: list[dict[str, Any]]
    ) -> dict[str, str]:
        del config, cases
        self.version_capture_calls += 1
        raise AssertionError("no-I/O prepared run must not query firmware version")

    def create_reporter(self) -> Any:
        plugin = self

        class _Reporter:
            def build_reports(self, run_result: Any) -> dict[str, Any]:
                plugin.run_result = run_result
                return {"status": "ok", "cases_count": run_result.cases_count}

        return _Reporter()


def test_post_case_unknown_transport_aborts_before_later_case_io(
    tmp_path: Path,
) -> None:
    events: list[tuple[str, str]] = []
    handler_data: list[dict[str, Any]] = []
    dispatcher = HookDispatcher(HookPolicyConfig(enabled_hooks={"post_case"}))

    def add_unknown_post_case_receipt(
        ctx: HookContext, data: dict[str, Any]
    ) -> HookResult:
        assert ctx.case_id == "D171"
        assert _INTERNAL_HOOK_RESULT not in data
        handler_data.append(deepcopy(data))
        data["transport_result"] = _accepted_unknown_receipt("safe-post-case-id")
        events.append(("post_case_unknown", ctx.case_id))
        return HookResult()

    dispatcher.register("post_case", add_unknown_post_case_receipt)
    plugin = _RunLoopProjectionPlugin(events)

    def select_case_runner(**kwargs: Any) -> tuple[dict[str, str], dict[str, str]]:
        case_id = kwargs["case"]["id"]
        events.append(("select", case_id))
        return {"provider": "stub", "model": "test"}, {"selected": "stub"}

    def plan_case(**kwargs: Any) -> CasePlanningResult:
        case_id = kwargs["case"]["id"]
        events.append(("plan", case_id))
        return CasePlanningResult(status="skipped_no_agent")

    def build_execution_engine(**kwargs: Any) -> None:
        case_id = kwargs["case_id"]
        events.append(("build_engine", case_id))

    runner_selector = SimpleNamespace(
        load_agent_config=lambda *args, **kwargs: {},
        build_execution_policy=lambda _config: {
            "mode": "sequential",
            "max_concurrency": 1,
            "retry": {"max_attempts": 3},
            "failure_policy": "retry_then_fail_and_continue",
        },
        select_case_runner=select_case_runner,
    )

    orchestrator = SimpleNamespace(
        root=tmp_path,
        plugins_dir=tmp_path / "plugins",
        config={},
        loader=SimpleNamespace(load=lambda _name: plugin),
        run_backend=object(),
        run_handle=None,
        runner_selector=runner_selector,
        execution_engine=ExecutionEngine({}, dispatcher),
        usage_ledger=UsageLedger(),
        agent_runtime=None,
        agent_session_degraded={"degraded": False, "reason": ""},
        agent_recovery_support={},
        _build_execution_engine=build_execution_engine,
        _plan_case=plan_case,
        _analyze_run=lambda **kwargs: SimpleNamespace(
            status="complete", to_dict=lambda: {"status": "complete"}
        ),
    )

    payload = run_loop.run(orchestrator, plugin.name, None, None)

    retry = plugin.run_result.cases[0].retry
    assert events == [
        ("prepare_run", "D171,D172"),
        ("select", "D171"),
        ("plan", "D171"),
        ("build_engine", "D171"),
        ("setup", "D171"),
        ("verify", "D171"),
        ("step", "D171"),
        ("evaluate", "D171"),
        ("teardown", "D171"),
        ("post_case_unknown", "D171"),
    ]
    assert retry.verdict is False
    assert retry.comment == "command outcome unknown"
    assert retry.abort_run is True
    assert retry.abort_reason == "command_outcome_unknown"
    assert retry.attempts_used == 1
    assert retry.attempts[0]["abort_run"] is True
    assert retry.attempts[0]["abort_reason"] == "command_outcome_unknown"
    assert retry.attempts[0]["transport_result"]["cmd_id"] == "safe-post-case-id"
    assert retry.attempts[0]["transport_result"]["status"] == "accepted"
    assert retry.attempts[0]["transport_result"]["outcome"] == "unknown"
    assert retry.attempts[0]["transport_result"]["non_replayable"] is True
    assert plugin.teardown_calls == 1  # case 1 cleanup finished before post_case.
    assert plugin.version_capture_calls == 0
    assert handler_data == [
        {
            "verdict": True,
            "attempts_used": 1,
            "comment": "",
            "diagnostic_status": "Pass",
            "remediation_history": [],
            "failure_snapshot": None,
            "tier2_audit": [],
            "agent_recovered": False,
        }
    ]
    post_case_envelopes = [
        payload for name, payload in plugin.projected_envelopes if name == "post_case"
    ]
    assert len(post_case_envelopes) == 2
    assert _INTERNAL_HOOK_RESULT not in post_case_envelopes[0]["data"]
    assert post_case_envelopes[1]["data"][_INTERNAL_HOOK_RESULT] == {
        "proceed": True,
        "advice": "",
    }
    assert post_case_envelopes[1]["data"]["transport_result"]["cmd_id"] == (
        "safe-post-case-id"
    )
    assert _INTERNAL_HOOK_RESULT not in str(asdict(retry))
    assert payload["status"] == "aborted"
    assert payload["run_abort"] == {
        "case_id": "D171",
        "reason": "command_outcome_unknown",
        "executed_case_count": 1,
        "requested_case_count": 2,
        "unexecuted_case_ids": ["D172"],
    }


def test_strict_allowlist_that_drops_engine_hook_result_fails_closed() -> None:
    dispatcher = HookDispatcher(HookPolicyConfig(enabled_hooks={"post_case"}))
    dispatcher.register("post_case", lambda _ctx, _data: HookResult())
    plugin = _ProjectionPlugin(projector_mode="strict-allowlist-drops-carrier")

    result = _run(plugin, dispatcher, max_attempts=3)

    assert result.verdict is False
    assert result.abort_run is True
    assert result.abort_reason == "hook_payload_projection_failed"
    assert result.comment == "hook_payload_projection_failed"
    assert result.attempts_used == 1
    assert plugin.teardown_calls == 1
    assert _INTERNAL_HOOK_RESULT not in str(asdict(result))
