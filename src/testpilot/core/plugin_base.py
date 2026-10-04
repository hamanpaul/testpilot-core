"""PluginBase — abstract base class for all test plugins."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
import inspect
from pathlib import Path
import re
from typing import Any, ClassVar, Sequence

from testpilot.core.case_utils import case_matches_requested_ids, stringify_step_command
from testpilot.core.cleanup_result import (
    cleanup_exception_result,
    cleanup_failure_snapshot,
    has_unknown_transport_outcome,
    normalize_cleanup_result,
    project_transport_evidence,
)
from testpilot.core.prepared_run import PreparedRun
from testpilot.core.run_start_gate import (
    PrepareRunAfterCaptureContext,
    PrepareRunGateResult,
    RunCapability,
    RunCapabilityAdmissionOutcome,
    admit_run_capabilities,
)

_ABORT_REASON_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_DEFAULT_PLUGIN_ABORT_REASON = "plugin_failure_abort"


class IncompatiblePluginError(Exception):
    """Plugin SDK API version is incompatible or undeclared."""


class PluginBase(ABC):
    """Base contract implemented by TestPilot plugins.

    A plugin owns project-specific test semantics:
    1. discover and load test cases
    2. prepare and verify the test environment
    3. execute test steps
    4. evaluate domain-specific pass/fail conditions
    5. clean up project-owned resources
    """

    api_version: str | None = None
    required_run_capabilities: ClassVar[frozenset[RunCapability]] = frozenset()

    @property
    @abstractmethod
    def name(self) -> str:
        """Plugin 的唯一識別名稱。"""

    @property
    def version(self) -> str:
        """Plugin 版本。預設 '0.0.0'；子類別可覆寫。"""
        return "0.0.0"

    @property
    def plugin_root(self) -> Path:
        """Plugin 模組所在目錄。"""
        return Path(inspect.getfile(type(self))).resolve().parent

    @property
    def cases_dir(self) -> Path:
        """cases/ 目錄路徑，預設為 plugin 同層的 cases/。"""
        return self.plugin_root / "cases"

    @abstractmethod
    def discover_cases(self) -> list[dict[str, Any]]:
        """掃描 cases/ 目錄，回傳所有 test case 描述（已解析的 YAML dict）。"""

    def setup_env(self, case: dict[str, Any], topology: Any) -> bool:
        """Prepare the environment required by this test case.

        預設實作直接回傳 True（不需佈建）。子類別可覆寫。

        Returns:
            True if setup succeeded.
        """
        return True

    def verify_env(self, case: dict[str, Any], topology: Any) -> bool:
        """環境自檢：驗證測試所需的前置條件是否就緒。

        預設實作直接回傳 True（不需驗證）。子類別可覆寫。

        Returns:
            True if environment is ready.
        """
        return True

    @abstractmethod
    def execute_step(self, case: dict[str, Any], step: dict[str, Any], topology: Any) -> dict[str, Any]:
        """執行單一測試步驟。

        Returns:
            dict with keys: success (bool), output (str), captured (dict), timing (float)
        """

    @abstractmethod
    def evaluate(self, case: dict[str, Any], results: dict[str, Any]) -> bool:
        """依 pass_criteria 評估測試結果。

        Returns:
            True if all criteria pass.
        """

    def teardown(
        self, case: dict[str, Any], topology: Any
    ) -> Mapping[str, Any] | None:
        """Clean up test state.

        API 1.5 plugins may return a bounded failure mapping with ``status``
        ``failed`` or ``unknown``. ``None`` remains successful legacy cleanup.
        """

    # -- optional live remediation hooks --------------------------------------

    def request_remediation_decision(
        self,
        case: dict[str, Any],
        failure_snapshot: Any,
        topology: Any,
        *,
        runner: dict[str, Any] | None = None,
        remediation_policy: dict[str, Any] | None = None,
    ) -> Any:
        """Optional agent-backed remediation proposal hook.

        Default implementation is disabled. Plugins may override to return a
        structured remediation decision dict. Deterministic validation still
        happens in the core coordinator.
        """
        del case, failure_snapshot, topology, runner, remediation_policy
        return None

    def build_remediation_decision(
        self,
        case: dict[str, Any],
        failure_snapshot: Any,
        topology: Any,
        *,
        runner: dict[str, Any] | None = None,
        remediation_policy: dict[str, Any] | None = None,
    ) -> Any:
        """Optional builtin fallback for safe remediation decisions."""
        del case, failure_snapshot, topology, runner, remediation_policy
        return None

    def execute_remediation(
        self,
        case: dict[str, Any],
        decision: Any,
        topology: Any,
    ) -> dict[str, Any]:
        """Execute a previously approved remediation decision.

        Default implementation is a safe no-op. Plugins should override if they
        support live environment repair between retry attempts.
        """
        del case, decision, topology
        return {
            "success": False,
            "verify_after": None,
            "comment": "live remediation not supported",
            "actions": [],
        }

    def build_tier2_remediation_context(
        self,
        case: dict[str, Any],
        failure_snapshot: Any,
        topology: Any,
        *,
        runner: dict[str, Any] | None = None,
        remediation_policy: dict[str, Any] | None = None,
    ) -> Any:
        """Return bounded domain context and an environment capability catalog.

        Core owns prompt construction and the LLM call. The default keeps tier-2
        disabled until a plugin explicitly advertises its environment-only
        recovery capabilities.
        """
        del case, failure_snapshot, topology, runner, remediation_policy
        return None

    def execute_tier2_remediation(
        self,
        case: dict[str, Any],
        plan: Any,
        topology: Any,
    ) -> dict[str, Any]:
        """Execute a core-validated tier-2 environment repair plan."""
        del case, plan, topology
        return {
            "success": False,
            "comment": "tier-2 remediation not supported",
            "actions": [],
        }

    # -- optional case-level hooks --------------------------------------------

    def validate_case(self, case: dict[str, Any]) -> None:
        """case 載入後的 plugin 專屬驗證；違規時 raise。default no-op。"""
        del case
        return None

    def execution_policy(self, case: dict[str, Any]) -> dict[str, Any]:
        """plugin 宣告自身執行約束（concurrency/mode/runner 等）。default 中性（無約束）。"""
        del case
        return {}

    def register_cli(self, registrar: Any) -> None:
        """plugin 註冊 install-time CLI 子命令。default 不註冊。"""
        del registrar
        return None

    def bind_project_root(self, project_root: Path | str | None) -> None:
        """Receive the active operator project root before a run starts.

        Core invokes this optional context hook before dispatching a run and
        again before ``prepare_run``. Plugins may use it for run-start work
        such as preflight artifacts. The default is a no-op so existing
        plugins keep their behavior and method signatures.
        """
        del project_root

    def verify_install(self) -> list[tuple[bool, str]]:
        """Return plugin-owned install-health checks for testpilot --verify-install."""
        return []

    # -- optional overridable reporter -----------------------------------------

    def create_reporter(self) -> Any:
        """Return a reporter instance for this plugin.

        Defaults to None (use orchestrator default). Override to provide
        a plugin-specific reporter implementing the IReporter protocol.
        """
        return None

    def report_formats(self) -> list[str]:
        """Return the output formats this plugin supports.

        Defaults to ['xlsx']. Plugins may override to add 'md', 'json', etc.
        """
        return ["xlsx"]

    def create_runner(self) -> Any:
        """Return a runner that owns the full run loop, or None.

        Plugins that drive their own run/report pipeline override this.
        Default None → orchestrator uses skeleton behavior.
        """
        return None

    def prepare_run(self, case_ids: Sequence[str] | None) -> PreparedRun:
        """Discover and optionally filter cases without mutating source files."""
        cases = self.discover_cases()
        if case_ids:
            requested_ids = {str(case_id).strip() for case_id in case_ids if str(case_id).strip()}
            cases = [
                case for case in cases
                if case_matches_requested_ids(case, requested_ids)
            ]
        return PreparedRun(cases=cases, artifacts={})

    def prepare_run_after_capture(
        self,
        prepared: PreparedRun,
        context: PrepareRunAfterCaptureContext,
    ) -> PrepareRunGateResult | None:
        """Optionally validate identities after strict capture and before version probes.

        The default is a no-op for existing plugins. A plugin that requires the
        gate must declare ``RunCapability.STRICT_CAPTURE_BINDING`` and override
        this method; Core rejects a missing or non-typed result before proceeding.
        """
        del prepared, context
        return None

    # -- optional overridable pipeline -----------------------------------------

    def run_pipeline(
        self,
        case: dict[str, Any],
        topology: Any,
    ) -> dict[str, Any]:
        """Execute the full case pipeline: setup → verify → steps → evaluate → teardown.

        Plugins may override this to customise execution order or add
        additional phases.  The default implementation mirrors the
        ExecutionEngine contract.
        """
        admission = admit_run_capabilities(
            self,
            None,
            default_gate_hook=PluginBase.prepare_run_after_capture,
        )
        if admission.outcome is not RunCapabilityAdmissionOutcome.LEGACY:
            raise RuntimeError("strict run requires Core-owned context-bearing lifecycle")

        commands: list[str] = []
        outputs: list[str] = []
        verdict = False
        comment = ""

        runtime_case = dict(case)
        runtime_case.pop("_last_failure", None)
        runtime_case["_attempt_index"] = 1

        def current_failure_snapshot() -> Mapping[str, Any] | None:
            failure = runtime_case.get("_last_failure")
            if not isinstance(failure, Mapping):
                return None
            if failure.get("case_id") != str(runtime_case.get("id", "")):
                return None
            attempt_index = failure.get("attempt_index")
            if (
                not isinstance(attempt_index, int)
                or isinstance(attempt_index, bool)
                or attempt_index != 1
            ):
                return None
            return failure

        def current_explicit_failure_abort() -> tuple[bool, str, bool, Mapping[str, Any] | None]:
            failure = current_failure_snapshot()
            if failure is None or failure.get("abort_run") is not True:
                return False, "", False, None

            raw_reason = failure.get("abort_reason") or failure.get("reason_code")
            reason = str(raw_reason or _DEFAULT_PLUGIN_ABORT_REASON).strip()[:128]
            if _ABORT_REASON_PATTERN.fullmatch(reason) is None:
                reason = _DEFAULT_PLUGIN_ABORT_REASON
            return True, reason, failure.get("skip_teardown") is True, dict(failure)

        unknown_outcome = False
        plugin_abort_run = False
        plugin_abort_reason = ""
        skip_teardown = False
        plugin_failure_snapshot: Mapping[str, Any] | None = None
        transport_evidence: dict[str, Any] = {}
        cleanup_result: dict[str, Any] | None = None
        try:
            if not self.setup_env(runtime_case, topology):
                comment = "setup_env failed"
                failure = current_failure_snapshot()
                unknown_outcome = has_unknown_transport_outcome(failure)
                transport_evidence = project_transport_evidence(failure)
                (
                    plugin_abort_run,
                    plugin_abort_reason,
                    skip_teardown,
                    plugin_failure_snapshot,
                ) = current_explicit_failure_abort()
            elif not self.verify_env(runtime_case, topology):
                comment = "env_verify gate failed"
                failure = current_failure_snapshot()
                unknown_outcome = has_unknown_transport_outcome(failure)
                transport_evidence = project_transport_evidence(failure)
                (
                    plugin_abort_run,
                    plugin_abort_reason,
                    skip_teardown,
                    plugin_failure_snapshot,
                ) = current_explicit_failure_abort()
            else:
                step_results: dict[str, Any] = {}
                raw_steps = runtime_case.get("steps", [])
                steps = raw_steps if isinstance(raw_steps, list) else []
                for step in steps:
                    step_data = dict(step) if isinstance(step, dict) else {"id": "step", "command": str(step)}
                    step_id = str(step_data.get("id", "step"))
                    cmd = stringify_step_command(step_data.get("command"))
                    # Keep commands/outputs index-aligned per step: a step with no
                    # command text or no output (e.g. a station verb with no key=value
                    # lines) still occupies its slot in BOTH lists, otherwise every
                    # later entry shifts up by one and evidence gets attributed to
                    # the wrong step (2026-09-17 EIT bench D259/D402 trace misread).
                    commands.append(cmd)
                    result = self.execute_step(runtime_case, step_data, topology)
                    step_results[step_id] = result
                    outputs.append(str(result.get("output", "")).strip())
                    failure = current_failure_snapshot()
                    if has_unknown_transport_outcome(result, failure):
                        unknown_outcome = True
                        transport_evidence = project_transport_evidence(
                            result,
                            failure,
                        )
                        comment = f"command outcome unknown: {step_id}"
                        break
                    if not result.get("success", False):
                        comment = f"step failed: {step_id}"
                        (
                            plugin_abort_run,
                            plugin_abort_reason,
                            skip_teardown,
                            plugin_failure_snapshot,
                        ) = current_explicit_failure_abort()
                        break

                if not comment:
                    verdict = self.evaluate(runtime_case, {"steps": step_results})
                    if not verdict:
                        comment = "pass_criteria not satisfied"
                        (
                            plugin_abort_run,
                            plugin_abort_reason,
                            skip_teardown,
                            plugin_failure_snapshot,
                        ) = current_explicit_failure_abort()

        except Exception as exc:
            failure = current_failure_snapshot()
            unknown_outcome = has_unknown_transport_outcome(exc, failure)
            transport_evidence = project_transport_evidence(exc, failure)
            comment = "command outcome unknown" if unknown_outcome else f"exception: {exc}"
            (
                plugin_abort_run,
                plugin_abort_reason,
                skip_teardown,
                plugin_failure_snapshot,
            ) = current_explicit_failure_abort()
        finally:
            unknown_outcome = unknown_outcome or has_unknown_transport_outcome(
                current_failure_snapshot()
            )
            if not unknown_outcome and not skip_teardown:
                try:
                    cleanup_result = normalize_cleanup_result(
                        self.teardown(runtime_case, topology)
                    )
                except Exception:
                    cleanup_result = cleanup_exception_result()

        result_payload: dict[str, Any] = {
            "verdict": verdict,
            "comment": comment,
            "commands": commands,
            "outputs": outputs,
        }
        if unknown_outcome:
            result_payload.update(
                {
                    "verdict": False,
                    "comment": comment or "command outcome unknown",
                    "failure_snapshot": {
                        "case_id": str(runtime_case.get("id", "")),
                        "attempt_index": 1,
                        "category": "environment",
                        "reason_code": "command_outcome_unknown",
                        "comment": comment or "command outcome unknown",
                        "transport_result": transport_evidence,
                    },
                    "diagnostic_status": "FailEnv",
                    "abort_run": True,
                    "abort_reason": "command_outcome_unknown",
                    "transport_result": transport_evidence,
                }
            )
        elif cleanup_result is not None:
            snapshot = cleanup_failure_snapshot(
                cleanup_result,
                case_id=runtime_case.get("id", ""),
                attempt_index=1,
            )
            result_payload.update(
                {
                    "verdict": False,
                    "comment": cleanup_result["comment"],
                    "failure_snapshot": snapshot,
                    "diagnostic_status": "FailEnv",
                    "abort_run": True,
                    "abort_reason": cleanup_result["reason_code"],
                    "transport_result": dict(cleanup_result["transport_result"]),
                }
            )
        elif plugin_abort_run and plugin_failure_snapshot is not None:
            category = str(plugin_failure_snapshot.get("category", "")).strip().lower()
            if category in {"environment", "session"}:
                diagnostic_status = "FailEnv"
            elif category in {"configuration", "config"}:
                diagnostic_status = "FailConfig"
            elif category in {"test", "semantic"}:
                diagnostic_status = "FailTest"
            else:
                diagnostic_status = "Inconclusive"
            transport_evidence = project_transport_evidence(
                transport_evidence,
                plugin_failure_snapshot,
            )
            result_payload.update(
                {
                    "verdict": False,
                    "failure_snapshot": dict(plugin_failure_snapshot),
                    "diagnostic_status": diagnostic_status,
                    "abort_run": True,
                    "abort_reason": plugin_abort_reason,
                    "transport_result": transport_evidence,
                }
            )
        return result_payload
