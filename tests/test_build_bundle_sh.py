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
    assert "configs/testbed.yaml" in SH
    assert "SHA256SUMS" in SH


def test_dry_run_gate_and_no_index():
    assert "--no-index" in SH and "--find-links" in SH


def test_downloads_release_wheels_not_rebuild():
    assert "gh release download" in SH


def test_pins_requirements():
    assert "requirements.txt" in SH
