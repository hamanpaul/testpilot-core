## ADDED Requirements

### Requirement: Per-band report value derives from verdict only

When producing per-band (5g / 6g / 2.4g) report values for a wifi_llapi case, the runtime SHALL compute each band's value from `(verdict, case.bands)` alone. The runtime MUST NOT read `results_reference`, `source.baseline`, `source.report`, or `source.sheet` from the case during verdict computation or report writing.

The per-band value MUST follow this rule:
- If `band` is in `case.bands`: `"Pass"` when `verdict` is true, `"Fail"` when `verdict` is false
- If `band` is NOT in `case.bands`: `"N/A"`

#### Scenario: Verdict true with all bands enumerated

- **WHEN** `verdict=true` and `case.bands = ["5g", "6g", "2.4g"]`
- **THEN** `case_band_results(case, verdict)` returns `("Pass", "Pass", "Pass")`

#### Scenario: Verdict true with partial bands

- **WHEN** `verdict=true` and `case.bands = ["5g"]`
- **THEN** `case_band_results(case, verdict)` returns `("Pass", "N/A", "N/A")`

#### Scenario: Verdict false with multiple bands

- **WHEN** `verdict=false` and `case.bands = ["5g", "6g"]`
- **THEN** `case_band_results(case, verdict)` returns `("Fail", "Fail", "N/A")`

#### Scenario: No oracle lookup function is imported

- **WHEN** code imports `from testpilot.core.case_utils import baseline_results_reference`
- **THEN** the import raises `ImportError` (the function MUST NOT exist)

### Requirement: Schema rejects oracle metadata fields for wifi_llapi cases

The wifi_llapi case validator SHALL reject any case that contains one or more of the following oracle metadata fields: top-level `results_reference`, or nested `source.baseline`, `source.report`, `source.sheet`. Rejection MUST raise `CaseValidationError` with a message containing the literal substring `#31 cleanup` and the list of offending field names.

#### Scenario: Top-level results_reference is rejected

- **WHEN** `validate_wifi_llapi_case(case, source=path)` is called on a case containing a top-level `results_reference` key
- **THEN** it raises `CaseValidationError`
- **AND** the error message contains `#31 cleanup` and mentions `results_reference`

#### Scenario: source.baseline is rejected

- **WHEN** `validate_wifi_llapi_case(case, source=path)` is called on a case whose `source` dict contains a `baseline` key
- **THEN** it raises `CaseValidationError`
- **AND** the error message contains `#31 cleanup` and mentions `baseline`

#### Scenario: source.report and source.sheet are rejected

- **WHEN** `validate_wifi_llapi_case(case, source=path)` is called on a case whose `source` dict contains `report` or `sheet` keys
- **THEN** it raises `CaseValidationError` mentioning the offending key(s)

#### Scenario: Clean case passes validation

- **WHEN** `validate_wifi_llapi_case(case, source=path)` is called on a case that passes generic validation and contains none of the forbidden oracle fields
- **THEN** no exception is raised

#### Scenario: wifi_llapi plugin uses the oracle-aware validator

- **WHEN** `plugins/wifi_llapi/plugin.py` loads a case (via `discover_cases` or its case-load path)
- **THEN** it calls `validate_wifi_llapi_case(...)` rather than the generic `validate_case(...)` alone

### Requirement: Migration script removes oracle metadata safely and idempotently

The migration utility at `scripts/wifi_llapi_strip_oracle_metadata.py` SHALL support both dry-run (default) and `--apply` modes, preserve YAML formatting (comments, key order, quoting) via `ruamel.yaml` round-trip, and be idempotent (running it a second time on already-cleaned YAML MUST NOT produce any change).

The script MUST delete, where present: top-level key `results_reference`; keys `baseline`, `report`, `sheet` within the `source` mapping. It MUST preserve all other keys in both the top level and the `source` mapping.

#### Scenario: Dry-run does not modify files

- **WHEN** the script runs without `--apply` on a YAML that contains `results_reference` and `source.baseline`
- **THEN** the file on disk is unchanged
- **AND** stdout lists the file with the fields that would be removed

#### Scenario: Apply removes all four oracle fields

- **WHEN** the script runs with `--apply` on a YAML containing `results_reference`, `source.baseline`, `source.report`, and `source.sheet`
- **THEN** the resulting file contains none of these four keys at their respective positions
- **AND** all other keys (e.g., `id`, `name`, `steps`, `pass_criteria`, `source.row`, `source.object`, `source.api`) remain

#### Scenario: Second apply is a no-op

- **WHEN** the script runs with `--apply` on a YAML that was already cleaned by a prior run
- **THEN** the file on disk is byte-identical to the pre-run state
- **AND** the summary reports this file as "already clean"

#### Scenario: Comments and key order are preserved

- **WHEN** the script runs with `--apply` on a YAML containing inline and standalone comments outside the deleted fields, and a specific key ordering
- **THEN** the resulting YAML preserves those comments and their ordering relative to surviving keys

#### Scenario: Source field is not a mapping

- **WHEN** the script runs with `--apply` on a YAML whose top-level `source` is `None` or a non-mapping scalar
- **THEN** the script does not attempt to remove `baseline` / `report` / `sheet` on that case (no exception)
- **AND** it still removes top-level `results_reference` if present

### Requirement: Shipped wifi_llapi cases contain no oracle metadata

After the change is applied, every YAML file under `plugins/wifi_llapi/cases/` SHALL pass `validate_wifi_llapi_case(...)` without raising `CaseValidationError`. No shipped case file may contain `results_reference`, `source.baseline`, `source.report`, or `source.sheet`.

#### Scenario: Repo-scale smoke validates all cases

- **WHEN** a test iterates every YAML under `plugins/wifi_llapi/cases/` and calls `validate_wifi_llapi_case(case, source=path)`
- **THEN** no file raises `CaseValidationError`

#### Scenario: No shipped case contains forbidden fields

- **WHEN** the test scans every YAML under `plugins/wifi_llapi/cases/` for the literal keys `results_reference`, `source.baseline`, `source.report`, `source.sheet`
- **THEN** zero occurrences are found
