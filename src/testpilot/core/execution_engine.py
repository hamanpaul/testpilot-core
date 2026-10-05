"""ExecutionEngine — case execution with retry, timeout escalation, and trace writing."""

from __future__ import annotations

from copy import deepcopy
import inspect
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

from testpilot.core.case_utils import safe_float, safe_int, stringify_step_command
from testpilot.core.cleanup_result import (
    cleanup_exception_result,
    cleanup_failure_snapshot,
    has_unknown_transport_outcome,
    normalize_cleanup_result,
    project_transport_evidence,
)
from testpilot.core.hook_policy import HookContext, HookDispatcher, HookResult
from testpilot.core.runner_selector import RunnerSelector

log = logging.getLogger(__name__)

_ABORT_REASON_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_DEFAULT_PLUGIN_ABORT_REASON = "plugin_failure_abort"
_HOOK_CONTEXT_FIELDS = frozenset(
    {
        "hook_name",
        "case_id",
        "plugin_name",
        "attempt_index",
        "step_id",
        "runner",
        "extra",
    }
)
_HOOK_ENVELOPE_FIELDS = frozenset({"data", "context"})
_HOOK_RESULT_FIELD = "__testpilot_hook_result__"
_FAILURE_HOOK_CONTROLS = frozenset(
    {
        "failure_snapshot",
        "transport_result",
        "remediation_decision",
        "remediation_history",
        "remediation_trace_entry",
        "tier2_audit",
        "agent_recovered",
        "abort_run",
        "abort_reason",
    }
)


class _HookPayloadProjectionError(Exception):
    """Internal fail-closed signal with no plugin-controlled exception text."""

    def __init__(self) -> None:
        super().__init__("hook_payload_projection_failed")


@dataclass(slots=True)
class _ProjectedHookDispatch:
    result: HookResult
    public_data: dict[str, Any]
    returned_data: dict[str, Any]


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

    @staticmethod
    def _hook_context_data(ctx: HookContext) -> dict[str, Any]:
        return {
            "hook_name": ctx.hook_name,
            "case_id": ctx.case_id,
            "plugin_name": ctx.plugin_name,
            "attempt_index": ctx.attempt_index,
            "step_id": ctx.step_id,
            "runner": ctx.runner,
            "extra": ctx.extra,
        }

    @staticmethod
    def _validate_projected_envelope(
        envelope: Any,
        *,
        hook_name: str,
    ) -> dict[str, Any]:
        if type(envelope) is not dict or set(envelope) != _HOOK_ENVELOPE_FIELDS:
            raise _HookPayloadProjectionError()
        data = envelope.get("data")
        context = envelope.get("context")
        if type(data) is not dict or type(context) is not dict:
            raise _HookPayloadProjectionError()
        if set(context) != _HOOK_CONTEXT_FIELDS:
            raise _HookPayloadProjectionError()
        if (
            type(context.get("hook_name")) is not str
            or context["hook_name"] != hook_name
            or type(context.get("case_id")) is not str
            or type(context.get("plugin_name")) is not str
            or type(context.get("attempt_index")) is not int
            or (
                context.get("step_id") is not None
                and type(context.get("step_id")) is not str
            )
            or type(context.get("runner")) is not dict
            or type(context.get("extra")) is not dict
        ):
            raise _HookPayloadProjectionError()
        return envelope

    def _project_hook_envelope(
        self,
        plugin: Any,
        ctx: HookContext,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """Copy and validate one plugin-projected public hook envelope."""
        try:
            envelope = deepcopy(
                {"data": data, "context": self._hook_context_data(ctx)}
            )
            try:
                inspect.getattr_static(type(plugin), "project_hook_payload")
            except AttributeError:
                projector = None
            else:
                projector = getattr(plugin, "project_hook_payload", None)
                if not callable(projector):
                    raise _HookPayloadProjectionError()
            projected = (
                projector(ctx.hook_name, envelope)
                if projector is not None
                else envelope
            )
            copied = deepcopy(projected)
            return self._validate_projected_envelope(
                copied,
                hook_name=ctx.hook_name,
            )
        except _HookPayloadProjectionError:
            raise
        except Exception:
            # Do not retain or format projector/deepcopy exception contents.
            raise _HookPayloadProjectionError() from None

    def _dispatch_projected_hook(
        self,
        plugin: Any,
        ctx: HookContext,
        data: dict[str, Any],
    ) -> _ProjectedHookDispatch:
        """Dispatch only a detached projection, then reproject returned controls."""
        envelope = self._project_hook_envelope(plugin, ctx, data)
        public_data = envelope["data"]
        projected_context = envelope["context"]
        try:
            dispatch_data = deepcopy(public_data)
            dispatch_ctx = HookContext(**projected_context)
            result = self.hooks.dispatch(dispatch_ctx, dispatch_data)
            if (
                not isinstance(result, HookResult)
                or type(result.proceed) is not bool
                or type(result.advice) is not str
            ):
                raise _HookPayloadProjectionError()
            returned_data = deepcopy(dispatch_data)
            returned_data[_HOOK_RESULT_FIELD] = {
                "proceed": result.proceed,
                "advice": result.advice,
            }
            returned_context = HookContext(
                hook_name=ctx.hook_name,
                case_id=ctx.case_id,
                plugin_name=ctx.plugin_name,
                attempt_index=ctx.attempt_index,
                step_id=ctx.step_id,
                runner=dispatch_ctx.runner,
                extra=dispatch_ctx.extra,
            )
            returned_envelope = self._project_hook_envelope(
                plugin,
                returned_context,
                returned_data,
            )
            projected_result = returned_envelope["data"].pop(
                _HOOK_RESULT_FIELD, None
            )
            if (
                type(projected_result) is not dict
                or set(projected_result) != {"proceed", "advice"}
                or type(projected_result.get("proceed")) is not bool
                or type(projected_result.get("advice")) is not str
            ):
                raise _HookPayloadProjectionError()
            return _ProjectedHookDispatch(
                result=HookResult(
                    proceed=projected_result["proceed"],
                    advice=projected_result["advice"],
                ),
                public_data=public_data,
                returned_data=returned_envelope["data"],
            )
        except _HookPayloadProjectionError:
            raise
        except Exception:
            raise _HookPayloadProjectionError() from None

    @staticmethod
    def _merge_hook_controls(
        public_data: dict[str, Any],
        returned_data: Mapping[str, Any],
        allowed_fields: set[str] | frozenset[str],
    ) -> dict[str, Any]:
        merged = dict(public_data)
        for field in allowed_fields:
            if field in returned_data:
                merged[field] = returned_data[field]
        return merged

    @staticmethod
    def _hook_abort_reason(payload: Mapping[str, Any]) -> tuple[bool, str]:
        if payload.get("abort_run") is not True:
            return False, ""
        reason = payload.get("abort_reason")
        if type(reason) is str and _ABORT_REASON_PATTERN.fullmatch(reason):
            return True, reason
        return True, _DEFAULT_PLUGIN_ABORT_REASON

    @classmethod
    def _transport_evidence(cls, value: Any) -> dict[str, Any]:
        return cls._merge_transport_evidence(value)

    @staticmethod
    def _merge_transport_evidence(*values: Any) -> dict[str, Any]:
        """Project transport fields from all surfaces without losing uncertainty.

        Receipt traversal and validation share the bounded fail-closed projection
        used by the cleanup-result contract.
        """
        return project_transport_evidence(*values)

    @staticmethod
    def _unknown_outcome(evidence: dict[str, Any]) -> bool:
        return has_unknown_transport_outcome(evidence)

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
        plugin: Any,
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
        else:
            # Do not let a stale or malformed plugin snapshot influence
            # coordinator decisions through the case argument. Keep the
            # runtime case itself intact for result handling.
            hook_case = dict(runtime_case)
            hook_case.pop("_last_failure", None)
            payload["case"] = hook_case
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
        ctx = self._hook_ctx(
            "on_failure", runtime_case, runner, attempt_index, step_id
        )
        if self._unknown_outcome(evidence):
            projected = self._project_hook_envelope(plugin, ctx, payload)
            returned_data = projected["data"]
        else:
            dispatch = self._dispatch_projected_hook(plugin, ctx, payload)
            returned_data = self._merge_hook_controls(
                dispatch.public_data,
                dispatch.returned_data,
                _FAILURE_HOOK_CONTROLS,
            )

        returned_evidence = self._merge_transport_evidence(
            returned_data.get("transport_result"),
            returned_data.get("failure_snapshot"),
        )
        evidence = self._merge_transport_evidence(evidence, returned_evidence)
        if evidence:
            returned_data["transport_result"] = evidence
        return returned_data

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
        cleanup_result: dict[str, Any] | None = None
        inflight_step = False

        runtime_case = dict(case)
        # Runtime failure metadata belongs to one case attempt. A caller may
        # reuse or deserialize a case object containing stale scratch fields.
        runtime_case.pop("_last_failure", None)
        runtime_case["_agent_runner"] = RunnerSelector.runner_summary(runner)
        runtime_case["_attempt_index"] = attempt_index
        runtime_case["_attempt_timeout_seconds"] = attempt_timeout_seconds

        def dispatch_failure(
            *,
            phase: str,
            reason: str,
            step_id: str | None = None,
            step_payload: dict[str, Any] | None = None,
            result: dict[str, Any] | None = None,
            exception: Exception | None = None,
        ) -> None:
            nonlocal comment
            nonlocal failure_payload
            nonlocal transport_evidence
            nonlocal unknown_outcome
            nonlocal plugin_abort_run
            nonlocal plugin_abort_reason
            nonlocal skip_teardown
            failure_payload = self._dispatch_failure(
                plugin=plugin,
                runtime_case=runtime_case,
                runner=runner,
                attempt_index=attempt_index,
                phase=phase,
                comment=reason,
                step_id=step_id,
                step_payload=step_payload,
                result=result,
                exception=exception,
            )
            transport_evidence = self._merge_transport_evidence(
                transport_evidence,
                failure_payload.get("transport_result"),
                self._failure_snapshot_evidence(runtime_case),
            )
            unknown_outcome = unknown_outcome or self._unknown_outcome(
                transport_evidence
            )
            snapshot_abort, snapshot_reason, snapshot_skip = (
                self._explicit_failure_abort(runtime_case)
            )
            hook_abort, hook_reason = self._hook_abort_reason(failure_payload)
            if snapshot_abort or hook_abort:
                plugin_abort_run = True
                plugin_abort_reason = (
                    hook_reason if hook_abort else snapshot_reason
                )
            skip_teardown = skip_teardown or snapshot_skip or unknown_outcome
            projected_comment = failure_payload.get("comment")
            if type(projected_comment) is str:
                comment = projected_comment
            if unknown_outcome:
                comment = "command outcome unknown"

        try:
            setup_ok = bool(plugin.setup_env(runtime_case, topology=self.config))
            transport_evidence = self._failure_snapshot_evidence(runtime_case)
            unknown_outcome = self._unknown_outcome(transport_evidence)
            if unknown_outcome:
                comment = "command outcome unknown"
                dispatch_failure(
                    phase="setup_env",
                    reason=comment,
                    result={"transport_result": transport_evidence},
                )
            elif not setup_ok:
                comment = "setup_env failed"
                dispatch_failure(phase="setup_env", reason=comment)

            env_ok = False
            if setup_ok and not unknown_outcome:
                verify_ok = bool(
                    plugin.verify_env(runtime_case, topology=self.config)
                )
                transport_evidence = self._merge_transport_evidence(
                    transport_evidence,
                    self._failure_snapshot_evidence(runtime_case),
                )
                unknown_outcome = self._unknown_outcome(transport_evidence)
                if unknown_outcome:
                    comment = "command outcome unknown"
                    dispatch_failure(
                        phase="verify_env",
                        reason=comment,
                        result={"transport_result": transport_evidence},
                    )
                elif not verify_ok:
                    comment = "env_verify gate failed"
                    dispatch_failure(phase="verify_env", reason=comment)
                else:
                    env_ok = True

            step_results: dict[str, Any] = {}
            raw_steps = runtime_case.get("steps", [])
            steps = raw_steps if isinstance(raw_steps, list) else []
            if env_ok and not unknown_outcome:
                for step in steps:
                    step_data = dict(step) if isinstance(step, dict) else {"id": "step", "command": str(step)}
                    step_id = str(step_data.get("id", "step"))

                    step_payload = dict(step_data)
                    step_payload.setdefault("timeout", attempt_timeout_seconds)
                    step_payload["_attempt_index"] = attempt_index
                    step_payload["_attempt_timeout_seconds"] = attempt_timeout_seconds
                    runtime_case["_step_results"] = step_results

                    # pre_step hook
                    pre = self._dispatch_projected_hook(
                        plugin,
                        self._hook_ctx(
                            "pre_step", runtime_case, runner, attempt_index, step_id
                        ),
                        {"step": step_payload},
                    )
                    if not pre.result.proceed:
                        comment = f"pre_step hook halted: {pre.result.advice}"
                        break

                    inflight_step = True
                    result = plugin.execute_step(runtime_case, step_payload, topology=self.config)
                    step_evidence = self._merge_transport_evidence(
                        result,
                        self._failure_snapshot_evidence(runtime_case),
                    )
                    if self._unknown_outcome(step_evidence):
                        transport_evidence = step_evidence
                        unknown_outcome = True
                        comment = f"command outcome unknown: {step_id}"
                        dispatch_failure(
                            phase="execute_step",
                            reason=comment,
                            step_id=step_id,
                            step_payload=step_payload,
                            result={"transport_result": step_evidence},
                        )
                        safe_step = failure_payload.get("step")
                        safe_step = safe_step if type(safe_step) is dict else {}
                        safe_command = stringify_step_command(
                            safe_step.get("command")
                        )
                        commands.append(safe_command)
                        outputs.append("")
                        inflight_step = False
                        break

                    step_results[step_id] = result
                    post = self._dispatch_projected_hook(
                        plugin,
                        self._hook_ctx(
                            "post_step", runtime_case, runner, attempt_index, step_id
                        ),
                        {"step": step_payload, "result": result},
                    )
                    safe_step = post.public_data.get("step")
                    safe_result = post.public_data.get("result")
                    safe_step = safe_step if type(safe_step) is dict else {}
                    safe_result = safe_result if type(safe_result) is dict else {}
                    # One slot per executed step in BOTH lists (empty string when a
                    # step has no command text / no output) so agent_trace
                    # attempts[].commands[i] always pairs with outputs[i].
                    raw_executed_command = safe_result.get("command")
                    if type(raw_executed_command) is not str or not raw_executed_command.strip():
                        raw_executed_command = stringify_step_command(
                            safe_step.get("command")
                        )
                    executed_command = (
                        raw_executed_command.strip()
                        if type(raw_executed_command) is str
                        else ""
                    )
                    commands.append(executed_command)
                    raw_output = safe_result.get("output")
                    outputs.append(
                        raw_output.strip() if type(raw_output) is str else ""
                    )
                    inflight_step = False

                    if not bool(result.get("success", False)):
                        transport_evidence = self._transport_evidence(result)
                        unknown_outcome = self._unknown_outcome(transport_evidence)
                        comment = f"step failed: {step_id}"
                        dispatch_failure(
                            phase="execute_step",
                            reason=comment,
                            step_id=step_id,
                            step_payload=step_payload,
                            result=result,
                        )
                        break

                if not comment and not unknown_outcome:
                    verdict = bool(plugin.evaluate(runtime_case, {"steps": step_results}))
                    transport_evidence = self._merge_transport_evidence(
                        transport_evidence,
                        self._failure_snapshot_evidence(runtime_case),
                    )
                    unknown_outcome = self._unknown_outcome(transport_evidence)
                    if unknown_outcome:
                        verdict = False
                        comment = "command outcome unknown"
                        dispatch_failure(
                            phase="evaluate",
                            reason=comment,
                            result={"transport_result": transport_evidence},
                        )
                    elif not verdict:
                        last_failure = runtime_case.get("_last_failure")
                        if isinstance(last_failure, dict):
                            comment = str(last_failure.get("comment") or "pass_criteria not satisfied")
                        else:
                            comment = "pass_criteria not satisfied"
                        dispatch_failure(
                            phase="evaluate",
                            reason=comment,
                        )

        except _HookPayloadProjectionError:
            unknown_outcome = unknown_outcome or self._unknown_outcome(
                self._merge_transport_evidence(
                    transport_evidence,
                    self._failure_snapshot_evidence(runtime_case),
                )
            )
            if inflight_step:
                commands.append("")
                outputs.append("")
            if unknown_outcome:
                comment = "command outcome unknown"
                plugin_abort_reason = "command_outcome_unknown"
            else:
                comment = "hook_payload_projection_failed"
                plugin_abort_reason = "hook_payload_projection_failed"
            plugin_abort_run = True
            skip_teardown = True
        except Exception as exc:  # pragma: no cover - defensive catch for runtime errors
            transport_evidence = self._transport_evidence(exc)
            unknown_outcome = self._unknown_outcome(transport_evidence)
            comment = "command outcome unknown" if unknown_outcome else f"exception: {exc}"
            try:
                dispatch_failure(
                    phase="exception",
                    reason=comment,
                    result=(
                        {"transport_result": transport_evidence}
                        if unknown_outcome
                        else None
                    ),
                    exception=exc if not unknown_outcome else None,
                )
            except _HookPayloadProjectionError:
                unknown_outcome = unknown_outcome or self._unknown_outcome(
                    self._merge_transport_evidence(
                        transport_evidence,
                        self._failure_snapshot_evidence(runtime_case),
                    )
                )
                comment = (
                    "command outcome unknown"
                    if unknown_outcome
                    else "hook_payload_projection_failed"
                )
                plugin_abort_run = True
                plugin_abort_reason = (
                    "command_outcome_unknown"
                    if unknown_outcome
                    else "hook_payload_projection_failed"
                )
                skip_teardown = True
        finally:
            transport_evidence = self._merge_transport_evidence(
                transport_evidence,
                self._failure_snapshot_evidence(runtime_case),
            )
            unknown_outcome = unknown_outcome or self._unknown_outcome(transport_evidence)
            if unknown_outcome:
                skip_teardown = True
            if not unknown_outcome and not skip_teardown:
                try:
                    cleanup_result = normalize_cleanup_result(
                        plugin.teardown(runtime_case, topology=self.config)
                    )
                except Exception:
                    log.error("teardown raised for case %s", runtime_case.get("id", "?"))
                    cleanup_result = cleanup_exception_result()

        if cleanup_result is not None:
            prior_failure = failure_payload.get("failure_snapshot")
            cleanup_snapshot = cleanup_failure_snapshot(
                cleanup_result,
                case_id=runtime_case.get("id", ""),
                attempt_index=attempt_index,
            )
            if type(prior_failure) is dict:
                cleanup_snapshot["prior_failure_snapshot"] = prior_failure
            transport_evidence = self._merge_transport_evidence(
                transport_evidence,
                cleanup_result,
                cleanup_result.get("transport_result"),
            )
            cleanup_unknown = self._unknown_outcome(cleanup_result) or self._unknown_outcome(
                transport_evidence
            )
            cleanup_projection_failed = False
            try:
                cleanup_data = self._project_hook_envelope(
                    plugin,
                    self._hook_ctx(
                        "post_case", runtime_case, runner, attempt_index
                    ),
                    {
                        "failure_snapshot": cleanup_snapshot,
                        "comment": cleanup_result["comment"],
                        "transport_result": transport_evidence,
                    },
                )["data"]
            except _HookPayloadProjectionError:
                cleanup_data = {
                    "failure_snapshot": {
                        "category": "environment",
                        "reason_code": (
                            cleanup_result.get("reason_code")
                            if type(cleanup_result.get("reason_code")) is str
                            else "cleanup_result_invalid"
                        ),
                        "comment": "cleanup could not be verified",
                        "metadata": transport_evidence,
                    },
                    "transport_result": transport_evidence,
                }
                if not cleanup_unknown:
                    cleanup_projection_failed = True
                    plugin_abort_run = True
                    plugin_abort_reason = "hook_payload_projection_failed"
                    comment = "hook_payload_projection_failed"
            failure_payload["failure_snapshot"] = cleanup_data.get(
                "failure_snapshot"
            )
            transport_evidence = self._merge_transport_evidence(
                transport_evidence,
                cleanup_data.get("transport_result"),
            )
            unknown_outcome = unknown_outcome or self._unknown_outcome(
                transport_evidence
            )
            verdict = False
            projected_cleanup_comment = cleanup_data.get("comment")
            comment = (
                projected_cleanup_comment
                if type(projected_cleanup_comment) is str
                else "cleanup could not be verified"
            )
            plugin_abort_run = True
            if not cleanup_projection_failed:
                plugin_abort_reason = cleanup_result["reason_code"]

        if unknown_outcome and not failure_payload.get("failure_snapshot"):
            failure_payload["failure_snapshot"] = {
                "category": "environment", "reason_code": "command_outcome_unknown",
                "metadata": transport_evidence,
            }
        if unknown_outcome:
            comment = "command outcome unknown"

        cleanup_reason = (
            cleanup_result.get("reason_code")
            if type(cleanup_result) is dict
            else None
        )
        abort_reason = (
            cleanup_reason
            if unknown_outcome
            and type(cleanup_reason) is str
            and _ABORT_REASON_PATTERN.fullmatch(cleanup_reason)
            else "command_outcome_unknown"
            if unknown_outcome
            else plugin_abort_reason if plugin_abort_run else ""
        )

        return {
            "verdict": verdict,
            "comment": comment,
            "commands": commands,
            "outputs": outputs,
            "failure_snapshot": failure_payload.get("failure_snapshot"),
            "remediation_decision": failure_payload.get("remediation_decision"),
            "transport_result": transport_evidence,
            "abort_run": unknown_outcome or plugin_abort_run,
            "abort_reason": abort_reason,
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
        suppress_post_case = False
        pre_case_halted = False

        # pre_case hook
        pre_case_payload = {
            "execution_policy": execution_policy,
            "max_attempts": max_attempts,
        }
        try:
            pre_case = self._dispatch_projected_hook(
                plugin,
                self._hook_ctx("pre_case", case, runner),
                pre_case_payload,
            )
        except _HookPayloadProjectionError:
            return RetryResult(
                verdict=False,
                comment="hook_payload_projection_failed",
                commands=[],
                outputs=[],
                attempts=[],
                attempts_used=0,
                max_attempts=max_attempts,
                diagnostic_status="Inconclusive",
                remediation_history=[],
                failure_snapshot=None,
                tier2_audit=[],
                agent_recovered=False,
                abort_run=True,
                abort_reason="hook_payload_projection_failed",
            )
        pre_case_controls = self._merge_hook_controls(
            pre_case.public_data,
            pre_case.returned_data,
            {"max_attempts"},
        )
        max_attempts = max(
            1,
            safe_int(pre_case_controls.get("max_attempts"), max_attempts),
        )
        if not pre_case.result.proceed:
            pre_case_halted = True
            final_comment = (
                pre_case.result.advice
                or "pre_case hook halted before case execution"
            )

        for attempt_index in range(1, max_attempts + 1) if not pre_case_halted else ():
            # on_retry hook (for attempts after the first)
            if attempt_index > 1:
                retry_payload = {
                    "case": dict(case),
                    "previous_attempts": attempts,
                    "attempt_index": attempt_index,
                }
                try:
                    retry_dispatch = self._dispatch_projected_hook(
                        plugin,
                        self._hook_ctx("on_retry", case, runner, attempt_index),
                        retry_payload,
                    )
                except _HookPayloadProjectionError:
                    abort_run = True
                    abort_reason = "hook_payload_projection_failed"
                    suppress_post_case = True
                    final_verdict = False
                    final_comment = "hook_payload_projection_failed"
                    break
                retry_payload = self._merge_hook_controls(
                    retry_dispatch.public_data,
                    retry_dispatch.returned_data,
                    {
                        "remediation_history",
                        "remediation_trace_entry",
                        "tier2_audit",
                        "agent_recovered",
                        "failure_snapshot",
                        "remediation_decision",
                        "transport_result",
                        "abort_run",
                        "abort_reason",
                    },
                )
                retry_evidence = self._merge_transport_evidence(
                    retry_payload.get("transport_result"),
                    retry_payload.get("failure_snapshot"),
                    retry_payload.get("remediation_decision"),
                    retry_payload.get("remediation_history"),
                    retry_payload.get("remediation_trace_entry"),
                    retry_payload.get("tier2_audit"),
                )
                if self._unknown_outcome(retry_evidence):
                    abort_run = True
                    abort_reason = "command_outcome_unknown"
                    suppress_post_case = True
                    final_verdict = False
                    final_comment = "command outcome unknown"
                    final_failure_snapshot = (
                        retry_payload.get("failure_snapshot")
                        if type(retry_payload.get("failure_snapshot")) is dict
                        else final_failure_snapshot
                    )
                    if attempts:
                        attempts[-1]["transport_result"] = (
                            self._merge_transport_evidence(
                                attempts[-1].get("transport_result"),
                                retry_evidence,
                            )
                        )
                        if final_failure_snapshot is not None:
                            attempts[-1]["failure_snapshot"] = final_failure_snapshot
                        attempts[-1]["abort_run"] = True
                        attempts[-1]["abort_reason"] = "command_outcome_unknown"
                    break
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
                    abort_reason = self._hook_abort_reason(retry_payload)[1]
                    final_verdict = False
                    final_comment = retry_dispatch.result.advice or abort_reason
                    break
                if not retry_dispatch.result.proceed:
                    final_verdict = False
                    final_comment = (
                        retry_dispatch.result.advice
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
            final_commands = [
                item for item in result.get("commands", []) if type(item) is str
            ]
            final_outputs = [
                item for item in result.get("outputs", []) if type(item) is str
            ]
            final_comment = (
                result.get("comment")
                if type(result.get("comment")) is str
                else ""
            )
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
                raw_abort_reason = result.get("abort_reason")
                abort_reason = (
                    raw_abort_reason
                    if type(raw_abort_reason) is str
                    and _ABORT_REASON_PATTERN.fullmatch(raw_abort_reason)
                    else _DEFAULT_PLUGIN_ABORT_REASON
                )
                final_verdict = False
                attempt_evidence = self._merge_transport_evidence(
                    result.get("transport_result"),
                    result.get("failure_snapshot"),
                )
                suppress_post_case = self._unknown_outcome(attempt_evidence) or (
                    abort_reason == "hook_payload_projection_failed"
                )
                if suppress_post_case and self._unknown_outcome(attempt_evidence):
                    if abort_reason == "command_outcome_unknown":
                        final_comment = "command outcome unknown"
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

        if not suppress_post_case and not pre_case_halted:
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
            try:
                post_case = self._dispatch_projected_hook(
                    plugin,
                    self._hook_ctx(
                        "post_case",
                        case,
                        runner,
                        max(1, attempts_used),
                    ),
                    post_case_payload,
                )
            except _HookPayloadProjectionError:
                abort_run = True
                abort_reason = "hook_payload_projection_failed"
                final_verdict = False
                final_comment = "hook_payload_projection_failed"
            else:
                post_case_payload = self._merge_hook_controls(
                    post_case.public_data,
                    post_case.returned_data,
                    {
                        "remediation_history",
                        "failure_snapshot",
                        "tier2_audit",
                        "agent_recovered",
                        "transport_result",
                        "abort_run",
                        "abort_reason",
                    },
                )
                post_case_evidence = self._merge_transport_evidence(
                    post_case_payload.get("transport_result"),
                    post_case_payload.get("failure_snapshot"),
                )
                if self._unknown_outcome(post_case_evidence):
                    abort_run = True
                    abort_reason = "command_outcome_unknown"
                    final_verdict = False
                    final_comment = "command outcome unknown"
                    if attempts:
                        attempts[-1]["transport_result"] = (
                            self._merge_transport_evidence(
                                attempts[-1].get("transport_result"),
                                post_case_evidence,
                            )
                        )
                        attempts[-1]["abort_run"] = True
                        attempts[-1]["abort_reason"] = "command_outcome_unknown"
                elif post_case_payload.get("abort_run") is True:
                    abort_run = True
                    abort_reason = self._hook_abort_reason(post_case_payload)[1]

                raw_history = post_case_payload.get(
                    "remediation_history", remediation_history
                )
                if isinstance(raw_history, list):
                    remediation_history = [
                        dict(item) for item in raw_history if isinstance(item, dict)
                    ]
                maybe_failure_snapshot = post_case_payload.get("failure_snapshot")
                if isinstance(maybe_failure_snapshot, dict):
                    final_failure_snapshot = dict(maybe_failure_snapshot)
                raw_tier2_audit = post_case_payload.get("tier2_audit")
                if isinstance(raw_tier2_audit, list):
                    tier2_audit = [
                        dict(item) for item in raw_tier2_audit if isinstance(item, dict)
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
