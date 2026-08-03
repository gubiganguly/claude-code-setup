"""Baxter Research (PeopleFacts) background-search invoices — MS Access report.

Structure:

    header       address block, with the totals interleaved on the SAME lines:
                   "PeopleFacts        Names: 518    Search Fees   $1,111.15"
                   "7373 Peak Drive    AKAs:    0    Court Fees        $3.80"
                   "Las Vegas, NV  Total Searches: 518  TOTAL DUE  $1,114.95"
    legend       TYPE: / CODE: keys that look like data
    table        one row per search, repeated column header on every page
                 └─ every row wraps: a bare accession number on the next line

Structurally the opposite of Cintas: **no in-body subtotals at all.** What makes
it verifiable is that the header decomposes the invoice by *column* — Search Fees
and Court Fees separately — plus a row count. So the ladder here runs across
columns rather than down groups:

    sum(search_fee)  == printed Search Fees
    sum(court_fee)   == printed Court Fees
    sum(both)        == printed TOTAL DUE
    count(rows)      == printed Total Searches

The count rung is not decoration. Court Fees is `$0.00` on nearly every row (518
of 518 zeros in one file), so a dropped row leaves both money sums intact and
only the count notices.

Discriminator: **exactly two trailing money tokens.** Every charge row ends in
`$court $search`; every total line carries one amount. An x-band would fail here,
because the Access report auto-sizes columns per file and the header's own money
tokens land inside the line-item bands.
"""

from __future__ import annotations

import re
from decimal import Decimal

from engine.classify import ClassifiedRow, LineContext, RowKind, Rule
from engine.columns import column_offsets, field_at_offset, slice_columns
from engine.money import parse_money
from engine.reconcile import CheckMode, LevelCheck
from engine.spec import InvoiceSpec

MONEY = r"[\d,]+\.\d{2}"

_COLUMN_LABELS = (
    "County",
    "Type",
    "Reference",
    "LAST",
    "FIRST",
    "Middle",
    "Request",
    "Code",
    "Result",
    "Court",
    "Search",
)

# Header label -> output field name.
_FIELD_FOR = {
    "County": "county",
    "Type": "type_code",
    "Reference": "reference",
    "LAST": "last_name",
    "FIRST": "first_name",
    "Middle": "middle_name",
    "Request": "request_date",
    "Code": "code",
    "Result": "result",
}


def _money(raw: str) -> Decimal:
    value = parse_money(raw)
    if value is None:  # pragma: no cover - classifier rejects first
        raise ValueError(f"unparseable amount {raw!r}")
    return value


# ---------------------------------------------------------------------------
# Charge rows
# ---------------------------------------------------------------------------

_CHARGE = rf"^(?P<head>.*?)\s+\$(?P<court>{MONEY})\s+\$(?P<search>{MONEY})\s*$"


def _extract_charge(match: re.Match[str] | None, line: str, ctx: LineContext) -> dict:
    assert match is not None
    court, search = _money(match.group("court")), _money(match.group("search"))

    header_row = ctx.last_row_of_kind(RowKind.COLUMN_HEADER)
    fields: dict = {}
    if header_row is not None:
        offsets = column_offsets(header_row.raw, _COLUMN_LABELS)
        # Cut the head only; the money columns are already captured.
        cells = slice_columns(match.group("head"), offsets, end=len(match.group("head")))
        for label, value in cells.items():
            if label in _FIELD_FOR:
                fields[_FIELD_FOR[label]] = value

    return {
        # `amount` is the row's total charge, so the grand-total rung needs no
        # special case; the per-column rungs address court_fee/search_fee.
        "amount": court + search,
        "court_fee": court,
        "search_fee": search,
        **fields,
    }


# ---------------------------------------------------------------------------
# Printed totals — all on page 1, sharing lines with the address block
# ---------------------------------------------------------------------------

_SEARCH_FEES = rf"Names:\s+(?P<names>\d+)\s+Search Fees\s+\$(?P<amount>{MONEY})\s*$"
_COURT_FEES = rf"AKAs:\s+(?P<akas>\d+)\s+Court Fees\s+\$(?P<amount>{MONEY})\s*$"
_TOTAL_DUE = (
    rf"Total Searches:\s+(?P<count>\d+)\s+TOTAL DUE\s+\$(?P<amount>{MONEY})\s*$"
)


def _extract_search_fees(match: re.Match[str] | None, line: str, ctx) -> dict:
    assert match is not None
    # Stored under a column-specific name so the two COLUMN_TOTAL rows can be
    # told apart by which field they carry, without needing distinct row kinds.
    return {
        "amount": _money(match.group("amount")),
        "search_fees_printed": _money(match.group("amount")),
        "names": match.group("names"),
    }


def _extract_court_fees(match: re.Match[str] | None, line: str, ctx) -> dict:
    assert match is not None
    return {
        "amount": _money(match.group("amount")),
        "court_fees_printed": _money(match.group("amount")),
        "akas": match.group("akas"),
    }


def _extract_total_due(match: re.Match[str] | None, line: str, ctx) -> dict:
    assert match is not None
    return {
        "amount": _money(match.group("amount")),
        "count": match.group("count"),
    }


# ---------------------------------------------------------------------------
# Structure and noise
# ---------------------------------------------------------------------------

_COLUMN_HEADER = r"^County\s+Type\s+Reference\s+LAST"
# Second physical line of the two-line header: the wrapped "Date"/"Fees"/"Fee".
_HEADER_TAIL = r"^\s+(Date|Fees|Fee)(\s+(Fees|Fee))*\s*$"

# A continuation line carries no money and sits under the table. It may hold
# more than one token — an accession overflow and a wrapped middle name land on
# the same physical line — so each token is routed by the column it sits in.
_CONTINUATION = r"^\s{10,}\S+(?:\s+\S+){0,3}\s*$"


def _continuation_guard(line: str, ctx: LineContext) -> bool:
    if "$" in line or re.search(r"\d+\.\d{2}\s*$", line):
        return False
    previous = ctx.last_significant_row(
        RowKind.IGNORABLE,
        RowKind.HEADER_FIELD,
        RowKind.COLUMN_HEADER,
        RowKind.CONTINUATION,
        RowKind.RESTATEMENT,
    )
    return previous is not None and previous.kind is RowKind.CHARGE


def _extract_continuation(match: re.Match[str] | None, line: str, ctx: LineContext) -> dict:
    header_row = ctx.last_row_of_kind(RowKind.COLUMN_HEADER)
    offsets = (
        column_offsets(header_row.raw, _COLUMN_LABELS) if header_row is not None else ()
    )
    parts: list[tuple[str, str]] = []
    for token in re.finditer(r"\S+", line):
        label = field_at_offset(offsets, token.start()) if offsets else None
        parts.append((_FIELD_FOR.get(label or "") or "reference", token.group()))
    return {"parts": parts, "text": line.strip()}


# "Court Search Fee for Case Number clerk check: $15.00" itemises the row's
# Court Fees value rather than adding to it: a row showing $18.00 is followed by
# $3.00 + $15.00. Summing these would double the court column. Verified against
# an 8,298-row invoice where all four rungs close without them.
#
# Matched structurally rather than by label. An earlier version enumerated the
# prefixes it had seen (Court, Miscellaneous, Clerk, Filing) and then failed on
# twelve invoices carrying "File Pull Fee". The shape — an indented label ending
# in a colon followed by exactly one amount — is what identifies these, and it
# cannot collide with a charge row, which carries two amounts and no colon.
_FEE_BREAKDOWN = rf"^\s+(?P<label>[A-Za-z][A-Za-z0-9 /#'.,\-]*?):\s*\$(?P<amount>{MONEY})\s*$"


def _extract_fee_breakdown(match: re.Match[str] | None, line: str, ctx) -> dict:
    assert match is not None
    return {
        "amount": _money(match.group("amount")),
        "label": match.group("label").strip(),
    }


def _before_table(line: str, ctx: LineContext) -> bool:
    """True while no column header has been seen yet.

    Everything above the detail table is the letterhead and remit block. Matching
    it positionally covers every entity's address without listing any of them —
    the bill-to changes per file, and one file has four AP notes wedged in.
    """
    return ctx.last_row_of_kind(RowKind.COLUMN_HEADER) is None


_IGNORABLE_PATTERNS = (
    r"^\s*TYPE:\s",
    r"^\s*CODE:\s",
    r"Make Check Payable To",
    r"^\s*TERMS:",
    r"Tax ID:",
    r"^\s*PeopleFacts\s*$",
    r"Attn: Accounts Payable",
    r"Peak Drive",
    r"Las Vegas, NV",
    r"Fort Harrison",
    r"^\s*Page \d+ of \d+\s*$",
    r"Tel: \d",
    # GL coding and AP annotations stamped onto the page.
    r"^\s*\d{5}-\d{4}-\d{6}",
    r"^\s*\d{1,2}/\d{1,2}/\d{2,4}:",
    r"requested Excel spreadsheet",
    r"cannot be provided",
    r"Per [A-Z][a-z]+ [A-Z][a-z]+",
    r"^\s*(EMPLOYMENT SCREENING|UNIVERSAL|Pluto Acquisitions)",
)

RULES: list[Rule] = [
    Rule(RowKind.COLUMN_HEADER, _COLUMN_HEADER, zones=frozenset({"*"}),
         name="column_header"),
    Rule(RowKind.IGNORABLE, _HEADER_TAIL, zones=frozenset({"*"}),
         name="column_header_tail"),
    Rule(RowKind.COLUMN_TOTAL, _SEARCH_FEES, extract=_extract_search_fees,
         zones=frozenset({"*"}), name="search_fees_total"),
    Rule(RowKind.COLUMN_TOTAL, _COURT_FEES, extract=_extract_court_fees,
         zones=frozenset({"*"}), name="court_fees_total"),
    Rule(RowKind.GRAND_TOTAL, _TOTAL_DUE, extract=_extract_total_due,
         zones=frozenset({"*"}), name="total_due"),
    Rule(RowKind.RESTATEMENT, _FEE_BREAKDOWN, extract=_extract_fee_breakdown,
         zones=frozenset({"*"}), name="fee_breakdown"),
    Rule(RowKind.CHARGE, _CHARGE, extract=_extract_charge, name="charge_row"),
    Rule(RowKind.IGNORABLE, r"|".join(_IGNORABLE_PATTERNS), zones=frozenset({"*"}),
         name="boilerplate"),
    Rule(RowKind.HEADER_FIELD, r"^\s*Invoice:\s+\S+", zones=frozenset({"*"}),
         name="header_field"),
    Rule(RowKind.CONTINUATION, _CONTINUATION, guard=_continuation_guard,
         extract=_extract_continuation, zones=frozenset({"*"}),
         name="row_continuation"),
    # Positional catch-all for the letterhead. Last, so nothing structural is
    # swallowed by it.
    Rule(RowKind.IGNORABLE, r"^.+$", guard=_before_table, zones=frozenset({"*"}),
         name="letterhead"),
]


def _postprocess(rows: list[ClassifiedRow]) -> None:
    """Fold each wrapped token into the specific field it continues.

    Baxter wraps on every row, and not always the same column: the accession
    number continues Reference while a long middle name continues Middle. The
    column the token sits under decides where it goes, so a middle name never
    lands on a reference.
    """
    last_charge: ClassifiedRow | None = None
    for row in rows:
        if row.kind is RowKind.CHARGE:
            last_charge = row
        elif row.kind is RowKind.CONTINUATION and last_charge is not None:
            for target, text in row.fields.get("parts", []):
                existing = str(last_charge.fields.get(target, "") or "")
                # A token of one or two characters is the tail of a value the
                # report broke mid-way (`39291945.11517070` + `1`); a longer one
                # is a distinct value sharing the column (a `cbc 7178537`
                # reference followed by its accession number). Joining the first
                # kind with a space would invent a different identifier.
                separator = "" if len(text) <= 2 else " "
                last_charge.fields[target] = f"{existing}{separator}{text}".strip()


LADDER = [
    LevelCheck(
        "search_fees",
        computed_from=(RowKind.CHARGE,),
        printed_kind=RowKind.COLUMN_TOTAL,
        computed_field="search_fee",
        printed_field="search_fees_printed",
        description="the Search Fee column sums to the printed Search Fees",
    ),
    LevelCheck(
        "court_fees",
        computed_from=(RowKind.CHARGE,),
        printed_kind=RowKind.COLUMN_TOTAL,
        computed_field="court_fee",
        printed_field="court_fees_printed",
        description="the Court Fees column sums to the printed Court Fees",
    ),
    LevelCheck(
        "grand_total",
        computed_from=(RowKind.CHARGE,),
        printed_kind=RowKind.GRAND_TOTAL,
        description="both fee columns together sum to TOTAL DUE",
    ),
    LevelCheck(
        "row_count",
        computed_from=(RowKind.CHARGE,),
        printed_kind=RowKind.GRAND_TOTAL,
        mode=CheckMode.COUNT,
        printed_field="count",
        description="row count equals the printed Total Searches",
    ),
]

SPEC = InvoiceSpec(
    name="baxter",
    description="Baxter Research / PeopleFacts background searches (MS Access report)",
    rules=RULES,
    ladder=LADDER,
    postprocess=_postprocess,
    header_fields={
        "invoice_number": r"Invoice:\s+(\S+)",
        "total_searches": r"Total Searches:\s+(\d+)",
        "names": r"Names:\s+(\d+)",
        "akas": r"AKAs:\s+(\d+)",
    },
    line_item_fields=(
        "county",
        "type_code",
        "reference",
        "last_name",
        "first_name",
        "middle_name",
        "request_date",
        "code",
        "result",
        "court_fee",
        "search_fee",
    ),
    identity_fields=("invoice_number",),
)
