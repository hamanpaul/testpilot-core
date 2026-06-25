"""TestPilot CLI — command-line entry point."""

from __future__ import annotations

import importlib
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


def _handle_verify_install() -> None:
    """Handle --verify-install pre-dispatch: report deployment health."""
    managed_src = _get_managed_src()
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

    errors: list[str] = []
    for ok_flag, msg in checks:
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


def _handle_update(ref: str | None) -> None:
    """Handle --update pre-dispatch: update managed checkout to ref (default: main)."""
    target_ref = ref or "main"
    managed_src = _get_managed_src()

    if not (managed_src / ".git").exists():
        console.print(
            "[bold red]Managed checkout not found.[/bold red]\n"
            "Run the managed installer before using testpilot --update.\n"
            f"  path: {managed_src}",
        )
        raise SystemExit(1)

    # Only check for dirty state when the managed checkout actually exists.
    # Skipping this guard on a nonexistent path would run git status against
    # the developer's own working tree and produce false positives.
    status = _git_run(
        ["git", "status", "--porcelain"],
        cwd=str(managed_src),
    )
    if status.returncode != 0:
        detail = status.stderr.strip() or "git status failed"
        console.print(
            "[bold red]Cannot inspect managed checkout state.[/bold red]\n"
            f"{detail}\n"
            f"  path: {managed_src}",
        )
        raise SystemExit(status.returncode or 1)
    if status.stdout.strip():
        console.print(
            "[bold red]Managed checkout has uncommitted changes.[/bold red]\n"
            "Please commit, stash, or resolve local edits before updating.\n"
            f"  path: {managed_src}",
        )
        raise SystemExit(1)

    installer = managed_src / "scripts" / "install.sh"
    if not installer.exists():
        console.print(
            "[bold red]Managed installer not found.[/bold red]\n"
            f"Expected scripts/install.sh under managed checkout: {installer}",
        )
        raise SystemExit(1)

    console.print(f"[bold]Updating TestPilot to ref:[/bold] {target_ref}")

    env = os.environ.copy()
    env.update(
        {
            "TESTPILOT_REF": target_ref,
            "TESTPILOT_HOME": str(managed_src.parent),
            "TESTPILOT_BIN_DIR": str(_get_wrapper_path().parent),
            "TESTPILOT_SKILLS_DIR": str(_get_skills_root()),
        }
    )

    with tempfile.TemporaryDirectory(prefix="testpilot-update-") as tmp_dir:
        installer_copy = Path(tmp_dir) / "install.sh"
        shutil.copy2(installer, installer_copy)
        result = subprocess.run(
            ["bash", str(installer_copy)],
            cwd=str(managed_src),
            env=env,
            text=True,
        )

    if result.returncode != 0:
        console.print(f"[bold red]Update failed with exit code {result.returncode}[/bold red]")
        raise SystemExit(result.returncode)

    console.print("[bold green]Update complete[/bold green]")


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


# Plugin CLI commands are install-time registrations from this checkout.
# Runtime --root selects project data, not the command registration source.
_register_plugins(main)


if __name__ == "__main__":
    main()
