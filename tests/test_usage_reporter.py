from types import SimpleNamespace
import json

from testpilot.core.usage_ledger import InvocationRecord, UsageRecord, UsageSnapshot
from testpilot.reporting.usage_reporter import build_core_cost_report, write_core_cost_artifacts


def _snapshot() -> UsageSnapshot:
    invocation = InvocationRecord(
        invocation_id="i1",
        run_id="r",
        session_id="s",
        case_id="D001",
        purpose="case_planning",
        allocation="direct",
        model="azure",
        started_at="",
        finished_at="",
        status="completed",
        error_type="",
        usage_status="exact",
    )
    usage = UsageRecord(
        invocation_id="i1",
        session_id="s",
        api_call_id="call",
        event_id=None,
        dedupe_basis="api_call_id",
        case_id="D001",
        purpose="case_planning",
        allocation="direct",
        model="azure",
        input_tokens=10,
        output_tokens=5,
        cache_read_tokens=2,
        cache_write_tokens=0,
        provider_cost_units=1.5,
        duration_seconds=None,
        timestamp="",
    )
    return UsageSnapshot(
        (invocation,),
        (usage,),
        ('{"event":"invocation_started","secret":"redacted"}',),
        0,
        0,
        0,
    )


def _snapshot_with_missing_usage() -> UsageSnapshot:
    return UsageSnapshot(
        (
            InvocationRecord(
                invocation_id="i1",
                run_id="r",
                session_id="s-plan",
                case_id="D001",
                purpose="case_planning",
                allocation="direct",
                model="azure",
                started_at="",
                finished_at="",
                status="completed",
                error_type="",
                usage_status="exact",
            ),
            InvocationRecord(
                invocation_id="i2",
                run_id="r",
                session_id="s-recovery",
                case_id="D001",
                purpose="agent_recovery",
                allocation="direct",
                model="azure",
                started_at="",
                finished_at="",
                status="failed",
                error_type="TimeoutError",
                usage_status="unavailable",
            ),
        ),
        (
            UsageRecord(
                invocation_id="i1",
                session_id="s-plan",
                api_call_id="call",
                event_id=None,
                dedupe_basis="api_call_id",
                case_id="D001",
                purpose="case_planning",
                allocation="direct",
                model="azure",
                input_tokens=10,
                output_tokens=5,
                cache_read_tokens=2,
                cache_write_tokens=0,
                provider_cost_units=1.5,
                duration_seconds=None,
                timestamp="",
            ),
        ),
        ('{"event":"invocation_started","secret":"redacted"}',),
        0,
        0,
        0,
    )


def _record(
    case_id: str,
    *,
    attempts: list[bool],
    final: bool,
    remediation_history: list[dict] | None = None,
    tier2_audit: list[dict] | None = None,
    agent_recovered: bool = False,
):
    retry = SimpleNamespace(
        attempts=[{"verdict": verdict} for verdict in attempts],
        verdict=final,
        remediation_history=remediation_history or [],
        tier2_audit=tier2_audit or [],
        agent_recovered=agent_recovered,
    )
    return SimpleNamespace(case_id=case_id, case={"id": case_id}, retry=retry)


def test_reporter_projects_tokens_without_secrets(tmp_path):
    record = SimpleNamespace(case_id="D001", case={"id": "D001"}, retry=SimpleNamespace(remediation_history=[] , agent_recovered=False))
    report = build_core_cost_report(run_result=SimpleNamespace(cases=[record]), planning_by_case={}, agent_recovery_support={}, usage=_snapshot(), metrics={}, analysis=SimpleNamespace(to_dict=lambda: {"status": "complete", "summary": "ok"}), agent_state={"initial_agent_state": "azure_ready", "final_agent_state": "azure_ready"})
    assert report["total"]["all_core_model_tokens"] == 15
    assert report["provider_cost_units"] == 1.5
    assert "secret" not in json.dumps(report).lower()
    artifacts = write_core_cost_artifacts(artifact_dir=tmp_path, report=report, usage=_snapshot(), analysis=SimpleNamespace(to_dict=lambda: {"status": "complete", "summary": "ok"}))
    assert (tmp_path / "agent_usage" / "cost-report.json").exists()
    assert artifacts.coverage == "core_sdk_calls_only"


def test_reporter_marks_missing_usage_as_unavailable_and_writes_markdown(tmp_path):
    record = SimpleNamespace(
        case_id="D001",
        case={"id": "D001"},
        retry=SimpleNamespace(remediation_history=[], tier2_audit=[], agent_recovered=False),
    )
    report = build_core_cost_report(
        run_result=SimpleNamespace(cases=[record]),
        planning_by_case={},
        agent_recovery_support={},
        usage=_snapshot_with_missing_usage(),
        metrics={},
        analysis=SimpleNamespace(to_dict=lambda: {"status": "complete", "summary": "ok"}),
        agent_state={"initial_agent_state": "azure_ready", "final_agent_state": "azure_ready"},
    )

    assert report["per_case"][0]["agent"]["usage_status"] == "exact"
    assert report["per_case"][0]["agent_recovery"]["usage_status"] == "unavailable"
    assert report["total"]["usage_status"] == "unavailable"

    write_core_cost_artifacts(
        artifact_dir=tmp_path,
        report=report,
        usage=_snapshot_with_missing_usage(),
        analysis=SimpleNamespace(to_dict=lambda: {"status": "complete", "summary": "ok"}),
    )
    markdown = (tmp_path / "agent_usage" / "cost-report.md").read_text(encoding="utf-8")

    assert "| D001 | 15 | 0 | 0 | 15 |" in markdown
    assert "## Analysis" in markdown


def test_reporter_marks_agent_intervention_without_claiming_resolution():
    report = build_core_cost_report(
        run_result=SimpleNamespace(
            cases=[
                _record(
                    "D001",
                    attempts=[False],
                    final=False,
                    tier2_audit=[
                        {
                            "status": "failed",
                            "prompt": "request",
                            "plan": {"actions": []},
                            "verify_gate": {"executed": True, "passed": False},
                        }
                    ],
                    agent_recovered=True,
                ),
                _record(
                    "D002",
                    attempts=[False, True],
                    final=True,
                    tier2_audit=[
                        {
                            "status": "accepted",
                            "prompt": "request",
                            "plan": {"actions": []},
                            "verify_gate": {"executed": True, "passed": True},
                        }
                    ],
                    agent_recovered=True,
                ),
            ]
        ),
        planning_by_case={},
        agent_recovery_support={},
        usage=UsageSnapshot((), (), (), 0, 0, 0),
        metrics={},
        analysis=SimpleNamespace(to_dict=lambda: {"status": "complete", "summary": "ok"}),
        agent_state={},
    )

    per_case = {row["case_id"]: row for row in report["per_case"]}
    assert per_case["D001"]["agent_recovery"]["intervened"] is True
    assert per_case["D001"]["agent_recovery"]["observed_resolution"] is False
    assert per_case["D002"]["agent_recovery"]["intervened"] is True
    assert per_case["D002"]["agent_recovery"]["observed_resolution"] is True


def test_reporter_counts_deterministic_resolution_from_applied_final_pass():
    report = build_core_cost_report(
        run_result=SimpleNamespace(
            cases=[
                _record(
                    "D001",
                    attempts=[False, True],
                    final=True,
                    remediation_history=[
                        {
                            "decision_source": "tier1-deterministic",
                            "applied": True,
                            "verify_after": None,
                            "executed_actions": [{"executor_key": "repair"}],
                        }
                    ],
                )
            ]
        ),
        planning_by_case={},
        agent_recovery_support={},
        usage=UsageSnapshot((), (), (), 0, 0, 0),
        metrics={},
        analysis=SimpleNamespace(to_dict=lambda: {"status": "complete", "summary": "ok"}),
        agent_state={},
    )

    assert report["per_case"][0]["deterministic_remediation"]["observed_resolution"] is True


def test_reporter_fences_analysis_summary_markdown(tmp_path):
    report = build_core_cost_report(
        run_result=SimpleNamespace(cases=[]),
        planning_by_case={},
        agent_recovery_support={},
        usage=UsageSnapshot((), (), (), 0, 0, 0),
        metrics={},
        analysis=SimpleNamespace(
            to_dict=lambda: {
                "status": "complete",
                "summary": "```html\n<script>alert(1)</script>\n```\n![x](http://evil)",
            }
        ),
        agent_state={},
    )

    write_core_cost_artifacts(
        artifact_dir=tmp_path,
        report=report,
        usage=UsageSnapshot((), (), (), 0, 0, 0),
        analysis=SimpleNamespace(
            to_dict=lambda: {
                "status": "complete",
                "summary": "```html\n<script>alert(1)</script>\n```\n![x](http://evil)",
            }
        ),
    )

    cost_md = (tmp_path / "agent_usage" / "cost-report.md").read_text(encoding="utf-8")
    analysis_md = (tmp_path / "agent_usage" / "run-analysis.md").read_text(encoding="utf-8")

    assert "## Analysis\n\n```" in cost_md
    assert "<script>alert(1)</script>" in cost_md
    assert "```html" not in cost_md
    assert "\n```\n" in analysis_md
    assert "```html" not in analysis_md


def test_reporter_projects_planning_status_when_no_agent_call_was_made():
    report = build_core_cost_report(
        run_result=SimpleNamespace(
            cases=[
                _record("D001", attempts=[False], final=False),
                _record("D002", attempts=[False], final=False),
                _record("D003", attempts=[False], final=False),
            ]
        ),
        planning_by_case={
            "D001": SimpleNamespace(status="skipped_no_agent", error_type=""),
            "D002": SimpleNamespace(
                status="failed",
                error_type="AgentRequestValidationError",
            ),
        },
        agent_recovery_support={},
        usage=UsageSnapshot((), (), (), 0, 0, 0),
        metrics={},
        analysis=SimpleNamespace(to_dict=lambda: {"status": "complete", "summary": "ok"}),
        agent_state={},
    )

    per_case = {row["case_id"]: row for row in report["per_case"]}
    assert per_case["D001"]["agent"]["status"] == "skipped_no_agent"
    assert per_case["D001"]["agent"]["error_type"] == ""
    assert per_case["D002"]["agent"]["status"] == "failed:AgentRequestValidationError"
    assert per_case["D002"]["agent"]["error_type"] == "AgentRequestValidationError"
    assert per_case["D003"]["agent"]["status"] == "not_called"


def _invocation(invocation_id: str, *, purpose: str, status: str, error_type: str = "") -> InvocationRecord:
    return InvocationRecord(
        invocation_id=invocation_id,
        run_id="r",
        session_id=f"s-{invocation_id}",
        case_id="D001",
        purpose=purpose,
        allocation="direct",
        model="azure",
        started_at="",
        finished_at="",
        status=status,
        error_type=error_type,
        usage_status="exact",
    )


def test_reporter_mixed_invocation_statuses_report_partial_not_completed():
    snapshot = UsageSnapshot(
        (
            _invocation("i1", purpose="agent_recovery", status="failed", error_type="TimeoutError"),
            _invocation("i2", purpose="agent_recovery", status="completed"),
            _invocation("i3", purpose="run_analysis", status="failed", error_type="TimeoutError"),
        ),
        (),
        (),
        0,
        0,
        0,
    )
    record = _record("D001", attempts=[False], final=False)
    report = build_core_cost_report(
        run_result=SimpleNamespace(cases=[record]),
        planning_by_case={},
        agent_recovery_support={},
        usage=snapshot,
        metrics={},
        analysis=SimpleNamespace(to_dict=lambda: {"status": "failed", "summary": ""}),
        agent_state={"initial_agent_state": "azure_ready", "final_agent_state": "azure_ready"},
    )
    assert report["per_case"][0]["agent_recovery"]["status"] == "partial"
    assert report["analysis"]["status"] == "failed"
