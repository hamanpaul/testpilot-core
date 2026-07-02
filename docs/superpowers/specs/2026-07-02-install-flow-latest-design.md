# Install Flow: Flow-Latest-Compatible for core / plugins (serialwrap stays pinned)

- Date: 2026-07-02
- Status: Draft (design approved, pre-implementation)
- Scope: `testpilot-core` install flow only
- Related: [`2026-06-27-install-flow-dual-entry-design.md`](2026-06-27-install-flow-dual-entry-design.md), [`2026-06-18-versioned-plugin-contract-design.md`](2026-06-18-versioned-plugin-contract-design.md)
- Rev 2 (2026-07-02): incorporate Codex adversarial review — (1) shared post-install
  verify gate across **both** online and offline paths (online currently has none);
  (2) resolution is latest-*compatible* + transactional, never mutating the managed
  venv into a broken state; (3) **serialwrap stays pinned** (no API contract to gate on).
- Rev 3 (2026-07-02): second Codex adversarial pass — as-built hardening:
  - install.sh is transactional: core's `API_VERSION` is read from the **downloaded
    core wheel** (via `zipfile`, no install), the full plugin plan is resolved
    **before** any managed-venv mutation, and a post-mutation failure rolls an
    existing install back from a `pip freeze` snapshot (or removes a fresh venv).
  - build-bundle.sh gains a **build-time API-compat gate**: after the offline
    dry-run install it loads the resolved plugin wheels against the resolved core
    (`_check_api_compat`) and fails the build on incompatibility.
  - No-metadata resolution: when no plugin release publishes `api-version.txt`
    yet (current state, pre metadata rollout), `_resolve_compatible_plugin` falls
    back to *latest* rather than a per-candidate wheel probe. This is safe in the
    default all-latest flow because core also flows latest, and a repo's latest
    core + latest plugin are released compatibly by construction; a mismatch only
    arises when core is explicitly pinned to an older version while plugins flow
    latest, which the post-install/gate + explicit `--plugins name@ver` cover. The
    per-candidate throwaway-venv probe (select the newest *compatible* release
    when metadata is absent) is the tracked robustness follow-up that lands with,
    or ahead of, the plugin `api-version.txt` metadata rollout.
  - Known limitation (pre-existing, tracked follow-up): offline rollback replays a
    `pip freeze` snapshot against the local wheel cache, which holds first-party
    release wheels but not necessarily every transitive dependency wheel; if a
    failed update changed a dependency version the offline rollback may be
    incomplete and surfaces a clear manual-recovery message. Not introduced by
    this change.

## Problem

The one-click install path pins every component to an exact release version in
`install-manifest.yaml`:

```yaml
core:       { distribution: testpilot-core, version: "0.3.2" }
plugins:
  - { name: wifi_llapi,       version: "0.3.1", api_version: "1.1" }
  - { name: brcm_fw_upgrade,  version: "0.1.0", api_version: "1.1" }
serialwrap: { version: "0.2.1" }
```

Every time a plugin cuts a patch release, `core` must open a re-pin PR **and cut
its own release** just to advance the pin — e.g. `core v0.3.2` was purely a
re-pin of `serialwrap 0.2.0 → 0.2.1`. This couples `core`'s release cadence to
unrelated downstream bumps even when nothing in `core` changed and the SDK API
contract is unchanged.

The intent: **as long as the SDK API version is compatible, `core` should
support the latest plugin without a re-pin release.**

## Current architecture (what actually binds versions today)

Three independent mechanisms — only one binds release versions:

1. **Runtime plugin load — already API-based, no release-version binding.**
   `src/testpilot/core/plugin_loader.py:_check_api_compat` (L36) enforces
   `plugin.major == core.major and core.minor >= plugin.minor` against
   `testpilot.api.API_VERSION` (`= "1.1"`, `src/testpilot/api/__init__.py:58`).
   The plugin's release version (0.3.1 …) is never consulted at load time.
   Consequence: raising core's **minor** never breaks existing plugins
   (`core.minor >= plugin.minor` still holds); only a plugin that declares a
   **higher minor than core provides**, or a **major** mismatch, is incompatible.

2. **serialwrap is not a pip dependency.** `pyproject.toml` deps are only
   `pyyaml / click / rich / openpyxl / ruamel.yaml`. `core` invokes serialwrap
   as an external binary via `resolve_serialwrap_binary`
   (`src/testpilot/serialwrap_binary.py`), so runtime never version-checks it —
   **and there is no API/protocol contract to gate a serialwrap upgrade on.**

3. **`install-manifest.yaml` exact-pin — install-time only.** Consumed by:
   - `scripts/install.sh`. **The post-install verify gate
     (`testpilot --verify-install || fail`, L227-231) runs ONLY inside the
     offline branch** (`if [[ -n "$OFFLINE_BUNDLE" ]]`, L143). The **online
     branch** (`else`, L235 → `fi`, L484) installs core → plugins → serialwrap
     via `gh release download "v${version}"` (L411) and prints success with **no
     verification step**. This is the safety-net gap Rev 2 fixes.
   - `scripts/build-bundle.sh` (offline bundle build): same
     `gh release download "v${version}"` (L183) to stage a wheelhouse +
     `SHA256SUMS` tarball.
   - `testpilot install-doctor` (`src/testpilot/cli.py:1327`, CI
     `.github/workflows/ci.yml:80`): reads only the manifest's `api_version`
     fields against core `API_VERSION` — does **not** read release `version`.

**Conclusion:** runtime is already API-gated. What forces re-pin releases is the
exact `version:` in the manifest; and the online install path has no post-install
verification at all.

## Goals

- Online install resolves **core and all plugins** to each repo's **newest
  release that is API-compatible with the installed core**, instead of a manifest
  pin. `core` releases only for its own code changes.
- **serialwrap stays pinned** in the manifest (no API/protocol contract exists to
  make latest safe; flow-latest for it is explicitly rejected).
- The managed venv is **never left in a broken state**: compatibility is checked
  before/without committing, and any failure rewinds to the previous good state.
- Preserve the escape hatch: an explicit pin (`--plugins name@ver`, or an
  optional `version:` left in the manifest) still works.
- Preserve offline reproducibility: the offline bundle remains an exact,
  SHA256-verified snapshot.
- A single post-install verify gate runs on **both** online and offline paths.

## Non-goals

- **serialwrap flow-latest.** Rejected; serialwrap remains manifest-pinned until
  it has an explicit compatibility contract (version range / protocol handshake /
  functional probe). Out of scope here.
- Changing runtime `_check_api_compat` semantics.
- Making serialwrap a pip dependency.
- Signing / platform-matrix / prerelease-channel work.

## Design

### 1. Manifest: repo registry + API contract; serialwrap still pinned

`install-manifest.yaml`: drop the checked-in `version:` pins **for core and
plugins only**. Keep `repo` (required), plugin `api_version` (the minimum
contract core requires; still read by `install-doctor`), and **serialwrap
`version:` (required, pinned)**.

```yaml
core:
  distribution: testpilot-core
  repo: hamanpaul/testpilot-core
  private: true
plugins:
  - { name: wifi_llapi,      repo: hamanpaul/wifi_llapi,      api_version: "1.1", private: true }
  - { name: brcm_fw_upgrade, repo: hamanpaul/brcm_fw_upgrade, api_version: "1.1", private: true }
serialwrap:
  repo: hamanpaul/serialwrap
  version: "0.2.1"          # PINNED — no API contract; bump deliberately
  private: false
```

`src/testpilot/install/manifest.py`: `version` becomes optional on `Core` and
`Plugin` (`str | None = None`) but stays **required** on `Serialwrap`.
`load_manifest` tolerates a missing `version:` on core/plugins; raises if
serialwrap has no `version:`. `InstallManifest.selected` keeps honoring
`name@ver` overrides (supplied version pins; otherwise `None` = resolve latest).

### 2. Latest-*compatible* transactional resolution (core + plugins)

Three properties every resolution must satisfy (directly from the adversarial
review):

- **P1 — compatibility is part of selection.** Pick the newest release whose
  declared `api_version` is compatible with the **installed core's**
  `API_VERSION` (via `_check_api_compat`), not merely the newest release.
- **P2 — no broken mutation.** The plugin's `api_version` is determined
  **before** the release is committed to the managed venv (staging / metadata
  probe). A candidate is only installed into the managed venv once it is known
  compatible.
- **P3 — loud abort, preserve prior good state.** If no compatible release exists
  for a required component, the installer aborts with a clear message (naming the
  component, its candidate api_versions, and core's provided version) and leaves
  any pre-existing working install untouched — `--update` must never brick a
  working install.

**Online flow (`scripts/install.sh`):**

1. Resolve + install **core** = latest core release (core is the API provider;
   self-consistent). Read the installed contract:
   `"${VENV}/bin/python" -c 'import testpilot.api as a; print(a.API_VERSION)'`.
2. For each **plugin** (respecting `--plugins` filter / `name@ver` pin):
   - Enumerate releases newest→oldest (`gh release list --repo R`).
   - Determine each candidate's `api_version` **without mutating the managed
     venv** (see mechanism below); pick the newest compatible with core (P1, P2).
   - Install only the winner (`--no-deps`), cache its wheel to `WHEEL_CACHE`.
   - No compatible candidate → P3 abort.
3. **serialwrap**: install the manifest-pinned `version` (existing download path,
   unchanged).
4. Run the **shared post-install gate** (below).

**Mechanism for reading a candidate's api_version pre-commit** (recommended for
writing-plans, exact impl deferred):

- *Primary:* plugin releases publish `api_version` as machine-readable release
  metadata — a wheel metadata field and/or a small `<plugin>-api.json` release
  asset — so the installer resolves newest-compatible by reading metadata and
  downloads only the winner. (Cross-repo: adds one line to each plugin's release
  workflow; tracked as a rollout dependency.)
- *Fallback when metadata is absent:* transactional probe — download the
  candidate wheel, install into a throwaway probe venv that already has core, run
  `_check_api_compat` / `install-doctor`, and only then install the winner into
  the managed venv; rewind to the previous candidate on failure.

### 3. Shared post-install verify gate (fix for the online gap)

Factor the offline branch's gate (`install.sh:227-231`) into a helper invoked at
the end of **both** branches:

```sh
_post_install_gate() {
    info "Running post-install gate: testpilot --verify-install ..."
    "${VENV}/bin/testpilot" --verify-install \
        || fail "Post-install gate FAILED. The installation may be incomplete."
    ok "Post-install gate passed"
}
```

`--verify-install` (wheel mode, `src/testpilot/cli.py:_verify_install_wheel_mode`
/ `_handle_verify_install`) must surface an `IncompatiblePluginError` from
`plugin_loader.load` as a clear, actionable **FAIL** (naming the plugin, its
requested API version, and core's provided version) — never a crash, never a
silent skip. Existing handling keyed on `error == "IncompatiblePluginError"`
(cli.py:426) is confirmed/hardened. This gate is the backstop; resolution (§2)
is the primary defense so the gate should essentially never trip in practice.

### 4. `scripts/build-bundle.sh` — offline path

- Same latest-*compatible* resolution for **core + plugins** at **build time**;
  **serialwrap uses the pinned manifest version**.
- The bundle still stages concrete wheels + `SHA256SUMS`, so the offline tarball
  remains an exact snapshot: **offline reproducibility is unchanged.**
- Write a `resolved-manifest.yaml` into the bundle recording the exact versions
  the snapshot was built from (provenance / reproducible pin set).

### 5. Untouched / minor

- **`install-doctor` CI gate** (`ci.yml:80`): reads only `api_version`; keeps
  working unchanged as the declared-contract check.
- **`testpilot --update`**: becomes "reinstall newest **compatible**" (re-runs
  §2 resolution). Must obey P3 — a failed resolve leaves the working install
  intact and reports why, rather than half-upgrading. Rollback via `WHEEL_CACHE`
  (`--no-index`) must still function.

### 6. Tests

- `tests/test_install_manifest.py`: `version` optional on core/plugin, required
  on serialwrap; missing-version loads; `name@ver` override still pins.
- **Online verify gate**: installer test proving the **online** path invokes
  `testpilot --verify-install` and exits nonzero when a plugin is
  API-incompatible (guards the Rev 2 critical finding).
- **Compatible resolution**: newest-compatible is selected over a newer-but-
  incompatible release; rewind to previous compatible; **no compatible release →
  abort without mutating** an existing good install (P1/P2/P3), mocking
  `gh release list` / metadata.
- **serialwrap stays pinned**: resolution never flows serialwrap to latest;
  manifest pin is honored.
- `tests/test_installer.py`, `test_update_reconcile.py`,
  `test_update_installer_seam.py`, `test_predispatch.py`,
  `test_wheel_contents.py`: drop exact-version assertions; cover resolution path.
- `tests/test_install_compat.py`: unaffected (api_version only).
- `tests/test_release_governance.py` / `test_version_metadata.py`: core's own
  version mirrors — unaffected unless they assert manifest `core.version`.

### 7. Docs

- `README.md` install section: online = latest-compatible, offline = pinned
  snapshot, serialwrap pinned.
- `docs/release-flow.md`: **remove the "re-pin manifest" step for core/plugins**;
  keep a deliberate serialwrap-pin bump step; state core releases only for its
  own changes.
- `CHANGELOG.md [Unreleased]`: entry for the flow-latest-compatible change.

## Reproducibility model (explicit)

| Path | core / plugins | serialwrap | Reproducible? |
|------|----------------|------------|---------------|
| Online one-click | newest compatible, resolved at install time | pinned (manifest) | No for core/plugins (by intent); serialwrap yes |
| Explicit pin (`--plugins name@ver` / manifest `version:`) | pinned | pinned | Yes |
| Offline bundle | snapshot of newest-compatible at **build** time + `SHA256SUMS` + `resolved-manifest.yaml` | pinned | Yes |

## Release-process impact (the payoff)

`core` no longer opens a re-pin PR + release when `wifi_llapi` / `brcm_fw_upgrade`
bump. Those release independently; the next online install / `--update` / bundle
build picks up the newest **compatible** release automatically. serialwrap bumps
remain a deliberate manifest edit (rare, gated by the missing contract).

## Risks & mitigations

- **A plugin release outruns core's API** (declares a higher minor / new major).
  → §2 resolution skips it and installs the newest compatible release (P1);
  never bricks the install (P2/P3); the §3 gate is the backstop. This is the core
  fix for the adversarial "global outage" finding.
- **Primary metadata mechanism needs downstream buy-in.** Until every plugin
  publishes per-release api metadata, the transactional-probe fallback (§2)
  applies — self-contained but pays a download+probe per rewind step. Tracked as
  a rollout dependency, not a blocker.
- **serialwrap latest could break live tests** — avoided: serialwrap stays
  pinned. Revisiting it requires a real contract (own future spec).
- **Non-determinism between two online installs** (core/plugins). Accepted for
  the online path; offline bundle + explicit pin cover reproducible use cases.
- **`gh release list/view` requires auth / a published release.** No-release path
  fails loudly; token handling unchanged from the existing download flow.

## Rollout

1. Manifest schema + `manifest.py` optional-version (core/plugin) / required
   serialwrap.
2. `install.sh`: shared post-install gate (§3) + latest-compatible resolution
   (§2); `build-bundle.sh` build-time resolution; serialwrap pinned throughout.
3. (Cross-repo, parallel) plugin release workflows publish per-release api
   metadata to enable the primary resolution mechanism.
4. Tests + docs + CHANGELOG.
5. Single PR on `feature/install-flow-latest` (zh-tw, policy-governed repo).
