"""Static-content assertions for scripts/build-bundle.sh.

These tests encode the contract for the build-bundle script:
- Excludes live testbed and generates SHA256SUMS
- Has dry-run gate with --no-index / --find-links
- Downloads release wheels (gh release download) rather than rebuilding
- Pins requirements.txt
"""
import pathlib

SH = (pathlib.Path(__file__).resolve().parents[1] / "scripts" / "build-bundle.sh").read_text()


def test_excludes_live_testbed():
    # The bundle must NOT contain the operator's live configs/testbed.yaml.
    # build-bundle.sh enforces this by ADDITIVE staging: it copies only an
    # allowlist of files into a fresh STAGE_DIR and tars *that dir* — it never
    # copies the whole repo (which would sweep in configs/testbed.yaml). This
    # test verifies the mechanism is real, not just that the string appears in a
    # comment.
    import re

    # 1. The tarball is produced from the staging dir, not the repo root.
    assert re.search(r'cd\s+"\$STAGE_DIR"\s*&&\s*tar', SH), (
        "bundle tar must be created from the staging dir (additive allowlist)"
    )

    # 2. No bulk whole-repo copy into the stage (which would leak live config).
    forbidden = [
        "cp -r .",
        "cp -a .",
        'cp -r "$REPO_ROOT"',
        'cp -r "${REPO_ROOT}"',
        "cp -r $REPO_ROOT",
        "rsync",
    ]
    for bad in forbidden:
        assert bad not in SH, f"build-bundle.sh must not bulk-copy the repo: found {bad!r}"

    # 3. configs/testbed.yaml is never actually copied/staged — it may only be
    #    referenced in the HARD-EXCLUDE comment.
    staged_copies = re.findall(r"^\s*cp\b.*configs/testbed\.yaml", SH, re.MULTILINE)
    assert not staged_copies, f"live testbed must never be staged: {staged_copies}"

    assert "SHA256SUMS" in SH


def test_dry_run_gate_and_no_index():
    assert "--no-index" in SH and "--find-links" in SH


def test_downloads_release_wheels_not_rebuild():
    assert "gh release download" in SH


def test_pins_requirements():
    assert "requirements.txt" in SH


def test_third_party_deps_resolved_from_first_party_wheels():
    # Regression guard for the click>=8.1,<8.4 breakage: third-party deps must be
    # resolved FROM the already-downloaded first-party wheels' metadata (so core's
    # pins are honored), NOT hand-listed as bare package names — which grabbed the
    # latest click (8.4.x), violated core's pin, and failed the dry-run gate.
    assert "FIRST_PARTY_WHEELS" in SH, (
        "third-party deps must resolve against the first-party wheels' metadata"
    )
    assert "THIRD_PARTY_DEPS=" not in SH, (
        "third-party deps must not be hand-enumerated as bare package names"
    )
