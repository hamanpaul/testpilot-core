"""Inline tests for the one-shot alignment script.

Run with:
    uv run pytest tools/oneoff/2026-04-24-align-missing-rows/test_align_missing_rows.py -v
"""

from __future__ import annotations

import sys
import json
from textwrap import dedent
from pathlib import Path
from types import SimpleNamespace
import pytest

# Make the script importable
sys.path.insert(0, str(Path(__file__).resolve().parent))
import align_missing_rows as ali  # noqa: E402


def clone_cases(cases: dict[str, ali.CaseInfo]) -> dict[str, ali.CaseInfo]:
    return {name: dict(info) for name, info in cases.items()}


def build_pre_apply_cases_from_current_repo() -> dict[str, ali.CaseInfo]:
    cases = clone_cases(ali.scan_cases())

    cases.pop(ali.PLAN_CREATE["filename"])
    for filename, stale_row in ali.PLAN_DELETES:
        cases[filename] = {"source_row": stale_row, "id": f"restored-{stale_row}"}

    for filename, old_row, old_id, _new_row in ali.PLAN_METADATA_ONLY:
        cases[filename] = {"source_row": old_row, "id": old_id}

    old, old_row, old_id, new, _new_row, _new_id = ali.PLAN_MOVE
    cases.pop(new)
    cases[old] = {"source_row": old_row, "id": old_id}

    for old, old_row, old_id, new, _new_row, _new_id in ali.PLAN_RENAMES:
        cases.pop(new)
        cases[old] = {"source_row": old_row, "id": old_id}

    return cases


def test_metadata_edit_only_updates_id_and_source_row_for_realistic_yaml(tmp_path):
    dst = tmp_path / "synthetic.yaml"
    before = dedent(
        """\
        id: wifi-llapi-D115-getstationstats-accesspoint
        name: getStationStats() — WiFi.AccessPoint.{i}.
        version: '1.0'
        source:
          row: 115
          object: WiFi.AccessPoint.{i}.
          api: getStationStats()
        test_environment: 'Topology:

          - DUT: COM1 (B0, AP role)

          - Workbook H excerpt uses `hostapd_cli sta`, but current 0403 official baseline
          exposes `/tmp/wl0_hapd.conf` without a matching `/var/run/hostapd/wl0` control socket;
          `hostapd_cli` returns `wpa_ctrl_open: No such file or directory`.

          - Current single-STA baseline therefore uses driver `wl assoclist` as the stable
          runtime association oracle and verifies that getStationStats() returns the same
          STA MAC.

          '
        steps:
        - id: step1_assoc_precheck
          action: exec
          target: DUT
          command: wl -i wl0 assoclist | awk 'NR==1 {print "AssocMac=" $2}'
          capture: assoc_check
        - id: step2_getstationstats
          action: exec
          target: DUT
          command:
          - A="$(wl -i wl0 assoclist | awk 'NR==1 {print $2}')"
          - S="$(ubus-cli "WiFi.AccessPoint.1.getStationStats()" 2>/dev/null)"
          - M="$(printf '%s\\n' "$S" | grep -m1 'MACAddress = ' | cut -d'"' -f2)"
          - echo "StationStatsMac=$M"
          - printf '%s\\n' "$S" | grep -m1 'Active = ' | cut -d= -f2 | tr -d ' ,' | sed
            's/^/TopLevelActive=/'
          capture: stats_output
        verification_command:
        - wl -i wl0 assoclist
        - ubus-cli "WiFi.AccessPoint.1.getStationStats()" 2>&1 | grep -m1 'MACAddress =
          '
        - ubus-cli "WiFi.AccessPoint.1.getStationStats()" 2>&1 | grep -m1 'Active = '
        """
    )
    dst.write_text(before)

    expected_after = (
        before
        .replace(
            "id: wifi-llapi-D115-getstationstats-accesspoint",
            "id: wifi-llapi-D109-getstationstats",
            1,
        )
        .replace("  row: 115", "  row: 109", 1)
    )

    changes = ali._edit_metadata(dst, new_row=109, new_id="wifi-llapi-D109-getstationstats")

    assert changes == {
        "id": ["wifi-llapi-D115-getstationstats-accesspoint", "wifi-llapi-D109-getstationstats"],
        "source.row": [115, 109],
    }
    after = dst.read_text()
    assert after == expected_after


def test_metadata_edit_inserts_source_row_without_touching_later_nested_row(tmp_path):
    dst = tmp_path / "synthetic.yaml"
    before = dedent(
        """\
        id: wifi-llapi-D115-getstationstats-accesspoint
        name: getStationStats() — WiFi.AccessPoint.{i}.
        source:
          object: WiFi.AccessPoint.{i}.
          api: getStationStats()
        other_section:
          label: example
          row: 999
        """
    )
    dst.write_text(before)

    changes = ali._edit_metadata(dst, new_row=109, new_id=None)

    assert changes == {"source.row": [None, 109]}
    after = dst.read_text()
    assert "source:\n  row: 109\n  object: WiFi.AccessPoint.{i}.\n  api: getStationStats()" in after
    assert "other_section:\n  label: example\n  row: 999" in after
    assert "  row: 109\n" in after.split("other_section:", 1)[0]


def test_load_support_rows_returns_415_entries():
    rows = ali.load_support_rows()
    assert len(rows) == 415
    # Spot-check a known row
    assert rows[428]["object"] == "WiFi.AccessPoint.{i}.Neighbour.{i}."
    assert rows[428]["param"] == "Channel"


def test_scan_cases_returns_415_files_after_apply():
    cases = ali.scan_cases()
    # Pre-action count; verify _template.yaml is excluded
    assert "_template.yaml" not in cases
    assert len(cases) == 415
    # Spot-check a known yaml
    assert cases["D109_getstationstats.yaml"]["source_row"] == 109


def test_filename_row_parsing():
    assert ali.filename_row("D068_foo.yaml") == 68
    assert ali.filename_row("D0428_bar.yaml") == 428
    assert ali.filename_row("_template.yaml") is None


def test_plan_validates_against_pre_apply_fixture():
    rows = ali.load_support_rows()
    cases = build_pre_apply_cases_from_current_repo()
    errors = ali.validate_plan(rows, cases)
    assert errors == [], "\n".join(errors)


def test_plan_rejects_rename_source_row_drift():
    rows = ali.load_support_rows()
    cases = build_pre_apply_cases_from_current_repo()
    cases["D068_discoverymethodenabled_accesspoint_fils.yaml"]["source_row"] = 999

    errors = ali.validate_plan(rows, cases)

    assert "rename source row drift: D068_discoverymethodenabled_accesspoint_fils.yaml" in errors


def test_plan_rejects_rename_source_id_drift():
    rows = ali.load_support_rows()
    cases = build_pre_apply_cases_from_current_repo()
    cases["D068_discoverymethodenabled_accesspoint_upr.yaml"]["id"] = "wifi-llapi-D999-wrong"

    errors = ali.validate_plan(rows, cases)

    assert "rename source id drift: D068_discoverymethodenabled_accesspoint_upr.yaml" in errors


def test_plan_rejects_move_source_row_and_id_drift():
    rows = ali.load_support_rows()
    cases = build_pre_apply_cases_from_current_repo()
    cases["D495_retrycount_ssid_stats_basic.yaml"]["source_row"] = 407
    cases["D495_retrycount_ssid_stats_basic.yaml"]["id"] = "wifi-llapi-D407-retrycount"

    errors = ali.validate_plan(rows, cases)

    assert "move source row drift: D495_retrycount_ssid_stats_basic.yaml" in errors
    assert "move source id drift: D495_retrycount_ssid_stats_basic.yaml" in errors


def test_plan_rejects_metadata_only_row_drift():
    rows = ali.load_support_rows()
    cases = build_pre_apply_cases_from_current_repo()
    cases["D495_retrycount_ssid_stats_verified.yaml"]["source_row"] = 495

    errors = ali.validate_plan(rows, cases)

    assert "metadata-only source row drift: D495_retrycount_ssid_stats_verified.yaml" in errors


def test_plan_rejects_metadata_only_id_drift():
    rows = ali.load_support_rows()
    cases = build_pre_apply_cases_from_current_repo()
    cases["D495_retrycount_ssid_stats_verified.yaml"]["id"] = "wifi-llapi-d495-retrycount-wrong"

    errors = ali.validate_plan(rows, cases)

    assert "metadata-only source id drift: D495_retrycount_ssid_stats_verified.yaml" in errors


def test_plan_rejects_delete_row_drift():
    rows = ali.load_support_rows()
    cases = build_pre_apply_cases_from_current_repo()
    cases["D096_uapsdenable.yaml"]["source_row"] = 999

    errors = ali.validate_plan(rows, cases)

    assert "delete source row drift: D096_uapsdenable.yaml" in errors


def test_plan_rejects_delete_row_still_in_support_set():
    rows = ali.load_support_rows()
    cases = build_pre_apply_cases_from_current_repo()
    rows[96] = {
        "object": "WiFi.AccessPoint.{i}.",
        "type": "boolean",
        "param": "UAPSDEnable",
        "hlapi": "ubus-cli WiFi.AccessPoint.{i}.UAPSDEnable=0",
    }

    errors = ali.validate_plan(rows, cases)

    assert "delete stale row still in Support set: D096_uapsdenable.yaml" in errors


def test_verify_post_state_returns_expected_summary(monkeypatch):
    rows = {row: {} for row in range(1, 416)}
    cases = {
        f"D{row:03d}_case.yaml": {"source_row": row, "id": f"wifi-llapi-D{row:03d}-case"}
        for row in rows
    }

    class DummyTemplate:
        def exists(self) -> bool:
            return True

    monkeypatch.setattr(ali, "load_support_rows", lambda: rows)
    monkeypatch.setattr(ali, "scan_cases", lambda: cases)
    monkeypatch.setattr(ali, "TEMPLATE_YAML", DummyTemplate())

    state = ali.verify_post_state()

    assert state == {
        "total_cases": 415,
        "incl_template": 416,
        "support_rows": 415,
        "canonical_coverage": 415,
        "liberal_missing": 0,
        "liberal_missing_rows": [],
    }


def test_verify_post_state_counts_duplicate_row_coverage_once(monkeypatch):
    rows = {row: {} for row in range(1, 416)}

    class Cases(dict):
        def __len__(self) -> int:  # pragma: no cover - test helper
            return 415

    cases = Cases(
        {
            "D001_alpha.yaml": {"source_row": 1, "id": "wifi-llapi-D001-alpha"},
            "D001_beta.yaml": {"source_row": 1, "id": "wifi-llapi-D001-beta"},
            **{
                f"D{row:03d}_case.yaml": {"source_row": row, "id": f"wifi-llapi-D{row:03d}-case"}
                for row in range(2, 416)
            },
        }
    )

    class DummyTemplate:
        def exists(self) -> bool:
            return True

    monkeypatch.setattr(ali, "load_support_rows", lambda: rows)
    monkeypatch.setattr(ali, "scan_cases", lambda: cases)
    monkeypatch.setattr(ali, "TEMPLATE_YAML", DummyTemplate())

    state = ali.verify_post_state()

    assert state["canonical_coverage"] == 415


def test_project_post_cases_matches_current_snapshot_shape():
    rows = ali.load_support_rows()
    projected = ali.project_post_cases(build_pre_apply_cases_from_current_repo())
    summary = ali.summarize_inventory(rows, projected, template_exists=True)

    assert summary == {
        "total_cases": 415,
        "incl_template": 416,
        "support_rows": 415,
        "canonical_coverage": 294,
        "liberal_missing": 0,
        "liberal_missing_rows": [],
    }


def test_verify_post_state_accepts_plan_derived_noncanonical_expected_state(monkeypatch):
    rows = {1: {}, 2: {}}
    cases = {
        "D001_alpha.yaml": {"source_row": 1, "id": "wifi-llapi-D001-alpha"},
        "D099_beta.yaml": {"source_row": 2, "id": "wifi-llapi-D002-beta"},
    }

    class DummyTemplate:
        def exists(self) -> bool:
            return True

    monkeypatch.setattr(ali, "load_support_rows", lambda: rows)
    monkeypatch.setattr(ali, "scan_cases", lambda: cases)
    monkeypatch.setattr(ali, "TEMPLATE_YAML", DummyTemplate())

    expected = ali.summarize_inventory(rows, cases, template_exists=True)
    state = ali.verify_post_state(expected)

    assert state == expected


def test_verify_post_state_ignores_mismatched_filename_row_for_canonical_coverage(monkeypatch):
    rows = {1: {}}
    cases = {
        "D002_misaligned.yaml": {"source_row": 1, "id": "wifi-llapi-D001-misaligned"},
    }

    class DummyTemplate:
        def exists(self) -> bool:
            return False

    monkeypatch.setattr(ali, "load_support_rows", lambda: rows)
    monkeypatch.setattr(ali, "scan_cases", lambda: cases)
    monkeypatch.setattr(ali, "TEMPLATE_YAML", DummyTemplate())

    with pytest.raises(ali.PostStateError) as excinfo:
        ali.verify_post_state()

    assert "canonical coverage = 0/1, expected 1/1" in str(excinfo.value)


def test_verify_post_state_raises_with_missing_rows(monkeypatch):
    cases = {
        "D001_alpha.yaml": {"source_row": 1, "id": "wifi-llapi-D001-alpha"},
        "D500_other.yaml": {"source_row": 999, "id": "wifi-llapi-D500-other"},
    }

    class DummyTemplate:
        def exists(self) -> bool:
            return False

    monkeypatch.setattr(ali, "load_support_rows", lambda: {1: {}, 2: {}})
    monkeypatch.setattr(ali, "scan_cases", lambda: cases)
    monkeypatch.setattr(ali, "TEMPLATE_YAML", DummyTemplate())

    with pytest.raises(ali.PostStateError) as excinfo:
        ali.verify_post_state()

    message = str(excinfo.value)
    assert "liberal-missing rows: [2], expected []" in message
    assert "canonical coverage = 1/2, expected 2/2" in message
    assert "'liberal_missing': 1" in message
    assert "'liberal_missing_rows': [2]" in message


def test_planned_actions_match_current_plan_shapes():
    actions = ali._planned_actions()

    assert len(actions) == 17
    assert [action["kind"] for action in actions].count("rename") == 8
    assert [action["kind"] for action in actions].count("move") == 1
    assert [action["kind"] for action in actions].count("metadata") == 1
    assert [action["kind"] for action in actions].count("delete") == 6
    assert [action["kind"] for action in actions].count("create") == 1
    assert actions[0] == {
        "kind": "rename",
        "row": 66,
        "from": "D068_discoverymethodenabled_accesspoint_fils.yaml",
        "to": "D066_discoverymethodenabled_accesspoint_fils.yaml",
        "fields_changed": {
            "id": [
                "wifi-llapi-D068-discoverymethodenabled-accesspoint-fils",
                "wifi-llapi-D066-discoverymethodenabled-accesspoint-fils",
            ],
            "source.row": [68, 66],
        },
    }
    assert actions[-1] == {
        "kind": "create",
        "row": 428,
        "from": "_template.yaml",
        "to": "D428_channel_neighbour.yaml",
        "fields_changed": {
            "id": [None, "wifi-llapi-D428-channel-neighbour"],
            "source.row": [None, 428],
            "source.object": [None, "WiFi.AccessPoint.{i}.Neighbour.{i}."],
            "source.api": [None, "Channel"],
        },
    }


def test_ensure_clean_worktree_allows_only_known_report_paths(monkeypatch):
    monkeypatch.setattr(
        ali.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            stdout=(
                " M tools/oneoff/2026-04-24-align-missing-rows/inventory_alignment_20260424.md\n"
                " M tools/oneoff/2026-04-24-align-missing-rows/inventory_alignment_20260424.json\n"
            )
        ),
    )

    ali._ensure_clean_worktree()


def test_ensure_clean_worktree_still_rejects_non_report_dirtiness(monkeypatch):
    monkeypatch.setattr(
        ali.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            stdout=(
                " M tools/oneoff/2026-04-24-align-missing-rows/inventory_alignment_20260424.md\n"
                " M README.md\n"
            )
        ),
    )

    with pytest.raises(RuntimeError) as excinfo:
        ali._ensure_clean_worktree()

    assert "README.md" in str(excinfo.value)


def test_main_dry_run_writes_both_reports_and_returns_zero(monkeypatch, tmp_path, capsys):
    markdown_path = tmp_path / "inventory_alignment_20260424.md"
    json_path = tmp_path / "inventory_alignment_20260424.json"
    support_rows = {
        428: {
            "object": "WiFi.AccessPoint.{i}.Neighbour.{i}.",
            "type": "unsignedInt",
            "param": "Channel",
            "hlapi": 'ubus-cli "WiFi.AccessPoint.{i}.Neighbour.{i}.Channel=36"',
        }
    }
    cases = {
        "D115_getstationstats_accesspoint.yaml": {
            "source_row": 115,
            "id": "wifi-llapi-D115-getstationstats-accesspoint",
        }
    }

    monkeypatch.setattr(ali, "REPORT_MD", markdown_path)
    monkeypatch.setattr(ali, "REPORT_JSON", json_path)
    monkeypatch.setattr(ali, "load_support_rows", lambda: support_rows)
    monkeypatch.setattr(ali, "scan_cases", lambda: cases)
    monkeypatch.setattr(ali, "validate_plan", lambda rows, scanned: [])

    rc = ali.main([])
    captured = capsys.readouterr()

    assert rc == 0
    assert markdown_path.exists()
    assert json_path.exists()
    payload = json.loads(json_path.read_text())
    assert payload["mode"] == "dry-run"
    assert payload["post_state"] is None
    assert len(payload["actions"]) == 17
    assert "mode=dry-run | support_rows=1 | current_cases=1" in captured.out
    assert (
        "reports: inventory_alignment_20260424.md, inventory_alignment_20260424.json"
        in captured.out
    )


def test_write_markdown_report_groups_actions_into_four_sections(monkeypatch, tmp_path):
    markdown_path = tmp_path / "inventory_alignment_20260424.md"
    monkeypatch.setattr(ali, "REPORT_MD", markdown_path)
    actions = ali._planned_actions()

    output = ali.write_markdown_report("dry-run", actions, None)

    assert output == markdown_path
    content = markdown_path.read_text()
    assert "# wifi_llapi inventory alignment report" in content
    assert "## Renames (8)" in content
    assert "## Move + Metadata Fix (2)" in content
    assert "## Deletes (6)" in content
    assert "## New from _template.yaml (1)" in content
    assert "## Actions" not in content
    assert content.count("| 66 | `D068_discoverymethodenabled_accesspoint_fils.yaml` |") == 1
    assert content.count("| 407 | `D495_retrycount_ssid_stats_basic.yaml` |") == 1
    assert content.count("| — | `D096_uapsdenable.yaml` | `—` | — |") == 1
    assert content.count("| 428 | `_template.yaml` | `D428_channel_neighbour.yaml` |") == 1
    assert "## Post state" in content
    assert "_not-run_" in content


def test_main_fails_when_plan_validation_errors_exist(monkeypatch, capsys):
    support_rows = {
        428: {
            "object": "WiFi.AccessPoint.{i}.Neighbour.{i}.",
            "type": "unsignedInt",
            "param": "Channel",
            "hlapi": 'ubus-cli "WiFi.AccessPoint.{i}.Neighbour.{i}.Channel=36"',
        }
    }
    cases = {
        "D115_getstationstats_accesspoint.yaml": {
            "source_row": 115,
            "id": "wifi-llapi-D115-getstationstats-accesspoint",
        }
    }

    monkeypatch.setattr(ali, "load_support_rows", lambda: support_rows)
    monkeypatch.setattr(ali, "scan_cases", lambda: cases)
    monkeypatch.setattr(
        ali,
        "validate_plan",
        lambda rows, scanned: [
            "rename source missing: D068_discoverymethodenabled_accesspoint_fils.yaml",
            "delete source row drift: D096_uapsdenable.yaml",
        ],
    )

    rc = ali.main([])
    captured = capsys.readouterr()

    assert rc != 0
    assert "plan validation failed" in captured.err
    assert "rename source missing: D068_discoverymethodenabled_accesspoint_fils.yaml" in captured.err
    assert "delete source row drift: D096_uapsdenable.yaml" in captured.err
    assert "mode:" not in captured.out


def test_main_apply_writes_reports_before_reraising_post_state_failure(monkeypatch):
    support_rows = {
        428: {
            "object": "WiFi.AccessPoint.{i}.Neighbour.{i}.",
            "type": "unsignedInt",
            "param": "Channel",
            "hlapi": 'ubus-cli "WiFi.AccessPoint.{i}.Neighbour.{i}.Channel=36"',
        }
    }
    cases = {
        "D115_getstationstats_accesspoint.yaml": {
            "source_row": 115,
            "id": "wifi-llapi-D115-getstationstats-accesspoint",
        }
    }
    calls: list[tuple[str, str, list[dict], dict | None]] = []
    actions = [{"kind": "rename", "row": 109, "from": "old.yaml", "to": "new.yaml", "fields_changed": {}}]

    monkeypatch.setattr(ali, "load_support_rows", lambda: support_rows)
    monkeypatch.setattr(ali, "scan_cases", lambda: cases)
    monkeypatch.setattr(ali, "validate_plan", lambda rows, scanned: [])
    monkeypatch.setattr(ali, "_ensure_clean_worktree", lambda: None)
    monkeypatch.setattr(ali, "_apply_actions", lambda: actions)
    monkeypatch.setattr(ali, "project_post_cases", lambda scanned: clone_cases(scanned))

    def fail_verify(_expected_state: dict) -> dict:
        raise ali.PostStateError("post-state failed")

    monkeypatch.setattr(ali, "verify_post_state", fail_verify)
    monkeypatch.setattr(
        ali,
        "write_markdown_report",
        lambda mode, report_actions, post_state: calls.append(("md", mode, report_actions, post_state)) or Path("report.md"),
    )
    monkeypatch.setattr(
        ali,
        "write_json_report",
        lambda mode, report_actions, post_state: calls.append(("json", mode, report_actions, post_state)) or Path("report.json"),
    )

    with pytest.raises(ali.PostStateError, match="post-state failed"):
        ali.main(["--apply"])

    assert calls == [
        ("md", "apply", actions, None),
        ("json", "apply", actions, None),
    ]


def test_main_apply_writes_partial_reports_before_reraising_apply_failure(monkeypatch):
    support_rows = {
        428: {
            "object": "WiFi.AccessPoint.{i}.Neighbour.{i}.",
            "type": "unsignedInt",
            "param": "Channel",
            "hlapi": 'ubus-cli "WiFi.AccessPoint.{i}.Neighbour.{i}.Channel=36"',
        }
    }
    cases = {
        "D115_getstationstats_accesspoint.yaml": {
            "source_row": 115,
            "id": "wifi-llapi-D115-getstationstats-accesspoint",
        }
    }
    calls: list[tuple[str, str, list[dict], dict | None]] = []
    partial_actions = [
        {"kind": "rename", "row": 109, "from": "old.yaml", "to": "new.yaml", "fields_changed": {}},
        {"kind": "delete", "row": None, "from": "stale.yaml", "to": None, "fields_changed": {}},
    ]

    monkeypatch.setattr(ali, "load_support_rows", lambda: support_rows)
    monkeypatch.setattr(ali, "scan_cases", lambda: cases)
    monkeypatch.setattr(ali, "validate_plan", lambda rows, scanned: [])
    monkeypatch.setattr(ali, "_ensure_clean_worktree", lambda: None)
    monkeypatch.setattr(ali, "project_post_cases", lambda scanned: clone_cases(scanned))

    def fail_apply() -> list[dict]:
        raise ali.ApplyActionsError("apply failed", partial_actions)

    monkeypatch.setattr(ali, "_apply_actions", fail_apply)
    monkeypatch.setattr(
        ali,
        "write_markdown_report",
        lambda mode, report_actions, post_state: calls.append(("md", mode, report_actions, post_state)) or Path("report.md"),
    )
    monkeypatch.setattr(
        ali,
        "write_json_report",
        lambda mode, report_actions, post_state: calls.append(("json", mode, report_actions, post_state)) or Path("report.json"),
    )

    with pytest.raises(ali.ApplyActionsError, match="apply failed"):
        ali.main(["--apply"])

    assert calls == [
        ("md", "apply", partial_actions, None),
        ("json", "apply", partial_actions, None),
    ]
