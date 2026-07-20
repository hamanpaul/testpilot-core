"""Bounded, post-run analysis helpers.

The analysis payload is deliberately a small projection of a completed run.  It
must never contain commands, logs, prompts, provider responses, or remediation
executor details.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Literal, Mapping, Sequence


class RunAnalysisValidationError(ValueError):
    """Raised when a local analysis payload violates its fixed contract."""


def _bounded_text(value: Any, limit: int) -> str:
    text = str(value or "")
    return text[:limit]


def _status(value: Any) -> str:
    return _bounded_text(value, 128)


@dataclass(frozen=True, slots=True)
class CaseAnalysisCapsule:
    case_id: str
    initial_verdict: Literal["Pass", "Fail"]
    final_verdict: Literal["Pass", "Fail"]
    attempts_used: int
    failure_category: str
    failure_reason_code: str
    deterministic_remediation: dict[str, Any]
    agent_recovery: dict[str, Any]
    direct_model_tokens: int
    duration_seconds: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


AnalysisStatus = Literal[
    "complete", "failed", "skipped_no_agent", "skipped_circuit_breaker", "skipped_no_cases", "skipped_aborted"
]


@dataclass(frozen=True, slots=True)
class RunAnalysisResult:
    status: AnalysisStatus
    summary: str = ""
    benefit_assessment: tuple[str, ...] = ()
    cost_observations: tuple[str, ...] = ()
    case_findings: tuple[dict[str, Any], ...] = ()
    batch_calls: int = 0
    reducer_calls: int = 0
    error_type: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status, "summary": self.summary,
            "benefit_assessment": list(self.benefit_assessment),
            "cost_observations": list(self.cost_observations),
            "case_findings": [dict(item) for item in self.case_findings],
            "batch_calls": self.batch_calls, "reducer_calls": self.reducer_calls,
            "error_type": self.error_type,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any], *, batch_calls: int,
                     reducer_calls: int = 0,
                     case_findings: Sequence[Mapping[str, Any]] | None = None) -> "RunAnalysisResult":
        return cls(status="complete", summary=str(value["summary"]),
                   benefit_assessment=tuple(value["benefit_assessment"]),
                   cost_observations=tuple(value["cost_observations"]),
                   case_findings=tuple(dict(x) for x in (value["case_findings"] if case_findings is None else case_findings)),
                   batch_calls=batch_calls, reducer_calls=reducer_calls)


def _verdict(value: Any) -> Literal["Pass", "Fail"]:
    return "Pass" if str(value).lower() in {"pass", "passed", "true", "ok"} else "Fail"


def _mapping_sequence(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _deterministic_remediation_summary(retry: Any, final: Literal["Pass", "Fail"]) -> dict[str, Any]:
    history = [
        entry
        for entry in _mapping_sequence(getattr(retry, "remediation_history", ()))
        if entry.get("decision_source") == "tier1-deterministic"
        and isinstance(entry.get("executed_actions"), Sequence)
        and not isinstance(entry.get("executed_actions"), (str, bytes, bytearray))
    ]
    actions = [
        action
        for entry in history
        for action in entry["executed_actions"]
        if isinstance(action, Mapping)
    ]
    return {
        "observed": bool(history),
        "applied": sum(bool(entry.get("applied")) for entry in history),
        "attempts": len(actions),
        "final_verdict": final,
    }


def build_case_capsule(record: Any, *, direct_usage: Mapping[str, Any]) -> CaseAnalysisCapsule:
    retry = getattr(record, "retry", None)
    attempts = getattr(retry, "attempts", None)
    if isinstance(attempts, (list, tuple)):
        attempts_used = len(attempts)
        initial = _verdict(attempts[0].get("verdict") if attempts and isinstance(attempts[0], Mapping) else attempts[0] if attempts else "Fail")
    else:
        attempts_used = max(1, int(getattr(retry, "attempts_used", 1) or 1))
        initial = _verdict(getattr(retry, "initial_verdict", getattr(retry, "verdict", "Fail")))
    final = _verdict(getattr(retry, "verdict", getattr(retry, "final_verdict", "Fail")))
    snapshot = getattr(retry, "failure_snapshot", None) or {}
    if not isinstance(snapshot, Mapping):
        snapshot = {}
    audit = getattr(retry, "tier2_audit", None) or []
    verified = sum(1 for item in audit if isinstance(item, Mapping) and item.get("verify_gate", {}).get("passed") is True)
    return CaseAnalysisCapsule(
        case_id=str(getattr(record, "case_id", "") or record.case.get("id", "")),
        initial_verdict=initial, final_verdict=final,
        attempts_used=attempts_used,
        failure_category=_status(snapshot.get("category")),
        failure_reason_code=_status(snapshot.get("reason_code")),
        deterministic_remediation=_deterministic_remediation_summary(retry, final),
        agent_recovery={"observed": bool(audit), "verified_count": verified,
                        "final_verdict": final, "recovered": bool(getattr(retry, "agent_recovered", False))},
        direct_model_tokens=max(0, int(direct_usage.get("model_tokens", 0) or 0)),
        duration_seconds=max(0.0, float(getattr(record, "duration_seconds", 0.0) or 0.0)),
    )


def _json_len(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def pack_case_capsules(capsules: Sequence[CaseAnalysisCapsule], *, target_chars: int = 48_000) -> list[tuple[CaseAnalysisCapsule, ...]]:
    if target_chars <= 0:
        raise RunAnalysisValidationError("invalid packing target")
    result: list[tuple[CaseAnalysisCapsule, ...]] = []
    current: list[CaseAnalysisCapsule] = []
    for capsule in capsules:
        size = _json_len(capsule.to_dict())
        if size > target_chars:
            raise RunAnalysisValidationError("capsule exceeds batch bound")
        candidate = current + [capsule]
        if current and _json_len([x.to_dict() for x in candidate]) + 2000 > target_chars:
            result.append(tuple(current))
            current = [capsule]
        else:
            current = candidate
    if current:
        result.append(tuple(current))
    return result


def build_run_analysis_prompt(*, capsules: Sequence[CaseAnalysisCapsule], metrics: Mapping[str, Any], batch_index: int, batch_count: int) -> str:
    payload = {"batch": batch_index, "batch_count": batch_count, "metrics": dict(metrics), "cases": [x.to_dict() for x in capsules]}
    prompt = "Return only JSON matching the fixed run-analysis schema.\n" + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if len(prompt) > 64_000:
        raise RunAnalysisValidationError("analysis prompt exceeds bound")
    return prompt


def _validate_list(value: Any, *, name: str, max_items: int, max_chars: int) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > max_items:
        raise RunAnalysisValidationError(f"invalid {name}")
    rows = tuple(str(x) for x in value)
    if any(len(x) > max_chars for x in rows):
        raise RunAnalysisValidationError(f"oversized {name}")
    return rows


def parse_run_analysis_response(raw_response: str, *, allowed_case_ids: set[str]) -> dict[str, Any]:
    try:
        value = json.loads(raw_response)
    except Exception as exc:
        raise RunAnalysisValidationError("invalid JSON") from exc
    if not isinstance(value, dict) or set(value) != {"summary", "benefit_assessment", "cost_observations", "case_findings"}:
        raise RunAnalysisValidationError("unexpected analysis schema")
    summary = str(value["summary"])
    if len(summary) > 4000 or any(token in summary.lower() for token in ("password", "api_key", "secret")):
        raise RunAnalysisValidationError("invalid summary")
    benefits = _validate_list(value["benefit_assessment"], name="benefit_assessment", max_items=32, max_chars=1000)
    costs = _validate_list(value["cost_observations"], name="cost_observations", max_items=32, max_chars=1000)
    findings = value["case_findings"]
    if not isinstance(findings, list) or len(findings) > len(allowed_case_ids):
        raise RunAnalysisValidationError("invalid case_findings")
    normalized: list[dict[str, Any]] = []
    seen_case_ids: set[str] = set()
    for item in findings:
        if not isinstance(item, dict) or set(item) != {"case_id", "assessment", "evidence"} or item["case_id"] not in allowed_case_ids:
            raise RunAnalysisValidationError("invalid case finding")
        case_id = str(item["case_id"])
        if case_id in seen_case_ids:
            raise RunAnalysisValidationError("duplicate case_id finding")
        seen_case_ids.add(case_id)
        assessment = str(item["assessment"])
        evidence = _validate_list(item["evidence"], name="evidence", max_items=8, max_chars=500)
        if len(assessment) > 2000:
            raise RunAnalysisValidationError("oversized finding assessment")
        normalized.append({"case_id": case_id, "assessment": assessment, "evidence": list(evidence)})
    return {"summary": summary, "benefit_assessment": list(benefits), "cost_observations": list(costs), "case_findings": normalized}


def compact_batch_summaries_for_reducer(summaries: Sequence[Mapping[str, Any]], *, target_chars: int = 40_000) -> tuple[dict[str, Any], ...]:
    rows = [{"batch": i + 1, "summary": str(x.get("summary", "")), "benefit_assessment": list(x.get("benefit_assessment", [])), "cost_observations": list(x.get("cost_observations", []))} for i, x in enumerate(summaries)]
    if _json_len([{**x, "summary": "", "benefit_assessment": [], "cost_observations": []} for x in rows]) > target_chars:
        raise RunAnalysisValidationError("reducer envelope exceeds bound")
    budget = max(0, target_chars - _json_len([{**x, "summary": "", "benefit_assessment": [], "cost_observations": []} for x in rows]))
    for row in rows:
        text = json.dumps(row, ensure_ascii=False, separators=(",", ":"))
        if len(text) > budget + _json_len({"batch": row["batch"], "summary": "", "benefit_assessment": [], "cost_observations": []}):
            row["summary"] = row["summary"][: max(0, budget // max(1, len(rows)))]
            row["benefit_assessment"] = [str(v)[:200] for v in row["benefit_assessment"][:8]]
            row["cost_observations"] = [str(v)[:200] for v in row["cost_observations"][:8]]
    compact = tuple(rows)
    if _json_len([dict(x) for x in compact]) > target_chars:
        raise RunAnalysisValidationError("reducer summary exceeds bound")
    return compact


def build_run_analysis_reducer_prompt(*, summaries: Sequence[Mapping[str, Any]], metrics: Mapping[str, Any]) -> str:
    payload = {"metrics": {k: metrics[k] for k in metrics if k in {"cases", "pass_count", "fail_count", "agent_tokens", "duration_seconds"}}, "batches": compact_batch_summaries_for_reducer(summaries)}
    prompt = "Return only JSON with empty case_findings for the aggregate run analysis.\n" + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if len(prompt) > 64_000:
        raise RunAnalysisValidationError("reducer prompt exceeds bound")
    return prompt
