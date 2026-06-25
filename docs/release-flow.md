# TestPilot Versioning and Release Flow

This document defines the repository-level versioning and release process for
TestPilot starting from the managed install baseline `v0.2.0`.

## 1. Versioning policy

TestPilot uses Semantic Versioning with git tags in the form `vX.Y.Z`.

- **Major (`X`)**: breaking operator-facing or consumer-facing changes
  (CLI contract breaks, artifact layout breaks, report format removals, or
  incompatible workflow changes).
- **Minor (`Y`)**: backward-compatible features (new commands, new reporting
  capabilities, new plugin/runtime features, new supported workflows).
- **Patch (`Z`)**: backward-compatible fixes, documentation corrections, test
  improvements, and release automation maintenance.

`v0.2.0` is the starting baseline for the managed installer/update flow.

## 2. Canonical version sources

- **Canonical source**: `VERSION`
- **Packaging mirror**: `pyproject.toml` → `[project].version`
- **Runtime mirror**: `src/testpilot/__init__.py` → `__version__`
- **Published identifier**: git tag `vX.Y.Z`

All four must agree for a release. The repo test suite and release workflow
validate that `VERSION`, `pyproject.toml`, `src/testpilot/__init__.py`, and the
pushed tag stay in sync.

## 3. Day-to-day pull request expectations

Normal feature/fix branches continue to merge through GitHub pull requests.

Each PR should use the GitHub PR template and explicitly cover:

- whether `CHANGELOG.md` needs an `Unreleased` entry
- whether README / docs / AGENTS updates are required
- whether README CLI help marker blocks governed by `.project-policy.yml` need
  synchronization
- what validation was run
- whether the change has release-note impact

Rule of thumb:

- **User-facing or operator-facing changes**: update `CHANGELOG.md`
- **Purely internal churn with no release-note value**: explain why changelog is
  not needed in the PR

## 4. Release preparation flow

Prepare releases in a dedicated branch and PR:

1. Branch from `main` as `feature/<slug>` (for example
   `feature/release-vX-Y-Z`; R-12 branch slugs allow only `[a-z0-9-]`, so drop
   the dots from the version).
2. Update `VERSION`, `pyproject.toml`, and `src/testpilot/__init__.py` to
   `X.Y.Z`.
3. Finalize `CHANGELOG.md`:
   - keep a fresh `Unreleased` section at the top
   - move release-ready notes into `## [X.Y.Z]`
4. Update `README.md`, `docs/release-flow.md`, and `AGENTS.md` if the release
   changes supported workflows, release rules, or operator guidance.
5. Ensure CI, release version validation, and policy/help sync checks are green.
6. Merge the release PR into `main`.

Recommended PR title (must satisfy R-10 conventional-commit; `release:` is not a
valid type):

- `chore(release): prepare vX.Y.Z`

Apply a `release:vX.Y.Z` label to the PR so the deferred VERSION bump (VERSION
leads the latest tag during release prep) is accepted by R-07.

Also apply the `skip-changelog` label: release prep empties the `Unreleased`
queue into `## [X.Y.Z]`, so R-09 (which expects an `Unreleased` bullet when code
files change) would otherwise fail even though the changes are recorded under
`## [X.Y.Z]`.

## 5. Tagging and publication

After the release PR is merged:

1. Create git tag `vX.Y.Z` on the merged `main` commit.
2. Push the tag (or create it from GitHub on the target commit).
3. The tag push triggers `.github/workflows/release.yml`.
4. The workflow:
    - verifies tag/version consistency
    - runs the pinned project policy check
    - runs release governance tests and the full repository test suite
    - creates the GitHub Release
    - uses GitHub auto-generated release notes for the published release page

GitHub Releases are the canonical published release notes surface. `CHANGELOG.md`
remains the curated in-repo history.

### Current deployment model

The current release workflow publishes **metadata only**:

- git tag `vX.Y.Z`
- GitHub Release page with generated release notes

It does **not** build or upload wheel / sdist / binary assets yet. QC/TEST
operators should install through the managed installer, which resolves
`latest-release` to the newest stable `vX.Y.Z` tag by default:

```bash
curl -fsSL https://raw.githubusercontent.com/paulc-arc/testpilot/main/scripts/install.sh | bash
testpilot --verify-install
```

For local validation or controlled rollouts, override the managed source/ref:

```bash
TESTPILOT_REPO_URL=https://github.com/hamanpaul/testpilot.git TESTPILOT_REF=vX.Y.Z bash scripts/install.sh
testpilot --update vX.Y.Z
```

## 6. Release gates

Do not tag a release until all of the following are true:

- the release PR is merged into `main`
- GitHub Actions CI is green for the release commit
- `VERSION`, `pyproject.toml`, `src/testpilot/__init__.py`, and the intended
  tag match
- `CHANGELOG.md` is finalized
- README / docs / AGENTS updates are merged when user-facing behavior changed
- `.project-policy.yml` still declares the required CLI help sync marker blocks

The minimum automated CI gate is the repo test suite (`uv run pytest -q`) plus
the release governance tests that validate policy config and release metadata.

## 7. Hotfixes

Hotfix releases follow the same flow with a patch bump:

1. branch from `main`
2. fix the issue
3. prepare the next patch release PR on a `feature/<slug>` branch (for example
   `feature/release-v0-2-1`)
4. merge
5. tag the merged commit

## 8. Recovery when a tag is wrong

If a tag is pushed with the wrong version:

1. delete the incorrect GitHub Release (if it was created)
2. delete the incorrect git tag
3. fix version metadata / changelog on a new PR
4. retag the correct merged `main` commit

Do not reuse an incorrect tag name for a different commit without first
cleaning up the bad release/tag state.
