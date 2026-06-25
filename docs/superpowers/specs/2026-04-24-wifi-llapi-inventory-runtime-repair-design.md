# wifi_llapi inventory + runtime repair design

## Problem

`wifi_llapi` official case inventory has drifted away from the current checked-in template workbook. The current `main` branch shows three related failures:

1. some official workbook rows no longer have a canonical discoverable YAML (for example `D407`)
2. some discoverable YAML files still carry stale canonical metadata (for example `D495_retrycount_ssid_stats_verified.yaml` keeping a stale `source.row`)
3. runtime alignment blocks on `(source.object, source.api)` families with multiple workbook rows because it does not use `source.row` to disambiguate

This creates a broken state where:

- docs can claim a row is aligned while the repo inventory no longer contains the canonical case file
- reruns of row-correct cases can still be blocked by `ambiguous_object_api_family`
- duplicate or stale historical YAML can remain discoverable and pollute official inventory

The repair must use the **current template workbook** as the only authoritative source and must restore a strict discoverable inventory: **one discoverable official YAML per workbook row**.

## Goals

1. rebuild canonical discoverable inventory from the current template workbook
2. restore any missing official case YAML required by the workbook
3. remove discoverable duplicates and drifted historical leftovers from official inventory
4. update runtime alignment so multi-row object/api families use `source.row` before blocking
5. resync repo documentation and handoff records to match the repaired inventory
6. re-check all blockers that can cause rows to be skipped, blocked, or silently omitted before claiming completion

## Non-goals

- changing workbook contents
- changing live calibration semantics, step commands, or pass criteria unless required to preserve the canonical row's existing meaning
- redesigning the broader wifi_llapi reporting pipeline

## Authoritative rules

### Workbook authority

The checked-in template workbook defines the canonical official row set. Historical repo state is reference material only; it is not authoritative when it conflicts with the current workbook.

### Canonical inventory invariant

For every official workbook row:

- exactly one discoverable YAML must exist
- that YAML must use the canonical row in `source.row`
- filename `D###_*.yaml` must match the canonical row
- any row-bearing official `id` must match the canonical row

Historical or duplicate YAML may exist only if they are explicitly demoted out of discoverable official inventory. They must not remain discoverable.

### Runtime disambiguation invariant

When `(source.object, source.api)` maps to multiple workbook rows, runtime alignment must:

1. inspect `source.row`
2. choose that row if it is one of the candidate rows
3. block only when `source.row` is missing or not part of the candidate family

This keeps runtime deterministic while preserving workbook-driven inventory repair.

## Proposed approach

Use a two-layer repair:

1. **inventory-first canonicalization**
2. **runtime row-based disambiguation**

This addresses both root causes:

- broken or incomplete official inventory
- runtime family ambiguity even when a case already has the correct canonical row

## Design

### 1. Inventory audit layer

Add a workbook-driven audit pass that compares the current official workbook row set with discoverable YAML under `plugins/wifi_llapi/cases/`.

The audit output must classify each item into:

- `canonical_rows`: workbook rows already represented by one correct discoverable YAML
- `missing_rows`: workbook rows with no canonical discoverable YAML
- `drifted_cases`: discoverable YAML whose row, filename, id, or object/api metadata does not match the canonical workbook row they should represent
- `extra_cases`: discoverable YAML that do not belong in the canonical official inventory
- `duplicate_rows`: more than one discoverable YAML trying to represent the same workbook row

The audit result must be machine-checkable so tests can assert inventory completeness and uniqueness.

### 2. Canonicalization rules

#### Missing rows

If a workbook row is official but missing from discoverable inventory, create or restore a canonical YAML for that row.

Preferred reconstruction order:

1. reuse the closest historical YAML that already represents the same workbook row semantics
2. if no exact historical YAML exists, reuse the nearest drifted YAML for that row family and normalize its row-bearing metadata
3. only if neither exists, synthesize a canonical YAML from workbook/template metadata plus existing repo conventions

The result must land as a canonical discoverable file for the exact workbook row.

#### Drifted rows

If a discoverable YAML should represent a canonical workbook row but carries stale metadata, rewrite:

- filename
- `source.row`
- row-bearing `id`

Any non-row-bearing metadata should stay unchanged unless required to preserve canonical workbook identity.

#### Extra or duplicate rows

If a discoverable YAML is not part of the canonical workbook inventory, it must exit discoverable official inventory.

If its contents are still useful for tests or historical reference, demote it to an underscore-prefixed fixture-style file so `load_cases_dir()` no longer discovers it.

### 3. Runtime alignment changes

Update `align_case()` so `ambiguous_object_api_family` is not emitted immediately when multiple template rows share the same `(source.object, source.api)`.

New behavior:

1. read candidate rows from `TemplateIndex.by_object_api[(obj, api)]`
2. if there is exactly one candidate row, keep current behavior
3. if there are multiple candidates:
   - if `source.row_before` is a member of that candidate set, select it as the canonical row
   - otherwise block with `ambiguous_object_api_family` and include candidate rows
4. keep the later `name`-vs-template API checks unchanged after a single target row has been chosen

This preserves guardrails while allowing deterministic execution for row-correct cases such as:

- `D308`
- `D313`
- `D316`
- `D495 basic`

Cases such as stale `D495 verified` should still be surfaced as drift/blocker candidates until their canonical row is repaired.

### 4. Blocker re-audit before completion

Before declaring the repair complete, run a full blocker sweep over the repaired inventory and runtime path.

The sweep must explicitly account for anything that can cause a case to be:

- skipped
- blocked
- silently excluded from discoverable inventory
- shadowed by a duplicate canonical row

Completion requires proving that all workbook-authoritative official rows are either:

- present as canonical discoverable YAML, or
- explicitly listed as a blocker with a concrete reason

No row may disappear implicitly.

### 5. Documentation sync

Update repo handoff documents that describe official inventory status so they match the repaired inventory exactly.

At minimum, reconcile:

- `README.md`
- `docs/plan.md`
- `docs/todos.md`
- any active audit or handoff doc that references the repaired rows

The key rule is simple: documentation must not claim an official row exists or is aligned unless the canonical discoverable YAML is actually present in the repo.

## Components affected

- `src/testpilot/reporting/wifi_llapi_align.py`
- inventory audit / normalization helpers in the existing wifi_llapi case-loading and reporting area
- `plugins/wifi_llapi/cases/`
- runtime and regression tests covering alignment and inventory integrity
- repo handoff docs that describe official inventory state

## Validation plan

### Inventory validation

- assert official workbook rows and discoverable YAML are in 1:1 correspondence
- assert each canonical row appears exactly once in discoverable inventory
- assert no extra discoverable YAML claims an official canonical row outside the workbook-defined set

### Runtime validation

- add regression coverage for multi-row object/api family disambiguation using `source.row`
- verify row-correct cases no longer block with `ambiguous_object_api_family`
- verify stale-row cases still surface as blockers until repaired

### Integration validation

- rerun representative problematic rows, including the currently affected families around `D308/D313/D316/D407/D495`
- confirm they are executed or explicitly blocked for a concrete remaining reason, never silently skipped

### Documentation validation

- compare repaired inventory against official-row claims in repo docs
- remove or fix any stale claim that references rows no longer present in discoverable inventory

## Risks and controls

### Risk: wrong historical YAML chosen as canonical source

Control: workbook row remains authoritative; history is only a reconstruction aid.

### Risk: runtime fix masks inventory bugs

Control: keep inventory audit and runtime disambiguation as separate checks. Runtime may use `source.row`, but inventory still must prove one canonical YAML per workbook row.

### Risk: silent omission of rows during cleanup

Control: blocker re-audit is a required gate before completion. Missing rows must be explicit.

## Definition of done

The change is complete only when all of the following are true:

1. every official workbook row has exactly one canonical discoverable YAML
2. discoverable inventory contains no duplicate canonical rows
3. drifted historical files no longer pollute discoverable official inventory
4. runtime uses `source.row` to disambiguate multi-row object/api families
5. representative reruns are no longer blocked only because of family ambiguity when the case already has the correct row
6. all remaining skip/block conditions have been re-audited and explicitly accounted for
7. documentation matches the actual repaired inventory
