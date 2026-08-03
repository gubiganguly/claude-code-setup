r"""Experian / Corporate Cost Control verification invoices (Oracle BI Publisher).

Two families, one grammar:

    VOE detail    30-46 pages, 648-945 item rows, one row per verification
    aggregate     1 page, 1 row: "Employment Verifications Purchased  39.90/EA"

Structure (the page header block repeats on EVERY page, up to 46 times):

    page header   INVOICE title, remit letterhead, DATE / DUE DATE / INVOICE /
                  ACCOUNT / ACCT EXEC / TERMS, ATTN / BILL TO and its address,
                  INVOICE DESCRIPTION + "Page n of m", then the column header
                  `DESCRIPTIONS   Price/Rate   Quantity   Amount`
    item rows     `Date: 01/02/26 ID: 0617497C VOE for KADAMERIA CAPLES| Ref #:
                   12905023                     68.95/FL      1        68.95`
    requester     `Hyttel, Nancy Total $45335.1` followed by a rule of dashes
    tax summary   `Summary of Taxes` / `Arizona: $3,626.81` / `Total: $3,626.81`
    footer        `Subtotal` / `Sales Tax` / `TOTAL`, on the last page
    remit stub    below a `____ ____ ...` rule; restates `AMOUNT:` = TOTAL
    barcode       a padded scanline repeated once per page that embeds the total

Discriminator: **the trailing column signature `<rate>/<UNIT> <int qty>
<amount>`, with no `$` anywhere on the line.** Items print bare numbers; every
printed sum prints `$`. The rate carries a unit suffix (`68.95/FL`, `39.90/EA`)
that nothing else on the page has, so the row shape identifies items without any
reference to the description text — which matters, because the description takes
at least four different forms across the corpus (`VOE for NAME`, `-VOE request
for NAME, EMPLOYER at ...`, ISO timestamps, and a run-together
`Date: 01/02/26ID: ...-VOE`).

Seven traps this spec exists to handle:

1. `Total: $3,626.81` inside `Summary of Taxes` holds ONLY the tax. It is never
   the grand total. It is matched (colon-terminated, inside the summary block)
   before any other total rule and reconciled against the footer `Sales Tax`.
2. The per-requester subtotal prints UNFORMATTED — `$45335.1`, one decimal, no
   thousands comma — while every other amount prints `$45,335.10`. A
   `\$[\d,]+\.\d\d` pattern misses it entirely, and `parse_money` cannot read it.
3. That same subtotal is INCONSISTENTLY emitted: two files print the pair of
   dash rules with no label and no value at all. So its rung is advisory.
4. Cross-page description wrap: the tail of the last item on page N is the FIRST
   body line of page N+1, with ~21 lines of repeated page header in between. The
   continuation guard looks back past the structural kinds to find the charge.
5. Template placeholder garbage emitted as real text on every page: literal
   lines `A`, `a`, `asddfgg`, `I`, and up to 28 bare `B` lines. Classified as
   boilerplate BEFORE the shape-based continuation rule, or they are appended to
   descriptions and the totals never notice.
6. A padded barcode/scanline repeated once per page embeds the invoice total as a
   digit run (`...000489619100000000000126-3E5CEB00` for $48,961.91).
7. The remit stub restates the grand total as `AMOUNT: $48,961.91`. Summing it
   would overstate by 100%, so it is a RESTATEMENT and becomes a free extra rung.

Corpus: 27 files, 26 with a usable text layer (one is a Microsoft Print-To-PDF
scan carrying 24 characters and must be skipped, not parsed).
"""

from __future__ import annotations

import re
from decimal import Decimal

from engine.classify import ClassifiedRow, LineContext, RowKind, Rule
from engine.money import parse_money
from engine.reconcile import LevelCheck
from engine.spec import InvoiceSpec

MONEY = r"[\d,]+\.\d{2}"
# Deliberately loose: the per-requester subtotal prints with one decimal place
# and no thousands separator, so the strict pattern above does not reach it.
LOOSE_MONEY = r"[\d,]+(?:\.\d+)?"


def _money(raw: str) -> Decimal:
    value = parse_money(raw)
    if value is None:  # pragma: no cover - the classifier rejects this first
        raise ValueError(f"unparseable amount {raw!r}")
    return value


def _loose_amount(raw: str) -> Decimal:
    """Parse an amount the report printed unformatted.

    `Hyttel, Nancy Total $45335.1` is the only amount on an Experian invoice
    that is not printed to two decimals, and `parse_money` requires exactly two
    (deliberately, so that a bare integer is not mistaken for money). The
    fractional part is padded to two digits here — an exact, value-preserving
    rewrite — and then handed to the one money parser, rather than introducing a
    second way to turn a string into a Decimal.

    More than two decimals is not padding but a figure this parser has never
    seen, so it raises instead of rounding.
    """
    token = raw.strip().lstrip("$")
    whole, _, frac = token.partition(".")
    if len(frac) > 2:
        raise ValueError(f"amount {raw!r} carries more precision than cents")
    return _money(f"{whole}.{frac.ljust(2, '0')}")


# ---------------------------------------------------------------------------
# Item rows
# ---------------------------------------------------------------------------

# The tail is the whole discriminator; the head is the description and is taken
# verbatim rather than parsed, because its internal grammar varies by product
# and by year while the tail never does.
_ITEM = (
    r"^(?P<description>\s*\S.*?)\s{2,}"
    r"(?P<rate>\d+\.\d{2})/(?P<unit>[A-Za-z]{1,4})\s+"
    r"(?P<quantity>\d+)\s+"
    r"(?P<amount>" + MONEY + r")\s*$"
)


def _no_dollar(line: str, ctx: LineContext) -> bool:
    """Items print bare numbers; every printed sum on the page prints `$`."""
    return "$" not in line


def _extract_item(match: re.Match[str] | None, line: str, ctx: LineContext) -> dict:
    assert match is not None
    return {
        "amount": _money(match.group("amount")),
        "description": match.group("description").strip(),
        "rate": match.group("rate"),
        # The unit is a real column value (`FL` fulfilment vs `EA` each) and the
        # only thing distinguishing the two product families, so it is kept.
        "unit": match.group("unit"),
        "quantity": match.group("quantity"),
    }


# ---------------------------------------------------------------------------
# Printed sums
# ---------------------------------------------------------------------------

# Inside `Summary of Taxes`. Colon-terminated labels, one amount each. Matched
# structurally (indented label, colon, single amount) rather than by listing
# jurisdictions, so a second state does not go unnoticed.
_TAX_SUMMARY_TOTAL = rf"^\s+Total:\s+\$(?P<amount>{MONEY})\s*$"
_TAX_JURISDICTION = (
    rf"^\s+(?P<jurisdiction>[A-Z][A-Za-z .\-]*):\s+\$(?P<amount>{MONEY})\s*$"
)

# `Hyttel, Nancy Total $45335.1` — no colon, unformatted amount.
_REQUESTER_TOTAL = (
    rf"^\s*(?P<requester>\S.*?)\s+Total\s+\$(?P<amount>{LOOSE_MONEY})\s*$"
)

_SUBTOTAL = rf"^(?P<head>.*?)\bSubtotal\s+\$(?P<amount>{MONEY})\s*$"
_SALES_TAX = rf"^(?P<head>.*?)\bSales Tax\s+\$(?P<amount>{MONEY})\s*$"
_GRAND_TOTAL = rf"^(?P<head>.*?)\bTOTAL\s+\$(?P<amount>{MONEY})\s*$"
# Remit stub. Restates the grand total; never summed.
_REMIT_AMOUNT = rf"^(?P<head>.*?)\bAMOUNT:\s+\$(?P<amount>{MONEY})\s*$"


def _plain_amount(match: re.Match[str] | None, line: str, ctx) -> dict:
    assert match is not None
    return {"amount": _money(match.group("amount"))}


def _extract_tax_summary_total(match: re.Match[str] | None, line: str, ctx) -> dict:
    assert match is not None
    amount = _money(match.group("amount"))
    return {"amount": amount, "tax_summary_total": amount}


def _extract_jurisdiction(match: re.Match[str] | None, line: str, ctx) -> dict:
    assert match is not None
    amount = _money(match.group("amount"))
    return {
        "amount": amount,
        "jurisdiction_tax": amount,
        "jurisdiction": match.group("jurisdiction"),
    }


def _extract_requester_total(match: re.Match[str] | None, line: str, ctx) -> dict:
    assert match is not None
    return {
        "amount": _loose_amount(match.group("amount")),
        "requester": match.group("requester").strip(),
    }


# ---------------------------------------------------------------------------
# Structure and noise
# ---------------------------------------------------------------------------

_COLUMN_HEADER = r"^\s*DESCRIPTIONS\s+Price/Rate\s+Quantity\s+Amount\s*$"

_HEADER_LABELS = (
    r"DUE\s+DATE\s*:",
    r"\bDATE\s*:",
    r"\bINVOICE\s*:",
    r"\bACCOUNT\s*:",
    r"\bACCT EXEC\s*:",
    r"\bTERMS\s*:",
    r"\bATTN\s*:",
    r"\bBILL TO\s*:",
    r"^\s*Tax ID\s*:",
    r"^\s*INVOICE DESCRIPTION\s*:",
)

_BOILERPLATE = (
    # Template placeholder garbage emitted as real text, on every page.
    r"^\s*(?:A|a|B|I|asddfgg)\s*$",
    # The rule of dashes printed under the per-requester subtotal. Its length
    # varies from 22 to 61 characters and it is sometimes the only thing the
    # report emits where that subtotal should be.
    r"^\s*-{3,}\s*$",
    r"^\s*Summary of Taxes\s*$",
    r"^\s*INVOICE\s*$",
    r"^\s*Experian Verify\s*$",
    r"^\s*www\.",
    r"^\s*\d+\s+Anton Blvd",
    r"^\s*Costa Mesa, CA",
    r"For Product Inquiries",
    r"For Invoice/Collection Inquiries",
    # Barcode / scanline: a long unbroken alphanumeric run that embeds the total.
    r"^\s*[0-9][0-9A-Z\-]{30,}\s*$",
    r"^[_ ]{20,}$",
    r"^\s*REMITTANCE STUB\s*$",
)


def _above_table(line: str, ctx: LineContext) -> bool:
    """True while this page's own column header has not been seen yet.

    The whole page header block repeats up to 46 times, so "above the table" has
    to be evaluated per page rather than once per document — hence the page
    comparison rather than Baxter's simple "no header yet". Matching the block
    positionally is what keeps the bill-to name and its four address lines out
    of the spec: the payer differs between the two invoice families and one of
    them is truncated mid-word by the template.
    """
    header = ctx.last_row_of_kind(RowKind.COLUMN_HEADER)
    return header is None or header.page < ctx.page


# A wrapped description tail: an indented fragment with no money on it. It can be
# the `12905023` tail of a Ref #, a `#: 12905727` where the wrap fell inside the
# label, or a whole employer name (`Allied Universal [Allied Universal
# Services]| Ref #: 12945678`).
_CONTINUATION = r"^\s{4,}(?P<text>\S.*?)\s*$"


def _continuation_guard(line: str, ctx: LineContext) -> bool:
    """A bare indented fragment continues the description above it.

    "Above" has to survive a page break: a description wraps from the last item
    row of page N onto the first body line of page N+1, with the repeated page
    header — INVOICE title, letterhead, ATTN/BILL TO, address, page number,
    column header — in between. Skipping the structural kinds is what makes that
    work. The garbage placeholder lines are already classified as IGNORABLE by an
    earlier rule, so they are skipped here too and cannot break a wrap.
    """
    if "$" in line:
        return False
    previous = ctx.last_significant_row(
        RowKind.IGNORABLE,
        RowKind.HEADER_FIELD,
        RowKind.COLUMN_HEADER,
        RowKind.CONTINUATION,
    )
    return previous is not None and previous.kind is RowKind.CHARGE


RULES: list[Rule] = [
    Rule(RowKind.COLUMN_HEADER, _COLUMN_HEADER, zones=frozenset({"*"}),
         name="column_header"),
    # Items first: the most specific shape on the page, and putting it ahead of
    # the positional page-header catch-all means a page whose column header the
    # parser failed to recognise loses its rows to the ladder (loudly) rather
    # than to the catch-all (silently).
    Rule(RowKind.CHARGE, _ITEM, guard=_no_dollar, extract=_extract_item,
         zones=frozenset({"*"}), name="item_row"),
    # Tax summary before every other total rule: `Total: $3,626.81` here is the
    # tax and nothing else, and a general total rule would take it.
    Rule(RowKind.SECTION_SUBTOTAL, _TAX_SUMMARY_TOTAL,
         extract=_extract_tax_summary_total, zones=frozenset({"*"}),
         name="tax_summary_total"),
    Rule(RowKind.COLUMN_TOTAL, _TAX_JURISDICTION, extract=_extract_jurisdiction,
         zones=frozenset({"*"}), name="tax_by_jurisdiction"),
    Rule(RowKind.GROUP_SUBTOTAL, _REQUESTER_TOTAL, extract=_extract_requester_total,
         zones=frozenset({"*"}), name="requester_subtotal"),
    Rule(RowKind.INVOICE_SUBTOTAL, _SUBTOTAL, extract=_plain_amount,
         zones=frozenset({"*"}), name="invoice_subtotal"),
    Rule(RowKind.TAX, _SALES_TAX, extract=_plain_amount, zones=frozenset({"*"}),
         name="sales_tax"),
    Rule(RowKind.GRAND_TOTAL, _GRAND_TOTAL, extract=_plain_amount,
         zones=frozenset({"*"}), name="grand_total"),
    Rule(RowKind.RESTATEMENT, _REMIT_AMOUNT, extract=_plain_amount,
         zones=frozenset({"*"}), name="remit_stub_amount"),
    # Header fields ahead of boilerplate: the letterhead and the identifying
    # fields share physical lines (`Costa Mesa, CA 92626    INVOICE: 0126-...`),
    # and a line that carries a header field should be recorded as one.
    Rule(RowKind.HEADER_FIELD, r"|".join(_HEADER_LABELS), zones=frozenset({"*"}),
         name="header_field"),
    # Known boilerplate before anything shape-based, or 467 `B` placeholder
    # lines are appended to item descriptions while every rung still passes.
    Rule(RowKind.IGNORABLE, r"|".join(_BOILERPLATE), zones=frozenset({"*"}),
         name="boilerplate"),
    # Positional catch-all for the repeated page header block.
    Rule(RowKind.IGNORABLE, r"^.+$", guard=_above_table, zones=frozenset({"*"}),
         name="page_header_block"),
    Rule(RowKind.CONTINUATION, _CONTINUATION, guard=_continuation_guard,
         extract=lambda m, ln, ctx: {"text": m.group("text")},
         zones=frozenset({"*"}), name="description_continuation"),
    # Everything left is the remit stub, which only exists below the footer
    # totals on the final page. Guarded on having seen the grand total so it
    # cannot reach up into the detail table.
    Rule(
        RowKind.IGNORABLE,
        r"^.+$",
        guard=lambda ln, ctx: ctx.last_row_of_kind(RowKind.GRAND_TOTAL) is not None,
        zones=frozenset({"*"}),
        name="remit_stub",
    ),
]


def _postprocess(rows: list[ClassifiedRow]) -> None:
    """Fold each wrapped fragment back onto the description it belongs to.

    Without this the description of roughly a third of all rows is truncated
    mid-identifier — `VOE for CHANA DAVIS| Ref #:` with the reference itself
    lost — and every rung of the ladder still passes, because the money is on
    the item row and the wrap carries none.

    The join is always a single space, and that is a checked property rather than
    an assumption: BI Publisher breaks these descriptions only at a space, never
    mid-token. Verified over all 10,047 wraps in the corpus — including the ones
    that break inside a label (`... KADAMERIA CAPLES| Ref` + `#: 12905023`, 321
    of them) and the rows that wrap twice (`... DARIUS at The` + `Stop & Shop
    Supermarket Company LLC [ADUSA Support] | Ref #:` + `11885889`). Baxter's
    length heuristic for mid-value breaks is deliberately not copied here; it
    would be guessing at a break this vendor does not make.
    """
    last_charge: ClassifiedRow | None = None
    for row in rows:
        if row.kind is RowKind.CHARGE:
            last_charge = row
        elif row.kind is RowKind.CONTINUATION and last_charge is not None:
            extra = row.fields.get("text", "")
            if not extra:
                continue
            base = str(last_charge.fields.get("description", "") or "")
            last_charge.fields["description"] = f"{base} {extra}".strip()


LADDER = [
    # Advisory: two files print the pair of dash rules with no label and no
    # value where this subtotal belongs, and the one-page aggregate family never
    # prints it at all. Every invoice here bills a single requester, so this is
    # deliberately not grouped — a second requester would make the rung fail
    # loudly rather than pass on a mis-bucketed sum.
    LevelCheck(
        "requester_subtotal",
        computed_from=(RowKind.CHARGE,),
        printed_kind=RowKind.GROUP_SUBTOTAL,
        required=False,
        description="every item row sums to the printed per-requester Total",
    ),
    LevelCheck(
        "invoice_subtotal",
        computed_from=(RowKind.CHARGE,),
        printed_kind=RowKind.INVOICE_SUBTOTAL,
        description="every item row sums to the printed Subtotal",
    ),
    LevelCheck(
        "tax_by_jurisdiction",
        computed_from=(RowKind.COLUMN_TOTAL,),
        printed_kind=RowKind.SECTION_SUBTOTAL,
        computed_field="jurisdiction_tax",
        printed_field="tax_summary_total",
        description="per-state tax sums to the Summary of Taxes total",
    ),
    LevelCheck(
        "tax_summary_matches_footer",
        computed_from=(RowKind.SECTION_SUBTOTAL,),
        printed_kind=RowKind.TAX,
        computed_field="tax_summary_total",
        description="the Summary of Taxes total equals the footer Sales Tax",
    ),
    LevelCheck(
        "grand_total",
        computed_from=(RowKind.INVOICE_SUBTOTAL, RowKind.TAX),
        printed_kind=RowKind.GRAND_TOTAL,
        description="Subtotal plus Sales Tax equals TOTAL",
    ),
    LevelCheck(
        "remit_stub",
        computed_from=(RowKind.GRAND_TOTAL,),
        printed_kind=RowKind.RESTATEMENT,
        description="the remittance stub AMOUNT restates TOTAL",
    ),
]

SPEC = InvoiceSpec(
    name="experian",
    description="Experian / Corporate Cost Control verifications (Oracle BI Publisher)",
    rules=RULES,
    ladder=LADDER,
    postprocess=_postprocess,
    header_fields={
        "invoice_number": r"\bINVOICE:\s+(\S+)",
        "account": r"\bACCOUNT:\s+(\S+)",
        "invoice_date": r"(?<!DUE )\bDATE:\s+([A-Z]{3}\s+\d{1,2},\s+\d{4})",
        "due_date": r"\bDUE\s+DATE\s*:\s+([A-Z]{3}\s+\d{1,2},\s+\d{4})",
        "terms": r"\bTERMS:\s+(.+?)\s*$",
        "bill_to": r"\bBILL TO:\s+(.+?)\s*$",
        "attn": r"\bATTN:\s+(.+?)\s*$",
        "invoice_description": r"INVOICE DESCRIPTION:\s+(.*?)\s{2,}Page \d+ of \d+",
        "tax_id": r"Tax ID\s*:\s*(\S+)",
        "requester": r"^\s*(\S[^\n]*?)\s+Total\s+\$[\d,]+(?:\.\d+)?\s*$",
    },
    line_item_fields=("description", "rate", "unit", "quantity"),
    identity_fields=("invoice_number",),
)
