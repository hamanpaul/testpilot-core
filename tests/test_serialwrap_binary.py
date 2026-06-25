"""Tests for serialwrap binary resolution."""

from __future__ import annotations

import pytest

from testpilot.serialwrap_binary import resolve_serialwrap_binary


def test_resolve_uses_path_when_env_points_to_missing_binary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SERIALWRAP_BIN", "/home/paul_chen/.paul_chen/serialwrap")

    def fake_which(cmd: str) -> str | None:
        if cmd == "serialwrap":
            return "/home/paul_chen/.paul_tools/serialwrap"
        return None

    monkeypatch.setattr("testpilot.serialwrap_binary.shutil.which", fake_which)

    resolved = resolve_serialwrap_binary(
        None,
        config_label="'serialwrap_binary' in testbed config",
    )

    assert resolved == "/home/paul_chen/.paul_tools/serialwrap"


def test_resolve_uses_config_when_env_points_to_missing_binary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("SERIALWRAP_BIN", "/missing/serialwrap")
    monkeypatch.setattr("testpilot.serialwrap_binary.shutil.which", lambda cmd: None)
    binary = tmp_path / "serialwrap"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")

    resolved = resolve_serialwrap_binary(
        str(binary),
        config_label="'serialwrap_binary' in testbed config",
    )

    assert resolved == str(binary)


def test_resolve_raises_clear_error_when_nothing_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SERIALWRAP_BIN", "/missing/serialwrap")
    monkeypatch.setattr("testpilot.serialwrap_binary.shutil.which", lambda cmd: None)

    with pytest.raises(FileNotFoundError, match="SERIALWRAP_BIN=.*does not exist"):
        resolve_serialwrap_binary(
            None,
            config_label="'serialwrap_binary' in testbed config",
        )
