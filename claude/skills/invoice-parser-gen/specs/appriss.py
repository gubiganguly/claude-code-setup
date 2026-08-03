"""Appriss Insights LLC / Equifax background-screening invoices (Oracle BI Publisher).

Structure:

    page 1        letterhead + Account Summary + remit stub + barcode scanline
                    Previous Account Balance / Current Invoice Subtotal /
                    Current Tax Subtotal / Current Invoice Total /
                    Total Account Balance:
    SERVICE SUMMARY
      segment A   "ALL LOCATIONS" then one row per service x item, ungrouped
                  └─ bare "Service Summary Total" with its value on the NEXT line
      segment B   the SAME charges again, regrouped by service type under
                  "County Civil from 01/01/2025-01/31/2025" subheaders
                  └─ "Location:000. Total"
                  └─ inline "Service Summary Total   $74,955.81"
                  └─ "Service Subtotal   $74,955.81"
    TAX SUMMARY   one row per jurisdiction x product class
                  └─ "Tax Subtotal" then "CURRENT INVOICE TOTAL"
    STATEMENT OF ACCOUNT   aging page: every open invoice, ending in
                  "TOTAL ACCOUNT BALANCE"
    last page     "**** Intentionally left blank****"

Discriminator: **a five-decimal unit rate.** `118  0.09000  $10.62` — no other line
in the document carries a `\\d+\\.\\d{5}` token. The tax table's rate column prints
three decimals (`0.065`) or a bare `0`, the aging page prints none, and every
printed sum carries exactly one money token and no rate at all. 14,722 rate lines
across the 33 text-layer files, all matched by one pattern.

Six traps, each of which reconciles perfectly if mishandled:

1. **The entire detail block is printed twice.** Segment B is the same charges
   regrouped by service type. Naive parsing overstates by exactly 100%: on
   invoice 2064179441 segment A is 2,521 rows summing to $74,564.51 and segment B
   is 2,521 rows summing to $74,564.51, against a printed Current Invoice
   Subtotal of $74,564.51. The cut is a ZONE on the bare `Service Summary Total`
   marker; segment B becomes RESTATEMENT and is never summed into the invoice.
   `ALL LOCATIONS` looks like the segment-A opener but one file
   (2065086576) omits it, so it cannot be the marker.

2. **Twelve competing total labels, and the largest is wrong.**
   `Total Account Balance: $149,739.57` is `Previous Account Balance $74,680.19`
   plus `Current Invoice Total $75,059.38`. The grand total is
   `Current Invoice Total`. "Pick the largest" is wrong on 24 of the 33 files.

3. **The same label with two layouts in one document.** The first
   `Service Summary Total` prints its value on the following line; the second
   prints it inline. They are the same figure, so classifying both as one kind
   would double the printed side of the rung. Each gets its own named field.

4. **The TAX SUMMARY `Non-Taxable Amount` column restates the whole invoice
   subtotal once per jurisdiction** — three jurisdictions on a PeopleFacts
   invoice, each showing the full $1,231.29 against a `Total` of $0.00. Only the
   `Total` column is money owed, and it does sum to the printed `Tax Subtotal` on
   all 33 files, which buys a rung nobody would expect from a decoy table.

5. **Wrapped descriptions, both right-indented and column-0.** 1,594 bare `COURT`
   lines and 244 `DISTRICT COURT` lines continue
   `... CRIM AL NORTHERN DISTRICT` from the row above, and the wrap crosses page
   breaks with the whole repeated page-header block in between. Separately,
   `PUBLIC TRANSPORTATION BENEFIT AREA` wraps at column 0 inside the tax table.
   Money is unaffected, so the ladder cannot see either one.

6. **A STATEMENT OF ACCOUNT aging page and a trailing blank page.** The aging
   rows carry `Transaction Amount` and `Open Balance` columns holding real
   dollar figures for invoices billed months ago, and the final page contains
   literally `**** Intentionally left blank****`.

Not in the earlier reconnaissance, and worth naming: the restatement is **not**
byte-identical on the four-page single-service invoices. Segment A appends the
customer's GL / cost-centre code to the description (`FACT 50130-1500-113000-004`,
and one file prints it spaced as `50130 - 1500 - 113000-113004`), segment B prints
the bare service name. The quantities, rates and amounts are identical, so the
money rungs hold, but a description-equality test would fail on 9 of 33 files.
Positional pairing of the two segments holds on all 33 (same row count, same
`(product class, quantity, rate, amount)` tuple at every index, segment A's
description always starting with segment B's), and postprocess uses that to lift
the service group and the GL suffix onto the charge rows.

Two more surprises worth naming:

- The customer's GL / cost-centre code is not always inside a detail row. On one
  file it is appended to the `ALL LOCATIONS` header
  (`ALL LOCATIONS 50130-1500-113000-004`) and on another it wraps to the line
  *below* that header, so the location header is itself wrappable.
- The tax jurisdiction name wraps at column 0, not right-indented:
  `PUBLIC TRANSPORTATION` / `BENEFIT AREA`. The right-indent shape that catches
  every description wrap cannot reach it.

Two engine limitations this spec had to work around rather than fix:

- `Document.needs_ocr` is true if *any* page falls under 200 characters, and every
  one of these invoices ends with a page reading
  `**** Intentionally left blank****`. `profile().usable_text` therefore rejects
  all 33 readable files. Gating on document-level `chars_per_page` separates them
  cleanly: the 33 readable files run 633-3,239 chars/page and the 18 scans run
  0-22.
- `CheckMode.COUNT` compares a row count against a printed integer field and
  cannot compare it against the row count of another kind, so "the restatement
  holds the same number of rows as the detail block" is not expressible as a rung.
  The equal-length test lives in `_postprocess` instead, where a mismatch
  suppresses the service-group lift rather than flagging the invoice.
"""

from __future__ import annotations

import re
from decimal import Decimal

from engine.classify import ClassifiedRow, LineContext, RowKind, Rule, ZoneMarker
from engine.money import parse_money
from engine.reconcile import LevelCheck
from engine.spec import InvoiceSpec

MONEY = r"[\d,]+\.\d{2}"
RESTATED = "restated"
ZONE_MARKER_NAME = "zone:service_summary_break"


def _money(raw: str) -> Decimal:
    value = parse_money(raw)
    if value is None:  # pragma: no cover - the classifier rejects this first
        raise ValueError(f"unparseable amount {raw!r}")
    return value


# ---------------------------------------------------------------------------
# Detail rows. One pattern, used twice: as CHARGE in the body zone and as
# RESTATEMENT in the restated zone. Identical shape, opposite meaning.
# ---------------------------------------------------------------------------

# The printed header labels exactly one text column ("Description"), so the
# leading product-class digit and the service/item text inside that column are
# taken as they come rather than sliced on offsets that shift page to page
# (Description sits at column 28 on page 2 and column 22 on page 3 of the same
# file). `\s{2,}` before the quantity is what makes the head/tail split safe:
# descriptions contain digits (`50130-1500-113000-004`) and the separator run in
# front of the quantity column is never a single space.
_DETAIL = (
    r"^(?P<product_class>\d+)\s+"
    r"(?P<description>.*?)\s{2,}"
    r"(?P<quantity>[\d,]+)\s+"
    r"(?P<unit_rate>\d+\.\d{5})\s+"
    rf"\$(?P<amount>{MONEY})\s*$"
)


def _extract_detail(match: re.Match[str] | None, line: str, ctx: LineContext) -> dict:
    assert match is not None
    group_row = ctx.last_row_of_kind(RowKind.SECTION_HEADER)
    return {
        "amount": _money(match.group("amount")),
        "product_class": match.group("product_class"),
        # Whitespace inside the Description cell is padding between an
        # unlabelled service-name sub-column and the item code, and the width of
        # that padding varies per page. Collapsing it keeps the same logical
        # description stable across both segments so the two can be paired.
        "description": re.sub(r"\s+", " ", match.group("description").strip()),
        "quantity": match.group("quantity").replace(",", ""),
        "unit_rate": match.group("unit_rate"),
        # Only meaningful in the restated zone, where the rows sit under a
        # "<service> from <date>-<date>" subheader. Segment A has no grouping;
        # postprocess lifts the group across.
        "service_group": (group_row.fields.get("service_group", "") if group_row else ""),
        "service_name": "",
        "gl_code": "",
    }


# ---------------------------------------------------------------------------
# Tax table. The Total column is the only money owed; Non-Taxable Amount
# restates the whole invoice subtotal once per jurisdiction and Taxable Amount
# restates the taxed portion. All three are kept as fields — dropping a column
# because it is a decoy is how a real charge goes missing when a vendor starts
# using it.
# ---------------------------------------------------------------------------

_TAX_ROW = (
    r"^(?P<jurisdiction>\S.*?)\s{2,}"
    r"(?P<product_class>\d+) - (?P<product>\S.*?)\s{2,}"
    r"(?P<rate>\d+(?:\.\d+)?)\s+"
    rf"\$(?P<non_taxable>{MONEY})\s+"
    rf"\$(?P<taxable>{MONEY})\s+"
    rf"\$(?P<total>{MONEY})\s*$"
)


def _extract_tax_row(match: re.Match[str] | None, line: str, ctx) -> dict:
    assert match is not None
    return {
        "amount": _money(match.group("total")),
        "jurisdiction": match.group("jurisdiction").strip(),
        "tax_product_class": match.group("product_class"),
        "tax_product": match.group("product").strip(),
        "tax_rate": match.group("rate"),
        "non_taxable_amount": _money(match.group("non_taxable")),
        "taxable_amount": _money(match.group("taxable")),
    }


# ---------------------------------------------------------------------------
# Printed sums. Every one of the twelve total-like labels gets its own field so
# that no two of them land on the same side of the same rung — several of them
# print the identical figure, and summing a printed side twice is exactly the
# failure the ladder exists to catch.
# ---------------------------------------------------------------------------


def _named(field: str):
    def extract(match: re.Match[str] | None, line: str, ctx) -> dict:
        assert match is not None
        value = _money(match.group("amount"))
        return {"amount": value, field: value}

    return extract


def _extract_location_total(match: re.Match[str] | None, line: str, ctx) -> dict:
    assert match is not None
    value = _money(match.group("amount"))
    return {
        "amount": value,
        "location_total": value,
        "location_code": match.group("location").rstrip("."),
    }


def _orphan_value_guard(line: str, ctx: LineContext) -> bool:
    """The bare `Service Summary Total` prints its figure on the next line.

    Recognised by position rather than by shape: a lone money token is otherwise
    indistinguishable from a dozen other right-aligned amounts, and the only
    thing that makes this one the segment-A total is that the zone marker is
    directly above it.
    """
    previous = ctx.prev_row
    return previous is not None and previous.rule == ZONE_MARKER_NAME


# ---------------------------------------------------------------------------
# Structure and noise
# ---------------------------------------------------------------------------

_DETAIL_HEADER = r"^\s+Description\s+Quantity\s+Unit Amount\s+Amount\s*$"
_TAX_HEADER = (
    r"^Jurisdiction\s+Product\s+Rate\s+Non-Taxable Amount\s+Taxable Amount\s+Total\s*$"
)
_AGING_HEADER = r"^Transaction Date\s+Days Outstanding\s+Description\s+Transaction Number"

# "County Criminal Search from 01/01/2025-01/31/2025"
_SERVICE_GROUP = r"^(?P<service_group>\S.*?) from (?P<from>\d{2}/\d{2}/\d{4})-(?P<to>\d{2}/\d{2}/\d{4})\s*$"

# Opens segment A. Usually bare, but one file prints the customer's
# cost-centre code on the same line ("ALL LOCATIONS 50130-1500-113000-004"), so
# the trailing text is captured rather than the line being matched exactly. And
# one file omits the line altogether, which is why the segment cut keys on the
# `Service Summary Total` marker instead.
_LOCATION_HEADER = r"^ALL LOCATIONS(?:\s+(?P<location_label>\S.*?))?\s*$"

# Aging rows on the STATEMENT OF ACCOUNT page. Real dollar figures for invoices
# billed months ago; never a charge on this invoice.
_AGING_ROW = (
    rf"^\s*\d{{2}}/\d{{2}}/\d{{4}}\s+\d+\s+\S.*?\s+\d+\s+\${MONEY}\s+\${MONEY}\s*$"
)

# Remit stub: one line per open invoice, restating this invoice's total and the
# previous balance next to a blank "Applied Amount" rule.
_REMIT_STUB_ROW = rf"^\s{{1,6}}\d{{6,}}\s+\${MONEY}\s+_{{5,}}"

_IGNORABLE_PATTERNS = (
    r"^SERVICE SUMMARY(\(Continued\))?\s*$",
    r"^TAX SUMMARY\s*$",
    r"^STATEMENT OF ACCOUNT AS OF ",
    r"^\*{2,}\s*Intentionally left blank",
    r"^-{20,}\s*$",
    r"^\s*Please return lower portion with payment",
    r"^\s*Payment and contact information on back of remittance stub",
    r"^\s*Payment Instructions\s*$",
    r"^\s*Wire Transfer Details\s*$",
    r"^\s*Bank of America\s*$",
    r"^\s*(Account|Routing) Number:\s",
    r"^\s*Customer Assistance:\s",
    r"^\s*For Remittance Notices",
    r"^\s*TO PAY OR VIEW INVOICE DETAILS ONLINE GO TO:",
    r"^\s*https?://",
    r"^\s*YOUR CUSTOMER NUMBER\s*$",
    r"^\s*\d{4}/\d{6}\s*$",
    r"^\s*Page \d+ of \d+\s*$",
    r"^\s*Account Summary\s*$",
    r"^\s*Current Charges\s*$",
    r"^\s*Overview\s*$",
    r"^\s*INVOICE\s*$",
    r"^\s*Terms:\s",
    r"^\s*Due Date:\s",
    r"^\s*BILL TO:",
    # Barcode scanline: the invoice number, the total as a digit run, and the
    # customer number concatenated.
    r"^\s*\d{10,}X\d{4,}\s*$",
    r"^\s*_{5,}",
    r"^\s*ENCLOSED\s*$",
    r"^\s*AMOUNT\s*$",
    r"^\s*TOTAL\s*$",
)


def _before_detail_table(line: str, ctx: LineContext) -> bool:
    """True while no detail column header has been seen yet.

    Page one is letterhead, a bill-to block whose contents change per entity, an
    AP contact name, a remit stub and a barcode. Matching it positionally covers
    every entity without enumerating any of them; the Account Summary figures are
    claimed by earlier rules, so only genuine boilerplate reaches here.
    """
    return ctx.last_row_of_kind(RowKind.COLUMN_HEADER) is None


# A wrapped tail: a right-indented run of text under the row it continues,
# carrying no money. `COURT`, `DISTRICT COURT`, and GL codes such as
# `50130-1500-125000-010`. Matched by shape, not by value.
_WRAP = r"^\s{5,}(?P<text>\S+(?:\s+\S+){0,4})\s*$"

# Which field a wrap continues, keyed on what it hangs beneath.
_WRAP_TARGET = {
    RowKind.CHARGE: "description",
    RowKind.RESTATEMENT: "description",
    RowKind.TAX: "jurisdiction",
    RowKind.SECTION_HEADER: "location_label",
}


def _wrap_anchor(line: str, ctx: LineContext) -> ClassifiedRow | None:
    """The row a right-indented bare line continues, or None if there is none.

    "Beneath" has to survive a page break: a description wraps from the last row
    of one page onto the first body line of the next, with the repeated
    customer/page header and the column header in between. A service-group
    subheader can also land in the gap, so it is stepped over — but the
    `ALL LOCATIONS` header is *itself* wrappable (one file prints the customer's
    cost-centre code on the line below it), so that one is an anchor rather than
    something to step past.
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
        if row.kind is RowKind.SECTION_HEADER:
            if row.rule == "location_header":
                return row
            continue
        if row.kind is RowKind.CONTINUATION:
            continue
        return row if row.kind in _WRAP_TARGET else None
    return None


def _wrap_guard(line: str, ctx: LineContext) -> bool:
    return _wrap_anchor(line, ctx) is not None


def _extract_wrap(match: re.Match[str] | None, line: str, ctx: LineContext) -> dict:
    assert match is not None
    anchor = _wrap_anchor(line, ctx)
    kind = anchor.kind if anchor is not None else RowKind.CHARGE
    return {
        "text": match.group("text").strip(),
        "target": _WRAP_TARGET.get(kind, "description"),
    }


# `PUBLIC TRANSPORTATION BENEFIT AREA` wraps at column 0 inside the tax table,
# so the right-indent shape above cannot reach it.
_TAX_WRAP = r"^(?P<text>[A-Z][A-Z ]{2,40})$"


def _tax_wrap_guard(line: str, ctx: LineContext) -> bool:
    previous = ctx.last_significant_row(
        RowKind.IGNORABLE, RowKind.HEADER_FIELD, RowKind.COLUMN_HEADER
    )
    return previous is not None and previous.kind is RowKind.TAX


_HEADER_LABELS = (
    "Customer Number:",
    "Invoice Number:",
    "Invoice Date:",
    "Customer Name:",
)


RULES: list[Rule] = [
    Rule(RowKind.COLUMN_HEADER, _DETAIL_HEADER, zones=frozenset({"*"}),
         name="detail_header"),
    Rule(RowKind.COLUMN_HEADER, _TAX_HEADER, zones=frozenset({"*"}),
         name="tax_header"),
    Rule(RowKind.COLUMN_HEADER, _AGING_HEADER, zones=frozenset({"*"}),
         name="aging_header"),
    Rule(
        RowKind.SECTION_HEADER,
        _LOCATION_HEADER,
        extract=lambda m, ln, ctx: {
            "location_label": (m.group("location_label") or "").strip()
        },
        zones=frozenset({"*"}),
        name="location_header",
    ),
    Rule(
        RowKind.SECTION_HEADER,
        _SERVICE_GROUP,
        extract=lambda m, ln, ctx: {
            "service_group": m.group("service_group").strip(),
            "period_from": m.group("from"),
            "period_to": m.group("to"),
        },
        zones=frozenset({"*"}),
        name="service_group_header",
    ),
    # The lone money token that carries the first Service Summary Total. Must
    # precede every other bare-amount rule.
    Rule(RowKind.COLUMN_TOTAL, rf"^\s+\$(?P<amount>{MONEY})\s*$",
         guard=_orphan_value_guard, extract=_named("service_summary_total_a"),
         zones=frozenset({"*"}), name="service_summary_total_a"),

    # --- Account Summary, page 1. Case-sensitive: the mixed-case labels here and
    # the upper-case labels on the detail pages are different figures.
    Rule(RowKind.INVOICE_SUBTOTAL, rf"^\s*Current Invoice Subtotal\s+\$(?P<amount>{MONEY})\s*$",
         extract=_named("current_invoice_subtotal"), zones=frozenset({"*"}),
         name="current_invoice_subtotal"),
    Rule(RowKind.COLUMN_TOTAL, rf"^\s*Current Tax Subtotal\s+\$(?P<amount>{MONEY})\s*$",
         extract=_named("current_tax_subtotal"), zones=frozenset({"*"}),
         name="current_tax_subtotal"),
    Rule(RowKind.GRAND_TOTAL, rf"^\s*Current Invoice Total\s+\$(?P<amount>{MONEY})\s*$",
         extract=_named("current_invoice_total"), zones=frozenset({"*"}),
         name="current_invoice_total"),
    Rule(RowKind.COLUMN_TOTAL, rf"^\s*Previous Account Balance\s+\$(?P<amount>{MONEY})\s*$",
         extract=_named("previous_account_balance"), zones=frozenset({"*"}),
         name="previous_account_balance"),
    # Previous balance plus current charges. Never the grand total, and on 24 of
    # 33 files it is the largest figure on the page.
    Rule(RowKind.COLUMN_TOTAL, rf"^\s*Total Account Balance:\s+\$(?P<amount>{MONEY})\s*$",
         extract=_named("total_account_balance"), zones=frozenset({"*"}),
         name="total_account_balance"),
    Rule(RowKind.COLUMN_TOTAL, rf"^\s*CURRENT INVOICE\s+\$(?P<amount>{MONEY})\s*$",
         extract=_named("current_invoice_headline"), zones=frozenset({"*"}),
         name="current_invoice_headline"),

    # --- Detail-page and aging-page sums.
    Rule(RowKind.COLUMN_TOTAL,
         rf"^Location:(?P<location>\S+)\s+Total\s+\$(?P<amount>{MONEY})\s*$",
         extract=_extract_location_total, zones=frozenset({"*"}),
         name="location_total"),
    Rule(RowKind.COLUMN_TOTAL, rf"^\s*Service Summary Total\s+\$(?P<amount>{MONEY})\s*$",
         extract=_named("service_summary_total_b"), zones=frozenset({"*"}),
         name="service_summary_total_b"),
    Rule(RowKind.COLUMN_TOTAL, rf"^\s*Service Subtotal\s+\$(?P<amount>{MONEY})\s*$",
         extract=_named("service_subtotal"), zones=frozenset({"*"}),
         name="service_subtotal"),
    Rule(RowKind.COLUMN_TOTAL, rf"^\s*Tax Subtotal\s+\$(?P<amount>{MONEY})\s*$",
         extract=_named("tax_subtotal"), zones=frozenset({"*"}),
         name="tax_subtotal"),
    Rule(RowKind.COLUMN_TOTAL, rf"^\s*CURRENT INVOICE TOTAL\s+\$(?P<amount>{MONEY})\s*$",
         extract=_named("current_invoice_total_detail"), zones=frozenset({"*"}),
         name="current_invoice_total_detail"),
    Rule(RowKind.COLUMN_TOTAL, rf"^\s*TOTAL ACCOUNT BALANCE\s+\$(?P<amount>{MONEY})\s*$",
         extract=_named("total_account_balance_aging"), zones=frozenset({"*"}),
         name="total_account_balance_aging"),

    # --- Detail rows. The zone is the whole defence against the 100% overstate.
    Rule(RowKind.CHARGE, _DETAIL, extract=_extract_detail, name="detail_row"),
    Rule(RowKind.RESTATEMENT, _DETAIL, extract=_extract_detail,
         zones=frozenset({RESTATED}), name="restated_detail_row"),

    Rule(RowKind.TAX, _TAX_ROW, extract=_extract_tax_row, zones=frozenset({"*"}),
         name="tax_jurisdiction_row"),

    # --- Decoys with real dollar amounts.
    Rule(RowKind.IGNORABLE, _AGING_ROW, zones=frozenset({"*"}), name="aging_row"),
    Rule(RowKind.IGNORABLE, _REMIT_STUB_ROW, zones=frozenset({"*"}),
         name="remit_stub_row"),

    Rule(
        RowKind.HEADER_FIELD,
        r"(?:" + "|".join(re.escape(lbl) for lbl in _HEADER_LABELS) + r")\s+\S",
        zones=frozenset({"*"}),
        name="header_field",
    ),
    Rule(RowKind.IGNORABLE, r"|".join(_IGNORABLE_PATTERNS), zones=frozenset({"*"}),
         name="boilerplate"),
    Rule(RowKind.CONTINUATION, _TAX_WRAP, guard=_tax_wrap_guard,
         extract=lambda m, ln, ctx: {"text": m.group("text").strip(),
                                     "target": "jurisdiction"},
         zones=frozenset({"*"}), name="tax_jurisdiction_wrap"),
    # After every boilerplate rule: a lone right-shifted token also describes the
    # centred `INVOICE` page title and the `ENCLOSED` stub label.
    Rule(RowKind.CONTINUATION, _WRAP, guard=_wrap_guard, extract=_extract_wrap,
         zones=frozenset({"*"}), name="description_wrap"),
    # Positional catch-all for page one. Last, so nothing structural is swallowed.
    Rule(RowKind.IGNORABLE, r"^.+$", guard=_before_detail_table,
         zones=frozenset({"*"}), name="letterhead"),
]

ZONE_MARKERS = [
    # The bare label with no value on it. The second occurrence prints its value
    # inline and therefore does not match, so the zone flips exactly once.
    ZoneMarker(r"^Service Summary Total\s*$", RESTATED,
               name=ZONE_MARKER_NAME),
]


# ---------------------------------------------------------------------------
# Post-processing
# ---------------------------------------------------------------------------


def _postprocess(rows: list[ClassifiedRow]) -> None:
    """Fold wrapped text back, then lift the service grouping onto the charges.

    Segment B groups the same charges by service type, which is the only place
    the invoice states which service a row belongs to. Pairing the two segments
    positionally recovers it for every charge row. The pairing is checked before
    it is used — same row count, and the same
    `(product class, quantity, rate, amount)` tuple at every index — so a future
    invoice whose restatement is reordered leaves the field blank instead of
    mislabelling every row.
    """
    # Wrapped tails first: the description they belong to is what the pairing
    # check compares.
    anchor: ClassifiedRow | None = None
    for row in rows:
        if row.kind in (RowKind.CHARGE, RowKind.RESTATEMENT, RowKind.TAX):
            anchor = row
        elif row.kind is RowKind.SECTION_HEADER and row.rule == "location_header":
            anchor = row
        elif row.kind is RowKind.CONTINUATION and anchor is not None:
            target = row.fields.get("target", "description")
            extra = row.fields.get("text", "")
            if extra:
                base = str(anchor.fields.get(target, "") or "")
                anchor.fields[target] = f"{base} {extra}".strip()

    charges = [r for r in rows if r.kind is RowKind.CHARGE]
    restated = [r for r in rows if r.kind is RowKind.RESTATEMENT]

    def key(row: ClassifiedRow) -> tuple:
        return (
            row.fields.get("product_class"),
            row.fields.get("quantity"),
            row.fields.get("unit_rate"),
            row.amount,
        )

    aligned = len(charges) == len(restated) and all(
        key(a) == key(b) for a, b in zip(charges, restated)
    )
    if not aligned:
        return

    for charge, twin in zip(charges, restated):
        charge.fields["service_group"] = twin.fields.get("service_group", "")
        service_name = twin.fields.get("description", "")
        description = charge.fields.get("description", "")
        charge.fields["service_name"] = service_name
        # Segment A appends the customer's GL / cost-centre code to the service
        # name; segment B prints the name alone. The difference is the GL code.
        if service_name and description.startswith(service_name):
            charge.fields["gl_code"] = description[len(service_name):].strip()


# ---------------------------------------------------------------------------
# The ladder. Nine rungs, five of them independent prints of the same subtotal,
# which is what makes a mis-cut of the restated block impossible to miss.
# ---------------------------------------------------------------------------

LADDER = [
    LevelCheck(
        "invoice_subtotal",
        computed_from=(RowKind.CHARGE,),
        printed_kind=RowKind.INVOICE_SUBTOTAL,
        printed_field="current_invoice_subtotal",
        description="segment-A detail rows sum to the page-1 Current Invoice Subtotal",
    ),
    LevelCheck(
        "service_subtotal",
        computed_from=(RowKind.CHARGE,),
        printed_kind=RowKind.COLUMN_TOTAL,
        printed_field="service_subtotal",
        description="segment-A detail rows sum to the printed Service Subtotal",
    ),
    LevelCheck(
        "service_summary_total_a",
        computed_from=(RowKind.CHARGE,),
        printed_kind=RowKind.COLUMN_TOTAL,
        printed_field="service_summary_total_a",
        description="segment-A rows sum to the first Service Summary Total "
                    "(value printed on the following line)",
    ),
    LevelCheck(
        "service_summary_total_b",
        computed_from=(RowKind.RESTATEMENT,),
        printed_kind=RowKind.COLUMN_TOTAL,
        printed_field="service_summary_total_b",
        description="segment-B rows sum to the second Service Summary Total "
                    "(printed inline)",
    ),
    LevelCheck(
        "tax_subtotal",
        computed_from=(RowKind.TAX,),
        printed_kind=RowKind.COLUMN_TOTAL,
        printed_field="tax_subtotal",
        description="the TAX SUMMARY Total column sums to the printed Tax Subtotal",
    ),
    LevelCheck(
        "current_tax_subtotal",
        computed_from=(RowKind.TAX,),
        printed_kind=RowKind.COLUMN_TOTAL,
        printed_field="current_tax_subtotal",
        description="the TAX SUMMARY Total column sums to the page-1 "
                    "Current Tax Subtotal",
    ),
    LevelCheck(
        "grand_total",
        computed_from=(RowKind.INVOICE_SUBTOTAL, RowKind.TAX),
        printed_kind=RowKind.GRAND_TOTAL,
        description="subtotal plus tax equals Current Invoice Total — not "
                    "Total Account Balance, which adds the previous balance",
    ),
    LevelCheck(
        "grand_total_restated",
        computed_from=(RowKind.INVOICE_SUBTOTAL, RowKind.TAX),
        printed_kind=RowKind.COLUMN_TOTAL,
        printed_field="current_invoice_total_detail",
        description="subtotal plus tax equals the detail-page CURRENT INVOICE TOTAL",
    ),
    LevelCheck(
        "location_total",
        computed_from=(RowKind.RESTATEMENT,),
        printed_kind=RowKind.COLUMN_TOTAL,
        printed_field="location_total",
        required=False,
        description="segment-B rows sum to Location:000. Total",
    ),
    LevelCheck(
        "restatement",
        computed_from=(RowKind.CHARGE,),
        printed_kind=RowKind.RESTATEMENT,
        required=False,
        description="the regrouped second copy of the detail block restates the "
                    "same money as the first",
    ),
]
# A row-count rung against the restatement would be the one check that catches a
# dropped $0.00 row, but `CheckMode.COUNT` compares a row count against a
# *printed* integer field and cannot compare it against the row count of another
# kind. The equal-length test therefore lives in `_postprocess`, where a mismatch
# suppresses the service-group lift instead of flagging the invoice. See the
# report note on this engine gap.

SPEC = InvoiceSpec(
    name="appriss",
    description="Appriss Insights LLC / Equifax background screening "
                "(Oracle BI Publisher)",
    rules=RULES,
    zone_markers=ZONE_MARKERS,
    ladder=LADDER,
    postprocess=_postprocess,
    header_fields={
        "invoice_number": r"Invoice Number:\s+(\d+)",
        "invoice_date": r"Invoice Date:\s+(\d{2}/\d{2}/\d{4})",
        "customer_number": r"Customer Number:\s+(\S+)",
        "customer_name": r"Customer Name:\s+(.+?)\s{2,}Page \d+ of \d+",
        "terms": r"Terms:\s+(.+?)\s*$",
        "due_date": r"Due Date:\s+(\d{2}/\d{2}/\d{4})",
        "previous_account_balance": r"Previous Account Balance\s+\$([\d,]+\.\d{2})",
        "current_invoice_subtotal": r"Current Invoice Subtotal\s+\$([\d,]+\.\d{2})",
        "current_tax_subtotal": r"Current Tax Subtotal\s+\$([\d,]+\.\d{2})",
        "current_invoice_total": r"Current Invoice Total\s+\$([\d,]+\.\d{2})",
        "total_account_balance": r"Total Account Balance:\s+\$([\d,]+\.\d{2})",
    },
    line_item_fields=(
        "product_class",
        "service_group",
        "service_name",
        "description",
        "gl_code",
        "quantity",
        "unit_rate",
    ),
    identity_fields=("invoice_number",),
)
