"""RunnerSelector — agent/runner selection and policy resolution."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from testpilot.core.case_utils import safe_float, safe_int

try:
    from testpilot.core import agent_runtime as agent_runtime_module
except Exception:  # pragma: no cover - optional module during incremental rollout
    agent_runtime_module = None

log = logging.getLogger(__name__)

DEFAULT_EXECUTION_POLICY: dict[str, Any] = {
    "scope": "per_case",
    "mode": "sequential",
    "max_concurrency": 1,
    "failure_policy": "retry_then_fail_and_continue",
    "retry": {
        "max_attempts": 2,
        "backoff_seconds": 5,
    },
    "timeout": {
        "base_seconds": 120,
        "per_step_seconds": 45,
        "retry_multiplier": 1.25,
        "max_seconds": 900,
    },
}


class RunnerSelector:
    """Resolve agent-config, build execution policy, and select runner per case."""

    def __init__(self, plugins_dir: Path) -> None:
        self.plugins_dir = plugins_dir

    # -- agent config -----------------------------------------------------------

    def load_agent_config(self, plugin_name: str, plugin: Any | None = None) -> dict[str, Any]:
        base_dir = Path(plugin.plugin_root) if plugin is not None else self.plugins_dir / plugin_name
        path = base_dir / "agent-config.yaml"
        if not path.exists():
            return {}
        try:
            content = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as exc:  # pragma: no cover - defensive config parse
            log.warning("failed to load agent-config for %s: %s", plugin_name, exc)
            return {}
        return content if isinstance(content, dict) else {}

    # -- execution policy -------------------------------------------------------

    def build_execution_policy(self, agent_config: dict[str, Any]) -> dict[str, Any]:
        execution = agent_config.get("execution")
        if not isinstance(execution, dict):
            execution = {}

        retry = execution.get("retry")
        if not isinstance(retry, dict):
            retry = {}

        timeout = execution.get("timeout")
        if not isinstance(timeout, dict):
            timeout = {}

        defaults = DEFAULT_EXECUTION_POLICY
        policy = {
            "scope": str(execution.get("scope", defaults["scope"])),
            "mode": str(execution.get("mode", defaults["mode"])),
            "max_concurrency": max(1, safe_int(execution.get("max_concurrency"), 1)),
            "failure_policy": str(execution.get("failure_policy", defaults["failure_policy"])),
            "retry": {
                "max_attempts": max(1, safe_int(retry.get("max_attempts"), 2)),
                "backoff_seconds": max(0.0, safe_float(retry.get("backoff_seconds"), 5.0)),
            },
            "timeout": {
                "base_seconds": max(1.0, safe_float(timeout.get("base_seconds"), 120.0)),
                "per_step_seconds": max(0.0, safe_float(timeout.get("per_step_seconds"), 45.0)),
                "retry_multiplier": max(
                    1.0, safe_float(timeout.get("retry_multiplier"), 1.25)
                ),
                "max_seconds": max(1.0, safe_float(timeout.get("max_seconds"), 900.0)),
            },
        }

        return policy

    # -- runner enumeration & matching ------------------------------------------

    def enabled_runners(self, agent_config: dict[str, Any]) -> list[dict[str, Any]]:
        runners_raw = agent_config.get("runners")
        if not isinstance(runners_raw, list):
            return []

        runners: list[dict[str, Any]] = []
        for idx, item in enumerate(runners_raw, start=1):
            if not isinstance(item, dict):
                continue
            if item.get("enabled", True) is False:
                continue
            runner = dict(item)
            runner.setdefault("priority", idx)
            runners.append(runner)

        runners.sort(key=lambda r: safe_int(r.get("priority"), 9999))
        return runners

    def runner_availability_overrides(self, plugin_name: str) -> dict[str, str | bool]:
        """Optional env-based availability overrides for deterministic fallback simulation."""
        raw = os.environ.get("TESTPILOT_AGENT_AVAILABILITY", "").strip()
        if not raw:
            return {}
        try:
            payload = json.loads(raw)
        except Exception:
            log.warning("invalid TESTPILOT_AGENT_AVAILABILITY, ignore override")
            return {}
        if not isinstance(payload, dict):
            return {}

        scoped = payload.get(plugin_name, payload)
        if not isinstance(scoped, dict):
            return {}

        out: dict[str, str | bool] = {}
        for key, value in scoped.items():
            if not isinstance(key, str) or not key.strip():
                continue
            if isinstance(value, bool):
                out[key.strip()] = value
                continue
            if value is None:
                out[key.strip()] = False
                continue
            out[key.strip()] = str(value)
        return out

    @staticmethod
    def runner_summary(runner: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(runner, dict):
            runner = {
                "priority": getattr(runner, "priority", 0),
                "cli_agent": getattr(runner, "cli_agent", ""),
                "model": getattr(runner, "model", ""),
                "effort": getattr(runner, "effort", ""),
                "enabled": getattr(runner, "enabled", True),
            }
        return {
            "priority": runner.get("priority"),
            "cli_agent": runner.get("cli_agent"),
            "model": runner.get("model"),
            "effort": runner.get("effort"),
            "enabled": runner.get("enabled", True),
        }

    def match_runner_by_selector(
        self, selector: Any, runners: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        if hasattr(selector, "runner"):
            return self.match_runner_by_selector(getattr(selector, "runner"), runners)
        if (
            hasattr(selector, "cli_agent")
            and hasattr(selector, "model")
            and not isinstance(selector, dict)
        ):
            selector = {
                "priority": getattr(selector, "priority", None),
                "cli_agent": getattr(selector, "cli_agent", ""),
                "model": getattr(selector, "model", ""),
                "effort": getattr(selector, "effort", "high"),
                "enabled": getattr(selector, "enabled", True),
            }
        if isinstance(selector, dict):
            if "cli_agent" in selector and "model" in selector:
                for runner in runners:
                    if str(runner.get("cli_agent")) == str(selector.get("cli_agent")) and str(
                        runner.get("model")
                    ) == str(selector.get("model")):
                        return runner
                return {
                    "priority": selector.get("priority", 0),
                    "cli_agent": selector.get("cli_agent"),
                    "model": selector.get("model"),
                    "effort": selector.get("effort", "high"),
                    "enabled": True,
                }

            for runner in runners:
                if "priority" in selector and safe_int(
                    runner.get("priority"), -1
                ) != safe_int(selector.get("priority"), -2):
                    continue
                if "cli_agent" in selector and str(runner.get("cli_agent")) != str(
                    selector.get("cli_agent")
                ):
                    continue
                if "model" in selector and str(runner.get("model")) != str(selector.get("model")):
                    continue
                return runner
            return None

        if isinstance(selector, str):
            lowered = selector.strip().lower()
            for runner in runners:
                if str(runner.get("cli_agent", "")).lower() == lowered:
                    return runner
                if str(runner.get("model", "")).lower() == lowered:
                    return runner
            return None

        if isinstance(selector, (int, float)):
            wanted = int(selector)
            for runner in runners:
                if safe_int(runner.get("priority"), -1) == wanted:
                    return runner
            return None

        return None

    def normalize_runtime_selection(
        self, selection: Any, runners: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        if selection is None:
            return None
        if isinstance(selection, dict):
            for key in ("selected_runner", "runner", "selected", "selection"):
                if key in selection:
                    matched = self.match_runner_by_selector(selection.get(key), runners)
                    if matched is not None:
                        return matched
            matched = self.match_runner_by_selector(selection, runners)
            if matched is not None:
                return matched
        return self.match_runner_by_selector(selection, runners)

    # -- agent_runtime integration ---------------------------------------------

    def select_runner_via_agent_runtime(
        self,
        plugin_name: str,
        case: dict[str, Any],
        agent_config: dict[str, Any],
        runners: list[dict[str, Any]],
    ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        trace: dict[str, Any] = {
            "module_available": agent_runtime_module is not None,
            "method": None,
            "reason": "",
        }
        if agent_runtime_module is None:
            trace["reason"] = "agent_runtime module unavailable"
            return None, trace

        parse_fn = getattr(agent_runtime_module, "parse_agent_runtime_config", None)
        select_fn = getattr(agent_runtime_module, "select_runner", None)
        if callable(parse_fn) and callable(select_fn):
            try:
                runtime_config = parse_fn(agent_config)
                availability = self.runner_availability_overrides(plugin_name)
                selection = select_fn(runtime_config, availability=availability)
                trace["method"] = "module.select_runner"
                trace["availability"] = availability

                selection_items: list[dict[str, Any]] = []
                for item in getattr(selection, "trace", []):
                    selection_items.append(
                        {
                            "priority": getattr(item, "priority", 0),
                            "cli_agent": getattr(item, "cli_agent", ""),
                            "model": getattr(item, "model", ""),
                            "status": getattr(item, "status", ""),
                            "unavailable_reason": getattr(item, "unavailable_reason", None),
                        }
                    )
                trace["selection"] = selection_items

                matched = self.normalize_runtime_selection(selection, runners)
                if matched is not None:
                    return matched, trace
                trace["reason"] = "module.select_runner returned no valid runner"
            except Exception as exc:
                trace["reason"] = f"module.select_runner failed: {exc}"

        case_id = str(case.get("id", "?"))
        call_targets: list[tuple[str, Any]] = []
        for fn_name in ("select_runner_for_case", "select_runner"):
            fn = getattr(agent_runtime_module, fn_name, None)
            if callable(fn):
                call_targets.append((f"module.{fn_name}", fn))

        runtime_cls = getattr(agent_runtime_module, "AgentRuntime", None)
        if callable(runtime_cls):
            runtime_obj = None
            for init_kwargs in (
                {"plugin_name": plugin_name, "agent_config": agent_config},
                {"plugin": plugin_name, "config": agent_config},
                {},
            ):
                try:
                    runtime_obj = runtime_cls(**init_kwargs)
                    break
                except TypeError:
                    continue
                except Exception as exc:  # pragma: no cover - defensive runtime init
                    trace["reason"] = f"AgentRuntime init failed: {exc}"
                    break
            if runtime_obj is not None:
                for method_name in ("select_runner_for_case", "select_runner"):
                    fn = getattr(runtime_obj, method_name, None)
                    if callable(fn):
                        call_targets.append((f"AgentRuntime.{method_name}", fn))

        if not call_targets:
            trace["reason"] = "no callable selector in agent_runtime"
            return None, trace

        for method_name, selector in call_targets:
            for kwargs in (
                {"plugin_name": plugin_name, "case": case, "agent_config": agent_config},
                {"plugin_name": plugin_name, "case_id": case_id, "agent_config": agent_config},
                {"plugin": plugin_name, "case": case, "config": agent_config},
                {"case": case, "agent_config": agent_config},
                {"case_id": case_id, "agent_config": agent_config},
            ):
                try:
                    selection = selector(**kwargs)
                except TypeError:
                    continue
                except Exception as exc:  # pragma: no cover - defensive runtime call
                    trace["reason"] = f"{method_name} failed: {exc}"
                    break

                matched = self.normalize_runtime_selection(selection, runners)
                if matched is not None:
                    trace["method"] = method_name
                    return matched, trace

            try:
                selection = selector(plugin_name, case, agent_config)
            except Exception:
                continue
            matched = self.normalize_runtime_selection(selection, runners)
            if matched is not None:
                trace["method"] = method_name
                return matched, trace

        trace["reason"] = trace["reason"] or "selector returned no valid runner"
        return None, trace

    # -- top-level per-case selection ------------------------------------------

    def select_case_runner(
        self,
        plugin_name: str,
        case: dict[str, Any],
        agent_config: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        runners = self.enabled_runners(agent_config)
        selection_trace: dict[str, Any] = {
            "timestamp": datetime.now().isoformat(),
            "case_id": str(case.get("id", "?")),
            "candidates": [self.runner_summary(r) for r in runners],
            "fallback": {
                "applied": False,
                "reason": "",
            },
        }

        selected_runner: dict[str, Any] | None = None
        runtime_trace: dict[str, Any] = {
            "module_available": False,
            "method": None,
            "reason": "skip: no enabled runners",
        }
        if runners:
            selected_runner, runtime_trace = self.select_runner_via_agent_runtime(
                plugin_name=plugin_name,
                case=case,
                agent_config=agent_config,
                runners=runners,
            )

        selection_trace["runtime"] = runtime_trace
        runtime_selection = runtime_trace.get("selection", [])
        if isinstance(runtime_selection, list):
            for item in runtime_selection:
                if not isinstance(item, dict):
                    continue
                if str(item.get("status", "")).lower() != "unavailable":
                    continue
                reason = str(item.get("unavailable_reason") or "next_priority")
                selection_trace["fallback"] = {
                    "applied": True,
                    "reason": f"next_priority due unavailable: {reason}",
                }
                break

        if selected_runner is None and runners:
            selected_runner = runners[0]
            selection_trace["fallback"] = {
                "applied": True,
                "reason": runtime_trace.get("reason") or "fallback to first enabled runner",
            }

        if selected_runner is None:
            selected_runner = {
                "priority": 0,
                "cli_agent": "plugin-native",
                "model": "plugin-hooks",
                "effort": "high",
                "enabled": True,
            }
            selection_trace["fallback"] = {
                "applied": True,
                "reason": "no enabled runner configured",
            }

        selection_trace["selected"] = self.runner_summary(selected_runner)
        return selected_runner, selection_trace
