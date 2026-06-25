## Context

`main` already ships the runtime alignment pipeline that was originally designed in `docs/superpowers/specs/2026-04-22-wifi-llapi-runtime-alignment-design.md`:

- `src/testpilot/reporting/wifi_llapi_align.py` builds a template index, classifies cases, mutates YAML, and emits `blocked_cases.md` / `skipped_cases.md`.
- `src/testpilot/core/orchestrator.py` calls that aligner before execution and records `alignment_summary`.
- `plugins/wifi_llapi/tests/test_wifi_llapi_align.py` and `plugins/wifi_llapi/tests/test_orchestrator_realistic_runtime.py` already cover the happy path.

What is missing is a safe boundary for structured display names and duplicate template families. The recent D308/D313/D316 change exposed that gap: adding `getSSIDStats().` to the tail of the name made `_extract_name_api()` return `""`, which disabled the validation branch entirely. A repo-wide audit also confirmed that the template contains duplicate `(object, api)` families (`getSSIDStats()`, `getRadioStats()`, `getScanResults()`), so the current one-row `by_object_api` map is fundamentally unsafe for those cases.

Stakeholders: wifi_llapi plugin maintainers, runtime operators who rely on report fidelity, and auditors who need clear blocked artifacts instead of silent YAML mutation.

## Goals / Non-Goals

**Goals:**
- Make name-token extraction deterministic for structured display names so punctuation cannot suppress validation.
- Represent duplicate template families explicitly and block them before any YAML mutation happens.
- Preserve the existing auto-alignment path for unique `(source.object, source.api)` lookups.
- Produce actionable runtime artifacts for ambiguous families without folding this work into a full corpus rewrite.

**Non-Goals:**
- Do not solve every existing `name_not_in_template` case in the repository.
- Do not add new YAML schema fields or rewrite `name`, `steps`, `pass_criteria`, `source.object`, or `source.api`.
- Do not redesign runtime alignment from scratch; this is a guardrail change on top of the current implementation.
- Do not fix the unrelated pre-existing plugin-runtime test failure that already exists in the new worktree baseline.

## Decisions

### 1. Replace split-on-last-dot parsing with structured token extraction

**Choice:** `_extract_name_api()` will extract the last method token like `getSSIDStats()` if one appears anywhere in the display name. If no method token exists but the name uses a structured display form like `AssociationTime - WiFi.AccessPoint.{i}.AssociatedDevice.{i}.`, the extractor will use the display token before the separator. Otherwise it will return the original text for legacy flat names.

**Why:** This removes the `...getSSIDStats().` bypass, keeps existing method-style names (`kickStation() - WiFi.AccessPoint.{i}.`) valid, and avoids turning every legacy prose name into an implicit pass.

**Alternatives considered:**
- Keep `split(".")[-1]` and only add more YAML workarounds. Rejected because it reproduces the same bypass.
- Reject every case whose extracted token is empty. Rejected because many already-aligned method cases intentionally use object-path suffixes in `name`.

### 2. Treat `(source.object, source.api)` as a family, not a single row

**Choice:** `TemplateIndex.by_object_api` becomes a one-to-many map and `align_case()` distinguishes:
- zero matching rows -> `object_api_not_in_template`
- one matching row -> current alignment path
- more than one matching row -> new blocked reason `ambiguous_object_api_family`

**Why:** The template itself already proves that duplicate getter families exist. Picking one row during indexing loses information and causes incorrect mutations before the code even has a chance to reason about ambiguity.

**Alternatives considered:**
- Keep the existing dict and let "last row wins". Rejected because this is the root cause of the current collision behavior.
- Pick the first row and keep `_resolve_collisions()` as the safety net. Rejected because it still mutates the wrong case before reporting the conflict.

### 3. Block ambiguous families before collision resolution

**Choice:** `ambiguous_object_api_family` cases never enter the runnable pool, so `_resolve_collisions()` only sees unique-row results.

**Why:** Collision resolution is still useful for true duplicate YAML files that point at the same unique template row. It is not the right mechanism for template families where the aligner itself cannot prove which row is correct.

**Alternatives considered:**
- Reuse `skipped` for ambiguous families. Rejected because `skipped` implies there is a deterministic winner, which is false here.
- Guess the correct row from the parsed name token. Rejected because getter families intentionally reuse the same API token across many rows.

### 4. Enrich blocked reporting with candidate rows

**Choice:** `AlignResult` gets `candidate_template_rows`, and `write_blocked_cases_report()` emits those rows for ambiguous families. `alignment_summary` carries the new blocked reason counts through the existing summary path.

**Why:** Once runtime stops auto-mutating ambiguous families, the blocked artifact becomes the handoff document for later corpus cleanup. Candidate rows must be visible there; otherwise operators still have to reverse-engineer the template by hand.

**Alternatives considered:**
- Keep the current blocked report shape. Rejected because it hides the exact ambiguity the operator needs to resolve.

### 5. Defer corpus rewrite to a later follow-up

**Choice:** This change stops at guardrails and reporting. It intentionally does not try to rewrite all affected YAMLs in the same PR.

**Why:** The audit already showed that the problem surface is much larger than the recent three-case workaround. Guardrails are safe to merge first; bulk metadata cleanup should happen only after runtime no longer guesses.

## Risks / Trade-offs

- **[Risk]** Some cases that currently run will become blocked once ambiguous families stop auto-aligning. -> **Mitigation**: document the behavior change and surface candidate rows in `blocked_cases.md` and `alignment_summary`.
- **[Risk]** A more permissive structured parser could accidentally un-block legacy prose names. -> **Mitigation**: keep the parser conservative for non-structured names and add regression tests for both method and property display forms.
- **[Risk]** Repo-scale counts will change once ambiguous families are blocked. -> **Mitigation**: update the repo-scale test to assert representative samples and reason-specific counts instead of relying only on the old aggregate shape.
- **[Trade-off]** This change improves correctness by reducing automatic mutation coverage. That slows down cleanup for ambiguous families, but it prevents runtime from silently mutating the wrong files.

## Migration Plan

1. Update `test_wifi_llapi_align.py` with parser and ambiguous-family regression tests.
2. Modify `wifi_llapi_align.py` to:
   - extract structured tokens safely,
   - preserve one-to-many template families,
   - emit `ambiguous_object_api_family`,
   - attach candidate rows to blocked results.
3. Update orchestrator/runtime integration tests to reflect "blocked, not skipped" for ambiguous families.
4. Update docs (`CHANGELOG.md`, `README.md`, `AGENTS.md`) to describe the new guardrail and its runtime effect.
5. Validate with targeted alignment tests and the repo baseline, recording the existing unrelated failure separately.

**Rollback:** revert the code/docs commit. No data migration is required because this change reduces runtime mutation rather than introducing a new disk format.

## Open Questions

1. Which discriminator should a later corpus-cleanup change use for duplicate getter families: parsed field name, filename suffix, or an explicit YAML metadata field?
2. Should the eventual follow-up add a dedicated `alignment audit` command that inventories ambiguous families without running DUT/STA execution?
