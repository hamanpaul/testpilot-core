"""Orchestrator — central coordinator for plugin loading, test scheduling, and monitoring.

The heavy lifting is delegated to:
- ``case_utils``       — pure helpers for case filtering, band mapping, ID handling
- ``runner_selector``  — agent/runner selection and policy resolution
- ``execution_engine`` — per-case execution with retry and timeout escalation

This module keeps the public API identical to pre-split versions so that
``from testpilot.core.orchestrator import Orchestrator`` continues to work.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

try:
    from testpilot.core.copilot_session import (
        CopilotSDKUnavailableError,
        CopilotSessionManager,
        CopilotSessionRequest,
        build_case_session_plan,
        build_session_id,
    )
except Exception:  # pragma: no cover - optional during incremental rollout
    build_case_session_plan = None
    CopilotSDKUnavailableError = None  # type: ignore[assignment,misc]
    CopilotSessionManager = None  # type: ignore[assignment,misc]
    CopilotSessionRequest = None  # type: ignore[assignment,misc]
    build_session_id = None  # type: ignore[assignment]

from testpilot.core.case_utils import (
    band_results as _band_results,
    case_aliases as _case_aliases,
    case_band_results as _case_band_results,
    case_matches_requested_ids as _case_matches_requested_ids,
    overall_case_status as _overall_case_status,
    safe_float as _safe_float,
    safe_int as _safe_int,
    sanitize_case_id as _sanitize_case_id,
)
from testpilot.core.execution_engine import ExecutionEngine
from testpilot.core.advisory import AdvisoryCollector
from testpilot.core.hook_policy import HookDispatcher, build_hook_policy
from testpilot.core.plugin_loader import PluginLoader
from testpilot.core.remediation import RuntimeRemediationCoordinator
from testpilot.core.runner_selector import (
    DEFAULT_EXECUTION_POLICY,
    RunnerSelector,
)
from testpilot.core.testbed_config import TestbedConfig
from testpilot.runtime.factory import create_run_backend
from testpilot.runtime.orchestrator_run_backend_compat import OrchestratorRunBackendCompat
from testpilot.runtime.run_backend import RunHandle

log = logging.getLogger(__name__)

# 預設路徑（相對於專案根目錄）
DEFAULT_PLUGINS_DIR = "plugins"
DEFAULT_CONFIG_DIR = "configs"

# Re-export for backward compatibility
__all__ = ["Orchestrator", "DEFAULT_EXECUTION_POLICY"]


class Orchestrator(OrchestratorRunBackendCompat):
    """主編排器：載入 plugin、排程測試、協調監控與報告。

    Delegates runner selection to :class:`RunnerSelector` and per-case
    execution to :class:`ExecutionEngine`.
    """

    def __init__(
        self,
        project_root: Path | str | None = None,
        plugins_dir: Path | str | None = None,
        config_path: Path | str | None = None,
    ) -> None:
        self.root = Path(project_root) if project_root else Path(__file__).resolve().parents[3]
        self.plugins_dir = Path(plugins_dir) if plugins_dir else self.root / DEFAULT_PLUGINS_DIR
        config = config_path or self.root / DEFAULT_CONFIG_DIR / "testbed.yaml"
        self.config = TestbedConfig(config)
        self.run_backend = create_run_backend(
            self.config.raw.get("testbed", {}).get("run_backend"),
            self.config.raw.get("testbed", {}),
        )
        self._run_handle: RunHandle | None = None
        self.loader = PluginLoader(self.plugins_dir)
        self.runner_selector = RunnerSelector(self.plugins_dir)
        self.execution_engine = ExecutionEngine(self.config)
        self.session_manager: CopilotSessionManager | None = self._try_init_session_manager()
        # Loud surfacing (#16): when the SDK session foundation fails, remediation
        # silently falls back to the builtin classifier. Track a run-level degraded
        # status so the failure is warned once and carried in the run payload.
        self.agent_session_degraded: dict[str, Any] = {"degraded": False, "reason": ""}

    @property
    def run_handle(self) -> RunHandle | None:
        return self._run_handle

    def _build_execution_engine(
        self,
        *,
        plugin_name: str,
        plugin: Any,
        agent_config: dict[str, Any],
    ) -> ExecutionEngine:
        policy = build_hook_policy(agent_config)
        dispatcher = HookDispatcher(policy)
        advisory_collector = AdvisoryCollector()
        advisory_handler = advisory_collector.to_hook_handler()
        dispatcher.register("on_failure", advisory_handler)
        dispatcher.register("post_case", advisory_handler)

        remediation_policy = agent_config.get("remediation", {})
        if not isinstance(remediation_policy, dict):
            remediation_policy = {}
        remediation = RuntimeRemediationCoordinator(
            plugin=plugin,
            topology=self.config,
            policy=remediation_policy,
        )
        for hook_name, handler in (
            ("pre_case", remediation.handle_pre_case),
            ("on_failure", remediation.handle_on_failure),
            ("on_retry", remediation.handle_on_retry),
            ("post_case", remediation.handle_post_case),
        ):
            dispatcher.register(hook_name, handler)
        self.execution_engine = ExecutionEngine(self.config, dispatcher)
        log.debug(
            "execution engine rebuilt for %s hooks=%s",
            plugin_name,
            dispatcher.registered_hooks,
        )
        return self.execution_engine

    # -- SDK session management ------------------------------------------------

    @staticmethod
    def _try_init_session_manager() -> CopilotSessionManager | None:
        """Try to create a CopilotSessionManager; return None if SDK unavailable."""
        if CopilotSessionManager is None:
            return None
        try:
            mgr = CopilotSessionManager()
            mgr._load_sdk()  # probe availability
            return mgr
        except Exception:
            log.debug("Copilot SDK unavailable — session foundation disabled")
            return None

    def _create_case_session(
        self,
        session_plan: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Attempt to create an SDK session from a session plan; return handle info or None."""
        if self.session_manager is None or CopilotSessionRequest is None:
            return None
        try:
            provider = session_plan.get("provider_config")
            request = CopilotSessionRequest(
                session_id=str(session_plan.get("session_id", "")),
                model=str(session_plan.get("model", "")),
                reasoning_effort=str(session_plan.get("reasoning_effort", "high")),
                provider=provider,
            )
            handle = self.session_manager.create_session(request)
            return {
                "session_id": handle.session_id,
                "workspace_path": handle.workspace_path,
                "status": "created",
            }
        except Exception as exc:
            if not self.agent_session_degraded["degraded"]:
                log.warning(
                    "SDK session foundation failed; remediation will run with "
                    "builtin-fallback for the whole run: %s",
                    exc,
                )
                self.agent_session_degraded = {"degraded": True, "reason": str(exc)}
            else:
                log.debug("SDK session creation failed (already degraded): %s", exc)
            return {"status": "failed", "error": str(exc)}

    def _cleanup_case_session(self, session_id: str | None) -> None:
        """Best-effort cleanup of a case-level SDK session."""
        if not session_id or self.session_manager is None:
            return
        try:
            self.session_manager.delete_session(session_id)
        except Exception:
            log.debug("SDK session cleanup failed for %s", session_id)

    # -- discovery -------------------------------------------------------------

    def discover_plugins(self) -> list[str]:
        """列出所有可用 plugin。"""
        return self.loader.discover()

    def list_cases(self, plugin_name: str) -> list[dict[str, Any]]:
        """載入指定 plugin 並列出其 test cases。"""
        plugin = self.loader.load(plugin_name)
        return plugin.discover_cases()

    # -- backward-compatible static/class delegates ----------------------------
    # Existing tests call e.g. ``Orchestrator._safe_int(...)``; keep them
    # working by delegating to the new ``case_utils`` module.

    @staticmethod
    def _band_results(status: str, bands: list[str] | None) -> tuple[str, str, str]:
        return _band_results(status, bands)

    @classmethod
    def _case_band_results(cls, case: dict[str, Any], verdict: bool) -> tuple[str, str, str]:
        return _case_band_results(case, verdict)

    @staticmethod
    def _overall_case_status(result_5g: str, result_6g: str, result_24g: str) -> str:
        return _overall_case_status(result_5g, result_6g, result_24g)

    @staticmethod
    def _safe_int(value: Any, default: int) -> int:
        return _safe_int(value, default)

    @staticmethod
    def _safe_float(value: Any, default: float) -> float:
        return _safe_float(value, default)

    @staticmethod
    def _sanitize_case_id(case_id: str) -> str:
        return _sanitize_case_id(case_id)

    @staticmethod
    def _case_aliases(case: dict[str, Any]) -> list[str]:
        return _case_aliases(case)

    @classmethod
    def _case_matches_requested_ids(
        cls,
        case: dict[str, Any],
        requested_ids: set[str],
    ) -> bool:
        return _case_matches_requested_ids(case, requested_ids)

    # -- runner selection delegates (backward compat) --------------------------

    def _enabled_runners(self, agent_config: dict[str, Any]) -> list[dict[str, Any]]:
        return self.runner_selector.enabled_runners(agent_config)

    def _runner_availability_overrides(self, plugin_name: str) -> dict[str, str | bool]:
        return self.runner_selector.runner_availability_overrides(plugin_name)

    @staticmethod
    def _runner_summary(runner: dict[str, Any]) -> dict[str, Any]:
        return RunnerSelector.runner_summary(runner)

    def _match_runner_by_selector(
        self, selector: Any, runners: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        return self.runner_selector.match_runner_by_selector(selector, runners)

    def _normalize_runtime_selection(
        self, selection: Any, runners: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
        return self.runner_selector.normalize_runtime_selection(selection, runners)

    def _select_runner_via_agent_runtime(
        self,
        plugin_name: str,
        case: dict[str, Any],
        agent_config: dict[str, Any],
        runners: list[dict[str, Any]],
    ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        return self.runner_selector.select_runner_via_agent_runtime(
            plugin_name, case, agent_config, runners
        )

    def _select_case_runner(
        self,
        plugin_name: str,
        case: dict[str, Any],
        agent_config: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return self.runner_selector.select_case_runner(plugin_name, case, agent_config)

    # -- execution delegates (backward compat) ---------------------------------

    def _attempt_timeout_seconds(
        self,
        *,
        steps_count: int,
        attempt_index: int,
        execution_policy: dict[str, Any],
    ) -> float:
        return ExecutionEngine.attempt_timeout_seconds(
            steps_count=steps_count,
            attempt_index=attempt_index,
            execution_policy=execution_policy,
        )

    @staticmethod
    def _write_case_trace(path: Path, payload: dict[str, Any]) -> None:
        ExecutionEngine.write_case_trace(path, payload)

    # -- runner-delegated run loop ---------------------------------------------

    def _run_via_runner(
        self,
        plugin: Any,
        runner: Any,
        plugin_name: str,
        case_ids: list[str] | None,
        dut_fw_ver: str | None,
        provider_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return runner.run(
            self,
            plugin_name,
            case_ids,
            dut_fw_ver,
            provider_config,
        )

    def _skeleton_run(
        self,
        *,
        plugin: Any,
        plugin_name: str,
        case_ids: list[str] | None,
    ) -> dict[str, Any]:
        cases = plugin.discover_cases()
        if case_ids:
            requested_ids = {str(case_id).strip() for case_id in case_ids if str(case_id).strip()}
            cases = [c for c in cases if _case_matches_requested_ids(c, requested_ids)]

        log.info("would run %d cases from plugin '%s'", len(cases), plugin_name)
        return {
            "plugin": plugin_name,
            "plugin_version": plugin.version,
            "cases_count": len(cases),
            "case_ids": [c.get("id", "?") for c in cases],
            "status": "skeleton — not yet implemented",
        }

    # -- public entry point ----------------------------------------------------

    def run(
        self,
        plugin_name: str,
        case_ids: list[str] | None = None,
        *,
        dut_fw_ver: str | None = None,
        provider_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """執行測試。

        If the plugin provides a runner (create_runner() returns non-None),
        the full run/report pipeline is delegated to it.

        Other plugins:
        - runner override if create_runner() returns non-None with run()
        - core run_loop if plugin exposes a reporter with build_reports()
        - otherwise keeps skeleton behavior
        """
        plugin = self.loader.load(plugin_name)
        create_runner = getattr(plugin, "create_runner", None)
        runner = create_runner() if callable(create_runner) else None
        if runner is not None and hasattr(runner, "run"):
            return self._run_via_runner(
                plugin=plugin,
                runner=runner,
                plugin_name=plugin_name,
                case_ids=case_ids,
                dut_fw_ver=dut_fw_ver,
                provider_config=provider_config,
            )
        reporter = plugin.create_reporter()
        if reporter is None or not hasattr(reporter, "build_reports"):
            return self._skeleton_run(
                plugin=plugin,
                plugin_name=plugin_name,
                case_ids=case_ids,
            )
        from testpilot.core.run_loop import run as core_run

        return core_run(
            self,
            plugin_name,
            case_ids,
            dut_fw_ver,
            provider_config=provider_config,
        )
