"""Agent runtime config parser and runner selector."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml

DEFAULT_SCOPE = "per_case"
DEFAULT_MODE = "sequential"
DEFAULT_MAX_CONCURRENCY = 1
DEFAULT_FAILURE_POLICY = "retry_then_fail_and_continue"
DEFAULT_RETRY_MAX_ATTEMPTS = 2
DEFAULT_RETRY_BACKOFF_SECONDS = 5.0
DEFAULT_TIMEOUT_BASE_SECONDS = 120.0
DEFAULT_TIMEOUT_PER_STEP_SECONDS = 45.0
DEFAULT_TIMEOUT_RETRY_MULTIPLIER = 1.25
DEFAULT_TIMEOUT_MAX_SECONDS = 900.0


@dataclass(frozen=True)
class SelectionPolicy:
    fallback: str = "automatic"
    on_unavailable: str = "next_priority"


@dataclass(frozen=True)
class RetryConfig:
    max_attempts: int = DEFAULT_RETRY_MAX_ATTEMPTS
    backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS


@dataclass(frozen=True)
class TimeoutConfig:
    base_seconds: float = DEFAULT_TIMEOUT_BASE_SECONDS
    per_step_seconds: float = DEFAULT_TIMEOUT_PER_STEP_SECONDS
    retry_multiplier: float = DEFAULT_TIMEOUT_RETRY_MULTIPLIER
    max_seconds: float = DEFAULT_TIMEOUT_MAX_SECONDS


@dataclass(frozen=True)
class ExecutionConfig:
    scope: str = DEFAULT_SCOPE
    mode: str = DEFAULT_MODE
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY
    failure_policy: str = DEFAULT_FAILURE_POLICY
    retry: RetryConfig = field(default_factory=RetryConfig)
    timeout: TimeoutConfig = field(default_factory=TimeoutConfig)


@dataclass(frozen=True)
class RunnerConfig:
    priority: int
    cli_agent: str
    model: str
    effort: str
    enabled: bool = True

    @property
    def key(self) -> str:
        return f"{self.cli_agent}:{self.model}"


@dataclass(frozen=True)
class AgentRuntimeConfig:
    version: int
    default_mode: str
    selection_policy: SelectionPolicy
    execution: ExecutionConfig
    runners: list[RunnerConfig]


@dataclass(frozen=True)
class SelectionTraceItem:
    priority: int
    cli_agent: str
    model: str
    status: str
    unavailable_reason: str | None = None


@dataclass(frozen=True)
class RunnerSelection:
    runner: RunnerConfig | None
    trace: list[SelectionTraceItem]


def _ensure_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    return {}


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_bool(value: Any, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return bool(value)


def parse_agent_runtime_config(raw: Mapping[str, Any]) -> AgentRuntimeConfig:
    """Parse raw agent-config YAML mapping into typed runtime config."""
    selection_raw = _ensure_mapping(raw.get("selection_policy"))
    execution_raw = _ensure_mapping(raw.get("execution"))
    retry_raw = _ensure_mapping(execution_raw.get("retry"))
    timeout_raw = _ensure_mapping(execution_raw.get("timeout"))

    selection_policy = SelectionPolicy(
        fallback=str(selection_raw.get("fallback", "automatic")),
        on_unavailable=str(selection_raw.get("on_unavailable", "next_priority")),
    )

    retry = RetryConfig(
        max_attempts=max(1, _as_int(retry_raw.get("max_attempts"), DEFAULT_RETRY_MAX_ATTEMPTS)),
        backoff_seconds=max(
            0.0,
            _as_float(retry_raw.get("backoff_seconds"), DEFAULT_RETRY_BACKOFF_SECONDS),
        ),
    )
    timeout = TimeoutConfig(
        base_seconds=max(
            0.0,
            _as_float(timeout_raw.get("base_seconds"), DEFAULT_TIMEOUT_BASE_SECONDS),
        ),
        per_step_seconds=max(
            0.0,
            _as_float(timeout_raw.get("per_step_seconds"), DEFAULT_TIMEOUT_PER_STEP_SECONDS),
        ),
        retry_multiplier=max(
            0.0,
            _as_float(
                timeout_raw.get("retry_multiplier"),
                DEFAULT_TIMEOUT_RETRY_MULTIPLIER,
            ),
        ),
        max_seconds=max(
            0.0,
            _as_float(timeout_raw.get("max_seconds"), DEFAULT_TIMEOUT_MAX_SECONDS),
        ),
    )
    execution = ExecutionConfig(
        scope=str(execution_raw.get("scope", DEFAULT_SCOPE)),
        mode=str(execution_raw.get("mode", DEFAULT_MODE)),
        max_concurrency=max(
            1,
            _as_int(execution_raw.get("max_concurrency"), DEFAULT_MAX_CONCURRENCY),
        ),
        failure_policy=str(
            execution_raw.get("failure_policy", DEFAULT_FAILURE_POLICY)
        ),
        retry=retry,
        timeout=timeout,
    )

    runners: list[RunnerConfig] = []
    raw_runners = raw.get("runners")
    if isinstance(raw_runners, list):
        for index, item in enumerate(raw_runners):
            if not isinstance(item, Mapping):
                continue
            cli_agent = str(item.get("cli_agent", "")).strip()
            model = str(item.get("model", "")).strip()
            effort = str(item.get("effort", "high")).strip() or "high"
            if not cli_agent or not model:
                continue
            runners.append(
                RunnerConfig(
                    priority=_as_int(item.get("priority"), index + 1),
                    cli_agent=cli_agent,
                    model=model,
                    effort=effort,
                    enabled=_as_bool(item.get("enabled"), True),
                )
            )
    runners.sort(key=lambda x: x.priority)

    return AgentRuntimeConfig(
        version=_as_int(raw.get("version"), 1),
        default_mode=str(raw.get("default_mode", "headless")),
        selection_policy=selection_policy,
        execution=execution,
        runners=runners,
    )


def load_agent_runtime_config(plugin_dir: Path | str) -> AgentRuntimeConfig:
    """Load plugins/<plugin>/agent-config.yaml and return parsed runtime config."""
    config_path = Path(plugin_dir) / "agent-config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        loaded = yaml.safe_load(f)
    if loaded is None:
        loaded = {}
    if not isinstance(loaded, Mapping):
        raise TypeError(f"agent-config must be a mapping: {config_path}")
    return parse_agent_runtime_config(loaded)


def _availability_reason(
    runner: RunnerConfig,
    availability: Mapping[str, str | bool] | None,
) -> str | None:
    if availability is None:
        return None

    for key in (runner.key, runner.cli_agent):
        if key not in availability:
            continue
        status = availability[key]
        if status is True:
            return None
        if status is False:
            return "reported_unavailable"
        reason = str(status).strip()
        return reason or "reported_unavailable"
    return None


def select_runner(
    config: AgentRuntimeConfig,
    availability: Mapping[str, str | bool] | None = None,
) -> RunnerSelection:
    """Select runner by priority and fallback policy, with selection trace."""
    trace: list[SelectionTraceItem] = []
    can_fallback = (
        config.selection_policy.fallback == "automatic"
        and config.selection_policy.on_unavailable == "next_priority"
    )

    for runner in config.runners:
        unavailable_reason: str | None = None
        if not runner.enabled:
            unavailable_reason = "disabled"

        external_reason = _availability_reason(runner, availability)
        if external_reason:
            unavailable_reason = (
                external_reason
                if unavailable_reason is None
                else f"{unavailable_reason}; {external_reason}"
            )

        if unavailable_reason:
            trace.append(
                SelectionTraceItem(
                    priority=runner.priority,
                    cli_agent=runner.cli_agent,
                    model=runner.model,
                    status="unavailable",
                    unavailable_reason=unavailable_reason,
                )
            )
            if not can_fallback:
                break
            continue

        trace.append(
            SelectionTraceItem(
                priority=runner.priority,
                cli_agent=runner.cli_agent,
                model=runner.model,
                status="selected",
                unavailable_reason=None,
            )
        )
        return RunnerSelection(runner=runner, trace=trace)

    return RunnerSelection(runner=None, trace=trace)


def calculate_attempt_timeout(
    timeout: TimeoutConfig,
    *,
    steps_count: int,
    attempt_index: int,
) -> float:
    """Calculate retry-aware attempt timeout (attempt_index starts from 1)."""
    if steps_count < 0:
        raise ValueError("steps_count must be >= 0")
    if attempt_index < 1:
        raise ValueError("attempt_index must be >= 1")
    base = timeout.base_seconds + steps_count * timeout.per_step_seconds
    scaled = base * (timeout.retry_multiplier ** (attempt_index - 1))
    return min(timeout.max_seconds, scaled)

