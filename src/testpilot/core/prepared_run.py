from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class PreparedRun:
    """Plugin's prepared selection and run-scoped evidence metadata.

    ``no_io`` is an opt-in declaration that the selected run needs no DUT/STA
    I/O for Core's capture, sequence-marker, export, or firmware-version hooks.
    It does not suppress per-case planning, execution, or reporting.
    """

    cases: list[dict[str, Any]]
    artifacts: dict[str, Any] = field(default_factory=dict)
    no_io: bool = False
