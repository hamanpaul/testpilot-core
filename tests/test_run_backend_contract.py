"""RunBackend 契約 + serialwrap 為預設 provider(change abstract-serialwrap-runbackend)。

RED phase: all four tests must fail until src/testpilot/runtime/ is created.
"""
from __future__ import annotations

import pytest


def test_run_backend_interface_methods():
    from testpilot.runtime.run_backend import RunBackend
    for m in ("setup_run", "bind_sessions", "mark_position", "export_logs", "teardown_run"):
        assert hasattr(RunBackend, m), f"RunBackend missing {m}"


def test_serialwrap_backend_implements_runbackend():
    from testpilot.runtime.run_backend import RunBackend
    from testpilot.runtime.serialwrap_backend import SerialwrapBackend
    assert issubclass(SerialwrapBackend, RunBackend)


def test_factory_defaults_to_serialwrap():
    from testpilot.runtime.factory import create_run_backend
    from testpilot.runtime.serialwrap_backend import SerialwrapBackend
    assert isinstance(create_run_backend(None, {}), SerialwrapBackend)


def test_factory_normalizes_backend_aliases():
    from testpilot.runtime.direct_tty_backend import DirectTtyBackend
    from testpilot.runtime.factory import create_run_backend
    from testpilot.runtime.serialwrap_backend import SerialwrapBackend

    for kind in ("", " serial ", "SERIALWRAP"):
        assert isinstance(create_run_backend(kind, {}), SerialwrapBackend)

    for kind in ("direct_tty", " direct_tty ", "TTYUSB"):
        assert isinstance(create_run_backend(kind, {}), DirectTtyBackend)


def test_factory_rejects_unknown_backend_kind():
    from testpilot.runtime.factory import create_run_backend

    with pytest.raises(ValueError, match="Unknown RunBackend kind"):
        create_run_backend("unknown-backend", {})


def test_direct_tty_backend_exists_as_stub():
    from testpilot.runtime.run_backend import RunBackend
    from testpilot.runtime.direct_tty_backend import DirectTtyBackend
    assert issubclass(DirectTtyBackend, RunBackend)
