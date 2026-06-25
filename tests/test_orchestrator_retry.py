"""Tests for Orchestrator retry-aware timeout escalation (E06).

Verifies _attempt_timeout_seconds() correctly applies exponential backoff
based on attempt index, step count, and execution policy config.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pytest

from testpilot.core.orchestrator import Orchestrator


def _make_orch() -> Orchestrator:
    return Orchestrator(project_root=Path(__file__).resolve().parents[1])


# -- _attempt_timeout_seconds tests --


class TestAttemptTimeoutSeconds:
    """Tests for _attempt_timeout_seconds with various policy configs."""

    def _call(
        self,
        steps_count: int = 3,
        attempt_index: int = 1,
        policy: dict[str, Any] | None = None,
    ) -> float:
        orch = _make_orch()
        if policy is None:
            policy = {}
        return orch._attempt_timeout_seconds(
            steps_count=steps_count,
            attempt_index=attempt_index,
            execution_policy=policy,
        )

    def test_default_policy_first_attempt(self):
        """First attempt with default policy = base + steps * per_step."""
        result = self._call(steps_count=3, attempt_index=1)
        expected = 120.0 + 3 * 45.0  # 255.0
        assert result == pytest.approx(expected)

    def test_default_policy_second_attempt_applies_multiplier(self):
        """Second attempt applies retry_multiplier^1."""
        first = self._call(steps_count=3, attempt_index=1)
        second = self._call(steps_count=3, attempt_index=2)
        assert second == pytest.approx(first * 1.25)

    def test_third_attempt_squares_multiplier(self):
        """Third attempt applies retry_multiplier^2."""
        first = self._call(steps_count=3, attempt_index=1)
        third = self._call(steps_count=3, attempt_index=3)
        assert third == pytest.approx(first * 1.25**2)

    def test_zero_steps_uses_base_only(self):
        """Zero steps → only base_seconds."""
        result = self._call(steps_count=0, attempt_index=1)
        assert result == pytest.approx(120.0)

    def test_negative_steps_clamped_to_zero(self):
        """Negative step count is clamped to zero."""
        result = self._call(steps_count=-5, attempt_index=1)
        assert result == pytest.approx(120.0)

    def test_custom_policy_overrides_defaults(self):
        """Custom timeout config overrides all defaults."""
        policy = {
            "timeout": {
                "base_seconds": 60,
                "per_step_seconds": 10,
                "retry_multiplier": 2.0,
                "max_seconds": 500,
            }
        }
        result = self._call(steps_count=5, attempt_index=1, policy=policy)
        expected = 60.0 + 5 * 10.0  # 110.0
        assert result == pytest.approx(expected)

    def test_max_seconds_caps_result(self):
        """Result is capped at max_seconds."""
        policy = {
            "timeout": {
                "base_seconds": 800,
                "per_step_seconds": 200,
                "retry_multiplier": 1.5,
                "max_seconds": 900,
            }
        }
        result = self._call(steps_count=10, attempt_index=3, policy=policy)
        assert result == pytest.approx(900.0)

    def test_invalid_timeout_config_uses_defaults(self):
        """Non-dict timeout config falls back to defaults."""
        policy = {"timeout": "not_a_dict"}
        result = self._call(steps_count=3, attempt_index=1, policy=policy)
        expected = 120.0 + 3 * 45.0
        assert result == pytest.approx(expected)

    def test_multiplier_never_below_one(self):
        """retry_multiplier < 1 is clamped to 1.0."""
        policy = {"timeout": {"retry_multiplier": 0.5}}
        first = self._call(steps_count=3, attempt_index=1, policy=policy)
        second = self._call(steps_count=3, attempt_index=2, policy=policy)
        assert second == pytest.approx(first)  # multiplier^0 = 1.0 when clamped

    def test_monotonically_increasing_across_attempts(self):
        """Timeout increases (or stays equal) across attempts."""
        timeouts = [self._call(steps_count=5, attempt_index=i) for i in range(1, 6)]
        for i in range(1, len(timeouts)):
            assert timeouts[i] >= timeouts[i - 1]


# -- _safe_int / _safe_float tests --


class TestSafeConversions:
    """Edge cases for _safe_int and _safe_float."""

    def test_safe_int_normal(self):
        assert Orchestrator._safe_int(42, 0) == 42
        assert Orchestrator._safe_int("7", 0) == 7

    def test_safe_int_fallback(self):
        assert Orchestrator._safe_int(None, 99) == 99
        assert Orchestrator._safe_int("abc", 99) == 99

    def test_safe_float_normal(self):
        assert Orchestrator._safe_float(3.14, 0.0) == pytest.approx(3.14)
        assert Orchestrator._safe_float("2.5", 0.0) == pytest.approx(2.5)

    def test_safe_float_fallback(self):
        assert Orchestrator._safe_float(None, 1.0) == pytest.approx(1.0)
        assert Orchestrator._safe_float("xyz", 1.0) == pytest.approx(1.0)
