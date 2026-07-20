"""PluginBase — abstract base class for all test plugins."""

from __future__ import annotations

from abc import ABC, abstractmethod
import inspect
from pathlib import Path
from typing import Any, Sequence

from testpilot.core.case_utils import case_matches_requested_ids, stringify_step_command
from testpilot.core.prepared_run import PreparedRun


class IncompatiblePluginError(Exception):
    """Plugin SDK API version is incompatible or undeclared."""


class PluginBase(ABC):
    """各測試類型 plugin 繼承此基底類別。

    Plugin 負責：
    1. 發現並載入 cases/*.yaml
    2. 依 case 描述佈建測試環境
    3. 執行測試步驟
    4. 評估通過條件
    5. 清理環境
    """

    api_version: str | None = None

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
        """依 case 描述佈建測試環境（DUT/STA/EndpointPC）。

        預設實作直接回傳 True（不需佈建）。子類別可覆寫。

        Returns:
            True if setup succeeded.
        """
        return True

    def verify_env(self, case: dict[str, Any], topology: Any) -> bool:
        """環境自檢：驗證連線、服務就緒。

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

    def teardown(self, case: dict[str, Any], topology: Any) -> None:
        """清理測試環境。預設為 no-op；子類別可覆寫。"""

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
        commands: list[str] = []
        outputs: list[str] = []
        verdict = False
        comment = ""

        try:
            if not self.setup_env(case, topology):
                return {"verdict": False, "comment": "setup_env failed", "commands": [], "outputs": []}
            if not self.verify_env(case, topology):
                return {"verdict": False, "comment": "env_verify gate failed", "commands": [], "outputs": []}

            step_results: dict[str, Any] = {}
            raw_steps = case.get("steps", [])
            steps = raw_steps if isinstance(raw_steps, list) else []
            for step in steps:
                step_data = dict(step) if isinstance(step, dict) else {"id": "step", "command": str(step)}
                step_id = str(step_data.get("id", "step"))
                cmd = stringify_step_command(step_data.get("command"))
                if cmd:
                    commands.append(cmd)
                result = self.execute_step(case, step_data, topology)
                step_results[step_id] = result
                out = str(result.get("output", "")).strip()
                if out:
                    outputs.append(out)
                if not result.get("success", False):
                    comment = f"step failed: {step_id}"
                    break

            if not comment:
                verdict = self.evaluate(case, {"steps": step_results})
                if not verdict:
                    comment = "pass_criteria not satisfied"

        except Exception as exc:
            comment = f"exception: {exc}"
        finally:
            self.teardown(case, topology)

        return {
            "verdict": verdict,
            "comment": comment,
            "commands": commands,
            "outputs": outputs,
        }
