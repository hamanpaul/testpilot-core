## MODIFIED Requirements

### Requirement: Runtime alignment MUST block unresolved ambiguous template families
The runtime alignment phase MUST NOT auto-align or mutate YAML when the template contains more than one row for the same `(source.object, source.api)` pair unless the case's `source.row` resolves that family to a single canonical row. It MUST classify only unresolved collisions as blocked with reason `ambiguous_object_api_family`.

#### Scenario: Duplicate getter family is resolved by source row
- **WHEN** the template contains multiple rows for `("WiFi.SSID.{i}.", "getSSIDStats()")`
- **AND** a case with that same `(source.object, source.api)` pair has `source.row` equal to one of those candidate rows
- **THEN** runtime alignment selects that row as the canonical target
- **AND** the case is not blocked only because the object-api family has multiple rows

#### Scenario: Duplicate getter family remains unresolved
- **WHEN** the template contains multiple rows for `("WiFi.SSID.{i}.", "getSSIDStats()")`
- **AND** a case with that same `(source.object, source.api)` pair has no `source.row` match in that candidate family
- **THEN** the case is classified as `blocked`
- **AND** no filename, `source.row`, or `id` mutation is applied

#### Scenario: Unique object-api pair still auto-aligns
- **WHEN** the template contains exactly one row for a case's `(source.object, source.api)` pair
- **THEN** runtime alignment keeps the existing `already_aligned` or `auto_aligned` behavior
- **AND** collision resolution only applies after the case is proven to reference a unique template row
