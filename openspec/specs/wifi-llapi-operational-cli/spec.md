# wifi-llapi-operational-cli Specification

## Purpose
Define the primary operator-facing wifi_llapi command contract while preserving compatibility with the generic plugin run command.

## Requirements
### Requirement: Primary wifi_llapi command shares normal run behavior
`testpilot wifi_llapi` SHALL be the primary documented normal-run command for the wifi_llapi plugin. It SHALL use the same execution path as `testpilot run wifi_llapi`, accept the same normal-run flags including `--case` and `--dut-fw-ver`, and produce equivalent runtime artifacts and reports.

#### Scenario: Primary command runs selected case
- **WHEN** user runs `testpilot wifi_llapi --case wifi-llapi-D004-kickstation --dut-fw-ver BGW720-B0-403`
- **THEN** TestPilot executes the wifi_llapi plugin through the same run helper used by `testpilot run wifi_llapi` with the selected case and DUT firmware version

#### Scenario: Compatibility command remains valid
- **WHEN** user runs `testpilot run wifi_llapi --dut-fw-ver BGW720-B0-403`
- **THEN** TestPilot continues to execute the wifi_llapi plugin successfully

### Requirement: wifi_llapi help shows fixed operational format
`testpilot wifi_llapi --help` SHALL clearly show the fixed user-facing format `testpilot wifi_llapi [--case CASE_ID] [--dut-fw-ver FW_VER]` and SHALL not present editable-install or `python -m testpilot.cli` forms as the primary path.

#### Scenario: Help displays operational usage
- **WHEN** user runs `testpilot wifi_llapi --help`
- **THEN** the help output contains `testpilot wifi_llapi [--case CASE_ID] [--dut-fw-ver FW_VER]`

### Requirement: README and skill prefer installed command
README documentation and `skills/testpilot-normal-test/SKILL.md` SHALL prefer `testpilot wifi_llapi` and `testpilot wifi_llapi --case <CASE_ID>` for QC/TEST operation. Compatibility notes MAY mention `testpilot run wifi_llapi` for existing developer scripts, but they SHALL NOT present `uv run python -m testpilot.cli run wifi_llapi` as the preferred normal-run path.

#### Scenario: Skill shows primary command
- **WHEN** a user reads `skills/testpilot-normal-test/SKILL.md`
- **THEN** the normal test command examples use `testpilot wifi_llapi` and `testpilot wifi_llapi --case <CASE_ID>`

#### Scenario: README help markers include wifi_llapi command
- **WHEN** policy help sync checks README
- **THEN** README contains a `testpilot-wifi-llapi-help` marker block reflecting `testpilot wifi_llapi --help`
