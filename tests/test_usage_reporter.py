from types import SimpleNamespace
import json

from testpilot.core.usage_ledger import UsageSnapshot, UsageRecord, InvocationRecord
from testpilot.reporting.usage_reporter import build_core_cost_report, write_core_cost_artifacts


def _snapshot() -> UsageSnapshot:
    invocation = InvocationRecord("i1", "r", "s", "D001", "case_planning", "direct", "azure", "", "", "completed", "", "exact")
    usage = UsageRecord("i1", "s", "call", None, "api_call_id", "D001", "case_planning", "direct", "azure", 10, 5, 2, 0, 1.5, None, "")
    return UsageSnapshot((invocation,), (usage,), ('{"event":"invocation_started","secret":"redacted"}',), 0, 0, 0)


def test_reporter_projects_tokens_without_secrets(tmp_path):
    record = SimpleNamespace(case_id="D001", case={"id": "D001"}, retry=SimpleNamespace(remediation_history=[] , agent_recovered=False))
    report = build_core_cost_report(run_result=SimpleNamespace(cases=[record]), planning_by_case={}, agent_recovery_support={}, usage=_snapshot(), metrics={}, analysis=SimpleNamespace(to_dict=lambda: {"status": "complete", "summary": "ok"}), agent_state={"initial_agent_state": "azure_ready", "final_agent_state": "azure_ready"})
    assert report["total"]["all_core_model_tokens"] == 15
    assert report["provider_cost_units"] == 1.5
    assert "secret" not in json.dumps(report).lower()
    artifacts = write_core_cost_artifacts(artifact_dir=tmp_path, report=report, usage=_snapshot(), analysis=SimpleNamespace(to_dict=lambda: {"status": "complete", "summary": "ok"}))
    assert (tmp_path / "agent_usage" / "cost-report.json").exists()
    assert artifacts.coverage == "core_sdk_calls_only"
