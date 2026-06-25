"""Tests for advisory agent output schema and collector."""

from __future__ import annotations

from testpilot.core.advisory import AdvisoryCollector, AdvisoryOutput
from testpilot.core.hook_policy import HookContext, HookResult


class TestAdvisoryOutput:
    """AdvisoryOutput dataclass creation."""

    def test_creation_with_all_fields(self) -> None:
        out = AdvisoryOutput(
            case_id="D001",
            severity="error",
            category="firmware",
            summary="DUT did not respond",
            detail="Timeout after 30 s waiting for beacon",
            suggested_action="Reboot DUT and retry",
            confidence=0.85,
            evidence=["log line 42", "log line 99"],
        )
        assert out.case_id == "D001"
        assert out.severity == "error"
        assert out.category == "firmware"
        assert out.summary == "DUT did not respond"
        assert out.detail == "Timeout after 30 s waiting for beacon"
        assert out.suggested_action == "Reboot DUT and retry"
        assert out.confidence == 0.85
        assert out.evidence == ["log line 42", "log line 99"]

    def test_creation_with_defaults(self) -> None:
        out = AdvisoryOutput(
            case_id="D002",
            severity="info",
            category="configuration",
            summary="SSID mismatch",
        )
        assert out.detail == ""
        assert out.suggested_action == ""
        assert out.confidence == 0.0
        assert out.evidence == []

    def test_evidence_default_is_independent(self) -> None:
        a = AdvisoryOutput(case_id="A", severity="info", category="flaky", summary="x")
        b = AdvisoryOutput(case_id="B", severity="info", category="flaky", summary="y")
        a.evidence.append("only-a")
        assert b.evidence == []


class TestAdvisoryCollector:
    """AdvisoryCollector add / retrieval / filtering."""

    @staticmethod
    def _make(
        case_id: str = "D001",
        severity: str = "error",
        category: str = "firmware",
        summary: str = "fail",
    ) -> AdvisoryOutput:
        return AdvisoryOutput(
            case_id=case_id,
            severity=severity,
            category=category,
            summary=summary,
        )

    def test_add_and_all(self) -> None:
        col = AdvisoryCollector()
        o1 = self._make()
        o2 = self._make(case_id="D002")
        col.add(o1)
        col.add(o2)
        assert len(col.all) == 2

    def test_all_returns_copy(self) -> None:
        col = AdvisoryCollector()
        col.add(self._make())
        snapshot = col.all
        snapshot.clear()
        assert len(col.all) == 1

    def test_for_case_filtering(self) -> None:
        col = AdvisoryCollector()
        col.add(self._make(case_id="D001"))
        col.add(self._make(case_id="D002"))
        col.add(self._make(case_id="D001", severity="warning"))
        result = col.for_case("D001")
        assert len(result) == 2
        assert all(o.case_id == "D001" for o in result)

    def test_by_severity_filtering(self) -> None:
        col = AdvisoryCollector()
        col.add(self._make(severity="error"))
        col.add(self._make(severity="warning"))
        col.add(self._make(severity="error"))
        result = col.by_severity("error")
        assert len(result) == 2
        assert all(o.severity == "error" for o in result)

    def test_by_category_filtering(self) -> None:
        col = AdvisoryCollector()
        col.add(self._make(category="firmware"))
        col.add(self._make(category="environment"))
        col.add(self._make(category="firmware"))
        result = col.by_category("firmware")
        assert len(result) == 2
        assert all(o.category == "firmware" for o in result)

    def test_summary_generation(self) -> None:
        col = AdvisoryCollector()
        col.add(self._make(severity="error", category="firmware"))
        col.add(self._make(severity="error", category="environment"))
        col.add(self._make(severity="warning", category="firmware"))
        s = col.summary()
        assert s["total"] == 3
        assert s["by_severity"] == {"error": 2, "warning": 1}
        assert s["by_category"] == {"firmware": 2, "environment": 1}

    def test_summary_empty(self) -> None:
        col = AdvisoryCollector()
        s = col.summary()
        assert s == {"total": 0, "by_severity": {}, "by_category": {}}

    def test_empty_collector_returns_empty(self) -> None:
        col = AdvisoryCollector()
        assert col.all == []
        assert col.for_case("D001") == []
        assert col.by_severity("error") == []
        assert col.by_category("firmware") == []


class TestAdvisoryHookHandler:
    """to_hook_handler integration with hook system."""

    def test_handler_is_callable(self) -> None:
        col = AdvisoryCollector()
        handler = col.to_hook_handler()
        assert callable(handler)

    def test_handler_creates_advisory_on_failure_hook(self) -> None:
        col = AdvisoryCollector()
        handler = col.to_hook_handler()
        ctx = HookContext(
            hook_name="on_failure",
            case_id="D010",
            plugin_name="wifi_llapi",
        )
        result = handler(ctx, {"comment": "step timed out"})
        assert isinstance(result, HookResult)
        assert result.proceed is True
        assert result.advice == "step timed out"
        assert len(col.all) == 1
        adv = col.all[0]
        assert adv.case_id == "D010"
        assert adv.severity == "error"
        assert adv.summary == "step timed out"

    def test_handler_creates_advisory_on_post_case_failure(self) -> None:
        col = AdvisoryCollector()
        handler = col.to_hook_handler()
        ctx = HookContext(
            hook_name="post_case",
            case_id="D018",
            plugin_name="wifi_llapi",
        )
        result = handler(ctx, {"verdict": False, "comment": "all retries exhausted"})
        assert isinstance(result, HookResult)
        assert len(col.all) == 1
        assert col.all[0].severity == "warning"

    def test_handler_skips_on_pass(self) -> None:
        col = AdvisoryCollector()
        handler = col.to_hook_handler()
        ctx = HookContext(
            hook_name="post_case",
            case_id="D028",
            plugin_name="wifi_llapi",
        )
        result = handler(ctx, {"verdict": True, "comment": "ok"})
        assert result.proceed is True
        assert len(col.all) == 0

    def test_handler_accumulates_multiple(self) -> None:
        col = AdvisoryCollector()
        handler = col.to_hook_handler()
        for i in range(3):
            ctx = HookContext(
                hook_name="on_failure",
                case_id=f"D{i:03d}",
                plugin_name="wifi_llapi",
            )
            handler(ctx, {"comment": f"fail {i}"})
        assert len(col.all) == 3
        assert col.for_case("D001")[0].summary == "fail 1"
