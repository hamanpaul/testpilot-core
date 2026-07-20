from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from testpilot.core.execution_engine import RetryResult
from testpilot.core.run_analysis import (
    CaseAnalysisCapsule,
    RunAnalysisResult,
    RunAnalysisValidationError,
    build_case_capsule,
    compact_batch_summaries_for_reducer,
    pack_case_capsules,
    parse_run_analysis_response,
)


def _capsule(
    case_id: str,
    *,
    failure_category: str = "environment",
) -> CaseAnalysisCapsule:
    return CaseAnalysisCapsule(
        case_id=case_id,
        initial_verdict="Fail",
        final_verdict="Pass",
        attempts_used=2,
        failure_category=failure_category,
        failure_reason_code="not_ready",
        deterministic_remediation={
            "observed": True,
            "applied": 1,
            "attempts": 1,
            "final_verdict": "Pass",
        },
        agent_recovery={
            "observed": False,
            "verified_count": 0,
            "final_verdict": "Pass",
            "recovered": False,
        },
        direct_model_tokens=42,
        duration_seconds=12.5,
    )


def test_build_case_capsule_projects_tier1_history_from_retry_result() -> None:
    retry = RetryResult(
        verdict=True,
        comment="",
        commands=[],
        outputs=[],
        attempts=[{"verdict": False}, {"verdict": True}],
        attempts_used=2,
        max_attempts=4,
        remediation_history=[
            {
                "decision_source": "tier1-deterministic",
                "applied": False,
                "executed_actions": [{"executor_key": "preflight"}],
            },
            {
                "decision_source": "tier1-deterministic",
                "applied": True,
                "executed_actions": [
                    {"executor_key": "repair"},
                    {"executor_key": "reverify"},
                ],
            },
            {
                "decision_source": "tier2-agent",
                "applied": True,
                "executed_actions": [{"executor_key": "agent-repair"}],
            },
        ],
        failure_snapshot={"category": "environment", "reason_code": "not_ready"},
    )
    record = SimpleNamespace(
        case_id="D001",
        case={"id": "D001"},
        retry=retry,
        duration_seconds=12.5,
    )

    capsule = build_case_capsule(
        record,
        direct_usage={"model_tokens": 42},
    )

    assert capsule.initial_verdict == "Fail"
    assert capsule.final_verdict == "Pass"
    assert capsule.deterministic_remediation == {
        "observed": True,
        "applied": 1,
        "attempts": 3,
        "final_verdict": "Pass",
    }


def test_parse_run_analysis_response_accepts_valid_payload() -> None:
    raw = json.dumps(
        {
            "summary": "overall summary",
            "benefit_assessment": ["saved retries"],
            "cost_observations": ["one analysis batch"],
            "case_findings": [
                {
                    "case_id": "D001",
                    "assessment": "tier-1 fixed the issue",
                    "evidence": ["final pass", "deterministic remediation applied"],
                }
            ],
        }
    )

    parsed = parse_run_analysis_response(raw, allowed_case_ids={"D001"})

    assert parsed == {
        "summary": "overall summary",
        "benefit_assessment": ["saved retries"],
        "cost_observations": ["one analysis batch"],
        "case_findings": [
            {
                "case_id": "D001",
                "assessment": "tier-1 fixed the issue",
                "evidence": ["final pass", "deterministic remediation applied"],
            }
        ],
    }


def test_parse_run_analysis_response_rejects_wrong_schema() -> None:
    raw = json.dumps({"summary": "ok", "benefit_assessment": [], "cost_observations": []})

    with pytest.raises(RunAnalysisValidationError, match="schema"):
        parse_run_analysis_response(raw, allowed_case_ids={"D001"})


def test_parse_run_analysis_response_rejects_oversized_summary() -> None:
    raw = json.dumps(
        {
            "summary": "x" * 4001,
            "benefit_assessment": [],
            "cost_observations": [],
            "case_findings": [],
        }
    )

    with pytest.raises(RunAnalysisValidationError, match="summary"):
        parse_run_analysis_response(raw, allowed_case_ids={"D001"})


def test_parse_run_analysis_response_rejects_secret_bearing_summary() -> None:
    raw = json.dumps(
        {
            "summary": "password leaked",
            "benefit_assessment": [],
            "cost_observations": [],
            "case_findings": [],
        }
    )

    with pytest.raises(RunAnalysisValidationError, match="summary"):
        parse_run_analysis_response(raw, allowed_case_ids={"D001"})


def test_parse_run_analysis_response_rejects_duplicate_case_ids() -> None:
    raw = json.dumps(
        {
            "summary": "overall summary",
            "benefit_assessment": [],
            "cost_observations": [],
            "case_findings": [
                {"case_id": "D001", "assessment": "first", "evidence": []},
                {"case_id": "D001", "assessment": "second", "evidence": []},
            ],
        }
    )

    with pytest.raises(RunAnalysisValidationError, match="duplicate"):
        parse_run_analysis_response(raw, allowed_case_ids={"D001", "D002"})


def test_parse_run_analysis_response_rejects_unknown_case_id() -> None:
    raw = json.dumps(
        {
            "summary": "overall summary",
            "benefit_assessment": [],
            "cost_observations": [],
            "case_findings": [
                {"case_id": "D999", "assessment": "unknown", "evidence": []},
            ],
        }
    )

    with pytest.raises(RunAnalysisValidationError, match="invalid case finding"):
        parse_run_analysis_response(raw, allowed_case_ids={"D001"})


def test_pack_case_capsules_splits_before_overhead_buffer() -> None:
    batches = pack_case_capsules(
        [_capsule("D001"), _capsule("D002")],
        target_chars=2200,
    )

    assert [[capsule.case_id for capsule in batch] for batch in batches] == [
        ["D001"],
        ["D002"],
    ]


def test_pack_case_capsules_rejects_single_oversized_capsule() -> None:
    with pytest.raises(RunAnalysisValidationError, match="capsule exceeds"):
        pack_case_capsules(
            [_capsule("D001", failure_category="x" * 500)],
            target_chars=100,
        )


def test_compact_batch_summaries_for_reducer_truncates_to_budget() -> None:
    summaries = [
        {
            "summary": "s" * 1200,
            "benefit_assessment": [],
            "cost_observations": [],
        },
    ]

    compact = compact_batch_summaries_for_reducer(summaries, target_chars=500)
    compact_json = json.dumps(
        [dict(row) for row in compact],
        ensure_ascii=False,
        separators=(",", ":"),
    )

    assert len(compact_json) <= 500
    assert compact[0]["summary"] != summaries[0]["summary"]


def test_compact_batch_summaries_for_reducer_rejects_oversized_envelope() -> None:
    with pytest.raises(RunAnalysisValidationError, match="envelope"):
        compact_batch_summaries_for_reducer(
            [{"summary": "", "benefit_assessment": [], "cost_observations": []}],
            target_chars=10,
        )


def test_run_analysis_result_from_mapping_preserves_override_findings() -> None:
    result = RunAnalysisResult.from_mapping(
        {
            "summary": "overall summary",
            "benefit_assessment": ["saved retries"],
            "cost_observations": ["one batch"],
            "case_findings": [{"case_id": "D002", "assessment": "ignored", "evidence": []}],
        },
        batch_calls=2,
        reducer_calls=1,
        case_findings=[{"case_id": "D001", "assessment": "kept", "evidence": []}],
    )

    assert result == RunAnalysisResult(
        status="complete",
        summary="overall summary",
        benefit_assessment=("saved retries",),
        cost_observations=("one batch",),
        case_findings=({"case_id": "D001", "assessment": "kept", "evidence": []},),
        batch_calls=2,
        reducer_calls=1,
        error_type="",
    )
