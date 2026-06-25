"""Tests for agent runtime config parser/selector."""

import pytest

from testpilot.core.agent_runtime import (
    TimeoutConfig,
    calculate_attempt_timeout,
    parse_agent_runtime_config,
    select_runner,
)


def test_parse_execution_block():
    cfg = parse_agent_runtime_config(
        {
            "execution": {
                "scope": "per_case",
                "mode": "sequential",
                "max_concurrency": 1,
                "failure_policy": "retry_then_fail_and_continue",
                "retry": {
                    "max_attempts": 3,
                    "backoff_seconds": 8,
                },
                "timeout": {
                    "base_seconds": 100,
                    "per_step_seconds": 30,
                    "retry_multiplier": 1.5,
                    "max_seconds": 400,
                },
            },
            "runners": [
                {
                    "priority": 1,
                    "cli_agent": "copilot",
                    "model": "gpt-5.4",
                    "effort": "high",
                    "enabled": True,
                }
            ],
        }
    )

    assert cfg.execution.scope == "per_case"
    assert cfg.execution.mode == "sequential"
    assert cfg.execution.max_concurrency == 1
    assert cfg.execution.failure_policy == "retry_then_fail_and_continue"
    assert cfg.execution.retry.max_attempts == 3
    assert cfg.execution.retry.backoff_seconds == 8
    assert cfg.execution.timeout.base_seconds == 100
    assert cfg.execution.timeout.per_step_seconds == 30
    assert cfg.execution.timeout.retry_multiplier == 1.5
    assert cfg.execution.timeout.max_seconds == 400


def test_select_runner_fallback_with_unavailable_reason():
    cfg = parse_agent_runtime_config(
        {
            "selection_policy": {
                "fallback": "automatic",
                "on_unavailable": "next_priority",
            },
            "runners": [
                {
                    "priority": 1,
                    "cli_agent": "copilot",
                    "model": "gpt-5.4",
                    "effort": "high",
                    "enabled": True,
                },
                {
                    "priority": 2,
                    "cli_agent": "copilot",
                    "model": "sonnet-4.6",
                    "effort": "high",
                    "enabled": True,
                },
            ],
        }
    )

    selected = select_runner(
        cfg,
        availability={"copilot:gpt-5.4": "binary_not_found"},
    )

    assert selected.runner is not None
    assert selected.runner.cli_agent == "copilot"
    assert len(selected.trace) == 2
    assert selected.trace[0].status == "unavailable"
    assert selected.trace[0].unavailable_reason == "binary_not_found"
    assert selected.trace[1].status == "selected"


def test_select_runner_skips_disabled_runner():
    cfg = parse_agent_runtime_config(
        {
            "runners": [
                {
                    "priority": 1,
                    "cli_agent": "copilot",
                    "model": "gpt-5.4",
                    "effort": "high",
                    "enabled": False,
                },
                {
                    "priority": 2,
                    "cli_agent": "copilot",
                    "model": "sonnet-4.6",
                    "effort": "high",
                    "enabled": True,
                },
            ]
        }
    )

    selected = select_runner(cfg)

    assert selected.runner is not None
    assert selected.runner.cli_agent == "copilot"
    assert selected.runner.model == "sonnet-4.6"
    assert len(selected.trace) == 2
    assert selected.trace[0].status == "unavailable"
    assert selected.trace[0].unavailable_reason == "disabled"
    assert selected.trace[1].status == "selected"


def test_calculate_attempt_timeout_with_cap():
    timeout = TimeoutConfig(
        base_seconds=120,
        per_step_seconds=45,
        retry_multiplier=1.25,
        max_seconds=300,
    )

    assert calculate_attempt_timeout(timeout, steps_count=2, attempt_index=1) == pytest.approx(210)
    assert calculate_attempt_timeout(timeout, steps_count=2, attempt_index=2) == pytest.approx(262.5)
    assert calculate_attempt_timeout(timeout, steps_count=2, attempt_index=4) == pytest.approx(300)
