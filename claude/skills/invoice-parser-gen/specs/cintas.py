"""Cintas Corporation uniform-rental invoices (SAP form ZMF_SD_RNT_INVOICE_B EN).

Structure:

    header            INVOICE # / DATE / SERVICE TICKET # / SOLD TO # / ...
    section+          optional "DEPT: <name>", may span page breaks
      employee group+ charge rows keyed by EMP#/LOCK#
                      └─ "0002  CAMERON WEINTZ SUBTOTAL - 15.82"
      flat charge*    EMBLEM ADVANTAGE / PREP ADVANTAGE
      └─ "[DEPT ]SUBTOTAL  67.55"
    SERVICE CHARGE    invoice-level, outside every section
    footer            SUBTOTAL / (SALES )?TAX / TOTAL USD
    restatement       SPECIAL PROGRAMS BREAKDOWN — already-billed charges, re-presented

The discriminator that makes this layout tractable: **a real charge row ends in
an amount followed by `Y` or `N`** (the taxable flag). No subtotal row carries
one. That single rule separates charges from all four kinds of decoy number on
the page, and it is why an amount-column x-band would not work here — charge
amounts sit at x≈566 and the grand total at x≈562, far too close to separate.

Four traps this spec exists to handle, each of which reconciles perfectly if
mishandled and is therefore invisible to the totals:

1. SPECIAL PROGRAMS BREAKDOWN restates the program charges with qty x rate.
   Summing them double-counts. Handled by a zone.
2. `EMPLOYEE 0005 OWES 002 Shirts OR PAY $ 52.56 REPLACEMENT CHARGE` is a
   contingent notice, not a charge. 77 of them across the corpus.
3. Long descriptions wrap to a bare token on the next line (`PREM-RG2XL`).
   277 of them. The money is unaffected; the description is silently truncated.
4. The footer `SUBTOTAL` is textually identical to a section `SUBTOTAL`. Only
   the `TAX` line beneath it tells them apart.
"""

from __future__ import annotations

import re
from decimal import Decimal
from functools import lru_cache

from engine.classify import BODY, ClassifiedRow, LineContext, RowKind, Rule, ZoneMarker
from engine.money import money_tokens, parse_money
from engine.reconcile import LevelCheck
from engine.spec import InvoiceSpec

NUM = r"[\d,]+\.\d{2}"
RESTATEMENT_ZONE = "restatement"


def _amount(raw: str) -> Decimal:
    value = parse_money(raw)
    if value is None:  # pragma: no cover - the classifier rejects this first
        raise ValueError(f"unparseable amount {raw!r}")
    return value


# ---------------------------------------------------------------------------
# Charge rows
# ---------------------------------------------------------------------------

# The tail is unambiguous, so it is matched precisely and the head is split
# afterwards on runs of two-or-more spaces. Trying to anchor the head in the
# same regex is what makes these patterns brittle: the employee column is blank
# on consumable invoices, and `(\S+)?\s+(\S+)` then silently shifts the material
# code into the employee slot.
_CHARGE_TAIL = (
    r"^(?P<head>.*?)\s{2,}"
    r"(?P<freq>\d{2}|D)\s+"
    r"(?:(?P<exch>[FR])\s+)?"
    r"(?P<qty>\d+)\s+"
    r"(?P<unit_price>\d+\.\d{2,3})\s+"
    rf"(?P<amount>{NUM})\s+"
    r"(?P<taxable>[YN])\s*$"
)


_COLUMN_LABELS = (
    "EMP#/LOCK#",
    "MATERIAL",
    "DESCRIPTION",
    "FREQ",
    "EXCH",
    "QTY",
    "UNIT PRICE",
    "LINE TOTAL",
    "TAX",
)


@lru_cache(maxsize=64)
def _column_offsets(header: str) -> dict[str, int]:
    """Character offsets of each column, read off the printed header row.

    They are not fixed across this vendor's own variants: garment invoices put
    MATERIAL at column 16 and facility invoices at 13. Reading them from the
    header row that governs each table is what makes one spec cover both.
    """
    found = {}
    for label in _COLUMN_LABELS:
        at = header.find(label)
        if at >= 0:
            found[label] = at
    return found


def _extract_charge(match: re.Match[str] | None, line: str, ctx) -> dict:
    assert match is not None
    head = match.group("head")

    header_row = ctx.last_row_of_kind(RowKind.COLUMN_HEADER)
    offsets = _column_offsets(header_row.raw) if header_row else {}
    material_at = offsets.get("MATERIAL")
    description_at = offsets.get("DESCRIPTION")

    variant = ""
    if material_at is not None and description_at is not None and len(head) > material_at:
        # Slice on the real column boundaries. Splitting on whitespace runs
        # instead would mistake an unlabelled sub-column for the employee
        # number: `X2160  SM SHOP TWL-RED-        L  01 F 20 ...` has three
        # whitespace-separated head fields but no employee at all.
        employee = head[:material_at].strip()
        material = head[material_at:description_at].strip()
        remainder = [p for p in re.split(r"\s{2,}", head[description_at:].strip()) if p]
        description = remainder[0] if remainder else ""
        # Anything further right inside the description column is a real
        # sub-column (a size or handling code), so it is kept rather than
        # dropped: two rows for the same material differ only by this flag.
        variant = " ".join(remainder[1:])
    else:
        parts = [p for p in re.split(r"\s{2,}", head.strip()) if p]
        employee = ""
        material = parts[0] if parts else ""
        description = parts[1] if len(parts) > 1 else ""
        variant = " ".join(parts[2:])

    return {
        "amount": _amount(match.group("amount")),
        "employee": employee,
        "material": material,
        "description": description,
        "variant": variant,
        "freq": match.group("freq"),
        "exch": match.group("exch") or "",
        "quantity": match.group("qty"),
        "unit_price": match.group("unit_price"),
        "taxable": match.group("taxable"),
    }


# Section-level and invoice-level charges that carry no material code:
# EMBLEM ADVANTAGE, PREP ADVANTAGE, SERVICE CHARGE.
_FLAT_CHARGE = rf"^\s+(?P<label>[A-Z][A-Z0-9 /&.\-]*[A-Z])\s{{2,}}(?P<amount>{NUM})\s+(?P<taxable>[YN])\s*$"

_PROGRAM_LABELS = {"PREP ADVANTAGE", "EMBLEM ADVANTAGE"}


def _extract_flat(match: re.Match[str] | None, line: str, ctx) -> dict:
    assert match is not None
    label = match.group("label").strip()
    return {
        "amount": _amount(match.group("amount")),
        "employee": "",
        "material": "",
        "description": label,
        "freq": "",
        "exch": "",
        "quantity": "",
        "unit_price": "",
        "taxable": match.group("taxable"),
        # Tagged so the restatement rung can pair it with the summary block.
        "program_label": label if label in _PROGRAM_LABELS else None,
    }


# ---------------------------------------------------------------------------
# Printed sums
# ---------------------------------------------------------------------------

_GROUP_SUBTOTAL = rf"^\s*(?P<employee>\S+)\s+(?P<name>.+?)\s+SUBTOTAL\s+-\s+(?P<amount>{NUM})\s*$"
_SECTION_SUBTOTAL = rf"^\s*(?:(?P<dept>[A-Z][A-Z ]*?)\s+)?SUBTOTAL\s+(?P<amount>{NUM})\s*$"
_FOOTER_SUBTOTAL = rf"^\s*SUBTOTAL\s+(?P<amount>{NUM})\s*$"
_TAX = rf"^\s*(?P<label>SALES\s+TAX|TAX)\s+(?P<amount>{NUM})\s*$"
_GRAND_TOTAL = rf"^\s*TOTAL\s+USD\s+(?P<amount>{NUM})\s*$"

_TAX_FOLLOWS = re.compile(rf"^\s*(?:SALES\s+)?TAX\s+{NUM}\s*$")


def _footer_guard(line: str, ctx: LineContext) -> bool:
    """A bare `SUBTOTAL` is the footer only when a tax line comes next."""
    following = ctx.next_nonblank()
    return following is not None and bool(_TAX_FOLLOWS.match(following))


def _simple_amount(match: re.Match[str] | None, line: str, ctx) -> dict:
    assert match is not None
    return {"amount": _amount(match.group("amount"))}


def _extract_group_subtotal(match: re.Match[str] | None, line: str, ctx) -> dict:
    assert match is not None
    return {
        "amount": _amount(match.group("amount")),
        "employee": match.group("employee"),
        "employee_name": match.group("name").strip(),
    }


def _extract_section_subtotal(match: re.Match[str] | None, line: str, ctx) -> dict:
    assert match is not None
    return {
        "amount": _amount(match.group("amount")),
        "dept": (match.group("dept") or "").strip(),
    }


def _extract_tax(match: re.Match[str] | None, line: str, ctx) -> dict:
    assert match is not None
    return {
        "amount": _amount(match.group("amount")),
        "tax_label": re.sub(r"\s+", " ", match.group("label")),
    }


# The trailing summary block restates program charges as qty x rate. Same text,
# different meaning, so a zone rather than a lookahead.
_RESTATEMENT = (
    rf"^\s*(?P<label>PREP ADVANTAGE|EMBLEM ADVANTAGE)\s+"
    rf"(?P<qty>\d+)\s+(?P<rate>\d+\.\d+)\s+(?P<amount>{NUM})\s+[YN]\s*$"
)


def _extract_restatement(match: re.Match[str] | None, line: str, ctx) -> dict:
    assert match is not None
    return {
        "amount": _amount(match.group("amount")),
        "program_label": match.group("label"),
        "quantity": match.group("qty"),
        "rate": match.group("rate"),
    }


# ---------------------------------------------------------------------------
# Structure and noise
# ---------------------------------------------------------------------------

_CONTINUATION = r"^\s{15,}(?P<text>(?=[A-Z0-9/.\-]*[A-Z])[A-Z0-9][A-Z0-9/.\-]*)\s*$"


def _continuation_guard(line: str, ctx: LineContext) -> bool:
    """A bare right-shifted token is a wrapped description, not a row of its own.

    Valid only beneath a charge row, but "beneath" has to survive a page break:
    a description can wrap from the last row of one page onto the first body
    line of the next, with the whole remit-to and column-header block in
    between. Skipping the structural kinds is what makes that case work.
    """
    previous = ctx.last_significant_row(
        RowKind.IGNORABLE,
        RowKind.HEADER_FIELD,
        RowKind.COLUMN_HEADER,
        RowKind.SECTION_HEADER,
    )
    return previous is not None and previous.kind is RowKind.CHARGE


_HEADER_LABELS = (
    "INVOICE #",
    "INVOICE DATE",
    "SERVICE TICKET #",
    "CUSTOMER REF #",
    "USER ID #",
    "SOLD TO #",
    "PAYER #",
    "PAYMENT TERMS",
    "SORT #",
    "CINTAS ROUTE",
)

_IGNORABLE_PATTERNS = (
    # Contingent replacement notices. Real dollar amounts that are not charges.
    r"^\s*EMPLOYEE\s+\S+\s+OWES\b.*REPLACEMENT CHARGE",
    r"ADVANTAGE PROGRAMS PREVENTED YOU FROM",
    r"REMIT PAYMENT TO",
    r"PAY YOUR BILL WITH MYCINTAS",
    r"WWW\.CINTAS\.COM",
    r"MANAGE \| SHOP \| PAY",
    r"CUSTOMER SVC/BILLING",
    r"CINTAS FAX",
    r"^\s*CINTAS CORP\s*$",
    r"^\s*P\.O\. BOX",
    r"^\s*PHOENIX, AZ",
    r"^\s*INVOICE\s*$",
    r"NON-PAYMENT RELATED CORRESPONDENCE",
    r"^\s*Page \d+ of \d+\s*$",
    r"^\s*Signature\s*:",
    r"^(SHIP|BILL) TO:",
)


def _letterhead(line: str, ctx: LineContext) -> bool:
    """True for a line in this page's header block that carries no money.

    Replaces three patterns that named the customer and its street address
    outright. Those worked for one company and would have flagged every invoice
    of any other Cintas customer, since their address lines would go unclassified
    — a red flag on every row for no real reason, which is the fastest way to
    train someone to ignore red.

    Matched positionally instead: above *this page's* column header (per-page,
    because the block repeats and page one's header must not vouch for page two)
    and containing no amount, so a charge or a printed sum can never be absorbed
    here.
    """
    if money_tokens(line):
        return False
    return ctx.last_row_of_kind(RowKind.COLUMN_HEADER, this_page=True) is None

RULES: list[Rule] = [
    Rule(
        RowKind.COLUMN_HEADER,
        r"^\s*EMP#/LOCK#\s+MATERIAL\s+DESCRIPTION",
        zones=frozenset({"*"}),
        name="column_header",
    ),
    Rule(
        RowKind.SECTION_HEADER,
        r"^DEPT:\s*(?P<dept>.+?)\s*$",
        extract=lambda m, ln, ctx: {"dept": m.group("dept").strip()},
        zones=frozenset({"*"}),
        name="dept_header",
    ),
    Rule(RowKind.RESTATEMENT, _RESTATEMENT, extract=_extract_restatement,
         zones=frozenset({RESTATEMENT_ZONE}), name="restatement"),
    Rule(RowKind.CHARGE, _CHARGE_TAIL, extract=_extract_charge, name="charge_item"),
    Rule(RowKind.GROUP_SUBTOTAL, _GROUP_SUBTOTAL, extract=_extract_group_subtotal,
         name="employee_subtotal"),
    # Guarded footer rule must precede the unguarded section rule: the two
    # patterns overlap and first match wins.
    Rule(RowKind.INVOICE_SUBTOTAL, _FOOTER_SUBTOTAL, guard=_footer_guard,
         extract=_simple_amount, name="footer_subtotal"),
    Rule(RowKind.SECTION_SUBTOTAL, _SECTION_SUBTOTAL, extract=_extract_section_subtotal,
         name="section_subtotal"),
    Rule(RowKind.TAX, _TAX, extract=_extract_tax, zones=frozenset({"*"}), name="tax"),
    Rule(RowKind.GRAND_TOTAL, _GRAND_TOTAL, extract=_simple_amount,
         zones=frozenset({"*"}), name="grand_total"),
    Rule(RowKind.CHARGE, _FLAT_CHARGE, extract=_extract_flat, name="charge_flat"),
    Rule(
        RowKind.HEADER_FIELD,
        r"(?:" + "|".join(re.escape(lbl) for lbl in _HEADER_LABELS) + r")\s+\S",
        zones=frozenset({"*"}),
        name="header_field",
    ),
    Rule(
        RowKind.IGNORABLE,
        r"|".join(_IGNORABLE_PATTERNS),
        zones=frozenset({"*"}),
        name="boilerplate",
    ),
    Rule(
        RowKind.IGNORABLE,
        r"^\s*\S",
        guard=_letterhead,
        zones=frozenset({"*"}),
        name="letterhead",
    ),
    Rule(RowKind.CONTINUATION, _CONTINUATION, guard=_continuation_guard,
         extract=lambda m, ln, ctx: {"text": m.group("text")},
         zones=frozenset({"*"}), name="description_continuation"),
]

ZONE_MARKERS = [
    ZoneMarker(r"^\s*SPECIAL PROGRAMS BREAKDOWN\s*$", RESTATEMENT_ZONE,
               name="special_programs_breakdown"),
]


# ---------------------------------------------------------------------------
# Post-processing: attach the grouping keys the ladder buckets on
# ---------------------------------------------------------------------------


def _postprocess(rows: list[ClassifiedRow]) -> None:
    """Assign section and employee-group keys, and join wrapped descriptions.

    Sections are delimited by their own printed subtotal, not by page breaks:
    one invoice in the corpus runs a single section across four pages. Charges
    left over after the final section subtotal are invoice-level (SERVICE
    CHARGE) and get no section, which keeps them out of the section rung while
    still counting toward the invoice subtotal.
    """
    section_index = 0
    pending: list[ClassifiedRow] = []
    closed_sections: set[int] = set()

    for row in rows:
        if row.kind is RowKind.CHARGE:
            row.fields["section_key"] = f"s{section_index}"
            employee = row.fields.get("employee") or ""
            row.fields["group_key"] = (
                f"s{section_index}:{employee}" if employee else None
            )
            pending.append(row)
        elif row.kind is RowKind.GROUP_SUBTOTAL:
            employee = row.fields.get("employee") or ""
            row.fields["group_key"] = f"s{section_index}:{employee}"
        elif row.kind is RowKind.SECTION_SUBTOTAL:
            row.fields["section_key"] = f"s{section_index}"
            closed_sections.add(section_index)
            section_index += 1
            pending = []

    # Charges in a section that never printed a subtotal are invoice-level.
    for row in rows:
        if row.kind is RowKind.CHARGE:
            key = row.fields.get("section_key")
            if key and int(key[1:]) not in closed_sections:
                row.fields["section_key"] = None

    # Fold wrapped continuations back into the description they belong to.
    last_charge: ClassifiedRow | None = None
    for row in rows:
        if row.kind is RowKind.CHARGE:
            last_charge = row
        elif row.kind is RowKind.CONTINUATION and last_charge is not None:
            extra = row.fields.get("text", "")
            if extra:
                base = last_charge.fields.get("description", "")
                last_charge.fields["description"] = f"{base} {extra}".strip()
            last_charge = None

    # Carry the department name onto every charge for reporting.
    current_dept = ""
    for row in rows:
        if row.kind is RowKind.SECTION_HEADER:
            current_dept = row.fields.get("dept", "")
        elif row.kind is RowKind.CHARGE:
            row.fields.setdefault("dept", current_dept)


LADDER = [
    LevelCheck(
        "employee_subtotal",
        computed_from=(RowKind.CHARGE,),
        printed_kind=RowKind.GROUP_SUBTOTAL,
        group_by="group_key",
        where=lambda r: r.fields.get("group_key") is not None,
        description="garment rows sum to the printed per-employee subtotal",
    ),
    LevelCheck(
        "section_subtotal",
        computed_from=(RowKind.CHARGE,),
        printed_kind=RowKind.SECTION_SUBTOTAL,
        group_by="section_key",
        where=lambda r: r.fields.get("section_key") is not None,
        description="all charges in a department sum to its printed subtotal",
    ),
    LevelCheck(
        "invoice_subtotal",
        computed_from=(RowKind.CHARGE,),
        printed_kind=RowKind.INVOICE_SUBTOTAL,
        description="every charge on the invoice sums to the footer subtotal",
    ),
    LevelCheck(
        "grand_total",
        computed_from=(RowKind.INVOICE_SUBTOTAL, RowKind.TAX),
        printed_kind=RowKind.GRAND_TOTAL,
        description="subtotal plus tax equals TOTAL USD",
    ),
    LevelCheck(
        "restatement",
        computed_from=(RowKind.CHARGE,),
        printed_kind=RowKind.RESTATEMENT,
        group_by="program_label",
        where=lambda r: r.fields.get("program_label") is not None,
        required=False,
        description="program charges match the SPECIAL PROGRAMS BREAKDOWN restatement",
    ),
]

SPEC = InvoiceSpec(
    name="cintas",
    description="Cintas Corporation uniform rental (SAP ZMF_SD_RNT_INVOICE_B EN)",
    rules=RULES,
    zone_markers=ZONE_MARKERS,
    ladder=LADDER,
    postprocess=_postprocess,
    header_fields={
        "invoice_number": r"INVOICE #\s+(\S+)",
        "invoice_date": r"INVOICE DATE\s+(\S+)",
        "service_ticket": r"SERVICE TICKET #\s+(\S+)",
        "customer_ref": r"CUSTOMER REF #\s+(\S+)",
        "user_id": r"USER ID #\s+(\S+)",
        "sold_to": r"SOLD TO #\s+(\S+)",
        "payer": r"PAYER #\s+(\S+)",
        "payment_terms": r"PAYMENT TERMS\s+(.+?)\s*$",
        "sort_number": r"SORT #\s+(\S+)",
        "route": r"CINTAS ROUTE\s+(.+?)\s*$",
    },
    line_item_fields=(
        "dept",
        "employee",
        "material",
        "description",
        "variant",
        "freq",
        "exch",
        "quantity",
        "unit_price",
        "taxable",
    ),
    identity_fields=("invoice_number",),
)
