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
from typing import Any, Callable, Literal, TypeVar

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
from testpilot.core.azure_auth import AzureAgentRuntime, AzureAgentState, resolve_azure_agent_runtime
from testpilot.core.execution_engine import ExecutionEngine
from testpilot.core.advisory import AdvisoryCollector
from testpilot.core.hook_policy import HookDispatcher, build_hook_policy
from testpilot.core.plugin_loader import PluginLoader
from testpilot.core.remediation import RuntimeRemediationCoordinator, tier2_support
from testpilot.core.tier2_recovery import (
    Tier2RecoveryContext,
    parse_tier2_plan,
)
from testpilot.core.usage_ledger import UsageLedger, UsagePurpose
from testpilot.core.case_planning import (
    CasePlanningResult,
    CasePlanningValidationError,
    build_case_planning_prompt,
    parse_case_planning_response,
)
from testpilot.core.run_analysis import (
    RunAnalysisResult,
    build_case_capsule,
    build_run_analysis_prompt,
    build_run_analysis_reducer_prompt,
    pack_case_capsules,
    parse_run_analysis_response,
)
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

T = TypeVar("T")


class AgentCallSkipped(RuntimeError):
    def __init__(self, reason: Literal["no_agent", "circuit_breaker"]):
        super().__init__(reason)
        self.reason = reason


class AgentProviderCallError(RuntimeError):
    """Provider/SDK/session failure that opens the run circuit."""

    def __init__(self, error_type: str):
        super().__init__(error_type)
        self.error_type = error_type


class AgentResponseValidationError(ValueError):
    """Purpose-schema rejection that leaves the provider circuit closed."""

    def __init__(self, error_type: str):
        super().__init__(error_type)
        self.error_type = error_type


def _planning_result_error(exc: Exception) -> CasePlanningResult:
    return CasePlanningResult(status="failed", error_type=type(exc).__name__)


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
        agent_runtime: AzureAgentRuntime | None = None,
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
        self.agent_runtime = agent_runtime or resolve_azure_agent_runtime()
        self.session_manager: CopilotSessionManager | None = None
        # Loud surfacing (#16): track general SDK session foundation failures at
        # run scope. Current remediation policy may still use an independent,
        # tool-denied tier-2 one-shot session (#4).
        self.agent_session_degraded: dict[str, Any] = {"degraded": False, "reason": ""}
        self.usage_ledger = UsageLedger()
        self.agent_circuit_open = False
        self.agent_circuit_error_type = ""
        self.agent_recovery_support: dict[str, Any] = {}
        self._reset_run_state()

    def _reset_run_state(self) -> None:
        """Reset per-run state at the start of each run.

        ``agent_session_degraded`` (#16) is run-scoped, not instance-scoped:
        without this reset a reused Orchestrator instance would leak a prior
        run's degraded status into the next run's payload.
        """
        self.agent_session_degraded = {"degraded": False, "reason": ""}
        self.usage_ledger = UsageLedger()
        self.agent_circuit_open = False
        self.agent_circuit_error_type = ""
        self.agent_recovery_support = {}
        self.agent_runtime.reset_to_initial()
        if self.agent_runtime.status.state is AzureAgentState.AZURE_READY and self.session_manager is None:
            self.session_manager = self._try_init_session_manager()
            if self.session_manager is None:
                self.agent_circuit_open = True
                self.agent_circuit_error_type = "CopilotSDKUnavailableError"
                self.agent_runtime.mark_degraded(self.agent_circuit_error_type)

    @property
    def run_handle(self) -> RunHandle | None:
        return self._run_handle

    def _build_execution_engine(
        self,
        *,
        plugin_name: str,
        plugin: Any,
        agent_config: dict[str, Any],
        run_id: str,
        case_id: str,
        runner: dict[str, Any],
        provider_config: dict[str, Any] | None,
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
        raw_tier2_policy = remediation_policy.get("tier2", {})
        tier2_policy = (
            dict(raw_tier2_policy)
            if isinstance(raw_tier2_policy, dict)
            else {}
        )
        support = tier2_support(plugin, remediation_policy)
        support_map = getattr(self, "agent_recovery_support", None)
        if support_map is None:
            support_map = self.agent_recovery_support = {}
        support_map[case_id] = support
        tier2_requester = None
        runtime = getattr(self, "agent_runtime", None)
        runtime_ready = runtime is not None and runtime.status.state is AzureAgentState.AZURE_READY
        if support.supported and runtime_ready and not self.agent_circuit_open:
            remediation_invocation = 0
            timeout_seconds = tier2_policy.get("timeout_seconds", 60.0)

            def _request_tier2_plan(
                prompt: str,
                context: dict[str, Any],
            ) -> str | None:
                nonlocal remediation_invocation
                remediation_invocation += 1
                session_id = build_session_id(
                    run_id,
                    case_id=case_id,
                    remediate_attempt=remediation_invocation,
                )
                raw, _ = self._invoke_agent_one_shot(
                    run_id=run_id,
                    case_id=case_id,
                    purpose="agent_recovery",
                    session_id=session_id,
                    prompt=prompt,
                    timeout_seconds=timeout_seconds,
                    validate=lambda raw: parse_tier2_plan(
                        raw,
                        capability_schemas=Tier2RecoveryContext.from_mapping(
                            context
                        ).capability_schemas,
                        max_actions=max(
                            0, _safe_int(tier2_policy.get("max_actions"), 3)
                        ),
                    ),
                )
                return raw

            tier2_requester = _request_tier2_plan
        remediation = RuntimeRemediationCoordinator(
            plugin=plugin,
            topology=self.config,
            policy=remediation_policy,
            tier2_requester=tier2_requester,
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
            manager = CopilotSessionManager()
            manager._load_sdk()  # probe availability
            return manager
        except Exception:
            log.debug("Copilot SDK unavailable — session foundation disabled")
            return None

    def _invoke_agent_one_shot(
        self,
        *,
        run_id: str,
        case_id: str | None,
        purpose: UsagePurpose,
        session_id: str,
        prompt: str,
        timeout_seconds: float,
        validate: Callable[[str], T],
    ) -> tuple[str, T]:
        """Execute one measured, tool-denied agent turn.

        Provider/session failures are run-fatal for agent calls and open the
        circuit. Response validation is purpose-local and keeps the provider
        available for the next call.
        """
        if getattr(self, "agent_circuit_open", False):
            raise AgentCallSkipped("circuit_breaker")
        if getattr(self, "agent_runtime", None) is None or self.agent_runtime.status.state is not AzureAgentState.AZURE_READY:
            raise AgentCallSkipped("no_agent")

        binding = self.usage_ledger.start_invocation(
            run_id=run_id,
            session_id=session_id,
            case_id=case_id,
            purpose=purpose,
            model=self.agent_runtime.status.deployment,
        )
        try:
            provider = self.agent_runtime.sdk_provider_config()
            if provider is None or CopilotSessionRequest is None:
                raise CopilotSDKUnavailableError("Azure provider is unavailable")
            if self.session_manager is None:
                raise CopilotSDKUnavailableError("Copilot one-shot manager is unavailable")
            request = CopilotSessionRequest(
                session_id=session_id,
                model=self.agent_runtime.status.deployment,
                reasoning_effort="high",
                provider=provider,
                on_event=self.usage_ledger.event_handler(binding),
            )
            raw = self.session_manager.send_one_shot(
                request,
                prompt,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:
            error_type = type(exc).__name__
            self.usage_ledger.finish_invocation(binding, status="failed", error_type=error_type)
            self.agent_circuit_open = True
            self.agent_circuit_error_type = error_type
            self.agent_runtime.mark_degraded(error_type)
            self._record_agent_session_failure(
                exc,
                warning="Azure SDK one-shot failed; later agent calls are disabled",
            )
            raise AgentProviderCallError(error_type) from None

        try:
            parsed = validate(raw)
        except Exception as exc:
            error_type = type(exc).__name__
            self.usage_ledger.finish_invocation(binding, status="failed", error_type=error_type)
            raise AgentResponseValidationError(error_type) from None

        self.usage_ledger.finish_invocation(binding, status="completed")
        return raw, parsed

    def _plan_case(
        self,
        *,
        run_id: str,
        plugin_name: str,
        case: dict[str, Any],
        case_ordinal: int,
        case_count: int,
        execution_policy: dict[str, Any],
    ) -> CasePlanningResult:
        if getattr(self, "agent_circuit_open", False):
            return CasePlanningResult(status="skipped_circuit_breaker")
        if getattr(self, "agent_runtime", None) is None or self.agent_runtime.status.state is not AzureAgentState.AZURE_READY:
            return CasePlanningResult(status="skipped_no_agent")
        case_id = str(case.get("id", "?"))
        session_plan = build_case_session_plan(
            run_id, case_id, {}, agent_runtime=self.agent_runtime
        )
        if session_plan is None:
            return CasePlanningResult(status="skipped_no_agent")
        try:
            prompt = build_case_planning_prompt(
                case=case,
                execution_policy=execution_policy,
                run_metadata={"run_id": run_id, "plugin_name": plugin_name, "case_ordinal": case_ordinal, "case_count": case_count},
            )
            _, advisory = self._invoke_agent_one_shot(
                run_id=run_id,
                case_id=case_id,
                purpose="case_planning",
                session_id=str(session_plan["session_id"]),
                prompt=prompt,
                timeout_seconds=60.0,
                validate=parse_case_planning_response,
            )
            return CasePlanningResult(status="completed", advisory=advisory)
        except AgentCallSkipped as exc:
            return CasePlanningResult(status="skipped_circuit_breaker" if exc.reason == "circuit_breaker" else "skipped_no_agent")
        except (CasePlanningValidationError, AgentResponseValidationError) as exc:
            return _planning_result_error(exc)
        except AgentProviderCallError as exc:
            return CasePlanningResult(status="failed", error_type=exc.error_type)

    def _analyze_run(self, *, run_result: Any, metrics: dict[str, Any], direct_usage: Any) -> RunAnalysisResult:
        """Analyze completed verdicts once, after execution has ended."""
        if not run_result.cases:
            return RunAnalysisResult(status="skipped_no_cases")
        if self.agent_circuit_open:
            return RunAnalysisResult(status="skipped_circuit_breaker")
        if not self.agent_runtime.status.ready:
            return RunAnalysisResult(status="skipped_no_agent")
        batch_calls = 0
        reducer_calls = 0
        try:
            capsules = []
            for record in run_result.cases:
                usage = direct_usage.case_totals(record.case_id) if hasattr(direct_usage, "case_totals") else direct_usage.get(record.case_id, {})
                capsules.append(build_case_capsule(record, direct_usage=usage))
            batches = pack_case_capsules(capsules)
            summaries = []
            for index, batch in enumerate(batches, 1):
                batch_calls += 1
                _, parsed = self._invoke_agent_one_shot(
                    run_id=run_result.run_id, case_id=None,
                    purpose="run_analysis_batch",
                    session_id=build_session_id(run_result.run_id, purpose="analysis-batch", invocation_index=index),
                    prompt=build_run_analysis_prompt(capsules=batch, metrics=metrics, batch_index=index, batch_count=len(batches)),
                    timeout_seconds=60.0,
                    validate=lambda raw, ids={x.case_id for x in batch}: parse_run_analysis_response(raw, allowed_case_ids=ids),
                )
                summaries.append(parsed)
            if len(summaries) == 1:
                return RunAnalysisResult.from_mapping(summaries[0], batch_calls=1)
            reducer_calls = 1
            _, reduced = self._invoke_agent_one_shot(
                run_id=run_result.run_id, case_id=None, purpose="run_analysis_reducer",
                session_id=build_session_id(run_result.run_id, purpose="analysis-reducer", invocation_index=1),
                prompt=build_run_analysis_reducer_prompt(summaries=summaries, metrics=metrics),
                timeout_seconds=60.0,
                validate=lambda raw: parse_run_analysis_response(raw, allowed_case_ids=set()),
            )
            findings = [item for summary in summaries for item in summary["case_findings"]]
            return RunAnalysisResult.from_mapping(reduced, batch_calls=len(batches), reducer_calls=1, case_findings=findings)
        except Exception as exc:
            return RunAnalysisResult(status="failed", batch_calls=batch_calls, reducer_calls=reducer_calls, error_type=getattr(exc, "error_type", type(exc).__name__))

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
            safe_reason = self._record_agent_session_failure(
                exc,
                warning=(
                    "SDK session foundation failed; agent session marked "
                    "degraded"
                ),
            )
            return {"status": "failed", "error": safe_reason}

    def _record_agent_session_failure(
        self,
        exc: Exception,
        *,
        warning: str,
    ) -> str:
        """Surface an SDK/provider failure once without persisting its text."""
        safe_reason = f"SDK session operation failed ({type(exc).__name__})"
        if not self.agent_session_degraded["degraded"]:
            log.warning(
                "%s: error_type=%s",
                warning,
                type(exc).__name__,
            )
            self.agent_session_degraded = {
                "degraded": True,
                "reason": safe_reason,
            }
        else:
            log.debug(
                "SDK session operation failed (already degraded): error_type=%s",
                type(exc).__name__,
            )
        return safe_reason

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
        payload = runner.run(
            self,
            plugin_name,
            case_ids,
            dut_fw_ver,
            provider_config,
        )
        if isinstance(payload, dict):
            payload["core_cost_report"] = {
                "status": "unsupported_execution_path",
                "execution_path": "custom_runner",
                "coverage": "core_sdk_calls_only",
                "analysis_status": "unavailable",
            }
        return payload

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
            "core_cost_report": {
                "status": "unsupported_execution_path",
                "execution_path": "skeleton",
                "coverage": "core_sdk_calls_only",
                "analysis_status": "unavailable",
            },
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
        self._reset_run_state()
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
