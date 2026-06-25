"""RunBackend ABC and neutral dataclasses for run-level log capture.

Concrete implementations live in:
  - serialwrap_backend.SerialwrapBackend (default)
  - direct_tty_backend.DirectTtyBackend  (stub)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class RunHandle:
    """Opaque handle to an active run, returned by setup_run."""

    run_id: str
    seq_start: int | None = None
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExportRequest:
    """Backend-neutral request for log export after a test run."""

    run_id: str
    artifact_dir: Path
    case_seq_ranges: dict[str, dict[str, int | None]]
    case_results: list[Any] = field(default_factory=list)
    run_seq_start: int | None = None
    run_seq_end: int | None = None
    # Device channel identifiers — interpreted by the backend.
    # For SerialwrapBackend these are WAL COM-port labels (e.g. "COM0").
    dut_com: str = "COM0"
    sta_com: str = "COM1"


@dataclass
class ExportResult:
    """Backend-neutral result of a log export operation."""

    paths: dict[str, str] = field(default_factory=dict)

    @property
    def dut_log_path(self) -> str | None:
        return self.paths.get("dut_log_path")

    @property
    def sta_log_path(self) -> str | None:
        return self.paths.get("sta_log_path")


class RunBackend(ABC):
    """Abstract base for run-level device access (daemon, sessions, log capture)."""

    @abstractmethod
    def setup_run(self, run_id: str, config: dict[str, Any]) -> RunHandle:
        """Initialise backend state for a new run; return a RunHandle."""

    @abstractmethod
    def bind_sessions(
        self,
        handle: RunHandle,
        devices: list[dict[str, Any]],
    ) -> None:
        """Bind logging sessions to the physical devices for this run."""

    @abstractmethod
    def mark_position(self, handle: RunHandle) -> int | None:
        """Return the current log-stream sequence number (for seq-range tracking)."""

    @abstractmethod
    def export_logs(self, request: ExportRequest) -> ExportResult:
        """Export and decode run logs; annotate case_results with line ranges."""

    @abstractmethod
    def teardown_run(self, handle: RunHandle) -> None:
        """Clean up backend resources after a run completes."""
