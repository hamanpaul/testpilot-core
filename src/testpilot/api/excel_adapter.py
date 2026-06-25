"""testpilot.api.excel_adapter — reporting.excel_adapter 的公開 re-export。"""
from __future__ import annotations

from testpilot.reporting.excel_adapter import (
    col_to_index,
    is_merged_cell,
    open_workbook,
)

__all__ = ["col_to_index", "is_merged_cell", "open_workbook"]
