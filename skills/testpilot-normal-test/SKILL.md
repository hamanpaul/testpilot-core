---
name: testpilot-normal-test
description: Use when running TestPilot wifi_llapi normal tests with GPT-5-mini, including full campaign runs or focused case reruns.
---

# TestPilot Normal Test

## Overview

Use this skill when GPT-5-mini operates TestPilot `wifi_llapi` normal tests. Normal test means runtime execution through the installed `testpilot wifi_llapi` command; it is not audit mode, repository pytest, schema cleanup, report comparison, or YAML editing.

## Allowed Modes

Only two allowed modes:

| Mode | Command shape | Purpose |
| --- | --- | --- |
| `full-run` | `testpilot wifi_llapi` | Execute the complete discoverable `wifi_llapi` catalog and produce a report bundle. |
| `by-case` | `testpilot wifi_llapi --case <CASE_ID>` | Re-run one explicit case, or a small explicit set of cases, using normal runtime behavior. |

`testpilot run wifi_llapi` remains a compatibility path for legacy scripts, but the installed `testpilot wifi_llapi` entry point is preferred.

## Hard Boundaries

- Do not use repo pytest as a substitute for normal test execution.
- Do not run audit commands (`testpilot audit ...`) under this skill.
- Do not edit case YAML, template workbooks, or plugin code while operating in normal-test mode.
- Do not invent batch modes other than `full-run` and `by-case`.
- If alignment blocks or skipped cases appear, report them and stop normal-test interpretation; fixes belong to a separate development workflow.

## Required Report Checks

After a normal run, read the generated JSON report and verify:

1. `summary.total_cases`
2. `meta.alignment_summary.blocked`
3. `meta.alignment_summary.skipped`
4. `agent_trace/` JSON count
5. `DUT.log` and `STA.log` exist and correspond to the current report bundle

## Documents to Keep in Sync

When changing this skill, normal-test commands, report interpretation, or `wifi_llapi` execution policy, check whether these files must be updated in the same PR:

- `README.md`
- `docs/plan.md`
- `docs/todos.md`
- `AGENTS.md`
- `plugins/wifi_llapi/agent-config.yaml`
- `plugins/wifi_llapi/testbed.yaml.example`

## Common Mistakes

| Mistake | Correct behavior |
| --- | --- |
| Running pytest and calling it a full run | Use `testpilot wifi_llapi`. |
| Treating blocked/skipped as executed failures | Report them as coverage blockers. |
| Rewriting YAML during normal-test mode | Stop and switch to the appropriate development or audit workflow. |
| Summarizing only pass/fail totals | Include coverage, alignment blocked/skipped, artifact paths, and log presence. |
