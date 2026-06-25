"""Tests for the thin Copilot SDK session adapter."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from testpilot.core.copilot_session import (
    CopilotSDKUnavailableError,
    CopilotSessionManager,
    CopilotSessionRequest,
    build_case_session_plan,
    build_session_id,
)


@dataclass
class _FakeSessionContext:
    cwd: str | None = None
    gitRoot: str | None = None
    repository: str | None = None
    branch: str | None = None


@dataclass
class _FakeSessionMetadata:
    sessionId: str
    startTime: str
    modifiedTime: str
    isRemote: bool
    summary: str | None = None
    context: _FakeSessionContext | None = None


@dataclass
class _FakeSession:
    session_id: str
    workspace_path: str | None = None


class _FakeClient:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.created_configs: list[dict] = []
        self.resumed_configs: list[tuple[str, dict]] = []
        self.deleted_session_ids: list[str] = []

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def create_session(self, config: dict) -> _FakeSession:
        self.created_configs.append(config)
        return _FakeSession(
            session_id=config["session_id"],
            workspace_path="/tmp/copilot/workspaces/run-1",
        )

    async def resume_session(self, session_id: str, config: dict) -> _FakeSession:
        self.resumed_configs.append((session_id, config))
        return _FakeSession(session_id=session_id, workspace_path="/tmp/copilot/workspaces/run-1")

    async def list_sessions(self) -> list[_FakeSessionMetadata]:
        return [
            _FakeSessionMetadata(
                sessionId="run-20260311-case-wifi-llapi-D001",
                startTime="2026-03-11T07:00:00Z",
                modifiedTime="2026-03-11T07:05:00Z",
                isRemote=False,
                summary="operator session",
                context=_FakeSessionContext(
                    cwd="/workspace",
                    gitRoot="/workspace",
                    repository="hamanpaul/testpilot",
                    branch="docs/third-refactor-copilot-sdk",
                ),
            )
        ]

    async def delete_session(self, session_id: str) -> None:
        self.deleted_session_ids.append(session_id)


def test_build_session_id_matches_third_refactor_policy():
    assert build_session_id("20260311T101010") == "run-20260311T101010"
    assert build_session_id("20260311T101010", case_id="wifi-llapi-D328-errorssent-ssid-stats") == (
        "run-20260311T101010-case-wifi-llapi-D328-errorssent-ssid-stats"
    )
    assert build_session_id(
        "20260311T101010",
        case_id="wifi llapi D328/errorssent",
        remediate_attempt=2,
    ) == "run-20260311T101010-case-wifi_llapi_D328_errorssent-remediate-2"


def test_build_case_session_plan_for_copilot_runner():
    plan = build_case_session_plan(
        "20260311T101010",
        "wifi-llapi-D328-errorssent-ssid-stats",
        {
            "cli_agent": "copilot",
            "model": "gpt-5.4",
            "effort": "high",
        },
    )

    assert plan == {
        "provider": "copilot-sdk",
        "session_id": "run-20260311T101010-case-wifi-llapi-D328-errorssent-ssid-stats",
        "model": "gpt-5.4",
        "reasoning_effort": "high",
        "status": "planned",
    }


def test_create_resume_list_delete_session_via_sdk_adapter():
    fake_client = _FakeClient()
    fake_sdk = SimpleNamespace(PermissionHandler=SimpleNamespace(approve_all="APPROVE_ALL"))
    manager = CopilotSessionManager(
        sdk_module=fake_sdk,
        client_factory=lambda: fake_client,
    )
    request = CopilotSessionRequest(
        session_id="run-20260311T101010-case-wifi-llapi-D328-errorssent-ssid-stats",
        model="gpt-5.4",
        reasoning_effort="high",
        working_directory="/workspace",
        config_dir="/workspace/.copilot",
        available_tools=("view", "edit"),
        excluded_tools=("shell",),
        agent="case-auditor",
        skill_directories=("/workspace/skills",),
        disabled_skills=("legacy-skill",),
        hooks={"on_session_start": object()},
        custom_agents=(
            {
                "name": "case-auditor",
                "prompt": "audit this case",
            },
        ),
        infinite_sessions={"enabled": True},
        streaming=True,
        client_name="testpilot",
    )

    created = manager.create_session(request)
    resumed = manager.resume_session(request.session_id, request, disable_resume=True)
    listed = manager.list_sessions()
    manager.delete_session(request.session_id)

    assert fake_client.started is True
    assert fake_client.stopped is True

    assert created.session_id == request.session_id
    assert created.workspace_path == "/tmp/copilot/workspaces/run-1"
    assert resumed.session_id == request.session_id

    created_config = fake_client.created_configs[0]
    assert created_config["session_id"] == request.session_id
    assert created_config["model"] == "gpt-5.4"
    assert created_config["reasoning_effort"] == "high"
    assert created_config["working_directory"] == "/workspace"
    assert created_config["config_dir"] == "/workspace/.copilot"
    assert created_config["available_tools"] == ["view", "edit"]
    assert created_config["excluded_tools"] == ["shell"]
    assert created_config["agent"] == "case-auditor"
    assert created_config["skill_directories"] == ["/workspace/skills"]
    assert created_config["disabled_skills"] == ["legacy-skill"]
    assert created_config["streaming"] is True
    assert created_config["client_name"] == "testpilot"
    assert created_config["on_permission_request"] == "APPROVE_ALL"

    resumed_session_id, resumed_config = fake_client.resumed_configs[0]
    assert resumed_session_id == request.session_id
    assert "session_id" not in resumed_config
    assert resumed_config["disable_resume"] is True
    assert resumed_config["on_permission_request"] == "APPROVE_ALL"

    assert len(listed) == 1
    assert listed[0].session_id == "run-20260311-case-wifi-llapi-D001"
    assert listed[0].cwd == "/workspace"
    assert listed[0].repository == "hamanpaul/testpilot"
    assert fake_client.deleted_session_ids == [request.session_id]


def test_missing_sdk_raises_clear_error(monkeypatch):
    manager = CopilotSessionManager()

    def _raise(name: str):
        raise ModuleNotFoundError(name)

    monkeypatch.setattr("importlib.import_module", _raise)

    with pytest.raises(CopilotSDKUnavailableError):
        manager.create_session(
            CopilotSessionRequest(
                session_id="run-20260311T101010",
                model="gpt-5.4",
            )
        )

