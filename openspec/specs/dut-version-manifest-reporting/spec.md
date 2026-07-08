# dut-version-manifest-reporting Specification

## Purpose
TBD - created by archiving change dut-version-manifest-report-alignment. Update Purpose after archive.
## Requirements
### Requirement: the core run loop SHALL persist a plugin-provided DUT version manifest
The core run loop SHALL capture the plugin-provided DUT version manifest once at run start and store it in `meta["version_manifest"]` for downstream reporting. The run loop SHALL continue to honor `--dut-fw-ver` as the preferred report-naming string, but it MUST still capture and persist the manifest even when the CLI override is present.

#### Scenario: no CLI override uses manifest git for naming
- **WHEN** a plugin returns a version manifest with `git` populated and the run does not specify `--dut-fw-ver`
- **THEN** the run metadata stores the full manifest and the report firmware naming string comes from `version_manifest["git"]`

#### Scenario: CLI override still captures manifest
- **WHEN** a run specifies `--dut-fw-ver` and the plugin returns a version manifest
- **THEN** the report naming string uses the CLI value and `meta["version_manifest"]` still contains the captured manifest

### Requirement: generic reporters SHALL render a collapsed Environment / Versions section
HTML and Markdown report generators SHALL render a collapsed Environment / Versions section near the top of the report when `meta["version_manifest"]` is present and non-empty. The section SHALL list the captured manifest fields without requiring plugin-specific rendering logic, and reporters MUST leave existing output unchanged when the manifest is absent.

#### Scenario: manifest present renders collapsed section
- **WHEN** report generation receives metadata containing a non-empty `version_manifest`
- **THEN** the HTML and Markdown outputs include a collapsed Environment / Versions block before the KPI or suite-summary sections

#### Scenario: manifest absent is a no-op
- **WHEN** report generation receives metadata without `version_manifest`
- **THEN** the reporters do not emit an Environment / Versions block and continue producing the existing report structure

