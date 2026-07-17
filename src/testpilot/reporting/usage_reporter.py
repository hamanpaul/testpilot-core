"""Core-owned, secret-safe cost and usage report projection."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from testpilot.core.usage_ledger import UsageSnapshot


@dataclass(frozen=True, slots=True)
class CoreCostArtifacts:
    status: str
    json_path: str = ""
    markdown_path: str = ""
    analysis_status: str = ""
    execution_path: str = "core_run_loop"
    coverage: str = "core_sdk_calls_only"
    error_type: str = ""

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


def _usage_rows(usage: UsageSnapshot, *, case_id: str | None = None, purpose: str | None = None) -> list[Any]:
    return [r for r in usage.usage if (case_id is None or r.case_id == case_id) and (purpose is None or r.purpose == purpose)]


def _invocations(usage: UsageSnapshot, *, case_id: str | None = None, purpose: str | None = None) -> list[Any]:
    return [r for r in usage.invocations if (case_id is None or r.case_id == case_id) and (purpose is None or r.purpose == purpose)]


def _usage_summary(usage: UsageSnapshot, *, case_id: str | None, purpose: str) -> dict[str, Any]:
    calls = _invocations(usage, case_id=case_id, purpose=purpose)
    rows = _usage_rows(usage, case_id=case_id, purpose=purpose)
    tokens = sum(r.model_tokens for r in rows)
    status = "not_called" if not calls else ("exact" if all(r.usage_status == "exact" for r in calls) else "unavailable")
    return {"purpose": purpose, "status": "completed" if any(r.status == "completed" for r in calls) else (calls[0].status if calls else "not_called"), "calls": len(calls), "input_tokens": sum(r.input_tokens for r in rows), "output_tokens": sum(r.output_tokens for r in rows), "total_tokens": tokens, "usage_status": status, "cache_read_tokens": sum(r.cache_read_tokens for r in rows), "cache_write_tokens": sum(r.cache_write_tokens for r in rows), "provider_cost_units": sum(r.provider_cost_units or 0 for r in rows) if any(r.provider_cost_units is not None for r in rows) else None}


def _deterministic(record: Any) -> dict[str, Any]:
    history = getattr(record.retry, "remediation_history", None) or []
    rows = [x for x in history if isinstance(x, Mapping) and str(x.get("decision_source", "")).startswith("tier1-deterministic") and x.get("executed_actions")]
    actions = [a for x in rows for a in x.get("executed_actions", []) if isinstance(a, Mapping)]
    plugin_attempted = sum(isinstance(x.get("verify_after"), bool) for x in rows)
    plugin_passed = sum(x.get("verify_after") is True for x in rows)
    core_attempted = sum(isinstance(x.get("core_verify_after"), bool) for x in rows)
    core_passed = sum(x.get("core_verify_after") is True for x in rows)
    return {"calls": len(rows), "tokens": 0, "actions": len(actions), "applied": sum(bool(x.get("applied")) for x in rows), "failed": sum(not bool(x.get("applied")) for x in rows), "plugin_verify": {"attempted": plugin_attempted, "passed": plugin_passed}, "core_next_attempt_verify": {"attempted": core_attempted, "passed": core_passed}, "observed_resolution": any(bool(x.get("applied")) and x.get("verify_after") is True for x in rows)}


def build_core_cost_report(*, run_result: Any, planning_by_case: Mapping[str, Any], agent_recovery_support: Mapping[str, Any], usage: UsageSnapshot, metrics: Mapping[str, Any], analysis: Any, agent_state: Mapping[str, str]) -> dict[str, Any]:
    per_case = []
    for record in run_result.cases:
        case_id = str(record.case_id or record.case.get("id", ""))
        agent = _usage_summary(usage, case_id=case_id, purpose="case_planning")
        recovery = _usage_summary(usage, case_id=case_id, purpose="agent_recovery")
        support = agent_recovery_support.get(case_id)
        recovery.update({"supported": bool(getattr(support, "supported", False)), "reason": str(getattr(support, "reason", "") or ""), "observed_resolution": bool(getattr(record.retry, "agent_recovered", False))})
        deterministic = _deterministic(record)
        per_case.append({"case_id": case_id, "agent": agent, "deterministic_remediation": deterministic, "agent_recovery": recovery, "direct_total_tokens": agent["total_tokens"] + recovery["total_tokens"]})
    shared_rows = _usage_rows(usage, purpose="run_analysis_batch") + _usage_rows(usage, purpose="run_analysis_reducer")
    shared_tokens = sum(r.model_tokens for r in shared_rows)
    direct_tokens = sum(c["direct_total_tokens"] for c in per_case)
    all_invocations = usage.invocations
    usage_status = "not_called" if not all_invocations else ("exact" if all(r.usage_status == "exact" for r in all_invocations) else "unavailable")
    costs = [r.provider_cost_units for r in usage.usage if r.provider_cost_units is not None]
    state = dict(agent_state)
    return {"schema_version": "1.0", "coverage": "core_sdk_calls_only", "execution_path": "core_run_loop", "agent_state": state, "per_case": per_case, "shared": {"run_analysis_tokens": shared_tokens, "batch_calls": len(_invocations(usage, purpose="run_analysis_batch")), "reducer_calls": len(_invocations(usage, purpose="run_analysis_reducer")), "usage_status": "not_called" if not shared_rows else ("exact" if all(r.usage_status == "exact" for r in _invocations(usage, purpose="run_analysis_batch") + _invocations(usage, purpose="run_analysis_reducer")) else "unavailable")}, "total": {"direct_tokens": direct_tokens, "shared_tokens": shared_tokens, "all_core_model_tokens": direct_tokens + shared_tokens, "usage_status": usage_status}, "cache_tokens": {"read": sum(r.cache_read_tokens for r in usage.usage), "write": sum(r.cache_write_tokens for r in usage.usage)}, "provider_cost_units": sum(costs) if costs else None, "assistance_metrics": dict(metrics), "analysis": analysis.to_dict() if hasattr(analysis, "to_dict") else dict(analysis or {})}


def _markdown(report: Mapping[str, Any], analysis: Any) -> str:
    lines = ["# Core Agent Cost Report", "", f"- coverage: `{report.get('coverage')}`", f"- execution_path: `{report.get('execution_path')}`", f"- agent state: `{report.get('agent_state', {}).get('initial_agent_state', '')}` → `{report.get('agent_state', {}).get('final_agent_state', '')}`", "", "| case | planning tokens | deterministic actions | recovery tokens | direct total |", "|---|---:|---:|---:|---:|"]
    for row in report.get("per_case", []):
        lines.append(f"| {row['case_id']} | {row['agent']['total_tokens']} | {row['deterministic_remediation']['actions']} | {row['agent_recovery']['total_tokens']} | {row['direct_total_tokens']} |")
    lines += ["", f"- shared run-analysis tokens: {report.get('shared', {}).get('run_analysis_tokens', 0)}", f"- all core model tokens: {report.get('total', {}).get('all_core_model_tokens', 0)}", "", "## Analysis", "", str(report.get("analysis", {}).get("summary", ""))[:4000]]
    return "\n".join(lines) + "\n"


def write_core_cost_artifacts(*, artifact_dir: Path, report: Mapping[str, Any], usage: UsageSnapshot, analysis: Any) -> CoreCostArtifacts:
    out = artifact_dir / "agent_usage"
    out.mkdir(parents=True, exist_ok=True)
    (out / "events.jsonl").write_text("".join(line + "\n" for line in usage.journal_lines), encoding="utf-8")
    (out / "cost-report.json").write_text(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")
    (out / "cost-report.md").write_text(_markdown(report, analysis), encoding="utf-8")
    analysis_payload = analysis.to_dict() if hasattr(analysis, "to_dict") else dict(analysis or {})
    (out / "run-analysis.json").write_text(json.dumps(analysis_payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")
    (out / "run-analysis.md").write_text("# Run Analysis\n\n" + str(analysis_payload.get("summary", ""))[:4000] + "\n", encoding="utf-8")
    status = "partial" if analysis_payload.get("status") == "failed" else "complete"
    return CoreCostArtifacts(status=status, json_path=str(out / "cost-report.json"), markdown_path=str(out / "cost-report.md"), analysis_status=str(analysis_payload.get("status", "")))
