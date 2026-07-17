"""Bounded, advisory per-case planning for the Azure agent."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal, Mapping


class CasePlanningValidationError(ValueError):
    """Raised when local prompt or provider planning data is invalid."""


PlanningStatus = Literal["completed", "failed", "skipped_no_agent", "skipped_circuit_breaker"]


@dataclass(frozen=True, slots=True)
class CasePlanningAdvisory:
    risk_summary: str
    attention_points: tuple[str, ...]
    expected_observations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"risk_summary": self.risk_summary, "attention_points": list(self.attention_points), "expected_observations": list(self.expected_observations)}


@dataclass(frozen=True, slots=True)
class CasePlanningResult:
    status: PlanningStatus
    advisory: CasePlanningAdvisory | None = None
    error_type: str = ""

    def to_trace_dict(self) -> dict[str, Any]:
        return {"status": self.status, "advisory": self.advisory.to_dict() if self.advisory else None, "error_type": self.error_type}


_SECRET_PATTERN = re.compile(r"(?i)(password|passwd|api[_-]?key|token|secret)\s*[:=]\s*([^\s,;]+)")


def _text(value: Any, limit: int) -> str:
    text = str(value or "")
    text = _SECRET_PATTERN.sub(lambda match: f"{match.group(1)}=<redacted>", text)
    return text[:limit]


def _strings(value: Any, *, limit: int, item_chars: int = 500) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [_text(item, item_chars) for item in value[:limit]]


def _step_summary(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, (list, tuple)):
        return []
    result: list[dict[str, Any]] = []
    for item in value[:32]:
        if not isinstance(item, Mapping):
            continue
        result.append({"id": _text(item.get("id"), 100), "command": _text(item.get("command"), 500), "capture": _strings(item.get("capture"), limit=8, item_chars=120)})
    return result


def build_case_planning_prompt(*, case: Mapping[str, Any], execution_policy: Mapping[str, Any], run_metadata: Mapping[str, Any]) -> str:
    case_payload = {"id": _text(case.get("id"), 200), "name": _text(case.get("name"), 500), "bands": _strings(case.get("bands"), limit=8), "steps": _step_summary(case.get("steps")), "pass_criteria": _strings(case.get("pass_criteria"), limit=32)}
    policy_payload = {key: execution_policy[key] for key in ("mode", "max_concurrency", "retry", "timeout", "failure_policy") if key in execution_policy}
    metadata = {key: run_metadata[key] for key in ("run_id", "plugin_name", "case_ordinal", "case_count") if key in run_metadata}
    prompt = (
        "Provide advisory planning only. You cannot change runner, commands, pass criteria, retry policy, or execute tools. "
        "Return exactly one JSON object with keys risk_summary, attention_points, expected_observations.\n"
        + json.dumps({"case": case_payload, "execution_policy": policy_payload, "run_metadata": metadata}, ensure_ascii=False, separators=(",", ":"))
    )
    if len(prompt) > 24_000:
        raise CasePlanningValidationError("planning prompt exceeds bounded size")
    return prompt


def parse_case_planning_response(raw_response: str) -> CasePlanningAdvisory:
    try:
        value = json.loads(raw_response)
    except (TypeError, json.JSONDecodeError) as exc:
        raise CasePlanningValidationError("planning response is not JSON") from exc
    if not isinstance(value, dict) or set(value) != {"risk_summary", "attention_points", "expected_observations"}:
        raise CasePlanningValidationError("planning response schema is not exact")
    risk = value["risk_summary"]
    attention = value["attention_points"]
    expected = value["expected_observations"]
    if not isinstance(risk, str) or not risk or len(risk) > 2_000 or not isinstance(attention, list) or not isinstance(expected, list):
        raise CasePlanningValidationError("planning response values are invalid")
    if len(attention) > 16 or len(expected) > 16 or any(not isinstance(x, str) or len(x) > 1_000 for x in [*attention, *expected]):
        raise CasePlanningValidationError("planning response values are unbounded")
    return CasePlanningAdvisory(risk, tuple(attention), tuple(expected))
