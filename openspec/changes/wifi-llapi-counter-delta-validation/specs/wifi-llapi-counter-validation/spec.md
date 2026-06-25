## ADDED Requirements

### Requirement: Case YAML SHALL support a step-level `phase` label

The wifi_llapi case yaml SHALL accept an optional `phase: baseline | trigger | verify` field on each step. Steps that do not declare a `phase` MUST be treated as `verify` for backward compatibility.

#### Scenario: Step declares baseline phase
- **WHEN** a step contains `phase: baseline`
- **THEN** the runtime classifies the step as a baseline capture
- **AND** the step is recognized as occurring before any `trigger` step

#### Scenario: Step declares trigger phase
- **WHEN** a step contains `phase: trigger`
- **THEN** the runtime classifies the step as the workload-trigger phase
- **AND** the step is allowed to perform side-effects without producing a captured value

#### Scenario: Step omits phase declaration
- **WHEN** a step does not contain a `phase` field
- **THEN** the runtime treats the step as `phase: verify`
- **AND** existing case yaml that predates this change continues to execute unchanged

#### Scenario: Step declares an unknown phase value
- **WHEN** a step contains `phase: warmup` or any value other than `baseline`, `trigger`, `verify`
- **THEN** schema validation rejects the case with reason `unknown phase: <value>`

### Requirement: Phase ordering MUST be validated at case load time when a case uses any delta operator

When any `pass_criteria` entry in a case contains a `delta:` key, case loading SHALL verify that all `phase: baseline` steps precede all `phase: trigger` steps, and all `phase: verify` steps follow all `phase: trigger` steps. The case MUST also contain at least one `phase: trigger` step. Cases that violate these constraints MUST be classified as BLOCKED with a `blocked_reason` beginning with `invalid_delta_schema:`. Validation MUST NOT raise; other cases MUST continue loading unaffected.

#### Scenario: Valid baseline-trigger-verify ordering
- **WHEN** a case has steps in order [baseline, baseline, trigger, verify, verify] and uses `delta_nonzero`
- **THEN** the case loads successfully
- **AND** runtime evaluation proceeds normally

#### Scenario: Case with no delta operator skips phase validation
- **WHEN** a case has only `field+value` or `field+reference` pass criteria (no `delta:`)
- **THEN** phase ordering is not validated regardless of step phase labels
- **AND** the case loads successfully

#### Scenario: Missing trigger step
- **WHEN** a case uses `delta_nonzero` but contains only baseline and verify steps
- **THEN** the case is classified as BLOCKED
- **AND** `blocked_reason` is `invalid_delta_schema: delta_* operators require at least one phase=trigger step`

#### Scenario: Baseline step ordered after trigger
- **WHEN** a case has steps [baseline, trigger, baseline, verify] and uses `delta_match`
- **THEN** the case is classified as BLOCKED
- **AND** `blocked_reason` is `invalid_delta_schema: baseline step must precede trigger; ...`

#### Scenario: Verify step ordered before trigger
- **WHEN** a case has steps [baseline, verify, trigger] and uses `delta_nonzero`
- **THEN** the case is classified as BLOCKED
- **AND** `blocked_reason` is `invalid_delta_schema: verify step must follow trigger; ...`

#### Scenario: One invalid case does not affect others
- **WHEN** a single case fails phase ordering validation during plugin discover
- **THEN** that case is marked BLOCKED
- **AND** all other cases in the plugin continue to load and execute normally

### Requirement: `delta_nonzero` operator SHALL pass when `verify - baseline > 0`

The `delta_nonzero` operator SHALL evaluate `verify_value - baseline_value > 0` (strict greater-than). Equality and negative deltas MUST be treated as failure. Both endpoints MUST be resolvable to numeric values; non-numeric endpoints MUST fail with `reason_code="delta_value_not_numeric"`.

#### Scenario: Counter grew under trigger
- **WHEN** baseline=10, verify=42 with `operator: delta_nonzero`
- **THEN** the criterion passes

#### Scenario: Counter unchanged after trigger
- **WHEN** baseline=10, verify=10 with `operator: delta_nonzero`
- **THEN** the criterion fails with `reason_code="delta_zero"`
- **AND** the failure comment is `"fail 原因為 0，數值無變化"`

#### Scenario: Counter decreased after trigger
- **WHEN** baseline=10, verify=5 with `operator: delta_nonzero`
- **THEN** the criterion fails with `reason_code="delta_zero"`
- **AND** the failure comment is `"fail 原因為 0，數值無變化"`

#### Scenario: Baseline endpoint unresolvable
- **WHEN** the `baseline` field path resolves to nothing in the eval context
- **THEN** the criterion fails with `reason_code="delta_value_not_numeric"`
- **AND** the failure comment is `"fail 原因為 delta 端點非數值"`

#### Scenario: Verify endpoint not numeric
- **WHEN** verify resolves to `"N/A"` or non-numeric text
- **THEN** the criterion fails with `reason_code="delta_value_not_numeric"`

### Requirement: `delta_match` operator SHALL require both deltas to grow and to agree within tolerance

The `delta_match` operator SHALL compute `delta_a = verify_a - baseline_a` and `delta_b = verify_b - baseline_b`. Both deltas MUST be strictly greater than zero; otherwise the criterion MUST fail with `reason_code="delta_zero_side"` and the comment `"fail 原因為 0，數值無變化"`. When both are positive, the operator SHALL pass when `|delta_a - delta_b| / max(|delta_a|, |delta_b|) <= tolerance_pct / 100`. The tolerance boundary MUST be inclusive (`<=`).

#### Scenario: Both sides agree within tolerance
- **WHEN** api delta=100, drv delta=109, `tolerance_pct: 10`
- **THEN** the criterion passes

#### Scenario: Both sides agree exactly
- **WHEN** api delta=100, drv delta=100
- **THEN** the criterion passes

#### Scenario: Boundary case at tolerance edge
- **WHEN** api delta=100, drv delta=110, `tolerance_pct: 10`
- **THEN** the criterion passes (boundary is inclusive)

#### Scenario: Difference exceeds tolerance
- **WHEN** api delta=100, drv delta=120, `tolerance_pct: 10`
- **THEN** the criterion fails with `reason_code="delta_mismatch"`
- **AND** the failure comment is `"fail 原因為 delta 不一致：api=100 drv=120 tol=10%"`

#### Scenario: One side did not grow
- **WHEN** api delta=100, drv delta=0
- **THEN** the criterion fails with `reason_code="delta_zero_side"`
- **AND** the failure comment is `"fail 原因為 0，數值無變化"`

#### Scenario: Both sides did not grow
- **WHEN** api delta=0, drv delta=0
- **THEN** the criterion fails with `reason_code="delta_zero_side"`

#### Scenario: Negative delta on either side
- **WHEN** either delta is negative (counter regression)
- **THEN** the criterion fails with `reason_code="delta_zero_side"`

### Requirement: Evaluate dispatch SHALL route criteria by presence of `delta` key

`Plugin.evaluate()` SHALL inspect each `pass_criteria` entry and route it to the new delta evaluator when the entry contains a `delta:` key, and otherwise route it to the existing field-based evaluator. The dispatch MUST NOT introduce any change to the behavior of `field+value` or `field+reference` criteria.

#### Scenario: Existing field+value criterion runs unchanged
- **WHEN** a criterion has `field`, `operator`, `value` and no `delta:` key
- **THEN** it is evaluated by the existing path
- **AND** failure produces the existing `reason_code="pass_criteria_not_satisfied"`

#### Scenario: Delta criterion goes to new dispatch
- **WHEN** a criterion has a `delta:` key with `baseline` and `verify`
- **THEN** it is evaluated by `_evaluate_delta_criterion`
- **AND** the existing `_compare()` is not invoked for this criterion

#### Scenario: Mixed criteria evaluate sequentially
- **WHEN** a case has both field-based and delta-based criteria
- **THEN** they are evaluated in declared order
- **AND** evaluation halts on the first failing criterion (existing semantics)

### Requirement: Failure comment string SHALL be a plugin-level constant, not yaml-overridable

The "delta 為零" failure comment SHALL be defined as a module-level constant `ZERO_DELTA_COMMENT = "fail 原因為 0，數值無變化"` in `plugins/wifi_llapi/plugin.py`. Case yaml entries MUST NOT be able to override this string. The `delta_match` mismatch comment SHALL follow a fixed template `"fail 原因為 delta 不一致：api={a} drv={b} tol={t}%"`.

#### Scenario: All delta_nonzero zero-delta failures share the same comment
- **WHEN** any `delta_nonzero` criterion fails because `verify - baseline <= 0`
- **THEN** the comment recorded on the case is exactly `"fail 原因為 0，數值無變化"`

#### Scenario: Case yaml cannot inject custom comment for zero delta
- **WHEN** a case yaml adds an `on_zero_comment:` or similar field on a delta criterion
- **THEN** the runtime ignores it and writes the constant comment

### Requirement: Reporter SHALL add a Comment column (M) and write evaluate-failure comments to it

`wifi_llapi_excel.py` SHALL extend the report template to include column M with header `"Comment"`. `fill_case_results()` SHALL write each `WifiLlapiCaseResult.comment` (truncated to 200 characters with `"..."` suffix when longer) to column M. `DEFAULT_TEMPLATE_MAX_COLUMN` MUST become `"M"` and `DEFAULT_CLEAR_COLUMNS` MUST include `"M"`. Existing G–L column behavior MUST NOT change.

#### Scenario: Template header includes Comment in column M
- **WHEN** `_normalize_template_headers()` runs on the template sheet
- **THEN** row 3 column 13 contains the value `"Comment"`

#### Scenario: Case result writes comment to M column
- **WHEN** `fill_case_results()` is called with a `WifiLlapiCaseResult` whose `comment` is `"fail 原因為 0，數值無變化"`
- **THEN** the corresponding row's column M contains exactly that string

#### Scenario: Empty comment leaves M column blank
- **WHEN** the case passed and `comment` is the empty string
- **THEN** column M is empty (not the literal `"None"`)

#### Scenario: Long comment is truncated
- **WHEN** the comment exceeds 200 characters
- **THEN** column M contains the first 200 characters followed by `"..."`

#### Scenario: G through L columns are unchanged
- **WHEN** an existing case (no delta criteria, plain PASS) is written
- **THEN** column G still holds the executed test command
- **AND** column H still holds the command output
- **AND** columns I/J/K still hold per-band verdicts
- **AND** column L still holds the tester name

### Requirement: BLOCKED and SKIP markers SHALL continue to write column H and MUST NOT write column M

`fill_blocked_markers()` and `fill_skip_markers()` MUST keep their existing behavior of writing to column H. They MUST NOT write to column M. Column M is reserved for evaluate-phase failure comments only, since BLOCKED / SKIP represent "not tested / needs retest" — a different semantic level than evaluate failures.

#### Scenario: BLOCKED case fills H column only
- **WHEN** `fill_blocked_markers()` writes a BLOCKED result for a case
- **THEN** column H contains `"BLOCKED: <reason>"`
- **AND** column M for that row is empty

#### Scenario: SKIP case fills H column only
- **WHEN** `fill_skip_markers()` writes a SKIP result for a case
- **THEN** column H contains `"SKIP: duplicate with D<row>"`
- **AND** column M for that row is empty

### Requirement: Five new reason_codes SHALL be reserved for delta evaluation paths

The following `reason_code` values SHALL be used by the delta evaluation path and MUST NOT be repurposed elsewhere:

| reason_code | Triggered by |
|---|---|
| `invalid_delta_schema` | Phase ordering validation failure (BLOCKED path) |
| `delta_value_not_numeric` | Either endpoint cannot resolve to a number |
| `delta_zero` | `delta_nonzero` failure (`verify - baseline <= 0`) |
| `delta_zero_side` | `delta_match` failure where either side did not grow |
| `delta_mismatch` | `delta_match` failure where both sides grew but differ beyond tolerance |

Existing `reason_code="pass_criteria_not_satisfied"` MUST NOT be replaced or removed by this change; its refinement is tracked separately by issue #39.

#### Scenario: invalid_delta_schema is reserved for phase ordering
- **WHEN** a case is BLOCKED due to phase ordering violation
- **THEN** `blocked_reason` begins with `"invalid_delta_schema:"`
- **AND** the reason_code is not used by any other failure path

#### Scenario: Existing pass_criteria_not_satisfied is preserved
- **WHEN** a `field+value` criterion fails (not a delta criterion)
- **THEN** the recorded `reason_code` is still `"pass_criteria_not_satisfied"`
