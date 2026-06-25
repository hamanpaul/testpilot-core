## Requirements

### Requirement: Runtime alignment SHALL extract comparison tokens from structured display names
The runtime alignment parser SHALL derive the comparison token from structured wifi_llapi case names without relying on the final period-delimited segment. Method tokens such as `getSSIDStats()` MUST still be recognized when they appear before trailing object paths or punctuation.

#### Scenario: Method token remains visible in a structured name
- **WHEN** a case name is `FailedRetransCount - WiFi.SSID.{i}.getSSIDStats().`
- **THEN** the extracted comparison token is `getSSIDStats()`
- **AND** runtime alignment does not treat the case as having an empty name API

#### Scenario: Property token is extracted from the display prefix
- **WHEN** a case name is `AssociationTime - WiFi.AccessPoint.{i}.AssociatedDevice.{i}.`
- **THEN** the extracted comparison token is `AssociationTime`
- **AND** the parser ignores the trailing object path for validation purposes

### Requirement: Runtime alignment MUST block ambiguous template families
The runtime alignment phase MUST NOT auto-align or mutate YAML when the template contains more than one row for the same `(source.object, source.api)` pair. It MUST classify those cases as blocked with reason `ambiguous_object_api_family`.

#### Scenario: Duplicate getter family is encountered
- **WHEN** the template contains multiple rows for `("WiFi.SSID.{i}.", "getSSIDStats()")`
- **THEN** a case with that same `(source.object, source.api)` pair is classified as `blocked`
- **AND** no filename, `source.row`, or `id` mutation is applied

#### Scenario: Unique object-api pair still auto-aligns
- **WHEN** the template contains exactly one row for a case's `(source.object, source.api)` pair
- **THEN** runtime alignment keeps the existing `already_aligned` or `auto_aligned` behavior
- **AND** collision resolution only applies after the case is proven to reference a unique template row

### Requirement: Runtime artifacts MUST explain ambiguous-family blocks
When runtime alignment blocks a case because its template family is ambiguous, the emitted artifacts MUST include enough detail for a later cleanup pass to resolve the case without re-deriving the template mapping by hand.

#### Scenario: Blocked report includes candidate rows
- **WHEN** a case is classified as `ambiguous_object_api_family`
- **THEN** `blocked_cases.md` includes the blocked reason and the candidate template rows for that family

#### Scenario: Summary JSON records the new blocked reason
- **WHEN** a run finishes with at least one ambiguous-family block
- **THEN** `alignment_summary` in the run JSON reports the blocked count
- **AND** the per-case blocked entry identifies the `ambiguous_object_api_family` reason
