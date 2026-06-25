"""DirectTtyBackend — stub RunBackend for direct TTY access (not yet implemented)."""

from __future__ import annotations

from typing import Any

from testpilot.runtime.run_backend import (
    ExportRequest,
    ExportResult,
    RunBackend,
    RunHandle,
)


class DirectTtyBackend(RunBackend):
    """Placeholder backend for direct TTY log capture. Not yet implemented."""

    def setup_run(self, run_id: str, config: dict[str, Any]) -> RunHandle:
        raise NotImplementedError("DirectTtyBackend.setup_run is not yet implemented")

    def bind_sessions(
        self,
        handle: RunHandle,
        devices: list[dict[str, Any]],
    ) -> None:
        raise NotImplementedError("DirectTtyBackend.bind_sessions is not yet implemented")

    def mark_position(self, handle: RunHandle) -> int | None:
        raise NotImplementedError("DirectTtyBackend.mark_position is not yet implemented")

    def export_logs(self, request: ExportRequest) -> ExportResult:
        raise NotImplementedError("DirectTtyBackend.export_logs is not yet implemented")

    def teardown_run(self, handle: RunHandle) -> None:
        raise NotImplementedError("DirectTtyBackend.teardown_run is not yet implemented")
