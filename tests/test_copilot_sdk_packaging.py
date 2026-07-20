from __future__ import annotations

import os
from pathlib import Path
import tomllib

import pytest


def test_pyproject_declares_github_copilot_sdk_dependency() -> None:
    pyproject = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
            encoding="utf-8"
        )
    )

    assert any(
        str(dep).startswith("github-copilot-sdk")
        for dep in pyproject["project"]["dependencies"]
    )


def test_installed_copilot_sdk_exposes_one_shot_surface() -> None:
    if os.environ.get("TESTPILOT_SDK_SURFACE_PROBE") != "1":
        pytest.skip("set TESTPILOT_SDK_SURFACE_PROBE=1 to probe installed SDK surface")

    copilot = pytest.importorskip("copilot")

    assert getattr(copilot, "CopilotClient", None) is not None
    assert getattr(copilot, "CopilotSession", None) is not None
    assert getattr(copilot, "PermissionRequestResult", None) is not None
    assert callable(getattr(copilot.CopilotSession, "send_and_wait", None))
    assert callable(getattr(copilot.CopilotSession, "on", None))
