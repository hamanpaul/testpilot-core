"""Remediation planner — iterative failure analysis and fix suggestion loop.

Combines advisory outputs with agent role capabilities to build
remediation plans for persistent test failures.  The planner operates
as a post-run aggregation step, not during individual case execution.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Mapping, Sequence

from testpilot.core.advisory import AdvisoryCollector, AdvisoryOutput
from testpilot.core.hook_policy import HookContext, HookResult

log = logging.getLogger(__name__)


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
        return asdict(self)


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
        return asdict(self)


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
        return {
            "case_id": self.case_id,
            "attempt_index": self.attempt_index,
            "summary": self.summary,
            "source": self.source,
            "approved": self.approved,
            "failure": self.failure.to_dict() if self.failure else None,
            "actions": [action.to_dict() for action in self.actions],
        }


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
    comment: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(k): v for k, v in value.items()}
    if is_dataclass(value):
        return asdict(value)
    return {}


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
    return FailureSnapshot(
        case_id=str(data.get("case_id", case_id)),
        attempt_index=int(data.get("attempt_index", attempt_index)),
        phase=str(data.get("phase", phase)),
        comment=str(data.get("comment", comment)),
        step_id=str(data.get("step_id", step_id) or ""),
        category=str(data.get("category", "inconclusive") or "inconclusive"),
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
    """Hook-driven coordinator for safe in-run remediation."""

    def __init__(
        self,
        *,
        plugin: Any,
        topology: Any,
        policy: Mapping[str, Any] | None = None,
    ) -> None:
        self.plugin = plugin
        self.topology = topology
        self.policy = dict(policy or {})
        allowed = self.policy.get("allowed_actions")
        if isinstance(allowed, Sequence) and not isinstance(allowed, (str, bytes)):
            self.allowed_actions = {str(item).strip() for item in allowed if str(item).strip()}
        else:
            self.allowed_actions = set()
        self.max_actions_per_attempt = max(1, int(self.policy.get("max_actions_per_attempt", 3)))
        self.enabled = bool(self.policy.get("enabled", False))
        self._state: dict[str, dict[str, Any]] = {}

    def _case_state(self, case_id: str) -> dict[str, Any]:
        return self._state.setdefault(
            case_id,
            {
                "pending_decision": None,
                "failure_snapshot": None,
                "remediation_history": [],
            },
        )

    def handle_pre_case(self, ctx: HookContext, data: dict[str, Any]) -> HookResult:
        state = self._case_state(ctx.case_id)
        state["pending_decision"] = None
        state["failure_snapshot"] = None
        state["remediation_history"] = []
        data["remediation_history"] = []
        return HookResult()

    def handle_on_failure(self, ctx: HookContext, data: dict[str, Any]) -> HookResult:
        if not self.enabled:
            return HookResult()

        case = _as_mapping(data.get("case"))
        plugin_failure = case.get("_last_failure")
        snapshot = _coerce_failure_snapshot(
            plugin_failure,
            case_id=ctx.case_id,
            attempt_index=ctx.attempt_index,
            phase=str(data.get("phase", "failure")),
            comment=str(data.get("comment", "") or ""),
            step_id=ctx.step_id or "",
        )
        data["failure_snapshot"] = snapshot.to_dict()
        state = self._case_state(ctx.case_id)
        state["failure_snapshot"] = snapshot.to_dict()

        if snapshot.category not in {"environment", "session"}:
            state["pending_decision"] = None
            return HookResult(advice=snapshot.comment)

        decision = self._request_decision(case=case, snapshot=snapshot, runner=ctx.runner)
        if decision is None or not decision.approved:
            state["pending_decision"] = None
            return HookResult(advice=snapshot.comment)

        state["pending_decision"] = decision
        data["remediation_decision"] = decision.to_dict()
        return HookResult(advice=decision.summary or snapshot.comment)

    def handle_on_retry(self, ctx: HookContext, data: dict[str, Any]) -> HookResult:
        if not self.enabled:
            return HookResult()

        state = self._case_state(ctx.case_id)
        pending = state.get("pending_decision")
        decision = pending if isinstance(pending, RemediationDecision) else None
        if decision is None:
            data["remediation_history"] = list(state["remediation_history"])
            return HookResult()

        case = _as_mapping(data.get("case"))
        execution = self._execute_decision(case=case, decision=decision)
        trace_entry = RemediationTraceEntry(
            case_id=ctx.case_id,
            attempt_index=ctx.attempt_index,
            decision_source=decision.source,
            summary=decision.summary,
            failure_snapshot=decision.failure.to_dict() if decision.failure else None,
            executed_actions=[dict(item) for item in execution.get("actions", [])],
            applied=bool(execution.get("success", False)),
            verify_after=execution.get("verify_after"),
            comment=str(execution.get("comment", "") or ""),
        )
        state["remediation_history"].append(trace_entry.to_dict())
        state["pending_decision"] = None
        data["remediation_trace_entry"] = trace_entry.to_dict()
        data["remediation_history"] = list(state["remediation_history"])
        return HookResult(advice=trace_entry.comment or decision.summary)

    def handle_post_case(self, ctx: HookContext, data: dict[str, Any]) -> HookResult:
        state = self._case_state(ctx.case_id)
        data["remediation_history"] = list(state["remediation_history"])
        data["failure_snapshot"] = state.get("failure_snapshot")
        return HookResult()

    def _request_decision(
        self,
        *,
        case: Mapping[str, Any],
        snapshot: FailureSnapshot,
        runner: Mapping[str, Any],
    ) -> RemediationDecision | None:
        request_agent = getattr(self.plugin, "request_remediation_decision", None)
        if callable(request_agent):
            try:
                raw_agent_decision = request_agent(
                    dict(case),
                    snapshot,
                    self.topology,
                    runner=dict(runner),
                    remediation_policy=dict(self.policy),
                )
            except Exception:
                log.exception("agent remediation decision failed for %s", snapshot.case_id)
            else:
                decision = _coerce_decision(
                    raw_agent_decision,
                    default_source="agent",
                    failure=snapshot,
                )
                validated = self._validate_decision(decision)
                if validated is not None:
                    return validated

        builtin = getattr(self.plugin, "build_remediation_decision", None)
        if not callable(builtin):
            return None
        try:
            raw_builtin_decision = builtin(
                dict(case),
                snapshot,
                self.topology,
                runner=dict(runner),
                remediation_policy=dict(self.policy),
            )
        except Exception:
            log.exception("builtin remediation decision failed for %s", snapshot.case_id)
            return None
        decision = _coerce_decision(
            raw_builtin_decision,
            default_source="builtin-fallback",
            failure=snapshot,
        )
        return self._validate_decision(decision)

    def _validate_decision(self, decision: RemediationDecision | None) -> RemediationDecision | None:
        if decision is None or not decision.actions:
            return None

        approved_actions: list[RuntimeRemediationAction] = []
        for action in decision.actions:
            if action.safety_class != "safe_env":
                log.warning("reject unsafe remediation action: %s", action.executor_key)
                continue
            if self.allowed_actions and action.executor_key not in self.allowed_actions:
                log.warning("reject remediation action outside whitelist: %s", action.executor_key)
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
        try:
            result = execute(
                dict(case),
                decision,
                self.topology,
            )
        except Exception as exc:
            log.exception("remediation execution failed for %s", decision.case_id)
            return {
                "success": False,
                "verify_after": None,
                "comment": str(exc),
                "actions": [],
            }
        result_map = _as_mapping(result)
        return {
            "success": bool(result_map.get("success", False)),
            "verify_after": result_map.get("verify_after"),
            "comment": str(result_map.get("comment", "") or ""),
            "actions": [
                dict(item)
                for item in result_map.get("actions", [])
                if isinstance(item, Mapping)
            ],
        }
