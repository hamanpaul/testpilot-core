"""Remediation planner — iterative failure analysis and fix suggestion loop.

Combines advisory outputs with agent role capabilities to build
remediation plans for persistent test failures.  The planner operates
as a post-run aggregation step, not during individual case execution.
"""

from __future__ import annotations

import logging
from copy import deepcopy
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Callable, Mapping, Sequence

from testpilot.core.advisory import AdvisoryCollector, AdvisoryOutput
from testpilot.core.hook_policy import HookContext, HookResult
from testpilot.core.tier2_recovery import (
    Tier2PlanValidationError,
    Tier2RecoveryAudit,
    Tier2RecoveryContext,
    build_tier2_prompt,
    parse_tier2_plan,
    sanitize_tier2_value,
)

log = logging.getLogger(__name__)


def _sanitized_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    sanitized = sanitize_tier2_value(value)
    return dict(sanitized) if isinstance(sanitized, Mapping) else {}


@dataclass(slots=True)
class RemediationAction:
    """A single proposed remediation action."""

    action_id: str
    case_id: str
    action_type: str  # "config_change", "reboot", "firmware_update", "test_skip", "manual_review"
    description: str
    priority: int = 0  # higher = more important
    estimated_impact: str = ""  # "high", "medium", "low"
    prerequisites: list[str] = field(default_factory=list)
    auto_applicable: bool = False


@dataclass(slots=True)
class RemediationPlan:
    """Aggregated remediation plan for a test run."""

    run_id: str
    actions: list[RemediationAction] = field(default_factory=list)
    skipped_cases: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def action_count(self) -> int:
        return len(self.actions)

    @property
    def auto_applicable_actions(self) -> list[RemediationAction]:
        return [a for a in self.actions if a.auto_applicable]

    def actions_for_case(self, case_id: str) -> list[RemediationAction]:
        return [a for a in self.actions if a.case_id == case_id]

    def by_priority(self) -> list[RemediationAction]:
        return sorted(self.actions, key=lambda a: a.priority, reverse=True)

    def summary(self) -> dict[str, Any]:
        by_type: dict[str, int] = {}
        for action in self.actions:
            by_type[action.action_type] = by_type.get(action.action_type, 0) + 1
        return {
            "run_id": self.run_id,
            "total_actions": self.action_count,
            "auto_applicable": len(self.auto_applicable_actions),
            "by_type": by_type,
            "skipped_cases": len(self.skipped_cases),
            "notes_count": len(self.notes),
        }


class RemediationPlanner:
    """Build remediation plans from advisory outputs and failure patterns."""

    def __init__(self, run_id: str = "") -> None:
        self.run_id = run_id
        self._action_counter = 0

    def _next_action_id(self) -> str:
        self._action_counter += 1
        return f"RA-{self._action_counter:03d}"

    def plan_from_advisories(
        self,
        collector: AdvisoryCollector,
        *,
        failed_case_ids: Sequence[str] = (),
    ) -> RemediationPlan:
        """Build a remediation plan from collected advisories.

        Processes advisories by severity (critical first), maps categories
        to action types, and deduplicates per-case actions.
        """
        plan = RemediationPlan(run_id=self.run_id)

        severity_order = {"critical": 4, "error": 3, "warning": 2, "info": 1}
        sorted_advisories = sorted(
            collector.all,
            key=lambda a: severity_order.get(a.severity, 0),
            reverse=True,
        )

        seen_case_categories: set[tuple[str, str]] = set()

        for advisory in sorted_advisories:
            key = (advisory.case_id, advisory.category)
            if key in seen_case_categories:
                continue
            seen_case_categories.add(key)

            action = self._advisory_to_action(advisory)
            if action is not None:
                plan.actions.append(action)

        # Mark failed cases with no advisories for manual review
        advised_cases = {a.case_id for a in collector.all}
        for case_id in failed_case_ids:
            if case_id not in advised_cases:
                plan.actions.append(RemediationAction(
                    action_id=self._next_action_id(),
                    case_id=case_id,
                    action_type="manual_review",
                    description=f"No advisory data for failed case {case_id}",
                    priority=1,
                ))

        return plan

    def _advisory_to_action(self, advisory: AdvisoryOutput) -> RemediationAction | None:
        """Map an advisory output to a remediation action."""
        category_to_type = {
            "configuration": "config_change",
            "environment": "reboot",
            "firmware": "firmware_update",
            "test_design": "test_skip",
            "flaky": "manual_review",
        }
        action_type = category_to_type.get(advisory.category, "manual_review")

        severity_to_priority = {"critical": 10, "error": 7, "warning": 4, "info": 1}
        priority = severity_to_priority.get(advisory.severity, 0)

        impact = "high" if advisory.confidence >= 0.8 else "medium" if advisory.confidence >= 0.5 else "low"

        return RemediationAction(
            action_id=self._next_action_id(),
            case_id=advisory.case_id,
            action_type=action_type,
            description=advisory.suggested_action or advisory.summary,
            priority=priority,
            estimated_impact=impact,
            auto_applicable=action_type == "config_change" and advisory.confidence >= 0.9,
        )


@dataclass(slots=True)
class FailureSnapshot:
    """Normalized failure shape used by in-run remediation."""

    case_id: str
    attempt_index: int
    phase: str
    comment: str
    step_id: str = ""
    category: str = "inconclusive"
    reason_code: str = ""
    device: str = ""
    band: str = ""
    command: str = ""
    output: str = ""
    evidence: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return _sanitized_mapping(asdict(self))


@dataclass(slots=True)
class RuntimeRemediationAction:
    """Single safe remediation action for retry-time execution."""

    executor_key: str
    description: str = ""
    device: str = ""
    band: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    safety_class: str = "safe_env"
    source: str = "builtin-fallback"

    def to_dict(self) -> dict[str, Any]:
        return _sanitized_mapping(asdict(self))


@dataclass(slots=True)
class RemediationDecision:
    """Structured remediation decision emitted by agent or builtin fallback."""

    case_id: str
    attempt_index: int
    summary: str
    actions: list[RuntimeRemediationAction] = field(default_factory=list)
    source: str = "builtin-fallback"
    approved: bool = True
    failure: FailureSnapshot | None = None

    def to_dict(self) -> dict[str, Any]:
        return _sanitized_mapping({
            "case_id": self.case_id,
            "attempt_index": self.attempt_index,
            "summary": self.summary,
            "source": self.source,
            "approved": self.approved,
            "failure": self.failure.to_dict() if self.failure else None,
            "actions": [action.to_dict() for action in self.actions],
        })


@dataclass(slots=True)
class RemediationTraceEntry:
    """Recorded remediation execution between two attempts."""

    case_id: str
    attempt_index: int
    decision_source: str
    summary: str
    failure_snapshot: dict[str, Any] | None
    executed_actions: list[dict[str, Any]] = field(default_factory=list)
    applied: bool = False
    verify_after: bool | None = None
    core_verify_after: bool | None = None
    comment: str = ""

    def to_dict(self) -> dict[str, Any]:
        return _sanitized_mapping(asdict(self))


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(k): v for k, v in value.items()}
    if is_dataclass(value):
        return asdict(value)
    return {}


def _public_case_semantics(case: Mapping[str, Any]) -> dict[str, Any]:
    """Return the plugin-visible case definition without runtime scratch fields."""
    return deepcopy(
        {
            str(key): value
            for key, value in case.items()
            if not str(key).startswith("_")
        }
    )


def _coerce_failure_snapshot(
    raw: Any,
    *,
    case_id: str,
    attempt_index: int,
    phase: str,
    comment: str,
    step_id: str = "",
) -> FailureSnapshot:
    data = _as_mapping(raw)
    metadata = data.get("metadata")
    default_category = (
        "environment" if phase in {"setup_env", "verify_env"} else "inconclusive"
    )
    return FailureSnapshot(
        case_id=str(data.get("case_id", case_id)),
        attempt_index=int(data.get("attempt_index", attempt_index)),
        phase=str(data.get("phase", phase)),
        comment=str(data.get("comment", comment)),
        step_id=str(data.get("step_id", step_id) or ""),
        category=str(data.get("category", default_category) or default_category),
        reason_code=str(data.get("reason_code", "") or ""),
        device=str(data.get("device", "") or ""),
        band=str(data.get("band", "") or ""),
        command=str(data.get("command", "") or ""),
        output=str(data.get("output", "") or ""),
        evidence=[str(item) for item in data.get("evidence", []) if str(item).strip()],
        metadata=dict(metadata) if isinstance(metadata, Mapping) else {},
    )


def _coerce_runtime_action(raw: Any, *, default_source: str) -> RuntimeRemediationAction | None:
    data = _as_mapping(raw)
    executor_key = str(data.get("executor_key", "") or "").strip()
    if not executor_key:
        return None
    params = data.get("params")
    return RuntimeRemediationAction(
        executor_key=executor_key,
        description=str(data.get("description", "") or ""),
        device=str(data.get("device", "") or ""),
        band=str(data.get("band", "") or ""),
        params=dict(params) if isinstance(params, Mapping) else {},
        safety_class=str(data.get("safety_class", "safe_env") or "safe_env"),
        source=str(data.get("source", default_source) or default_source),
    )


def _coerce_decision(
    raw: Any,
    *,
    default_source: str,
    failure: FailureSnapshot,
) -> RemediationDecision | None:
    if raw is None:
        return None
    data = _as_mapping(raw)
    actions_raw = data.get("actions")
    actions: list[RuntimeRemediationAction] = []
    if isinstance(actions_raw, Sequence) and not isinstance(actions_raw, (str, bytes)):
        for item in actions_raw:
            action = _coerce_runtime_action(item, default_source=default_source)
            if action is not None:
                actions.append(action)
    if not actions:
        return None
    return RemediationDecision(
        case_id=str(data.get("case_id", failure.case_id) or failure.case_id),
        attempt_index=int(data.get("attempt_index", failure.attempt_index)),
        summary=str(data.get("summary", failure.comment) or failure.comment),
        actions=actions,
        source=str(data.get("source", default_source) or default_source),
        approved=bool(data.get("approved", True)),
        failure=failure,
    )


class RuntimeRemediationCoordinator:
    """Tier-1-first, retry-only coordinator for bounded environment recovery."""

    def __init__(
        self,
        *,
        plugin: Any,
        topology: Any,
        policy: Mapping[str, Any] | None = None,
        tier2_requester: Callable[[str, dict[str, Any]], str | None] | None = None,
    ) -> None:
        self.plugin = plugin
        self.topology = topology
        self.policy = dict(policy or {})
        self.tier2_requester = tier2_requester
        allowed = self.policy.get("allowed_actions")
        if isinstance(allowed, Sequence) and not isinstance(allowed, (str, bytes)):
            self.allowed_actions = {
                str(item).strip() for item in allowed if str(item).strip()
            }
        else:
            self.allowed_actions = set()
        self.max_actions_per_attempt = max(
            1,
            self._policy_int(self.policy.get("max_actions_per_attempt"), 3),
        )
        self.enabled = bool(self.policy.get("enabled", False))

        raw_tier2 = self.policy.get("tier2")
        self.tier2_policy = dict(raw_tier2) if isinstance(raw_tier2, Mapping) else {}
        self.tier2_enabled = self.enabled and bool(
            self.tier2_policy.get("enabled", False)
        )
        self.tier2_trigger_failures = max(
            1,
            self._policy_int(
                self.tier2_policy.get("escalate_after_tier1_failures"),
                2,
            ),
        )
        self.tier2_max_invocations = max(
            0,
            self._policy_int(
                self.tier2_policy.get("max_invocations_per_case"),
                1,
            ),
        )
        self.tier2_max_actions = max(
            0,
            self._policy_int(self.tier2_policy.get("max_actions"), 3),
        )
        self.tier2_max_total_attempts = max(
            1,
            self._policy_int(
                self.tier2_policy.get("max_total_attempts"),
                self.tier2_trigger_failures + 2,
            ),
        )
        minimum_total_attempts = self.tier2_trigger_failures + 2
        if (
            self.tier2_enabled
            and self.tier2_max_total_attempts < minimum_total_attempts
        ):
            raise ValueError(
                "tier2.max_total_attempts must be at least "
                f"{minimum_total_attempts} when escalation requires "
                f"{self.tier2_trigger_failures} tier-1 failures"
            )
        self._state: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _policy_int(value: Any, default: int) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _new_case_state() -> dict[str, Any]:
        return {
            "pending_decision": None,
            "failure_snapshot": None,
            "remediation_history": [],
            "tier1_failure_streak": 0,
            "last_tier1": None,
            "tier2_invocations": 0,
            "tier2_audit": [],
            "agent_recovered": False,
        }

    def _case_state(self, case_id: str) -> dict[str, Any]:
        return self._state.setdefault(case_id, self._new_case_state())

    @staticmethod
    def _project_state(state: dict[str, Any], data: dict[str, Any]) -> None:
        data["remediation_history"] = [
            dict(item) for item in state["remediation_history"]
        ]
        data["failure_snapshot"] = state.get("failure_snapshot")
        data["tier2_audit"] = [dict(item) for item in state["tier2_audit"]]
        data["agent_recovered"] = bool(state["agent_recovered"])

    def handle_pre_case(self, ctx: HookContext, data: dict[str, Any]) -> HookResult:
        state = self._case_state(ctx.case_id)
        state.clear()
        state.update(self._new_case_state())
        if self.tier2_enabled:
            data["max_attempts"] = self.tier2_max_total_attempts
        self._project_state(state, data)
        return HookResult()

    def _consume_last_tier1(
        self,
        state: dict[str, Any],
        *,
        attempt_index: int,
        env_gate_passed: bool,
    ) -> None:
        last = state.get("last_tier1")
        if not isinstance(last, Mapping):
            return
        if int(last.get("attempt_index", -1)) != attempt_index:
            return
        history_index = self._policy_int(last.get("history_index"), -1)
        if 0 <= history_index < len(state["remediation_history"]):
            state["remediation_history"][history_index][
                "core_verify_after"
            ] = env_gate_passed
        if env_gate_passed:
            state["tier1_failure_streak"] = 0
        elif not bool(last.get("counted", False)):
            self._record_tier1_failure(state, reason="core verify_env failed")
        state["last_tier1"] = None

    def _record_tier1_failure(
        self,
        state: dict[str, Any],
        *,
        reason: str,
    ) -> None:
        state["tier1_failure_streak"] += 1
        log.info(
            "tier-1 deterministic failure %d/%d: %s",
            state["tier1_failure_streak"],
            self.tier2_trigger_failures,
            reason,
        )

    def handle_on_failure(self, ctx: HookContext, data: dict[str, Any]) -> HookResult:
        if not self.enabled:
            return HookResult()

        case = _as_mapping(data.get("case"))
        snapshot = _coerce_failure_snapshot(
            case.get("_last_failure"),
            case_id=ctx.case_id,
            attempt_index=ctx.attempt_index,
            phase=str(data.get("phase", "failure")),
            comment=str(data.get("comment", "") or ""),
            step_id=ctx.step_id or "",
        )
        state = self._case_state(ctx.case_id)
        state["failure_snapshot"] = snapshot.to_dict()
        data["failure_snapshot"] = snapshot.to_dict()
        eligible = snapshot.category in {"environment", "session"}

        self._consume_last_tier1(
            state,
            attempt_index=ctx.attempt_index,
            env_gate_passed=not eligible,
        )
        if not eligible:
            state["pending_decision"] = None
            self._project_state(state, data)
            return HookResult(advice=snapshot.comment)

        log.info(
            "env-recovery eligible case=%s category=%s reason=%s",
            ctx.case_id,
            snapshot.category,
            sanitize_tier2_value(snapshot.reason_code),
        )
        if (
            self.tier2_enabled
            and state["tier1_failure_streak"] >= self.tier2_trigger_failures
        ):
            state["pending_decision"] = None
            self._project_state(state, data)
            return HookResult(advice="tier-2 escalation ready")

        decision = self._request_tier1_decision(
            case=case,
            snapshot=snapshot,
            runner=ctx.runner,
        )
        if decision is None or not decision.approved:
            state["pending_decision"] = None
            if self.tier2_enabled:
                miss = RemediationTraceEntry(
                    case_id=ctx.case_id,
                    attempt_index=ctx.attempt_index,
                    decision_source="tier1-deterministic",
                    summary="no valid deterministic tier-1 decision",
                    failure_snapshot=snapshot.to_dict(),
                    applied=False,
                    comment="tier-1 decision unavailable or rejected",
                )
                state["remediation_history"].append(miss.to_dict())
                self._record_tier1_failure(
                    state,
                    reason="no valid deterministic decision",
                )
            self._project_state(state, data)
            return HookResult(advice=snapshot.comment)

        state["pending_decision"] = decision
        data["remediation_decision"] = decision.to_dict()
        self._project_state(state, data)
        log.info(
            "tier-1 decision case=%s actions=%s",
            ctx.case_id,
            [action.executor_key for action in decision.actions],
        )
        return HookResult(advice=decision.summary or snapshot.comment)

    def handle_on_retry(self, ctx: HookContext, data: dict[str, Any]) -> HookResult:
        if not self.enabled:
            return HookResult()

        state = self._case_state(ctx.case_id)
        case = _as_mapping(data.get("case"))
        pending = state.get("pending_decision")
        decision = pending if isinstance(pending, RemediationDecision) else None
        if decision is not None:
            execution = self._execute_decision(case=case, decision=decision)
            trace_entry = RemediationTraceEntry(
                case_id=ctx.case_id,
                attempt_index=ctx.attempt_index,
                decision_source="tier1-deterministic",
                summary=decision.summary,
                failure_snapshot=(
                    decision.failure.to_dict() if decision.failure else None
                ),
                executed_actions=[
                    dict(item) for item in execution.get("actions", [])
                ],
                applied=bool(execution.get("success", False)),
                verify_after=execution.get("verify_after"),
                comment=str(execution.get("comment", "") or ""),
            )
            state["remediation_history"].append(trace_entry.to_dict())
            history_index = len(state["remediation_history"]) - 1
            explicit_failure = (
                not bool(execution.get("success", False))
                or execution.get("verify_after") is False
            )
            if explicit_failure:
                self._record_tier1_failure(
                    state,
                    reason="tier-1 executor reported failure",
                )
            state["last_tier1"] = {
                "attempt_index": ctx.attempt_index,
                "history_index": history_index,
                "counted": explicit_failure,
            }
            state["pending_decision"] = None
            data["remediation_trace_entry"] = trace_entry.to_dict()

        if (
            self.tier2_enabled
            and state["tier1_failure_streak"] >= self.tier2_trigger_failures
        ):
            if state["tier2_invocations"] >= self.tier2_max_invocations:
                snapshot = self._tier2_failure_snapshot(
                    ctx,
                    "tier-2 invocation budget exhausted",
                    agent_intervened=bool(state["agent_recovered"]),
                )
                state["failure_snapshot"] = snapshot.to_dict()
                self._project_state(state, data)
                return HookResult(
                    proceed=False,
                    advice=snapshot.comment,
                )
            return self._run_tier2(ctx=ctx, data=data, case=case, state=state)

        self._project_state(state, data)
        return HookResult(
            advice=(
                str(data["remediation_trace_entry"].get("comment", ""))
                if isinstance(data.get("remediation_trace_entry"), Mapping)
                else ""
            )
        )

    def handle_post_case(self, ctx: HookContext, data: dict[str, Any]) -> HookResult:
        state = self._case_state(ctx.case_id)
        if bool(data.get("verdict", False)):
            self._consume_last_tier1(
                state,
                attempt_index=ctx.attempt_index,
                env_gate_passed=True,
            )
        self._project_state(state, data)
        return HookResult()

    def _request_tier1_decision(
        self,
        *,
        case: Mapping[str, Any],
        snapshot: FailureSnapshot,
        runner: Mapping[str, Any],
    ) -> RemediationDecision | None:
        builtin = getattr(self.plugin, "build_remediation_decision", None)
        if not callable(builtin):
            return None
        plugin_case = deepcopy(dict(case))
        semantics_before = _public_case_semantics(plugin_case)
        try:
            raw_decision = builtin(
                plugin_case,
                snapshot,
                self.topology,
                runner=dict(runner),
                remediation_policy=dict(self.policy),
            )
        except Exception:
            log.warning(
                "tier-1 deterministic decision failed for %s",
                snapshot.case_id,
            )
            return None
        if _public_case_semantics(plugin_case) != semantics_before:
            log.warning(
                "reject tier-1 decision that mutated case semantics: %s",
                snapshot.case_id,
            )
            return None
        decision = _coerce_decision(
            raw_decision,
            default_source="tier1-deterministic",
            failure=snapshot,
        )
        validated = self._validate_decision(decision)
        if validated is not None:
            validated.source = "tier1-deterministic"
            for action in validated.actions:
                action.source = "tier1-deterministic"
        return validated

    def _validate_decision(
        self,
        decision: RemediationDecision | None,
    ) -> RemediationDecision | None:
        if decision is None or not decision.actions:
            return None

        approved_actions: list[RuntimeRemediationAction] = []
        for action in decision.actions:
            if action.safety_class != "safe_env":
                log.warning("reject unsafe remediation action: %s", action.executor_key)
                continue
            if self.allowed_actions and action.executor_key not in self.allowed_actions:
                log.warning(
                    "reject remediation action outside whitelist: %s",
                    action.executor_key,
                )
                continue
            approved_actions.append(action)
            if len(approved_actions) >= self.max_actions_per_attempt:
                break
        if not approved_actions:
            return None

        decision.actions = approved_actions
        return decision

    def _execute_decision(
        self,
        *,
        case: Mapping[str, Any],
        decision: RemediationDecision,
    ) -> dict[str, Any]:
        execute = getattr(self.plugin, "execute_remediation", None)
        if not callable(execute):
            return {
                "success": False,
                "verify_after": None,
                "comment": "plugin does not support live remediation execution",
                "actions": [],
            }
        plugin_case = deepcopy(dict(case))
        semantics_before = _public_case_semantics(plugin_case)
        try:
            result = execute(
                plugin_case,
                deepcopy(decision),
                self.topology,
            )
        except Exception as exc:
            log.warning(
                "remediation execution failed for %s error_type=%s",
                decision.case_id,
                type(exc).__name__,
            )
            return {
                "success": False,
                "verify_after": None,
                "comment": str(sanitize_tier2_value(str(exc))),
                "actions": [],
            }
        if _public_case_semantics(plugin_case) != semantics_before:
            return {
                "success": False,
                "verify_after": False,
                "comment": "tier-1 executor attempted to mutate test semantics",
                "actions": [],
            }
        result_map = _as_mapping(result)
        raw_verify_after = result_map.get("verify_after")
        verify_after = (
            raw_verify_after if isinstance(raw_verify_after, bool) else None
        )
        return {
            "success": bool(result_map.get("success", False)),
            "verify_after": verify_after,
            "comment": str(result_map.get("comment", "") or ""),
            "actions": [
                dict(item)
                for item in result_map.get("actions", [])
                if isinstance(item, Mapping)
            ],
        }

    def _run_tier2(
        self,
        *,
        ctx: HookContext,
        data: dict[str, Any],
        case: Mapping[str, Any],
        state: dict[str, Any],
    ) -> HookResult:
        state["tier2_invocations"] += 1
        raw_snapshot = state.get("failure_snapshot")
        snapshot = _coerce_failure_snapshot(
            raw_snapshot,
            case_id=ctx.case_id,
            attempt_index=ctx.attempt_index,
            phase="tier2_env_recovery",
            comment="tier-2 escalation",
        )
        audit = Tier2RecoveryAudit(
            case_id=ctx.case_id,
            attempt_index=ctx.attempt_index,
            tier1_failures=state["tier1_failure_streak"],
            trigger_threshold=self.tier2_trigger_failures,
            context={},
            prompt="",
        )
        log.info(
            "tier-2 escalation case=%s invocation=%d/%d",
            ctx.case_id,
            state["tier2_invocations"],
            self.tier2_max_invocations,
        )

        build_context = getattr(
            self.plugin,
            "build_tier2_remediation_context",
            None,
        )
        if not callable(build_context):
            return self._fail_tier2(
                ctx=ctx,
                data=data,
                state=state,
                audit=audit,
                error="plugin does not support tier-2 remediation context",
            )
        context_case = deepcopy(dict(case))
        context_semantics = _public_case_semantics(context_case)
        try:
            raw_context = build_context(
                context_case,
                snapshot,
                self.topology,
                runner=dict(ctx.runner),
                remediation_policy=dict(self.policy),
            )
            if _public_case_semantics(context_case) != context_semantics:
                raise ValueError(
                    "tier-2 context hook attempted to mutate test semantics"
                )
            context = Tier2RecoveryContext.from_mapping(
                _as_mapping(raw_context)
            )
            prompt = build_tier2_prompt(
                context=context,
                failure=snapshot.to_dict(),
                tier1_failures=state["tier1_failure_streak"],
            )
        except Exception as exc:
            return self._fail_tier2(
                ctx=ctx,
                data=data,
                state=state,
                audit=audit,
                error=str(exc),
                status="rejected",
            )
        audit.context = context.to_dict()
        audit.prompt = prompt

        if self.tier2_requester is None:
            return self._fail_tier2(
                ctx=ctx,
                data=data,
                state=state,
                audit=audit,
                error="tier-2 requester is unavailable",
            )
        state["agent_recovered"] = True
        try:
            raw_response = self.tier2_requester(prompt, context.to_dict())
            if not isinstance(raw_response, str) or not raw_response.strip():
                raise ValueError("tier-2 requester returned no plan")
            audit.raw_response = raw_response
            plan = parse_tier2_plan(
                raw_response,
                capability_schemas=context.capability_schemas,
                max_actions=self.tier2_max_actions,
            )
        except Exception as exc:
            log.warning(
                "tier-2 request/plan failed case=%s error_type=%s",
                ctx.case_id,
                type(exc).__name__,
            )
            return self._fail_tier2(
                ctx=ctx,
                data=data,
                state=state,
                audit=audit,
                error=str(exc),
                status=(
                    "rejected"
                    if isinstance(exc, Tier2PlanValidationError)
                    else "failed"
                ),
            )
        audit.plan = plan

        execute = getattr(self.plugin, "execute_tier2_remediation", None)
        if not callable(execute):
            return self._fail_tier2(
                ctx=ctx,
                data=data,
                state=state,
                audit=audit,
                error="plugin does not support tier-2 remediation execution",
            )
        execution_case = deepcopy(dict(case))
        semantics_before = _public_case_semantics(execution_case)
        try:
            raw_execution = execute(
                execution_case,
                deepcopy(plan),
                self.topology,
            )
            execution = _as_mapping(raw_execution)
        except Exception as exc:
            return self._fail_tier2(
                ctx=ctx,
                data=data,
                state=state,
                audit=audit,
                error=str(exc),
            )
        audit.execution = execution
        if _public_case_semantics(execution_case) != semantics_before:
            return self._fail_tier2(
                ctx=ctx,
                data=data,
                state=state,
                audit=audit,
                error="tier-2 executor attempted to mutate test semantics",
                status="rejected",
            )

        verify_case = deepcopy(dict(case))
        verify_case["_attempt_index"] = ctx.attempt_index
        verify_case["_agent_runner"] = dict(ctx.runner)
        verify_semantics = _public_case_semantics(verify_case)
        verify_error = ""
        try:
            gate_passed = bool(
                self.plugin.verify_env(verify_case, topology=self.topology)
            )
            if _public_case_semantics(verify_case) != verify_semantics:
                gate_passed = False
                verify_error = (
                    "tier-2 verify_env attempted to mutate test semantics"
                )
        except Exception as exc:
            gate_passed = False
            verify_error = str(exc)
        safe_verify_error = str(sanitize_tier2_value(verify_error))
        audit.verify_gate = {
            "passed": gate_passed,
            "definition": context.verify_env_definition,
            "error": safe_verify_error,
        }
        audit.status = "verified" if gate_passed else "failed"
        if verify_error:
            audit.error = verify_error
        state["tier2_audit"].append(audit.to_dict())

        raw_actions = execution.get("actions", [])
        safe_actions = sanitize_tier2_value(raw_actions)
        executed_actions = (
            [dict(item) for item in safe_actions if isinstance(item, Mapping)]
            if isinstance(safe_actions, list)
            else []
        )
        safe_execution_comment = str(
            sanitize_tier2_value(str(execution.get("comment", "") or ""))
        )
        trace = RemediationTraceEntry(
            case_id=ctx.case_id,
            attempt_index=ctx.attempt_index,
            decision_source="tier2-agent",
            summary=str(plan.get("summary", "tier-2 environment recovery")),
            failure_snapshot=snapshot.to_dict(),
            executed_actions=executed_actions,
            applied=bool(execution.get("success", False)),
            verify_after=gate_passed,
            core_verify_after=gate_passed,
            comment=(
                safe_execution_comment
                if gate_passed
                else safe_verify_error
                or "tier-2 deterministic verify_env gate failed"
            ),
        )
        state["remediation_history"].append(trace.to_dict())
        data["remediation_trace_entry"] = trace.to_dict()
        if gate_passed:
            state["tier1_failure_streak"] = 0
            state["last_tier1"] = None
            self._project_state(state, data)
            log.info("tier-2 verify_env gate passed case=%s", ctx.case_id)
            return HookResult(advice="tier-2 verify_env gate passed")

        failure = self._tier2_failure_snapshot(
            ctx,
            safe_verify_error or "tier-2 deterministic verify_env gate failed",
            agent_intervened=bool(state["agent_recovered"]),
        )
        state["failure_snapshot"] = failure.to_dict()
        self._project_state(state, data)
        log.info("tier-2 verify_env gate failed case=%s", ctx.case_id)
        return HookResult(proceed=False, advice=failure.comment)

    def _fail_tier2(
        self,
        *,
        ctx: HookContext,
        data: dict[str, Any],
        state: dict[str, Any],
        audit: Tier2RecoveryAudit,
        error: str,
        status: str = "failed",
    ) -> HookResult:
        safe_error = str(sanitize_tier2_value(error))
        audit.status = status
        audit.error = error
        audit.verify_gate = {
            "passed": False,
            "executed": False,
            "error": "tier-2 flow halted before deterministic verify_env",
        }
        state["tier2_audit"].append(audit.to_dict())
        failure = self._tier2_failure_snapshot(
            ctx,
            safe_error,
            agent_intervened=bool(state["agent_recovered"]),
        )
        state["failure_snapshot"] = failure.to_dict()
        trace = RemediationTraceEntry(
            case_id=ctx.case_id,
            attempt_index=ctx.attempt_index,
            decision_source="tier2-agent",
            summary="tier-2 environment recovery failed closed",
            failure_snapshot=failure.to_dict(),
            applied=False,
            verify_after=False,
            core_verify_after=False,
            comment=safe_error,
        )
        state["remediation_history"].append(trace.to_dict())
        data["remediation_trace_entry"] = trace.to_dict()
        self._project_state(state, data)
        return HookResult(proceed=False, advice=failure.comment)

    @staticmethod
    def _tier2_failure_snapshot(
        ctx: HookContext,
        comment: str,
        *,
        agent_intervened: bool,
    ) -> FailureSnapshot:
        return FailureSnapshot(
            case_id=ctx.case_id,
            attempt_index=ctx.attempt_index,
            phase="tier2_verify_env",
            comment=str(sanitize_tier2_value(comment)),
            category="environment",
            reason_code="tier2_env_recovery_failed",
            metadata={"agent_intervened": agent_intervened},
        )
