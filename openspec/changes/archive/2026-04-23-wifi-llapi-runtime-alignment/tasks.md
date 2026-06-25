## 1. Parser Guardrails

- [x] 1.1 Add targeted regression tests for structured display-name parsing in `plugins/wifi_llapi/tests/test_wifi_llapi_align.py`
- [x] 1.2 Update `_extract_name_api()` in `src/testpilot/reporting/wifi_llapi_align.py` to extract structured method/property tokens safely
- [x] 1.3 Re-run the targeted alignment tests and confirm the trailing-punctuation bypass is gone

## 2. Ambiguous Family Blocking

- [x] 2.1 Change `TemplateIndex` and `align_case()` to preserve one-to-many `(source.object, source.api)` families
- [x] 2.2 Introduce `ambiguous_object_api_family` reporting and candidate-template-row metadata
- [x] 2.3 Update orchestrator integration tests so ambiguous getter families are blocked instead of collision-skipped

## 3. Runtime Reporting and Docs

- [x] 3.1 Extend blocked artifact and `alignment_summary` coverage for the new blocked reason
- [x] 3.2 Document the guarded runtime behavior in `CHANGELOG.md`, `README.md`, and `AGENTS.md`
- [x] 3.3 Run the focused alignment/orchestrator test set and capture the existing unrelated baseline failure separately
