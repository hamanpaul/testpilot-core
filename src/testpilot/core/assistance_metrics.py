"""Pure, observational case-assistance metrics.

This module intentionally only reads retry records.  It does not call an agent,
execute remediation, or reinterpret the case verdict.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from testpilot.core.run_loop import CaseRunRecord

_OBSERVATIONAL = "observational"
_UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class CaseAssistanceSummary:
    case_id: str
    initial_pass: bool
    final_pass: bool
    deterministic_records: tuple[Mapping[str, Any], ...]
    deterministic_gate_attempts: int
    deterministic_gate_passes: int
    deterministic_observed_resolution: bool
    agent_intervened: bool
    agent_plans_accepted: int
    agent_gate_attempts: int
    agent_gate_passes: int
    agent_observed_resolution: bool
    post_gate_case_failure: bool


def _mapping_sequence(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def summarize_case_assistance(record: CaseRunRecord) -> CaseAssistanceSummary:
    retry = record.retry
    attempts = _mapping_sequence(getattr(retry, "attempts", ()))
    initial_pass = bool(attempts[0].get("verdict", False)) if attempts else bool(getattr(retry, "verdict", False))
    final_pass = bool(getattr(retry, "verdict", False))

    tier1_history = [
        entry for entry in _mapping_sequence(getattr(retry, "remediation_history", ()))
        if entry.get("decision_source") == "tier1-deterministic"
    ]
    tier1_interventions = [
        entry for entry in tier1_history
        if isinstance(entry.get("executed_actions"), Sequence)
        and not isinstance(entry.get("executed_actions"), (str, bytes))
        and any(isinstance(action, Mapping) for action in entry["executed_actions"])
    ]
    deterministic_gate_values = [
        entry.get("verify_after") if isinstance(entry.get("verify_after"), bool)
        else entry.get("core_verify_after")
        for entry in tier1_interventions
        if isinstance(entry.get("verify_after"), bool)
        or isinstance(entry.get("core_verify_after"), bool)
    ]
    deterministic_gate_passes = sum(value is True for value in deterministic_gate_values)

    audits = _mapping_sequence(getattr(retry, "tier2_audit", ()))
    agent_intervened = bool(getattr(retry, "agent_recovered", False))
    invocation_audits = [
        item for item in audits
        if agent_intervened and bool(str(item.get("prompt", "")).strip())
    ]
    agent_plans_accepted = sum(isinstance(item.get("plan"), Mapping) for item in invocation_audits)
    gate_audits = [
        item for item in invocation_audits
        if isinstance(item.get("verify_gate"), Mapping)
        and item["verify_gate"].get("executed") is not False
    ]
    agent_gate_passes = sum(item["verify_gate"].get("passed") is True for item in gate_audits)
    agent_observed_resolution = (
        not initial_pass and agent_intervened and agent_gate_passes > 0 and final_pass
    )
    deterministic_observed_resolution = (
        not initial_pass and bool(tier1_interventions)
        and not agent_intervened and final_pass
    )
    return CaseAssistanceSummary(
        case_id=str(getattr(record, "case_id", "")),
        initial_pass=initial_pass,
        final_pass=final_pass,
        deterministic_records=tuple(tier1_interventions),
        deterministic_gate_attempts=len(deterministic_gate_values),
        deterministic_gate_passes=deterministic_gate_passes,
        deterministic_observed_resolution=deterministic_observed_resolution,
        agent_intervened=agent_intervened,
        agent_plans_accepted=agent_plans_accepted,
        agent_gate_attempts=len(gate_audits),
        agent_gate_passes=agent_gate_passes,
        agent_observed_resolution=agent_observed_resolution,
        post_gate_case_failure=bool(agent_gate_passes and not final_pass),
    )


def _rate(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate_percent": round(numerator * 100.0 / denominator, 6) if denominator else None,
        "evidence_level": _OBSERVATIONAL,
        "causal_uplift": _UNAVAILABLE,
    }


def _agent_invocation_count(record: CaseRunRecord) -> int:
    retry = record.retry
    if not bool(getattr(retry, "agent_recovered", False)):
        return 0
    return sum(
        bool(str(item.get("prompt", "")).strip())
        for item in _mapping_sequence(getattr(retry, "tier2_audit", ()))
    )


def compute_assistance_metrics(records: Sequence[CaseRunRecord]) -> dict[str, dict[str, Any]]:
    summaries = [summarize_case_assistance(record) for record in records]
    count = len(summaries)
    initial = sum(summary.initial_pass for summary in summaries)
    final = sum(summary.final_pass for summary in summaries)
    deterministic = [summary for summary in summaries if summary.deterministic_records]
    recovery_pairs = [
        (record, summary)
        for record, summary in zip(records, summaries, strict=True)
        if not summary.initial_pass
    ]
    recovery_records = [record for record, _summary in recovery_pairs]
    recovery_summaries = [summary for _record, summary in recovery_pairs]
    agent = [summary for summary in recovery_summaries if summary.agent_intervened]
    accepted = sum(summary.agent_plans_accepted for summary in agent)
    invocation_count = sum(_agent_invocation_count(record) for record in recovery_records)
    gate_attempts = sum(summary.agent_gate_attempts for summary in recovery_summaries)
    gate_passes = sum(summary.agent_gate_passes for summary in recovery_summaries)
    recovery_candidates = [summary for summary in recovery_summaries if summary.agent_gate_passes]
    initial_fraction = initial / count if count else 0.0
    final_fraction = final / count if count else 0.0
    return {
        "initial_pass_rate": _rate(initial, count),
        "final_pass_rate": _rate(final, count),
        "overall_observed_delta_percentage_points": {
            "value_percentage_points": round((final_fraction - initial_fraction) * 100.0, 6),
            "evidence_level": _OBSERVATIONAL,
            "causal_uplift": _UNAVAILABLE,
        },
        "deterministic_observed_resolution_rate": _rate(
            sum(summary.deterministic_observed_resolution for summary in deterministic), len(deterministic)
        ),
        "deterministic_env_gate_conversion_rate": _rate(
            sum(summary.deterministic_gate_passes for summary in deterministic),
            sum(summary.deterministic_gate_attempts for summary in deterministic),
        ),
        "agent_recovery_plan_acceptance_rate": _rate(accepted, invocation_count),
        "agent_recovery_env_gate_conversion_rate": _rate(gate_passes, gate_attempts),
        "agent_recovery_observed_resolution_rate": _rate(
            sum(summary.agent_observed_resolution for summary in recovery_candidates), len(recovery_candidates)
        ),
        "post_gate_case_failure_rate": _rate(
            sum(summary.post_gate_case_failure for summary in recovery_candidates), len(recovery_candidates)
        ),
    }
