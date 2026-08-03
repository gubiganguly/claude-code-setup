"""Classify every line of an invoice into a known row kind, or flag it.

This module exists for one guarantee: **no line is ever silently ignored.**

A parser that scans for rows it recognises and skips the rest will happily
produce a clean-looking result from a document it only half understood. When a
vendor adds a row type, that parser drops it and reports success. The
reconciliation ladder catches the subset of those mistakes that move money, but
a dropped row whose amount happens to be zero, or a truncated text field, moves
nothing and passes.

So classification is total. Every non-blank line matches exactly one rule or
becomes `UNCLASSIFIED`, and an invoice with any unclassified line does not pass,
regardless of how well its arithmetic reconciles. Building the Cintas spec, this
is what surfaced 277 wrapped description continuations and 77 contingent
"employee owes" notices — both invisible to the totals.

Zones handle the common case where the same text means different things in
different parts of the document. Cintas restates its program charges in a
trailing summary block; the identical `PREP ADVANTAGE  14.50  N` line is a
charge in the body and a restatement below the marker. A zone switch draws that
boundary once instead of smearing lookahead through every rule.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

from .text import Document

__all__ = [
    "RowKind",
    "Rule",
    "ZoneMarker",
    "ClassifiedRow",
    "Classifier",
    "LineContext",
    "BODY",
]

BODY = "body"


class RowKind(str, Enum):
    """What a line is, for reconciliation purposes."""

    # Money that is actually billed. These are what sum to the invoice.
    CHARGE = "charge"

    # Amounts the invoice itself prints as checkable sums.
    GROUP_SUBTOTAL = "group_subtotal"
    SECTION_SUBTOTAL = "section_subtotal"
    INVOICE_SUBTOTAL = "invoice_subtotal"
    TAX = "tax"
    GRAND_TOTAL = "grand_total"
    # A total for one column of the detail table rather than for a band of rows.
    # Vendors whose rows carry several money columns often print one of these per
    # column and no row-wise subtotal at all, which makes them the only
    # intermediate check available.
    COLUMN_TOTAL = "column_total"
    # A printed count of rows ("Total Searches: 518"). Not money, but a free
    # independent constraint: it catches a dropped row whose amount is 0.00,
    # which no sum can see.
    ROW_COUNT = "row_count"
    # A credit or payment applied against the invoice ("Payments/Credits Applied
    # -$1,032.35"), and the net figure after it ("Balance Due"). Distinct kinds
    # because they are neither charges nor sums of charges: the invoice total and
    # the amount payable genuinely differ once a credit exists, and borrowing
    # COLUMN_TOTAL for them erodes what that kind means in every other spec.
    ADJUSTMENT = "adjustment"
    NET_DUE = "net_due"

    # Structure, carrying no money of its own.
    SECTION_HEADER = "section_header"
    COLUMN_HEADER = "column_header"
    HEADER_FIELD = "header_field"
    CONTINUATION = "continuation"

    # Amounts that must never be summed: the invoice restating charges it has
    # already billed, in a different breakdown.
    RESTATEMENT = "restatement"

    # Text with no bearing on extraction: boilerplate, addresses, marketing,
    # and contingent amounts that are not charges.
    IGNORABLE = "ignorable"

    # The tripwire.
    UNCLASSIFIED = "unclassified"

    @property
    def is_money(self) -> bool:
        return self in _MONEY_KINDS


_MONEY_KINDS = frozenset(
    {
        RowKind.CHARGE,
        RowKind.GROUP_SUBTOTAL,
        RowKind.SECTION_SUBTOTAL,
        RowKind.INVOICE_SUBTOTAL,
        RowKind.TAX,
        RowKind.GRAND_TOTAL,
        RowKind.COLUMN_TOTAL,
        RowKind.ADJUSTMENT,
        RowKind.NET_DUE,
        RowKind.RESTATEMENT,
    }
)


@dataclass
class LineContext:
    """What surrounds the line being classified.

    Some rows are only identifiable from context, and pretending otherwise is
    where parsers go wrong. On a Cintas invoice the footer `SUBTOTAL 131.33` is
    textually identical to a section `SUBTOTAL 67.55`; the only thing that
    distinguishes them is that `TAX` follows the footer. Wrapped description
    continuations are likewise recognisable only as "a bare token directly under
    a charge row".

    `prev_rows` holds what has already been classified, so a rule can depend on
    what came before without a second pass.
    """

    page: int
    line_no: int
    lines: list[str]
    index: int
    zone: str
    prev_rows: list["ClassifiedRow"]

    def peek(self, offset: int) -> str | None:
        i = self.index + offset
        return self.lines[i] if 0 <= i < len(self.lines) else None

    def next_nonblank(self, skip: int = 0) -> str | None:
        seen = 0
        for line in self.lines[self.index + 1 :]:
            if line.strip():
                if seen == skip:
                    return line
                seen += 1
        return None

    def prev_nonblank(self, skip: int = 0) -> str | None:
        seen = 0
        for line in reversed(self.lines[: self.index]):
            if line.strip():
                if seen == skip:
                    return line
                seen += 1
        return None

    @property
    def prev_row(self) -> "ClassifiedRow | None":
        return self.prev_rows[-1] if self.prev_rows else None

    def last_row_of_kind(
        self, *kinds: "RowKind", this_page: bool = False
    ) -> "ClassifiedRow | None":
        """Most recent classified row of any of these kinds.

        Used to reach the governing column-header row, whose character offsets
        give the real column boundaries. Those offsets differ between invoice
        variants from the same vendor, so reading them from the document beats
        hard-coding them.

        `this_page=True` restricts the search to the current page, which is how a
        rule asks "is this line above or below *this* page's table" — a page that
        prints no column header at all (a remittance stub) must not silently
        inherit the previous page's.
        """
        wanted = set(kinds)
        for row in reversed(self.prev_rows):
            if this_page and row.page != self.page:
                return None
            if row.kind in wanted:
                return row
        return None

    def last_significant_row(self, *skip: "RowKind") -> "ClassifiedRow | None":
        """Most recent row that is not one of the structural kinds to skip.

        Lets a rule reason about what precedes it *in the invoice body* while
        ignoring the header block a page break injects in between.
        """
        skipped = set(skip)
        for row in reversed(self.prev_rows):
            if row.kind not in skipped:
                return row
        return None


@dataclass(frozen=True)
class Rule:
    """One classification rule. Order matters: first match wins.

    `extract` receives the regex match and the raw line and returns fields to
    attach to the row. Money-bearing kinds must return an `amount` Decimal;
    the classifier enforces that rather than letting a None reach the ladder.

    `guard` is a second gate consulted only after the pattern matches. Keeping
    shape (pattern) and context (guard) separate means a rule reads as "this
    looks like X, and it is in a position where X is possible", which is easier
    to get right than one regex trying to encode both.
    """

    kind: RowKind
    pattern: str | re.Pattern[str] | None = None
    predicate: Callable[[str], bool] | None = None
    guard: Callable[[str, LineContext], bool] | None = None
    extract: Callable[[re.Match[str] | None, str, LineContext], dict] | None = None
    zones: frozenset[str] = frozenset({BODY})
    name: str = ""

    def __post_init__(self) -> None:
        if self.pattern is None and self.predicate is None:
            raise ValueError(f"rule {self.name!r} needs a pattern or a predicate")
        if isinstance(self.pattern, str):
            object.__setattr__(self, "pattern", re.compile(self.pattern))
        if not self.name:
            object.__setattr__(self, "name", f"{self.kind.value}:unnamed")

    def applies_in(self, zone: str) -> bool:
        return "*" in self.zones or zone in self.zones

    def test(self, line: str) -> re.Match[str] | bool | None:
        if self.pattern is not None:
            return self.pattern.search(line)
        return self.predicate(line)  # type: ignore[misc]


@dataclass(frozen=True)
class ZoneMarker:
    """A line that switches the active zone for everything after it."""

    pattern: str | re.Pattern[str]
    zone: str
    kind: RowKind = RowKind.IGNORABLE
    name: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.pattern, str):
            object.__setattr__(self, "pattern", re.compile(self.pattern))
        if not self.name:
            object.__setattr__(self, "name", f"zone:{self.zone}")


@dataclass
class ClassifiedRow:
    kind: RowKind
    page: int
    line_no: int
    raw: str
    zone: str = BODY
    rule: str = ""
    fields: dict = field(default_factory=dict)

    @property
    def amount(self) -> Decimal | None:
        return self.decimal_field("amount")

    def decimal_field(self, name: str) -> Decimal | None:
        """Read a named field as a Decimal.

        Rows with several money columns need each one reconcilable on its own, so
        the ladder addresses fields by name rather than assuming a single
        `amount`. Strings are coerced because extractors may store the raw token.
        """
        value = self.fields.get(name)
        if isinstance(value, Decimal):
            return value
        if isinstance(value, int):
            return Decimal(value)
        if isinstance(value, str) and value.strip():
            try:
                return Decimal(value.replace(",", "").replace("$", "").strip())
            except Exception:
                return None
        return None

    @property
    def location(self) -> str:
        return f"page {self.page}, line {self.line_no}"

    def __str__(self) -> str:
        return f"[{self.kind.value}] {self.location}: {self.raw.strip()[:90]}"


class ClassifierError(RuntimeError):
    pass


class Classifier:
    """Applies an ordered rule set to every line of a document."""

    def __init__(
        self,
        rules: Sequence[Rule],
        zone_markers: Sequence[ZoneMarker] = (),
        *,
        blank_is_ignorable: bool = True,
    ) -> None:
        self.rules = list(rules)
        self.zone_markers = list(zone_markers)
        self.blank_is_ignorable = blank_is_ignorable

    def classify_line(
        self, line: str, ctx: LineContext
    ) -> tuple[ClassifiedRow | None, str]:
        """Classify one line. Returns the row (or None for blanks) and the new zone."""
        zone, page, line_no = ctx.zone, ctx.page, ctx.line_no

        for marker in self.zone_markers:
            if marker.pattern.search(line):  # type: ignore[union-attr]
                return (
                    ClassifiedRow(
                        kind=marker.kind,
                        page=page,
                        line_no=line_no,
                        raw=line,
                        zone=marker.zone,
                        rule=marker.name,
                    ),
                    marker.zone,
                )

        if not line.strip():
            if self.blank_is_ignorable:
                return None, zone
            return (
                ClassifiedRow(RowKind.UNCLASSIFIED, page, line_no, line, zone, "blank"),
                zone,
            )

        for rule in self.rules:
            if not rule.applies_in(zone):
                continue
            result = rule.test(line)
            if not result:
                continue
            if rule.guard is not None and not rule.guard(line, ctx):
                continue

            fields: dict = {}
            if rule.extract is not None:
                match = result if isinstance(result, re.Match) else None
                fields = rule.extract(match, line, ctx) or {}

            if rule.kind.is_money and not isinstance(fields.get("amount"), Decimal):
                raise ClassifierError(
                    f"rule {rule.name!r} matched a {rule.kind.value} row but produced "
                    f"no Decimal amount (page {page}, line {line_no}): {line.strip()[:80]!r}. "
                    "A money row with an unreadable amount must fail loudly, not "
                    "default to zero."
                )

            return (
                ClassifiedRow(
                    kind=rule.kind,
                    page=page,
                    line_no=line_no,
                    raw=line,
                    zone=zone,
                    rule=rule.name,
                    fields=fields,
                ),
                zone,
            )

        return (
            ClassifiedRow(RowKind.UNCLASSIFIED, page, line_no, line, zone, ""),
            zone,
        )

    def classify(self, doc: Document) -> list[ClassifiedRow]:
        """Classify a whole document. Zones persist across page breaks.

        Zone state deliberately does not reset per page: on real invoices a
        section routinely runs across a page boundary, and one Cintas invoice
        carries a single section across four pages.
        """
        rows: list[ClassifiedRow] = []
        zone = BODY
        for page in doc.pages:
            for index, line in enumerate(page.lines):
                ctx = LineContext(
                    page=page.number,
                    line_no=index,
                    lines=page.lines,
                    index=index,
                    zone=zone,
                    prev_rows=rows,
                )
                row, zone = self.classify_line(line, ctx)
                if row is not None:
                    rows.append(row)
        return rows

    # -- reporting helpers -------------------------------------------------

    @staticmethod
    def unclassified(rows: Iterable[ClassifiedRow]) -> list[ClassifiedRow]:
        return [r for r in rows if r.kind is RowKind.UNCLASSIFIED]

    @staticmethod
    def of_kind(rows: Iterable[ClassifiedRow], *kinds: RowKind) -> list[ClassifiedRow]:
        wanted = set(kinds)
        return [r for r in rows if r.kind in wanted]

    @staticmethod
    def counts(rows: Iterable[ClassifiedRow]) -> dict[str, int]:
        out: dict[str, int] = {}
        for row in rows:
            out[row.kind.value] = out.get(row.kind.value, 0) + 1
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))
