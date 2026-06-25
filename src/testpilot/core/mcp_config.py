"""Selective MCP server configuration for per-plugin/role Copilot SDK integration.

Each :class:`MCPServerConfig` describes a single MCP server (command, args,
env, role restrictions).  :class:`MCPRegistry` aggregates them and can
produce the ``mcp_servers`` mapping expected by
:class:`~testpilot.core.copilot_session.CopilotSessionRequest`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class MCPServerConfig:
    """Configuration for a single MCP server."""

    name: str
    command: str
    args: tuple[str, ...] = ()
    env: Mapping[str, str] = field(default_factory=dict)
    enabled: bool = True
    roles: frozenset[str] = frozenset()  # empty = available to all roles


class MCPRegistry:
    """Manage MCP server configurations with role-based filtering."""

    def __init__(self) -> None:
        self._servers: dict[str, MCPServerConfig] = {}

    def register(self, config: MCPServerConfig) -> None:
        """Register an MCP server configuration."""
        self._servers[config.name] = config

    def get(self, name: str) -> MCPServerConfig | None:
        """Get server config by name."""
        return self._servers.get(name)

    def for_role(self, role_name: str) -> list[MCPServerConfig]:
        """Get enabled MCP servers available to a specific role.

        A server is included when it is enabled **and** either has no role
        restriction (empty ``roles``) or *role_name* appears in its ``roles``
        set.
        """
        return [
            cfg
            for cfg in self._servers.values()
            if cfg.enabled and (not cfg.roles or role_name in cfg.roles)
        ]

    def to_session_config(self, role_name: str = "") -> dict[str, Any]:
        """Build ``mcp_servers`` dict for :class:`CopilotSessionRequest`.

        Returns a mapping keyed by server name.  Each value contains
        ``command``, ``args``, and ``env``.
        """
        servers = self.for_role(role_name) if role_name else [
            cfg for cfg in self._servers.values() if cfg.enabled
        ]
        result: dict[str, Any] = {}
        for cfg in servers:
            entry: dict[str, Any] = {"command": cfg.command}
            if cfg.args:
                entry["args"] = list(cfg.args)
            if cfg.env:
                entry["env"] = dict(cfg.env)
            result[cfg.name] = entry
        return result

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> MCPRegistry:
        """Load MCP config from ``agent-config.yaml`` ``mcp_servers`` section.

        Expected shape::

            mcp_servers:
              device-broker:
                command: device-broker-mcp
                args: ["--broker", "unix:///tmp/sw.sock"]
                env:
                  SW_LOG_LEVEL: debug
                enabled: true
                roles: [executor]
        """
        registry = cls()
        for name, entry in raw.items():
            if not isinstance(entry, dict):
                continue

            args_raw = entry.get("args", ())
            args = tuple(str(a) for a in args_raw) if args_raw else ()

            env_raw = entry.get("env", {})
            env: dict[str, str] = (
                {str(k): str(v) for k, v in env_raw.items()}
                if isinstance(env_raw, dict)
                else {}
            )

            roles_raw = entry.get("roles", ())
            roles = (
                frozenset(str(r) for r in roles_raw)
                if roles_raw
                else frozenset()
            )

            registry.register(
                MCPServerConfig(
                    name=name,
                    command=str(entry.get("command", "")),
                    args=args,
                    env=env,
                    enabled=bool(entry.get("enabled", True)),
                    roles=roles,
                )
            )
        return registry

    @property
    def all_servers(self) -> list[MCPServerConfig]:
        """All registered servers (including disabled ones)."""
        return list(self._servers.values())
