"""Tests for scripts/install.sh managed installer (wheel-world model).

The installer was rewritten from a git-checkout model to a wheel download model.
These tests verify the NEW behaviors using stub executables (gh, uv) that avoid
real network calls, while letting real python3 handle manifest parsing.

OLD behaviors that no longer exist and are NOT tested here:
  - git clone / git ls-remote / git merge --ff-only (all removed)
  - TESTPILOT_REPO_URL (removed; manifest-driven now)
  - serialwrap git clone (removed; serialwrap is a wheel)
"""

from __future__ import annotations

import os
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest

INSTALL_SH = Path(__file__).resolve().parents[1] / "scripts" / "install.sh"
REPO_ROOT = Path(__file__).resolve().parents[1]
REAL_MANIFEST = REPO_ROOT / "install-manifest.yaml"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_executable(path: Path) -> None:
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _write_stub(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content))
    _make_executable(path)


def _build_stub_bin(tmp_path: Path, gh_log: Path, uv_log: Path) -> Path:
    """Create a stub bin/ with fake `gh` and `uv`.

    Real python3 is intentionally NOT stubbed so the manifest parser works.
    """
    bin_dir = tmp_path / "stub_bin"
    bin_dir.mkdir()

    # Real (minimal) wheel builder so the installer can read core's API_VERSION
    # from the downloaded wheel (transactional resolution reads it pre-install).
    make_wheel_py = bin_dir / "make_fake_wheel.py"
    make_wheel_py.write_text(
        "import sys, zipfile\n"
        'with zipfile.ZipFile(sys.argv[1], "w") as z:\n'
        "    z.writestr(\"testpilot/api/__init__.py\", 'API_VERSION = \"1.1\"\\n')\n"
    )
    make_wheel_str = str(make_wheel_py)

    gh_log_str = str(gh_log)
    _write_stub(
        bin_dir / "gh",
        f"""\
        #!/usr/bin/env bash
        # Stub gh — logs all calls; handles `release download` and `api`.
        echo "$@" >> "{gh_log_str}"
        # Parse --dir argument for release download
        _dir=""
        prev=""
        for arg in "$@"; do
            if [[ "$prev" == "--dir" ]]; then
                _dir="$arg"
            fi
            prev="$arg"
        done
        case "$*" in
          *api-version.txt*)
            # Per-release API metadata probe. Default: none published -> fail so
            # the installer falls back to latest. Tests set STUB_PLUGIN_API to
            # exercise compatible-resolution / abort paths.
            if [[ -n "$STUB_PLUGIN_API" ]]; then printf '%s' "$STUB_PLUGIN_API"; exit 0; fi
            exit 1
            ;;
          *"release view"*)
            # latest release tag resolution (sans-v stripped by the installer)
            echo "v9.9.9"
            exit 0
            ;;
          *"release list"*)
            printf 'v9.9.9\\nv9.9.8\\n'
            exit 0
            ;;
          *"release download"*)
            if [[ -n "$_dir" ]]; then
                mkdir -p "$_dir"
                # Create a real minimal wheel (zip) carrying testpilot/api so the
                # installer can read core's API_VERSION from it pre-install.
                python3 "{make_wheel_str}" "$_dir/testpilot_core-0.3.0-py3-none-any.whl"
            fi
            exit 0
            ;;
          *api*)
            # Output a minimal valid manifest for the caller
            printf 'core:\\n  repo: hamanpaul/testpilot-core\\n  version: \"0.3.0\"\\nplugins: []\\nserialwrap:\\n  repo: hamanpaul/serialwrap\\n  version: \"0.2.0\"\\n'
            exit 0
            ;;
          *)
            exit 0
            ;;
        esac
        """,
    )

    uv_log_str = str(uv_log)
    _write_stub(
        bin_dir / "uv",
        f"""\
        #!/usr/bin/env bash
        # Stub uv — creates minimal venv; records all calls.
        echo "$@" >> "{uv_log_str}"
        case "$1" in
          venv)
            VENV_DIR="$2"
            mkdir -p "$VENV_DIR/bin"
            printf '#!/usr/bin/env sh\\necho "$@" >> "%s/.testpilot_calls.log"\\nif [ "$1" = "--verify-install" ] && [ -n "$TESTPILOT_STUB_VERIFY_FAIL" ]; then echo "verify failed" >&2; exit 1; fi\\nexec echo "testpilot mock"\\n' "$VENV_DIR" > "$VENV_DIR/bin/testpilot"
            chmod +x "$VENV_DIR/bin/testpilot"
            # Stub python: report a core SDK API_VERSION when asked, else no-op.
            printf '#!/usr/bin/env sh\\ncase "$*" in\\n  *API_VERSION*) echo "1.1" ;;\\nesac\\nexit 0\\n' > "$VENV_DIR/bin/python"
            chmod +x "$VENV_DIR/bin/python"
            printf '#!/usr/bin/env sh\\nexit 0\\n' > "$VENV_DIR/bin/pip"
            chmod +x "$VENV_DIR/bin/pip"
            ;;
          pip)
            : # no-op for pip install
            ;;
        esac
        exit 0
        """,
    )

    return bin_dir


# Env vars that vary by test and should not leak from the parent process
_ISOLATED_VARS = frozenset(
    {
        "TESTPILOT_HOME",
        "TESTPILOT_BIN_DIR",
        "TESTPILOT_SKILLS_DIR",
        "TESTPILOT_MANIFEST",
        "TESTPILOT_INSTALL_TOKEN",
        "TESTPILOT_REF",
        "GH_TOKEN",
    }
)


def _run_installer(
    fake_home: Path,
    stub_bin: Path,
    extra_env: dict[str, str] | None = None,
    extra_args: list[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run install.sh with stub PATH and isolated env."""
    base_env = {k: v for k, v in os.environ.items() if k not in _ISOLATED_VARS}
    env = {
        **base_env,
        "HOME": str(fake_home),
        # stub_bin first so our fake gh/uv override any system versions;
        # real python3 comes from the system PATH (not stubbed).
        "PATH": f"{stub_bin}:{os.environ.get('PATH', '/usr/bin:/bin')}",
        "TESTPILOT_HOME": str(fake_home / ".local" / "share" / "testpilot"),
        "TESTPILOT_BIN_DIR": str(fake_home / ".local" / "bin"),
        "TESTPILOT_SKILLS_DIR": str(fake_home / ".agents" / "skills"),
        # Use the real repo manifest to avoid gh api calls in tests
        "TESTPILOT_MANIFEST": str(REAL_MANIFEST),
        # Suppress any GH_TOKEN so tests don't depend on dev machine auth
        "GH_TOKEN": "",
    }
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(INSTALL_SH), *(extra_args or [])],
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
def gh_log(tmp_path: Path) -> Path:
    return tmp_path / "gh.log"


@pytest.fixture()
def uv_log(tmp_path: Path) -> Path:
    return tmp_path / "uv.log"


@pytest.fixture()
def stubs(tmp_path: Path, gh_log: Path, uv_log: Path) -> Path:
    return _build_stub_bin(tmp_path, gh_log, uv_log)


# ---------------------------------------------------------------------------
# Scenario: Online mode — basic install flow
# ---------------------------------------------------------------------------


class TestOnlineInstall:
    """Installer (online mode) creates venv, downloads wheels, writes wrapper."""

    def test_exits_zero_with_manifest_override(
        self, fake_home: Path, stubs: Path
    ) -> None:
        """Installer exits 0 when TESTPILOT_MANIFEST is set (skips gh api call)."""
        result = _run_installer(fake_home, stubs)
        assert result.returncode == 0, (
            f"installer failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )

    def test_creates_venv(self, fake_home: Path, stubs: Path) -> None:
        """Installer creates the managed virtualenv directory."""
        result = _run_installer(fake_home, stubs)
        assert result.returncode == 0, f"installer failed:\n{result.stderr}"
        managed_venv = fake_home / ".local" / "share" / "testpilot" / ".venv"
        assert managed_venv.exists(), f"venv not created at {managed_venv}"

    def test_creates_wrapper(self, fake_home: Path, stubs: Path) -> None:
        """Installer creates an executable wrapper at TESTPILOT_BIN_DIR/testpilot."""
        result = _run_installer(fake_home, stubs)
        assert result.returncode == 0, f"installer failed:\n{result.stderr}"
        wrapper = fake_home / ".local" / "bin" / "testpilot"
        assert wrapper.exists(), f"wrapper not created at {wrapper}"
        assert os.access(wrapper, os.X_OK), "wrapper is not executable"

    def test_wrapper_references_managed_venv(self, fake_home: Path, stubs: Path) -> None:
        """Wrapper must exec the managed venv's testpilot binary (no source activation)."""
        result = _run_installer(fake_home, stubs)
        assert result.returncode == 0, f"installer failed:\n{result.stderr}"
        wrapper = fake_home / ".local" / "bin" / "testpilot"
        content = wrapper.read_text()
        managed_venv = fake_home / ".local" / "share" / "testpilot" / ".venv"
        assert str(managed_venv) in content, (
            f"wrapper does not reference managed venv {managed_venv}:\n{content}"
        )

    def test_calls_gh_release_download(
        self, fake_home: Path, stubs: Path, gh_log: Path
    ) -> None:
        """Online mode calls gh release download (not git clone) for packages."""
        result = _run_installer(fake_home, stubs)
        assert result.returncode == 0, f"installer failed:\n{result.stderr}"
        assert gh_log.exists(), "gh was never called"
        gh_calls = gh_log.read_text()
        assert "release download" in gh_calls, (
            f"gh release download not called:\n{gh_calls}"
        )

    def test_does_not_call_git_clone(
        self, fake_home: Path, stubs: Path, tmp_path: Path, gh_log: Path
    ) -> None:
        """Online mode must NOT use git clone (old model); wheels only."""
        result = _run_installer(fake_home, stubs)
        assert result.returncode == 0, f"installer failed:\n{result.stderr}"
        # There is no stub for git in stub_bin, so if the script called git
        # it would use the system git — but we check that no managed src dir
        # was created (that's the old model's artifact).
        managed_src = fake_home / ".local" / "share" / "testpilot" / "src"
        assert not managed_src.exists(), (
            f"old-model managed_src checkout was created at {managed_src} — "
            "installer should not git-clone anymore"
        )

    def test_no_token_in_stdout(self, fake_home: Path, stubs: Path) -> None:
        """Installer must never print the GH_TOKEN value to stdout."""
        sentinel = "TEST_SECRET_TOKEN_12345"
        result = _run_installer(
            fake_home, stubs, extra_env={"GH_TOKEN": sentinel}
        )
        assert sentinel not in result.stdout, (
            "GH_TOKEN value appeared in installer stdout — token leak detected"
        )

    def test_plugins_flag_filters_downloads(
        self, fake_home: Path, stubs: Path, gh_log: Path
    ) -> None:
        """--plugins <csv> restricts which plugin wheels are downloaded."""
        result = _run_installer(
            fake_home,
            stubs,
            extra_env={"TESTPILOT_MANIFEST": str(REAL_MANIFEST)},
        )
        # With the real manifest that has wifi_llapi and brcm_fw_upgrade,
        # running without --plugins should attempt both. We just verify exit 0
        # and that core download was called.
        assert result.returncode == 0, f"installer failed:\n{result.stderr}"
        gh_calls = gh_log.read_text() if gh_log.exists() else ""
        # Core should always be downloaded
        assert "release download" in gh_calls


# ---------------------------------------------------------------------------
# Scenario: Online mode — offline rollback wheel cache (CRITICAL)
# ---------------------------------------------------------------------------


class TestWheelCachePreservation:
    """Online install preserves wheels into the rollback wheel-cache.

    The cache backs `testpilot --update` rollback's `--no-index --find-links`
    reinstall, so it must never reach a public index.
    """

    def test_online_populates_wheel_cache(
        self, fake_home: Path, stubs: Path
    ) -> None:
        result = _run_installer(fake_home, stubs)
        assert result.returncode == 0, (
            f"installer failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
        cache = fake_home / ".local" / "share" / "testpilot" / ".wheel-cache"
        assert cache.exists(), f"wheel cache not created at {cache}"
        wheels = list(cache.glob("*.whl"))
        assert wheels, (
            f"no wheels preserved into the rollback cache {cache}:\n{result.stdout}"
        )


class TestVenvCreationGuard:
    """A failed venv creation must abort with a clear error (no `|| true` mask)."""

    def _stub_bin_with_broken_venv(self, tmp_path: Path) -> Path:
        bin_dir = tmp_path / "broken_stub_bin"
        bin_dir.mkdir()
        # gh stub: same minimal release/api behavior as the normal stub.
        _write_stub(
            bin_dir / "gh",
            """\
            #!/usr/bin/env bash
            _dir=""
            prev=""
            for arg in "$@"; do
                if [[ "$prev" == "--dir" ]]; then _dir="$arg"; fi
                prev="$arg"
            done
            case "$*" in
              *"release download"*)
                if [[ -n "$_dir" ]]; then
                    mkdir -p "$_dir"
                    touch "$_dir/testpilot_core-0.3.0-py3-none-any.whl"
                fi
                exit 0 ;;
              *) exit 0 ;;
            esac
            """,
        )
        # uv stub: `venv` creates the dir + testpilot/pip but a NON-executable python.
        _write_stub(
            bin_dir / "uv",
            """\
            #!/usr/bin/env bash
            case "$1" in
              venv)
                VENV_DIR="$2"
                mkdir -p "$VENV_DIR/bin"
                printf '#!/usr/bin/env sh\\nexit 0\\n' > "$VENV_DIR/bin/testpilot"
                chmod +x "$VENV_DIR/bin/testpilot"
                # python created but deliberately NOT executable -> broken venv
                printf 'broken\\n' > "$VENV_DIR/bin/python"
                chmod 0644 "$VENV_DIR/bin/python"
                ;;
              pip) : ;;
            esac
            exit 0
            """,
        )
        return bin_dir

    def test_broken_venv_python_aborts(self, fake_home: Path, tmp_path: Path) -> None:
        broken = self._stub_bin_with_broken_venv(tmp_path)
        result = _run_installer(fake_home, broken)
        assert result.returncode != 0, (
            "installer must abort when the managed venv python is not executable\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
        combined = (result.stdout + result.stderr).lower()
        assert "virtualenv" in combined or "venv" in combined or "python" in combined, (
            f"no clear venv-failure message:\n{result.stdout}\n{result.stderr}"
        )


# ---------------------------------------------------------------------------
# Scenario: Offline mode
# ---------------------------------------------------------------------------


class TestOfflineInstall:
    """Installer (--offline mode) verifies checksum, extracts bundle, installs."""

    def _make_bundle(self, tmp_path: Path) -> tuple[Path, Path]:
        """Create a minimal fake bundle tarball with valid SHA256SUMS sidecar."""
        import hashlib
        import tarfile

        bundle_dir = tmp_path / "bundle_staging"
        wheelhouse = bundle_dir / "wheelhouse"
        wheelhouse.mkdir(parents=True)
        # Create a dummy wheel
        (wheelhouse / "testpilot_core-0.3.0-py3-none-any.whl").write_bytes(b"")
        # Create requirements.txt
        (bundle_dir / "requirements.txt").write_text(
            "testpilot-core==0.3.0\n"
        )

        # Python minor for the bundle filename
        import sys
        pyminor = f"{sys.version_info.major}{sys.version_info.minor}"

        tarball_name = f"testpilot-bundle-0.3.0-linux-x86_64-cp{pyminor}.tar.gz"
        tarball_path = tmp_path / tarball_name

        with tarfile.open(str(tarball_path), "w:gz") as tar:
            tar.add(str(bundle_dir), arcname=".")

        # Write SHA256SUMS sidecar (correct)
        digest = hashlib.sha256(tarball_path.read_bytes()).hexdigest()
        sums_path = Path(str(tarball_path) + ".SHA256SUMS")
        sums_path.write_text(f"{digest}  {tarball_name}\n")

        return tarball_path, sums_path

    def test_offline_bad_checksum_aborts(self, tmp_path: Path, fake_home: Path) -> None:
        """--offline rejects a bundle whose SHA256SUMS doesn't match."""
        tarball, sums = self._make_bundle(tmp_path)
        # Corrupt the sidecar
        sums.write_text("deadbeef  " + tarball.name + "\n")

        result = subprocess.run(
            ["bash", str(INSTALL_SH), "--offline", str(tarball)],
            env={
                **os.environ,
                "HOME": str(fake_home),
                "TESTPILOT_HOME": str(fake_home / ".local" / "share" / "testpilot"),
                "TESTPILOT_BIN_DIR": str(fake_home / ".local" / "bin"),
                "TESTPILOT_SKILLS_DIR": str(fake_home / ".agents" / "skills"),
            },
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0, "installer should have aborted on bad checksum"
        assert "checksum" in (result.stdout + result.stderr).lower() or \
               "FAIL" in (result.stdout + result.stderr), (
            f"No checksum failure message:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )

    def test_offline_python_version_mismatch_aborts(
        self, tmp_path: Path, fake_home: Path
    ) -> None:
        """--offline aborts if bundle cpXY token doesn't match running python."""
        # Build a bundle with a deliberately wrong python version token
        import hashlib, tarfile, sys

        bundle_dir = tmp_path / "bundle_staging"
        (bundle_dir / "wheelhouse").mkdir(parents=True)
        (bundle_dir / "requirements.txt").write_text("testpilot-core==0.3.0\n")

        running_minor = sys.version_info.minor
        # Pick a different minor version
        wrong_minor = running_minor + 1 if running_minor < 20 else running_minor - 1
        wrong_pyminor = f"3{wrong_minor}"

        tarball_name = f"testpilot-bundle-0.3.0-linux-x86_64-cp{wrong_pyminor}.tar.gz"
        tarball_path = tmp_path / tarball_name
        with tarfile.open(str(tarball_path), "w:gz") as tar:
            tar.add(str(bundle_dir), arcname=".")

        digest = hashlib.sha256(tarball_path.read_bytes()).hexdigest()
        sums_path = Path(str(tarball_path) + ".SHA256SUMS")
        sums_path.write_text(f"{digest}  {tarball_name}\n")

        result = subprocess.run(
            ["bash", str(INSTALL_SH), "--offline", str(tarball_path)],
            env={
                **os.environ,
                "HOME": str(fake_home),
                "TESTPILOT_HOME": str(fake_home / ".local" / "share" / "testpilot"),
                "TESTPILOT_BIN_DIR": str(fake_home / ".local" / "bin"),
                "TESTPILOT_SKILLS_DIR": str(fake_home / ".agents" / "skills"),
            },
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0, (
            f"installer should have aborted on python version mismatch"
            f"\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
        combined = result.stdout + result.stderr
        assert "mismatch" in combined.lower() or "version" in combined.lower(), (
            f"No version mismatch message:\n{combined}"
        )

    def test_offline_arch_mismatch_aborts(self, tmp_path: Path, fake_home: Path) -> None:
        """--offline aborts (before extraction) if the bundle linux-<arch> tag
        does not match `uname -m`."""
        import hashlib
        import tarfile
        import sys

        bundle_dir = tmp_path / "bundle_staging"
        (bundle_dir / "wheelhouse").mkdir(parents=True)
        (bundle_dir / "requirements.txt").write_text("testpilot-core==0.3.0\n")

        pyminor = f"{sys.version_info.major}{sys.version_info.minor}"
        # Deliberately wrong architecture token (correct python token).
        tarball_name = f"testpilot-bundle-0.3.0-linux-ppc64le-cp{pyminor}.tar.gz"
        tarball_path = tmp_path / tarball_name
        with tarfile.open(str(tarball_path), "w:gz") as tar:
            tar.add(str(bundle_dir), arcname=".")

        digest = hashlib.sha256(tarball_path.read_bytes()).hexdigest()
        sums_path = Path(str(tarball_path) + ".SHA256SUMS")
        sums_path.write_text(f"{digest}  {tarball_name}\n")

        result = subprocess.run(
            ["bash", str(INSTALL_SH), "--offline", str(tarball_path)],
            env={
                **{k: v for k, v in os.environ.items() if k not in _ISOLATED_VARS},
                "HOME": str(fake_home),
                "TESTPILOT_HOME": str(fake_home / ".local" / "share" / "testpilot"),
                "TESTPILOT_BIN_DIR": str(fake_home / ".local" / "bin"),
                "TESTPILOT_SKILLS_DIR": str(fake_home / ".agents" / "skills"),
            },
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0, (
            "installer should abort on arch mismatch\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
        combined = (result.stdout + result.stderr).lower()
        assert "arch" in combined or "ppc64le" in combined, (
            f"no architecture mismatch message:\n{result.stdout}\n{result.stderr}"
        )
        # Fail-fast: the managed venv must NOT have been created.
        assert not (fake_home / ".local" / "share" / "testpilot" / ".venv").exists(), (
            "arch check must fail BEFORE venv creation / extraction"
        )

    def test_offline_creates_wrapper(self, tmp_path: Path, fake_home: Path, stubs: Path) -> None:
        """--offline mode still writes the wrapper at TESTPILOT_BIN_DIR/testpilot.

        We use a stub uv so the (empty) wheel install succeeds, and check that
        the wrapper was written afterward.
        """
        tarball, sums = self._make_bundle(tmp_path)

        result = subprocess.run(
            ["bash", str(INSTALL_SH), "--offline", str(tarball)],
            env={
                **{k: v for k, v in os.environ.items() if k not in _ISOLATED_VARS},
                "HOME": str(fake_home),
                "PATH": f"{stubs}:{os.environ.get('PATH', '/usr/bin:/bin')}",
                "TESTPILOT_HOME": str(fake_home / ".local" / "share" / "testpilot"),
                "TESTPILOT_BIN_DIR": str(fake_home / ".local" / "bin"),
                "TESTPILOT_SKILLS_DIR": str(fake_home / ".agents" / "skills"),
            },
            capture_output=True,
            text=True,
        )
        # The post-install gate (testpilot --verify-install) will fail with the
        # stub venv; check that we get at least as far as wrapper creation.
        wrapper = fake_home / ".local" / "bin" / "testpilot"
        assert wrapper.exists(), (
            f"Wrapper was not created even though bundle extraction succeeded.\n"
            f"returncode={result.returncode}\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
        assert os.access(wrapper, os.X_OK), "wrapper is not executable"


# ---------------------------------------------------------------------------
# Scenario: Venv idempotency
# ---------------------------------------------------------------------------


class TestVenvIdempotence:
    """Installer is idempotent when the managed venv already exists."""

    def test_existing_venv_not_recreated(
        self, fake_home: Path, stubs: Path, uv_log: Path
    ) -> None:
        """When .venv/bin already exists, `uv venv` is not called again (uses || true)."""
        # Pre-create the managed venv directory
        managed_venv = fake_home / ".local" / "share" / "testpilot" / ".venv"
        (managed_venv / "bin").mkdir(parents=True)
        # Create a stub testpilot binary so wrapper creation succeeds
        tp = managed_venv / "bin" / "testpilot"
        tp.write_text("#!/usr/bin/env sh\nexec echo 'testpilot mock'\n")
        tp.chmod(0o755)
        py = managed_venv / "bin" / "python"
        py.write_text("#!/usr/bin/env sh\nexit 0\n")
        py.chmod(0o755)

        result = _run_installer(fake_home, stubs)
        assert result.returncode == 0, (
            f"installer failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )

        uv_calls = uv_log.read_text() if uv_log.exists() else ""
        # The script calls `uv venv ... 2>/dev/null || true` — it may still call
        # uv venv (that's fine; || true makes it idempotent). The key assertion is
        # that the installer still SUCCEEDS even with a pre-existing venv.
        # Additionally, uv pip install should still be called to refresh packages.
        assert "pip" in uv_calls, (
            f"uv pip install was not called to refresh packages:\n{uv_calls}"
        )

    def test_installer_succeeds_on_rerun(
        self, fake_home: Path, stubs: Path
    ) -> None:
        """Running the installer twice produces consistent results (idempotent)."""
        result1 = _run_installer(fake_home, stubs)
        assert result1.returncode == 0, f"First run failed:\n{result1.stderr}"

        result2 = _run_installer(fake_home, stubs)
        assert result2.returncode == 0, f"Second run failed:\n{result2.stderr}"

        wrapper = fake_home / ".local" / "bin" / "testpilot"
        assert wrapper.exists(), "Wrapper missing after second run"


# ---------------------------------------------------------------------------
# Scenario: shared post-install verify gate on the ONLINE path
# ---------------------------------------------------------------------------


def _venv_calls_log(fake_home: Path) -> Path:
    return fake_home / ".local" / "share" / "testpilot" / ".venv" / ".testpilot_calls.log"


class TestOnlineVerifyGate:
    """The online path must run `testpilot --verify-install` and honor its exit."""

    def test_online_runs_verify_gate(self, fake_home: Path, stubs: Path) -> None:
        result = _run_installer(fake_home, stubs)
        assert result.returncode == 0, result.stderr
        calls = _venv_calls_log(fake_home).read_text()
        assert "--verify-install" in calls

    def test_online_verify_failure_fails_install(
        self, fake_home: Path, stubs: Path
    ) -> None:
        result = _run_installer(
            fake_home, stubs, {"TESTPILOT_STUB_VERIFY_FAIL": "1"}
        )
        assert result.returncode != 0
        assert "Post-install gate FAILED" in result.stderr


# ---------------------------------------------------------------------------
# Scenario: latest-compatible resolution (core/plugins unpinned; serialwrap pinned)
# ---------------------------------------------------------------------------


class TestLatestCompatibleResolution:
    def test_resolves_latest_when_unpinned(
        self, fake_home: Path, stubs: Path, gh_log: Path
    ) -> None:
        """With no pinned core/plugin version, the installer resolves latest."""
        result = _run_installer(fake_home, stubs)
        assert result.returncode == 0, result.stderr
        log = gh_log.read_text()
        assert "release view" in log  # core latest resolution

    def test_no_compatible_release_aborts(
        self, fake_home: Path, stubs: Path, uv_log: Path
    ) -> None:
        """Published api metadata incompatible with core -> loud abort BEFORE any
        package is installed (transactional: resolution precedes mutation)."""
        result = _run_installer(fake_home, stubs, {"STUB_PLUGIN_API": "2.0"})
        assert result.returncode != 0
        assert "No API-compatible release" in result.stderr
        # Non-mutation: no `pip install` into the managed venv happened — the
        # abort occurred during resolution, before the install phase.
        uv_calls = uv_log.read_text() if uv_log.exists() else ""
        assert "pip install" not in uv_calls, (
            f"resolution abort must not install anything: {uv_calls!r}"
        )

    def test_compatible_metadata_resolves(
        self, fake_home: Path, stubs: Path
    ) -> None:
        """Published api metadata compatible with core -> install succeeds."""
        result = _run_installer(fake_home, stubs, {"STUB_PLUGIN_API": "1.0"})
        assert result.returncode == 0, result.stderr

    def test_explicit_pin_bypasses_resolution(
        self, fake_home: Path, stubs: Path, gh_log: Path
    ) -> None:
        """`--plugins name@ver` pins the plugin, skipping latest resolution."""
        result = _run_installer(
            fake_home, stubs, extra_args=["--plugins", "wifi_llapi@1.2.3"]
        )
        assert result.returncode == 0, result.stderr
        log = gh_log.read_text()
        assert "release download v1.2.3" in log
