## Why

`wifi_llapi` runtime alignment already exists in `src/testpilot/reporting/wifi_llapi_align.py`, but the current implementation still has two correctness gaps:

1. `_extract_name_api()` uses `text.split(".")[-1]`, so a name like `FailedRetransCount - WiFi.SSID.{i}.getSSIDStats().` produces an empty token and silently skips validation instead of proving the name matches the template API.
2. `build_template_index()` stores only one row per `(source.object, source.api)`, so duplicate getter families such as `getSSIDStats()` and `getRadioStats()` collapse to a single row and can auto-mutate unrelated cases into the same template target.

The result is that the recent D308/D313/D316 fix (`865207a`) unblocked execution by bypassing validation, not by making alignment trustworthy. A repo-wide audit in the same codebase also showed that the issue is systemic: duplicate getter families exist in the checked-in template and the current aligner cannot safely disambiguate them.

## What Changes

- Tighten name-token extraction so structured display names no longer bypass validation when they include trailing object paths or punctuation.
- Change template indexing for `(source.object, source.api)` from "pick one row" to "detect unique vs ambiguous family" and refuse auto-alignment for ambiguous families.
- Add an explicit blocked reason for ambiguous families and surface candidate template rows in runtime artifacts so follow-up cleanup is actionable.
- Keep unique `(object, api)` cases on the current auto-alignment path; do not expand this change into a full corpus rewrite.
- Update tests, docs, and implementation plan so future fixes do not rely on YAML display-name workarounds.
- **BREAKING**: cases that currently auto-align through ambiguous duplicate getter families will stop mutating at runtime and be reported as blocked until a later discriminator/corpus cleanup is added.

## Capabilities

### New Capabilities

- `wifi-llapi-alignment-guardrails`: Define robust display-name parsing, ambiguous family detection, and runtime artifact reporting for guarded wifi_llapi alignment.

### Modified Capabilities

None (no archived specs exist under `openspec/specs/` yet).

## Impact

**Code**:
- `src/testpilot/reporting/wifi_llapi_align.py` - strengthen `_extract_name_api()`, represent duplicate template families explicitly, add a new blocked reason, and enrich blocked report output.
- `src/testpilot/core/orchestrator.py` - preserve the existing alignment pipeline but expose the new blocked reason in `alignment_summary`.
- `plugins/wifi_llapi/tests/test_wifi_llapi_align.py` - add parser and ambiguous-family regression coverage.
- `plugins/wifi_llapi/tests/test_orchestrator_realistic_runtime.py` - assert ambiguous families are blocked, not collision-skipped.

**Runtime behavior**:
- Unique `(source.object, source.api)` cases continue to auto-align.
- Ambiguous families such as `getSSIDStats()` stop mutating YAML automatically and are surfaced as blocked work.

**Docs**:
- `CHANGELOG.md`, `AGENTS.md`, and `README.md` need a short note that runtime alignment now rejects ambiguous template families instead of silently choosing a winner.

**Out of scope**:
- Rewriting the full `plugins/wifi_llapi/cases/` corpus.
- Adding new YAML discriminator fields or changing case semantics.
- Resolving the unrelated baseline failure in `plugins/wifi_llapi/tests/test_wifi_llapi_plugin_runtime.py::test_pre_skip_aligned_manual_cases_avoid_stale_sample_values`.
