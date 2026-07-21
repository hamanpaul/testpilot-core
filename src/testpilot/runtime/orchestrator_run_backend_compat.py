"""Compatibility helpers that delegate Orchestrator run-log lifecycle to RunBackend."""

from __future__ import annotations

import inspect
import logging
from pathlib import Path
from typing import Any

from testpilot.runtime.run_backend import ExportRequest, RunHandle

log = logging.getLogger(__name__)


class OrchestratorRunBackendCompat:
    """Provide legacy orchestrator hook names via thin RunBackend delegation."""

    def _start_run_capture(self, run_id: str = "run") -> Path | None:
        start_capture = self._start_serialwrap_for_run
        signature = inspect.signature(start_capture)
        params = list(signature.parameters.values())
        if any(param.kind == inspect.Parameter.VAR_POSITIONAL for param in params):
            return start_capture(run_id)
        if any(
            param.kind in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            )
            for param in params
        ):
            return start_capture(run_id)
        if "run_id" in signature.parameters or any(
            param.kind == inspect.Parameter.VAR_KEYWORD for param in params
        ):
            return start_capture(run_id=run_id)
        if params:
            return start_capture(run_id)
        return start_capture()

    def _stop_run_capture(self) -> None:
        self._stop_serialwrap()

    def _export_run_logs(
        self,
        *,
        run_id: str,
        artifact_dir: Path,
        case_seq_ranges: dict[str, dict[str, int | None]],
        case_results: list[Any],
        run_seq_start: int | None = None,
        run_seq_end: int | None = None,
    ) -> dict[str, str]:
        return self._export_serialwrap_logs(
            run_id=run_id,
            artifact_dir=artifact_dir,
            case_seq_ranges=case_seq_ranges,
            case_results=case_results,
            run_seq_start=run_seq_start,
            run_seq_end=run_seq_end,
        )

    def _run_backend_devices(self) -> list[dict[str, Any]]:
        devs = self.config.devices
        devices: list[dict[str, Any]] = []
        for alias in ("dut", "sta"):
            cfg = devs.get(alias) or devs.get(alias.upper()) or {}
            selector = cfg.get("selector", "")
            if selector:
                devices.append(
                    {
                        "com": selector,
                        "alias": alias,
                        # testbed 可用 console_profile（station-layer）或 profile 指定
                        # serialwrap session profile；未指定維持 prpl-template。
                        "profile": cfg.get(
                            "console_profile", cfg.get("profile", "prpl-template")
                        ),
                        "serial_port": cfg.get("serial_port", ""),
                    }
                )
        return devices

    def _run_backend_ports(self) -> tuple[str, str]:
        devs = self.config.devices
        dut_dev = devs.get("dut") or devs.get("DUT") or {}
        sta_dev = devs.get("sta") or devs.get("STA") or {}
        return (
            dut_dev.get("com_port") or dut_dev.get("selector", "COM0"),
            sta_dev.get("com_port") or sta_dev.get("selector", "COM1"),
        )

    def _start_serialwrap_for_run(self, run_id: str = "run") -> Path | None:
        handle: RunHandle | None = None
        try:
            handle = self.run_backend.setup_run(
                run_id=run_id,
                config=self.config.raw.get("testbed", {}),
            )
            self._run_handle = handle
            devices = self._run_backend_devices()
            if devices and handle.meta.get("bind_sessions"):
                self.run_backend.bind_sessions(handle, devices)
            path_value = handle.meta.get("wal_path")
            return Path(path_value) if path_value else None
        except NotImplementedError:
            raise
        except Exception:
            if handle is None:
                handle = RunHandle(run_id=run_id)
            handle.meta["wal_path"] = None
            self._run_handle = handle
            log.warning("run backend start failed; logs will be unavailable", exc_info=True)
            return None

    def _stop_serialwrap(self) -> None:
        handle = self._run_handle
        if handle is None:
            return
        try:
            self.run_backend.teardown_run(handle)
        finally:
            self._run_handle = None

    def _export_serialwrap_logs(
        self,
        *,
        run_id: str,
        artifact_dir: Path,
        case_seq_ranges: dict[str, dict[str, int | None]],
        case_results: list[Any],
        run_seq_start: int | None = None,
        run_seq_end: int | None = None,
    ) -> dict[str, str]:
        dut_com, sta_com = self._run_backend_ports()
        result = self.run_backend.export_logs(
            ExportRequest(
                run_id=run_id,
                artifact_dir=artifact_dir,
                case_seq_ranges=case_seq_ranges,
                case_results=case_results,
                run_seq_start=run_seq_start,
                run_seq_end=run_seq_end,
                dut_com=dut_com,
                sta_com=sta_com,
            )
        )
        return dict(result.paths)
