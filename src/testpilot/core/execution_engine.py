"""ExecutionEngine — case execution with retry, timeout escalation, and trace writing."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

from testpilot.core.case_utils import safe_float, safe_int, stringify_step_command
from testpilot.core.hook_policy import HookContext, HookDispatcher
from testpilot.core.runner_selector import RunnerSelector

log = logging.getLogger(__name__)

_ABORT_REASON_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_DEFAULT_PLUGIN_ABORT_REASON = "plugin_failure_abort"


@dataclass(slots=True)
class RetryResult:
    """Structured result of a case execution with full retry history."""

    verdict: bool
    comment: str
    commands: list[str]
    outputs: list[str]
    attempts: list[dict[str, Any]]
    attempts_used: int
    max_attempts: int
    diagnostic_status: str = ""
    remediation_history: list[dict[str, Any]] | None = None
    failure_snapshot: dict[str, Any] | None = None
    tier2_audit: list[dict[str, Any]] | None = None
    agent_recovered: bool = False
    abort_run: bool = False
    abort_reason: str = ""


class ExecutionEngine:
    """Execute a single case through plugin hooks with retry and timeout escalation."""

    def __init__(
        self,
        config: Any,
        hook_dispatcher: HookDispatcher | None = None,
    ) -> None:
        self.config = config
        self.hooks = hook_dispatcher or HookDispatcher()

    @classmethod
    def _transport_evidence(cls, value: Any) -> dict[str, Any]:
        return cls._merge_transport_evidence(value)

    @staticmethod
    def _merge_transport_evidence(*values: Any) -> dict[str, Any]:
        """Project transport fields from all surfaces without losing uncertainty.

        Exceptions may expose both ``result`` and ``transport_result``. Plugin
        failure snapshots and hook payloads may also carry the same receipt.
        Preserve the first ordinary value, but let any explicit unknown marker
        dominate a conflicting benign projection.
        """
        fields = (
            "error_code", "retry_after_s", "recommended_action", "cmd_id",
            "outcome", "ambiguous", "non_replayable", "retryable", "partial", "status",
            "input_integrity", "tx_bytes", "sent_chars", "acked_chars",
            "newline_sent", "session_recovered", "recovery_error",
        )
        sources: list[Mapping[str, Any]] = []
        for value in values:
            if isinstance(value, BaseException):
                result = getattr(value, "result", None)
                transport_result = getattr(value, "transport_result", None)
                if isinstance(result, Mapping):
                    sources.append(result)
                if isinstance(transport_result, Mapping):
                    sources.append(transport_result)
            elif isinstance(value, Mapping):
                sources.append(value)

        evidence: dict[str, Any] = {}
        for source in sources:
            for key in fields:
                if key in source and key not in evidence:
                    evidence[key] = source[key]

        uncertain_sources = [
            source for source in sources
            if (
                str(source.get("outcome") or "").strip().lower() in {"unknown", "ambiguous"}
                or source.get("ambiguous") is True
                or source.get("non_replayable") is True
                or source.get("partial") is True
                or str(source.get("input_integrity") or "").strip().lower() == "uncertain"
                or str(source.get("error_code") or "").strip().upper() == "COMMAND_OUTCOME_UNKNOWN"
            )
        ]
        for source in uncertain_sources:
            if source.get("cmd_id"):
                evidence["cmd_id"] = source["cmd_id"]
                break

        for key in ("ambiguous", "non_replayable", "partial"):
            if any(source.get(key) is True for source in sources):
                evidence[key] = True

        outcomes = [str(source.get("outcome") or "").strip().lower() for source in sources]
        if "unknown" in outcomes:
            evidence["outcome"] = "unknown"
        elif "ambiguous" in outcomes:
            evidence["outcome"] = "ambiguous"

        error_codes = [str(source.get("error_code") or "").strip().upper() for source in sources]
        if "COMMAND_OUTCOME_UNKNOWN" in error_codes:
            evidence["error_code"] = "COMMAND_OUTCOME_UNKNOWN"

        integrity_values = [
            str(source.get("input_integrity") or "").strip().lower()
            for source in sources
        ]
        if "uncertain" in integrity_values:
            evidence["input_integrity"] = "uncertain"

        if any(source.get("retryable") is False for source in sources):
            evidence["retryable"] = False
        return evidence

    @staticmethod
    def _unknown_outcome(evidence: dict[str, Any]) -> bool:
        return (
            str(evidence.get("outcome") or "").lower() in {"unknown", "ambiguous"}
            or evidence.get("ambiguous") is True
            or evidence.get("non_replayable") is True
            or evidence.get("partial") is True
            or str(evidence.get("input_integrity") or "").lower() == "uncertain"
            or str(evidence.get("error_code") or "").upper() == "COMMAND_OUTCOME_UNKNOWN"
        )

    @staticmethod
    def _current_failure_snapshot(
        runtime_case: Mapping[str, Any],
    ) -> Mapping[str, Any] | None:
        failure = runtime_case.get("_last_failure")
        if not isinstance(failure, Mapping):
            return None
        expected_case_id = str(runtime_case.get("id", ""))
        if failure.get("case_id") != expected_case_id:
            return None
        expected_attempt = runtime_case.get("_attempt_index", 1)
        failure_attempt = failure.get("attempt_index")
        if (
            not isinstance(expected_attempt, int)
            or isinstance(expected_attempt, bool)
            or not isinstance(failure_attempt, int)
            or isinstance(failure_attempt, bool)
            or failure_attempt != expected_attempt
        ):
            return None
        return failure

    @classmethod
    def _failure_snapshot_evidence(cls, runtime_case: Mapping[str, Any]) -> dict[str, Any]:
        failure = cls._current_failure_snapshot(runtime_case)
        if failure is None:
            return {}
        return cls._merge_transport_evidence(
            failure.get("metadata"), failure.get("transport_result")
        )

    @staticmethod
    def _explicit_failure_abort(
        runtime_case: Mapping[str, Any],
    ) -> tuple[bool, str, bool]:
        """Read a plugin's explicit terminal abort request from its failure snapshot.

        This path is independent of command receipt certainty. A plugin may stop
        the run for a terminal device state even when no command was accepted.
        """
        failure = ExecutionEngine._current_failure_snapshot(runtime_case)
        if failure is None or failure.get("abort_run") is not True:
            return False, "", False

        raw_reason = failure.get("abort_reason") or failure.get("reason_code")
        reason = str(raw_reason or _DEFAULT_PLUGIN_ABORT_REASON).strip()[:128]
        if _ABORT_REASON_PATTERN.fullmatch(reason) is None:
            reason = _DEFAULT_PLUGIN_ABORT_REASON
        return True, reason, failure.get("skip_teardown") is True

    @staticmethod
    def attempt_timeout_seconds(
        *,
        steps_count: int,
        attempt_index: int,
        execution_policy: dict[str, Any],
    ) -> float:
        timeout = execution_policy.get("timeout", {})
        if not isinstance(timeout, dict):
            timeout = {}
        base_seconds = max(1.0, safe_float(timeout.get("base_seconds"), 120.0))
        per_step_seconds = max(0.0, safe_float(timeout.get("per_step_seconds"), 45.0))
        retry_multiplier = max(1.0, safe_float(timeout.get("retry_multiplier"), 1.25))
        max_seconds = max(1.0, safe_float(timeout.get("max_seconds"), 900.0))

        raw_timeout = (base_seconds + max(0, steps_count) * per_step_seconds) * (
            retry_multiplier ** max(0, attempt_index - 1)
        )
        return min(max_seconds, raw_timeout)

    def _hook_ctx(
        self,
        hook_name: str,
        case: dict[str, Any],
        runner: dict[str, Any],
        attempt_index: int = 1,
        step_id: str | None = None,
    ) -> HookContext:
        return HookContext(
            hook_name=hook_name,
            case_id=str(case.get("id", "?")),
            plugin_name=str(case.get("_plugin", "")),
            attempt_index=attempt_index,
            step_id=step_id,
            runner=dict(runner),
        )

    @staticmethod
    def _classify_diagnostic_status(
        *,
        verdict: bool,
        remediation_history: list[dict[str, Any]],
        failure_snapshot: dict[str, Any] | None,
    ) -> str:
        if verdict:
            return "PassAfterRemediation" if remediation_history else "Pass"
        snapshot = failure_snapshot or {}
        category = str(snapshot.get("category", "")).strip().lower()
        if category in {"environment", "session"}:
            return "FailEnv"
        if category in {"configuration", "config"}:
            return "FailConfig"
        if category in {"test", "semantic"}:
            return "FailTest"
        return "Inconclusive"

    def _dispatch_failure(
        self,
        *,
        runtime_case: dict[str, Any],
        runner: dict[str, Any],
        attempt_index: int,
        phase: str,
        comment: str,
        step_id: str | None = None,
        step_payload: dict[str, Any] | None = None,
        result: dict[str, Any] | None = None,
        exception: Exception | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "case": runtime_case,
            "phase": phase,
            "comment": comment,
        }
        failure_snapshot = self._current_failure_snapshot(runtime_case)
        if failure_snapshot is not None:
            payload["failure_snapshot"] = dict(failure_snapshot)
        if step_payload is not None:
            payload["step"] = dict(step_payload)
        if result is not None:
            payload["result"] = dict(result)
        if exception is not None:
            payload["exception"] = str(exception)
        evidence = self._merge_transport_evidence(
            result,
            exception,
            self._failure_snapshot_evidence(runtime_case),
        )
        if evidence:
            payload["transport_result"] = evidence
        self.hooks.dispatch(
            self._hook_ctx("on_failure", runtime_case, runner, attempt_index, step_id),
            payload,
        )
        return payload

    def execute_case_once(
        self,
        plugin: Any,
        case: dict[str, Any],
        *,
        attempt_index: int,
        attempt_timeout_seconds: float,
        runner: dict[str, Any],
    ) -> dict[str, Any]:
        """Run setup → verify → steps → evaluate → teardown for one attempt."""
        commands: list[str] = []
        outputs: list[str] = []
        verdict = False
        comment = ""
        failure_payload: dict[str, Any] = {}
        transport_evidence: dict[str, Any] = {}
        unknown_outcome = False
        plugin_abort_run = False
        plugin_abort_reason = ""
        skip_teardown = False

        runtime_case = dict(case)
        # Runtime failure metadata belongs to one case attempt. A caller may
        # reuse or deserialize a case object containing stale scratch fields.
        runtime_case.pop("_last_failure", None)
        runtime_case["_agent_runner"] = RunnerSelector.runner_summary(runner)
        runtime_case["_attempt_index"] = attempt_index
        runtime_case["_attempt_timeout_seconds"] = attempt_timeout_seconds

        try:
            setup_ok = bool(plugin.setup_env(runtime_case, topology=self.config))
            if not setup_ok:
                transport_evidence = self._failure_snapshot_evidence(runtime_case)
                unknown_outcome = self._unknown_outcome(transport_evidence)
                comment = "setup_env failed"
                failure_payload = self._dispatch_failure(
                    runtime_case=runtime_case,
                    runner=runner,
                    attempt_index=attempt_index,
                    phase="setup_env",
                    comment=comment,
                )
                transport_evidence = self._merge_transport_evidence(
                    transport_evidence,
                    failure_payload.get("transport_result"),
                    self._failure_snapshot_evidence(runtime_case),
                )
                unknown_outcome = unknown_outcome or self._unknown_outcome(transport_evidence)
                plugin_abort_run, plugin_abort_reason, skip_teardown = (
                    self._explicit_failure_abort(runtime_case)
                )
            env_ok = setup_ok and bool(plugin.verify_env(runtime_case, topology=self.config))
            if setup_ok and not env_ok:
                transport_evidence = self._failure_snapshot_evidence(runtime_case)
                unknown_outcome = self._unknown_outcome(transport_evidence)
                comment = "env_verify gate failed"
                failure_payload = self._dispatch_failure(
                    runtime_case=runtime_case,
                    runner=runner,
                    attempt_index=attempt_index,
                    phase="verify_env",
                    comment=comment,
                )
                transport_evidence = self._merge_transport_evidence(
                    transport_evidence,
                    failure_payload.get("transport_result"),
                    self._failure_snapshot_evidence(runtime_case),
                )
                unknown_outcome = unknown_outcome or self._unknown_outcome(transport_evidence)
                plugin_abort_run, plugin_abort_reason, skip_teardown = (
                    self._explicit_failure_abort(runtime_case)
                )

            step_results: dict[str, Any] = {}
            raw_steps = runtime_case.get("steps", [])
            steps = raw_steps if isinstance(raw_steps, list) else []
            if env_ok:
                for step in steps:
                    step_data = dict(step) if isinstance(step, dict) else {"id": "step", "command": str(step)}
                    step_id = str(step_data.get("id", "step"))
                    command = stringify_step_command(step_data.get("command"))

                    step_payload = dict(step_data)
                    step_payload.setdefault("timeout", attempt_timeout_seconds)
                    step_payload["_attempt_index"] = attempt_index
                    step_payload["_attempt_timeout_seconds"] = attempt_timeout_seconds
                    runtime_case["_step_results"] = step_results

                    # pre_step hook
                    pre = self.hooks.dispatch(
                        self._hook_ctx("pre_step", runtime_case, runner, attempt_index, step_id),
                        {"step": step_payload},
                    )
                    if not pre.proceed:
                        comment = f"pre_step hook halted: {pre.advice}"
                        break

                    result = plugin.execute_step(runtime_case, step_payload, topology=self.config)
                    step_results[step_id] = result
                    # One slot per executed step in BOTH lists (empty string when a
                    # step has no command text / no output) so agent_trace
                    # attempts[].commands[i] always pairs with outputs[i].
                    executed_command = str(result.get("command", "")).strip() or command
                    commands.append(executed_command)
                    outputs.append(str(result.get("output", "")).strip())

                    # post_step hook
                    self.hooks.dispatch(
                        self._hook_ctx("post_step", runtime_case, runner, attempt_index, step_id),
                        {"step": step_payload, "result": result},
                    )

                    if not bool(result.get("success", False)):
                        transport_evidence = self._transport_evidence(result)
                        unknown_outcome = self._unknown_outcome(transport_evidence)
                        comment = f"step failed: {step_id}"
                        failure_payload = self._dispatch_failure(
                            runtime_case=runtime_case,
                            runner=runner,
                            attempt_index=attempt_index,
                            phase="execute_step",
                            comment=comment,
                            step_id=step_id,
                            step_payload=step_payload,
                            result=result,
                        )
                        transport_evidence = self._merge_transport_evidence(
                            transport_evidence,
                            failure_payload.get("transport_result"),
                            self._failure_snapshot_evidence(runtime_case),
                        )
                        unknown_outcome = unknown_outcome or self._unknown_outcome(transport_evidence)
                        plugin_abort_run, plugin_abort_reason, skip_teardown = (
                            self._explicit_failure_abort(runtime_case)
                        )
                        break

                if not comment:
                    verdict = bool(plugin.evaluate(runtime_case, {"steps": step_results}))
                    if not verdict:
                        last_failure = runtime_case.get("_last_failure")
                        if isinstance(last_failure, dict):
                            comment = str(last_failure.get("comment") or "pass_criteria not satisfied")
                        else:
                            comment = "pass_criteria not satisfied"
                        failure_payload = self._dispatch_failure(
                            runtime_case=runtime_case,
                            runner=runner,
                            attempt_index=attempt_index,
                            phase="evaluate",
                            comment=comment,
                        )
                        transport_evidence = self._merge_transport_evidence(
                            transport_evidence,
                            failure_payload.get("transport_result"),
                            self._failure_snapshot_evidence(runtime_case),
                        )
                        unknown_outcome = unknown_outcome or self._unknown_outcome(transport_evidence)
                        plugin_abort_run, plugin_abort_reason, skip_teardown = (
                            self._explicit_failure_abort(runtime_case)
                        )

        except Exception as exc:  # pragma: no cover - defensive catch for runtime errors
            transport_evidence = self._transport_evidence(exc)
            unknown_outcome = self._unknown_outcome(transport_evidence)
            comment = f"exception: {exc}"
            failure_payload = self._dispatch_failure(
                runtime_case=runtime_case,
                runner=runner,
                attempt_index=attempt_index,
                phase="exception",
                comment=comment,
                exception=exc,
            )
            transport_evidence = self._merge_transport_evidence(
                transport_evidence,
                failure_payload.get("transport_result"),
                self._failure_snapshot_evidence(runtime_case),
            )
            unknown_outcome = unknown_outcome or self._unknown_outcome(transport_evidence)
            plugin_abort_run, plugin_abort_reason, skip_teardown = (
                self._explicit_failure_abort(runtime_case)
            )
        finally:
            if not unknown_outcome and not skip_teardown:
                try:
                    plugin.teardown(runtime_case, topology=self.config)
                except Exception:
                    log.exception("teardown failed: %s", runtime_case.get("id", "?"))

        if unknown_outcome and not failure_payload.get("failure_snapshot"):
            failure_payload["failure_snapshot"] = {
                "category": "environment", "reason_code": "command_outcome_unknown",
                "metadata": transport_evidence,
            }

        return {
            "verdict": verdict,
            "comment": comment,
            "commands": commands,
            "outputs": outputs,
            "failure_snapshot": failure_payload.get("failure_snapshot"),
            "remediation_decision": failure_payload.get("remediation_decision"),
            "transport_result": transport_evidence,
            "abort_run": unknown_outcome or plugin_abort_run,
            "abort_reason": (
                "command_outcome_unknown"
                if unknown_outcome
                else plugin_abort_reason if plugin_abort_run else ""
            ),
        }

    def execute_with_retry(
        self,
        plugin: Any,
        case: dict[str, Any],
        *,
        runner: dict[str, Any],
        execution_policy: dict[str, Any],
    ) -> RetryResult:
        """Execute a case with retry logic and return full attempt history."""
        retry_cfg = execution_policy.get("retry", {})
        if not isinstance(retry_cfg, dict):
            retry_cfg = {}
        max_attempts = max(1, safe_int(retry_cfg.get("max_attempts"), 1))
        failure_policy = str(
            execution_policy.get("failure_policy", "retry_then_fail_and_continue")
        )

        raw_steps = case.get("steps", [])
        steps_count = len(raw_steps) if isinstance(raw_steps, list) else 0

        attempts: list[dict[str, Any]] = []
        final_verdict = False
        final_commands: list[str] = []
        final_outputs: list[str] = []
        final_comment = ""
        final_failure_snapshot: dict[str, Any] | None = None
        remediation_history: list[dict[str, Any]] = []
        tier2_audit: list[dict[str, Any]] = []
        agent_recovered = False
        abort_run = False
        abort_reason = ""

        # pre_case hook
        pre_case_payload = {
            "execution_policy": execution_policy,
            "max_attempts": max_attempts,
        }
        self.hooks.dispatch(
            self._hook_ctx("pre_case", case, runner),
            pre_case_payload,
        )
        max_attempts = max(
            1,
            safe_int(pre_case_payload.get("max_attempts"), max_attempts),
        )

        for attempt_index in range(1, max_attempts + 1):
            # on_retry hook (for attempts after the first)
            if attempt_index > 1:
                retry_payload = {
                    "case": dict(case),
                    "previous_attempts": attempts,
                    "attempt_index": attempt_index,
                }
                retry_hook_result = self.hooks.dispatch(
                    self._hook_ctx("on_retry", case, runner, attempt_index),
                    retry_payload,
                )
                raw_history = retry_payload.get("remediation_history")
                if isinstance(raw_history, list):
                    remediation_history = [
                        dict(item)
                        for item in raw_history
                        if isinstance(item, dict)
                    ]
                else:
                    trace_entry = retry_payload.get("remediation_trace_entry")
                    if isinstance(trace_entry, dict):
                        remediation_history.append(dict(trace_entry))
                raw_tier2_audit = retry_payload.get("tier2_audit")
                if isinstance(raw_tier2_audit, list):
                    tier2_audit = [
                        dict(item)
                        for item in raw_tier2_audit
                        if isinstance(item, dict)
                    ]
                agent_recovered = bool(
                    retry_payload.get("agent_recovered", agent_recovered)
                )
                retry_failure = retry_payload.get("failure_snapshot")
                if isinstance(retry_failure, dict):
                    final_failure_snapshot = dict(retry_failure)
                if retry_payload.get("abort_run") is True:
                    abort_run = True
                    abort_reason = str(retry_payload.get("abort_reason") or "remediation_readiness_failed")
                    final_verdict = False
                    final_comment = retry_hook_result.advice or abort_reason
                    break
                if not retry_hook_result.proceed:
                    final_verdict = False
                    final_comment = (
                        retry_hook_result.advice
                        or "on_retry hook halted before case execution"
                    )
                    break

            timeout = self.attempt_timeout_seconds(
                steps_count=steps_count,
                attempt_index=attempt_index,
                execution_policy=execution_policy,
            )
            result = self.execute_case_once(
                plugin=plugin,
                case=case,
                attempt_index=attempt_index,
                attempt_timeout_seconds=timeout,
                runner=runner,
            )

            final_verdict = bool(result.get("verdict", False))
            final_commands = [str(x) for x in result.get("commands", [])]
            final_outputs = [str(x) for x in result.get("outputs", [])]
            final_comment = str(result.get("comment", ""))
            if isinstance(result.get("failure_snapshot"), dict):
                final_failure_snapshot = dict(result["failure_snapshot"])

            attempts.append({
                "attempt": attempt_index,
                "timeout_seconds": timeout,
                "runner": RunnerSelector.runner_summary(runner),
                "verdict": final_verdict,
                "evaluation_verdict": "Pass" if final_verdict else "Fail",
                "comment": final_comment,
                "commands": final_commands,
                "outputs": final_outputs,
                "failure_snapshot": result.get("failure_snapshot"),
                "remediation_decision": result.get("remediation_decision"),
                "transport_result": result.get("transport_result", {}),
                "abort_run": result.get("abort_run") is True,
                "abort_reason": str(result.get("abort_reason") or ""),
            })

            if result.get("abort_run") is True:
                abort_run = True
                abort_reason = str(result.get("abort_reason") or "command_outcome_unknown")
                final_verdict = False
                break
            if final_verdict:
                break
            should_retry = (
                failure_policy == "retry_then_fail_and_continue"
                and attempt_index < max_attempts
            )
            if not should_retry:
                break

        attempts_used = len(attempts)
        if final_verdict and attempts_used > 1 and not final_comment:
            final_comment = f"pass after retry ({attempts_used}/{max_attempts})"
        if not final_verdict and attempts_used > 1:
            if final_comment:
                final_comment = f"{final_comment} (failed after {attempts_used}/{max_attempts} attempts)"
            else:
                final_comment = f"failed after {attempts_used}/{max_attempts} attempts"

        diagnostic_status = self._classify_diagnostic_status(
            verdict=final_verdict,
            remediation_history=remediation_history,
            failure_snapshot=final_failure_snapshot,
        )

        # post_case hook
        post_case_payload = {
            "verdict": final_verdict,
            "attempts_used": attempts_used,
            "comment": final_comment,
            "diagnostic_status": diagnostic_status,
            "remediation_history": remediation_history,
            "failure_snapshot": final_failure_snapshot,
            "tier2_audit": tier2_audit,
            "agent_recovered": agent_recovered,
        }
        self.hooks.dispatch(
            self._hook_ctx(
                "post_case",
                case,
                runner,
                max(1, attempts_used),
            ),
            post_case_payload,
        )
        remediation_history = [
            dict(item)
            for item in post_case_payload.get("remediation_history", remediation_history)
            if isinstance(item, dict)
        ]
        maybe_failure_snapshot = post_case_payload.get("failure_snapshot")
        if isinstance(maybe_failure_snapshot, dict):
            final_failure_snapshot = dict(maybe_failure_snapshot)
        raw_tier2_audit = post_case_payload.get("tier2_audit")
        if isinstance(raw_tier2_audit, list):
            tier2_audit = [
                dict(item)
                for item in raw_tier2_audit
                if isinstance(item, dict)
            ]
        agent_recovered = bool(
            post_case_payload.get("agent_recovered", agent_recovered)
        )
        diagnostic_status = self._classify_diagnostic_status(
            verdict=final_verdict,
            remediation_history=remediation_history,
            failure_snapshot=final_failure_snapshot,
        )

        return RetryResult(
            verdict=final_verdict,
            comment=final_comment,
            commands=final_commands,
            outputs=final_outputs,
            attempts=attempts,
            attempts_used=attempts_used,
            max_attempts=max_attempts,
            diagnostic_status=diagnostic_status,
            remediation_history=remediation_history,
            failure_snapshot=final_failure_snapshot,
            tier2_audit=tier2_audit,
            agent_recovered=agent_recovered,
            abort_run=abort_run,
            abort_reason=abort_reason,
        )

    @staticmethod
    def write_case_trace(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
