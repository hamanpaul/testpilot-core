"""Tests for CLI help text vs README alignment (E10).

Verifies that CLI commands documented in README.md actually exist
in the Click command tree, preventing documentation drift.
"""

from __future__ import annotations

import re
from pathlib import Path

from click.testing import CliRunner

from testpilot.cli import main


def _readme_text() -> str:
    readme = Path(__file__).resolve().parents[1] / "README.md"
    return readme.read_text(encoding="utf-8")


def _extract_cli_commands_from_readme() -> list[str]:
    """Extract CLI command invocations from README."""
    text = _readme_text()
    pattern = re.compile(r"^\s*(?:python\s+-m\s+testpilot\.cli|testpilot)\s+(.+)", re.MULTILINE)
    commands = []
    for match in pattern.finditer(text):
        # Get first word(s) before any flags/args
        raw = match.group(1).strip()
        # Remove trailing backslash continuations
        raw = raw.rstrip("\\").strip()
        # Take subcommand tokens (stop at -- flags or arguments)
        tokens = []
        for tok in raw.split():
            if tok.startswith("-") or tok.startswith("<") or tok.startswith("`"):
                break
            # Strip trailing backtick, comma, etc.
            tok = tok.rstrip("`,.;")
            if tok == "..." or not tok:
                break
            tokens.append(tok)
        if tokens:
            commands.append(" ".join(tokens))
    return list(dict.fromkeys(commands))  # dedupe, preserve order


class TestCLIDocAlignment:
    """Verify README CLI examples match actual CLI commands."""

    def test_readme_has_cli_examples(self):
        """README should contain CLI usage examples."""
        commands = _extract_cli_commands_from_readme()
        assert len(commands) >= 3, f"Expected at least 3 CLI examples in README, got {commands}"

    def test_version_flag_documented(self):
        """--version flag is mentioned in README."""
        text = _readme_text()
        assert "--version" in text

    def test_list_plugins_exists_in_cli(self):
        """list-plugins command exists and responds to --help."""
        runner = CliRunner()
        result = runner.invoke(main, ["list-plugins", "--help"])
        assert result.exit_code == 0

    def test_list_cases_exists_in_cli(self):
        """list-cases command exists and responds to --help."""
        runner = CliRunner()
        result = runner.invoke(main, ["list-cases", "--help"])
        assert result.exit_code == 0

    def test_run_exists_in_cli(self):
        """run command exists and responds to --help."""
        runner = CliRunner()
        result = runner.invoke(main, ["run", "--help"])
        assert result.exit_code == 0

    def test_all_readme_commands_resolve(self):
        """Every CLI command in README should resolve without UsageError."""
        runner = CliRunner()
        commands = _extract_cli_commands_from_readme()
        for cmd_str in commands:
            tokens = cmd_str.split()
            # Try --help to verify the command exists
            result = runner.invoke(main, tokens + ["--help"])
            # Some commands (like list-cases wifi_llapi) may not have --help
            # but should not produce "No such command" error
            if result.exit_code != 0:
                # Retry without --help (some commands run directly)
                result2 = runner.invoke(main, tokens)
                assert "No such command" not in (result.output + result2.output), (
                    f"Command '{cmd_str}' from README not found in CLI: {result.output}"
                )
