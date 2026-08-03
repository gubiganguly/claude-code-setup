"""Labcorp / Occupational Testing Services invoices (Quadient Inspire + Xerox VI).

One vendor, **two printed templates**, and the corpus also contains a container
document that must be refused. All three come out of the same billing system and
share page 1, so a single spec covers them and branches on *zone*.

    Template A  "otsinv"  — footers read FORM otsinv_remit / _summ / _detail /
                            _prod / _stmt. Five page types:
                              remit   page 1 stub: aging table, open-invoice list
                              summ    "Current Period Summary" — item rows with a
                                      TESTS count and NO money; LOCATION/ACCOUNT
                                      TOTAL rows restate the detail-page money
                              detail  "Sample Detail" — the real charges, as
                                      MULTI-ROW items (donor row, then one
                                      indented continuation line per test, and
                                      the money is on the continuation lines)
                              prod    "Charges for Products" — a *second* charge
                                      stream that the sample detail does not
                                      contain at all
                              stmt    "STATEMENT" — full transaction ledger,
                                      pure decoy
    Template B  "grid"    — no FORM footer. One grid, money printed with no `$`.
                            Charges live between `* * * CURRENT PERIOD ACTIVITY
                            * * *` and `Current Period Subtotal`. A
                            `* * * PRIOR PERIODS SUMMARY * * *` block holds only
                            prior invoices, payments and adjustments.

Zones, not page footers. The `FORM otsinv_*` marker sits at the *bottom* of its
page, so a rule guarded on it cannot see it while the page's own rows are being
classified. Every page instead carries its title at the top — `Current Period
Summary`, `Sample Detail`, `Charges for Products`, `STATEMENT` — and those work
as zone markers directly. Template B's `* * * ... * * *` banners do the same job.

Traps this spec exists to handle. Each of them reconciles or parses cleanly if
mishandled, which is why they are called out:

1. **LOCATION TOTAL / ACCOUNT TOTAL are printed twice**, once on `otsinv_summ`
   and once on `otsinv_detail`, with identical values. Summing both yields
   exactly 2x the invoice. Zone scoping splits them: the detail copies are
   SECTION_SUBTOTAL / GROUP_SUBTOTAL and reconcile the charges; the summary
   copies are RESTATEMENT and become *free cross-page checks* instead of a
   hazard.
2. **`otsinv_prod` product charges are not in the sample detail.** `INVOICE
   TOTAL` = `TOTAL SAMPLES BILLED` + every `TOTAL PRODUCT CHARGES`. This is the
   whole of one file's reported -$101.50 shortfall; it is not a regex problem.
3. **Test codes are not always six digits.** `D13480 D13480 5+Crt-Bund` and
   `D10122` are real. A `\\d{6}` pattern loses $275.00 on one file. The code is
   matched as "the first token of the description column", structurally.
4. **Multi-row items.** The donor row carries no money on Template A; its
   indented continuation lines carry all of it. `SAMPLES:` counts donor rows,
   not charge rows, so both are declared: a money ladder over charges and a
   count ladder over donor rows.
5. **Six competing grand totals.** `TOTAL AMOUNT DUE` is the whole-account
   payable, `ACCOUNT BALANCE:` is the statement balance, and the aging buckets
   carry `CR` suffixes that make a credit look larger than the answer. All of
   them live on pages that this spec classifies as non-charge zones, so the
   grand total can only ever be `INVOICE TOTAL` (A) or `CURRENT PERIOD TOTAL`
   (B). The remit stub's own line for *this* invoice number is kept as one more
   independent rung.
6. **`INVOICE NUMBER = SUMMARY`** on page 1 of every file. The header regex is
   shaped so it can only match the numeric variant printed on later pages, and
   identity is the (invoice, account) pair rather than the number alone.
7. **A 642-page container** holding 494 nested sub-invoices across two billing
   periods. Its 494 `CURRENT PERIOD TOTAL` rows sum to exactly the 494 subtotals,
   so a naive ladder *passes* while reporting a number that is not any invoice.
   It is detected and refused.
"""

from __future__ import annotations

import re
from dataclasses import replace
from decimal import Decimal

from engine.classify import BODY, ClassifiedRow, LineContext, RowKind, Rule, ZoneMarker
from engine.columns import column_offsets, slice_columns
from engine.money import parse_money
from engine.reconcile import CheckMode, LevelCheck
from engine.spec import InvoiceSpec

# ---------------------------------------------------------------------------
# Zones
# ---------------------------------------------------------------------------

REMIT = BODY      # page 1 payment stub, both templates
SUMM = "summ"     # A: Current Period Summary  (restated money)
DETAIL = "detail" # A: Sample Detail           (real sample charges)
PROD = "prod"     # A: Charges for Products    (real product charges)
STMT = "stmt"     # A: STATEMENT               (transaction ledger, decoy)
PRIOR = "prior"   # B: PRIOR PERIODS SUMMARY   (decoy)
CURRENT = "current"  # B: CURRENT PERIOD ACTIVITY (real charges)

MONEY = r"[\d,]+\.\d{2}"
# A code cell: 708008, D13480, 780029. Never assume digits only.
CODE = r"[0-9A-Z][0-9A-Z\-]*"
_MONEY_ON_LINE = re.compile(r"\d[\d,]*\.\d{2}")
_INVOICE_HEADER = re.compile(
    r"^\s*(?P<account>\d{6,9})\s+(?P<invoice>\d{6,9})\s+\d{1,2}/\d{1,2}/\d{2,4}\b"
)


def _money(raw: str, credit: str | None = None) -> Decimal:
    value = parse_money(raw)
    if value is None:  # pragma: no cover - the classifier rejects this first
        raise ValueError(f"unparseable amount {raw!r}")
    # `CR` is Labcorp's credit marker and it is printed both flush against the
    # number and separated by a space. Never treat it as noise: on the remit
    # stub a $204.50CR bucket is larger in absolute value than the real total.
    return -value if credit else value


def _has_money(line: str) -> bool:
    return bool(_MONEY_ON_LINE.search(line))


ZONE_MARKERS = [
    ZoneMarker(r"^\s{2,}Current Period Summary\b", SUMM, name="page_current_period_summary"),
    ZoneMarker(r"^\s{2,}Sample Detail\b", DETAIL, name="page_sample_detail"),
    ZoneMarker(r"^\s{2,}Charges for Products\b", PROD, name="page_charges_for_products"),
    ZoneMarker(r"^\s+STATEMENT\s*$", STMT, name="page_statement"),
    ZoneMarker(r"\*\s*\*\s*\*\s+PRIOR\s+PERIODS?\s+SUMMARY\s+\*", PRIOR,
               name="banner_prior_periods"),
    ZoneMarker(r"\*\s*\*\s*\*\s+CURRENT\s+PERIOD\s+ACTIVITY\s+\*", CURRENT,
               name="banner_current_period"),
]


# ---------------------------------------------------------------------------
# Template A — otsinv_detail: the multi-row sample item
# ---------------------------------------------------------------------------

# The donor row. It carries no money at all; every charge for this sample is on
# an indented continuation line beneath it. It is still a row we must count,
# because `SAMPLES: 6` counts donor rows and is the only check that would notice
# a whole sample being dropped when its charges happen to be $0.00.
#
# Anchored on the two stable shapes — the SSN and the collection date — because
# the three cells in between are not reliably present: the sample-id cell is
# blank on some rows, contains spaces on others (`A MARTINEZ C`), and can hold a
# value byte-identical to the accession number next to it. Column slicing does
# not work here either: the printed values sit several characters left of their
# own header labels.
_DONOR_ROW = (
    r"^\s*(?P<ssn>\d{3}-\d{2}-\d{4})\s{2,}"
    r"(?P<middle>\S.*?)\s{2,}"
    r"(?P<date>\d{1,2}/\d{1,2}/\d{2,4})"
    r"(?:\s+(?P<donor>\S.*?))?\s*$"
)

_ACCESSION = re.compile(r"^\d{10}$")
_REFERENCE = re.compile(r"^[0-9A-Z]{12}$")


def _split_middle(middle: str) -> tuple[str, str, str]:
    """Cut the sample-id / accession / reference run, from the right.

    Right-to-left because the leftmost cell is the optional one. Three parts is
    the full house; two parts is a blank sample id, which is distinguished from
    a blank reference by the reference's fixed 12-character shape rather than by
    position — the accession and the sample id can be the same 10-digit string.
    """
    parts = [p for p in re.split(r"\s{2,}", middle.strip()) if p]
    if len(parts) >= 3:
        return " ".join(parts[:-2]), parts[-2], parts[-1]
    if len(parts) == 2:
        if _REFERENCE.match(parts[1]) and _ACCESSION.match(parts[0]):
            return "", parts[0], parts[1]
        return parts[0], parts[1], ""
    return ("", parts[0], "") if parts and _ACCESSION.match(parts[0]) else (
        (parts[0] if parts else ""), "", ""
    )


def _extract_donor(match: re.Match[str] | None, line: str, ctx) -> dict:
    assert match is not None
    sample_id, accession, reference = _split_middle(match.group("middle"))
    return {
        "is_sample": True,
        "ssn": match.group("ssn"),
        "sample_id": sample_id,
        "accession": accession,
        "reference": reference,
        "service_date": match.group("date"),
        "donor": (match.group("donor") or "").strip(),
    }


# The charge. `<code> <description>  $<amount>`, indented into the DONOR /
# DESCRIPTION column. The code is the first whitespace-delimited token and is
# taken as-is: `708008`, `D13480` and `790020` all occur, and a six-digit
# pattern silently drops $275.00 on one file in this corpus.
_DETAIL_CHARGE = (
    rf"^\s{{10,}}(?P<code>{CODE})\s+(?P<description>\S.*?)\s{{2,}}"
    rf"\$\s?(?P<amount>{MONEY})\s*$"
)


def _extract_detail_charge(match: re.Match[str] | None, line: str, ctx) -> dict:
    assert match is not None
    description = match.group("description").strip()
    code = match.group("code")
    # Labcorp prints the code twice on most rows ("724202 724202 U6-Bund+SVT")
    # and once on others ("708008 PSC Specimen Collection"). Keep the printed
    # description verbatim and expose the code separately; do not "clean" it,
    # because the duplicated form is what appears on the summary page too.
    return {
        "amount": _money(match.group("amount")),
        "code": code,
        "description": description,
        "quantity": "",
        "unit_price": "",
    }


def _detail_charge_guard(line: str, ctx: LineContext) -> bool:
    """A charge belongs to the sample above it.

    Looking back past the structural kinds so the guard survives a page break:
    a sample's second test can land as the first body line of the next page with
    the whole repeated address block and column header in between.
    """
    previous = ctx.last_significant_row(
        RowKind.IGNORABLE,
        RowKind.HEADER_FIELD,
        RowKind.COLUMN_HEADER,
        RowKind.CONTINUATION,
    )
    return previous is not None and (
        previous.kind is RowKind.CHARGE
        or (previous.kind is RowKind.SECTION_HEADER and previous.fields.get("is_sample"))
    )


# A donor row's cells can overflow onto the line below it. The sample id is the
# usual culprit — `MCELDOWNEY` printed under an otherwise blank sample-id cell —
# and the money is unaffected, so the ladder passes while the identifier is lost
# and, worse, the charge line beneath it loses its parent.
_DETAIL_CELL_CONTINUATION = r"^\s{2,}(?P<text>[A-Z0-9][A-Z0-9'\-,.& ]*?)\s*$"

_DETAIL_COLUMN_LABELS = ("SS#", "SAMPLE ID/ACCESSION #", "REFERENCE # / DATE",
                         "DONOR / DESCRIPTION", "AMOUNT")


def _detail_continuation_guard(line: str, ctx: LineContext) -> bool:
    if _has_money(line):
        return False
    previous = ctx.last_significant_row(
        RowKind.IGNORABLE, RowKind.HEADER_FIELD, RowKind.COLUMN_HEADER
    )
    return (
        previous is not None
        and previous.kind is RowKind.SECTION_HEADER
        and bool(previous.fields.get("is_sample"))
    )


def _extract_detail_continuation(match: re.Match[str] | None, line: str, ctx) -> dict:
    """Route the overflow token to the cell it continues.

    By horizontal position relative to the DONOR / DESCRIPTION column, not by
    `field_at_offset`: on this table the printed values sit several characters
    to the LEFT of their own header labels, so a strict label-boundary lookup
    puts a sample id in the SS# cell.
    """
    assert match is not None
    header = ctx.last_row_of_kind(RowKind.COLUMN_HEADER)
    target = "sample_id"
    if header is not None:
        offsets = dict(column_offsets(header.raw, _DETAIL_COLUMN_LABELS))
        donor_at = offsets.get("DONOR / DESCRIPTION")
        if donor_at is not None and (len(line) - len(line.lstrip())) >= donor_at - 10:
            target = "donor"
    return {"text": match.group("text").strip(), "target": target}


# Printed sums on otsinv_detail. These are the ones that reconcile the charges.
_DET_LOCATION_TOTAL = (
    rf"^\s*LOCATION TOTAL:\s+(?P<location>\S+)\s+SAMPLES:\s+(?P<samples>\d+)\s+"
    rf"\$\s?(?P<amount>{MONEY})\s*$"
)
_DET_ACCOUNT_TOTAL = (
    rf"^\s*ACCOUNT TOTAL:\s+(?P<account>\S+)\s+SAMPLES:\s+(?P<samples>\d+)\s+"
    rf"\$\s?(?P<amount>{MONEY})\s*$"
)
_DET_TOTAL_BILLED = (
    rf"^\s+TOTAL SAMPLES BILLED:\s+(?P<samples>\d+)\s+\$\s?(?P<amount>{MONEY})\s*$"
)

# Structure on otsinv_detail and otsinv_summ.
_ACCOUNT_HEADER = r"^\s*ACCOUNT:\s+(?P<account>\S+)\s*(?P<account_name>\S.*?)?\s*$"
_LOCATION_HEADER = r"^\s*LOCATION:\s+(?P<location>\S+)\s*$"


def _totals(match: re.Match[str] | None, line: str, ctx) -> dict:
    assert match is not None
    fields: dict = {"amount": _money(match.group("amount"))}
    groups = match.groupdict()
    if groups.get("samples"):
        fields["samples"] = Decimal(groups["samples"])
    for name in ("location", "account"):
        if groups.get(name):
            fields[name] = groups[name]
    return fields


# ---------------------------------------------------------------------------
# Template A — otsinv_summ: the restated copy
# ---------------------------------------------------------------------------

# Item rows here carry a TESTS count and no money whatsoever. They are the only
# place the invoice states how many charge lines each test code should produce,
# which makes them a count check on the multi-row parsing that no sum can give.
_SUMM_ITEM = (
    rf"^\s{{20,}}(?P<code>{CODE})\s+(?P<description>\S.*?)\s{{2,}}(?P<tests>\d+)\s*$"
)
# The first item of a location shares the line with the LOCATION: label.
_SUMM_LOCATION_ITEM = (
    rf"^\s*LOCATION:\s+(?P<location>\S+)\s+(?P<code>{CODE})\s+"
    rf"(?P<description>\S.*?)\s{{2,}}(?P<tests>\d+)\s*$"
)
_SUMM_LOCATION_TOTAL = (
    rf"^\s*LOCATION TOTAL:\s+(?P<location>\S+)\s+(?P<samples>\d+)\s+"
    rf"\$\s?(?P<amount>{MONEY})\s*$"
)
_SUMM_ACCOUNT_TOTAL = (
    rf"^\s*ACCOUNT TOTAL:\s+(?P<account>\S+)\s+TOTAL SAMPLES:\s+(?P<samples>\d+)\s+"
    rf"\$\s?(?P<amount>{MONEY})\s*$"
)
_SUMM_ACCOUNT_PRODUCT = (
    rf"^\s*ACCOUNT:\s+(?P<account>\S+)\s+TOTAL PRODUCT CHARGES\s+"
    rf"\$\s?(?P<amount>{MONEY})\s*$"
)
_SUMM_GRAND_SAMPLES = (
    rf"^\s{{20,}}TOTAL SAMPLES:\s+(?P<samples>\d+)\s+\$\s?(?P<amount>{MONEY})\s*$"
)
_INVOICE_TOTAL = rf"^\s+INVOICE TOTAL\s+\$\s?(?P<amount>{MONEY})\s*$"


def _extract_summ_item(match: re.Match[str] | None, line: str, ctx) -> dict:
    assert match is not None
    groups = match.groupdict()
    fields = {
        "tests": Decimal(groups["tests"]),
        "code": groups["code"],
        "description": groups["description"].strip(),
    }
    if groups.get("location"):
        fields["location"] = groups["location"]
    return fields


def _extract_summ_restatement(match: re.Match[str] | None, line: str, ctx) -> dict:
    fields = _totals(match, line, ctx)
    fields["is_summ_restatement"] = True
    return fields


def _extract_summ_product(match: re.Match[str] | None, line: str, ctx) -> dict:
    fields = _totals(match, line, ctx)
    fields["is_summ_product"] = True
    return fields


def _extract_summ_grand(match: re.Match[str] | None, line: str, ctx) -> dict:
    fields = _totals(match, line, ctx)
    fields["is_summ_grand"] = True
    return fields


# ---------------------------------------------------------------------------
# Template A — otsinv_prod: a second, independent charge stream
# ---------------------------------------------------------------------------

_SHIPPED_TO = r"^\s*SHIPPED TO:\s+(?P<order_account>\S+)\s*(?P<purchase_order>\S.*?)?\s*$"
_PROD_CHARGE = (
    rf"^\s*(?P<code>{CODE})\s+(?P<description>\S.*?)\s{{2,}}(?P<qty>\d+)\s+"
    rf"\$\s?(?P<unit_price>{MONEY})\s+\$\s?(?P<amount>{MONEY})\s*$"
)
_ORDER_TOTAL = rf"^\s+ORDER TOTAL:\s+\$\s?(?P<amount>{MONEY})\s*$"
_PRODUCT_CHARGES_TOTAL = (
    rf"^\s+TOTAL PRODUCT CHARGES:\s+\$\s?(?P<amount>{MONEY})\s*$"
)


def _extract_prod_charge(match: re.Match[str] | None, line: str, ctx) -> dict:
    assert match is not None
    return {
        "amount": _money(match.group("amount")),
        "code": match.group("code"),
        "description": match.group("description").strip(),
        "quantity": match.group("qty"),
        "unit_price": match.group("unit_price"),
    }


# ---------------------------------------------------------------------------
# Template B — the grid
# ---------------------------------------------------------------------------

_GRID_COLUMN_LABELS = ("DATE", "ITEM/PATIENT", "NUMBER", "DESCRIPTION", "CODES", "AMOUNT")

# The first charge for a patient shares the patient's own row, unlike Template A.
_GRID_PARENT = (
    rf"^\s*(?P<date>\d{{1,2}}/\d{{1,2}}/\d{{2,4}})\s+(?P<patient>\S.*?)\s{{2,}}"
    rf"(?P<accession>\S+)\s{{2,}}(?P<code>{CODE})\s+(?P<description>\S.*?)\s{{2,}}"
    rf"(?P<lab>\*?[0-9A-Z]{{1,4}})\s{{2,}}(?P<amount>{MONEY})\s*$"
)
# Further charges for the same patient. The patient column may carry another
# fragment of the patient id, or be empty.
_GRID_CHILD = (
    rf"^\s{{2,}}(?:(?P<patient_extra>\S+)\s{{2,}})?(?P<code>{CODE})\s+"
    rf"(?P<description>\S.*?)\s{{2,}}(?P<lab>\*?[0-9A-Z]{{1,4}})\s{{2,}}"
    rf"(?P<amount>{MONEY})\s*$"
)
_GRID_SUBTOTAL = rf"^\s+Current Period Subtotal\s+(?P<amount>{MONEY})\s*$"
_GRID_TOTAL = rf"^\s+CURRENT PERIOD TOTAL\s+(?P<amount>{MONEY})\s*$"
# A bare patient-id fragment with no charge beside it.
_GRID_ID_CONTINUATION = r"^\s{2,}(?P<text>[0-9A-Z][0-9A-Z\-]*)\s*$"


def _extract_grid_charge(match: re.Match[str] | None, line: str, ctx) -> dict:
    assert match is not None
    groups = match.groupdict()
    fields = {
        "amount": _money(groups["amount"]),
        "code": groups["code"],
        "description": groups["description"].strip(),
        "lab_code": groups["lab"].lstrip("*"),
        "quantity": "",
        "unit_price": "",
    }
    if groups.get("date"):
        fields["service_date"] = groups["date"]
    if groups.get("accession"):
        fields["accession"] = groups["accession"]
    if groups.get("patient"):
        fields["donor"] = groups["patient"].strip()
        fields["is_grid_parent"] = True
    # The extra token in the patient column is another slice of the patient id,
    # not a second patient. It is routed by the column it sits in so a wrapped
    # id never lands on a name.
    if groups.get("patient_extra"):
        header = ctx.last_row_of_kind(RowKind.COLUMN_HEADER)
        label = None
        if header is not None:
            offsets = column_offsets(header.raw, _GRID_COLUMN_LABELS)
            cells = slice_columns(line, offsets)
            label = cells.get("ITEM/PATIENT") or None
        fields["patient_id_part"] = label or groups["patient_extra"]
    return fields


def _grid_child_guard(line: str, ctx: LineContext) -> bool:
    previous = ctx.last_significant_row(
        RowKind.IGNORABLE,
        RowKind.HEADER_FIELD,
        RowKind.COLUMN_HEADER,
        RowKind.CONTINUATION,
    )
    return previous is not None and previous.kind is RowKind.CHARGE


def _grid_id_guard(line: str, ctx: LineContext) -> bool:
    if _has_money(line):
        return False
    previous = ctx.last_significant_row(
        RowKind.IGNORABLE,
        RowKind.HEADER_FIELD,
        RowKind.COLUMN_HEADER,
        RowKind.CONTINUATION,
    )
    return previous is not None and previous.kind is RowKind.CHARGE


# ---------------------------------------------------------------------------
# The remit stub — page 1, both templates. Every number on it is a decoy except
# the one line that names this invoice.
# ---------------------------------------------------------------------------

# `82574192   $135.00   ________________` is the open balance of this invoice
# among all the account's open invoices. The trailing cell is an AcroForm field
# and real AP staff have typed into it — "Need invoice", "Entering for payment.",
# "CM-84550312 Price $22.50 not $29.50 as billed" — so only the FIRST amount
# after the invoice number is read, and everything after it is captured as a note
# rather than dropped.
_STUB_ROW = (
    rf"^\s{{2,}}(?P<stub_invoice>\d{{7,9}})\s+\$?\s?(?P<num>{MONEY})"
    rf"(?:\s{{0,2}}(?P<cr>CR))?(?:\s+(?P<note>\S.*?))?\s*$"
)


def _extract_stub(match: re.Match[str] | None, line: str, ctx) -> dict:
    assert match is not None
    note = (match.group("note") or "").strip(" _")
    return {
        "amount": _money(match.group("num"), match.group("cr")),
        "stub_invoice": match.group("stub_invoice"),
        "ap_note": note,
        "is_stub": True,
    }


# ---------------------------------------------------------------------------
# Structure and noise
# ---------------------------------------------------------------------------

# Every money figure on the payment stub, named explicitly rather than left to
# the positional catch-all below it. This is the most dangerous region of the
# document — it holds `TOTAL AMOUNT DUE`, `ACCOUNT BALANCE` and four aging
# buckets whose `CR` suffixes make a credit look bigger than the real total — so
# it is the region that most needs to keep its tripwire. A *new* money shape here
# stays UNCLASSIFIED and flags, instead of disappearing into a catch-all.
#
# None of these is a rung. `TOTAL AMOUNT DUE` is the whole-account payable, and
# its label is split across three physical lines with the value on a different
# one of them in each of the two templates, so pairing it up is guesswork. The
# aging row is printed with no labels at all on one variant.
_AGING_BUCKET = rf"(?:\$\s?)?[\d,]*\.\d{{2}}(?:CR)?"
# Four aging buckets, then TOTAL AMOUNT DUE — which is printed on this same line
# on the variant that has no labels at all, and on a neighbouring line otherwise.
_AGING_ROW = (
    rf"^\s*{_AGING_BUCKET}\s+{_AGING_BUCKET}\s+{_AGING_BUCKET}\s+{_AGING_BUCKET}"
    rf"(?:\s+DUE)?(?:\s+{_AGING_BUCKET})?\s*$"
)
_TOTAL_AMOUNT_DUE = (
    rf"^.*?\bAMOUNT\s+\$\s?{MONEY}(?:CR)?\s*$"
    rf"|^[\s_]*DUE\s+(?:\$\s?)?{MONEY}(?:CR)?\s*$"
)
_ORPHAN_STUB_AMOUNT = rf"^\s*\$\s?{MONEY}(?:\s?CR)?(?:\s+_+)?\s*$"


_DETAIL_COLUMN_HEADER = r"^\s+SS#\s+SAMPLE ID/ACCESSION #\s+REFERENCE"
_SUMM_COLUMN_HEADER = r"^\s+TEST\s+DESCRIPTION\s+TESTS\s+SAMPLES\s+AMOUNT\s*$"
_PROD_COLUMN_HEADER = r"^\s+ITEM\s+DESCRIPTION\s+QUANTITY\s+UNIT PRICE\s+AMOUNT\s*$"
_GRID_COLUMN_HEADER = r"^\s+DATE\s+ITEM/PATIENT\s+NUMBER\s+DESCRIPTION\s+CODES\s+AMOUNT\s*$"

_PAGE_HEADER_FIELDS = (
    r"^\s*ACCOUNT NUMBER\s+INVOICE\s*$",
    r"^\s*ACCOUNT NUMBER\s+INVOICE NUMBER\s+DATE",
    r"^\s*NUMBER\s+DATE\s+PURCHASE ORDER NO\.\s+PAGE\s*$",
    r"^\s*\d{6,9}\s+(?:\d{6,9}|SUMMARY)\s+\d{1,2}/\d{1,2}/\d{2,4}(\s+\d+)?\s*$",
    r"^\s*Account Number:?\s+\d+\s*$",
    r"^\s*ACCOUNT #\s+\d+\s*$",
    r"^\s*STATEMENT AS OF\s+\d",
    r"^\s*PAYING ACCOUNT\b",
)

# The statement page's transaction ledger. Matched structurally — a date, a
# free-text activity, then one or two amounts (the second is a running balance,
# and on some files it is an empty AcroForm underscore run). It is captured as
# IGNORABLE rather than left to a blanket catch-all so that a new *shape* on this
# page still trips the tripwire.
_STMT_LEDGER = (
    rf"^\s*(?:\d{{6,9}}\s+)?\d{{1,2}}/\d{{1,2}}/\d{{2,4}}\s+\S.*?"
    rf"\$\s?{MONEY}(?:CR)?(?:\s+(?:\$\s?{MONEY}(?:CR)?|_+))?\s*$"
)
_STMT_BALANCE = rf"^\s+ACCOUNT BALANCE:\s+\$\s?{MONEY}(?:CR)?\s*$"

# The prior-periods block: prior invoices, payments, wire transfers and price
# corrections. None of it is a charge on this invoice.
_PRIOR_ENTRY = (
    rf"^\s*\d{{1,2}}/\d{{1,2}}/\d{{2,4}}\s+\S.*?(?:\s+{MONEY}(?:CR)?)?\s*$"
)
_PRIOR_BALANCE = (
    rf"^\s+(?:INVOICE BALANCE|PRIOR PERIOD BALANCE|PRIOR PERIODS? SUBTOTAL)"
    rf"\s+{MONEY}(?:CR)?\s*$"
)

_LAB_INDEX_ROW = r"^[0-9A-Z]{1,4}\s{2,}\S"

_IGNORABLE_PATTERNS = (
    r"^\s*Occupational Testing Services\s*$",
    r"^\s*Burlington, North Carolina\s*$",
    r"^\s*FORM otsinv_\w+\s*$",
    r"^\s*PO BOX \d+ BURLINGTON, NC .*TAX ID#",
    r"^\s*\d+\s+PO BOX(\s+\d)+\s+BURL\s?I\s?NGTON",   # letter-spaced footer
    r"^\s*PO BOX(\s+\d)+\s+BURL\s?I\s?NGTON",
    r"^\s*R\d{2}-[A-Z]{2,4}(\s+[\d,]+)?\s*$",
    r"^\s*Performing Lab Index\s*$",
    r"^\s*[A-Z]\s*$",                                  # vertical INVOICE TO letters
    r"^\s*[A-Z]\s{2,}\S",                              # ... with an address beside it
    r"^\s*_{3,}\s*$",
    r"^\s*[-=]{3,}\s*$",
    r"^\s*,\s*$",
    r"^\s*\(\s*\d{3}\s*\)\s*\d",
    r"^\s*\(\d{3}\)\s*\d{3}\s*-?\s*\d{4}\s*$",
    r"^\s*INVOICE\s*$",
    r"^\s*\*\d+\*\s*$",                                # barcode strings
    r"^\s*SHIPPED:\s+\d",
    r"^\s*NOTE:\s",
    r"TAX\s?I\s?D",
    r"MAKE CHECK PAYABLE",
    r"DETACH HERE AND RETURN",
)


def _in_page_header(line: str, ctx: LineContext) -> bool:
    """True while this page has not yet printed its column header.

    Every page repeats the letterhead, the account/invoice block and a bill-to
    address whose contents differ per file and per entity. Matching that
    positionally covers all of them without enumerating a single address, and
    scoping it *per page* keeps it from reaching into the table below. Money-
    bearing lines are excluded outright, so a charge can never be swallowed.
    """
    if _has_money(line):
        return False
    header = ctx.last_row_of_kind(RowKind.COLUMN_HEADER)
    return header is None or header.page != ctx.page


def _prod_supporting(line: str, ctx: LineContext) -> bool:
    """The ship-to address block under `SHIPPED TO:`.

    Freeform, several lines long, and it can be cut by a page break. Every real
    row on this page carries money, so "no money in the product zone" is a safe
    and complete description of the supporting text.
    """
    return not _has_money(line)


RULES: list[Rule] = [
    # Column headers first: several zones' catch-alls sit below, and the header
    # offsets are needed by the extractors.
    Rule(RowKind.COLUMN_HEADER, _DETAIL_COLUMN_HEADER, zones=frozenset({"*"}),
         name="detail_column_header"),
    Rule(RowKind.COLUMN_HEADER, _SUMM_COLUMN_HEADER, zones=frozenset({"*"}),
         name="summ_column_header"),
    Rule(RowKind.COLUMN_HEADER, _PROD_COLUMN_HEADER, zones=frozenset({"*"}),
         name="prod_column_header"),
    Rule(RowKind.COLUMN_HEADER, _GRID_COLUMN_HEADER, zones=frozenset({"*"}),
         name="grid_column_header"),
    Rule(RowKind.HEADER_FIELD, r"|".join(_PAGE_HEADER_FIELDS), zones=frozenset({"*"}),
         name="page_header_field"),
    Rule(RowKind.IGNORABLE, r"|".join(_IGNORABLE_PATTERNS), zones=frozenset({"*"}),
         name="boilerplate"),

    # --- Template A: otsinv_detail. Printed sums before the charge shape. -----
    Rule(RowKind.SECTION_SUBTOTAL, _DET_LOCATION_TOTAL, extract=_totals,
         zones=frozenset({DETAIL}), name="detail_location_total"),
    Rule(RowKind.GROUP_SUBTOTAL, _DET_ACCOUNT_TOTAL, extract=_totals,
         zones=frozenset({DETAIL}), name="detail_account_total"),
    Rule(RowKind.INVOICE_SUBTOTAL, _DET_TOTAL_BILLED, extract=_totals,
         zones=frozenset({DETAIL}), name="detail_total_samples_billed"),
    Rule(RowKind.SECTION_HEADER, _LOCATION_HEADER,
         extract=lambda m, ln, c: {"location": m.group("location")},
         zones=frozenset({DETAIL, SUMM}), name="location_header"),
    Rule(RowKind.SECTION_HEADER, _DONOR_ROW, extract=_extract_donor,
         zones=frozenset({DETAIL}), name="detail_donor_row"),
    Rule(RowKind.CHARGE, _DETAIL_CHARGE, extract=_extract_detail_charge,
         guard=_detail_charge_guard, zones=frozenset({DETAIL}), name="detail_charge"),
    Rule(RowKind.CONTINUATION, _DETAIL_CELL_CONTINUATION,
         guard=_detail_continuation_guard, extract=_extract_detail_continuation,
         zones=frozenset({DETAIL}), name="detail_cell_continuation"),

    # --- Template A: otsinv_summ. Every money row here is a restatement. -----
    Rule(RowKind.RESTATEMENT, _SUMM_ACCOUNT_PRODUCT, extract=_extract_summ_product,
         zones=frozenset({SUMM}), name="summ_account_product_total"),
    Rule(RowKind.RESTATEMENT, _SUMM_LOCATION_TOTAL, extract=_extract_summ_restatement,
         zones=frozenset({SUMM}), name="summ_location_total"),
    Rule(RowKind.RESTATEMENT, _SUMM_ACCOUNT_TOTAL, extract=_extract_summ_restatement,
         zones=frozenset({SUMM}), name="summ_account_total"),
    Rule(RowKind.RESTATEMENT, _SUMM_GRAND_SAMPLES, extract=_extract_summ_grand,
         zones=frozenset({SUMM}), name="summ_grand_samples"),
    Rule(RowKind.GRAND_TOTAL, _INVOICE_TOTAL,
         extract=lambda m, ln, c: {"amount": _money(m.group("amount"))},
         zones=frozenset({SUMM}), name="invoice_total"),
    Rule(RowKind.ROW_COUNT, _SUMM_LOCATION_ITEM, extract=_extract_summ_item,
         zones=frozenset({SUMM}), name="summ_location_item"),
    Rule(RowKind.ROW_COUNT, _SUMM_ITEM, extract=_extract_summ_item,
         zones=frozenset({SUMM}), name="summ_item"),

    # --- Template A: otsinv_prod. A second charge stream. --------------------
    Rule(RowKind.SECTION_HEADER, _SHIPPED_TO,
         extract=lambda m, ln, c: {
             "order_account": m.group("order_account"),
             "purchase_order": (m.group("purchase_order") or "").strip(),
             "is_order": True,
         },
         zones=frozenset({PROD}), name="prod_shipped_to"),
    Rule(RowKind.SECTION_SUBTOTAL, _ORDER_TOTAL,
         extract=lambda m, ln, c: {"amount": _money(m.group("amount"))},
         zones=frozenset({PROD}), name="prod_order_total"),
    Rule(RowKind.GROUP_SUBTOTAL, _PRODUCT_CHARGES_TOTAL,
         extract=lambda m, ln, c: {"amount": _money(m.group("amount"))},
         zones=frozenset({PROD}), name="prod_total_product_charges"),
    Rule(RowKind.CHARGE, _PROD_CHARGE, extract=_extract_prod_charge,
         zones=frozenset({PROD}), name="prod_charge"),

    # Account header last among the ACCOUNT: shapes, so the product-total and
    # account-total variants win first.
    Rule(RowKind.SECTION_HEADER, _ACCOUNT_HEADER,
         extract=lambda m, ln, c: {
             "account": m.group("account"),
             "account_name": (m.group("account_name") or "").strip(),
         },
         zones=frozenset({DETAIL, SUMM}), name="account_header"),

    # --- Template B: the grid ------------------------------------------------
    Rule(RowKind.INVOICE_SUBTOTAL, _GRID_SUBTOTAL,
         extract=lambda m, ln, c: {"amount": _money(m.group("amount"))},
         zones=frozenset({CURRENT}), name="grid_current_period_subtotal"),
    Rule(RowKind.GRAND_TOTAL, _GRID_TOTAL,
         extract=lambda m, ln, c: {"amount": _money(m.group("amount"))},
         zones=frozenset({CURRENT}), name="grid_current_period_total"),
    Rule(RowKind.CHARGE, _GRID_PARENT, extract=_extract_grid_charge,
         zones=frozenset({CURRENT}), name="grid_charge_parent"),
    Rule(RowKind.CHARGE, _GRID_CHILD, extract=_extract_grid_charge,
         guard=_grid_child_guard, zones=frozenset({CURRENT}), name="grid_charge_child"),
    # Deliberately NOT matched here: the container document's roll-up block prints
    # one `01/31/26  INVOICE  02021085  86160681  169.00` line per child invoice.
    # Those are neither charges nor sums of this document, and classifying them
    # would quiet the tripwire on the one file that most needs it — a batch of
    # 494 invoices, including clinical-lab service lines this spec has never been
    # approved against. They stay UNCLASSIFIED so the file can never verify.
    Rule(RowKind.CONTINUATION, _GRID_ID_CONTINUATION, guard=_grid_id_guard,
         extract=lambda m, ln, c: {"text": m.group("text")},
         zones=frozenset({CURRENT}), name="grid_patient_id_continuation"),
    Rule(RowKind.IGNORABLE, _LAB_INDEX_ROW, zones=frozenset({CURRENT, PRIOR}),
         name="performing_lab_index_row"),

    # --- The remit stub ------------------------------------------------------
    Rule(RowKind.RESTATEMENT, _STUB_ROW, extract=_extract_stub,
         zones=frozenset({REMIT}), name="remit_stub_row"),

    # --- Decoy blocks, matched structurally before their catch-alls ----------
    Rule(RowKind.IGNORABLE, _TOTAL_AMOUNT_DUE, zones=frozenset({REMIT}),
         name="total_amount_due_decoy"),
    Rule(RowKind.IGNORABLE, _AGING_ROW, zones=frozenset({REMIT}),
         name="aging_buckets_decoy"),
    Rule(RowKind.IGNORABLE, _ORPHAN_STUB_AMOUNT, zones=frozenset({REMIT, STMT}),
         name="orphan_amount_column_value"),
    Rule(RowKind.IGNORABLE, _STMT_BALANCE, zones=frozenset({STMT}),
         name="statement_account_balance"),
    Rule(RowKind.IGNORABLE, _STMT_LEDGER, zones=frozenset({STMT}),
         name="statement_ledger_entry"),
    Rule(RowKind.IGNORABLE, _PRIOR_BALANCE, zones=frozenset({PRIOR}),
         name="prior_period_balance"),
    Rule(RowKind.IGNORABLE, _PRIOR_ENTRY, zones=frozenset({PRIOR}),
         name="prior_period_entry"),

    # --- Positional catch-alls, last ----------------------------------------
    Rule(RowKind.IGNORABLE, r"^.+$", guard=_in_page_header, zones=frozenset({"*"}),
         name="page_letterhead"),
    Rule(RowKind.IGNORABLE, r"^.+$", guard=_prod_supporting, zones=frozenset({PROD}),
         name="prod_ship_to_block"),
    # The remit stub and the statement ledger are non-charge pages by the
    # vendor's own form definition: otsinv_remit is a payment stub and
    # otsinv_stmt is an account statement. Neither can carry an invoice charge,
    # so a catch-all here is scoped to exactly the two zones where every money
    # figure has already been accounted for above.
    Rule(RowKind.IGNORABLE, r"^.+$", zones=frozenset({REMIT, STMT, PRIOR}),
         name="non_charge_page"),
]


# ---------------------------------------------------------------------------
# Post-processing: grouping keys, multi-row item assembly, container refusal
# ---------------------------------------------------------------------------

_CONTAINER_NOTE = (
    "CONTAINER DOCUMENT \u2014 {n} nested sub-invoices, REFUSED. No single-level "
    "reconciliation exists for this file: each sub-invoice prints its own "
    "'Current Period Subtotal' and 'CURRENT PERIOD TOTAL', and they span more "
    "than one billing period. The {n} sub-invoice totals sum to {total}, this "
    "document's printed CURRENT AMOUNT DUE is {current} and its TOTAL AMOUNT DUE "
    "is {due} \u2014 three different figures, none of which is an invoice value. "
    "{unrecognised} further lines belong to service lines this spec has not been "
    "approved against. Split the file per sub-invoice before extracting; every "
    "rung is reported not-applicable rather than emitting a number that belongs "
    "to no invoice."
)


def _postprocess(rows: list[ClassifiedRow]) -> None:
    """Assign the keys every rung buckets on, then fold the multi-row items.

    Grouping keys come in two flavours on purpose:

    * a **sequential** key (`location_key`, `account_key`, `order_key`) used for
      the same-zone rungs. Sequential rather than the printed account number
      because a number could repeat within one invoice, and two buckets merged
      into one is a weaker check.
    * a **natural** key (`location_nat`, `account_nat`) used for the cross-page
      rungs that pair otsinv_detail against the restated otsinv_summ copy. Those
      two pages are independent row streams, so only the printed identifiers can
      join them.
    """
    # -- Template A: detail zone ------------------------------------------------
    account_seq = location_seq = 0
    account_no = account_name = location_no = ""
    for row in rows:
        if row.zone is not DETAIL and row.zone != DETAIL:
            continue
        if row.kind is RowKind.SECTION_HEADER and row.fields.get("account"):
            account_seq += 1
            account_no = row.fields["account"]
            account_name = row.fields.get("account_name", "")
        elif row.kind is RowKind.SECTION_HEADER and row.fields.get("location"):
            location_seq += 1
            location_no = row.fields["location"]
        row.fields.setdefault("account_number", account_no)
        row.fields.setdefault("account_name", account_name)
        row.fields.setdefault("location", location_no)
        row.fields["account_key"] = f"a{account_seq}"
        row.fields["location_key"] = f"l{location_seq}"
        row.fields["account_nat"] = account_no
        row.fields["location_nat"] = f"{account_no}/{location_no}"

    # -- Template A: summary zone (independent counters) -----------------------
    summ_account_no = summ_location_no = ""
    for row in rows:
        if row.zone != SUMM:
            continue
        if row.kind is RowKind.SECTION_HEADER and row.fields.get("account"):
            summ_account_no = row.fields["account"]
        if row.fields.get("location"):
            summ_location_no = row.fields["location"]
        row.fields.setdefault("account_number", summ_account_no)
        row.fields["account_nat"] = summ_account_no
        row.fields["location_nat"] = f"{summ_account_no}/{summ_location_no}"

    # -- Template A: product zone ---------------------------------------------
    order_seq = 0
    order_account = purchase_order = ""
    for row in rows:
        if row.zone != PROD:
            continue
        if row.kind is RowKind.SECTION_HEADER and row.fields.get("is_order"):
            order_seq += 1
            order_account = row.fields.get("order_account", "")
            purchase_order = row.fields.get("purchase_order", "")
        row.fields["order_key"] = f"o{order_seq}"
        row.fields.setdefault("account_number", order_account)
        row.fields.setdefault("purchase_order", purchase_order)

    # -- Multi-row items: carry the sample's identity onto its charges ---------
    # Template A prints the donor once and its tests beneath. Without this the
    # line items would name no patient at all while reconciling perfectly.
    sample: ClassifiedRow | None = None
    for row in rows:
        if row.kind is RowKind.SECTION_HEADER and row.fields.get("is_sample"):
            sample = row
        elif row.kind is RowKind.SECTION_HEADER:
            sample = None
        elif row.kind is RowKind.CHARGE and row.zone == DETAIL and sample is not None:
            for name in ("ssn", "sample_id", "accession", "reference",
                         "service_date", "donor"):
                row.fields.setdefault(name, sample.fields.get(name, ""))
            sample.fields.setdefault("charge_lines", 0)
            sample.fields["charge_lines"] += 1
        elif row.kind is RowKind.CONTINUATION and row.zone == DETAIL and sample is not None:
            target = row.fields.get("target", "sample_id")
            base = str(sample.fields.get(target, "") or "")
            sample.fields[target] = f"{base} {row.fields.get('text','')}".strip()

    # The count rung on the summary page's TESTS column joins on location *and*
    # test code, which is the tightest available check that the multi-row items
    # were split into the right number of charges.
    for row in rows:
        if row.zone in (DETAIL, SUMM) and row.fields.get("code"):
            row.fields["code_key"] = (
                f"{row.fields.get('location_nat', '')}|{row.fields['code']}"
            )

    # -- Template B: fold the wrapped patient id back onto its charge ----------
    parent: ClassifiedRow | None = None
    for row in rows:
        if row.kind is RowKind.CHARGE and row.zone == CURRENT:
            if row.fields.get("is_grid_parent"):
                parent = row
            elif parent is not None:
                for name in ("donor", "service_date", "accession"):
                    row.fields.setdefault(name, parent.fields.get(name, ""))
            extra = row.fields.get("patient_id_part")
            if extra and parent is not None:
                parent.fields.setdefault("patient_parts", []).append(extra)
        elif row.kind is RowKind.CONTINUATION and parent is not None:
            text = row.fields.get("text", "")
            if text:
                parent.fields.setdefault("patient_parts", []).append(text)
    # The stacked values are joined with a space, never concatenated. Template B
    # prints `0` on one line and `0590616994` on the next; gluing them yields
    # `00590616994`, an identifier that is on no page of the invoice.
    for row in rows:
        if row.kind is RowKind.CHARGE and row.zone == CURRENT:
            if row.fields.get("is_grid_parent"):
                row.fields["patient_detail"] = " ".join(row.fields.get("patient_parts", []))
            row.fields.setdefault("patient_detail", "")

    # -- The remit stub line that names *this* invoice -------------------------
    invoice_number = ""
    for row in rows:
        hit = _INVOICE_HEADER.match(row.raw)
        if hit:
            invoice_number = hit.group("invoice")
            break
    for row in rows:
        if row.fields.get("is_stub"):
            row.fields["stub_key"] = (
                "self" if row.fields.get("stub_invoice") == invoice_number else None
            )

    # -- Container refusal -----------------------------------------------------
    # More than one printed grand total in one file means this is not an
    # invoice, it is a batch of them. 494 of them, in the one file in this
    # corpus, spanning two billing periods and including service lines this
    # spec has never been approved against. Every rung is marked inapplicable
    # rather than being allowed to compare a computed figure against the sum of
    # 494 unrelated printed ones — that comparison is what would let a wrong
    # number look verified.
    grand_totals = [r for r in rows if r.kind is RowKind.GRAND_TOTAL]
    if len(grand_totals) > 1:
        total = sum((r.amount or Decimal("0.00") for r in grand_totals), Decimal("0.00"))
        printed = _printed_account_figures(rows)
        unrecognised = sum(1 for r in rows if r.kind is RowKind.UNCLASSIFIED)
        for row in rows:
            row.fields["container"] = True
        rows.insert(
            0,
            ClassifiedRow(
                kind=RowKind.UNCLASSIFIED,
                page=grand_totals[1].page,
                line_no=grand_totals[1].line_no,
                raw=_CONTAINER_NOTE.format(
                    n=len(grand_totals),
                    total=f"${total:,}",
                    current=f"${printed.get('current', '?')}",
                    due=f"${printed.get('due', '?')}",
                    unrecognised=unrecognised,
                ),
                zone=grand_totals[1].zone,
                rule="container_document",
                fields={"container": True},
            ),
        )


_AGING_VALUES = re.compile(
    r"^\s*(?:\$\s?)?[\d,.]+(?:CR)?\s+(?:\$\s?)?[\d,.]+(?:CR)?\s+(?:\$\s?)?[\d,.]+(?:CR)?"
    r"\s+(?:\$\s?)?(?P<current>[\d,]+\.\d{2})(?P<ccr>CR)?"
    r"(?:\s+DUE\s+(?:\$\s?)?(?P<due>[\d,]+\.\d{2})(?P<dcr>CR)?)?\s*$"
)


def _printed_account_figures(rows: list[ClassifiedRow]) -> dict:
    """Read the aging row's CURRENT AMOUNT DUE / TOTAL AMOUNT DUE, for reporting.

    Never used as a rung. The label `TOTAL AMOUNT DUE` is split across three
    physical lines with its value on a different line in each of the two
    templates, and one variant of this document prints the aging row with no
    labels at all. Pairing them spatially is guesswork, so these figures are
    reported and never reconciled against.
    """
    out: dict = {}
    for row in rows:
        if row.zone != REMIT:
            continue
        hit = _AGING_VALUES.match(row.raw)
        if hit:
            out["current"] = hit.group("current") + (hit.group("ccr") or "")
            if hit.group("due"):
                out["due"] = hit.group("due") + (hit.group("dcr") or "")
            break
    return out


# ---------------------------------------------------------------------------
# The ladder
# ---------------------------------------------------------------------------

def _in(zone: str):
    return lambda r: r.zone == zone


_LADDER = [
    # --- Template A: otsinv_detail -------------------------------------------
    LevelCheck(
        "detail_location_total",
        computed_from=(RowKind.CHARGE,),
        printed_kind=RowKind.SECTION_SUBTOTAL,
        group_by="location_key",
        where=_in(DETAIL),
        description="sample charges in a location sum to its printed LOCATION TOTAL",
    ),
    LevelCheck(
        "detail_account_total",
        computed_from=(RowKind.CHARGE,),
        printed_kind=RowKind.GROUP_SUBTOTAL,
        group_by="account_key",
        where=_in(DETAIL),
        description="sample charges in an account sum to its printed ACCOUNT TOTAL",
    ),
    LevelCheck(
        "detail_total_samples_billed",
        computed_from=(RowKind.CHARGE,),
        printed_kind=RowKind.INVOICE_SUBTOTAL,
        where=_in(DETAIL),
        # Omitted by the vendor when the invoice has a single account: with
        # nothing above the ACCOUNT TOTAL level there is no grand line to print.
        required=False,
        description="every sample charge sums to TOTAL SAMPLES BILLED",
    ),
    # Counts, not money. `SAMPLES:` counts donor rows, and a whole sample whose
    # charges are $0.00 — which happens — moves no total at all.
    LevelCheck(
        "samples_per_location",
        computed_from=(RowKind.SECTION_HEADER,),
        printed_kind=RowKind.SECTION_SUBTOTAL,
        mode=CheckMode.COUNT,
        printed_field="samples",
        group_by="location_key",
        where=lambda r: r.zone == DETAIL and (
            r.fields.get("is_sample") or r.kind is RowKind.SECTION_SUBTOTAL
        ),
        description="donor rows in a location equal its printed SAMPLES count",
    ),
    LevelCheck(
        "samples_per_account",
        computed_from=(RowKind.SECTION_HEADER,),
        printed_kind=RowKind.GROUP_SUBTOTAL,
        mode=CheckMode.COUNT,
        printed_field="samples",
        group_by="account_key",
        where=lambda r: r.zone == DETAIL and (
            r.fields.get("is_sample") or r.kind is RowKind.GROUP_SUBTOTAL
        ),
        description="donor rows in an account equal its printed SAMPLES count",
    ),
    LevelCheck(
        "samples_billed_count",
        computed_from=(RowKind.SECTION_HEADER,),
        printed_kind=RowKind.INVOICE_SUBTOTAL,
        mode=CheckMode.COUNT,
        printed_field="samples",
        where=lambda r: r.zone == DETAIL and (
            r.fields.get("is_sample") or r.kind is RowKind.INVOICE_SUBTOTAL
        ),
        # Omitted by the vendor when the invoice has a single account: with
        # nothing above the ACCOUNT TOTAL level there is no grand line to print.
        required=False,
        description="donor rows equal the printed TOTAL SAMPLES BILLED count",
    ),

    # --- Template A: otsinv_prod ---------------------------------------------
    LevelCheck(
        "product_order_total",
        computed_from=(RowKind.CHARGE,),
        printed_kind=RowKind.SECTION_SUBTOTAL,
        group_by="order_key",
        where=_in(PROD),
        description="product items in an order sum to its printed ORDER TOTAL",
    ),
    LevelCheck(
        "product_charges_total",
        computed_from=(RowKind.CHARGE,),
        printed_kind=RowKind.GROUP_SUBTOTAL,
        group_by="order_key",
        where=_in(PROD),
        description="product items sum to the printed TOTAL PRODUCT CHARGES",
    ),

    # --- Template A: the restated otsinv_summ copy ---------------------------
    # These are the rows that double the invoice if they are summed with the
    # detail. Declared as rungs instead, they become cross-page checks: the
    # summary and the detail are separately generated row streams, so agreeing
    # per location and per account is real evidence, not self-consistency.
    LevelCheck(
        "summary_restates_location",
        computed_from=(RowKind.CHARGE,),
        printed_kind=RowKind.RESTATEMENT,
        group_by="location_nat",
        where=lambda r: (r.kind is RowKind.CHARGE and r.zone == DETAIL) or (
            r.zone == SUMM and r.fields.get("is_summ_restatement")
            and r.fields.get("location")
        ),
        description="otsinv_summ restates each LOCATION TOTAL identically",
    ),
    LevelCheck(
        "summary_restates_account",
        computed_from=(RowKind.CHARGE,),
        printed_kind=RowKind.RESTATEMENT,
        group_by="account_nat",
        where=lambda r: (r.kind is RowKind.CHARGE and r.zone == DETAIL) or (
            r.zone == SUMM and r.fields.get("is_summ_restatement")
            and r.fields.get("account")
        ),
        description="otsinv_summ restates each ACCOUNT TOTAL identically",
    ),
    LevelCheck(
        "summary_grand_samples",
        computed_from=(RowKind.CHARGE,),
        printed_kind=RowKind.RESTATEMENT,
        where=lambda r: (r.kind is RowKind.CHARGE and r.zone == DETAIL)
        or bool(r.fields.get("is_summ_grand")),
        # Omitted by the vendor when the invoice has a single account: with
        # nothing above the ACCOUNT TOTAL level there is no grand line to print.
        required=False,
        description="otsinv_summ's TOTAL SAMPLES amount equals the sample charges",
    ),
    LevelCheck(
        "summary_grand_sample_count",
        computed_from=(RowKind.SECTION_HEADER,),
        printed_kind=RowKind.RESTATEMENT,
        mode=CheckMode.COUNT,
        printed_field="samples",
        where=lambda r: (r.zone == DETAIL and r.fields.get("is_sample"))
        or bool(r.fields.get("is_summ_grand")),
        # Omitted by the vendor when the invoice has a single account: with
        # nothing above the ACCOUNT TOTAL level there is no grand line to print.
        required=False,
        description="otsinv_summ's TOTAL SAMPLES count equals the donor rows",
    ),
    LevelCheck(
        "summary_tests_per_code",
        computed_from=(RowKind.CHARGE,),
        printed_kind=RowKind.ROW_COUNT,
        mode=CheckMode.COUNT,
        printed_field="tests",
        group_by="code_key",
        where=lambda r: (r.kind is RowKind.CHARGE and r.zone == DETAIL)
        or r.kind is RowKind.ROW_COUNT,
        description=(
            "the summary's TESTS count for each location and test code equals the "
            "number of detail charge lines carrying that code"
        ),
    ),
    LevelCheck(
        "summary_product_total",
        computed_from=(RowKind.CHARGE,),
        printed_kind=RowKind.RESTATEMENT,
        where=lambda r: (r.kind is RowKind.CHARGE and r.zone == PROD)
        or bool(r.fields.get("is_summ_product")),
        description="otsinv_summ's per-account TOTAL PRODUCT CHARGES equal the product items",
    ),

    # --- Template B ----------------------------------------------------------
    LevelCheck(
        "current_period_subtotal",
        computed_from=(RowKind.CHARGE,),
        printed_kind=RowKind.INVOICE_SUBTOTAL,
        where=_in(CURRENT),
        description="grid charges sum to the printed Current Period Subtotal",
    ),

    # --- Both templates ------------------------------------------------------
    # The only grand total this spec can reach. `TOTAL AMOUNT DUE`,
    # `ACCOUNT BALANCE:` and the four aging buckets all live in zones that carry
    # no GRAND_TOTAL rule at all, so the wrong answer is unreachable by
    # construction rather than by a blocklist.
    LevelCheck(
        "grand_total",
        computed_from=(RowKind.CHARGE,),
        printed_kind=RowKind.GRAND_TOTAL,
        description=(
            "every charge — samples and products — sums to INVOICE TOTAL "
            "(Template A) or CURRENT PERIOD TOTAL (Template B)"
        ),
    ),
    LevelCheck(
        "remit_stub_balance",
        computed_from=(RowKind.CHARGE,),
        printed_kind=RowKind.RESTATEMENT,
        where=lambda r: r.kind is RowKind.CHARGE or r.fields.get("stub_key") == "self",
        description=(
            "the page 1 payment stub's own line for this invoice number equals "
            "the charges"
        ),
    ),
]



def _outside_container(where):
    """Make a rung inapplicable inside a container document.

    Not a tolerance and not a skip: a container's printed sums belong to its
    children, so comparing anything against them is meaningless. Excluding both
    sides leaves every rung `not_applicable`, the invoice unverified, and the
    refusal note as the reason.
    """
    if where is None:
        return lambda r: not r.fields.get("container")
    return lambda r: not r.fields.get("container") and where(r)


LADDER = [replace(c, where=_outside_container(c.where)) for c in _LADDER]


SPEC = InvoiceSpec(
    name="labcorp",
    description=(
        "Labcorp / Occupational Testing Services — otsinv multi-page form and the "
        "no-footer grid, one spec, zone-scoped"
    ),
    rules=RULES,
    zone_markers=ZONE_MARKERS,
    ladder=LADDER,
    postprocess=_postprocess,
    header_fields={
        # `INVOICE NUMBER` reads the literal string SUMMARY on page 1 of every
        # file in this corpus, so the pattern is shaped to match only the numeric
        # variant printed in the header block of every later page.
        "invoice_number": (
            r"^\s*\d{6,9}\s+(\d{6,9})\s+\d{1,2}/\d{1,2}/\d{2,4}\b"
        ),
        "account_number": (
            r"^\s*(\d{6,9})\s+(?:\d{6,9}|SUMMARY)\s+\d{1,2}/\d{1,2}/\d{2,4}\b"
        ),
        "invoice_date": (
            r"^\s*\d{6,9}\s+(?:\d{6,9}|SUMMARY)\s+(\d{1,2}/\d{1,2}/\d{2,4})\b"
        ),
        "bill_to_account": r"^\s*Account Number:?\s+(\d+)\b",
    },
    line_item_fields=(
        "account_number",
        "account_name",
        "location",
        "purchase_order",
        "order_account",
        "code",
        "description",
        "quantity",
        "unit_price",
        "ssn",
        "sample_id",
        "accession",
        "reference",
        "service_date",
        "donor",
        "patient_detail",
        "lab_code",
    ),
    # Invoice numbers are unique per file here, but the same number is printed on
    # the stub of every later invoice for the account, and one variant prints
    # `SUMMARY` in the number field. Pairing it with the account keeps the
    # dedup key meaningful even when a number is unreadable.
    identity_fields=("invoice_number", "account_number"),
)
