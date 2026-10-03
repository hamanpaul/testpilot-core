from __future__ import annotations

import pytest

from testpilot.runtime import _serialwrap_log


@pytest.fixture(autouse=True)
def _reset_serialwrap_run_target(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep run-scoped CLI binding state from leaking between unit tests."""
    defaults = {
        "_configured_bin": None,
        "_configured_socket": None,
        "_configured_enabled": True,
        "_configured_reason": "",
        "_configured_owner": None,
    }
    for name, value in defaults.items():
        monkeypatch.setattr(_serialwrap_log, name, value)
