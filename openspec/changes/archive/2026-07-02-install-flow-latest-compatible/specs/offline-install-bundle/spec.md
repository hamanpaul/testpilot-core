## MODIFIED Requirements

### Requirement: Build a portable offline install bundle on a networked Linux box
`scripts/build-bundle.sh` SHALL, on a networked Linux box matching the target's architecture and Python minor version, assemble a single portable bundle: it SHALL resolve and download the **newest API-compatible** `testpilot-core` and plugin wheels and the **manifest-pinned** `serialwrap` wheel from their releases (never rebuild them), `pip download` the full third-party dependency closure for the same platform, and emit a `wheelhouse/` plus a pinned `requirements.txt` enumerating the entire closure at exact versions, plus the packaged `testpilot-normal-test` skill and `testbed.yaml.example`. It SHALL record a `resolved-manifest.yaml` inside the bundle capturing the exact core/plugin/serialwrap versions the snapshot was built from (provenance and reproducible pin set). It SHALL hard-exclude operator-local secrets and artifacts (`configs/testbed.yaml`, root `*.xlsx`, `compare-*`). Before producing the tarball it SHALL run a build-box dry-run install (`pip install --no-index --find-links=wheelhouse -r requirements.txt` into a throwaway venv) and fail the build if the closure does not resolve. The output SHALL be a `.tar.gz` whose name encodes platform + Python minor (e.g. `testpilot-bundle-<ver>-linux-x86_64-cp311.tar.gz`) accompanied by a detached `SHA256SUMS`. The resulting bundle remains an exact snapshot: an offline install from it is fully reproducible regardless of later upstream releases.

#### Scenario: Bundle build produces a resolvable, self-contained wheelhouse
- **WHEN** `build-bundle.sh` runs on a Linux box matching the target arch + Python minor with valid release access
- **THEN** it emits a `.tar.gz` containing `wheelhouse/` (newest-compatible core + plugins, the pinned serialwrap, and all third-party wheels), a pinned `requirements.txt`, a `resolved-manifest.yaml`, the skill, and `testbed.yaml.example`, plus a sidecar `SHA256SUMS`

#### Scenario: Resolved snapshot is recorded for provenance
- **WHEN** the bundle is built with latest-compatible resolution for core/plugins
- **THEN** the bundle contains a `resolved-manifest.yaml` listing the exact core, plugin, and serialwrap versions it was built from

#### Scenario: Unresolvable closure fails the build
- **WHEN** the build-box dry-run `pip install --no-index --find-links=wheelhouse -r requirements.txt` cannot satisfy the closure
- **THEN** `build-bundle.sh` exits non-zero and does not produce a tarball

#### Scenario: Live operator secrets are excluded
- **WHEN** the build directory contains an effective `configs/testbed.yaml` and root `*.xlsx` artifacts
- **THEN** the produced bundle contains only `testbed.yaml.example` and none of the excluded live/local files
