# TestPilot Versioning and Release Flow

This document defines the repository-level versioning and release process for TestPilot Core. It describes the current wheel-based GitHub Release flow and the managed QC/TEST installation model.

## 1. Versioning policy

TestPilot uses Semantic Versioning with git tags in the form `vX.Y.Z`.

- **Major (`X`)**: breaking operator-facing or plugin-SDK changes.
- **Minor (`Y`)**: backward-compatible features such as new commands, SDK additions, reporting capabilities, runtime features, or supported workflows.
- **Patch (`Z`)**: backward-compatible fixes, documentation corrections, test improvements, and release automation maintenance.

The plugin SDK contract has its own `testpilot.api.API_VERSION` (`major.minor`) and is intentionally separate from the package release version. A package patch/minor release does not necessarily imply an SDK API change.

## 2. Canonical version sources

- **Canonical project version**: `VERSION`
- **Packaging version**: `pyproject.toml` uses Hatch dynamic versioning sourced from `VERSION`
- **Runtime mirror**: `src/testpilot/__init__.py` → `__version__`
- **Published identifier**: git tag `vX.Y.Z`

`VERSION`, the runtime mirror, package metadata produced from `pyproject.toml`, and the release tag must agree. Repository tests and the release workflow validate this contract.

## 3. Day-to-day pull request expectations

Normal feature/fix branches merge through GitHub pull requests.

Each PR should explicitly cover:

- whether a `changelog.d/*.md` fragment is required
- whether README / docs / AGENTS updates are required
- whether README CLI help marker blocks governed by `.project-policy.yml` need synchronization
- what validation was run
- whether the change has release-note impact

Rule of thumb:

- **User-facing or operator-facing changes**: add a changelog fragment.
- **Purely internal churn with no release-note value**: explain in the PR why a fragment is not needed.

Do not edit a future dated release section directly during ordinary development. Pending release notes live in `changelog.d/` until release preparation collates them.

## 4. Release preparation flow

Prepare releases in a dedicated branch and PR:

1. Branch from `main` as `feature/<slug>` (for example `feature/release-v0-3-8`; R-12 branch slugs allow only `[a-z0-9-]`).
2. Update `VERSION` and `src/testpilot/__init__.py` to `X.Y.Z`. `pyproject.toml` remains dynamically sourced from `VERSION`; there is no static `[project].version` field to edit.
3. Finalize `CHANGELOG.md` by collating pending fragments:

   ```bash
   python3 -m policy_check.changelog collate --version X.Y.Z --date YYYY-MM-DD
   ```

   The collator folds `changelog.d/*.md` into a dated `## [X.Y.Z]` section and clears the fragment directory. Supported fragment groups include `feat`, `fix`, `refactor`, `perf`, `change`, `remove`, `deprecate`, and `security`; `chore` is not a valid fragment type, so use `change` for maintenance entries that belong in release notes.
4. Keep a fresh empty `## [Unreleased]` section at the top of `CHANGELOG.md` for readability.
5. Update README / docs / AGENTS if supported workflows, operator guidance, SDK behavior, or release rules changed.
6. Run the repository test suite and policy/preflight checks.
7. Open the release PR with the `release:vX.Y.Z` label. Use `skip-changelog` on the release-prep PR because the pending fragments have already been moved into the dated release section.
8. Merge the release PR into `main`.

Recommended PR title:

```text
chore(release): prepare vX.Y.Z
```

## 5. Tagging and publication

After the release PR is merged:

1. Create tag `vX.Y.Z` on the merged `main` commit.
2. Push the tag.
3. `.github/workflows/release.yml` runs the project policy gate and release validation.
4. The release job verifies tag/version consistency, runs tests, builds the wheel, creates the GitHub Release, and uploads the wheel asset.

GitHub Releases are the canonical published release surface. `CHANGELOG.md` remains the curated in-repository history.

### Current published artifact

The release workflow publishes a Python wheel for `testpilot-core` to the corresponding GitHub Release. It does not currently publish TestPilot Core to a public Python package index.

The repository also contains a managed installer used by the maintainer's current QC/TEST deployment profile. That installer resolves the core and the plugin repositories listed in `install-manifest.yaml`; it may therefore require credentials for non-public plugin repositories declared by that manifest.

The current managed online flow resolves the newest release compatible with the declared SDK contract where applicable. `serialwrap` is separately pinned because it does not use the TestPilot plugin SDK compatibility contract.

`testpilot --update REF` currently accepts a `REF` argument for interface compatibility, but cross-version targeting is not implemented; the command reinstalls/reconciles the currently resolved manifest-managed set. Do not document it as a working way to select an arbitrary historical release.

## 6. Release gates

Do not tag a release until all of the following are true:

- the release PR is merged into `main`
- GitHub Actions CI is green for the release commit
- `VERSION`, runtime `__version__`, built package metadata, and intended tag agree
- `CHANGELOG.md` is finalized
- README / docs / AGENTS updates are merged when user-facing behavior changed
- README CLI help marker blocks are synchronized when CLI help changed
- the manifest API-compatibility gate passes
- the offline installer integration gate passes in CI

The repository CI currently includes the core test suite, a real install/discovery/run smoke for `examples/sample_echo`, release-governance tests, manifest SDK compatibility checks, and an offline installer integration smoke.

## 7. Managed-install validation

For a managed installation, use:

```bash
testpilot --verify-install
```

The managed installer and `--update` path are separate from ordinary plugin development. Plugin developers can use the core package with an independently installed plugin, or use path mode to run a plugin checkout directly:

```bash
testpilot /path/to/my_plugin --help
testpilot /path/to/my_plugin
```

## 8. Hotfixes

Hotfix releases follow the same flow with a patch bump:

1. branch from `main`
2. fix the issue and add an appropriate changelog fragment
3. merge the fix PR
4. prepare the next patch release PR
5. merge the release PR
6. tag the merged release commit

## 9. Recovery when a tag is wrong

If a tag is pushed with the wrong version or wrong commit:

1. delete the incorrect GitHub Release if it was created
2. delete the incorrect git tag
3. fix version metadata / changelog on a new PR
4. tag the correct merged `main` commit

Do not reuse an incorrect tag name for a different commit until the bad release/tag has been removed and the intended target has been verified.
