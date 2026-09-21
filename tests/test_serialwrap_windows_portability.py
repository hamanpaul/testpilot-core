"""Windows portability of the serialwrap client glue (#50, #51).

#50 ``_match_device_by_id`` compared ``Path(...).resolve()`` results; on Windows a
bare ``COM5`` resolves to ``<cwd>\\COM5`` while serialwrap reports
``real_path`` as ``\\\\.\\COM5``, so testbed ``serial_port: COM5`` never matched.

#51 ``_run_sw`` / ``session bind`` ``Popen`` / ``_run_json`` used ``text=True``
without an ``encoding``; on a cp950 (zh-TW) Windows host, serialwrap's UTF-8
output raised ``UnicodeDecodeError`` inside the subprocess reader threads.
"""

from __future__ import annotations

import subprocess

import pytest

from testpilot.runtime import _serialwrap_log
from testpilot.transport.serialwrap import SerialWrapTransport

_WIN_DEVICES = [
    {"by_id": "COM5", "real_path": "\\\\.\\COM5"},
    {"by_id": "COM7", "real_path": "\\\\.\\COM7"},
]


@pytest.fixture(autouse=True)
def _set_serialwrap_bin(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    fake = tmp_path / "serialwrap"
    fake.write_text("#!/bin/sh\nexit 0\n")
    fake.chmod(0o755)
    monkeypatch.setenv("SERIALWRAP_BIN", str(fake))


# ---------------------------------------------------------------------------
# #50 — COM name matching on Windows
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("serial_port", ["COM5", "\\\\.\\COM5", "com5"])
def test_match_device_by_id_windows_com_names(
    monkeypatch: pytest.MonkeyPatch, serial_port: str
) -> None:
    monkeypatch.setattr(_serialwrap_log, "_is_windows", lambda: True, raising=False)
    assert _serialwrap_log._match_device_by_id(_WIN_DEVICES, serial_port) == "COM5"


def test_match_device_by_id_windows_unknown_com_is_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_serialwrap_log, "_is_windows", lambda: True, raising=False)
    assert _serialwrap_log._match_device_by_id(_WIN_DEVICES, "COM9") is None


def test_match_device_by_id_posix_resolves_symlink(tmp_path) -> None:
    real = tmp_path / "ttyUSB0"
    real.write_text("")
    link = tmp_path / "by-id-link"
    link.symlink_to(real)
    devices = [{"by_id": str(link), "real_path": str(real)}]
    assert _serialwrap_log._match_device_by_id(devices, str(link)) == str(link)


# ---------------------------------------------------------------------------
# #51 — UTF-8 decoding independent of the host locale
# ---------------------------------------------------------------------------

_UTF8_JSON = '{"ok": true, "console_hint": "human console 請用 serialwrap-minicom"}'


def _decode_like_subprocess(raw: bytes, encoding: str | None) -> str:
    """Emulate ``subprocess`` text decoding on a cp950 host: no explicit
    encoding → locale codec (cp950), which cannot decode UTF-8 Chinese."""
    return raw.decode(encoding or "cp950")


def test_run_sw_decodes_utf8_output_on_cp950_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(cmd, **kwargs):  # noqa: ANN001
        stdout = _decode_like_subprocess(_UTF8_JSON.encode("utf-8"), kwargs.get("encoding"))
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(_serialwrap_log.subprocess, "run", fake_run)

    payload = _serialwrap_log._run_sw(["daemon", "status"])

    assert payload["console_hint"] == "human console 請用 serialwrap-minicom"


def test_run_json_decodes_utf8_output_on_cp950_host(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    def fake_run(cmd, **kwargs):  # noqa: ANN001
        stdout = _decode_like_subprocess(_UTF8_JSON.encode("utf-8"), kwargs.get("encoding"))
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=stdout, stderr="")

    import testpilot.transport.serialwrap as transport_mod

    monkeypatch.setattr(transport_mod.subprocess, "run", fake_run)
    transport = SerialWrapTransport({"binary": str(tmp_path / "serialwrap"), "selector": "COM0"})

    payload = transport._run_json(["daemon", "status"])

    assert payload["console_hint"] == "human console 請用 serialwrap-minicom"


def test_session_bind_popen_requests_utf8(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[dict] = []

    class _FakeProc:
        returncode = 0

        def communicate(self, timeout=None):  # noqa: ANN001
            return "{}", ""

    def fake_popen(cmd, **kwargs):  # noqa: ANN001
        captured.append(kwargs)
        return _FakeProc()

    monkeypatch.setattr(_serialwrap_log.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(_serialwrap_log, "_list_devices", lambda: list(_WIN_DEVICES))
    monkeypatch.setattr(_serialwrap_log, "_run_sw", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(_serialwrap_log.time, "sleep", lambda *_: None)

    _serialwrap_log.setup_sessions(
        [{"profile": "prpl-template", "com": "COM0", "serial_port": "\\\\.\\COM5", "alias": "dut"}],
        bind_timeout=1.0,
        settle_delay=0.0,
    )

    assert captured and captured[0].get("encoding") == "utf-8"
