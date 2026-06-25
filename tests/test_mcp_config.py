"""Tests for testpilot.core.mcp_config."""

from __future__ import annotations

from testpilot.core.mcp_config import MCPRegistry, MCPServerConfig


# -- MCPServerConfig creation -------------------------------------------------

def test_config_defaults() -> None:
    cfg = MCPServerConfig(name="sw", command="serialwrap-mcp")
    assert cfg.name == "sw"
    assert cfg.command == "serialwrap-mcp"
    assert cfg.args == ()
    assert cfg.env == {}
    assert cfg.enabled is True
    assert cfg.roles == frozenset()


def test_config_full_construction() -> None:
    cfg = MCPServerConfig(
        name="db",
        command="db-mcp",
        args=("--host", "localhost"),
        env={"DB_PORT": "5432"},
        enabled=False,
        roles=frozenset({"advisor"}),
    )
    assert cfg.args == ("--host", "localhost")
    assert cfg.env == {"DB_PORT": "5432"}
    assert cfg.enabled is False
    assert cfg.roles == frozenset({"advisor"})


def test_config_is_frozen() -> None:
    cfg = MCPServerConfig(name="x", command="x")
    try:
        cfg.name = "y"  # type: ignore[misc]
        raise AssertionError("Should have raised FrozenInstanceError")
    except AttributeError:
        pass


# -- register / get -----------------------------------------------------------

def test_register_and_get() -> None:
    reg = MCPRegistry()
    cfg = MCPServerConfig(name="sw", command="serialwrap-mcp")
    reg.register(cfg)
    assert reg.get("sw") is cfg


def test_get_missing_returns_none() -> None:
    reg = MCPRegistry()
    assert reg.get("nonexistent") is None


def test_register_overwrites() -> None:
    reg = MCPRegistry()
    cfg1 = MCPServerConfig(name="sw", command="v1")
    cfg2 = MCPServerConfig(name="sw", command="v2")
    reg.register(cfg1)
    reg.register(cfg2)
    assert reg.get("sw") is cfg2


# -- for_role -----------------------------------------------------------------

def test_for_role_unrestricted() -> None:
    reg = MCPRegistry()
    reg.register(MCPServerConfig(name="a", command="a-cmd"))
    result = reg.for_role("executor")
    assert len(result) == 1
    assert result[0].name == "a"


def test_for_role_restricted_match() -> None:
    reg = MCPRegistry()
    reg.register(MCPServerConfig(name="a", command="a", roles=frozenset({"executor"})))
    assert len(reg.for_role("executor")) == 1


def test_for_role_restricted_no_match() -> None:
    reg = MCPRegistry()
    reg.register(MCPServerConfig(name="a", command="a", roles=frozenset({"advisor"})))
    assert reg.for_role("executor") == []


def test_for_role_mixed() -> None:
    reg = MCPRegistry()
    reg.register(MCPServerConfig(name="all", command="all"))
    reg.register(MCPServerConfig(name="exec", command="exec", roles=frozenset({"executor"})))
    reg.register(MCPServerConfig(name="adv", command="adv", roles=frozenset({"advisor"})))
    result = reg.for_role("executor")
    names = {c.name for c in result}
    assert names == {"all", "exec"}


def test_for_role_excludes_disabled() -> None:
    reg = MCPRegistry()
    reg.register(MCPServerConfig(name="on", command="on"))
    reg.register(MCPServerConfig(name="off", command="off", enabled=False))
    result = reg.for_role("executor")
    assert len(result) == 1
    assert result[0].name == "on"


def test_for_role_disabled_even_if_role_matches() -> None:
    reg = MCPRegistry()
    reg.register(
        MCPServerConfig(name="d", command="d", enabled=False, roles=frozenset({"executor"}))
    )
    assert reg.for_role("executor") == []


# -- to_session_config --------------------------------------------------------

def test_to_session_config_basic() -> None:
    reg = MCPRegistry()
    reg.register(MCPServerConfig(name="sw", command="serialwrap-mcp", args=("--broker", "x")))
    out = reg.to_session_config("executor")
    assert out == {"sw": {"command": "serialwrap-mcp", "args": ["--broker", "x"]}}


def test_to_session_config_with_env() -> None:
    reg = MCPRegistry()
    reg.register(MCPServerConfig(name="db", command="db-mcp", env={"K": "V"}))
    out = reg.to_session_config("advisor")
    assert out == {"db": {"command": "db-mcp", "env": {"K": "V"}}}


def test_to_session_config_no_role_returns_all_enabled() -> None:
    reg = MCPRegistry()
    reg.register(MCPServerConfig(name="a", command="a"))
    reg.register(MCPServerConfig(name="b", command="b", enabled=False))
    out = reg.to_session_config()
    assert "a" in out
    assert "b" not in out


def test_to_session_config_filters_by_role() -> None:
    reg = MCPRegistry()
    reg.register(MCPServerConfig(name="e", command="e", roles=frozenset({"executor"})))
    reg.register(MCPServerConfig(name="a", command="a", roles=frozenset({"advisor"})))
    out = reg.to_session_config("executor")
    assert "e" in out
    assert "a" not in out


def test_to_session_config_minimal_entry() -> None:
    """No args/env → entry has only 'command'."""
    reg = MCPRegistry()
    reg.register(MCPServerConfig(name="m", command="m-cmd"))
    out = reg.to_session_config()
    assert out == {"m": {"command": "m-cmd"}}


# -- from_dict ----------------------------------------------------------------

def test_from_dict_basic() -> None:
    raw = {
        "sw": {
            "command": "serialwrap-mcp",
            "args": ["--broker", "unix:///tmp/sw.sock"],
            "env": {"SW_LOG_LEVEL": "debug"},
            "roles": ["executor"],
        },
    }
    reg = MCPRegistry.from_dict(raw)
    cfg = reg.get("sw")
    assert cfg is not None
    assert cfg.command == "serialwrap-mcp"
    assert cfg.args == ("--broker", "unix:///tmp/sw.sock")
    assert cfg.env == {"SW_LOG_LEVEL": "debug"}
    assert cfg.roles == frozenset({"executor"})
    assert cfg.enabled is True


def test_from_dict_disabled() -> None:
    raw = {"x": {"command": "x-cmd", "enabled": False}}
    reg = MCPRegistry.from_dict(raw)
    cfg = reg.get("x")
    assert cfg is not None
    assert cfg.enabled is False


def test_from_dict_empty() -> None:
    reg = MCPRegistry.from_dict({})
    assert reg.all_servers == []


def test_from_dict_skips_non_dict_entries() -> None:
    raw = {"bad": "not-a-dict", "ok": {"command": "ok-cmd"}}
    reg = MCPRegistry.from_dict(raw)
    assert reg.get("bad") is None
    assert reg.get("ok") is not None


def test_from_dict_defaults() -> None:
    raw = {"m": {"command": "m-cmd"}}
    reg = MCPRegistry.from_dict(raw)
    cfg = reg.get("m")
    assert cfg is not None
    assert cfg.args == ()
    assert cfg.env == {}
    assert cfg.roles == frozenset()
    assert cfg.enabled is True


def test_from_dict_multiple_roles() -> None:
    raw = {"s": {"command": "s", "roles": ["executor", "advisor"]}}
    reg = MCPRegistry.from_dict(raw)
    cfg = reg.get("s")
    assert cfg is not None
    assert cfg.roles == frozenset({"executor", "advisor"})


# -- all_servers --------------------------------------------------------------

def test_all_servers_includes_disabled() -> None:
    reg = MCPRegistry()
    reg.register(MCPServerConfig(name="on", command="on"))
    reg.register(MCPServerConfig(name="off", command="off", enabled=False))
    assert len(reg.all_servers) == 2


# -- empty registry -----------------------------------------------------------

def test_empty_registry_for_role() -> None:
    reg = MCPRegistry()
    assert reg.for_role("executor") == []


def test_empty_registry_to_session_config() -> None:
    reg = MCPRegistry()
    assert reg.to_session_config("executor") == {}


def test_empty_registry_all_servers() -> None:
    reg = MCPRegistry()
    assert reg.all_servers == []
