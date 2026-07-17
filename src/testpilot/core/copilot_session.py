"""Thin GitHub Copilot SDK session adapter for the third refactor foundation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import importlib
import inspect
import logging
import math
from typing import Any, Callable, Mapping
import re


_SESSION_COMPONENT_PATTERN = re.compile(r"[^A-Za-z0-9._-]+")
_ONE_SHOT_CONFIG_FIELDS = {
    "client_name",
    "model",
    "on_permission_request",
    "provider",
    "reasoning_effort",
    "session_id",
}
_MAX_ONE_SHOT_PROMPT_CHARS = 64_000
_MAX_ONE_SHOT_TIMEOUT_SECONDS = 600.0

log = logging.getLogger(__name__)


class CopilotSDKUnavailableError(RuntimeError):
    """Raised when the GitHub Copilot SDK Python package is unavailable."""


def _sanitize_session_component(value: str) -> str:
    normalized = _SESSION_COMPONENT_PATTERN.sub("_", value.strip())
    return normalized.strip("._-") or "unknown"


def build_session_id(
    run_id: str,
    *,
    case_id: str | None = None,
    remediate_attempt: int | None = None,
) -> str:
    """Build stable session IDs that match the third-refactor policy."""
    session_id = f"run-{_sanitize_session_component(run_id)}"
    if case_id:
        session_id += f"-case-{_sanitize_session_component(case_id)}"
    if remediate_attempt is not None:
        session_id += f"-remediate-{int(remediate_attempt)}"
    return session_id


@dataclass(frozen=True)
class CopilotSessionRequest:
    """Normalized session request for create/resume calls."""

    session_id: str
    model: str
    reasoning_effort: str = "high"
    working_directory: str | None = None
    config_dir: str | None = None
    available_tools: tuple[str, ...] = ()
    excluded_tools: tuple[str, ...] = ()
    agent: str | None = None
    skill_directories: tuple[str, ...] = ()
    disabled_skills: tuple[str, ...] = ()
    hooks: Mapping[str, Any] | None = None
    custom_agents: tuple[Mapping[str, Any], ...] = ()
    mcp_servers: Mapping[str, Any] | None = None
    infinite_sessions: Mapping[str, Any] | None = None
    streaming: bool = False
    system_message: Mapping[str, Any] | None = None
    client_name: str | None = None
    provider: Mapping[str, Any] | None = None
    on_permission_request: Any = None
    on_event: Callable[[Any], None] | None = None

    def _base_config(self, permission_handler: Any) -> dict[str, Any]:
        config: dict[str, Any] = {
            "session_id": self.session_id,
            "model": self.model,
            "on_permission_request": permission_handler,
        }
        if self.reasoning_effort:
            config["reasoning_effort"] = self.reasoning_effort
        if self.working_directory:
            config["working_directory"] = self.working_directory
        if self.config_dir:
            config["config_dir"] = self.config_dir
        if self.available_tools:
            config["available_tools"] = list(self.available_tools)
        if self.excluded_tools:
            config["excluded_tools"] = list(self.excluded_tools)
        if self.agent:
            config["agent"] = self.agent
        if self.skill_directories:
            config["skill_directories"] = list(self.skill_directories)
        if self.disabled_skills:
            config["disabled_skills"] = list(self.disabled_skills)
        if self.hooks:
            config["hooks"] = dict(self.hooks)
        if self.custom_agents:
            config["custom_agents"] = [dict(agent) for agent in self.custom_agents]
        if self.mcp_servers:
            config["mcp_servers"] = dict(self.mcp_servers)
        if self.infinite_sessions:
            config["infinite_sessions"] = dict(self.infinite_sessions)
        if self.streaming:
            config["streaming"] = True
        if self.system_message:
            config["system_message"] = dict(self.system_message)
        if self.client_name:
            config["client_name"] = self.client_name
        if self.provider:
            config["provider"] = dict(self.provider)
        if self.on_event:
            config["on_event"] = self.on_event
        return config

    def to_create_config(self, permission_handler: Any) -> dict[str, Any]:
        return self._base_config(permission_handler)

    def to_resume_config(
        self,
        permission_handler: Any,
        *,
        disable_resume: bool = False,
    ) -> dict[str, Any]:
        config = self._base_config(permission_handler)
        config.pop("session_id", None)
        if disable_resume:
            config["disable_resume"] = True
        return config


@dataclass(frozen=True)
class CopilotSessionHandle:
    session_id: str
    workspace_path: str | None = None


@dataclass(frozen=True)
class CopilotSessionInfo:
    session_id: str
    start_time: str
    modified_time: str
    is_remote: bool
    summary: str | None = None
    cwd: str | None = None
    git_root: str | None = None
    repository: str | None = None
    branch: str | None = None


def build_case_session_plan(
    run_id: str,
    case_id: str,
    runner: Mapping[str, Any],
    provider_config: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Build planned Copilot session metadata without creating the session yet."""
    if str(runner.get("cli_agent", "")).strip().lower() != "copilot":
        return None
    plan: dict[str, Any] = {
        "provider": "copilot-sdk",
        "session_id": build_session_id(run_id, case_id=case_id),
        "model": str(runner.get("model", "")).strip(),
        "reasoning_effort": str(runner.get("effort", "high")).strip() or "high",
        "status": "planned",
    }
    if provider_config:
        plan["provider_config"] = dict(provider_config)
    return plan


@dataclass
class CopilotSessionManager:
    """Sync wrapper around the async GitHub Copilot SDK client APIs."""

    sdk_module: Any | None = None
    client_factory: Callable[[], Any] | None = None
    permission_handler: Any = None
    _loaded_sdk: Any | None = field(default=None, init=False, repr=False)

    def _load_sdk(self) -> Any:
        if self.sdk_module is not None:
            return self.sdk_module
        if self._loaded_sdk is None:
            try:
                self._loaded_sdk = importlib.import_module("copilot")
            except ModuleNotFoundError as exc:
                raise CopilotSDKUnavailableError(
                    "GitHub Copilot SDK Python package is not installed. "
                    "Install `github-copilot-sdk` to enable session foundation."
                ) from exc
        return self._loaded_sdk

    def _build_client(self) -> Any:
        if self.client_factory is not None:
            return self.client_factory()
        sdk = self._load_sdk()
        client_cls = getattr(sdk, "CopilotClient", None)
        if client_cls is None:
            raise CopilotSDKUnavailableError("copilot.CopilotClient is unavailable")
        return client_cls()

    def _resolve_permission_handler(self) -> Any:
        if self.permission_handler is not None:
            return self.permission_handler
        sdk = self._load_sdk()
        result_type = getattr(sdk, "PermissionRequestResult", None)
        if result_type is None:
            raise CopilotSDKUnavailableError(
                "copilot.PermissionRequestResult is unavailable"
            )

        def _approve_all(request: Any, context: Any) -> Any:
            return result_type(kind="approved")

        return _approve_all

    @staticmethod
    def _deny_all_permission_handler(request: Any, context: Any) -> dict[str, Any]:
        """Deny every SDK tool request for plan-only one-shot sessions."""
        del request, context
        return {"kind": "denied-by-rules", "rules": []}

    @staticmethod
    async def _maybe_await(value: Any) -> Any:
        if inspect.isawaitable(value):
            return await value
        return value

    def _run(self, awaitable: Any) -> Any:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(awaitable)
        raise RuntimeError(
            "CopilotSessionManager sync API cannot be used inside an active event loop"
        )

    async def _with_client(self, fn: Callable[[Any], Any]) -> Any:
        client = self._build_client()
        start = getattr(client, "start", None)
        stop = getattr(client, "stop", None)
        if callable(start):
            await self._maybe_await(start())
        primary_error: BaseException | None = None
        try:
            result = fn(client)
            return await self._maybe_await(result)
        except BaseException as exc:
            primary_error = exc
            raise
        finally:
            if callable(stop):
                try:
                    await self._maybe_await(stop())
                except Exception as cleanup_error:
                    if primary_error is None:
                        raise
                    primary_error.add_note(
                        "Copilot client stop cleanup also failed: "
                        f"{type(cleanup_error).__name__}"
                    )
                    log.warning(
                        "Copilot client stop failed after primary error; "
                        "cleanup_error_type=%s",
                        type(cleanup_error).__name__,
                    )

    @staticmethod
    def _session_handle(session: Any, fallback_session_id: str) -> CopilotSessionHandle:
        session_id = str(getattr(session, "session_id", fallback_session_id))
        workspace_path = getattr(session, "workspace_path", None)
        return CopilotSessionHandle(session_id=session_id, workspace_path=workspace_path)

    @staticmethod
    def _session_info(item: Any) -> CopilotSessionInfo:
        context = getattr(item, "context", None)
        return CopilotSessionInfo(
            session_id=str(getattr(item, "sessionId")),
            start_time=str(getattr(item, "startTime")),
            modified_time=str(getattr(item, "modifiedTime")),
            is_remote=bool(getattr(item, "isRemote")),
            summary=getattr(item, "summary", None),
            cwd=getattr(context, "cwd", None) if context is not None else None,
            git_root=getattr(context, "gitRoot", None) if context is not None else None,
            repository=getattr(context, "repository", None) if context is not None else None,
            branch=getattr(context, "branch", None) if context is not None else None,
        )

    def create_session(self, request: CopilotSessionRequest) -> CopilotSessionHandle:
        permission_handler = request.on_permission_request or self._resolve_permission_handler()

        async def _op(client: Any) -> CopilotSessionHandle:
            session = await client.create_session(request.to_create_config(permission_handler))
            return self._session_handle(session, request.session_id)

        return self._run(self._with_client(_op))

    def resume_session(
        self,
        session_id: str,
        request: CopilotSessionRequest,
        *,
        disable_resume: bool = False,
    ) -> CopilotSessionHandle:
        permission_handler = request.on_permission_request or self._resolve_permission_handler()

        async def _op(client: Any) -> CopilotSessionHandle:
            session = await client.resume_session(
                session_id,
                request.to_resume_config(permission_handler, disable_resume=disable_resume),
            )
            return self._session_handle(session, session_id)

        return self._run(self._with_client(_op))

    def send_one_shot(
        self,
        request: CopilotSessionRequest,
        prompt: str,
        *,
        timeout_seconds: float = 60.0,
    ) -> str:
        """Run one tool-denied SDK 0.1.x turn and destroy its session.

        The adapter targets ``github-copilot-sdk>=0.1.23,<0.2``. It fails
        loudly when that ``send_and_wait`` surface is unavailable instead of
        treating an incompatible SDK response as a valid recovery plan.
        """
        prompt_text = str(prompt)
        if not prompt_text.strip():
            raise ValueError("Copilot one-shot prompt must not be empty")
        if len(prompt_text) > _MAX_ONE_SHOT_PROMPT_CHARS:
            raise ValueError(
                "Copilot one-shot prompt size limit exceeded "
                f"({_MAX_ONE_SHOT_PROMPT_CHARS} chars)"
            )
        try:
            normalized_timeout = float(timeout_seconds)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "Copilot one-shot timeout_seconds must be positive and bounded"
            ) from exc
        if (
            not math.isfinite(normalized_timeout)
            or normalized_timeout <= 0
            or normalized_timeout > _MAX_ONE_SHOT_TIMEOUT_SECONDS
        ):
            raise ValueError("Copilot one-shot timeout_seconds must be positive")

        async def _op(client: Any) -> str:
            requested_config = request.to_create_config(
                self._deny_all_permission_handler
            )
            # Plan-only sessions expose no agent/tool/MCP/hook surface. Empty
            # available_tools is omitted by SDK 0.1.x, so permission denial and
            # this explicit allowlist are both required.
            config = {
                key: value
                for key, value in requested_config.items()
                if key in _ONE_SHOT_CONFIG_FIELDS
            }
            session = await client.create_session(config)
            actual_session_id = str(
                getattr(session, "session_id", request.session_id)
                or request.session_id
            )
            unsubscribe: Callable[[], Any] | None = None
            primary_error: BaseException | None = None
            try:
                if request.on_event is not None:
                    subscribe = getattr(session, "on", None)
                    if not callable(subscribe):
                        raise CopilotSDKUnavailableError(
                            "Copilot SDK session.on is unavailable; "
                            "tier-2 requires github-copilot-sdk>=0.1.23,<0.2"
                        )
                    unsubscribe = subscribe(request.on_event)

                send_and_wait = getattr(session, "send_and_wait", None)
                if not callable(send_and_wait):
                    raise CopilotSDKUnavailableError(
                        "Copilot SDK session.send_and_wait is unavailable; "
                        "tier-2 requires github-copilot-sdk>=0.1.23,<0.2"
                    )
                try:
                    event = await send_and_wait(
                        {"prompt": prompt_text},
                        timeout=normalized_timeout,
                    )
                except asyncio.TimeoutError as timeout_error:
                    abort = getattr(session, "abort", None)
                    if not callable(abort):
                        timeout_error.add_note(
                            "Copilot SDK session.abort is unavailable after timeout; "
                            "tier-2 requires github-copilot-sdk>=0.1.23,<0.2"
                        )
                        log.warning(
                            "Copilot one-shot abort unavailable after timeout"
                        )
                    else:
                        try:
                            await self._maybe_await(abort())
                        except Exception as abort_error:
                            timeout_error.add_note(
                                "Copilot one-shot abort cleanup also failed: "
                                f"{type(abort_error).__name__}"
                            )
                            log.warning(
                                "Copilot one-shot abort failed after timeout; "
                                "cleanup_error_type=%s",
                                type(abort_error).__name__,
                            )
                    raise

                content = getattr(getattr(event, "data", None), "content", None)
                if not isinstance(content, str) or not content.strip():
                    raise CopilotSDKUnavailableError(
                        "Copilot one-shot returned no assistant content"
                    )
                return content.strip()
            except BaseException as exc:
                primary_error = exc
                raise
            finally:
                cleanup_errors: list[Exception] = []
                try:
                    if callable(unsubscribe):
                        await self._maybe_await(unsubscribe())
                except Exception as cleanup_error:
                    cleanup_errors.append(cleanup_error)

                delete_session = getattr(client, "delete_session", None)
                if not callable(delete_session):
                    cleanup_errors.append(
                        CopilotSDKUnavailableError(
                            "Copilot SDK client.delete_session is unavailable; "
                            "tier-2 requires github-copilot-sdk>=0.1.23,<0.2"
                        )
                    )
                else:
                    try:
                        await self._maybe_await(
                            delete_session(actual_session_id)
                        )
                    except Exception as cleanup_error:
                        cleanup_errors.append(cleanup_error)

                if cleanup_errors:
                    cleanup_types = ",".join(
                        type(item).__name__ for item in cleanup_errors
                    )
                    if primary_error is not None:
                        primary_error.add_note(
                            "Copilot one-shot cleanup also failed: "
                            f"{cleanup_types}"
                        )
                        log.warning(
                            "Copilot one-shot cleanup failed after primary error; "
                            "cleanup_error_types=%s",
                            cleanup_types,
                        )
                    else:
                        raise CopilotSDKUnavailableError(
                            "Copilot one-shot cleanup failed; "
                            f"cleanup_error_types={cleanup_types}"
                        ) from cleanup_errors[0]

        return self._run(self._with_client(_op))

    def list_sessions(self) -> list[CopilotSessionInfo]:
        async def _op(client: Any) -> list[CopilotSessionInfo]:
            sessions = await client.list_sessions()
            return [self._session_info(item) for item in sessions]

        return self._run(self._with_client(_op))

    def delete_session(self, session_id: str) -> None:
        async def _op(client: Any) -> None:
            await client.delete_session(session_id)

        self._run(self._with_client(_op))
