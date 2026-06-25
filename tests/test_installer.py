"""Tests for scripts/install.sh managed installer (Task 2.1).

These tests use temporary HOME/bin directories and stub PATH executables to
avoid touching real user state or network resources.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

INSTALL_SH = Path(__file__).resolve().parents[1] / "scripts" / "install.sh"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_executable(path: Path) -> None:
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _write_stub(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    _make_executable(path)


def _build_stub_bin(
    tmp_path: Path, git_log: Path, uv_log: Path | None = None
) -> Path:
    """Create a stub bin/ directory with fake git, uv, python3."""
    bin_dir = tmp_path / "stub_bin"
    bin_dir.mkdir()

    git_log_str = str(git_log)
    _write_stub(
        bin_dir / "git",
        f"""\
#!/usr/bin/env bash
# Stub git — logs all calls; handles ls-remote, clone, and the rest as no-ops.
echo "$@" >> "{git_log_str}"
args=("$@")
case "$*" in
  *ls-remote*)
    printf 'abc123\\trefs/tags/v0.2.0\\n'
    printf 'def456\\trefs/tags/v0.1.5\\n'
    exit 0
    ;;
  *clone*)
    # Extract destination (last positional arg)
    DEST="${{args[-1]}}"
    mkdir -p "$DEST/.git" "$DEST/skills/testpilot-normal-test"
    touch "$DEST/.git/config"
    exit 0
    ;;
  *"merge --ff-only origin/main"*)
    if [ "${{STUB_FAIL_FF_ONLY:-0}}" = "1" ]; then
      exit 1
    fi
    exit 0
    ;;
  *)
    exit 0
    ;;
esac
""",
    )

    uv_log_line = f'echo "$@" >> "{uv_log}"' if uv_log is not None else ": # uv logging disabled"
    _write_stub(
        bin_dir / "uv",
        f"""\
#!/usr/bin/env bash
# Stub uv — creates minimal venv structure; treats pip/run/sync as no-ops.
{uv_log_line}
case "$1" in
  venv)
    VENV_DIR="$2"
    mkdir -p "$VENV_DIR/bin"
    printf '#!/usr/bin/env sh\\nexec echo "testpilot mock"\\n' > "$VENV_DIR/bin/testpilot"
    chmod +x "$VENV_DIR/bin/testpilot"
    printf '#!/usr/bin/env sh\\nexec echo "python mock"\\n' > "$VENV_DIR/bin/python"
    chmod +x "$VENV_DIR/bin/python"
    ;;
  *)
    : # no-op for pip, run, sync, …
    ;;
esac
exit 0
""",
    )

    _write_stub(
        bin_dir / "python3",
        """\
#!/usr/bin/env bash
case "$*" in
  *version_info*|*sys*)
    echo "3.11"
    ;;
  -V|--version)
    echo "Python 3.11.0"
    ;;
  *)
    echo "Python 3.11.0"
    ;;
esac
exit 0
""",
    )

    return bin_dir


_ISOLATED_VARS = frozenset(
    {
        "TESTPILOT_REPO_URL",
        "TESTPILOT_REF",
        "SERIALWRAP_REPO_URL",
        "TESTPILOT_HOME",
        "TESTPILOT_BIN_DIR",
        "TESTPILOT_SKILLS_DIR",
        "SERIALWRAP_INSTALL_DIR",
    }
)


def _run_installer(
    fake_home: Path,
    stub_bin: Path,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run install.sh with stubbed HOME and PATH.

    Parent-process TESTPILOT_* and SERIALWRAP_* env vars are stripped so that
    operator-local settings cannot bleed into tests that verify default behaviour.
    """
    # Start from a clean base — strip vars that install.sh honours as overrides.
    base_env = {k: v for k, v in os.environ.items() if k not in _ISOLATED_VARS}
    env = {
        **base_env,
        "HOME": str(fake_home),
        "PATH": f"{stub_bin}:{os.environ.get('PATH', '/usr/bin:/bin')}",
        # Redirect all managed paths into fake_home so real user dirs are untouched.
        "TESTPILOT_HOME": str(fake_home / ".local" / "share" / "testpilot"),
        "TESTPILOT_BIN_DIR": str(fake_home / ".local" / "bin"),
        "TESTPILOT_SKILLS_DIR": str(fake_home / ".agents" / "skills"),
        "SERIALWRAP_INSTALL_DIR": str(fake_home / ".local" / "share" / "serialwrap"),
    }
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(INSTALL_SH)],
        env=env,
        capture_output=True,
        text=True,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    return home


@pytest.fixture()
def git_log(tmp_path: Path) -> Path:
    return tmp_path / "git.log"


@pytest.fixture()
def uv_log(tmp_path: Path) -> Path:
    return tmp_path / "uv.log"


@pytest.fixture()
def stubs(tmp_path: Path, git_log: Path, uv_log: Path) -> Path:
    return _build_stub_bin(tmp_path, git_log, uv_log)


# ---------------------------------------------------------------------------
# Scenario: Local override install
# ---------------------------------------------------------------------------


class TestLocalOverrideInstall:
    """Installer creates managed checkout from a local TESTPILOT_REPO_URL."""

    def test_creates_managed_checkout(self, fake_home: Path, stubs: Path) -> None:
        """Installer creates managed checkout under TESTPILOT_HOME/src."""
        result = _run_installer(
            fake_home,
            stubs,
            {"TESTPILOT_REPO_URL": "file:///local/testpilot", "TESTPILOT_REF": "v0.2.0"},
        )
        assert result.returncode == 0, f"installer failed:\n{result.stdout}\n{result.stderr}"
        managed_src = fake_home / ".local" / "share" / "testpilot" / "src"
        assert managed_src.exists(), f"managed_src not created at {managed_src}"

    def test_creates_wrapper(self, fake_home: Path, stubs: Path) -> None:
        """Installer creates an executable wrapper at TESTPILOT_BIN_DIR/testpilot."""
        result = _run_installer(
            fake_home,
            stubs,
            {"TESTPILOT_REPO_URL": "file:///local/testpilot", "TESTPILOT_REF": "v0.2.0"},
        )
        assert result.returncode == 0, f"installer failed:\n{result.stdout}\n{result.stderr}"
        wrapper = fake_home / ".local" / "bin" / "testpilot"
        assert wrapper.exists(), f"wrapper not created at {wrapper}"
        assert os.access(wrapper, os.X_OK), "wrapper is not executable"

    def test_wrapper_references_managed_venv(self, fake_home: Path, stubs: Path) -> None:
        """Wrapper content must exec the managed venv's testpilot (no source activation)."""
        result = _run_installer(
            fake_home,
            stubs,
            {"TESTPILOT_REPO_URL": "file:///local/testpilot", "TESTPILOT_REF": "v0.2.0"},
        )
        assert result.returncode == 0, f"installer failed:\n{result.stdout}\n{result.stderr}"
        wrapper = fake_home / ".local" / "bin" / "testpilot"
        assert wrapper.exists(), "wrapper not created"
        content = wrapper.read_text()
        managed_venv = fake_home / ".local" / "share" / "testpilot" / ".venv"
        assert str(managed_venv) in content, (
            f"wrapper does not reference managed venv {managed_venv}:\n{content}"
        )

    def test_syncs_skill(self, fake_home: Path, stubs: Path) -> None:
        """Installer syncs testpilot-normal-test to TESTPILOT_SKILLS_DIR."""
        result = _run_installer(
            fake_home,
            stubs,
            {"TESTPILOT_REPO_URL": "file:///local/testpilot", "TESTPILOT_REF": "v0.2.0"},
        )
        assert result.returncode == 0, f"installer failed:\n{result.stdout}\n{result.stderr}"
        skill_dst = fake_home / ".agents" / "skills" / "testpilot-normal-test"
        assert skill_dst.exists(), f"skill not synced to {skill_dst}"


# ---------------------------------------------------------------------------
# Scenario: Default latest-release resolution
# ---------------------------------------------------------------------------


class TestDefaultLatestRelease:
    """Installer resolves latest-release to the highest stable vX.Y.Z tag."""

    def test_resolves_latest_release_tag(
        self, fake_home: Path, stubs: Path, git_log: Path
    ) -> None:
        """latest-release is resolved to the highest vX.Y.Z tag from git ls-remote."""
        result = _run_installer(
            fake_home,
            stubs,
            {
                "TESTPILOT_REPO_URL": "file:///local/testpilot",
                "TESTPILOT_REF": "latest-release",
            },
        )
        assert result.returncode == 0, f"installer failed:\n{result.stdout}\n{result.stderr}"
        assert git_log.exists(), "git log not created"
        log_content = git_log.read_text()
        # After resolving, installer must check out v0.2.0 (highest tag in stub output).
        assert "v0.2.0" in log_content, (
            f"latest-release was not resolved to v0.2.0 in git calls:\n{log_content}"
        )

    def test_uses_default_repo_url(
        self, fake_home: Path, stubs: Path, git_log: Path
    ) -> None:
        """When TESTPILOT_REPO_URL is unset, installer uses the paulc-arc default."""
        result = _run_installer(fake_home, stubs)
        assert result.returncode == 0, f"installer failed:\n{result.stdout}\n{result.stderr}"
        log_content = git_log.read_text() if git_log.exists() else ""
        assert "paulc-arc/testpilot" in log_content, (
            f"default repo URL not used:\n{log_content}"
        )


# ---------------------------------------------------------------------------
# Scenario: Serialwrap command selection
# ---------------------------------------------------------------------------


class TestSerialwrapInstall:
    """Installer clones serialwrap from SERIALWRAP_REPO_URL."""

    def test_clones_serialwrap(
        self, fake_home: Path, stubs: Path, git_log: Path
    ) -> None:
        """git clone is called with the serialwrap URL."""
        result = _run_installer(
            fake_home,
            stubs,
            {
                "TESTPILOT_REPO_URL": "file:///local/testpilot",
                "TESTPILOT_REF": "v0.2.0",
                "SERIALWRAP_REPO_URL": "https://github.com/paulc-arc/serialwrap.git",
            },
        )
        assert result.returncode == 0, f"installer failed:\n{result.stdout}\n{result.stderr}"
        log_content = git_log.read_text() if git_log.exists() else ""
        assert "serialwrap" in log_content, (
            f"serialwrap was not cloned (no serialwrap in git log):\n{log_content}"
        )


class TestSerialwrapUpdate:
    """Installer updates existing serialwrap checkout deterministically."""

    def test_existing_serialwrap_fast_forwards_without_pull(
        self, fake_home: Path, stubs: Path, git_log: Path
    ) -> None:
        """Existing serialwrap checkout uses fetch + ff-only merge, never bare pull."""
        serialwrap_src = fake_home / ".local" / "share" / "serialwrap" / "src"
        (serialwrap_src / ".git").mkdir(parents=True)
        (serialwrap_src / ".git" / "config").touch()

        result = _run_installer(
            fake_home,
            stubs,
            {"TESTPILOT_REPO_URL": "file:///local/testpilot", "TESTPILOT_REF": "v0.2.0"},
        )
        assert result.returncode == 0, f"installer failed:\n{result.stdout}\n{result.stderr}"

        log_content = git_log.read_text() if git_log.exists() else ""
        assert "pull" not in log_content, f"serialwrap update used bare pull:\n{log_content}"
        assert "fetch origin" in log_content, f"serialwrap update did not fetch:\n{log_content}"
        assert "merge --ff-only" in log_content, (
            f"serialwrap update did not attempt ff-only merge:\n{log_content}"
        )


# ---------------------------------------------------------------------------
# Scenario: Venv idempotency (I-1)
# ---------------------------------------------------------------------------


class TestVenvIdempotence:
    """installer must skip venv creation when the venv already exists."""

    def test_existing_venv_not_recreated(
        self, fake_home: Path, stubs: Path, uv_log: Path
    ) -> None:
        """When MANAGED_VENV/bin already exists, uv venv is NOT called again."""
        # Pre-create the managed venv so the installer should skip creation.
        managed_venv = fake_home / ".local" / "share" / "testpilot" / ".venv"
        (managed_venv / "bin").mkdir(parents=True)
        py = managed_venv / "bin" / "python"
        py.write_text("#!/usr/bin/env sh\nexec echo 'python mock'\n")
        py.chmod(0o755)

        result = _run_installer(
            fake_home,
            stubs,
            {"TESTPILOT_REPO_URL": "file:///local/testpilot", "TESTPILOT_REF": "v0.2.0"},
        )
        assert result.returncode == 0, f"installer failed:\n{result.stdout}\n{result.stderr}"

        uv_calls = uv_log.read_text() if uv_log.exists() else ""
        # "uv venv …" must NOT appear when venv already exists.
        assert not any(
            line.startswith("venv ") or line == "venv" for line in uv_calls.splitlines()
        ), f"uv venv was called despite existing venv:\n{uv_calls}"
        # "uv pip install …" MUST still appear to keep the package up-to-date.
        assert "pip" in uv_calls, f"uv pip install was not called:\n{uv_calls}"


# ---------------------------------------------------------------------------
# Scenario: Branch fast-forward on existing checkout (I-2)
# ---------------------------------------------------------------------------


class TestExistingCheckoutUpdate:
    """Installer fast-forwards branch HEAD when updating an existing checkout."""

    def test_existing_checkout_fast_forwards_branch(
        self, fake_home: Path, stubs: Path, git_log: Path
    ) -> None:
        """Existing checkout with a branch ref: git merge --ff-only is called."""
        managed_src = fake_home / ".local" / "share" / "testpilot" / "src"
        (managed_src / ".git").mkdir(parents=True)
        (managed_src / ".git" / "config").touch()
        (managed_src / "skills" / "testpilot-normal-test").mkdir(parents=True)

        result = _run_installer(
            fake_home,
            stubs,
            {"TESTPILOT_REPO_URL": "file:///local/testpilot", "TESTPILOT_REF": "main"},
        )
        assert result.returncode == 0, f"installer failed:\n{result.stdout}\n{result.stderr}"

        log_content = git_log.read_text() if git_log.exists() else ""
        assert "merge --ff-only origin/main" in log_content, (
            f"fast-forward merge not found in git log:\n{log_content}"
        )

    def test_existing_checkout_warns_when_fast_forward_fails(
        self, fake_home: Path, stubs: Path
    ) -> None:
        """Diverged branch update warns instead of claiming silent success."""
        managed_src = fake_home / ".local" / "share" / "testpilot" / "src"
        (managed_src / ".git").mkdir(parents=True)
        (managed_src / ".git" / "config").touch()
        (managed_src / "skills" / "testpilot-normal-test").mkdir(parents=True)

        result = _run_installer(
            fake_home,
            stubs,
            {
                "TESTPILOT_REPO_URL": "file:///local/testpilot",
                "TESTPILOT_REF": "main",
                "STUB_FAIL_FF_ONLY": "1",
            },
        )

        assert result.returncode == 0, f"installer failed:\n{result.stdout}\n{result.stderr}"
        assert "testpilot fast-forward failed" in result.stdout
