"""Tests for testpilot.core.agent_roles."""

from __future__ import annotations

from testpilot.core.agent_roles import (
    BUILTIN_ROLES,
    AgentRole,
    load_agent_roles,
    roles_to_hook_policy,
)


# -- BUILTIN_ROLES -----------------------------------------------------------

def test_builtin_roles_expected_keys() -> None:
    assert set(BUILTIN_ROLES.keys()) == {"executor", "advisor", "remediation", "observer"}


def test_executor_hooks() -> None:
    assert BUILTIN_ROLES["executor"].hooks == frozenset({"pre_case", "post_case"})


def test_advisor_hooks() -> None:
    assert BUILTIN_ROLES["advisor"].hooks == frozenset({"on_failure", "post_case"})


def test_remediation_hooks() -> None:
    assert BUILTIN_ROLES["remediation"].hooks == frozenset({"on_failure", "on_retry"})


def test_observer_hooks() -> None:
    assert BUILTIN_ROLES["observer"].hooks == frozenset(
        {"pre_case", "post_case", "pre_step", "post_step", "on_failure", "on_retry"}
    )


# -- load_agent_roles ---------------------------------------------------------

def test_load_agent_roles_empty_config_returns_builtins() -> None:
    roles = load_agent_roles({})
    assert roles == BUILTIN_ROLES


def test_load_agent_roles_custom_role_merges() -> None:
    config = {
        "roles": [
            {
                "name": "debugger",
                "description": "Debug helper",
                "hooks": ["on_failure"],
                "model": "gpt-5.4",
                "tools": ["bash", "view"],
            }
        ]
    }
    roles = load_agent_roles(config)
    assert "debugger" in roles
    assert roles["debugger"].hooks == frozenset({"on_failure"})
    assert roles["debugger"].model == "gpt-5.4"
    assert roles["debugger"].tools == ("bash", "view")
    # builtins still present
    for key in BUILTIN_ROLES:
        assert key in roles


def test_load_agent_roles_override_builtin() -> None:
    config = {
        "roles": [
            {
                "name": "executor",
                "description": "Custom executor",
                "hooks": ["pre_case", "post_case", "pre_step"],
                "model": "sonnet-4.6",
            }
        ]
    }
    roles = load_agent_roles(config)
    assert roles["executor"].description == "Custom executor"
    assert roles["executor"].hooks == frozenset({"pre_case", "post_case", "pre_step"})
    assert roles["executor"].model == "sonnet-4.6"


# -- roles_to_hook_policy -----------------------------------------------------

def test_roles_to_hook_policy_correct_hooks() -> None:
    roles = load_agent_roles({})
    policy = roles_to_hook_policy(["executor", "remediation"], roles)
    expected = {"pre_case", "post_case", "on_failure", "on_retry"}
    assert policy.enabled_hooks == expected


def test_roles_to_hook_policy_empty_roles_returns_disabled() -> None:
    roles = load_agent_roles({})
    policy = roles_to_hook_policy([], roles)
    assert policy.enabled_hooks == set()
    assert policy.fail_open is True


def test_roles_to_hook_policy_unknown_role_skipped() -> None:
    roles = load_agent_roles({})
    policy = roles_to_hook_policy(["nonexistent"], roles)
    assert policy.enabled_hooks == set()
