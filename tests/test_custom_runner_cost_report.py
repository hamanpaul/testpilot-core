from pathlib import Path

from testpilot.core.orchestrator import Orchestrator


class _FakePlugin:
    version = "0.1.0"

    def discover_cases(self):
        return [
            {"id": "D001"},
            {"id": "D002", "aliases": ["two"]},
        ]


def test_skeleton_run_returns_unsupported_execution_path_payload(tmp_path: Path) -> None:
    orchestrator = Orchestrator(project_root=tmp_path)

    payload = orchestrator._skeleton_run(
        plugin=_FakePlugin(),
        plugin_name="fake",
        case_ids=["two"],
    )

    assert payload == {
        "plugin": "fake",
        "plugin_version": "0.1.0",
        "cases_count": 1,
        "case_ids": ["D002"],
        "status": "skeleton — not yet implemented",
        "core_cost_report": {
            "status": "unsupported_execution_path",
            "execution_path": "skeleton",
            "coverage": "core_sdk_calls_only",
            "analysis_status": "unavailable",
        },
    }
