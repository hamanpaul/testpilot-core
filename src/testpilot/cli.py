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
            versions["pyproject.toml"] = data["project"]["version"]
        except (KeyError, tomllib.TOMLDecodeError) as exc:
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
            rows.append((False, f"FAIL plugin: {name} api-incompatible ({error})"))

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

    # --- stray import: try system python to locate testpilot ---
    probe["stray_import"] = None
    try:
        # Use sys.executable (the venv python); compare its testpilot path to this file.
        managed_pkg_dir = str(Path(__file__).resolve().parent)
        result = subprocess.run(
            [sys.executable, "-c",
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


def _resolve_manifest(ref) -> set[str]:
    """Load the bundled install-manifest.yaml and return the set of plugin names.

    NOTE: Online ref-fetch (fetching a specific git ref from the remote) is performed
    by scripts/install.sh, not here. This function loads the local bundled manifest only.
    """
    here = Path(__file__).parent
    candidates = [
        here.parent.parent / "install-manifest.yaml",  # repo root from src/testpilot/
        here.parent.parent.parent / "install-manifest.yaml",  # one more level up
        Path.cwd() / "install-manifest.yaml",
    ]
    for candidate in candidates:
        if candidate.exists():
            from testpilot.install.manifest import load_manifest
            m = load_manifest(candidate)
            return {p.name for p in m.plugins}
    return set()


def _default_pip_runner(args: list[str]) -> int:
    """Run pip in the managed venv."""
    venv = _get_managed_venv()
    pip = venv / "bin" / "pip"
    result = subprocess.run([str(pip)] + args, capture_output=False)
    return result.returncode


def _handle_update(ref, *, runner=None) -> int:
    """Handle --update pre-dispatch: update testpilot in-place using the wheel model.

    Instead of requiring a git checkout at ~/.local/share/testpilot/src/.git,
    this function:
    1. Checks that the managed venv exists
    2. Snapshots the current environment to .last-good.txt
    3. Resolves the manifest (plugins to install)
    4. Reconciles installed plugins vs manifest
    5. Installs/uninstalls as needed
    """
    if runner is None:
        runner = _default_pip_runner

    managed_share = Path.home() / ".local" / "share" / "testpilot"
    managed_venv = _get_managed_venv()

    if not managed_venv.exists():
        print(
            "No managed testpilot installation found at "
            f"{managed_venv}.\n"
            "Run the installer first: curl -fsSL <url> | bash",
            file=sys.stderr,
        )
        sys.exit(1)

    # Snapshot current environment for rollback
    last_good = managed_share / ".last-good.txt"
    try:
        venv_python = managed_venv / "bin" / "python"
        freeze_result = subprocess.run(
            [str(venv_python), "-m", "pip", "freeze"],
            capture_output=True,
            text=True,
        )
        if freeze_result.returncode == 0:
            last_good.write_text(freeze_result.stdout)
    except Exception as e:
        print(f"Warning: could not snapshot environment: {e}", file=sys.stderr)

    # Resolve the manifest
    manifest_plugins = _resolve_manifest(ref)

    # Probe installed plugins
    installed_plugins = _probe_installed_plugins()

    # Compute reconcile plan
    plan = _reconcile_plan(installed=installed_plugins, manifest=manifest_plugins)

    # Apply: reinstall all manifest plugins
    for plugin_name in manifest_plugins:
        rc = runner(["install", "--upgrade", plugin_name])
        if rc != 0:
            print(f"Warning: failed to install {plugin_name}", file=sys.stderr)

    # Uninstall dropped plugins
    for plugin_name in plan.to_uninstall:
        rc = runner(["uninstall", "-y", plugin_name])
        if rc != 0:
            print(f"Warning: failed to uninstall {plugin_name}", file=sys.stderr)

    print("Update complete.")
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
    help="Update managed checkout to REF (default: main) and exit.",
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


# Plugin CLI commands are install-time registrations from this checkout.
# Runtime --root selects project data, not the command registration source.
_register_plugins(main)


if __name__ == "__main__":
    main()
