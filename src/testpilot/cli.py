"""TestPilot CLI — command-line entry point."""

from __future__ import annotations

import importlib
import importlib.metadata
import importlib.resources
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

import click
from dataclasses import dataclass
from rich.table import Table

from testpilot import __version__
from testpilot.cli_support import (
    CliRegistrar,
    console,
    get_orchestrator,
    run_command_guidance,
    run_plugin_cases,
)
from testpilot.core.azure_auth import (
    resolve_provider_config,
    setup_azure_auth,
)
from testpilot.core.plugin_loader import PluginLoader

# Expected under ~/.agents/skills/ — the Copilot agent skill directory for normal-test runs.
_SKILL_NAME = "testpilot-normal-test"


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def _git_run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    """Run a git command and return the CompletedProcess result.

    Returns a sentinel result with returncode=127 and empty stdout/stderr if
    the git executable is not found, so callers never see a FileNotFoundError.
    """
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            **kwargs,
        )
    except FileNotFoundError:
        return subprocess.CompletedProcess(args=cmd, returncode=127, stdout="", stderr="")


def _source_checkout_dir() -> Path:
    """Return the checkout directory used for source-ref-aware git metadata."""
    module_root = Path(__file__).resolve().parents[2]
    if (module_root / ".git").exists():
        return module_root

    managed_src = _get_managed_src()
    if (managed_src / ".git").exists():
        return managed_src

    return module_root


def _source_ref_label() -> str:
    """Return a source-ref label '<ref>@<short-sha>' for the current checkout."""
    git_kwargs = {"cwd": str(_source_checkout_dir())}
    sha_result = _git_run(["git", "rev-parse", "--short", "HEAD"], **git_kwargs)
    short_sha = sha_result.stdout.strip() if sha_result.returncode == 0 else "unknown"

    # Prefer symbolic branch ref
    sym_result = _git_run(["git", "symbolic-ref", "--short", "HEAD"], **git_kwargs)
    if sym_result.returncode == 0:
        ref = sym_result.stdout.strip()
        return f"{ref}@{short_sha}"

    # Fall back to exact tag name
    tag_result = _git_run(["git", "describe", "--tags", "--exact-match", "HEAD"], **git_kwargs)
    if tag_result.returncode == 0:
        ref = tag_result.stdout.strip()
        return f"{ref}@{short_sha}"

    # Detached HEAD
    return f"commit@{short_sha}"


def _version_string() -> str:
    """Return the full version string including source ref."""
    return f"TestPilot {__version__} ({_source_ref_label()})"


# ---------------------------------------------------------------------------
# Pre-dispatch helpers: --update and --verify-install
# ---------------------------------------------------------------------------


def _get_skills_root() -> Path:
    """Return the agents skills directory, respecting TESTPILOT_SKILLS_DIR env var."""
    return Path(
        os.environ.get(
            "TESTPILOT_SKILLS_DIR",
            str(Path.home() / ".agents" / "skills"),
        )
    )


def _get_managed_src() -> Path:
    """Return the managed checkout source path, respecting TESTPILOT_HOME env var."""
    testpilot_home = os.environ.get(
        "TESTPILOT_HOME",
        str(Path.home() / ".local" / "share" / "testpilot"),
    )
    return Path(testpilot_home) / "src"


def _get_managed_venv() -> Path:
    """Return the managed virtualenv path, respecting TESTPILOT_HOME env var."""
    testpilot_home = os.environ.get(
        "TESTPILOT_HOME",
        str(Path.home() / ".local" / "share" / "testpilot"),
    )
    return Path(testpilot_home) / ".venv"


def _get_wrapper_path() -> Path:
    """Return the installed wrapper path, respecting TESTPILOT_BIN_DIR env var."""
    bin_dir = os.environ.get(
        "TESTPILOT_BIN_DIR",
        str(Path.home() / ".local" / "bin"),
    )
    return Path(bin_dir) / "testpilot"


# ---------------------------------------------------------------------------
# Install-verification helpers (Task 2.4)
# ---------------------------------------------------------------------------


def _check_managed_checkout(managed_src: Path) -> tuple[bool, str]:
    """Report whether managed checkout exists (informational, not a hard failure)."""
    if managed_src.exists():
        return True, f"OK checkout: {managed_src}"
    return True, f"WARN checkout not found (non-managed install or first-run): {managed_src}"


def _check_wrapper(wrapper_path: Path, managed_venv: Path, managed_src: Path) -> tuple[bool, str]:
    """Report whether wrapper exists and references the managed venv."""
    if not wrapper_path.exists():
        if managed_src.exists():
            return False, f"FAIL wrapper not found: {wrapper_path}"
        return True, f"WARN wrapper not found: {wrapper_path}"
    content = wrapper_path.read_text(errors="replace")
    expected_console_script = managed_venv / "bin" / "testpilot"
    if str(expected_console_script) in content:
        return True, f"OK wrapper: {wrapper_path}"
    if managed_src.exists():
        return False, f"FAIL wrapper does not reference managed venv {managed_venv}: {wrapper_path}"
    return True, f"WARN wrapper does not reference managed venv {managed_venv}: {wrapper_path}"


def _check_console_script(managed_venv: Path, managed_src: Path) -> tuple[bool, str]:
    """Report whether the console script exists inside the managed venv."""
    script = managed_venv / "bin" / "testpilot"
    if script.exists():
        return True, f"OK console_script: {script}"
    if managed_src.exists():
        return False, f"FAIL console_script not found: {script}"
    return True, f"WARN console_script not found: {script}"


def _check_serialwrap_available() -> tuple[bool, str]:
    """Report whether serialwrap is available, preferring the managed venv."""
    venv_sw = _get_managed_venv() / "bin" / "serialwrap"
    if venv_sw.exists():
        return True, f"OK serialwrap: {venv_sw}"
    path = shutil.which("serialwrap")
    if path:
        return True, f"OK serialwrap: {path}"
    return True, "WARN serialwrap not found in PATH"


def _check_skill_path(skills_root: Path, skill_name: str) -> tuple[bool, str]:
    """Check skill directory exists. Absence is a hard failure."""
    skill_path = skills_root / skill_name
    if skill_path.exists():
        return True, f"OK skill: {skill_path}"
    return False, f"MISSING skill: {skill_path}"


def _check_git_source(managed_src: Path) -> tuple[bool, str]:
    """Report git remote/ref/SHA for the managed checkout."""
    if not managed_src.exists():
        return True, "SKIP git_source (no managed checkout)"
    remote = _git_run(["git", "remote", "get-url", "origin"], cwd=str(managed_src))
    sha = _git_run(["git", "rev-parse", "--short", "HEAD"], cwd=str(managed_src))
    ref = _git_run(["git", "symbolic-ref", "--short", "HEAD"], cwd=str(managed_src))
    remote_url = remote.stdout.strip() if remote.returncode == 0 else "unknown"
    short_sha = sha.stdout.strip() if sha.returncode == 0 else "unknown"
    branch = ref.stdout.strip() if ref.returncode == 0 else "detached"
    return True, f"OK git_source: {remote_url} ({branch}@{short_sha})"


def _check_version_mirrors(managed_src: Path) -> tuple[bool, str]:
    """Check VERSION, pyproject.toml, and __init__.py version alignment.

    Only runs when managed checkout exists. Misalignment is a hard failure.
    """
    if not managed_src.exists():
        return True, "SKIP version_mirrors (no managed checkout)"

    versions: dict[str, str] = {}
    errors: list[str] = []

    version_file = managed_src / "VERSION"
    if version_file.exists():
        versions["VERSION"] = version_file.read_text(encoding="utf-8").strip()

    pyproject_file = managed_src / "pyproject.toml"
    if pyproject_file.exists():
        try:
            data = tomllib.loads(pyproject_file.read_text(encoding="utf-8"))
            project = data["project"]
            if "version" in project.get("dynamic", []):
                # Dynamic version is sourced from the hatch version path
                # (e.g. the VERSION file); mirror tests/test_version_metadata.py
                # and scripts/check_release_version.py rather than reading a
                # static project.version that does not exist.
                version_path = data["tool"]["hatch"]["version"]["path"]
                versions["pyproject.toml"] = (
                    (managed_src / version_path).read_text(encoding="utf-8").strip()
                )
            else:
                versions["pyproject.toml"] = project["version"]
        except (KeyError, tomllib.TOMLDecodeError, OSError) as exc:
            errors.append(f"pyproject.toml unreadable: {exc}")

    init_file = managed_src / "src" / "testpilot" / "__init__.py"
    if init_file.exists():
        m = re.search(
            r'__version__\s*=\s*["\']([^"\']+)',
            init_file.read_text(encoding="utf-8"),
        )
        if m:
            versions["__init__.py"] = m.group(1)

    if errors:
        return False, f"FAIL version_mirrors metadata errors: {errors}"
    if not versions:
        return True, "SKIP version_mirrors (no version files found in managed checkout)"

    unique = set(versions.values())
    if len(unique) > 1:
        return False, f"FAIL version_mirrors misaligned: {versions}"

    version = next(iter(unique))
    return True, f"OK version_mirrors: all at {version}"


def _check_plugin_assets(managed_src: Path) -> tuple[bool, str]:
    """Report whether plugin directories are discoverable in the managed checkout."""
    plugins_dir = managed_src / "plugins"
    if not plugins_dir.exists():
        return True, f"WARN plugin_assets: plugins/ not found at {plugins_dir}"
    plugins = sorted(p.name for p in plugins_dir.iterdir() if p.is_dir())
    if not plugins:
        return True, f"WARN plugin_assets: no plugin directories in {plugins_dir}"
    return True, f"OK plugin_assets: {', '.join(plugins)}"


class _ManagedPluginEntryPoint:
    def __init__(self, name: str, value: str) -> None:
        self.name = name
        self.value = value

    def load(self):
        module_name, sep, attr_name = self.value.partition(":")
        module_name = module_name.strip()
        attr_name = attr_name.strip()
        if not sep or not module_name or not attr_name:
            raise ImportError(
                f"invalid testpilot.plugins entry point value for {self.name}: {self.value!r}"
            )
        module = importlib.import_module(module_name)
        try:
            return getattr(module, attr_name)
        except AttributeError as exc:
            raise ImportError(
                f"{module_name!r} does not define entry-point attribute {attr_name!r}"
            ) from exc


def _managed_plugin_entry_points(managed_src: Path) -> list[object]:
    pyproject_file = managed_src / "pyproject.toml"
    if not pyproject_file.exists():
        return []
    try:
        pyproject_data = tomllib.loads(pyproject_file.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return []
    entry_points = (
        pyproject_data.get("project", {})
        .get("entry-points", {})
        .get("testpilot.plugins", {})
    )
    if not isinstance(entry_points, dict):
        return []
    return [
        _ManagedPluginEntryPoint(name=name.strip(), value=value.strip())
        for name, value in sorted(entry_points.items())
        if isinstance(name, str)
        and name.strip()
        and not name.startswith("_")
        and isinstance(value, str)
        and value.strip()
    ]


def _entry_point_module_prefixes(entry_point: object) -> tuple[str, ...]:
    module_name = str(getattr(entry_point, "value", "")).partition(":")[0].strip()
    if not module_name:
        return ()
    parts = module_name.split(".")
    return tuple(".".join(parts[:index]) for index in range(1, len(parts) + 1))


def _check_plugin_health(managed_src: Path) -> list[tuple[bool, str]]:
    """Collect install-health checks exposed by discovered plugins."""
    plugins_dir = managed_src / "plugins"
    if not plugins_dir.exists():
        return []

    entry_points = _managed_plugin_entry_points(managed_src)
    if not entry_points:
        return []

    checks: list[tuple[bool, str]] = []
    managed_src_entry = str(managed_src)
    added_managed_src = managed_src_entry not in sys.path
    if added_managed_src:
        sys.path.insert(0, managed_src_entry)
    try:
        importlib.invalidate_caches()
        try:
            loader = PluginLoader.from_entry_points(entry_points)
        except ValueError as exc:
            return [(False, f"FAIL plugin_health: {exc}")]

        entry_points_by_name = {entry_point.name: entry_point for entry_point in entry_points}
        for name in loader.discover():
            entry_point = entry_points_by_name.get(name)
            prefixes = _entry_point_module_prefixes(entry_point) if entry_point is not None else ()
            saved_modules = {
                loaded_name: module
                for loaded_name, module in list(sys.modules.items())
                if any(
                    loaded_name == prefix or loaded_name.startswith(f"{prefix}.")
                    for prefix in prefixes
                )
            }
            for loaded_name in saved_modules:
                sys.modules.pop(loaded_name, None)
            try:
                checks.extend(loader.load(name).verify_install())
            except Exception as exc:
                checks.append((True, f"WARN plugin_health {name}: {exc}"))
            finally:
                for loaded_name in list(sys.modules):
                    if (
                        any(
                            loaded_name == prefix or loaded_name.startswith(f"{prefix}.")
                            for prefix in prefixes
                        )
                    ):
                        sys.modules.pop(loaded_name, None)
                sys.modules.update(saved_modules)
    finally:
        if added_managed_src and managed_src_entry in sys.path:
            sys.path.remove(managed_src_entry)
        importlib.invalidate_caches()
    return checks


# ---------------------------------------------------------------------------
# Wheel-mode verify-install (Task 5)
# ---------------------------------------------------------------------------


def _verify_install_wheel_mode(probe: dict) -> list[tuple[bool, str]]:
    """Pure function: build (ok, message) rows from a probe dict.

    No IO — callers supply the probe dict (real or test fixture).
    Exit-code decision is left to the caller: nonzero iff any ok is False.
    """
    rows: list[tuple[bool, str]] = []

    # Core importability
    core_version = probe.get("core_version")
    if not core_version:
        rows.append((False, "FAIL core: testpilot-core not importable"))
    else:
        rows.append((True, f"OK core: testpilot-core {core_version}"))

    # Plugin entry points
    for plugin in probe.get("plugins", []):
        name = plugin.get("name", "<unknown>")
        version = plugin.get("version", "?")
        api = plugin.get("api", "?")
        if plugin.get("loads"):
            rows.append((True, f"OK plugin: {name} {version} (api {api})"))
        else:
            error = plugin.get("error", "unknown error")
            # Use the captured error TYPE in the message rather than always
            # claiming "api-incompatible"; only IncompatiblePluginError is an
            # actual API-version mismatch.
            if error == "IncompatiblePluginError":
                rows.append((False, f"FAIL plugin: {name} api-incompatible ({error})"))
            else:
                rows.append((False, f"FAIL plugin: {name} failed to load ({error})"))

    # serialwrap — absence is a WARN, not a failure
    if probe.get("serialwrap"):
        rows.append((True, "OK serialwrap on PATH"))
    else:
        rows.append((True, "WARN serialwrap not found on PATH"))

    # wrapper_ok — mismatch is a WARN
    if not probe.get("wrapper_ok", True):
        rows.append((True, "WARN wrapper does not resolve to managed venv"))

    # packaged skill — absence is a WARN
    if not probe.get("skill_packaged", True):
        rows.append((True, f"WARN packaged skill {_SKILL_NAME} missing"))

    # stray import — present is a WARN
    stray = probe.get("stray_import")
    if stray:
        rows.append((True, f"WARN testpilot importable outside managed venv: {stray}"))

    return rows


def _system_python_outside(venv_bin: Path) -> str | None:
    """Resolve a python interpreter that is NOT inside the managed venv.

    The stray-import probe must use a non-managed interpreter; using the managed
    venv's own python (``sys.executable``) always finds the managed testpilot and
    therefore can never detect a genuine stray install. Returns a path string, or
    None when no distinct interpreter can be found. Never raises.
    """
    try:
        venv_bin_resolved = Path(venv_bin).resolve()
    except Exception:
        venv_bin_resolved = Path(venv_bin)

    def _outside(candidate: str | None) -> str | None:
        if not candidate:
            return None
        try:
            p = Path(candidate).resolve()
            if not p.exists():
                return None
        except Exception:
            return None
        # Reject anything living directly under the managed venv bin.
        if p.parent == venv_bin_resolved or venv_bin_resolved in p.parents:
            return None
        return str(p)

    # Prefer a python on PATH that is outside the managed venv.
    for name in ("python3", "python"):
        try:
            found = shutil.which(name)
        except Exception:
            found = None
        result = _outside(found)
        if result:
            return result

    # Fall back to a well-known system interpreter if it is distinct.
    try:
        usr = Path("/usr/bin/python3")
        if usr.exists():
            result = _outside(str(usr))
            if result and Path(result).resolve() != Path(sys.executable).resolve():
                return result
    except Exception:
        pass

    return None


def _probe_wheel_install() -> dict:
    """Gather real installation data for wheel-mode verify-install.

    Returns a probe dict compatible with _verify_install_wheel_mode.
    Never raises; all errors are captured as sentinel values.
    """
    probe: dict = {}

    # --- core version ---
    try:
        probe["core_version"] = importlib.metadata.version("testpilot-core")
    except importlib.metadata.PackageNotFoundError:
        probe["core_version"] = None

    # --- plugins via entry points ---
    plugin_rows: list[dict] = []
    try:
        eps = list(importlib.metadata.entry_points(group="testpilot.plugins"))
    except Exception:
        eps = []

    for ep in eps:
        row: dict = {"name": ep.name}
        # plugin package version
        try:
            dist_name = ep.dist.name if getattr(ep, "dist", None) else ep.name
            row["version"] = importlib.metadata.version(dist_name)
        except Exception:
            row["version"] = "?"

        # attempt load
        try:
            loader = PluginLoader.from_entry_points([ep])
            plugin_obj = loader.load(ep.name)
            row["loads"] = True
            row["api"] = getattr(plugin_obj, "api_version", "?")
            row["error"] = None
        except Exception as exc:
            row["loads"] = False
            row["api"] = "?"
            row["error"] = type(exc).__name__

        plugin_rows.append(row)

    probe["plugins"] = plugin_rows

    # --- serialwrap ---
    serialwrap_bin = os.environ.get("SERIALWRAP_BIN")
    if serialwrap_bin:
        probe["serialwrap"] = bool(Path(serialwrap_bin).exists())
    else:
        probe["serialwrap"] = bool(shutil.which("serialwrap"))

    # --- wrapper_ok: does the testpilot wrapper resolve to a managed venv? ---
    try:
        wrapper_path = _get_wrapper_path()
        managed_venv = _get_managed_venv()
        if wrapper_path.exists():
            content = wrapper_path.read_text(errors="replace")
            probe["wrapper_ok"] = str(managed_venv) in content
        else:
            probe["wrapper_ok"] = True  # no wrapper in wheel mode is fine
    except Exception:
        probe["wrapper_ok"] = True

    # --- packaged skill ---
    try:
        skill_ref = importlib.resources.files("testpilot") / "_skills" / _SKILL_NAME
        probe["skill_packaged"] = skill_ref.is_file() or skill_ref.is_dir()
    except Exception:
        probe["skill_packaged"] = False

    # --- stray import: use a NON-managed interpreter to locate testpilot ---
    # Using sys.executable (the managed venv python) would always find the
    # managed testpilot, so stray_import could never fire. Resolve a python
    # outside the managed venv instead.
    probe["stray_import"] = None
    try:
        managed_pkg_dir = str(Path(__file__).resolve().parent)
        system_python = _system_python_outside(_get_managed_venv() / "bin")
        if system_python:
            result = subprocess.run(
                [system_python, "-c",
                 "import os, testpilot; print(os.path.dirname(testpilot.__file__))"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                found_path = result.stdout.strip()
                if found_path and Path(found_path).resolve() != Path(managed_pkg_dir).resolve():
                    probe["stray_import"] = found_path
    except Exception:
        pass

    return probe


def _handle_verify_install() -> None:
    """Handle --verify-install pre-dispatch: report deployment health."""
    managed_src = _get_managed_src()

    # ------------------------------------------------------------------
    # Wheel-mode: no managed src directory at all → use importlib.metadata probes
    # ------------------------------------------------------------------
    if not managed_src.exists():
        probe = _probe_wheel_install()
        rows = _verify_install_wheel_mode(probe)
        errors: list[str] = []
        for ok_flag, msg in rows:
            if not ok_flag:
                console.print(f"[bold red]{msg}[/bold red]")
                errors.append(msg)
            elif msg.startswith("WARN") or msg.startswith("SKIP"):
                console.print(f"[yellow]{msg}[/yellow]")
            else:
                console.print(f"[bold green]{msg}[/bold green]")
        if errors:
            raise SystemExit(1)
        console.print("[bold green]verify-install: all checks passed[/bold green]")
        return

    # ------------------------------------------------------------------
    # Checkout-mode: existing managed git checkout path (preserved)
    # ------------------------------------------------------------------
    managed_venv = _get_managed_venv()
    wrapper_path = _get_wrapper_path()
    skills_root = _get_skills_root()

    checks = [
        _check_managed_checkout(managed_src),
        _check_wrapper(wrapper_path, managed_venv, managed_src),
        _check_console_script(managed_venv, managed_src),
        _check_serialwrap_available(),
        _check_skill_path(skills_root, _SKILL_NAME),
        _check_git_source(managed_src),
        _check_version_mirrors(managed_src),
        _check_plugin_assets(managed_src),
    ]
    checks.extend(_check_plugin_health(managed_src))

    checkout_errors: list[str] = []
    for ok_flag, msg in checks:
        if not ok_flag:
            console.print(f"[bold red]{msg}[/bold red]")
            checkout_errors.append(msg)
        elif msg.startswith("WARN") or msg.startswith("SKIP"):
            console.print(f"[yellow]{msg}[/yellow]")
        else:
            console.print(f"[bold green]{msg}[/bold green]")

    if checkout_errors:
        raise SystemExit(1)

    console.print("[bold green]verify-install: all checks passed[/bold green]")


@dataclass
class ReconcilePlan:
    to_install: set[str]
    to_uninstall: set[str]


def _reconcile_plan(installed: set[str], manifest: set[str]) -> ReconcilePlan:
    return ReconcilePlan(to_install=manifest - installed, to_uninstall=installed - manifest)


def _probe_installed_plugins() -> set[str]:
    """Return the set of plugin names currently installed in the managed environment."""
    try:
        eps = importlib.metadata.entry_points(group="testpilot.plugins")
        return {ep.name for ep in eps}
    except Exception:
        return set()


def _packaged_manifest_path() -> Path | None:
    """Locate the authoritative install-manifest.yaml.

    Prefers the copy shipped inside the wheel (``testpilot/_install/``) so that a
    real (non-checkout) install can always resolve it; falls back to repo-root
    copies for dev checkouts. Returns None when none can be found — callers MUST
    treat None as "unresolvable", never as "no plugins".
    """
    try:
        packaged = importlib.resources.files("testpilot") / "_install" / "install-manifest.yaml"
        if packaged.is_file():
            return Path(str(packaged))
    except Exception:
        pass
    here = Path(__file__).parent
    candidates = [
        here.parent.parent / "install-manifest.yaml",  # repo root from src/testpilot/
        here.parent.parent.parent / "install-manifest.yaml",  # one more level up
        Path.cwd() / "install-manifest.yaml",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _packaged_installer_path() -> Path | None:
    """Locate the authoritative install.sh.

    Prefers the copy shipped inside the wheel (``testpilot/_install/``); falls
    back to ``scripts/install.sh`` for dev checkouts. Returns None when neither
    can be found.
    """
    try:
        packaged = importlib.resources.files("testpilot") / "_install" / "install.sh"
        if packaged.is_file():
            return Path(str(packaged))
    except Exception:
        pass
    here = Path(__file__).parent
    candidates = [
        here.parent.parent / "scripts" / "install.sh",  # repo root from src/testpilot/
        here.parent.parent.parent / "scripts" / "install.sh",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _resolve_manifest(ref):
    """Load the authoritative install-manifest.yaml as a manifest object.

    Returns an ``InstallManifest`` or ``None`` when the manifest cannot be
    resolved. It must NEVER return an empty set/manifest that looks like "no
    plugins" — an empty set would make the reconcile loop uninstall every
    installed plugin (the C1 destructive bug).

    NOTE: Online ref-fetch (fetching a specific git ref from the remote) is
    performed by scripts/install.sh, not here. ``ref`` is accepted for signature
    stability and forwarded to the installer by ``_handle_update``.
    """
    path = _packaged_manifest_path()
    if path is None:
        return None
    from testpilot.install.manifest import load_manifest

    try:
        return load_manifest(path)
    except Exception:
        return None


def _default_pip_runner(args: list[str]) -> int:
    """Run pip in the managed venv."""
    venv = _get_managed_venv()
    pip = venv / "bin" / "pip"
    result = subprocess.run([str(pip)] + args, capture_output=False)
    return result.returncode


def _default_installer_runner(env: dict) -> int:
    """Invoke the packaged install.sh with the given environment overlaid."""
    installer = _packaged_installer_path()
    if installer is None:
        print("Installer script not found in package or checkout.", file=sys.stderr)
        return 1
    full_env = dict(os.environ)
    full_env.update({k: v for k, v in env.items() if v is not None})
    result = subprocess.run(["bash", str(installer)], env=full_env)
    return result.returncode


def _run_installer(env: dict, *, runner=None) -> int:
    """Injectable seam: run the authoritative installer with ``env`` overlaid.

    Tests patch ``runner``; the default delegates to ``_default_installer_runner``
    which executes the packaged ``install.sh``.
    """
    if runner is None:
        runner = _default_installer_runner
    return runner(env)


def _last_good_path() -> Path:
    """Return the rollback snapshot path under the managed home dir.

    Derived from the same TESTPILOT_HOME base as ``_get_managed_venv()`` so the
    snapshot always sits next to the venv it describes.
    """
    return _get_managed_venv().parent / ".last-good.txt"


def _snapshot_environment(managed_venv: Path, last_good: Path) -> None:
    """Freeze the managed venv to ``last_good`` for rollback. Best-effort."""
    try:
        venv_python = managed_venv / "bin" / "python"
        freeze_result = subprocess.run(
            [str(venv_python), "-m", "pip", "freeze"],
            capture_output=True,
            text=True,
        )
        if freeze_result.returncode == 0:
            last_good.parent.mkdir(parents=True, exist_ok=True)
            last_good.write_text(freeze_result.stdout)
    except Exception as e:
        print(f"Warning: could not snapshot environment: {e}", file=sys.stderr)


def _verify_after_update() -> bool:
    """Run wheel-mode verify-install as a post-update gate. True iff healthy."""
    probe = _probe_wheel_install()
    rows = _verify_install_wheel_mode(probe)
    return all(ok for ok, _ in rows)


def _handle_update(ref, *, runner=None, installer=None, verifier=None) -> int:
    """Handle --update pre-dispatch: update testpilot in-place using the wheel model.

    Wheel-model flow (no git checkout):
    1. Require the managed venv to exist.
    2. Resolve the authoritative manifest. If it cannot be resolved → exit
       nonzero WITHOUT touching the installation (never uninstall-all).
    3. Snapshot the current environment to .last-good.txt for rollback.
    4. Re-(install) the pinned set by delegating to the packaged install.sh
       (passing TESTPILOT_REF and TESTPILOT_MANIFEST), NOT `pip install <name>`.
    5. Reconcile: uninstall plugins dropped from a non-empty manifest.
    6. Gate on wheel-mode verify-install; on failure restore from .last-good.txt
       and exit nonzero.
    """
    if runner is None:
        runner = _default_pip_runner
    if verifier is None:
        verifier = _verify_after_update

    managed_venv = _get_managed_venv()

    if not managed_venv.exists():
        print(
            "No managed testpilot installation found at "
            f"{managed_venv}.\n"
            "Run the installer first: curl -fsSL <url> | bash",
            file=sys.stderr,
        )
        sys.exit(1)

    # Resolve the manifest FIRST. An unresolvable manifest must never lead to
    # uninstalling every installed plugin — bail out untouched.
    manifest = _resolve_manifest(ref)
    if manifest is None:
        print(
            "Could not resolve the install manifest; refusing to modify the "
            "installation. No plugins were changed.",
            file=sys.stderr,
        )
        sys.exit(1)

    manifest_path = _packaged_manifest_path()
    manifest_plugins = {p.name for p in manifest.plugins}

    # Snapshot current environment for rollback.
    last_good = _last_good_path()
    _snapshot_environment(managed_venv, last_good)

    # Probe installed plugins and compute reconcile plan.
    installed_plugins = _probe_installed_plugins()
    plan = _reconcile_plan(installed=installed_plugins, manifest=manifest_plugins)

    # Re-(install) the pinned set via the authoritative installer — NOT pip
    # bare-name (which would hit public PyPI for private plugins).
    installer_env = {
        "TESTPILOT_REF": ref or "",
        "TESTPILOT_MANIFEST": str(manifest_path) if manifest_path else "",
    }
    rc = _run_installer(installer_env, runner=installer)
    if rc != 0:
        print("Update failed: installer returned nonzero.", file=sys.stderr)
        sys.exit(1)

    # Uninstall dropped plugins (only when the manifest is non-empty).
    if manifest_plugins:
        for plugin_name in plan.to_uninstall:
            rc = runner(["uninstall", "-y", plugin_name])
            if rc != 0:
                print(f"Warning: failed to uninstall {plugin_name}", file=sys.stderr)

    # Post-update gate: verify the install; roll back on failure.
    if not verifier():
        print(
            "Post-update verify-install failed; rolling back from snapshot.",
            file=sys.stderr,
        )
        if last_good.exists():
            runner(["install", "-r", str(last_good)])
        sys.exit(1)

    print("Update complete.")
    return 0


def _detect_legacy_installs(probe: dict) -> list[str]:
    """Pure function: map detected legacy install shapes to action keys.

    Args:
        probe: dict with keys:
            - user_site_testpilot: bool - testpilot dist-info found in user site-packages
            - pipx_testpilot: bool - testpilot found in pipx list
            - legacy_src: bool - ~/.local/share/testpilot/src exists

    Returns:
        list of action keys: uninstall_user_site, uninstall_pipx, remove_legacy_src
    """
    actions = []
    if probe.get("user_site_testpilot"):
        actions.append("uninstall_user_site")
    if probe.get("pipx_testpilot"):
        actions.append("uninstall_pipx")
    if probe.get("legacy_src"):
        actions.append("remove_legacy_src")
    return actions


def _probe_legacy_installs() -> dict:
    """Best-effort probe of legacy install shapes. Never raises.

    Returns a dict suitable for passing to _detect_legacy_installs().
    """
    result = {
        "user_site_testpilot": False,
        "pipx_testpilot": False,
        "legacy_src": False,
    }

    # Check user site-packages for testpilot dist-info
    try:
        import site
        user_site = site.getusersitepackages()
        if user_site:
            user_site_path = Path(user_site)
            if user_site_path.exists():
                for entry in user_site_path.iterdir():
                    name = entry.name.lower()
                    if (name.startswith("testpilot") or name.startswith("testpilot_core")) and name.endswith(".dist-info"):
                        result["user_site_testpilot"] = True
                        break
    except Exception:
        pass

    # Check pipx
    try:
        proc = subprocess.run(
            ["pipx", "list", "--short"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0 and "testpilot" in proc.stdout.lower():
            result["pipx_testpilot"] = True
    except Exception:
        pass

    # Check legacy src checkout — use _get_managed_src() (TESTPILOT_HOME-aware)
    # so detection targets the same path that removal (_default_legacy_src_remover
    # via _get_managed_src) would delete.
    try:
        legacy_src = _get_managed_src()
        result["legacy_src"] = legacy_src.exists()
    except Exception:
        pass

    return result


def _default_migration_runner(cmd: list[str]) -> int:
    """Best-effort subprocess runner for migration actions. Never raises."""
    try:
        return subprocess.run(cmd).returncode
    except Exception as exc:
        print(f"Warning: migration command failed ({cmd[0]}): {exc}", file=sys.stderr)
        return 1


def _default_legacy_src_remover(path: Path) -> None:
    """Remove the legacy src checkout only (never the managed venv)."""
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def _handle_install_migrate(*, probe=None, runner=None, remover=None) -> int:
    """Detect legacy install shapes and migrate them to the wheel model.

    Conservative + best-effort. Actions:
      - uninstall_user_site: `python -m pip uninstall -y testpilot testpilot-core`
        using a NON-managed interpreter so it targets the user/system site.
      - uninstall_pipx: `pipx uninstall testpilot` / `testpilot-core`.
      - remove_legacy_src: remove ~/.local/share/testpilot/src (NOT the venv).
    After acting, WARN if `testpilot` still resolves outside the managed venv.
    """
    if probe is None:
        probe = _probe_legacy_installs()
    if runner is None:
        runner = _default_migration_runner
    if remover is None:
        remover = _default_legacy_src_remover

    actions = _detect_legacy_installs(probe)
    if not actions:
        print("No legacy testpilot installs detected; nothing to migrate.")
        return 0

    venv_bin = _get_managed_venv() / "bin"
    for action in actions:
        if action == "uninstall_user_site":
            system_python = _system_python_outside(venv_bin) or "python3"
            runner([system_python, "-m", "pip", "uninstall", "-y", "testpilot", "testpilot-core"])
        elif action == "uninstall_pipx":
            runner(["pipx", "uninstall", "testpilot"])
            runner(["pipx", "uninstall", "testpilot-core"])
        elif action == "remove_legacy_src":
            remover(_get_managed_src())

    # Warn if testpilot still resolves outside the managed venv after migration.
    system_python = _system_python_outside(venv_bin)
    if system_python:
        try:
            result = subprocess.run(
                [system_python, "-c",
                 "import os, testpilot; print(os.path.dirname(testpilot.__file__))"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                print(
                    "WARN: testpilot still importable outside the managed venv: "
                    f"{result.stdout.strip()}",
                    file=sys.stderr,
                )
        except Exception:
            pass

    print("Legacy migration complete.")
    return 0


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


class HelpfulRunCommand(click.Command):
    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        try:
            return super().parse_args(ctx, args)
        except click.MissingParameter as exc:
            if getattr(exc.param, "name", None) == "plugin_name":
                raise click.UsageError(
                    "Missing required argument PLUGIN_NAME.\n\n"
                    f"{run_command_guidance()}",
                    ctx=ctx,
                ) from exc
            raise


def _print_version(ctx: click.Context, _param: click.Parameter, value: bool) -> None:
    """Click callback: print source-ref-aware version string and exit."""
    if not value or ctx.resilient_parsing:
        return
    click.echo(_version_string())
    ctx.exit()


@click.group(invoke_without_command=True)
@click.option(
    "--version",
    is_eager=True,
    expose_value=False,
    is_flag=True,
    callback=_print_version,
    help="Show version and exit.",
)
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging.")
@click.option(
    "--root",
    type=click.Path(exists=True, file_okay=False),
    default=None,
    help="Project root directory.",
)
@click.option(
    "--azure",
    is_flag=True,
    default=False,
    help="Use Azure OpenAI API. Prompts for endpoint, key, and model interactively.",
)
@click.option(
    "--update",
    "update_ref",
    default=None,
    is_eager=True,
    expose_value=True,
    metavar="REF",
    help=(
        "Reinstall and reconcile the managed wheel install from its pinned "
        "manifest, then exit. REF is accepted but cross-version update is not "
        "yet implemented; the currently-pinned set is reinstalled."
    ),
    is_flag=False,
    flag_value="main",
)
@click.option(
    "--verify-install",
    "verify_install",
    is_flag=True,
    default=False,
    is_eager=True,
    expose_value=True,
    help="Report managed install health and exit.",
)
@click.pass_context
def main(
    ctx: click.Context,
    verbose: bool,
    root: str | None,
    azure: bool,
    update_ref: str | None,
    verify_install: bool,
) -> None:
    """TestPilot — plugin-based test automation for embedded devices."""
    # Pre-dispatch: --update and --verify-install run before normal routing.
    if update_ref is not None:
        if update_ref not in (None, "main"):
            click.echo(
                f"note: --update reinstalls the currently-pinned manifest set; "
                f"targeting REF {update_ref!r} for a cross-version update is not "
                f"yet implemented.",
                err=True,
            )
        _handle_update(update_ref)
        ctx.exit(0)
        return
    if verify_install:
        _handle_verify_install()
        ctx.exit(0)
        return

    _setup_logging(verbose)
    ctx.ensure_object(dict)
    ctx.obj["root"] = Path(root) if root else Path(__file__).resolve().parents[2]
    ctx.obj["provider_notice"] = None

    # When invoked without a subcommand (and no pre-dispatch flags), show help.
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())
        ctx.exit(0)
        return

    # --- Authentication: Azure BYOK → GitHub OAuth fallback ---
    provider_config: dict | None = None
    if azure:
        provider_config = setup_azure_auth()
        if provider_config is None:
            console.print(
                "[bold red]Azure authentication failed.[/bold red] "
                "Cannot proceed. Please check your credentials and network.",
            )
            raise SystemExit(1)
        ctx.obj["provider_notice"] = "azure_interactive"
    else:
        # Check if COPILOT_PROVIDER_* env vars are already set
        provider_config = resolve_provider_config()
        if provider_config:
            ctx.obj["provider_notice"] = "azure_env"
        # else: fall through to GitHub OAuth (handled by Copilot SDK)

    ctx.obj["provider_config"] = provider_config


@main.command("list-plugins")
@click.pass_context
def list_plugins(ctx: click.Context) -> None:
    """List available test plugins."""
    orch = get_orchestrator(ctx)
    names = orch.discover_plugins()
    if not names:
        console.print("[yellow]No plugins found.[/yellow]")
        return
    table = Table(title="Available Plugins")
    table.add_column("Name", style="cyan")
    table.add_column("Status", style="green")
    for name in names:
        try:
            plugin = orch.loader.load(name)
            cases = plugin.discover_cases()
            table.add_row(name, f"v{plugin.version} ({len(cases)} cases)")
        except Exception as e:
            table.add_row(name, f"[red]error: {e}[/red]")
    console.print(table)


@main.command("list-cases")
@click.argument("plugin_name")
@click.pass_context
def list_cases(ctx: click.Context, plugin_name: str) -> None:
    """List test cases for a plugin."""
    orch = get_orchestrator(ctx, plugin_name)
    cases = orch.list_cases(plugin_name)
    if not cases:
        console.print(f"[yellow]No cases found for plugin '{plugin_name}'.[/yellow]")
        return
    table = Table(title=f"Cases: {plugin_name}")
    table.add_column("ID", style="cyan")
    table.add_column("Name")
    table.add_column("Steps", justify="right")
    for case in cases:
        table.add_row(
            case.get("id", "?"),
            case.get("name", "?"),
            str(len(case.get("steps", []))),
        )
    console.print(table)

@main.command("run", cls=HelpfulRunCommand)
@click.argument("plugin_name")
@click.option("--case", "case_ids", multiple=True, help="Specific case IDs to run.")
@click.option(
    "--dut-fw-ver",
    default="DUT-FW-VER",
    show_default=True,
    help="DUT firmware version used in report filename.",
)
@click.pass_context
def run_tests(
    ctx: click.Context,
    plugin_name: str,
    case_ids: tuple[str, ...],
    dut_fw_ver: str,
) -> None:
    """Run tests for a plugin."""
    run_plugin_cases(ctx, plugin_name, case_ids, dut_fw_ver)


def _default_plugins_dir() -> Path:
    """Return the install-time plugin directory for eager CLI registration."""
    return Path(__file__).resolve().parents[2] / "plugins"


def _register_plugins(root: click.Group) -> None:
    """Register installed plugin CLI commands without letting one plugin break the CLI."""
    from testpilot.core.plugin_loader import PluginLoader

    plugins_dir = _default_plugins_dir()
    loader = PluginLoader(plugins_dir)
    registrar = CliRegistrar(root)
    repo_root = str(plugins_dir.parent)
    if repo_root not in sys.path:
        sys.path.append(repo_root)
    for name in loader.discover():
        commands_before = dict(root.commands)
        try:
            loader.load(name).register_cli(registrar)
            replaced = sorted(
                command_name
                for command_name, command in commands_before.items()
                if root.commands.get(command_name) is not command
            )
            if replaced:
                raise RuntimeError(
                    "plugin attempted to replace existing command(s): "
                    f"{', '.join(replaced)}"
                )
        except Exception as exc:
            root.commands.clear()
            root.commands.update(commands_before)
            click.echo(f"WARN: skipped plugin '{name}' CLI: {exc}", err=True)


@main.command("install-doctor")
@click.option(
    "--manifest",
    "manifest_path",
    default=None,
    type=click.Path(),
    help="Path to install-manifest.yaml (default: install-manifest.yaml in CWD).",
)
def install_doctor(manifest_path: str | None) -> None:
    """Check manifest plugin API-compat against installed core SDK version."""
    from testpilot.api import API_VERSION
    from testpilot.install.manifest import load_manifest
    from testpilot.install.compat import manifest_compat_report

    path = Path(manifest_path) if manifest_path else Path.cwd() / "install-manifest.yaml"
    m = load_manifest(path)
    pairs = [(p.name, p.api_version) for p in m.plugins]
    rep = manifest_compat_report(API_VERSION, pairs)
    for failure in rep.failures:
        click.echo(failure)
    if not rep.ok:
        raise SystemExit(1)
    click.echo("manifest compatible")


@main.command("install-migrate", hidden=True)
def install_migrate() -> None:
    """(hidden) Migrate a legacy user-site / pipx / git-checkout install to the wheel model."""
    raise SystemExit(_handle_install_migrate())


# Plugin CLI commands are install-time registrations from this checkout.
# Runtime --root selects project data, not the command registration source.
_register_plugins(main)


if __name__ == "__main__":
    main()
