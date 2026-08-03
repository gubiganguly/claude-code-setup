"""Eagle Eye Screening Solutions, Inc background-search invoices (iText).

Structure:

    page 1..N     letterhead: Invoice Number / Date / Due Date, then a
                  "Bill To: ... Remit payment to:" block, two addresses on the
                  same physical lines
    INVOICE SUMMARY   a per-state restatement of the whole invoice, 3-286 pages in
                  and 1-4 pages long:
                    COUNTY CRIMINAL SEARCH            <- service section
                      CALIFORNIA  QTY  Avg. Price  Tot. Fees  Total
                        LOS ANGELES  129  $3.00  $548.25  $935.25
                      Sub Total: 129                        $935.25
                    STATEWIDE CRIMINAL SEARCH
                              QTY  Unit Price  Tot. Fees  Total   <- no state name
                        IDAHO  34  $5.00  $136.00  $306.00
                      Sub Total: 36                        $315.00
                  Grand Total: 565                          $5,661.20
    detail        the letterhead again, then
                    Date  Search ID  Description  Fees  Price   <- printed ONCE
                    12/03/24  4796765  MARIO RAMIREZ GOMEZ County Criminal
                              Search SACRAMENTO, CA        $30.00  $5.00
                                Court Fees: $30.00
    final block   Total Search Fees / [Total Rush Fees] / All Other Fees /
                  [* Total Alias Fees] / Total Court Fees / Grand Total /
                  Credit/Payments / Balance Due
                  "* These Fees are included in the Total Search Fees."

The column names are counter-intuitive and getting them backwards silently swaps
two columns that both reconcile: **`Fees` is the court/handling fee and `Price` is
the search fee.** `Total Search Fees` is the sum of the `Price` column;
`Total Court Fees` is part of the `Fees` column.

Discriminator: **a leading `mm/dd/yy` plus a numeric Search ID, then exactly two
trailing money tokens.** Nothing else on the page opens with a date. The front
summary rows carry three money tokens and no date; the totals block carries one.
Geometry is useless here — iText re-flows the whole table per page, so the same
invoice prints its Description column at character 21 on one page and character 1
on the next, and the detail column header is printed exactly ONCE and never
repeated, so there is no per-page header to read offsets from either.

Seven traps:

1. **A front summary with the same money-column geometry as the detail table.**
   It restates the entire invoice by state and county. Summing it doubles the
   invoice exactly. The cut is a ZONE on the detail column header: everything
   before it is summary. The header is printed once, on the first detail page, in
   all 32 text-layer files.

2. **`Grand Total:` is printed twice** — once ending the summary, carrying a row
   count (`Grand Total: 565   $5,661.20`), once on the final page without one.
   Same figure. Classifying both as GRAND_TOTAL would double the printed side, so
   the summary copy is an INVOICE_SUBTOTAL carrying its own named fields.

3. **Indented `Court Fees: $30.00` / `Alias Fees: $2.50` continuation lines
   itemise their row rather than adding to it,** and the two have identical shape
   with opposite meaning: `Court Fees:` decomposes the `Fees` column while
   `Alias Fees:` decomposes the `Price` column. They are RESTATEMENT: captured,
   never added to a charge. Matched structurally — an indented label ending in a
   colon followed by one amount — never by enumerating labels.

4. **Five competing fee totals, one of them footnoted as already counted.**
   `* Total Alias Fees` carries an asterisk and the page says
   "* These Fees are included in the Total Search Fees." Adding it to the others
   overstates. The asterisk is the discriminator, read from the line.

5. **AP-stamped GL codes land in the middle of vendor content**, including on the
   same physical line as a total (`50130-1500-125001    Total Search Fees:
   $15,114.50`) and on the same line as a page number
   (`50130-1500-125015-ybp   Page 13 of 14`). A total rule anchored to
   start-of-line misses six of these across the corpus; a description-wrap rule
   without an explicit GL rule in front of it appends `50130-1500-125001` to the
   last search's description.

6. **Descriptions wrap, and the wrap crosses page breaks.** `... County Criminal`
   on one line and `Search LOS ANGELES, CA` on the next, sometimes with the whole
   repeated letterhead or a page footer in between. 4,000+ occurrences. The money
   is on the first line, so the ladder cannot see the truncation.

7. **A summary row with no name at all.** The `TEST` service section prints
   `1  $0.00  $0.00  $0.00` with an empty county column and a `Sub Total: 1
   $0.00` behind it. A pattern requiring a non-empty name leaves the line
   unclassified, and `$0.00` groups mean the count rungs are the only thing that
   would notice a dropped one.

8. **A detail row whose description cell is printed *empty*.** When the name is
   long enough, iText emits `01/23/25   4939259        $0.00   $1.50` and puts
   the whole description on the first line of the next page. 14 rows on invoice
   4531, 5 on 4960, 4 on 5075. A row pattern requiring a non-empty description
   drops the row *and its money*: those files came up $78.75, $8.75 and $6.00
   short until the description was made optional.

Correction to an earlier reading of this vendor, worth stating precisely because
it was previously recorded as a vendor arithmetic error: **Eagle Eye's printed
arithmetic is exact on all 32 text-layer invoices.** `Total Court Fees` was
reported as $82.00 wrong on invoice 4610 ($1,775.50 printed against a $1,857.50
column sum) and $3.00 wrong on 5631. It is not. The `Fees` column decomposes into
*three* printed totals, not one:

    Total Rush Fees + All Other Fees + Total Court Fees == sum(Fees)

On 4610 that is $0.00 + $82.00 + $1,775.50 = $1,857.50, exactly the column sum.
On 5631 it is $0.00 + $3.00 + $2,281.00 = $2,284.00. The earlier comparison
omitted `All Other Fees`, which is printed on 28 of the 32 files, and
`Total Rush Fees`, which appears on two. Every rung below therefore runs at zero
tolerance and every one of them closes on every file.

Two engine limitations this spec had to work around rather than fix:

- `Document.needs_ocr` is true if *any* page falls under 200 characters, and 15 of
  these 32 files print one legitimately sparse page (a page carrying only
  `Grand Total: 225   $1,054.50`, or a short final page). `profile().usable_text`
  therefore rejects them. Only 5388, which is a two-page scan with no text at all,
  genuinely needs OCR. Gating on document-level `chars_per_page` instead separates
  the two cleanly (0.0 for 5388, 1,914-3,020 for the rest).
- `LineContext.lines` holds one page, so lookahead cannot cross a page break. The
  service-section banner rule wants the table header that follows it, and on three
  invoices that header opens the next page; the guard steps over the page footer
  and then falls back to looking backwards instead.
"""

from __future__ import annotations

import re
from decimal import Decimal

from engine.classify import ClassifiedRow, LineContext, RowKind, Rule, ZoneMarker
from engine.money import parse_money
from engine.reconcile import CheckMode, LevelCheck
from engine.spec import InvoiceSpec

MONEY = r"[\d,]+\.\d{2}"
DETAIL = "detail"

# A total may be preceded on the same physical line by an AP-stamped GL code, so
# these anchor on "start of line, or after a gap" rather than on `^`.
LEAD = r"(?:^|\s{2,})"


def _money(raw: str) -> Decimal:
    value = parse_money(raw)
    if value is None:  # pragma: no cover - the classifier rejects this first
        raise ValueError(f"unparseable amount {raw!r}")
    return value


# ---------------------------------------------------------------------------
# Detail rows
# ---------------------------------------------------------------------------

# The description is optional. When a name is long enough that the whole cell
# overflows, iText prints the row with an *empty* description and puts the text on
# the first line of the next page — 14 rows on invoice 4531 alone. Requiring a
# non-empty description drops those rows, and the money goes with them.
_CHARGE = (
    r"^\s*(?P<search_date>\d{2}/\d{2}/\d{2})\s+"
    r"(?P<search_id>\d+)\s+"
    r"(?P<description>\S.*?)?\s*"
    rf"\$(?P<fees>{MONEY})\s+\$(?P<price>{MONEY})\s*$"
)


def _extract_charge(match: re.Match[str] | None, line: str, ctx) -> dict:
    assert match is not None
    # `Fees` is the court/handling fee and `Price` is the search fee, despite
    # `Total Search Fees` sitting under the label that looks like it belongs to
    # `Fees`. Both are stored under names that say which is which, so the
    # per-column rungs cannot be wired up backwards without failing.
    court = _money(match.group("fees"))
    search = _money(match.group("price"))
    return {
        # The row's whole charge, so the grand-total rung needs no special case.
        "amount": court + search,
        "court_fee": court,
        "search_fee": search,
        "search_date": match.group("search_date"),
        "search_id": match.group("search_id"),
        "description": re.sub(r"\s+", " ", (match.group("description") or "").strip()),
    }


# ---------------------------------------------------------------------------
# Front summary: a per-state, per-county restatement of the whole invoice
# ---------------------------------------------------------------------------

# "CALIFORNIA   QTY  Avg. Price  Tot. Fees  Total", or the same with no state
# name at all in the statewide sections, where the rows are themselves states.
_SUMMARY_TABLE_HEADER = (
    r"^\s*(?P<state>\S.*?)?\s*QTY\s+(?P<price_label>[A-Za-z.]+\s*Price)\s+"
    r"Tot\.\s*Fees\s+Total\s*$"
)

# "LOS ANGELES  129  $3.00  $548.25  $935.25". The name is optional: the TEST
# section prints a row with an empty name and three zero amounts.
_SUMMARY_ROW = (
    r"^\s*(?P<name>\S.*?)?\s*(?P<qty>\d+)\s+"
    rf"\$(?P<unit_price>{MONEY})\s+\$(?P<tot_fees>{MONEY})\s+\$(?P<amount>{MONEY})\s*$"
)

_SUB_TOTAL = rf"^\s*Sub Total:\s*(?P<count>\d+)\s+\$(?P<amount>{MONEY})\s*$"


def _extract_summary_row(match: re.Match[str] | None, line: str, ctx: LineContext) -> dict:
    assert match is not None
    header = ctx.last_row_of_kind(RowKind.SECTION_HEADER)
    state = header.fields.get("state", "") if header is not None else ""
    section = header.fields.get("section", "") if header is not None else ""
    return {
        "amount": _money(match.group("amount")),
        "summary_section": section,
        "summary_state": state,
        "summary_name": (match.group("name") or "").strip(),
        "qty": match.group("qty"),
        "unit_price": _money(match.group("unit_price")),
        # Not the same thing as the detail `Fees` column: this one also carries
        # the alias fees, which the detail table books inside `Price`.
        "tot_fees": _money(match.group("tot_fees")),
    }


def _extract_sub_total(match: re.Match[str] | None, line: str, ctx) -> dict:
    assert match is not None
    return {
        "amount": _money(match.group("amount")),
        "count": match.group("count"),
    }


def _section_header_guard(line: str, ctx: LineContext) -> bool:
    """A bare all-caps line is a service section banner, not a wrapped tail.

    Normally decided by lookahead: a banner is immediately followed by its table
    header. But `LineContext.lines` holds one page, so the lookahead goes blind
    when the banner is the last line of a page and its table header opens the
    next one — which is where `STATEWIDE CRIMINAL SEARCH` and `TEST` sit on three
    invoices. In that case fall back to looking *backwards*: the two things this
    rule must not steal are wrapped description tails, and those only ever hang
    beneath a charge or a summary row, which is exactly what `_wrap_anchor` tests.
    A banner follows a printed `Sub Total:` instead.
    """
    for skip in range(4):
        following = ctx.next_nonblank(skip)
        if following is None:
            break
        if _TABLE_HEADER_RE.match(following):
            return True
        # A page footer between the banner and its table header means the header
        # is on the next page, out of reach of this page's lookahead.
        if _PAGE_FOOTER_RE.search(following):
            continue
        return False
    return _wrap_anchor(line, ctx) is None


_TABLE_HEADER_RE = re.compile(_SUMMARY_TABLE_HEADER)
_PAGE_FOOTER_RE = re.compile(r"(?:^|\s)Page \d+ of \d+\s*$")


# ---------------------------------------------------------------------------
# Printed totals
# ---------------------------------------------------------------------------

# "Total Search Fees: $506.25", "* Total Alias Fees: $211.75",
# "Total Court Fees: $548.25", "Total Rush Fees: $10.00". Matched as a family
# rather than as four labels, so a new fee category cannot be silently dropped:
# it lands in the Fees column, which is the side the ladder checks.
_FEE_TOTAL = (
    LEAD + r"(?P<star>\*\s*)?Total\s+(?P<category>[A-Za-z][A-Za-z. ]*?)\s+Fees:\s+"
    rf"\$(?P<amount>{MONEY})\s*$"
)
_OTHER_FEES = LEAD + rf"All Other Fees:\s+\$(?P<amount>{MONEY})\s*$"
_SUMMARY_GRAND_TOTAL = (
    LEAD + rf"Grand Total:\s+(?P<count>\d+)\s+\$(?P<amount>{MONEY})\s*$"
)
_GRAND_TOTAL = LEAD + rf"Grand Total:\s+\$(?P<amount>{MONEY})\s*$"
_BALANCE_DUE = LEAD + rf"Balance Due:\s+\$(?P<amount>{MONEY})\s*$"
# Parenthesised *and* signed: "(-$0.00)" on all 32 files. `parse_money` cannot
# read a minus that sits between the bracket and the currency symbol, so the
# sign is taken from the match and applied here.
_CREDIT = LEAD + rf"Credit/Payments:\s+\((?P<neg>-)?\$(?P<amount>{MONEY})\)\s*$"


def _extract_fee_total(match: re.Match[str] | None, line: str, ctx) -> dict:
    assert match is not None
    value = _money(match.group("amount"))
    category = re.sub(r"\s+", " ", match.group("category").strip())
    fields: dict = {"amount": value, "fee_category": category}
    if category.lower() == "search":
        # The one category that totals the `Price` column.
        fields["total_search_fees"] = value
        return fields
    # Everything else totals part of the `Fees` column. The asterisk means the
    # invoice has already counted it inside Total Search Fees, so it belongs to
    # the summary's Tot. Fees column but not to the detail's Fees column.
    fields["summary_fees_component"] = value
    if not match.group("star"):
        fields["fees_column_component"] = value
    return fields


def _extract_other_fees(match: re.Match[str] | None, line: str, ctx) -> dict:
    assert match is not None
    value = _money(match.group("amount"))
    return {
        "amount": value,
        "fee_category": "All Other",
        "summary_fees_component": value,
        "fees_column_component": value,
    }


def _extract_summary_grand_total(match: re.Match[str] | None, line: str, ctx) -> dict:
    assert match is not None
    value = _money(match.group("amount"))
    return {
        "amount": value,
        "summary_grand_total": value,
        "row_count": match.group("count"),
    }


def _named(field: str):
    def extract(match: re.Match[str] | None, line: str, ctx) -> dict:
        assert match is not None
        value = _money(match.group("amount"))
        return {"amount": value, field: value}

    return extract


def _extract_credit(match: re.Match[str] | None, line: str, ctx) -> dict:
    assert match is not None
    value = _money(match.group("amount"))
    if match.group("neg"):
        value = -value
    return {"amount": value, "credit_payments": value}


# ---------------------------------------------------------------------------
# Fee decomposition lines
# ---------------------------------------------------------------------------

# "Court Fees: $30.00" / "Alias Fees: $2.50" / "Misc. Additional Fees: $19.00" /
# "Rush Fees: $10.00", indented under the row they itemise. Deliberately
# label-blind: the shape is an indented label ending in a colon followed by
# exactly one amount, which cannot collide with a charge row (two amounts, a
# leading date, no colon). Every invoice-level total is claimed by an earlier
# rule, so only per-row decompositions reach here.
_FEE_BREAKDOWN = (
    r"^\s+(?P<label>[A-Za-z][A-Za-z0-9 ./#'&,()\-]*?):\s+"
    rf"\$(?P<amount>{MONEY})\s*$"
)


def _extract_fee_breakdown(match: re.Match[str] | None, line: str, ctx) -> dict:
    assert match is not None
    return {
        "amount": _money(match.group("amount")),
        "fee_label": re.sub(r"\s+", " ", match.group("label").strip()),
    }


# ---------------------------------------------------------------------------
# Structure and noise
# ---------------------------------------------------------------------------

_DETAIL_HEADER = r"^\s*Date\s+Search ID\s+Description\s+Fees\s+Price\s*$"

_HEADER_FIELD = r"^\s*(?:Invoice Number|Invoice Date|Due Date)\s*:?\s+\S"

_IGNORABLE_PATTERNS = (
    r"^\s*INVOICE SUMMARY\s*$",
    r"Remit payment to:",
    # The remit block is constant while the bill-to entity changes per file, and
    # the two share physical lines. Keying on the remit side covers every
    # entity's address without naming any of them.
    r"Eagle Eye Screening Solutions, Inc",
    r"2621 Green River Road",
    r"S# 105-112",
    r"Corona, CA 92882",
    r"Tel\. \(\d{3}\) \d{3}-\d{4}",
    r"^\s*Bill To:",
    r"These Fees are included in the",
    # An AP-stamped GL code, alone on a line or sharing one with a page number.
    r"^\s*\d{4,6}(?:\s*-\s*[0-9A-Za-z]+)+\s*$",
    r"(?:^|\s)Page \d+ of \d+\s*$",
)


def _wrap_anchor(line: str, ctx: LineContext) -> ClassifiedRow | None:
    """The row a right-indented bare line continues, or None.

    A description wraps from the last row of one page onto the first body line of
    the next, with the page footer, the repeated letterhead or the reprinted
    header block in between, so the structural kinds are stepped over. A wrap can
    also sit above its own row's fee-decomposition lines or below them, so
    RESTATEMENT counts as an anchor too.
    """
    if "$" in line:
        return None
    for row in reversed(ctx.prev_rows):
        if row.kind in (
            RowKind.IGNORABLE,
            RowKind.HEADER_FIELD,
            RowKind.COLUMN_HEADER,
        ):
            continue
        if row.kind in (RowKind.CHARGE, RowKind.GROUP_SUBTOTAL):
            return row
        if row.kind in (RowKind.CONTINUATION, RowKind.RESTATEMENT):
            continue
        return None
    return None


def _wrap_guard(line: str, ctx: LineContext) -> bool:
    return _wrap_anchor(line, ctx) is not None


def _extract_wrap(match: re.Match[str] | None, line: str, ctx: LineContext) -> dict:
    assert match is not None
    anchor = _wrap_anchor(line, ctx)
    target = (
        "summary_name"
        if anchor is not None and anchor.kind is RowKind.GROUP_SUBTOTAL
        else "description"
    )
    return {"text": re.sub(r"\s+", " ", match.group("text").strip()), "target": target}


_WRAP = r"^\s{2,}(?P<text>\S.*?)\s*$"


RULES: list[Rule] = [
    # --- Printed totals. First, because a GL code or a fee-decomposition shape
    # can otherwise claim them.
    Rule(RowKind.COLUMN_TOTAL, _FEE_TOTAL, extract=_extract_fee_total,
         zones=frozenset({"*"}), name="fee_category_total"),
    Rule(RowKind.COLUMN_TOTAL, _OTHER_FEES, extract=_extract_other_fees,
         zones=frozenset({"*"}), name="all_other_fees"),
    # The summary copy carries the row count; the final-page copy does not. Must
    # precede the countless rule, whose pattern is a prefix of this one.
    Rule(RowKind.INVOICE_SUBTOTAL, _SUMMARY_GRAND_TOTAL,
         extract=_extract_summary_grand_total, zones=frozenset({"*"}),
         name="summary_grand_total"),
    Rule(RowKind.GRAND_TOTAL, _GRAND_TOTAL, extract=_named("grand_total"),
         zones=frozenset({"*"}), name="grand_total"),
    Rule(RowKind.COLUMN_TOTAL, _BALANCE_DUE, extract=_named("balance_due"),
         zones=frozenset({"*"}), name="balance_due"),
    Rule(RowKind.COLUMN_TOTAL, _CREDIT, extract=_extract_credit,
         zones=frozenset({"*"}), name="credit_payments"),

    # --- Front summary. Body zone only: the zone marker on the detail column
    # header is what stops these rules from reading the detail table.
    Rule(
        RowKind.SECTION_HEADER,
        _SUMMARY_TABLE_HEADER,
        extract=lambda m, ln, ctx: {
            "state": (m.group("state") or "").strip(),
            "price_label": re.sub(r"\s+", " ", m.group("price_label")),
            "section": (
                (ctx.last_row_of_kind(RowKind.SECTION_HEADER).fields.get("section", "")
                 if ctx.last_row_of_kind(RowKind.SECTION_HEADER) else "")
            ),
        },
        name="summary_table_header",
    ),
    Rule(RowKind.SECTION_SUBTOTAL, _SUB_TOTAL, extract=_extract_sub_total,
         name="state_sub_total"),
    Rule(RowKind.GROUP_SUBTOTAL, _SUMMARY_ROW, extract=_extract_summary_row,
         name="summary_row"),

    # --- Detail rows.
    Rule(RowKind.CHARGE, _CHARGE, extract=_extract_charge,
         zones=frozenset({DETAIL}), name="search_row"),

    # --- Per-row fee decomposition. After the totals, before the wrap rule.
    Rule(RowKind.RESTATEMENT, _FEE_BREAKDOWN, extract=_extract_fee_breakdown,
         zones=frozenset({"*"}), name="fee_breakdown"),

    Rule(RowKind.HEADER_FIELD, _HEADER_FIELD, zones=frozenset({"*"}),
         name="header_field"),
    Rule(RowKind.IGNORABLE, r"|".join(_IGNORABLE_PATTERNS), zones=frozenset({"*"}),
         name="boilerplate"),
    # Service-section banner. Guarded on the table header that must follow, so it
    # cannot swallow a wrapped description tail.
    Rule(
        RowKind.SECTION_HEADER,
        r"^\s*(?P<section>[A-Z][A-Z0-9 ()\-/.&]*[A-Z0-9)])\s*$",
        guard=_section_header_guard,
        extract=lambda m, ln, ctx: {"section": m.group("section").strip(), "state": ""},
        zones=frozenset({"*"}),
        name="summary_section_header",
    ),
    # Last of the shape-based rules: every piece of known boilerplate is already
    # claimed above, so an indented bare line here really is a wrapped tail.
    Rule(RowKind.CONTINUATION, _WRAP, guard=_wrap_guard, extract=_extract_wrap,
         zones=frozenset({"*"}), name="description_wrap"),
]

ZONE_MARKERS = [
    # Printed exactly once, on the first detail page, in all 32 text-layer files.
    # Everything above it is the front summary.
    ZoneMarker(_DETAIL_HEADER, DETAIL, kind=RowKind.COLUMN_HEADER,
               name="detail_column_header"),
]


# ---------------------------------------------------------------------------
# Post-processing
# ---------------------------------------------------------------------------


def _postprocess(rows: list[ClassifiedRow]) -> None:
    """Fold wrapped tails, key the summary groups, and net the credit off Balance Due."""
    anchor: ClassifiedRow | None = None
    for row in rows:
        if row.kind in (RowKind.CHARGE, RowKind.GROUP_SUBTOTAL):
            anchor = row
        elif row.kind is RowKind.CONTINUATION and anchor is not None:
            target = row.fields.get("target", "description")
            extra = row.fields.get("text", "")
            if extra:
                base = str(anchor.fields.get(target, "") or "")
                anchor.fields[target] = f"{base} {extra}".strip()

    # One group per printed table header. Keying on an incrementing index rather
    # than on the state name is what makes the statewide sections work: their
    # table header carries no name at all, and the same state can legitimately
    # appear under two different service sections.
    group = -1
    for row in rows:
        if row.kind is RowKind.SECTION_HEADER and row.rule == "summary_table_header":
            group += 1
        elif row.kind in (RowKind.GROUP_SUBTOTAL, RowKind.SECTION_SUBTOTAL):
            row.fields["state_key"] = f"g{group}"

    # Balance Due = Grand Total + Credit/Payments, with the credit carried as a
    # signed figure. Netting it here lets the rung compare like with like instead
    # of silently passing only while every credit happens to be zero.
    credit = sum(
        (r.fields["credit_payments"] for r in rows if "credit_payments" in r.fields),
        Decimal("0.00"),
    )
    for row in rows:
        if "balance_due" in row.fields:
            row.fields["balance_due_gross"] = row.fields["balance_due"] - credit


# ---------------------------------------------------------------------------
# The ladder
# ---------------------------------------------------------------------------

LADDER = [
    LevelCheck(
        "grand_total",
        computed_from=(RowKind.CHARGE,),
        printed_kind=RowKind.GRAND_TOTAL,
        description="Fees plus Price over every search row equals the final "
                    "Grand Total",
    ),
    LevelCheck(
        "search_fees",
        computed_from=(RowKind.CHARGE,),
        printed_kind=RowKind.COLUMN_TOTAL,
        computed_field="search_fee",
        printed_field="total_search_fees",
        description="the Price column sums to Total Search Fees",
    ),
    LevelCheck(
        "court_and_other_fees",
        computed_from=(RowKind.CHARGE,),
        printed_kind=RowKind.COLUMN_TOTAL,
        computed_field="court_fee",
        printed_field="fees_column_component",
        description="the Fees column sums to Total Rush Fees plus All Other Fees "
                    "plus Total Court Fees — the asterisked Total Alias Fees is "
                    "excluded because the invoice counts it inside Total Search Fees",
    ),
    LevelCheck(
        "balance_due",
        computed_from=(RowKind.GRAND_TOTAL,),
        printed_kind=RowKind.COLUMN_TOTAL,
        printed_field="balance_due_gross",
        description="Balance Due net of Credit/Payments equals the Grand Total",
    ),
    LevelCheck(
        "summary_grand_total",
        computed_from=(RowKind.CHARGE,),
        printed_kind=RowKind.INVOICE_SUBTOTAL,
        printed_field="summary_grand_total",
        description="the search rows sum to the Grand Total ending the front summary",
    ),
    LevelCheck(
        "row_count",
        computed_from=(RowKind.CHARGE,),
        printed_kind=RowKind.INVOICE_SUBTOTAL,
        mode=CheckMode.COUNT,
        printed_field="row_count",
        description="row count equals the integer on the summary Grand Total line — "
                    "the only rung that can see a dropped $0.00 row, and whole "
                    "summary groups are $0.00",
    ),
    LevelCheck(
        "state_sub_total",
        computed_from=(RowKind.GROUP_SUBTOTAL,),
        printed_kind=RowKind.SECTION_SUBTOTAL,
        group_by="state_key",
        description="each summary table's county rows sum to its printed Sub Total",
    ),
    LevelCheck(
        "state_sub_total_counts",
        computed_from=(RowKind.GROUP_SUBTOTAL,),
        printed_kind=RowKind.SECTION_SUBTOTAL,
        computed_field="qty",
        printed_field="count",
        group_by="state_key",
        description="each summary table's QTY column sums to its printed Sub Total count",
    ),
    LevelCheck(
        "summary_sub_totals",
        computed_from=(RowKind.SECTION_SUBTOTAL,),
        printed_kind=RowKind.INVOICE_SUBTOTAL,
        printed_field="summary_grand_total",
        description="the per-state Sub Totals sum to the summary Grand Total",
    ),
    LevelCheck(
        "summary_sub_total_counts",
        computed_from=(RowKind.SECTION_SUBTOTAL,),
        printed_kind=RowKind.INVOICE_SUBTOTAL,
        computed_field="count",
        printed_field="row_count",
        description="the per-state Sub Total counts sum to the printed row count",
    ),
    LevelCheck(
        "summary_qty",
        computed_from=(RowKind.GROUP_SUBTOTAL,),
        printed_kind=RowKind.INVOICE_SUBTOTAL,
        computed_field="qty",
        printed_field="row_count",
        description="the summary QTY column sums to the printed row count",
    ),
    LevelCheck(
        "summary_tot_fees",
        computed_from=(RowKind.GROUP_SUBTOTAL,),
        printed_kind=RowKind.COLUMN_TOTAL,
        computed_field="tot_fees",
        printed_field="summary_fees_component",
        description="the summary Tot. Fees column sums to every non-search fee "
                    "total including the asterisked alias fees — which is how the "
                    "summary column differs from the detail Fees column",
    ),
    LevelCheck(
        "fee_breakdown",
        computed_from=(RowKind.RESTATEMENT,),
        printed_kind=RowKind.COLUMN_TOTAL,
        printed_field="summary_fees_component",
        description="the indented per-row fee itemisations sum to the same "
                    "non-search fee totals, so they are accounted for without "
                    "ever being added to a charge",
    ),
    LevelCheck(
        "summary_restatement",
        computed_from=(RowKind.CHARGE,),
        printed_kind=RowKind.GROUP_SUBTOTAL,
        required=False,
        description="the whole per-state front summary restates the same money as "
                    "the detail table",
    ),
]

SPEC = InvoiceSpec(
    name="eagleeye",
    description="Eagle Eye Screening Solutions background searches (iText)",
    rules=RULES,
    zone_markers=ZONE_MARKERS,
    ladder=LADDER,
    postprocess=_postprocess,
    header_fields={
        "invoice_number": r"Invoice Number\s*:?\s+(\S+)",
        "invoice_date": r"Invoice Date\s*:?\s+(\d{2}/\d{2}/\d{4})",
        "due_date": r"Due Date\s*:?\s+(\d{2}/\d{2}/\d{4})",
        "bill_to": r"^\s(\S.*?)\s{2,}Eagle Eye Screening Solutions, Inc\s*$",
        "total_search_fees": r"Total Search Fees:\s+\$([\d,]+\.\d{2})",
        "total_court_fees": r"Total Court Fees:\s+\$([\d,]+\.\d{2})",
        "grand_total": r"Grand Total:\s+\$([\d,]+\.\d{2})",
        "balance_due": r"Balance Due:\s+\$([\d,]+\.\d{2})",
    },
    line_item_fields=(
        "search_date",
        "search_id",
        "description",
        "court_fee",
        "search_fee",
    ),
    identity_fields=("invoice_number",),
)
