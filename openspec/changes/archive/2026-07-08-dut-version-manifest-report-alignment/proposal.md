## Why

testpilot-core currently treats the firmware hook as a naming-only string source and generic reporters do not surface the richer DUT environment context operators need when triaging wifi_llapi runs. We need the core loop and generic report projectors to carry a full version manifest so plugin-specific report logic can rely on a stable runtime contract and human-readable reports show the captured environment directly.

## What Changes

- Update the core run loop to capture the plugin's DUT version manifest once at run start, store it in run metadata, and keep CLI firmware overrides limited to naming resolution.
- Render a collapsed Environment / Versions block at the top of HTML and Markdown reports when a version manifest is present.
- Add tests that lock the run-loop metadata contract and the new report projection behavior.

## Capabilities

### New Capabilities
- `dut-version-manifest-reporting`: Propagate a plugin-provided DUT version manifest through the core run loop and generic report outputs.

### Modified Capabilities

## Impact

- `src/testpilot/core/run_loop.py`
- `src/testpilot/reporting/html_reporter.py`
- `src/testpilot/reporting/reporter.py`
- `tests/test_run_loop*.py`
- `tests/test_html_reporter.py`
- `tests/test_reporter.py`
- `CHANGELOG.md` and directly related docs/OpenSpec artifacts
