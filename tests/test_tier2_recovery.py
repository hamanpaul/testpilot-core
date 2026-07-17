"""Tier-2 env-recovery prompt and schema contract tests."""

from __future__ import annotations

import json

import pytest

from testpilot.core.tier2_recovery import (
    Tier2Capability,
    Tier2PlanValidationError,
    Tier2RecoveryAudit,
    Tier2RecoveryContext,
    build_tier2_prompt,
    parse_tier2_plan,
)


def _schemas() -> dict[str, dict]:
    return {
        item["executor_key"]: item["params_schema"]
        for item in _context()["capabilities"]
    }


def _context() -> dict:
    return {
        "diagnosis": "environment readiness probe failed",
        "log_excerpt": ["probe rc=1"],
        "capabilities": [
            {
                "executor_key": "env_command",
                "description": "run a plugin-owned environment repair command",
                "execution_boundary": "isolated target environment transport",
                "params_schema": {"command": "string"},
            },
            {
                "executor_key": "service_restart",
                "description": "restart one environment service",
                "execution_boundary": "plugin-owned service controller",
                "params_schema": {"service": "string"},
            },
        ],
        "verify_env_definition": "all deterministic readiness probes pass",
    }


def test_context_normalizes_capability_catalog() -> None:
    context = Tier2RecoveryContext.from_mapping(_context())

    assert context.allowed_executor_keys == {
        "env_command",
        "service_restart",
    }
    assert context.to_dict()["capabilities"][0]["executor_key"] == "env_command"


def test_context_rejects_control_plane_fields_in_capability_schema() -> None:
    raw = _context()
    raw["capabilities"][0]["params_schema"] = {"pass_criteria": "string"}

    with pytest.raises(ValueError, match="forbidden control-plane field"):
        Tier2RecoveryContext.from_mapping(raw)


def test_context_requires_declared_execution_boundary() -> None:
    raw = _context()
    del raw["capabilities"][0]["execution_boundary"]

    with pytest.raises(ValueError, match="execution_boundary"):
        Tier2RecoveryContext.from_mapping(raw)


def test_prompt_is_bounded_and_redacts_common_secrets() -> None:
    context = _context()
    context["diagnosis"] = (
        "api_key=top-secret password: hunter2 credential=credential-secret"
    )
    context["log_excerpt"] = [
        "Authorization: Bearer abcdef",
        "token=secret-token",
        "x" * 4_000,
    ] * 30

    prompt = build_tier2_prompt(
        context=context,
        failure={
            "category": "environment",
            "reason_code": "not_ready",
            "output": "password=output-secret",
        },
        tier1_failures=2,
    )

    assert "top-secret" not in prompt
    assert "hunter2" not in prompt
    assert "abcdef" not in prompt
    assert "secret-token" not in prompt
    assert "output-secret" not in prompt
    assert "credential-secret" not in prompt
    assert "[REDACTED]" in prompt
    assert len(prompt) < 40_000
    assert "test steps" in prompt
    assert '"executor_key"' in prompt


def test_prompt_renormalizes_direct_context_instances() -> None:
    context = Tier2RecoveryContext(
        diagnosis="password=direct-secret",
        log_excerpt=("Authorization: Basic basic-secret",),
        capabilities=(
            Tier2Capability(
                executor_key="env_command",
                description="environment repair",
                execution_boundary="isolated target environment transport",
                params_schema={"command": "string"},
            ),
        ),
        verify_env_definition="token=verify-secret",
    )

    prompt = build_tier2_prompt(
        context=context,
        failure={"category": "environment"},
        tier1_failures=2,
    )

    assert "direct-secret" not in prompt
    assert "basic-secret" not in prompt
    assert "verify-secret" not in prompt
    assert prompt.count("[REDACTED]") >= 3


def test_parse_plan_accepts_plain_json_and_marks_tier2_actions() -> None:
    raw = json.dumps(
        {
            "summary": "repair the environment",
            "rationale": "the readiness service is stopped",
            "actions": [
                {
                    "executor_key": "service_restart",
                    "description": "restart readiness service",
                    "params": {"service": "readiness"},
                }
            ],
        }
    )

    plan = parse_tier2_plan(
        raw,
        capability_schemas=_schemas(),
        max_actions=3,
    )

    assert plan["summary"] == "repair the environment"
    assert plan["rationale"] == "the readiness service is stopped"
    assert plan["source"] == "tier2-agent"
    assert plan["schema_validated"] is True
    assert "approved" not in plan
    assert plan["actions"] == [
        {
            "executor_key": "service_restart",
            "description": "restart readiness service",
            "device": "",
            "band": "",
            "params": {"service": "readiness"},
            "safety_class": "tier2_env",
            "source": "tier2-agent",
        }
    ]


def test_parse_plan_accepts_one_fenced_json_object() -> None:
    plan = parse_tier2_plan(
        """```json
{"summary":"repair","actions":[{"executor_key":"env_command","params":{"command":"repair"}}]}
```""",
        capability_schemas={"env_command": {"command": "string"}},
        max_actions=1,
    )

    assert plan["actions"][0]["executor_key"] == "env_command"


def test_parse_plan_rejects_oversized_response() -> None:
    raw = json.dumps(
        {
            "summary": "x" * 70_000,
            "actions": [{"executor_key": "env_command"}],
        }
    )

    with pytest.raises(Tier2PlanValidationError, match="response size limit"):
        parse_tier2_plan(
            raw,
            capability_schemas={"env_command": {}},
            max_actions=1,
        )


@pytest.mark.parametrize(
    "params,match",
    [
        ({"unknown": "value"}, "outside capability schema"),
        ({"service": 7}, "must be string"),
    ],
)
def test_parse_plan_validates_capability_param_schema(
    params: dict,
    match: str,
) -> None:
    raw = json.dumps(
        {
            "summary": "repair",
            "actions": [
                {
                    "executor_key": "service_restart",
                    "params": params,
                }
            ],
        }
    )

    with pytest.raises(Tier2PlanValidationError, match=match):
        parse_tier2_plan(
            raw,
            capability_schemas={"service_restart": {"service": "string"}},
            max_actions=1,
        )


def test_parse_plan_rejects_non_positive_action_budget() -> None:
    raw = json.dumps(
        {
            "summary": "repair",
            "actions": [{"executor_key": "env_command"}],
        }
    )

    with pytest.raises(Tier2PlanValidationError, match="action budget must be positive"):
        parse_tier2_plan(
            raw,
            capability_schemas={"env_command": {}},
            max_actions=0,
        )


def test_parse_plan_rejects_max_length_for_scalar_schema() -> None:
    raw = json.dumps(
        {
            "summary": "repair",
            "actions": [
                {"executor_key": "set_retry", "params": {"count": 2}}
            ],
        }
    )

    with pytest.raises(Tier2PlanValidationError, match="max_length"):
        parse_tier2_plan(
            raw,
            capability_schemas={
                "set_retry": {"count": {"type": "integer", "max_length": 4}}
            },
            max_actions=1,
        )


def test_parse_plan_rejects_oversized_executable_param_instead_of_truncating() -> None:
    raw = json.dumps(
        {
            "summary": "repair",
            "actions": [
                {
                    "executor_key": "target_env_shell",
                    "params": {"command": "x" * 1_001},
                }
            ],
        }
    )

    with pytest.raises(Tier2PlanValidationError, match="length limit"):
        parse_tier2_plan(
            raw,
            capability_schemas={"target_env_shell": {"command": "string"}},
            max_actions=1,
        )


def test_parse_plan_rejects_non_boolean_required_schema_flag() -> None:
    raw = json.dumps(
        {
            "summary": "repair",
            "actions": [{"executor_key": "service_restart", "params": {}}],
        }
    )

    with pytest.raises(Tier2PlanValidationError, match="required must be boolean"):
        parse_tier2_plan(
            raw,
            capability_schemas={
                "service_restart": {
                    "service": {"type": "string", "required": "yes"}
                }
            },
            max_actions=1,
        )


def test_parse_plan_rejects_non_finite_json_numbers() -> None:
    raw = (
        '{"summary":"repair","actions":['
        '{"executor_key":"set_ratio","params":{"ratio":NaN}}]}'
    )

    with pytest.raises(Tier2PlanValidationError, match="valid JSON object"):
        parse_tier2_plan(
            raw,
            capability_schemas={"set_ratio": {"ratio": "number"}},
            max_actions=1,
        )


@pytest.mark.parametrize(
    "raw,match",
    [
        (
            '{"summary":"bad","actions":[{"executor_key":"rewrite_case"}]}',
            "outside plugin capability catalog",
        ),
        (
            '{"summary":"bad","actions":['
            '{"executor_key":"env_command","params":{"verdict":"Pass"}}]}',
            "forbidden control-plane field",
        ),
        (
            '{"summary":"bad","actions":['
            '{"executor_key":"env_command","params":{"password":"secret"}}]}',
            "sensitive material",
        ),
        (
            '{"summary":"too many","actions":['
            '{"executor_key":"env_command"},{"executor_key":"env_command"}]}',
            "action budget",
        ),
        ("not-json", "valid JSON object"),
    ],
)
def test_parse_plan_rejects_unsafe_or_invalid_payloads(raw: str, match: str) -> None:
    with pytest.raises(Tier2PlanValidationError, match=match):
        parse_tier2_plan(
            raw,
            capability_schemas={"env_command": {"command": "string"}},
            max_actions=1,
        )


def test_audit_serializes_empty_and_completed_shapes() -> None:
    context = Tier2RecoveryContext.from_mapping(_context())
    audit = Tier2RecoveryAudit(
        case_id="D001",
        attempt_index=3,
        tier1_failures=2,
        trigger_threshold=2,
        context=context.to_dict(),
        prompt="prompt",
    )

    assert audit.to_dict() == {
        "case_id": "D001",
        "attempt_index": 3,
        "tier1_failures": 2,
        "trigger_threshold": 2,
        "context": context.to_dict(),
        "prompt": "prompt",
        "raw_response": "",
        "plan": None,
        "execution": None,
        "verify_gate": None,
        "status": "pending",
        "error": "",
    }


def test_audit_serialization_redacts_and_bounds_untrusted_fields() -> None:
    audit = Tier2RecoveryAudit(
        case_id="D001",
        attempt_index=3,
        tier1_failures=2,
        trigger_threshold=2,
        context={"password": "context-secret"},
        prompt="Authorization: Basic prompt-secret\n" + "x" * 80_000,
        raw_response='{"token":"response-secret"}',
        execution={"output": "password=execution-secret"},
        error="api_key=error-secret",
    )

    serialized = json.dumps(audit.to_dict())

    for secret in (
        "context-secret",
        "prompt-secret",
        "response-secret",
        "execution-secret",
        "error-secret",
    ):
        assert secret not in serialized
    assert "[REDACTED]" in serialized
    assert len(audit.to_dict()["prompt"]) < 45_000
