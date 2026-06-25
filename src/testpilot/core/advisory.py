"""Structured output schema and collector for advisory agents."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable

from testpilot.core.hook_policy import HookContext, HookResult

VALID_SEVERITIES = frozenset({"info", "warning", "error", "critical"})
VALID_CATEGORIES = frozenset(
    {"configuration", "environment", "test_design", "firmware", "flaky"}
)


@dataclass(slots=True)
class AdvisoryOutput:
    """Structured output from an advisory agent analysis."""

    case_id: str
    severity: str  # "info", "warning", "error", "critical"
    category: str  # "configuration", "environment", "test_design", "firmware", "flaky"
    summary: str  # one-line summary
    detail: str = ""  # detailed analysis
    suggested_action: str = ""  # recommended fix/next step
    confidence: float = 0.0  # 0.0-1.0
    evidence: list[str] = field(default_factory=list)  # supporting evidence


class AdvisoryCollector:
    """Collect and aggregate advisory outputs across a test run."""

    def __init__(self) -> None:
        self._outputs: list[AdvisoryOutput] = []

    def add(self, output: AdvisoryOutput) -> None:
        """Add an advisory output."""
        self._outputs.append(output)

    def for_case(self, case_id: str) -> list[AdvisoryOutput]:
        """Get all advisories for a specific case."""
        return [o for o in self._outputs if o.case_id == case_id]

    def by_severity(self, severity: str) -> list[AdvisoryOutput]:
        """Filter advisories by severity level."""
        return [o for o in self._outputs if o.severity == severity]

    def by_category(self, category: str) -> list[AdvisoryOutput]:
        """Filter advisories by category."""
        return [o for o in self._outputs if o.category == category]

    def summary(self) -> dict[str, Any]:
        """Generate aggregate summary stats."""
        severity_counts: Counter[str] = Counter()
        category_counts: Counter[str] = Counter()
        for o in self._outputs:
            severity_counts[o.severity] += 1
            category_counts[o.category] += 1
        return {
            "total": len(self._outputs),
            "by_severity": dict(severity_counts),
            "by_category": dict(category_counts),
        }

    def to_hook_handler(self) -> Callable[[HookContext, dict[str, Any]], HookResult]:
        """Return a hook handler that creates advisories from failure context."""
        collector = self

        def _handler(ctx: HookContext, data: dict[str, Any]) -> HookResult:
            verdict = data.get("verdict")
            comment = data.get("comment", "")
            failure_snapshot = data.get("failure_snapshot")
            snapshot = failure_snapshot if isinstance(failure_snapshot, dict) else {}

            # Only generate advisory for failures
            if verdict is not False and ctx.hook_name != "on_failure":
                return HookResult(proceed=True)

            severity = "error" if ctx.hook_name == "on_failure" else "warning"
            category = str(snapshot.get("category", "environment") or "environment")
            summary_text = comment if comment else f"Failure in {ctx.case_id}"

            advisory = AdvisoryOutput(
                case_id=ctx.case_id,
                severity=severity,
                category=category,
                summary=summary_text,
            )
            collector.add(advisory)
            return HookResult(proceed=True, advice=advisory.summary)

        return _handler

    @property
    def all(self) -> list[AdvisoryOutput]:
        """All collected advisories."""
        return list(self._outputs)
