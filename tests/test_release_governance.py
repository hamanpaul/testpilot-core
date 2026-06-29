from __future__ import annotations

import re
import shlex
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def _read_policy() -> dict:
    return yaml.safe_load((ROOT / ".project-policy.yml").read_text(encoding="utf-8"))


def _read_workflow(path: str) -> dict:
    return yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))


def _extract_readme_marker(marker: str) -> str:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    match = re.search(
        rf"<!--\s*BEGIN:\s*cli-help\s+marker=\"{re.escape(marker)}\"\s*-->\s*(.*?)\s*<!--\s*END:\s*cli-help\s+marker=\"{re.escape(marker)}\"\s*-->",
        readme,
        re.DOTALL,
    )
    assert match is not None, f"Missing README help marker block: {marker}"
    return match.group(1).strip()


def _help_output(command: str, help_args: list[str]) -> str:
    result = subprocess.run(
        [*shlex.split(command), *help_args],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_project_policy_declares_help_sync_markers() -> None:
    policy_path = ROOT / ".project-policy.yml"
    assert policy_path.exists(), ".project-policy.yml is required"
    assert not (ROOT / ".paul-project.yml").exists()

    policy = _read_policy()
    assert policy["policy_profile"] == "flat"
    assert policy["policy_version"] == "1.0.5"
    markers = {entry["marker"] for entry in policy["cli"]}

    assert {
        "testpilot-help",
        "testpilot-update-help",
    } <= markers
    workflow_ref = policy["policy_check"]["workflow_ref"]
    assert re.search(r"@[0-9a-f]{40}$", workflow_ref), workflow_ref


def test_agent_instruction_files_are_synchronized() -> None:
    policy = _read_policy()
    assert "agent-instructions-sync" in policy["policy"]["required_checks"]

    relative_paths = (
        "CLAUDE.md",
        "AGENTS.md",
        "GEMINI.md",
        ".github/copilot-instructions.md",
    )
    contents = {relative_path: (ROOT / relative_path).read_bytes() for relative_path in relative_paths}
    reference = contents[relative_paths[0]]

    for relative_path in relative_paths[1:]:
        assert contents[relative_path] == reference

    content = reference.decode("utf-8")
    assert "<!-- managed-by: hamanpaul/paulsha-conventions@v1.0.5 -->" in content
    assert "policy_version: 1.0.5" in content
    # 同步 payload 不得引用已退役的 .paul-project.yml(本 repo canonical 是 .project-policy.yml;
    # codex review #90)——否則 agent 會看/建錯 config。
    assert ".paul-project.yml" not in content, (
        "synced agent payload references retired .paul-project.yml; use .project-policy.yml"
    )
    assert "## TestPilot 專案專屬" in content
    assert "VERSION" in content
    assert "testpilot wifi_llapi" in content
    assert ".project-policy.yml" in content


def test_policy_workflows_enforce_pinned_external_policy() -> None:
    workflow_ref = _read_policy()["policy_check"]["workflow_ref"]
    policy_sha = workflow_ref.rsplit("@", 1)[1]

    policy_workflow = _read_workflow(".github/workflows/policy-check.yml")
    release_workflow = _read_workflow(".github/workflows/release.yml")

    for workflow in (policy_workflow, release_workflow):
        jobs = workflow["jobs"]
        assert any(job.get("uses") == workflow_ref for job in jobs.values())
        assert any(
            job.get("with", {}).get("policy_engine_ref") == policy_sha
            for job in jobs.values()
            if isinstance(job, dict)
        )


def test_readme_help_sync_marker_blocks_match_cli_output() -> None:
    policy = _read_policy()

    for entry in policy["cli"]:
        assert _extract_readme_marker(entry["marker"]) == _help_output(
            entry["command"], entry["help_args"]
        )


def test_version_file_uses_semver() -> None:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert re.fullmatch(r"\d+\.\d+\.\d+", version)


def test_release_validation_accepts_matching_tag() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/check_release_version.py", "--tag", "v0.3.1"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "Validated release tag v0.3.1" in result.stdout


def test_release_validation_rejects_mismatched_tag() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/check_release_version.py", "--tag", "v0.3.0"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "does not match expected v0.3.1" in result.stderr


def test_release_validation_rejects_malformed_tag() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/check_release_version.py", "--tag", "v0.2.0-rc1"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "Release tag must use vX.Y.Z" in result.stderr
