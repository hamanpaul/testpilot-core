from types import SimpleNamespace

from testpilot.core.assistance_metrics import compute_assistance_metrics, summarize_case_assistance


def _audit(*, plan=True, gate=True, status="accepted", prompt="request"):
    return {
        "status": status,
        "prompt": prompt,
        "plan": {"actions": []} if plan else None,
        "verify_gate": {"executed": gate is not None, "passed": gate},
    }


def _tier1(*, applied=True, verify_after=None, core_verify_after=None,
           executed_actions=None, comment=""):
    return {
        "decision_source": "tier1-deterministic",
        "applied": applied,
        "verify_after": verify_after,
        "core_verify_after": core_verify_after,
        "executed_actions": executed_actions if executed_actions is not None else [],
        "comment": comment,
    }


def _tier2_trace(*, applied=True, core_verify_after=True):
    return {
        "decision_source": "tier2-agent",
        "applied": applied,
        "core_verify_after": core_verify_after,
        "executed_actions": [{"executor_key": "agent-repair"}],
    }


def _record(case_id, *, attempts, final, remediation=None, tier2_audit=None,
            agent_recovered=False):
    retry = SimpleNamespace(
        attempts=[{"verdict": verdict} for verdict in attempts],
        verdict=final,
        remediation_history=remediation or [],
        tier2_audit=tier2_audit or [],
        agent_recovered=agent_recovered,
    )
    return SimpleNamespace(case_id=case_id, retry=retry)


def _metric(*, numerator, denominator, rate_percent):
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate_percent": rate_percent,
        "evidence_level": "observational",
        "causal_uplift": "unavailable",
    }


def test_initial_and_final_pass_rates_and_delta():
    metrics = compute_assistance_metrics([
        _record("D001", attempts=[False, True], final=True),
        _record("D002", attempts=[True], final=True),
        _record("D003", attempts=[False], final=False),
    ])
    assert metrics["initial_pass_rate"] == _metric(numerator=1, denominator=3, rate_percent=33.333333)
    assert metrics["final_pass_rate"] == _metric(numerator=2, denominator=3, rate_percent=66.666667)
    assert metrics["overall_observed_delta_percentage_points"] == {
        "value_percentage_points": 33.333333,
        "evidence_level": "observational",
        "causal_uplift": "unavailable",
    }


def test_deterministic_resolution_excludes_any_tier2_intervention():
    metrics = compute_assistance_metrics([
        _record("D001", attempts=[False, True], final=True, remediation=[_tier1(
            verify_after=True, executed_actions=[{"executor_key": "generic-repair"}],
        )]),
        _record("D002", attempts=[False, True], final=True, remediation=[
            _tier1(verify_after=False), _tier2_trace(),
        ], tier2_audit=[_audit()]),
    ])
    assert metrics["deterministic_observed_resolution_rate"] == _metric(
        numerator=1, denominator=1, rate_percent=100.0
    )


def test_no_decision_tier1_miss_is_not_attributed_as_intervention():
    record = _record("D001", attempts=[False, True], final=True, remediation=[_tier1(
        applied=False, executed_actions=[], comment="tier-1 decision unavailable or rejected",
    )])
    summary = summarize_case_assistance(record)
    assert summary.deterministic_records == ()
    assert summary.deterministic_observed_resolution is False
    assert compute_assistance_metrics([record])["deterministic_observed_resolution_rate"] == _metric(
        numerator=0, denominator=0, rate_percent=None
    )


def test_agent_recovery_requires_invocation_gate_pass_and_final_pass():
    metrics = compute_assistance_metrics([
        _record("D001", attempts=[False, True], final=True, agent_recovered=True,
                tier2_audit=[_audit()]),
        _record("D002", attempts=[False, False], final=False, agent_recovered=True,
                tier2_audit=[_audit()]),
        _record("D003", attempts=[False, False], final=False, agent_recovered=True,
                tier2_audit=[_audit(plan=False, gate=None, status="rejected")]),
    ])
    assert metrics["agent_recovery_plan_acceptance_rate"] == _metric(numerator=2, denominator=3, rate_percent=66.666667)
    assert metrics["agent_recovery_env_gate_conversion_rate"] == _metric(numerator=2, denominator=2, rate_percent=100.0)
    assert metrics["agent_recovery_observed_resolution_rate"] == _metric(numerator=1, denominator=2, rate_percent=50.0)
    assert metrics["post_gate_case_failure_rate"] == _metric(numerator=1, denominator=2, rate_percent=50.0)


def test_empty_denominator_is_unavailable_not_zero():
    metric = compute_assistance_metrics([_record("D001", attempts=[True], final=True)])[
        "agent_recovery_plan_acceptance_rate"
    ]
    assert metric["rate_percent"] is None
    assert metric["denominator"] == 0
    assert metric["causal_uplift"] == "unavailable"


def test_agent_recovered_is_intervention_marker_not_success():
    summary = summarize_case_assistance(_record(
        "D001", attempts=[False], final=False, agent_recovered=True,
        tier2_audit=[_audit(plan=False, gate=None, status="failed")],
    ))
    assert summary.agent_intervened is True
    assert summary.agent_observed_resolution is False


def test_context_failure_audit_is_not_counted_as_agent_invocation():
    record = _record("D001", attempts=[False, True], final=True, remediation=[_tier1(
        verify_after=True, executed_actions=[{"executor_key": "generic-repair"}],
    )], tier2_audit=[_audit(plan=False, gate=False, status="rejected", prompt="")])
    metrics = compute_assistance_metrics([record])
    assert metrics["agent_recovery_plan_acceptance_rate"]["denominator"] == 0
    assert metrics["deterministic_observed_resolution_rate"] == _metric(
        numerator=1, denominator=1, rate_percent=100.0
    )
