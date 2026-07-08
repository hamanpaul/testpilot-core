## 1. Run-loop metadata propagation

- [ ] 1.1 Update the core run loop to capture the plugin version manifest unconditionally, preserve CLI naming precedence, and store the manifest in run metadata.
- [ ] 1.2 Add focused pytest coverage for the manifest metadata contract and naming fallback behavior.

## 2. Generic report rendering

- [ ] 2.1 Render a collapsed Environment / Versions block at the top of HTML and Markdown reports when `version_manifest` metadata is present.
- [ ] 2.2 Add reporter tests that verify the collapsed section content and the no-op behavior when the manifest is absent.

## 3. Delivery and verification

- [ ] 3.1 Sync the repo changelog/OpenSpec/docs impacted by the new reporting contract.
- [ ] 3.2 Run the targeted and full repo verification needed for the cross-repo landing.
