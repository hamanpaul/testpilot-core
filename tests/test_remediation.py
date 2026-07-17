"""Tests for remediation planner module."""

from __future__ import annotations

import json

import pytest
from testpilot.core.advisory import AdvisoryCollector, AdvisoryOutput
from testpilot.core.execution_engine import ExecutionEngine
from testpilot.core.hook_policy import (
    HookContext,
    HookDispatcher,
    HookPolicyConfig,
)
from testpilot.core.remediation import (
    FailureSnapshot,
    RemediationAction,
    RemediationDecision,
    RemediationPlan,
    RemediationPlanner,
    RemediationTraceEntry,
    RuntimeRemediationAction,
    RuntimeRemediationCoordinator,
)


# -- RemediationAction -------------------------------------------------------

class TestRemediationAction:
    def test_creation(self):
        action = RemediationAction(
            action_id="RA-001",
            case_id="D001",
            action_type="config_change",
            description="Fix SSID configuration",
        )
        assert action.action_id == "RA-001"
        assert action.auto_applicable is False

    def test_defaults(self):
        action = RemediationAction(
            action_id="RA-001", case_id="D001",
            action_type="manual_review", description="check",
        )
        assert action.priority == 0
        assert action.prerequisites == []
        assert action.estimated_impact == ""


# -- RemediationPlan ---------------------------------------------------------

class TestRemediationPlan:
    def test_empty_plan(self):
        plan = RemediationPlan(run_id="test-run")
        assert plan.action_count == 0
        assert plan.auto_applicable_actions == []
        assert plan.by_priority() == []

    def test_actions_for_case(self):
        plan = RemediationPlan(run_id="run1", actions=[
            RemediationAction("RA-001", "D001", "config_change", "fix1"),
            RemediationAction("RA-002", "D002", "reboot", "fix2"),
            RemediationAction("RA-003", "D001", "manual_review", "fix3"),
        ])
        d001 = plan.actions_for_case("D001")
        assert len(d001) == 2
        assert all(a.case_id == "D001" for a in d001)

    def test_by_priority(self):
        plan = RemediationPlan(run_id="run1", actions=[
            RemediationAction("RA-001", "D001", "a", "low", priority=1),
            RemediationAction("RA-002", "D002", "b", "high", priority=10),
            RemediationAction("RA-003", "D003", "c", "mid", priority=5),
        ])
        sorted_actions = plan.by_priority()
        assert [a.priority for a in sorted_actions] == [10, 5, 1]

    def test_auto_applicable(self):
        plan = RemediationPlan(run_id="run1", actions=[
            RemediationAction("RA-001", "D001", "a", "fix1", auto_applicable=True),
            RemediationAction("RA-002", "D002", "b", "fix2", auto_applicable=False),
        ])
        assert len(plan.auto_applicable_actions) == 1
        assert plan.auto_applicable_actions[0].action_id == "RA-001"

    def test_summary(self):
        plan = RemediationPlan(
            run_id="run1",
            actions=[
                RemediationAction("RA-001", "D001", "config_change", "fix1", auto_applicable=True),
                RemediationAction("RA-002", "D002", "reboot", "fix2"),
                RemediationAction("RA-003", "D003", "config_change", "fix3"),
            ],
            skipped_cases=["D097"],
            notes=["note1"],
        )
        s = plan.summary()
        assert s["total_actions"] == 3
        assert s["auto_applicable"] == 1
        assert s["by_type"] == {"config_change": 2, "reboot": 1}
        assert s["skipped_cases"] == 1
        assert s["notes_count"] == 1


# -- RemediationPlanner ------------------------------------------------------

class TestRemediationPlanner:
    def _make_advisory(
        self, case_id: str, severity: str = "warning",
        category: str = "configuration", confidence: float = 0.5,
    ) -> AdvisoryOutput:
        return AdvisoryOutput(
            case_id=case_id,
            severity=severity,
            category=category,
            summary=f"issue in {case_id}",
            suggested_action=f"fix {case_id}",
            confidence=confidence,
        )

    def test_plan_from_empty_advisories(self):
        planner = RemediationPlanner(run_id="run1")
        collector = AdvisoryCollector()
        plan = planner.plan_from_advisories(collector)
        assert plan.action_count == 0

    def test_plan_from_single_advisory(self):
        planner = RemediationPlanner(run_id="run1")
        collector = AdvisoryCollector()
        collector.add(self._make_advisory("D001"))
        plan = planner.plan_from_advisories(collector)
        assert plan.action_count == 1
        assert plan.actions[0].case_id == "D001"
        assert plan.actions[0].action_type == "config_change"

    def test_severity_ordering(self):
        planner = RemediationPlanner(run_id="run1")
        collector = AdvisoryCollector()
        collector.add(self._make_advisory("D001", severity="info"))
        collector.add(self._make_advisory("D002", severity="critical"))
        collector.add(self._make_advisory("D003", severity="error"))
        plan = planner.plan_from_advisories(collector)
        # Critical should get highest priority
        sorted_plan = plan.by_priority()
        assert sorted_plan[0].case_id == "D002"

    def test_category_to_action_type_mapping(self):
        planner = RemediationPlanner(run_id="run1")
        collector = AdvisoryCollector()
        for category, expected_type in [
            ("configuration", "config_change"),
            ("environment", "reboot"),
            ("firmware", "firmware_update"),
            ("test_design", "test_skip"),
            ("flaky", "manual_review"),
        ]:
            collector.add(self._make_advisory(f"D-{category}", category=category))
        plan = planner.plan_from_advisories(collector)
        action_types = {a.case_id: a.action_type for a in plan.actions}
        assert action_types["D-configuration"] == "config_change"
        assert action_types["D-environment"] == "reboot"
        assert action_types["D-firmware"] == "firmware_update"
        assert action_types["D-test_design"] == "test_skip"
        assert action_types["D-flaky"] == "manual_review"

    def test_deduplication_per_case_category(self):
        planner = RemediationPlanner(run_id="run1")
        collector = AdvisoryCollector()
        collector.add(self._make_advisory("D001", category="configuration"))
        collector.add(self._make_advisory("D001", category="configuration"))
        plan = planner.plan_from_advisories(collector)
        assert plan.action_count == 1  # deduplicated

    def test_failed_cases_without_advisories(self):
        planner = RemediationPlanner(run_id="run1")
        collector = AdvisoryCollector()
        collector.add(self._make_advisory("D001"))
        plan = planner.plan_from_advisories(
            collector, failed_case_ids=["D001", "D002", "D003"]
        )
        # D001 has advisory, D002/D003 get manual_review
        manual = [a for a in plan.actions if a.action_type == "manual_review"]
        assert len(manual) == 2
        manual_cases = {a.case_id for a in manual}
        assert manual_cases == {"D002", "D003"}

    def test_auto_applicable_high_confidence(self):
        planner = RemediationPlanner(run_id="run1")
        collector = AdvisoryCollector()
        collector.add(self._make_advisory("D001", confidence=0.95))
        plan = planner.plan_from_advisories(collector)
        assert plan.actions[0].auto_applicable is True

    def test_not_auto_applicable_low_confidence(self):
        planner = RemediationPlanner(run_id="run1")
        collector = AdvisoryCollector()
        collector.add(self._make_advisory("D001", confidence=0.5))
        plan = planner.plan_from_advisories(collector)
        assert plan.actions[0].auto_applicable is False

    def test_estimated_impact_levels(self):
        planner = RemediationPlanner(run_id="run1")
        collector = AdvisoryCollector()
        collector.add(self._make_advisory("D001", confidence=0.9, category="environment"))
        collector.add(self._make_advisory("D002", confidence=0.6, category="firmware"))
        collector.add(self._make_advisory("D003", confidence=0.2, category="flaky"))
        plan = planner.plan_from_advisories(collector)
        impacts = {a.case_id: a.estimated_impact for a in plan.actions}
        assert impacts["D001"] == "high"
        assert impacts["D002"] == "medium"
        assert impacts["D003"] == "low"


class TestLiveRemediationDataclasses:
    def test_failure_snapshot_to_dict(self) -> None:
        snapshot = FailureSnapshot(
            case_id="D001",
            attempt_index=1,
            phase="verify_env",
            comment="STA band baseline/connect failed",
            category="environment",
            reason_code="sta_band_not_ready",
            band="5g",
        )
        payload = snapshot.to_dict()
        assert payload["case_id"] == "D001"
        assert payload["band"] == "5g"

    def test_remediation_decision_to_dict(self) -> None:
        decision = RemediationDecision(
            case_id="D001",
            attempt_index=1,
            summary="repair env",
            actions=[
                RuntimeRemediationAction(executor_key="case_env_reverify"),
            ],
            failure=FailureSnapshot(
                case_id="D001",
                attempt_index=1,
                phase="verify_env",
                comment="fail",
            ),
        )
        payload = decision.to_dict()
        assert payload["actions"][0]["executor_key"] == "case_env_reverify"
        assert payload["failure"]["phase"] == "verify_env"

    def test_runtime_artifact_shapes_redact_common_secrets(self) -> None:
        snapshot = FailureSnapshot(
            case_id="D001",
            attempt_index=1,
            phase="verify_env",
            comment="password=snapshot-secret",
            output="token=output-secret",
        )
        action = RuntimeRemediationAction(
            executor_key="repair",
            params={"api_key": "action-secret"},
        )
        trace = RemediationTraceEntry(
            case_id="D001",
            attempt_index=2,
            decision_source="tier1-deterministic",
            summary="repair",
            failure_snapshot=snapshot.to_dict(),
            executed_actions=[action.to_dict()],
            comment="credential=trace-secret",
        )

        serialized = json.dumps(trace.to_dict())

        for secret in (
            "snapshot-secret",
            "output-secret",
            "action-secret",
            "trace-secret",
        ):
            assert secret not in serialized
        assert "[REDACTED]" in serialized


class _LivePlugin:
    def __init__(self) -> None:
        self.executed: list[str] = []

    def build_remediation_decision(self, case, failure_snapshot, topology, *, runner=None, remediation_policy=None):
        del topology, runner, remediation_policy
        return {
            "case_id": case["id"],
            "attempt_index": failure_snapshot.attempt_index,
            "summary": "repair env",
            "actions": [
                {"executor_key": "sta_band_rebaseline", "band": "5g"},
                {"executor_key": "case_env_reverify"},
            ],
        }

    def execute_remediation(self, case, decision, topology):
        del case, topology
        for action in decision.actions:
            self.executed.append(action.executor_key)
        return {
            "success": True,
            "verify_after": True,
            "comment": "remediation applied",
            "actions": [
                {"executor_key": action.executor_key, "success": True}
                for action in decision.actions
            ],
        }


class _UnsafeLivePlugin(_LivePlugin):
    def build_remediation_decision(self, case, failure_snapshot, topology, *, runner=None, remediation_policy=None):
        del case, failure_snapshot, topology, runner, remediation_policy
        return {
            "summary": "unsafe",
            "actions": [
                {"executor_key": "rewrite_yaml", "safety_class": "unsafe"},
            ],
        }


class _OpaqueTier1Plugin(_LivePlugin):
    def execute_remediation(self, case, decision, topology):
        del case, decision, topology
        raise RuntimeError("opaque-tier1-secret-sentinel")


class TestRuntimeRemediationCoordinator:
    def _ctx(self, hook_name: str, *, attempt_index: int = 1) -> HookContext:
        return HookContext(
            hook_name=hook_name,
            case_id="D001",
            plugin_name="wifi_llapi",
            attempt_index=attempt_index,
            runner={"cli_agent": "copilot", "model": "gpt-5.4"},
        )

    def test_on_failure_emits_decision_and_retry_executes_it(self) -> None:
        plugin = _LivePlugin()
        coordinator = RuntimeRemediationCoordinator(
            plugin=plugin,
            topology=object(),
            policy={
                "enabled": True,
                "allowed_actions": ["sta_band_rebaseline", "case_env_reverify"],
                "max_actions_per_attempt": 3,
            },
        )
        case = {
            "id": "D001",
            "_last_failure": {
                "case_id": "D001",
                "attempt_index": 1,
                "phase": "verify_env",
                "comment": "STA band baseline/connect failed",
                "category": "environment",
                "reason_code": "sta_band_not_ready",
                "band": "5g",
            },
        }

        pre_case_data: dict[str, object] = {}
        coordinator.handle_pre_case(self._ctx("pre_case"), pre_case_data)

        failure_data = {
            "case": case,
            "phase": "verify_env",
            "comment": "env_verify gate failed",
        }
        coordinator.handle_on_failure(self._ctx("on_failure"), failure_data)
        assert failure_data["failure_snapshot"]["category"] == "environment"
        assert failure_data["remediation_decision"]["actions"][0]["executor_key"] == "sta_band_rebaseline"

        retry_data = {
            "case": case,
            "previous_attempts": [],
            "attempt_index": 2,
        }
        coordinator.handle_on_retry(self._ctx("on_retry", attempt_index=2), retry_data)
        assert plugin.executed == ["sta_band_rebaseline", "case_env_reverify"]
        assert retry_data["remediation_trace_entry"]["applied"] is True
        assert retry_data["remediation_history"][0]["verify_after"] is True

    def test_tier1_executor_exception_is_opaque_in_trace(self) -> None:
        coordinator = RuntimeRemediationCoordinator(
            plugin=_OpaqueTier1Plugin(),
            topology=object(),
            policy={
                "enabled": True,
                "allowed_actions": [
                    "sta_band_rebaseline",
                    "case_env_reverify",
                ],
            },
        )
        case = {
            "id": "D001",
            "_last_failure": {
                "case_id": "D001",
                "attempt_index": 1,
                "phase": "verify_env",
                "comment": "environment not ready",
                "category": "environment",
                "reason_code": "not_ready",
            },
        }
        coordinator.handle_pre_case(self._ctx("pre_case"), {})
        coordinator.handle_on_failure(
            self._ctx("on_failure"),
            {"case": case, "phase": "verify_env", "comment": "failed"},
        )
        retry_data = {"case": case, "attempt_index": 2}

        coordinator.handle_on_retry(
            self._ctx("on_retry", attempt_index=2),
            retry_data,
        )

        serialized = json.dumps(retry_data)
        assert "opaque-tier1-secret-sentinel" not in serialized
        assert "RuntimeError" in retry_data["remediation_trace_entry"]["comment"]

    def test_non_env_failure_does_not_emit_decision(self) -> None:
        plugin = _LivePlugin()
        coordinator = RuntimeRemediationCoordinator(
            plugin=plugin,
            topology=object(),
            policy={"enabled": True, "allowed_actions": ["case_env_reverify"]},
        )
        case = {
            "id": "D001",
            "_last_failure": {
                "case_id": "D001",
                "attempt_index": 1,
                "phase": "evaluate",
                "comment": "pass_criteria not satisfied",
                "category": "test",
                "reason_code": "pass_criteria_not_satisfied",
            },
        }
        failure_data = {"case": case, "phase": "evaluate", "comment": "pass_criteria not satisfied"}
        coordinator.handle_on_failure(self._ctx("on_failure"), failure_data)
        assert "remediation_decision" not in failure_data

    @pytest.mark.parametrize("phase", ["setup_env", "verify_env"])
    def test_core_env_gate_phase_defaults_to_environment_without_plugin_snapshot(
        self,
        phase: str,
    ) -> None:
        coordinator = RuntimeRemediationCoordinator(
            plugin=_LivePlugin(),
            topology=object(),
            policy={"enabled": True, "allowed_actions": ["case_env_reverify"]},
        )
        failure_data = {
            "case": {"id": "D001"},
            "phase": phase,
            "comment": f"{phase} failed",
        }

        coordinator.handle_on_failure(self._ctx("on_failure"), failure_data)

        assert failure_data["failure_snapshot"]["category"] == "environment"
        assert "remediation_decision" in failure_data

    def test_unsafe_actions_are_rejected(self) -> None:
        plugin = _UnsafeLivePlugin()
        coordinator = RuntimeRemediationCoordinator(
            plugin=plugin,
            topology=object(),
            policy={"enabled": True, "allowed_actions": ["case_env_reverify"]},
        )
        case = {
            "id": "D001",
            "_last_failure": {
                "case_id": "D001",
                "attempt_index": 1,
                "phase": "verify_env",
                "comment": "fail",
                "category": "environment",
                "reason_code": "sta_band_not_ready",
            },
        }
        failure_data = {
            "case": case,
            "phase": "verify_env",
            "comment": "env_verify gate failed",
        }
        coordinator.handle_on_failure(self._ctx("on_failure"), failure_data)
        assert "remediation_decision" not in failure_data

    def test_non_env_failure_resets_tier1_miss_streak(self) -> None:
        requester = _Tier2Requester()
        coordinator = RuntimeRemediationCoordinator(
            plugin=_UnsafeLivePlugin(),
            topology=object(),
            policy={
                "enabled": True,
                "allowed_actions": ["case_env_reverify"],
                "tier2": {
                    "enabled": True,
                    "escalate_after_tier1_failures": 2,
                    "max_total_attempts": 4,
                },
            },
            tier2_requester=requester,
        )
        coordinator.handle_pre_case(self._ctx("pre_case"), {})

        coordinator.handle_on_failure(
            self._ctx("on_failure"),
            {
                "case": {
                    "id": "D001",
                    "_last_failure": {
                        "category": "environment",
                        "phase": "verify_env",
                    },
                },
                "phase": "verify_env",
                "comment": "environment failure one",
            },
        )
        coordinator.handle_on_failure(
            self._ctx("on_failure", attempt_index=2),
            {
                "case": {
                    "id": "D001",
                    "_last_failure": {
                        "category": "test",
                        "phase": "evaluate",
                    },
                },
                "phase": "evaluate",
                "comment": "non-environment failure",
            },
        )
        coordinator.handle_on_failure(
            self._ctx("on_failure", attempt_index=3),
            {
                "case": {
                    "id": "D001",
                    "_last_failure": {
                        "category": "environment",
                        "phase": "verify_env",
                    },
                },
                "phase": "verify_env",
                "comment": "environment failure two",
            },
        )
        retry_data = {"case": {"id": "D001"}, "attempt_index": 4}

        result = coordinator.handle_on_retry(
            self._ctx("on_retry", attempt_index=4),
            retry_data,
        )

        assert result.proceed is True
        assert requester.calls == []
        assert retry_data["tier2_audit"] == []


class _Tier2Requester:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, prompt: str, context: dict) -> str:
        self.calls.append((prompt, context))
        return json.dumps(
            {
                "summary": "repair target environment",
                "rationale": "tier-1 did not restore readiness",
                "actions": [{"executor_key": "target_env_repair"}],
            }
        )


class _InvalidTier2Requester(_Tier2Requester):
    def __call__(self, prompt: str, context: dict) -> str:
        self.calls.append((prompt, context))
        return "not-json"


class _OpaqueTier2Requester(_Tier2Requester):
    def __call__(self, prompt: str, context: dict) -> str:
        self.calls.append((prompt, context))
        raise RuntimeError("opaque-requester-secret-sentinel")


class _Tier2FlowPlugin:
    def __init__(
        self,
        *,
        verify_results: list[bool],
        tier1_results: list[dict],
        mutate_semantics: bool = False,
    ) -> None:
        self.verify_results = list(verify_results)
        self.tier1_results = list(tier1_results)
        self.mutate_semantics = mutate_semantics
        self.builtin_decision_calls = 0
        self.tier2_execute_calls = 0
        self.evaluate_calls = 0

    def setup_env(self, case, topology):
        del case, topology
        return True

    def verify_env(self, case, topology):
        del topology
        result = self.verify_results.pop(0)
        if not result:
            case["_last_failure"] = {
                "case_id": case["id"],
                "attempt_index": case.get("_attempt_index", 0),
                "phase": "verify_env",
                "comment": "target environment not ready",
                "category": "environment",
                "reason_code": "target_not_ready",
            }
        return result

    def execute_step(self, case, step, topology):
        del case, topology
        return {"success": True, "command": step["command"], "output": "ok"}

    def evaluate(self, case, results):
        del case, results
        self.evaluate_calls += 1
        return True

    def teardown(self, case, topology):
        del case, topology

    def build_remediation_decision(
        self,
        case,
        failure_snapshot,
        topology,
        *,
        runner=None,
        remediation_policy=None,
    ):
        del case, topology, runner, remediation_policy
        self.builtin_decision_calls += 1
        return {
            "case_id": failure_snapshot.case_id,
            "attempt_index": failure_snapshot.attempt_index,
            "summary": "tier-1 deterministic repair",
            "actions": [{"executor_key": "tier1_repair"}],
        }

    def request_remediation_decision(self, *args, **kwargs):
        del args, kwargs
        raise AssertionError("legacy agent-first hook must never be called")

    def execute_remediation(self, case, decision, topology):
        del case, decision, topology
        return self.tier1_results.pop(0)

    def build_tier2_remediation_context(
        self,
        case,
        failure_snapshot,
        topology,
        *,
        runner=None,
        remediation_policy=None,
    ):
        del case, failure_snapshot, topology, runner, remediation_policy
        return {
            "diagnosis": "target readiness probe remains down",
            "log_excerpt": ["probe rc=1"],
            "capabilities": [
                {
                    "executor_key": "target_env_repair",
                    "description": "repair target environment state",
                    "execution_boundary": "isolated target transport",
                    "params_schema": {},
                }
            ],
            "verify_env_definition": "target readiness probe returns success",
        }

    def execute_tier2_remediation(self, case, plan, topology):
        del plan, topology
        self.tier2_execute_calls += 1
        if self.mutate_semantics:
            case["steps"][0]["command"] = "rewritten-command"
            case["pass_criteria"].append("rewritten-criteria")
        return {
            "success": True,
            "comment": "tier-2 environment repair applied",
            "actions": [
                {"executor_key": "target_env_repair", "success": True}
            ],
        }


def _tier2_engine(
    plugin: _Tier2FlowPlugin,
    requester: _Tier2Requester,
) -> ExecutionEngine:
    dispatcher = HookDispatcher(
        HookPolicyConfig(
            enabled_hooks={"pre_case", "on_failure", "on_retry", "post_case"},
            fail_open=False,
        )
    )
    coordinator = RuntimeRemediationCoordinator(
        plugin=plugin,
        topology=object(),
        policy={
            "enabled": True,
            "allowed_actions": ["tier1_repair"],
            "tier2": {
                "enabled": True,
                "escalate_after_tier1_failures": 2,
                "max_invocations_per_case": 1,
                "max_actions": 2,
                "max_total_attempts": 4,
            },
        },
        tier2_requester=requester,
    )
    dispatcher.register("pre_case", coordinator.handle_pre_case)
    dispatcher.register("on_failure", coordinator.handle_on_failure)
    dispatcher.register("on_retry", coordinator.handle_on_retry)
    dispatcher.register("post_case", coordinator.handle_post_case)
    return ExecutionEngine(config=object(), hook_dispatcher=dispatcher)


def _tier2_case() -> dict:
    return {
        "id": "D001",
        "steps": [{"id": "step-1", "command": "original-command"}],
        "pass_criteria": ["original-criteria"],
    }


def _tier2_policy() -> dict:
    return {
        "retry": {"max_attempts": 2},
        "failure_policy": "retry_then_fail_and_continue",
    }


def test_tier1_explicit_failures_escalate_once_and_recover() -> None:
    plugin = _Tier2FlowPlugin(
        verify_results=[False, False, True, True],
        tier1_results=[
            {"success": False, "verify_after": False, "comment": "tier-1 failed"},
            {"success": False, "verify_after": False, "comment": "tier-1 failed"},
        ],
    )
    requester = _Tier2Requester()

    result = _tier2_engine(plugin, requester).execute_with_retry(
        plugin=plugin,
        case=_tier2_case(),
        runner={"cli_agent": "copilot", "model": "gpt-5.4"},
        execution_policy=_tier2_policy(),
    )

    assert result.verdict is True
    assert result.max_attempts == 4
    assert plugin.builtin_decision_calls == 2
    assert len(requester.calls) == 1
    assert plugin.tier2_execute_calls == 1
    assert result.agent_recovered is True
    assert result.tier2_audit[0]["verify_gate"]["passed"] is True
    assert [entry["decision_source"] for entry in result.remediation_history] == [
        "tier1-deterministic",
        "tier1-deterministic",
        "tier2-agent",
    ]


def test_tier2_max_total_attempts_is_a_hard_case_budget() -> None:
    plugin = _Tier2FlowPlugin(
        verify_results=[False, False, True, True],
        tier1_results=[
            {"success": False, "verify_after": False},
            {"success": False, "verify_after": False},
        ],
    )
    requester = _Tier2Requester()
    policy = _tier2_policy()
    policy["retry"]["max_attempts"] = 20

    result = _tier2_engine(plugin, requester).execute_with_retry(
        plugin=plugin,
        case=_tier2_case(),
        runner={"cli_agent": "copilot", "model": "gpt-5.4"},
        execution_policy=policy,
    )

    assert result.max_attempts == 4


def test_tier2_rejects_unreachable_total_attempt_budget() -> None:
    with pytest.raises(ValueError, match="max_total_attempts"):
        RuntimeRemediationCoordinator(
            plugin=object(),
            topology=object(),
            policy={
                "enabled": True,
                "tier2": {
                    "enabled": True,
                    "escalate_after_tier1_failures": 2,
                    "max_total_attempts": 3,
                },
            },
            tier2_requester=_Tier2Requester(),
        )


def test_tier2_failed_verify_gate_halts_before_test_execution() -> None:
    plugin = _Tier2FlowPlugin(
        verify_results=[False, False, False],
        tier1_results=[
            {"success": False, "verify_after": False},
            {"success": False, "verify_after": False},
        ],
    )
    requester = _Tier2Requester()

    result = _tier2_engine(plugin, requester).execute_with_retry(
        plugin=plugin,
        case=_tier2_case(),
        runner={"cli_agent": "copilot", "model": "gpt-5.4"},
        execution_policy=_tier2_policy(),
    )

    assert result.verdict is False
    assert result.diagnostic_status == "FailEnv"
    assert result.agent_recovered is True
    assert result.tier2_audit[0]["verify_gate"]["passed"] is False
    assert plugin.evaluate_calls == 0


def test_real_verify_failures_override_optimistic_tier1_results() -> None:
    plugin = _Tier2FlowPlugin(
        verify_results=[False, False, False, True, True],
        tier1_results=[
            {"success": True, "verify_after": True},
            {"success": True, "verify_after": True},
        ],
    )
    requester = _Tier2Requester()

    result = _tier2_engine(plugin, requester).execute_with_retry(
        plugin=plugin,
        case=_tier2_case(),
        runner={"cli_agent": "copilot", "model": "gpt-5.4"},
        execution_policy=_tier2_policy(),
    )

    assert result.verdict is True
    assert result.attempts_used == 4
    assert plugin.builtin_decision_calls == 2
    assert len(requester.calls) == 1
    assert result.agent_recovered is True


def test_tier2_executor_cannot_mutate_case_semantics() -> None:
    case = _tier2_case()
    plugin = _Tier2FlowPlugin(
        verify_results=[False, False],
        tier1_results=[
            {"success": False, "verify_after": False},
            {"success": False, "verify_after": False},
        ],
        mutate_semantics=True,
    )
    requester = _Tier2Requester()

    result = _tier2_engine(plugin, requester).execute_with_retry(
        plugin=plugin,
        case=case,
        runner={"cli_agent": "copilot", "model": "gpt-5.4"},
        execution_policy=_tier2_policy(),
    )

    assert result.verdict is False
    assert result.tier2_audit[0]["status"] == "rejected"
    assert "test semantics" in result.tier2_audit[0]["error"]
    assert case["steps"][0]["command"] == "original-command"
    assert case["pass_criteria"] == ["original-criteria"]


def test_invalid_tier2_plan_fails_closed_with_audit_and_single_invocation() -> None:
    plugin = _Tier2FlowPlugin(
        verify_results=[False, False],
        tier1_results=[
            {"success": False, "verify_after": False},
            {"success": False, "verify_after": False},
        ],
    )
    requester = _InvalidTier2Requester()

    result = _tier2_engine(plugin, requester).execute_with_retry(
        plugin=plugin,
        case=_tier2_case(),
        runner={"cli_agent": "copilot", "model": "gpt-5.4"},
        execution_policy=_tier2_policy(),
    )

    assert result.verdict is False
    assert result.diagnostic_status == "FailEnv"
    assert result.agent_recovered is True
    assert result.tier2_audit[0]["status"] == "rejected"
    assert len(requester.calls) == 1
    assert plugin.tier2_execute_calls == 0
    assert plugin.evaluate_calls == 0


def test_tier2_requester_exception_is_opaque_in_audit() -> None:
    plugin = _Tier2FlowPlugin(
        verify_results=[False, False],
        tier1_results=[
            {"success": False, "verify_after": False},
            {"success": False, "verify_after": False},
        ],
    )
    requester = _OpaqueTier2Requester()

    result = _tier2_engine(plugin, requester).execute_with_retry(
        plugin=plugin,
        case=_tier2_case(),
        runner={"cli_agent": "copilot", "model": "gpt-5.4"},
        execution_policy=_tier2_policy(),
    )

    serialized = json.dumps(
        {
            "tier2_audit": result.tier2_audit,
            "remediation_history": result.remediation_history,
        }
    )
    assert result.tier2_audit[0]["status"] == "failed"
    assert "RuntimeError" in result.tier2_audit[0]["error"]
    assert "opaque-requester-secret-sentinel" not in serialized
