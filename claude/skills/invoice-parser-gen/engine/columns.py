"""Read a table's column boundaries off its own printed header row.

Fixed-width invoice tables are best parsed by slicing on column positions rather
than splitting on whitespace runs, because a blank cell makes a row's field count
differ from the header's. Splitting `X2160  SM SHOP TWL-RED-      L  01 F 20 ...`
on whitespace yields three head fields where the employee column is actually
empty and the third field is an unlabelled sub-column, and the values silently
shift one slot left.

The offsets must come from the document. They are not stable even within one
vendor: Cintas puts MATERIAL at column 16 on garment invoices and 13 on facility
invoices, and Baxter's report generator auto-sizes columns so page 2 differs from
page 1 in the same file. Anything hard-coded is wrong by the second invoice.
"""

from __future__ import annotations

from functools import lru_cache

__all__ = ["column_offsets", "slice_columns", "field_at_offset"]


@lru_cache(maxsize=256)
def column_offsets(header: str, labels: tuple[str, ...]) -> tuple[tuple[str, int], ...]:
    """Offsets of each label in the header row, left to right.

    Returned as a tuple of pairs rather than a dict so the result stays hashable
    and cacheable; header rows repeat on every page of a long invoice.
    """
    found = [(label, header.find(label)) for label in labels]
    return tuple(sorted(((l, at) for l, at in found if at >= 0), key=lambda p: p[1]))


def slice_columns(
    line: str, offsets: tuple[tuple[str, int], ...], *, end: int | None = None
) -> dict[str, str]:
    """Cut a line into cells using the header offsets as boundaries.

    Each column runs from its own offset to the start of the next, and the last
    runs to `end` (or the end of the line). Values are stripped, so an empty cell
    is an empty string rather than whitespace.
    """
    cells: dict[str, str] = {}
    for index, (label, start) in enumerate(offsets):
        stop = offsets[index + 1][1] if index + 1 < len(offsets) else end
        cells[label] = line[start:stop].strip() if start < len(line) else ""
    return cells


def field_at_offset(
    offsets: tuple[tuple[str, int], ...], position: int
) -> str | None:
    """Which column a character position falls in.

    Used to route a wrapped continuation token back to the field it belongs to.
    A bare token under the Reference column continues the reference; the same
    shape under the Middle column continues a middle name, and appending it to
    the wrong field corrupts data that no total will catch.
    """
    match: str | None = None
    for label, start in offsets:
        if position >= start:
            match = label
        else:
            break
    return match
