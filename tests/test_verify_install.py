"""Tests for expanded _handle_verify_install checks (Task 2.3).

Focuses on:
- Version mirror mismatch → non-zero exit
- Missing skill → non-zero exit (additional variants)
- Healthy state with managed checkout → zero exit
- Managed checkout status reporting
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
import sys
import textwrap
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from testpilot.cli import _handle_verify_install


class _FakeEntryPoint:
    def __init__(
        self,
        name: str,
        value: str,
        *,
        dist_name: str = "testpilot",
        dist_root: Path | None = None,
        dist_files: list[Path] | None = None,
        direct_url: str | None = None,
    ) -> None:
        self.name = name
        self.value = value
        self.dist = SimpleNamespace(name=dist_name, metadata={"Name": dist_name})
        self.dist.files = dist_files
        self.dist.read_text = lambda filename: direct_url if filename == "direct_url.json" else None
        if dist_root is not None:
            self.dist.locate_file = lambda path: dist_root / path if str(path) else dist_root

    def load(self):
        module_name, _, attr_name = self.value.partition(":")
        module = importlib.import_module(module_name)
        return getattr(module, attr_name)


def _write_install_health_plugin(
    tmp_path: Path,
    module_name: str,
    *,
    ok: object,
    message: str,
    raise_error: str | None = None,
) -> _FakeEntryPoint:
    health_statement = (
        f"raise RuntimeError({raise_error!r})"
        if raise_error is not None
        else f"return [({ok!r}, {message!r})]"
    )
    module_path = tmp_path / f"{module_name}.py"
    module_path.write_text(
        textwrap.dedent(
            f"""
            from pathlib import Path
            from testpilot.core.plugin_base import PluginBase

            class Plugin(PluginBase):
                api_version = "1.1"

                @property
                def name(self):
                    return "health_fixture"

                @property
                def cases_dir(self):
                    return Path(__file__).parent

                def discover_cases(self):
                    return []

                def execute_step(self, case, step, topology):
                    return {{}}

                def evaluate(self, case, results):
                    return True

                def verify_install(self):
                    {health_statement}
            """
        ).lstrip(),
        encoding="utf-8",
    )
    return _FakeEntryPoint(
        "health_fixture",
        f"{module_name}:Plugin",
        dist_name="health-fixture",
        dist_root=tmp_path,
        dist_files=[Path(f"{module_name}.py")],
    )


def _healthy_wheel_probe() -> dict:
    return {
        "core_version": "0.3.9",
        "plugins": [],
        "serialwrap": True,
        "wrapper_ok": True,
        "skill_packaged": True,
        "stray_import": None,
    }


# ---------------------------------------------------------------------------
# Version mirror checks
# ---------------------------------------------------------------------------


class TestVersionMirrorCheck:
    """_handle_verify_install must exit non-zero when version files are misaligned."""

    def test_version_mismatch_fails_verify(self, tmp_path: Path) -> None:
        """VERSION differs from pyproject.toml → verify-install exits non-zero."""
        managed_src = tmp_path / "managed_src"
        managed_src.mkdir()

        (managed_src / "VERSION").write_text("0.1.0\n")
        (managed_src / "pyproject.toml").write_text(
            '[project]\nname = "testpilot"\nversion = "0.2.0"\n'
        )
        init_dir = managed_src / "src" / "testpilot"
        init_dir.mkdir(parents=True)
        (init_dir / "__init__.py").write_text('__version__ = "0.2.0"\n')

        skill_dir = tmp_path / "skills" / "testpilot-normal-test"
        skill_dir.mkdir(parents=True)

        with patch("testpilot.cli._get_managed_src", return_value=managed_src):
            with patch("testpilot.cli._get_skills_root", return_value=tmp_path / "skills"):
                with pytest.raises(SystemExit) as exc_info:
                    _handle_verify_install()
        assert exc_info.value.code != 0

    def test_malformed_pyproject_fails_verify(self, tmp_path: Path) -> None:
        """Unreadable pyproject version metadata is a hard verify-install failure."""
        managed_src = tmp_path / "managed_src"
        managed_src.mkdir()

        (managed_src / "VERSION").write_text("0.2.0\n")
        (managed_src / "pyproject.toml").write_text("[project\nversion = ")
        init_dir = managed_src / "src" / "testpilot"
        init_dir.mkdir(parents=True)
        (init_dir / "__init__.py").write_text('__version__ = "0.2.0"\n')

        skill_dir = tmp_path / "skills" / "testpilot-normal-test"
        skill_dir.mkdir(parents=True)
        managed_venv = tmp_path / ".venv"
        (managed_venv / "bin").mkdir(parents=True)
        console_script = managed_venv / "bin" / "testpilot"
        console_script.write_text("#!/usr/bin/env sh\n")
        wrapper = tmp_path / "bin" / "testpilot"
        wrapper.parent.mkdir(parents=True)
        wrapper.write_text(f'#!/usr/bin/env sh\nexec "{console_script}" "$@"\n')

        mock_console = MagicMock()
        with patch("testpilot.cli._get_managed_src", return_value=managed_src):
            with patch("testpilot.cli._get_managed_venv", return_value=managed_venv):
                with patch("testpilot.cli._get_wrapper_path", return_value=wrapper):
                    with patch("testpilot.cli._get_skills_root", return_value=tmp_path / "skills"):
                        with patch("testpilot.cli.console", mock_console):
                            with pytest.raises(SystemExit) as exc_info:
                                _handle_verify_install()
        assert exc_info.value.code != 0
        output = " ".join(str(c) for c in mock_console.print.call_args_list)
        assert "pyproject.toml" in output

    def test_malformed_pyproject_fails_when_it_is_only_version_source(
        self, tmp_path: Path
    ) -> None:
        """A malformed pyproject cannot be skipped just because other mirrors are absent."""
        managed_src = tmp_path / "managed_src"
        managed_src.mkdir()
        (managed_src / "pyproject.toml").write_text("[project\nversion = ")

        from testpilot.cli import _check_version_mirrors

        ok, msg = _check_version_mirrors(managed_src)

        assert not ok
        assert "pyproject.toml" in msg

    def test_dynamic_version_reads_from_version_file(self, tmp_path: Path) -> None:
        """Dynamic-version pyproject must source the version from the hatch path.

        Regression: ``dynamic = ["version"]`` previously raised KeyError on
        ``data["project"]["version"]`` and surfaced as
        ``pyproject.toml unreadable: 'version'`` — a spurious verify-install FAIL.
        """
        from testpilot.cli import _check_version_mirrors

        managed_src = tmp_path / "managed_src"
        managed_src.mkdir()

        (managed_src / "VERSION").write_text("0.3.0\n")
        (managed_src / "pyproject.toml").write_text(
            textwrap.dedent(
                """
                [project]
                name = "testpilot-core"
                dynamic = ["version"]

                [tool.hatch.version]
                path = "VERSION"
                pattern = "(?P<version>.+)"
                """
            ).lstrip(),
            encoding="utf-8",
        )
        init_dir = managed_src / "src" / "testpilot"
        init_dir.mkdir(parents=True)
        (init_dir / "__init__.py").write_text('__version__ = "0.3.0"\n')

        ok, msg = _check_version_mirrors(managed_src)

        assert ok, f"dynamic-version pyproject should pass, got: {msg}"
        assert "unreadable" not in msg
        assert "'version'" not in msg
        assert "0.3.0" in msg

    def test_version_aligned_passes(self, tmp_path: Path) -> None:
        """All version mirrors aligned → verify-install does not fail on version check."""
        managed_src = tmp_path / "managed_src"
        managed_src.mkdir()

        (managed_src / "VERSION").write_text("0.2.0\n")
        (managed_src / "pyproject.toml").write_text(
            '[project]\nname = "testpilot"\nversion = "0.2.0"\n'
        )
        init_dir = managed_src / "src" / "testpilot"
        init_dir.mkdir(parents=True)
        (init_dir / "__init__.py").write_text('__version__ = "0.2.0"\n')

        skill_dir = tmp_path / "skills" / "testpilot-normal-test"
        skill_dir.mkdir(parents=True)
        managed_venv = tmp_path / ".venv"
        (managed_venv / "bin").mkdir(parents=True)
        console_script = managed_venv / "bin" / "testpilot"
        console_script.write_text("#!/usr/bin/env sh\n")
        wrapper = tmp_path / "bin" / "testpilot"
        wrapper.parent.mkdir(parents=True)
        wrapper.write_text(f'#!/usr/bin/env sh\nexec "{console_script}" "$@"\n')

        mock_console = MagicMock()
        with patch("testpilot.cli._get_managed_src", return_value=managed_src):
            with patch("testpilot.cli._get_managed_venv", return_value=managed_venv):
                with patch("testpilot.cli._get_wrapper_path", return_value=wrapper):
                    with patch("testpilot.cli._get_skills_root", return_value=tmp_path / "skills"):
                        with patch("testpilot.cli.console", mock_console):
                            _handle_verify_install()  # must not raise

        output = " ".join(str(c) for c in mock_console.print.call_args_list)
        assert "0.2.0" in output

    def test_missing_skill_fails_even_when_version_ok(self, tmp_path: Path) -> None:
        """Missing skill fails even when all version mirrors are aligned."""
        managed_src = tmp_path / "managed_src"
        managed_src.mkdir()

        (managed_src / "VERSION").write_text("0.2.0\n")
        (managed_src / "pyproject.toml").write_text(
            '[project]\nname = "testpilot"\nversion = "0.2.0"\n'
        )
        init_dir = managed_src / "src" / "testpilot"
        init_dir.mkdir(parents=True)
        (init_dir / "__init__.py").write_text('__version__ = "0.2.0"\n')

        skills_root = tmp_path / "skills"
        expected_skill_path = skills_root / "testpilot-normal-test"
        mock_console = MagicMock()
        # No skill directory created intentionally.
        with patch("testpilot.cli._get_managed_src", return_value=managed_src):
            with patch("testpilot.cli._get_skills_root", return_value=skills_root):
                with patch("testpilot.cli.console", mock_console):
                    with pytest.raises(SystemExit) as exc_info:
                        _handle_verify_install()
        assert exc_info.value.code != 0
        output = " ".join(str(c) for c in mock_console.print.call_args_list)
        assert str(expected_skill_path) in output


# ---------------------------------------------------------------------------
# Managed checkout reporting
# ---------------------------------------------------------------------------


class TestManagedCheckoutReport:
    """_handle_verify_install reports managed checkout status without failing."""

    def test_missing_checkout_does_not_fail(self, tmp_path: Path) -> None:
        """Missing managed checkout is informational, not a hard failure."""
        skill_dir = tmp_path / "skills" / "testpilot-normal-test"
        skill_dir.mkdir(parents=True)

        nonexistent_src = tmp_path / "nonexistent" / "managed" / "src"
        mock_console = MagicMock()
        with patch("testpilot.cli._get_managed_src", return_value=nonexistent_src):
            with patch(
                "testpilot.cli._get_skills_root", return_value=tmp_path / "skills"
            ):
                with patch("testpilot.cli.console", mock_console):
                    _handle_verify_install()  # must not raise

        # Intent: a missing managed checkout must NOT hard-fail (no SystemExit above).
        # Assert a stable, environment-independent signal that wheel-mode ran and
        # passed — the core row + the success line are always emitted when core is
        # importable. (The earlier 'checkout'/'managed' string check was fragile: in
        # wheel-mode those words only appear when a wrapper/stray WARN happens to fire,
        # which is environment-dependent and broke in CI.)
        output = " ".join(str(c) for c in mock_console.print.call_args_list).lower()
        assert "core" in output
        assert "verify-install: all checks passed" in output

    def test_healthy_managed_checkout_prints_git_info(self, tmp_path: Path) -> None:
        """When managed checkout exists, verify-install prints git remote/ref/SHA."""
        managed_src = tmp_path / "managed_src"
        managed_src.mkdir()

        (managed_src / "VERSION").write_text("0.2.0\n")
        (managed_src / "pyproject.toml").write_text(
            '[project]\nname = "testpilot"\nversion = "0.2.0"\n'
        )
        init_dir = managed_src / "src" / "testpilot"
        init_dir.mkdir(parents=True)
        (init_dir / "__init__.py").write_text('__version__ = "0.2.0"\n')

        skill_dir = tmp_path / "skills" / "testpilot-normal-test"
        skill_dir.mkdir(parents=True)
        managed_venv = tmp_path / ".venv"
        (managed_venv / "bin").mkdir(parents=True)
        console_script = managed_venv / "bin" / "testpilot"
        console_script.write_text("#!/usr/bin/env sh\n")
        wrapper = tmp_path / "bin" / "testpilot"
        wrapper.parent.mkdir(parents=True)
        wrapper.write_text(f'#!/usr/bin/env sh\nexec "{console_script}" "$@"\n')

        def _fake_git(cmd, **kwargs):
            class _R:
                returncode = 0
                stdout = "abc1234\n"

            if "remote" in cmd:
                _R.stdout = "https://github.com/paulc-arc/testpilot.git\n"
            elif "symbolic-ref" in cmd:
                _R.stdout = "main\n"
            return _R()

        mock_console = MagicMock()
        with patch("testpilot.cli._get_managed_src", return_value=managed_src):
            with patch("testpilot.cli._get_managed_venv", return_value=managed_venv):
                with patch("testpilot.cli._get_wrapper_path", return_value=wrapper):
                    with patch(
                        "testpilot.cli._get_skills_root", return_value=tmp_path / "skills"
                    ):
                        with patch("testpilot.cli._git_run", side_effect=_fake_git):
                            with patch("testpilot.cli.console", mock_console):
                                _handle_verify_install()

        output = " ".join(str(c) for c in mock_console.print.call_args_list)
        assert "abc1234" in output or "paulc-arc" in output or "main" in output

    def test_wheel_verify_fails_when_declared_plugin_health_is_false(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A healthy core probe must not hide a declared plugin's failed install check."""
        entry_point = _write_install_health_plugin(
            tmp_path,
            "wheel_health_broken_plugin",
            ok=False,
            message="FAIL declared plugin health",
        )
        monkeypatch.syspath_prepend(str(tmp_path))
        monkeypatch.setattr(
            "testpilot.cli.importlib.metadata.entry_points",
            lambda *, group: [entry_point],
        )
        monkeypatch.setattr("testpilot.cli._probe_wheel_install", _healthy_wheel_probe)
        mock_console = MagicMock()

        with patch("testpilot.cli._get_managed_src", return_value=tmp_path / "no-checkout"):
            with patch("testpilot.cli.console", mock_console):
                with pytest.raises(SystemExit) as exc_info:
                    _handle_verify_install()

        assert exc_info.value.code == 1
        output = " ".join(str(call) for call in mock_console.print.call_args_list)
        assert "FAIL declared plugin health" in output
        assert "verify-install: all checks passed" not in output

    def test_wheel_verify_runs_warn_health_and_restores_managed_module_cache(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Wheel health WARNs pass, while installed imports leave managed modules intact."""
        module_name = "wheel_health_warn_plugin"
        entry_point = _write_install_health_plugin(
            tmp_path,
            module_name,
            ok=True,
            message="WARN installed plugin health advisory",
        )
        monkeypatch.syspath_prepend(str(tmp_path))
        managed_module = ModuleType(module_name)
        monkeypatch.setitem(sys.modules, module_name, managed_module)
        monkeypatch.setattr(
            "testpilot.cli.importlib.metadata.entry_points",
            lambda *, group: [entry_point],
        )
        monkeypatch.setattr("testpilot.cli._probe_wheel_install", _healthy_wheel_probe)
        mock_console = MagicMock()

        with patch("testpilot.cli._get_managed_src", return_value=tmp_path / "no-checkout"):
            with patch("testpilot.cli.console", mock_console):
                _handle_verify_install()

        output = " ".join(str(call) for call in mock_console.print.call_args_list)
        assert "WARN installed plugin health advisory" in output
        assert "verify-install: all checks passed" in output
        assert sys.modules[module_name] is managed_module

    def test_wheel_health_prefers_distribution_root_over_ambient_module(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A same-named cwd/PYTHONPATH module cannot stand in for the installed plugin."""
        module_name = "wheel_health_shadowed_plugin"
        installed_root = tmp_path / "site-packages"
        installed_root.mkdir()
        entry_point = _write_install_health_plugin(
            installed_root,
            module_name,
            ok=True,
            message="OK installed distribution selected",
        )

        ambient_root = tmp_path / "ambient"
        ambient_root.mkdir()
        ambient_module = ambient_root / f"{module_name}.py"
        ambient_module.write_text(
            "raise RuntimeError('ambient module must not load')\n", encoding="utf-8"
        )
        monkeypatch.syspath_prepend(str(ambient_root))
        # Metadata discovery normally sees this distribution root already later
        # in sys.path; verify the health loader still gives it precedence.
        monkeypatch.setattr(sys, "path", [*sys.path, str(installed_root)])
        original_path = list(sys.path)
        monkeypatch.setattr(
            "testpilot.cli.importlib.metadata.entry_points",
            lambda *, group: [entry_point],
        )
        monkeypatch.setattr("testpilot.cli._probe_wheel_install", _healthy_wheel_probe)
        mock_console = MagicMock()

        with patch("testpilot.cli._get_managed_src", return_value=tmp_path / "no-checkout"):
            with patch("testpilot.cli.console", mock_console):
                _handle_verify_install()

        output = " ".join(str(call) for call in mock_console.print.call_args_list)
        assert "OK installed distribution selected" in output
        assert "ambient module must not load" not in output
        assert sys.path == original_path

    def test_wheel_health_rejects_ambient_module_when_distribution_file_is_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An absent installed module cannot be masked by a healthy ambient copy."""
        module_name = "wheel_health_missing_distribution_plugin"
        installed_root = tmp_path / "site-packages"
        installed_root.mkdir()
        entry_point = _FakeEntryPoint(
            "health_fixture",
            f"{module_name}:Plugin",
            dist_name="health-fixture",
            dist_root=installed_root,
        )
        ambient_root = tmp_path / "ambient"
        ambient_root.mkdir()
        ambient_entry_point = _write_install_health_plugin(
            ambient_root,
            module_name,
            ok=True,
            message="OK ambient copy must not satisfy installed health",
        )
        entry_point.value = ambient_entry_point.value
        monkeypatch.syspath_prepend(str(ambient_root))
        monkeypatch.setattr(sys, "path", [*sys.path, str(installed_root)])
        monkeypatch.setattr(
            "testpilot.cli.importlib.metadata.entry_points",
            lambda *, group: [entry_point],
        )
        monkeypatch.setattr("testpilot.cli._probe_wheel_install", _healthy_wheel_probe)
        mock_console = MagicMock()

        with patch("testpilot.cli._get_managed_src", return_value=tmp_path / "no-checkout"):
            with patch("testpilot.cli.console", mock_console):
                with pytest.raises(SystemExit) as exc_info:
                    _handle_verify_install()

        assert exc_info.value.code == 1
        output = " ".join(str(call) for call in mock_console.print.call_args_list)
        assert "module ownership could not be verified" in output
        assert "OK ambient copy must not satisfy installed health" not in output

    @pytest.mark.parametrize("record_files", [[], None], ids=["empty-record", "record-unavailable"])
    def test_wheel_health_rejects_module_owned_by_another_distribution(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        record_files: list[Path] | None,
    ) -> None:
        """Shared site-packages containment does not prove per-distribution ownership."""
        module_name = "wheel_health_wrong_distribution_plugin"
        shared_site_packages = tmp_path / "site-packages"
        shared_site_packages.mkdir()
        entry_point = _write_install_health_plugin(
            shared_site_packages,
            module_name,
            ok=True,
            message="OK wrong-owner module",
        )
        # The module exists in site-packages but is not listed in this entry
        # point distribution's RECORD; another wheel owns it.
        entry_point.dist.files = record_files
        monkeypatch.syspath_prepend(str(shared_site_packages))
        monkeypatch.setattr(
            "testpilot.cli.importlib.metadata.entry_points",
            lambda *, group: [entry_point],
        )
        monkeypatch.setattr("testpilot.cli._probe_wheel_install", _healthy_wheel_probe)
        mock_console = MagicMock()

        with patch(
            "testpilot.cli._get_managed_src", return_value=tmp_path / "no-checkout"
        ):
            with patch("testpilot.cli.console", mock_console):
                with pytest.raises(SystemExit) as exc_info:
                    _handle_verify_install()

        assert exc_info.value.code == 1
        output = " ".join(str(call) for call in mock_console.print.call_args_list)
        assert "module ownership could not be verified" in output
        assert "OK wrong-owner module" not in output

    def test_wheel_health_rejects_editable_source_outside_declared_project(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Editable mode must use its PEP 610 source root, not shared site-packages."""
        module_name = "wheel_health_wrong_editable_source_plugin"
        shared_site_packages = tmp_path / "site-packages"
        shared_site_packages.mkdir()
        entry_point = _write_install_health_plugin(
            shared_site_packages,
            module_name,
            ok=True,
            message="OK wrong editable source",
        )
        editable_project = tmp_path / "editable-project"
        editable_project.mkdir()
        entry_point.dist.files = None
        entry_point.dist.read_text = lambda filename: (
            json.dumps(
                {"url": editable_project.as_uri(), "dir_info": {"editable": True}}
            )
            if filename == "direct_url.json"
            else None
        )
        monkeypatch.syspath_prepend(str(shared_site_packages))
        monkeypatch.setattr(
            "testpilot.cli.importlib.metadata.entry_points",
            lambda *, group: [entry_point],
        )
        monkeypatch.setattr("testpilot.cli._probe_wheel_install", _healthy_wheel_probe)
        mock_console = MagicMock()

        with patch(
            "testpilot.cli._get_managed_src", return_value=tmp_path / "no-checkout"
        ):
            with patch("testpilot.cli.console", mock_console):
                with pytest.raises(SystemExit) as exc_info:
                    _handle_verify_install()

        assert exc_info.value.code == 1
        output = " ".join(str(call) for call in mock_console.print.call_args_list)
        assert "module ownership could not be verified" in output
        assert "OK wrong editable source" not in output

    def test_wheel_health_accepts_editable_module_from_declared_project_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """PEP 610 editable installs are verified against their declared source root."""
        module_name = "wheel_health_verified_editable_plugin"
        shared_site_packages = tmp_path / "site-packages"
        shared_site_packages.mkdir()
        editable_project = tmp_path / "editable-project"
        editable_project.mkdir()
        entry_point = _write_install_health_plugin(
            editable_project,
            module_name,
            ok=True,
            message="OK editable plugin health",
        )
        entry_point.dist.locate_file = (
            lambda path: shared_site_packages / path if str(path) else shared_site_packages
        )
        entry_point.dist.files = None
        entry_point.dist.read_text = lambda filename: (
            json.dumps(
                {"url": editable_project.as_uri(), "dir_info": {"editable": True}}
            )
            if filename == "direct_url.json"
            else None
        )
        monkeypatch.syspath_prepend(str(editable_project))
        monkeypatch.setattr(
            "testpilot.cli.importlib.metadata.entry_points",
            lambda *, group: [entry_point],
        )
        monkeypatch.setattr("testpilot.cli._probe_wheel_install", _healthy_wheel_probe)
        mock_console = MagicMock()

        with patch(
            "testpilot.cli._get_managed_src", return_value=tmp_path / "no-checkout"
        ):
            with patch("testpilot.cli.console", mock_console):
                _handle_verify_install()

        output = " ".join(str(call) for call in mock_console.print.call_args_list)
        assert "OK editable plugin health" in output
        assert "verify-install: all checks passed" in output

    def test_wheel_verify_fails_closed_when_declared_plugin_health_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        entry_point = _write_install_health_plugin(
            tmp_path,
            "wheel_health_raises_plugin",
            ok=True,
            message="unused",
            raise_error="private-token-must-not-be-printed",
        )
        monkeypatch.syspath_prepend(str(tmp_path))
        monkeypatch.setattr(
            "testpilot.cli.importlib.metadata.entry_points",
            lambda *, group: [entry_point],
        )
        monkeypatch.setattr("testpilot.cli._probe_wheel_install", _healthy_wheel_probe)
        mock_console = MagicMock()

        with patch("testpilot.cli._get_managed_src", return_value=tmp_path / "no-checkout"):
            with patch("testpilot.cli.console", mock_console):
                with pytest.raises(SystemExit) as exc_info:
                    _handle_verify_install()

        assert exc_info.value.code == 1
        output = " ".join(str(call) for call in mock_console.print.call_args_list)
        assert "RuntimeError" in output
        assert "private-token-must-not-be-printed" not in output

    def test_wheel_verify_fails_closed_on_malformed_plugin_health_rows(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        entry_point = _write_install_health_plugin(
            tmp_path,
            "wheel_health_malformed_plugin",
            ok="not-a-bool",
            message="malformed result",
        )
        monkeypatch.syspath_prepend(str(tmp_path))
        monkeypatch.setattr(
            "testpilot.cli.importlib.metadata.entry_points",
            lambda *, group: [entry_point],
        )
        monkeypatch.setattr("testpilot.cli._probe_wheel_install", _healthy_wheel_probe)
        mock_console = MagicMock()

        with patch("testpilot.cli._get_managed_src", return_value=tmp_path / "no-checkout"):
            with patch("testpilot.cli.console", mock_console):
                with pytest.raises(SystemExit) as exc_info:
                    _handle_verify_install()

        assert exc_info.value.code == 1
        output = " ".join(str(call) for call in mock_console.print.call_args_list)
        assert "invalid check row" in output

    def test_plugin_owned_health_reports_wifi_llapi_case_inventory(
        self, tmp_path: Path
    ) -> None:
        """verify-install includes plugin-owned wifi_llapi case inventory health."""
        managed_src = tmp_path / "managed_src"
        managed_src.mkdir()
        (managed_src / "VERSION").write_text("0.2.0\n")
        (managed_src / "pyproject.toml").write_text(
            textwrap.dedent(
                """
                [project]
                name = "testpilot"
                version = "0.2.0"

                [project.entry-points."testpilot.plugins"]
                wifi_llapi = "wifi_llapi.plugin:Plugin"
                """
            ).lstrip(),
            encoding="utf-8",
        )
        init_dir = managed_src / "src" / "testpilot"
        init_dir.mkdir(parents=True)
        (init_dir / "__init__.py").write_text('__version__ = "0.2.0"\n')

        (managed_src / "plugins" / "__init__.py").parent.mkdir(parents=True, exist_ok=True)
        (managed_src / "plugins" / "__init__.py").write_text("", encoding="utf-8")
        plugin_dir = managed_src / "wifi_llapi"
        (plugin_dir / "__init__.py").parent.mkdir(parents=True, exist_ok=True)
        (plugin_dir / "__init__.py").write_text("", encoding="utf-8")
        cases_dir = plugin_dir / "cases"
        cases_dir.mkdir(parents=True)
        (cases_dir / "D001.yaml").write_text("id: wifi-llapi-D001\n", encoding="utf-8")
        (plugin_dir / "plugin.py").write_text(
            textwrap.dedent(
                """
                from pathlib import Path
                from testpilot.core.plugin_base import PluginBase

                class Plugin(PluginBase):
                    api_version = "1.0"

                    @property
                    def name(self):
                        return "wifi_llapi"

                    @property
                    def cases_dir(self):
                        return Path(__file__).parent / "cases"

                    def discover_cases(self):
                        return []

                    def execute_step(self, case, step, topology):
                        return {}

                    def evaluate(self, case, results):
                        return True

                    def verify_install(self):
                        return [(True, "OK wifi_llapi_cases: 1 discoverable")]
                """
            ).lstrip(),
            encoding="utf-8",
        )

        skill_dir = tmp_path / "skills" / "testpilot-normal-test"
        skill_dir.mkdir(parents=True)
        managed_venv = tmp_path / ".venv"
        (managed_venv / "bin").mkdir(parents=True)
        console_script = managed_venv / "bin" / "testpilot"
        console_script.write_text("#!/usr/bin/env sh\n")
        wrapper = tmp_path / "bin" / "testpilot"
        wrapper.parent.mkdir(parents=True)
        wrapper.write_text(f'#!/usr/bin/env sh\nexec "{console_script}" "$@"\n')

        mock_console = MagicMock()
        with patch("testpilot.cli._get_managed_src", return_value=managed_src):
            with patch("testpilot.cli._get_managed_venv", return_value=managed_venv):
                with patch("testpilot.cli._get_wrapper_path", return_value=wrapper):
                    with patch(
                        "testpilot.cli._get_skills_root", return_value=tmp_path / "skills"
                    ):
                        with patch("testpilot.cli.console", mock_console):
                            _handle_verify_install()

        output = " ".join(str(c) for c in mock_console.print.call_args_list)
        assert "OK wifi_llapi_cases: 1 discoverable" in output

    def test_plugin_health_loads_using_entry_point_value(
        self,
        tmp_path: Path,
    ) -> None:
        """verify-install must load the declared entry-point value, not plugins/<name>/plugin.py."""
        from testpilot.cli import _check_plugin_health

        managed_src = tmp_path / "managed_src"
        managed_src.mkdir()
        (managed_src / "plugins").mkdir()
        (managed_src / "pyproject.toml").write_text(
            textwrap.dedent(
                """
                [project]
                name = "testpilot"
                version = "0.2.0"

                [project.entry-points."testpilot.plugins"]
                wifi_llapi = "alt_plugins.runtime_health:Plugin"
                """
            ).lstrip(),
            encoding="utf-8",
        )

        package_dir = managed_src / "alt_plugins"
        package_dir.mkdir()
        (package_dir / "__init__.py").write_text("", encoding="utf-8")
        (package_dir / "runtime_health.py").write_text(
            textwrap.dedent(
                """
                from testpilot.core.plugin_base import PluginBase

                class Plugin(PluginBase):
                    api_version = "1.0"

                    @property
                    def name(self):
                        return "wifi_llapi"

                    def discover_cases(self):
                        return []

                    def execute_step(self, case, step, topology):
                        return {}

                    def evaluate(self, case, results):
                        return True

                    def verify_install(self):
                        return [(True, "OK entry_point_value loaded")]
                """
            ).lstrip(),
            encoding="utf-8",
        )

        checks = _check_plugin_health(managed_src)

        assert any(ok and "OK entry_point_value loaded" in msg for ok, msg in checks)
        assert all("missing plugin.py" not in msg for _, msg in checks)

    def test_plugin_health_fails_closed_on_duplicate_entry_points(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """verify-install must preserve duplicate entry-point fail-closed semantics."""
        from testpilot.cli import _check_plugin_health

        managed_src = tmp_path / "managed_src"
        managed_src.mkdir()
        (managed_src / "plugins").mkdir()

        duplicates = [
            _FakeEntryPoint(
                "wifi_llapi",
                "wifi_llapi.plugin:Plugin",
                dist_name="repo-testpilot",
            ),
            _FakeEntryPoint(
                "wifi_llapi",
                "vendor.extra.plugin:Plugin",
                dist_name="vendor-plugin-pack",
            ),
        ]
        monkeypatch.setattr(
            "testpilot.cli._managed_plugin_entry_points",
            lambda _managed_src: duplicates,
            raising=False,
        )

        checks = _check_plugin_health(managed_src)

        assert checks
        assert checks[0][0] is False
        assert "invalid entry-point configuration" in checks[0][1]
        assert "ValueError" in checks[0][1]


class TestManagedInstallHealthFailures:
    """Broken managed-install wrapper and console script are hard failures."""

    def test_missing_wrapper_fails_when_managed_checkout_exists(self, tmp_path: Path) -> None:
        """Managed checkout without wrapper cannot be considered healthy."""
        from testpilot.cli import _check_wrapper

        managed_src = tmp_path / "managed_src"
        managed_src.mkdir()
        managed_venv = tmp_path / ".venv"
        wrapper = tmp_path / "bin" / "testpilot"

        ok, msg = _check_wrapper(wrapper, managed_venv, managed_src)

        assert not ok
        assert str(wrapper) in msg

    def test_missing_console_script_fails_when_managed_checkout_exists(
        self, tmp_path: Path
    ) -> None:
        """Managed checkout without venv console script cannot be considered healthy."""
        from testpilot.cli import _check_console_script

        managed_src = tmp_path / "managed_src"
        managed_src.mkdir()
        managed_venv = tmp_path / ".venv"

        ok, msg = _check_console_script(managed_venv, managed_src)

        assert not ok
        assert "console_script" in msg


# ---------------------------------------------------------------------------
# serialwrap venv-first check (I-3)
# ---------------------------------------------------------------------------


class TestSerialwrapVenvCheck:
    """_check_serialwrap_available must prefer managed-venv serialwrap over PATH."""

    def test_serialwrap_found_in_managed_venv(self, tmp_path: Path) -> None:
        """serialwrap present in managed venv is reported OK even if not in PATH."""
        from unittest.mock import patch

        from testpilot.cli import _check_serialwrap_available

        managed_venv = tmp_path / ".venv"
        (managed_venv / "bin").mkdir(parents=True)
        sw = managed_venv / "bin" / "serialwrap"
        sw.write_text("#!/usr/bin/env sh\n")
        sw.chmod(0o755)

        with patch("testpilot.cli._get_managed_venv", return_value=managed_venv):
            # Remove serialwrap from PATH to prove venv-first logic.
            with patch("testpilot.cli.shutil.which", return_value=None):
                ok, msg = _check_serialwrap_available()

        assert ok, f"expected OK but got: {msg}"
        assert "serialwrap" in msg.lower(), f"expected 'serialwrap' in message: {msg}"
        assert str(managed_venv) in msg, (
            f"expected managed venv path {managed_venv} in message: {msg}"
        )
