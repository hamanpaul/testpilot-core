from __future__ import annotations

from pathlib import Path

import yaml


SKILL_PATH = Path("skills/testpilot-normal-test/SKILL.md")


def test_testpilot_normal_test_skill_limits_gpt5_mini_to_full_run_and_by_case() -> None:
    content = SKILL_PATH.read_text(encoding="utf-8")
    frontmatter = content.split("---", 2)[1]
    meta = yaml.safe_load(frontmatter)

    assert meta["name"] == "testpilot-normal-test"
    assert meta["description"].startswith("Use when")
    assert "GPT-5-mini" in content
    assert "full-run" in content
    assert "by-case" in content
    assert "testpilot wifi_llapi" in content
    assert "testpilot wifi_llapi --case" in content
    assert "Only two allowed modes" in content
    assert "Do not use repo pytest as a substitute" in content
    assert "Do not run audit" in content


def test_testpilot_normal_test_skill_lists_required_sync_documents() -> None:
    content = SKILL_PATH.read_text(encoding="utf-8")

    for path in (
        "README.md",
        "docs/plan.md",
        "docs/todos.md",
        "AGENTS.md",
        "plugins/wifi_llapi/agent-config.yaml",
    ):
        assert path in content
