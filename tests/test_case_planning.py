import json

import pytest

from testpilot.core.case_planning import (
    CasePlanningValidationError,
    build_case_planning_prompt,
    parse_case_planning_response,
)


def test_prompt_is_bounded_and_redacts_secret_values_without_mutating_input():
    case = {
        "id": "D001",
        "name": "ModeEnabled",
        "bands": ["5g"],
        "api_key": "opaque-key-sentinel",
        "steps": [
            {
                "id": "s1",
                "command": 'KeyPassPhrase = "opaque-passphrase"',
                "capture": [
                    "wpa_passphrase=opaque-psk",
                    "private_key=opaque-private",
                ],
            }
        ],
    }
    policy = {
        "mode": "sequential",
        "retry": {"max_attempts": 3},
        "private": "opaque-policy-secret",
    }
    original = repr(case)
    prompt = build_case_planning_prompt(
        case=case,
        execution_policy=policy,
        run_metadata={"run_id": "r1"},
    )
    assert len(prompt) <= 24_000
    assert repr(case) == original
    assert "opaque-key-sentinel" not in prompt
    assert "opaque-password" not in prompt
    assert "opaque-policy-secret" not in prompt
    assert "opaque-passphrase" not in prompt
    assert "opaque-psk" not in prompt
    assert "opaque-private" not in prompt
    assert "cannot change runner" in prompt


def test_prompt_serialization_failures_are_validation_errors():
    class BrokenMapping(dict):
        def get(self, key, default=None):
            raise RuntimeError("broken")

    with pytest.raises(CasePlanningValidationError):
        build_case_planning_prompt(
            case=BrokenMapping(),
            execution_policy={},
            run_metadata={},
        )


def test_parser_accepts_exact_schema():
    advisory = parse_case_planning_response(
        json.dumps(
            {
                "risk_summary": "watch timeout",
                "attention_points": ["band association"],
                "expected_observations": ["readback"],
            }
        )
    )
    assert advisory.risk_summary == "watch timeout"
    assert advisory.attention_points == ("band association",)


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        '{"risk_summary":"x","attention_points":[],"expected_observations":[],"retry":9}',
        '{"risk_summary":"******","attention_points":[],"expected_observations":[]}',
        '{"risk_summary":"x","attention_points":["token: leaked"],"expected_observations":[]}',
        '{"risk_summary":"x","attention_points":["psk=hunter2"],"expected_observations":[]}',
    ],
)
def test_parser_rejects_malformed_unknown_or_secret_like_output(raw):
    with pytest.raises(CasePlanningValidationError):
        parse_case_planning_response(raw)
