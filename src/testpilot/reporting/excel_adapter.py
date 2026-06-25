"""Excel adapter — thin isolation layer over openpyxl.

All direct openpyxl imports are centralised here so the rest of the
reporting package depends only on this adapter.  If openpyxl is ever
replaced (e.g. by xlsxwriter or calamine), only this file changes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from openpyxl import load_workbook as _openpyxl_load
from openpyxl.cell.cell import MergedCell as _OpenpyxlMergedCell
from openpyxl.utils import column_index_from_string as _openpyxl_col_idx

# Re-export the MergedCell type for isinstance checks
MergedCellType = _OpenpyxlMergedCell


def open_workbook(
    path: Path | str,
    *,
    read_only: bool = False,
    data_only: bool = False,
) -> Any:
    """Open an Excel workbook via openpyxl and return the Workbook object."""
    return _openpyxl_load(path, read_only=read_only, data_only=data_only)


def col_to_index(col: str | int) -> int:
    """Convert a column letter (e.g. ``'G'``) to a 1-based index."""
    if isinstance(col, int):
        return col
    return _openpyxl_col_idx(col)


def is_merged_cell(cell: Any) -> bool:
    """Return True if *cell* is a merged (non-anchor) cell."""
    return isinstance(cell, _OpenpyxlMergedCell)
