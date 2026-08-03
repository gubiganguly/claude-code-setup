"""Data Diver Technologies aggregate search invoices (QuickBooks via Amyuni).

Structure — one page, always:

    letterhead        Data Diver LLC-2011 / Dept 0208 / Po Box 120208 / Dallas TX
                      with `Date   Invoice #` and its values interleaved on the
                      SAME physical lines as the address
    bill-to block     the customer, plus (newer template) a right-hand column of
                      "update your payment information" notice text
    item table        `Quantity  Description  Rate  Amount`, 2-6 aggregate
                      rate-class rows, quantities up to 104,623
    footer            `Total`, and on the newer template
                      `Payments/Credits Applied` and `Balance Due`
                      — all three printed to the RIGHT of the remit-to address,
                      so label and value share a line with an address line
    tax tail          `$0.00` on one line and `Sales Tax (0.0%)` on the NEXT

Discriminator: **item rows carry no `$`; every printed sum carries one.** The
rate/amount columns of the table print bare (`0.11   1,087.90`) while the footer
prints `$9,302.15`. That one fact separates charges from totals without any
label list, and it is also what stops a total-finder latching onto the pseudo-row
`Total sales tax calculated by AvaTax   0.00   0.00`, which sits *inside* the
item table and has the word `Total` in its description.

Five traps this spec exists to handle:

1. `Total` is the invoice; `Balance Due` is what is payable. They are equal until
   a credit exists, and then `Payments/Credits Applied -$1,032.35` splits them.
   Line items reconcile against `Total`; the balance rung is a second, advisory
   rung because the older template prints neither credits nor a balance.
2. The minus of a credit sits INSIDE the money token (`-$1,032.35`), which
   `engine.money.parse_money` cannot read — it expects `$-1,032.35`. The sign is
   captured separately and applied after parsing.
3. The AvaTax pseudo-row has an empty Quantity cell, so the row pattern must
   allow a blank quantity. It is classified as a CHARGE: it is a row of the item
   table with Rate and Amount cells filled, QuickBooks emits it as a line item,
   and its amount is 0.00 in every file here.
4. `-layout` emits the sales-tax tail out of order — the value `$0.00` on one
   line and the label `Sales Tax (0.0%)` on the next. The money line is the tax
   row, recognised by looking *forward* to its label.
5. The footer sums are printed over the remit-to address block, so
   `PLEASE NOTE OUR REMITTANCE ADDRESS:   Total   $1,455.57` is one line. Every
   sum rule therefore has to run before any address boilerplate rule.

Corpus: 37 files, 34 with a usable text layer (3 are Microsoft Print-To-PDF
scans with no text at all and must be skipped, not parsed).
"""

from __future__ import annotations

import re
from decimal import Decimal

from engine.classify import ClassifiedRow, LineContext, RowKind, Rule
from engine.money import parse_money
from engine.reconcile import LevelCheck
from engine.spec import InvoiceSpec

MONEY = r"[\d,]+\.\d{2}"


def _money(raw: str) -> Decimal:
    value = parse_money(raw)
    if value is None:  # pragma: no cover - the classifier rejects this first
        raise ValueError(f"unparseable amount {raw!r}")
    return value


def _signed_money(raw: str, sign: str | None) -> Decimal:
    """Apply a minus that sits outside the currency symbol.

    `Payments/Credits Applied -$1,032.35` puts the sign before the `$`, which
    `parse_money` does not accept (its pattern reads the currency marker first,
    so it handles `$-1,032.35` and not `-$1,032.35`). Rather than hand-roll a
    second money parser, the sign is stripped here and re-applied to the Decimal
    that parse_money returns, so there is still exactly one place that turns a
    string into an amount.
    """
    value = _money(raw)
    return -value if sign else value


# ---------------------------------------------------------------------------
# Item rows
# ---------------------------------------------------------------------------

# `           9,890 Multistate Criminal Search              0.11        1,087.90`
#
# Quantity is right-aligned and separated from the description by a SINGLE space,
# so the two cannot be split on a whitespace run. The column boundary is not
# readable from the header row either: QuickBooks centres the header labels, so
# `Description` prints at column 49 while the description text starts at column
# 19. What is reliable is the shape — an optional comma-grouped integer, one
# space, a description that starts with a letter, then a wide gap and the two
# bare numeric cells. Requiring the description to start with a letter means a
# quantity is never mistaken for the head of a description; the row fails to
# classify (and is flagged) rather than silently splitting in the wrong place.
_ITEM = (
    r"^(?P<quantity>\s*(?:\d{1,3}(?:,\d{3})*)?)\s"
    r"(?P<description>[A-Za-z].*?)"
    r"\s{2,}(?P<rate>\d+\.\d{2,4})\s+(?P<amount>" + MONEY + r")\s*$"
)


def _no_dollar(line: str, ctx: LineContext) -> bool:
    """The discriminator: a table row never carries a currency symbol."""
    return "$" not in line


def _extract_item(match: re.Match[str] | None, line: str, ctx: LineContext) -> dict:
    assert match is not None
    quantity = match.group("quantity").strip()
    description = match.group("description").strip()
    return {
        "amount": _money(match.group("amount")),
        "quantity": quantity,
        "description": description,
        "rate": match.group("rate"),
        # QuickBooks drops an AvaTax sales-tax row into the middle of the item
        # table. Tagged rather than filtered, so it stays visible in the output
        # and in the row count instead of quietly disappearing.
        "is_tax_row": "sales tax" in description.lower(),
    }


# ---------------------------------------------------------------------------
# Printed sums — each shares its line with a remit-to address line
# ---------------------------------------------------------------------------

_TOTAL = rf"^(?P<head>.*?)(?<![:\w])Total\s+\$(?P<amount>{MONEY})\s*$"
_CREDITS = (
    rf"^(?P<head>.*?)Payments/Credits Applied\s+"
    rf"(?P<sign>-)?\$(?P<amount>{MONEY})\s*$"
)
_BALANCE = rf"^(?P<head>.*?)Balance Due\s+(?P<sign>-)?\$(?P<amount>{MONEY})\s*$"

# The tax value prints ABOVE its own label, alone on the line.
_TAX_VALUE = rf"^\s*\$(?P<amount>{MONEY})\s*$"
_TAX_LABEL = r"^\s*Sales Tax\s*\((?P<rate>[\d.]+)%\)\s*$"
_TAX_LABEL_RE = re.compile(_TAX_LABEL)


def _tax_value_guard(line: str, ctx: LineContext) -> bool:
    """A bare money line is the sales tax only when its label follows it."""
    following = ctx.next_nonblank()
    return following is not None and bool(_TAX_LABEL_RE.match(following))


def _plain_amount(match: re.Match[str] | None, line: str, ctx) -> dict:
    assert match is not None
    return {"amount": _money(match.group("amount"))}


def _extract_credits(match: re.Match[str] | None, line: str, ctx) -> dict:
    assert match is not None
    amount = _signed_money(match.group("amount"), match.group("sign"))
    return {"amount": amount, "credits_applied": amount}


def _extract_balance(match: re.Match[str] | None, line: str, ctx) -> dict:
    assert match is not None
    amount = _signed_money(match.group("amount"), match.group("sign"))
    return {"amount": amount, "balance_due": amount}


def _extract_tax(match: re.Match[str] | None, line: str, ctx) -> dict:
    assert match is not None
    following = ctx.next_nonblank() or ""
    label = _TAX_LABEL_RE.match(following)
    return {
        "amount": _money(match.group("amount")),
        "tax_rate": label.group("rate") if label else "",
    }


# ---------------------------------------------------------------------------
# Structure and noise
# ---------------------------------------------------------------------------

_COLUMN_HEADER = r"^\s*(?:Quantity\b|.*\bDescription\s+Rate\s+Amount\s*$)"

# The date and invoice number print to the right of an address line.
_DATE_AND_NUMBER = r"\d{1,2}/\d{1,2}/\d{4}\s+\d{4,7}\s*$"
_TERMS = r"^\s*Net\s+\d+(?:\s+\d{1,2}/\d{1,2}/\d{4})?\s*$"


def _above_table(line: str, ctx: LineContext) -> bool:
    """True while the item table's column header has not been seen yet.

    Everything above it is letterhead, the bill-to block and the right-hand
    payment notice. Matching that positionally is what keeps the spec free of a
    list of customer names and street addresses — the bill-to changes per file
    (three different entities across this corpus, one of them truncated
    mid-word by the template) and enumerating them would break on the fourth.
    """
    return ctx.last_row_of_kind(RowKind.COLUMN_HEADER) is None


# The remit-to block below the table is the vendor's own fixed address, printed
# on the same lines as the footer sums. Every sum rule runs before this.
_IGNORABLE_PATTERNS = (
    r"^\s*PLEASE NOTE OUR REMITTANCE ADDRESS",
    r"^\s*Data Diver (?:Technologies|LLC)",
    r"^\s*Dept\s+\d+\s*$",
    r"^\s*Po Box\s+\d+\s*$",
    r"^\s*Dallas, TX\s+[\d-]+\s*$",
    r"^\s*Questions regarding tax\?",
    r"^\s*DDsalestax@",
)

RULES: list[Rule] = [
    Rule(RowKind.COLUMN_HEADER, _COLUMN_HEADER, zones=frozenset({"*"}),
         name="column_header"),
    # Every printed sum, before any boilerplate rule: each one shares its line
    # with an address line that boilerplate would otherwise swallow.
    Rule(RowKind.COLUMN_TOTAL, _CREDITS, extract=_extract_credits,
         zones=frozenset({"*"}), name="payments_credits_applied"),
    Rule(RowKind.INVOICE_SUBTOTAL, _BALANCE, extract=_extract_balance,
         zones=frozenset({"*"}), name="balance_due"),
    Rule(RowKind.GRAND_TOTAL, _TOTAL, extract=_plain_amount,
         zones=frozenset({"*"}), name="invoice_total"),
    Rule(RowKind.TAX, _TAX_VALUE, guard=_tax_value_guard, extract=_extract_tax,
         zones=frozenset({"*"}), name="sales_tax_value"),
    Rule(RowKind.HEADER_FIELD, _TAX_LABEL, zones=frozenset({"*"}),
         name="sales_tax_label"),
    Rule(RowKind.CHARGE, _ITEM, guard=_no_dollar, extract=_extract_item,
         zones=frozenset({"*"}), name="item_row"),
    Rule(RowKind.HEADER_FIELD, _DATE_AND_NUMBER, zones=frozenset({"*"}),
         name="date_and_invoice_number"),
    Rule(RowKind.HEADER_FIELD, _TERMS, zones=frozenset({"*"}), name="terms"),
    Rule(RowKind.IGNORABLE, r"|".join(_IGNORABLE_PATTERNS),
         zones=frozenset({"*"}), name="remit_block"),
    # Positional catch-all for everything above the table. Last, so nothing
    # structural can be swallowed by it.
    Rule(RowKind.IGNORABLE, r"^.+$", guard=_above_table, zones=frozenset({"*"}),
         name="letterhead_and_bill_to"),
]


def _postprocess(rows: list[ClassifiedRow]) -> None:
    """Nothing to fold: Data Diver never wraps a description or groups rows.

    Kept explicit rather than left as None so the absence is a stated finding
    (verified across all 34 text-layer files) instead of an oversight.
    """
    return None


LADDER = [
    # `Total` is the invoice value, so this rung carries the name `grand_total`
    # and the extractor reports it. `Balance Due` is the payable and is checked
    # separately below; treating it as the invoice total would understate every
    # invoice that carries a credit.
    LevelCheck(
        "grand_total",
        computed_from=(RowKind.CHARGE, RowKind.TAX),
        printed_kind=RowKind.GRAND_TOTAL,
        description="every item row plus sales tax equals the printed Total",
    ),
    # Advisory: the older template prints neither a credit line nor a balance.
    # The kinds here are borrowed — the engine has no ADJUSTMENT or AMOUNT_DUE
    # kind, and the two rows have to sit in different kinds for one to be the
    # computed side and the other the printed side of this rung.
    LevelCheck(
        "balance_due",
        computed_from=(RowKind.GRAND_TOTAL, RowKind.COLUMN_TOTAL),
        printed_kind=RowKind.INVOICE_SUBTOTAL,
        required=False,
        description="Total plus Payments/Credits Applied equals Balance Due",
    ),
]

SPEC = InvoiceSpec(
    name="datadiver",
    description="Data Diver Technologies aggregate search billing (QuickBooks / Amyuni)",
    rules=RULES,
    ladder=LADDER,
    postprocess=_postprocess,
    header_fields={
        "invoice_number": r"\d{1,2}/\d{1,2}/\d{4}\s+(\d{4,7})\s*$",
        "invoice_date": r"(\d{1,2}/\d{1,2}/\d{4})\s+\d{4,7}\s*$",
        "terms": r"^\s*(Net\s+\d+)",
        "due_date": r"^\s*Net\s+\d+\s+(\d{1,2}/\d{1,2}/\d{4})\s*$",
        "customer": (
            r"^\s*Bill To\s*$\n"
            r"(?:[^\n]*To update your payment information[^\n]*\n)?"
            r"[ ]?(\S[^\n]*?)(?:\s{2,}[^\n]*)?$"
        ),
        "gl_code": r"(\d{5}-\d{4}-\d{6,8}-\w+)",
        "sales_tax_rate": r"Sales Tax\s*\(([\d.]+)%\)",
    },
    line_item_fields=("quantity", "description", "rate", "is_tax_row"),
    identity_fields=("invoice_number",),
)
