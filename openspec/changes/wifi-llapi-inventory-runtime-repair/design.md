## Context

`wifi_llapi` runtime alignment and official case inventory have diverged in two ways.

First, the repo no longer guarantees that every official workbook row has exactly one discoverable YAML. Some rows are missing entirely, while other historical YAML remain discoverable with stale row-bearing metadata.

Second, runtime alignment currently treats any duplicate `(source.object, source.api)` template family as an unconditional block. That guardrail was useful for surfacing ambiguity, but it now blocks row-correct cases that already carry the canonical `source.row`.

The change has to repair both layers together. If only runtime changes, broken inventory remains in the repo. If only inventory changes, future family collisions still block valid reruns.

## Goals / Non-Goals

**Goals:**
- make the current checked-in template workbook the authoritative source for official inventory
- ensure every official workbook row maps to exactly one discoverable YAML
- restore missing official rows and remove duplicate discoverable leftovers from canonical inventory
- allow runtime alignment to use `source.row` to resolve ambiguous template families before blocking
- keep blocked/skip states explicit so no official row disappears silently

**Non-Goals:**
- changing workbook contents
- changing live case semantics, pass criteria, or calibration intent beyond row/inventory repair
- redesigning the broader reporting pipeline or non-`wifi_llapi` plugins

## Decisions

### Decision: Introduce a workbook-driven inventory audit/reconcile layer

The repair will add a dedicated inventory helper that audits discoverable YAML against workbook rows and classifies cases as canonical, missing, drifted, duplicate, or extra.

This is preferred over ad hoc manual cleanup because the problem has already drifted over multiple days and needs a machine-checkable invariant. A formal audit also gives tests a stable API for asserting 1:1 inventory.

Alternative considered: repair the current case set manually and rely on runtime checks only. Rejected because it would not prevent future silent drift and would provide no reusable repo-scale validation.

### Decision: Keep runtime guardrails, but let `source.row` break family ties

`align_case()` will still treat duplicate `(source.object, source.api)` families as special handling, but it will first inspect `source.row`. If that row is one of the candidate rows, runtime will choose it deterministically. Only unresolved family collisions remain blocked as `ambiguous_object_api_family`.

This preserves the guardrail's purpose while unblocking row-correct cases such as the current `D308/D313/D316/D495` family.

Alternative considered: always block any duplicate family and force inventory cleanup first. Rejected because even after inventory repair the workbook can still contain legitimate duplicate object/api families that require row-based selection.

### Decision: Missing rows are restored from repo history before any synthesis

When a workbook row is missing from discoverable inventory, the reconcile flow will first search git history for the latest matching canonical `D###_*.yaml` file. Only if no historical candidate exists should the repair stop with an explicit blocker.

This minimizes semantic drift because historical YAML usually carry the closest row-specific content already validated in the project.

Alternative considered: synthesize missing YAML directly from workbook metadata. Rejected as the default because workbook metadata alone may not preserve case-specific topology and step structure.

### Decision: Non-canonical leftovers exit discoverable inventory

Historical or duplicate YAML that are no longer canonical will be demoted out of discoverable inventory, preferably by underscore prefix when their contents still have fixture value.

This follows the existing repo rule that underscore-prefixed YAML are excluded from `load_cases_dir()`.

Alternative considered: leave extra YAML discoverable and rely on collision resolution. Rejected because it keeps official inventory ambiguous and allows docs to drift from the actual canonical set.

## Risks / Trade-offs

- **Wrong historical file restored for a missing row** → Use workbook row as the canonical key and fail explicitly if history lookup is ambiguous or absent.
- **Runtime disambiguation masks broken inventory** → Keep inventory audit and runtime disambiguation as separate validations; runtime success alone is not enough.
- **Repo-scale YAML rewrite causes noisy diffs** → Isolate the repair in a dedicated worktree and commit runtime logic separately from inventory/application diffs.
- **Some rows remain blocked after repair** → Require a blocker re-audit pass and explicit reporting before claiming completion.

## Migration Plan

1. Add regression tests for row-based runtime disambiguation.
2. Implement runtime disambiguation in `wifi_llapi_align.py`.
3. Add inventory audit/reconcile helpers and tests.
4. Run reconcile flow against `plugins/wifi_llapi/cases/` to restore missing rows and demote non-canonical leftovers.
5. Re-run targeted runtime tests and the problematic case set.
6. Sync README / handoff docs to the repaired canonical inventory.

Rollback is straightforward:

- revert the runtime alignment commit if row disambiguation proves unsafe
- revert the inventory reconcile commit if the applied YAML repair is incorrect

Because inventory and runtime changes are separated, rollback can be targeted.

## Open Questions

- Whether any workbook-official row lacks a recoverable historical YAML and will need a follow-up manual blocker resolution
- Whether any repo docs outside `README.md`, `docs/plan.md`, and `docs/todos.md` still claim canonical rows that do not exist after reconciliation
