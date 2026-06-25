from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class PreparedRun:
    cases: list[dict[str, Any]]
    artifacts: dict[str, Any] = field(default_factory=dict)
