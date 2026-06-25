"""Agent role definitions for per-plugin Copilot SDK integration.

Each :class:`AgentRole` declares which lifecycle hooks the role participates
in, its preferred model/effort, and optional system prompt and tool lists.
Built-in roles cover common patterns; plugins may extend or override them
via the ``roles`` key in their ``agent-config.yaml``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from testpilot.core.hook_policy import HookPolicyConfig


@dataclass(frozen=True)
class AgentRole:
    """Immutable descriptor for an agent role."""

    name: str
    description: str
    hooks: frozenset[str]
    model: str = ""
    reasoning_effort: str = "high"
    system_prompt: str = ""
    tools: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()


# -- Built-in roles ----------------------------------------------------------

BUILTIN_ROLES: dict[str, AgentRole] = {
    "executor": AgentRole(
        name="executor",
        description="Primary test executor \u2014 runs steps and collects results",
        hooks=frozenset({"pre_case", "post_case"}),
    ),
    "advisor": AgentRole(
        name="advisor",
        description="Advisory agent \u2014 provides analysis on failures",
        hooks=frozenset({"on_failure", "post_case"}),
    ),
    "remediation": AgentRole(
        name="remediation",
        description="Remediation planner \u2014 suggests fixes for persistent failures",
        hooks=frozenset({"on_failure", "on_retry"}),
    ),
    "observer": AgentRole(
        name="observer",
        description="Passive observer \u2014 logs all lifecycle events",
        hooks=frozenset({"pre_case", "post_case", "pre_step", "post_step", "on_failure", "on_retry"}),
    ),
}


# -- Loader -------------------------------------------------------------------

def load_agent_roles(agent_config: dict[str, Any]) -> dict[str, AgentRole]:
    """Merge built-in roles with custom roles from agent config.

    Custom roles defined under the ``roles`` key in *agent_config* are added
    to (or override) the built-in set.  Each entry must be a mapping with at
    least ``name`` and ``hooks``.
    """
    roles: dict[str, AgentRole] = dict(BUILTIN_ROLES)

    raw_roles = agent_config.get("roles")
    if not isinstance(raw_roles, list):
        return roles

    for entry in raw_roles:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "")).strip()
        if not name:
            continue

        hooks_raw = entry.get("hooks", [])
        if isinstance(hooks_raw, str):
            hooks_raw = [h.strip() for h in hooks_raw.split(",") if h.strip()]
        hooks = frozenset(str(h) for h in hooks_raw) if hooks_raw else frozenset()

        tools_raw = entry.get("tools", ())
        tools = tuple(str(t) for t in tools_raw) if tools_raw else ()

        skills_raw = entry.get("skills", ())
        skills = tuple(str(s) for s in skills_raw) if skills_raw else ()

        roles[name] = AgentRole(
            name=name,
            description=str(entry.get("description", "")),
            hooks=hooks,
            model=str(entry.get("model", "")),
            reasoning_effort=str(entry.get("reasoning_effort", "high")),
            system_prompt=str(entry.get("system_prompt", "")),
            tools=tools,
            skills=skills,
        )

    return roles


# -- Policy bridge ------------------------------------------------------------

def roles_to_hook_policy(
    active_roles: Sequence[str],
    all_roles: dict[str, AgentRole],
) -> HookPolicyConfig:
    """Build a :class:`HookPolicyConfig` from a set of active role names.

    The enabled hooks are the union of hooks declared by all *active_roles*.
    Roles not found in *all_roles* are silently skipped.  If no valid roles
    are supplied, a disabled policy is returned.
    """
    enabled: set[str] = set()
    for role_name in active_roles:
        role = all_roles.get(role_name)
        if role is not None:
            enabled |= role.hooks

    if not enabled:
        return HookPolicyConfig.disabled()

    return HookPolicyConfig(enabled_hooks=enabled)
