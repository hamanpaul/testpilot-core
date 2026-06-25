"""Hook policy layer — lifecycle hooks for SDK/agent integration.

Defines hook points in the execution lifecycle where external agents
(Copilot SDK, custom runners) can intercept, observe, or modify behavior.

Hook points:
- ``pre_case``   — before any attempt starts for a case
- ``post_case``  — after all attempts complete for a case
- ``pre_step``   — before each step executes
- ``post_step``  — after each step executes (receives result)
- ``on_failure`` — when a step or case fails (for advisory/remediation)
- ``on_retry``   — before a retry attempt starts
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, runtime_checkable

log = logging.getLogger(__name__)


# -- Hook context dataclasses ------------------------------------------------

@dataclass(slots=True)
class HookContext:
    """Immutable snapshot passed to every hook invocation."""

    hook_name: str
    case_id: str
    plugin_name: str
    attempt_index: int = 1
    step_id: str | None = None
    runner: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class HookResult:
    """Value returned from a hook; controls execution flow."""

    proceed: bool = True
    modified_data: dict[str, Any] | None = None
    advice: str = ""


# -- Hook protocol -----------------------------------------------------------

@runtime_checkable
class IHook(Protocol):
    """Protocol for hook implementations."""

    def __call__(self, ctx: HookContext, data: dict[str, Any]) -> HookResult: ...


# -- Hook policy configuration -----------------------------------------------

@dataclass(slots=True)
class HookPolicyConfig:
    """Configuration for which hooks are enabled and their constraints."""

    enabled_hooks: set[str] = field(default_factory=lambda: set())
    timeout_seconds: float = 30.0
    fail_open: bool = True

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> HookPolicyConfig:
        hooks = raw.get("enabled_hooks", [])
        if isinstance(hooks, str):
            hooks = [h.strip() for h in hooks.split(",") if h.strip()]
        return cls(
            enabled_hooks=set(hooks) if hooks else set(),
            timeout_seconds=float(raw.get("timeout_seconds", 30.0)),
            fail_open=bool(raw.get("fail_open", True)),
        )

    @classmethod
    def disabled(cls) -> HookPolicyConfig:
        return cls(enabled_hooks=set(), fail_open=True)

    def is_enabled(self, hook_name: str) -> bool:
        return hook_name in self.enabled_hooks


ALL_HOOK_NAMES = frozenset({
    "pre_case", "post_case",
    "pre_step", "post_step",
    "on_failure", "on_retry",
})


# -- Hook dispatcher ---------------------------------------------------------

class HookDispatcher:
    """Registry and dispatcher for lifecycle hooks.

    Hooks are registered per hook-point name.  When ``dispatch()`` is called,
    all registered hooks for that point run sequentially.  If any hook raises
    and ``fail_open`` is True, the error is logged and execution continues.
    """

    def __init__(self, policy: HookPolicyConfig | None = None) -> None:
        self.policy = policy or HookPolicyConfig.disabled()
        self._hooks: dict[str, list[Callable[[HookContext, dict[str, Any]], HookResult]]] = {}

    def register(self, hook_name: str, handler: Callable[[HookContext, dict[str, Any]], HookResult]) -> None:
        """Register a handler for a hook point."""
        if hook_name not in ALL_HOOK_NAMES:
            log.warning("unknown hook name: %s (valid: %s)", hook_name, sorted(ALL_HOOK_NAMES))
        self._hooks.setdefault(hook_name, []).append(handler)

    def dispatch(self, ctx: HookContext, data: dict[str, Any]) -> HookResult:
        """Fire all registered handlers for ``ctx.hook_name``.

        Returns the last non-default HookResult, or a default proceed=True.
        """
        hook_name = ctx.hook_name
        if not self.policy.is_enabled(hook_name):
            return HookResult()

        handlers = self._hooks.get(hook_name, [])
        if not handlers:
            return HookResult()

        last_result = HookResult()
        for handler in handlers:
            try:
                result = handler(ctx, data)
                if result is not None:
                    last_result = result
                    if not result.proceed:
                        log.info("hook %s halted execution: %s", hook_name, result.advice)
                        return result
            except Exception as exc:
                if self.policy.fail_open:
                    log.warning("hook %s failed (fail_open=True): %s", hook_name, exc)
                else:
                    log.error("hook %s failed (fail_open=False): %s", hook_name, exc)
                    return HookResult(proceed=False, advice=f"hook error: {exc}")

        return last_result

    @property
    def registered_hooks(self) -> dict[str, int]:
        """Return a summary of registered hook counts."""
        return {name: len(handlers) for name, handlers in self._hooks.items() if handlers}


def build_hook_policy(agent_config: dict[str, Any]) -> HookPolicyConfig:
    """Build a HookPolicyConfig from agent-config.yaml content."""
    hooks_raw = agent_config.get("hooks", {})
    if not isinstance(hooks_raw, dict):
        return HookPolicyConfig.disabled()
    return HookPolicyConfig.from_dict(hooks_raw)
