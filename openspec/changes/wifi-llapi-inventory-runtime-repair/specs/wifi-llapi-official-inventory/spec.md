## ADDED Requirements

### Requirement: Official wifi_llapi inventory SHALL be workbook-authoritative
The system SHALL treat the current checked-in wifi_llapi template workbook as the only authoritative source for official discoverable case inventory. Every official workbook row MUST map to exactly one discoverable YAML in `plugins/wifi_llapi/cases/`.

#### Scenario: Workbook row has exactly one canonical discoverable YAML
- **WHEN** the inventory audit evaluates an official workbook row
- **THEN** it finds exactly one discoverable YAML whose filename row and `source.row` both match that workbook row

#### Scenario: Workbook row is missing from discoverable inventory
- **WHEN** the inventory audit evaluates an official workbook row and no canonical discoverable YAML exists for it
- **THEN** the row is reported as missing
- **AND** the row is not silently skipped or treated as covered by a different discoverable case

### Requirement: Non-canonical discoverable wifi_llapi cases MUST be classified explicitly
The inventory repair flow MUST classify discoverable `wifi_llapi` YAML that do not satisfy canonical workbook inventory as drifted, duplicate, or extra before any reconcile is applied.

#### Scenario: Discoverable case carries stale canonical metadata
- **WHEN** a discoverable YAML has a `source.row` or filename row that does not match its canonical workbook row
- **THEN** the inventory audit reports it as drifted

#### Scenario: Multiple discoverable cases claim the same workbook row
- **WHEN** more than one discoverable YAML maps to the same official workbook row
- **THEN** the inventory audit reports the row as duplicated
- **AND** the reconcile flow chooses at most one canonical discoverable case for that row

#### Scenario: Discoverable case is not part of official workbook inventory
- **WHEN** a discoverable YAML does not belong to the workbook-defined official inventory
- **THEN** the inventory audit reports it as extra

### Requirement: Inventory reconcile MUST make missing and extra rows explicit
The inventory reconcile flow MUST restore or preserve canonical discoverable coverage for each official workbook row, and it MUST demote non-canonical leftovers out of discoverable inventory instead of leaving them as silent duplicates.

#### Scenario: Missing official row is restorable from repo history
- **WHEN** an official workbook row is missing and a historical canonical YAML exists in repo history
- **THEN** the reconcile flow restores that row into discoverable inventory

#### Scenario: Extra historical YAML still has fixture value
- **WHEN** a non-canonical YAML should be kept for reference or testing
- **THEN** the reconcile flow demotes it out of discoverable inventory
- **AND** the file no longer participates in official case discovery

#### Scenario: Missing row cannot be restored automatically
- **WHEN** an official workbook row is missing and no safe restoration source exists
- **THEN** the reconcile flow reports an explicit blocker
- **AND** the row remains visible in blocker reporting until resolved
