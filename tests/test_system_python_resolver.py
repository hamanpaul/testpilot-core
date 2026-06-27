"""Unit tests for _system_python_outside (I2).

The stray-import probe must use a python interpreter that is NOT inside the
managed venv, otherwise it always finds the managed testpilot and never detects
a genuine stray (system/user-site) install.
"""

from __future__ import annotations

from pathlib import Path

import testpilot.cli as cli_mod
from testpilot.cli import _system_python_outside


def test_returns_none_when_only_candidate_is_inside_venv(monkeypatch, tmp_path):
    venv_bin = tmp_path / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    inside = venv_bin / "python3"
    inside.write_text("")

    # which() only ever finds the in-venv python -> no distinct interpreter.
    monkeypatch.setattr(cli_mod.shutil, "which", lambda name: str(inside))
    # /usr/bin/python3 absent
    monkeypatch.setattr(cli_mod.Path, "exists", lambda self: False, raising=False)

    assert _system_python_outside(venv_bin) is None


def test_returns_path_outside_venv(monkeypatch, tmp_path):
    venv_bin = tmp_path / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    sys_python = tmp_path / "usr" / "bin" / "python3"
    sys_python.parent.mkdir(parents=True)
    sys_python.write_text("")

    monkeypatch.setattr(cli_mod.shutil, "which", lambda name: str(sys_python))

    result = _system_python_outside(venv_bin)
    assert result is not None
    assert Path(result).resolve() == sys_python.resolve()
    # the resolved python must NOT live under the managed venv bin
    assert venv_bin not in Path(result).resolve().parents


def test_never_raises_on_bad_input(tmp_path):
    # Defensive: a nonexistent venv_bin must not raise.
    result = _system_python_outside(tmp_path / "does-not-exist" / "bin")
    assert result is None or isinstance(result, str)
