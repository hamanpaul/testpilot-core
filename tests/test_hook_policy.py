"""Tests for hook_policy module."""

from __future__ import annotations

import pytest
from testpilot.core.hook_policy import (
    ALL_HOOK_NAMES,
    HookContext,
    HookDispatcher,
    HookPolicyConfig,
    HookResult,
    IHook,
    build_hook_policy,
)


# -- HookPolicyConfig --------------------------------------------------------

class TestHookPolicyConfig:
    def test_disabled_has_no_hooks(self):
        cfg = HookPolicyConfig.disabled()
        assert cfg.enabled_hooks == set()
        assert cfg.fail_open is True

    def test_from_dict_with_list(self):
        cfg = HookPolicyConfig.from_dict({
            "enabled_hooks": ["pre_case", "post_case"],
            "timeout_seconds": 10.0,
            "fail_open": False,
        })
        assert cfg.enabled_hooks == {"pre_case", "post_case"}
        assert cfg.timeout_seconds == 10.0
        assert cfg.fail_open is False

    def test_from_dict_with_csv_string(self):
        cfg = HookPolicyConfig.from_dict({"enabled_hooks": "pre_step, post_step"})
        assert cfg.enabled_hooks == {"pre_step", "post_step"}

    def test_from_dict_empty(self):
        cfg = HookPolicyConfig.from_dict({})
        assert cfg.enabled_hooks == set()

    def test_is_enabled(self):
        cfg = HookPolicyConfig(enabled_hooks={"pre_case"})
        assert cfg.is_enabled("pre_case") is True
        assert cfg.is_enabled("post_case") is False


class TestBuildHookPolicy:
    def test_from_agent_config(self):
        cfg = build_hook_policy({"hooks": {"enabled_hooks": ["on_failure"]}})
        assert cfg.is_enabled("on_failure")

    def test_missing_hooks_key(self):
        cfg = build_hook_policy({})
        assert cfg.enabled_hooks == set()

    def test_non_dict_hooks(self):
        cfg = build_hook_policy({"hooks": "invalid"})
        assert cfg.enabled_hooks == set()


# -- HookContext --------------------------------------------------------------

class TestHookContext:
    def test_basic_creation(self):
        ctx = HookContext(
            hook_name="pre_case",
            case_id="D001",
            plugin_name="wifi_llapi",
        )
        assert ctx.hook_name == "pre_case"
        assert ctx.case_id == "D001"
        assert ctx.step_id is None
        assert ctx.attempt_index == 1


# -- HookDispatcher ----------------------------------------------------------

class TestHookDispatcher:
    def test_dispatch_disabled_hook_returns_default(self):
        dispatcher = HookDispatcher(HookPolicyConfig.disabled())
        ctx = HookContext(hook_name="pre_case", case_id="X", plugin_name="test")
        result = dispatcher.dispatch(ctx, {})
        assert result.proceed is True

    def test_dispatch_enabled_hook_fires(self):
        policy = HookPolicyConfig(enabled_hooks={"pre_case"})
        dispatcher = HookDispatcher(policy)
        called = []

        def handler(ctx: HookContext, data: dict) -> HookResult:
            called.append(ctx.case_id)
            return HookResult(proceed=True, advice="ok")

        dispatcher.register("pre_case", handler)
        ctx = HookContext(hook_name="pre_case", case_id="D001", plugin_name="test")
        result = dispatcher.dispatch(ctx, {"key": "value"})
        assert called == ["D001"]
        assert result.advice == "ok"

    def test_dispatch_halt_stops_execution(self):
        policy = HookPolicyConfig(enabled_hooks={"pre_step"})
        dispatcher = HookDispatcher(policy)
        call_order = []

        def halt_handler(ctx: HookContext, data: dict) -> HookResult:
            call_order.append("halt")
            return HookResult(proceed=False, advice="blocked by policy")

        def second_handler(ctx: HookContext, data: dict) -> HookResult:
            call_order.append("second")
            return HookResult()

        dispatcher.register("pre_step", halt_handler)
        dispatcher.register("pre_step", second_handler)
        ctx = HookContext(hook_name="pre_step", case_id="D001", plugin_name="test")
        result = dispatcher.dispatch(ctx, {})
        assert result.proceed is False
        assert call_order == ["halt"]  # second handler not called

    def test_dispatch_fail_open(self):
        policy = HookPolicyConfig(enabled_hooks={"on_failure"}, fail_open=True)
        dispatcher = HookDispatcher(policy)

        def bad_handler(ctx: HookContext, data: dict) -> HookResult:
            raise RuntimeError("hook crashed")

        dispatcher.register("on_failure", bad_handler)
        ctx = HookContext(hook_name="on_failure", case_id="D001", plugin_name="test")
        result = dispatcher.dispatch(ctx, {})
        assert result.proceed is True  # fail_open allows continuation

    def test_dispatch_fail_closed(self):
        policy = HookPolicyConfig(enabled_hooks={"on_failure"}, fail_open=False)
        dispatcher = HookDispatcher(policy)

        def bad_handler(ctx: HookContext, data: dict) -> HookResult:
            raise RuntimeError("hook crashed")

        dispatcher.register("on_failure", bad_handler)
        ctx = HookContext(hook_name="on_failure", case_id="D001", plugin_name="test")
        result = dispatcher.dispatch(ctx, {})
        assert result.proceed is False

    def test_no_registered_handlers(self):
        policy = HookPolicyConfig(enabled_hooks={"pre_case"})
        dispatcher = HookDispatcher(policy)
        ctx = HookContext(hook_name="pre_case", case_id="D001", plugin_name="test")
        result = dispatcher.dispatch(ctx, {})
        assert result.proceed is True

    def test_registered_hooks_summary(self):
        dispatcher = HookDispatcher()
        dispatcher.register("pre_case", lambda ctx, data: HookResult())
        dispatcher.register("pre_case", lambda ctx, data: HookResult())
        dispatcher.register("on_failure", lambda ctx, data: HookResult())
        assert dispatcher.registered_hooks == {"pre_case": 2, "on_failure": 1}

    def test_ihook_protocol(self):
        def my_hook(ctx: HookContext, data: dict) -> HookResult:
            return HookResult()

        assert isinstance(my_hook, IHook)


# -- ALL_HOOK_NAMES ----------------------------------------------------------

class TestAllHookNames:
    def test_expected_hooks(self):
        expected = {"pre_case", "post_case", "pre_step", "post_step", "on_failure", "on_retry"}
        assert ALL_HOOK_NAMES == expected
