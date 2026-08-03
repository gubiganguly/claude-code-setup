#!/usr/bin/env python3
"""Command line entry point for the invoice-parser-gen skill.

    run.py sample  <folder> --spec NAME    parse one representative, write nothing
    run.py extract <folder> --spec NAME    parse every new invoice, update the sheet
    run.py status  <folder>                what is bound, what is done, what is new

`sample` exists to be shown to a human before anything is written. `extract` is
append-only and safe to re-run: it skips invoices already in the sheet and
reports re-issued ones rather than overwriting them.
"""

from __future__ import annotations

import argparse
import importlib
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from engine.classify import Classifier, RowKind  # noqa: E402
from engine.discover import discover  # noqa: E402
from engine.reconcile import CheckStatus  # noqa: E402
from engine.sheet import DEFAULT_FILENAME, ExtractionWorkbook, timestamp  # noqa: E402
from engine.ocr import load_or_ocr  # noqa: E402
from engine.profile import profile  # noqa: E402
from engine.spec import ExtractedInvoice, InvoiceSpec  # noqa: E402
from engine.store import ExtractionStore, Verdict  # noqa: E402
from engine.text import load  # noqa: E402

PDF_GLOBS = ("*.pdf", "*.PDF", "*.Pdf")


def find_pdfs(folder: Path) -> list[Path]:
    found: dict[str, Path] = {}
    for pattern in PDF_GLOBS:
        for path in folder.glob(pattern):
            found[path.name] = path
    return sorted(found.values(), key=lambda p: p.name)


def load_spec(name: str) -> InvoiceSpec:
    module = importlib.import_module(f"specs.{name}")
    spec = getattr(module, "SPEC", None)
    if not isinstance(spec, InvoiceSpec):
        raise SystemExit(f"specs/{name}.py does not define a SPEC of type InvoiceSpec")
    return spec


def pick_representative(paths: list[Path]) -> Path:
    """Choose the invoice most likely to expose a problem, without being freakish.

    Not the first file: alphabetically-first is usually the simplest in the folder,
    so approving it proves the least. But not the largest either. An earlier
    version maximised page count and, on a folder containing a 642-page container
    holding 494 nested sub-invoices, picked exactly the one document that cannot
    reconcile — making the approval step useless.

    So: drop page-count outliers beyond three times the median, then among what
    remains pick the structurally richest, since distinct row shapes is what
    actually predicts whether a human will spot something wrong.
    """
    if not paths:
        raise SystemExit("no PDFs found")

    loaded: list[tuple[Path, int, int]] = []
    for path in paths:
        try:
            doc = load(path)
        except Exception:
            continue
        shapes = len({len(ln.split()) for ln in doc.lines if ln.strip()})
        loaded.append((path, doc.page_count, shapes))
    if not loaded:
        raise SystemExit("no readable PDFs found")

    pages = sorted(item[1] for item in loaded)
    median = pages[len(pages) // 2] or 1
    typical = [item for item in loaded if item[1] <= median * 3] or loaded
    return max(typical, key=lambda item: (item[2], item[1], item[0].name))[0]


# ---------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------


def _fmt(value) -> str:
    if value is None or value == "":
        return "-"
    if isinstance(value, Decimal):
        return f"{value:,.2f}"
    return str(value)


def worst_delta(inv: ExtractedInvoice):
    """The largest absolute discrepancy across every rung, or None if unmeasured.

    Spec-agnostic on purpose. An earlier version compared charges against a rung
    named `invoice_subtotal`, which exists only in some specs and left the column
    blank for the rest. Every spec declares *some* rungs, so the worst delta among
    them is always meaningful and is 0.00 exactly when the invoice verifies.
    """
    deltas = [r.delta for r in inv.reconciliation.results if r.delta is not None]
    return max(deltas, key=abs) if deltas else None


def summary_table(results: list[tuple[str, ExtractedInvoice]]) -> str:
    header = (
        f"{'INVOICE':<13}{'PG':>4}{'LINES':>7}{'CHARGES':>12}{'SUBTOTAL':>12}"
        f"{'TAX':>9}{'TOTAL':>12}{'DELTA':>8}{'CHECKS':>8}  STATUS"
    )
    lines = [header, "-" * len(header)]
    for name, inv in results:
        rec = inv.reconciliation
        subtotal = rec.value_of("invoice_subtotal")
        delta = worst_delta(inv)
        lines.append(
            f"{(inv.identity or name)[:12]:<13}{inv.page_count:>4}{len(inv.line_items):>7}"
            f"{_fmt(inv.computed_total):>12}{_fmt(subtotal):>12}{_fmt(_tax_of(inv)):>9}"
            f"{_fmt(inv.grand_total):>12}{_fmt(delta):>8}"
            f"{f'{sum(1 for r in rec.results if r.ok)}/{len(rec.results)}':>8}"
            f"  {'verified' if inv.verified else inv.status}"
        )
    verified = sum(1 for _, inv in results if inv.verified)
    lines.append("")
    lines.append(
        f"{verified} of {len(results)} extracted with full verification"
        + (f" · {len(results) - verified} flagged" if verified != len(results) else "")
    )

    # Depth is how many rungs actually compared two figures. At depth 1 only the
    # grand total was checkable, which cannot catch a parser that mis-distributes
    # values across rows while still totalling correctly. Saying so is the
    # difference between "verified" and "verified as far as this invoice allows".
    shallow = [inv for _, inv in results if inv.verified and inv.reconciliation.depth == 1]
    if shallow:
        lines.append(
            f"{len(shallow)} of those reconcile at depth 1 — the invoice prints only "
            "one sum, so the line items are checked from a single direction. Treat "
            "them as weaker evidence than the rest."
        )
    advisory = [
        (inv, a) for _, inv in results for a in inv.reconciliation.advisories
    ]
    if advisory:
        lines.append(
            f"{len(advisory)} advisory rung(s) disagreed without failing an invoice:"
        )
        for inv, a in advisory[:6]:
            lines.append(f"   {inv.identity}: {a}")
    ocr = [inv for _, inv in results if inv.ocr_applied]
    if ocr:
        lines.append(
            f"{len(ocr)} were OCR'd. Tesseract misreads digits and labels, so spot "
            "check these against the PDF even where they reconcile."
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------


def cmd_sample(args) -> int:
    folder = Path(args.folder).expanduser().resolve()
    spec = load_spec(args.spec)
    path = Path(args.file).expanduser() if args.file else pick_representative(find_pdfs(folder))

    doc, unusable_reason = load_or_ocr(
        path,
        allow_ocr=bool(getattr(args, "ocr", False)),
        max_pages=getattr(args, "ocr_max_pages", None),
    )
    if unusable_reason:
        print(f"SAMPLE  {path.name}\n  cannot parse: {unusable_reason}")
        return 1
    inv = spec.parse(path, doc=doc)
    rec = inv.reconciliation

    print(f"SAMPLE  {path.name}   spec={spec.name}")
    print(f"        {inv.page_count} page(s), {len(inv.line_items)} line items, "
          f"{'OCR applied' if inv.ocr_applied else 'text layer'}")
    print()
    print("HEADER FIELDS")
    for key, value in inv.fields.items():
        print(f"   {key:<18} {value if value else '(absent)'}")
    print()
    print("ROW CLASSIFICATION")
    for kind, count in Classifier.counts(inv.rows).items():
        marker = "  <-- TRIPWIRE" if kind == RowKind.UNCLASSIFIED.value else ""
        print(f"   {kind:<20} {count:>5}{marker}")
    print()
    print("RECONCILIATION LADDER")
    by_check: dict[str, list] = {}
    for result in rec.results:
        by_check.setdefault(result.check, []).append(result)
    for check, results in by_check.items():
        failed = [r for r in results if not r.ok]
        advisory = [r for r in results if r.status is CheckStatus.ADVISORY_MISMATCH]
        compared = [r for r in results if r.status is CheckStatus.PASS]
        # A rung with nothing to compare is not a pass. Showing it as one put 17
        # "[PASS]" lines directly above "NOTHING COULD BE VERIFIED" on a document
        # where no rung had run at all — the verdict was right and the display
        # flatly contradicted it.
        if failed:
            state = "FAIL"
        elif advisory:
            state = "ADVS"
        elif compared:
            state = "PASS"
        else:
            state = " n/a"
        print(
            f"   [{state}] {check:<22} {len(compared)}/{len(results)} groups compared"
        )
        for bad in (failed + advisory)[:4]:
            print(f"            {bad}")
    print()
    print(f"VERDICT: {'VERIFIED' if inv.verified else inv.status.upper()}"
          f"   (depth {rec.depth}, {sum(1 for r in rec.results if r.ok)}/{len(rec.results)} checks)")
    if not inv.verified:
        print()
        for reason in inv.failure_reasons()[:10]:
            print(f"   ! {reason}")
    print()
    print(f"FIRST {min(args.rows, len(inv.line_items))} LINE ITEMS")
    fields = ["material", "description", "quantity", "unit_price", "amount"]
    for item in inv.line_items[: args.rows]:
        print("   " + " | ".join(f"{str(item.get(f, '')):<28}"[:28] if f == "description"
                                 else f"{str(item.get(f, '')):<12}" for f in fields))
    print()
    print("Nothing was written. Review the above, then run `extract` to process the folder.")
    return 0 if inv.verified else 1


def cmd_extract(args) -> int:
    folder = Path(args.folder).expanduser().resolve()
    store = ExtractionStore(folder)
    spec = load_spec(args.spec) if args.spec else load_spec(_bound_spec(store, folder))
    book = ExtractionWorkbook(folder / (args.sheet or DEFAULT_FILENAME))

    known = store.by_identity()
    already = book.existing_identities() | set(known)

    paths = find_pdfs(folder)
    if not paths:
        print(f"No PDFs in {folder}")
        return 1

    added: list[tuple[str, ExtractedInvoice]] = []
    skipped: list[str] = []
    changed: list[tuple[str, str]] = []
    errored: list[tuple[str, str]] = []
    new_records: list[dict] = []
    when = timestamp()

    unusable: list[tuple[str, str]] = []
    sparse: list[tuple[str, tuple[int, ...]]] = []
    signatures: set[str] = set()

    for path in paths:
        try:
            # Refuse a document we cannot read rather than reporting an empty
            # extraction as a success. An annotation-only text layer is the
            # dangerous case: it has real characters, so a length check passes,
            # and the parser then finds zero line items and raises nothing.
            doc, unusable_reason = load_or_ocr(
                path,
                allow_ocr=bool(getattr(args, "ocr", False)),
                max_pages=getattr(args, "ocr_max_pages", None),
            )
            prof = profile(doc)
        except Exception as exc:
            errored.append((path.name, f"{type(exc).__name__}: {exc}"))
            continue

        if unusable_reason:
            unusable.append((path.name, unusable_reason))
            book.add_exceptions([{
                "Invoice #": "",
                "Status": "needs OCR",
                "Reason": f"{unusable_reason} ({prof.chars_per_page:.0f} chars/page)",
                "Source File": path.name,
                "Extracted": when,
            }])
            continue

        # A layout already bound to a different spec means this document is not
        # the kind the spec in hand was approved for. Parsing it anyway is how a
        # wrong-but-plausible result gets written, so refuse and say which spec
        # the layout belongs to.
        bound_elsewhere = store.spec_for_signature(prof.signature)
        if bound_elsewhere is not None and bound_elsewhere != spec.name:
            unusable.append(
                (path.name, f"layout is bound to spec {bound_elsewhere!r}, not {spec.name!r}")
            )
            book.add_exceptions([{
                "Invoice #": "",
                "Status": "wrong spec",
                "Reason": (
                    f"this layout ({prof.signature}) is bound to {bound_elsewhere!r}; "
                    f"extracting with {spec.name!r} was refused"
                ),
                "Source File": path.name,
                "Extracted": when,
            }])
            continue

        if prof.sparse_pages:
            # Usually benign, occasionally an image page whose rows are lost.
            # Reported rather than acted on: refusing the document would reject
            # every invoice that ends with a blank page.
            sparse.append((path.name, prof.sparse_pages))

        signatures.add(prof.signature)
        try:
            inv = spec.parse(path, doc=doc)
        except Exception as exc:  # a parse crash is data, not a reason to stop
            errored.append((path.name, f"{type(exc).__name__}: {exc}"))
            continue

        triage = store.triage(inv, spec, known)
        if triage.identity in already and triage.verdict is not Verdict.CHANGED:
            skipped.append(path.name)
            continue
        if triage.verdict is Verdict.CHANGED and triage.identity in already:
            changed.append((path.name, triage.detail))
            book.add_exceptions([{
                "Invoice #": inv.identity,
                "Status": "re-issued / changed",
                "Reason": triage.detail,
                "Source File": path.name,
                "Extracted": when,
            }])
            continue

        record = store.record_from(inv, spec)
        new_records.append(record)
        already.add(triage.identity)

        depts = sorted({str(li.get("dept", "")) for li in inv.line_items if li.get("dept")})
        rec = inv.reconciliation
        book.add_invoice(
            {
                "Invoice #": inv.identity,
                "Invoice Date": inv.fields.get("invoice_date", ""),
                "Status": "verified" if inv.verified else inv.status,
                "Pages": inv.page_count,
                "Line Items": len(inv.line_items),
                "Computed Total": inv.computed_total,
                "Printed Subtotal": rec.value_of("invoice_subtotal"),
                "Tax": _tax_of(inv),
                "Printed Total": inv.grand_total,
                "Delta": worst_delta(inv),
                "Checks": f"{sum(1 for r in rec.results if r.ok)}/{len(rec.results)}",
                "Depth": rec.depth,
                "Departments": ", ".join(depts),
                "Service Ticket": inv.fields.get("service_ticket", ""),
                "Customer Ref": inv.fields.get("customer_ref", ""),
                "User ID": inv.fields.get("user_id", ""),
                "Sold To": inv.fields.get("sold_to", ""),
                "Payer": inv.fields.get("payer", ""),
                "Payment Terms": inv.fields.get("payment_terms", ""),
                "Sort #": inv.fields.get("sort_number", ""),
                "Route": inv.fields.get("route", ""),
                "OCR": "yes" if inv.ocr_applied else "",
                "Source File": path.name,
                "Extracted": when,
                "Notes": None,
                "_verified": inv.verified,
            },
            [
                {
                    "Invoice #": inv.identity,
                    "Invoice Date": inv.fields.get("invoice_date", ""),
                    "Department": item.get("dept", ""),
                    "Employee": item.get("employee", ""),
                    "Material": item.get("material", ""),
                    "Description": item.get("description", ""),
                    "Variant": item.get("variant", ""),
                    "Freq": item.get("freq", ""),
                    "Exch": item.get("exch", ""),
                    "Qty": item.get("quantity", ""),
                    "Unit Price": item.get("unit_price", ""),
                    "Line Total": item.get("amount"),
                    "Taxable": item.get("taxable", ""),
                    "Page": item.get("page", ""),
                }
                for item in inv.line_items
            ],
        )
        if not inv.verified:
            book.add_exceptions([
                {
                    "Invoice #": inv.identity,
                    "Status": inv.status,
                    "Reason": reason,
                    "Source File": path.name,
                    "Extracted": when,
                }
                for reason in inv.failure_reasons()
            ])
        added.append((path.name, inv))

    for name, message in errored:
        book.add_exceptions([{
            "Invoice #": "", "Status": "parse error", "Reason": message,
            "Source File": name, "Extracted": when,
        }])

    if added or changed or errored or unusable:
        book.save()
        store.append(new_records)
    # Bind every layout seen to this spec, so a later run needs no --spec and a
    # NEW layout appearing in the folder is detectable rather than silently
    # parsed with rules that were never approved for it.
    for signature in signatures:
        if store.spec_for_signature(signature) is None:
            store.bind(spec.name, signature)

    print(f"Folder:  {folder}")
    print(f"Sheet:   {book.path.name}")
    print(f"PDFs:    {len(paths)}   added {len(added)}   "
          f"already recorded {len(skipped)}   re-issued {len(changed)}   "
          f"needs OCR {len(unusable)}   errors {len(errored)}")
    print()
    if added:
        print(summary_table(added))
    else:
        print("Nothing new to extract.")
    for name, detail in changed:
        print(f"\n  RE-ISSUED  {name}: {detail}")
    for name, pages in sparse[:6]:
        print(f"\n  SPARSE     {name}: page(s) {list(pages)} have almost no text — "
              "benign if blank, but check they are not image pages with rows on them")
    for name, reason in unusable:
        print(f"\n  NEEDS OCR  {name}: {reason}")
    for name, message in errored:
        print(f"\n  ERROR      {name}: {message}")
    return (
        0
        if not (changed or errored or unusable)
        and all(inv.verified for _, inv in added)
        else 1
    )


def _bound_spec(store: ExtractionStore, folder: Path) -> str:
    """Resolve the spec from the folder's bindings when --spec is omitted."""
    names = {entry["spec"] for entry in store.bindings().get("specs", {}).values()}
    if len(names) == 1:
        return names.pop()
    if not names:
        raise SystemExit(
            f"No spec bound to {folder}. Pass --spec NAME for the first run."
        )
    raise SystemExit(
        f"{folder} has several specs bound ({', '.join(sorted(names))}). "
        "Pass --spec NAME explicitly."
    )


def _tax_of(inv: ExtractedInvoice):
    for row in inv.rows:
        if row.kind is RowKind.TAX:
            return row.amount
    return None


def cmd_discover(args) -> int:
    """Profile a folder and search for its grammar. Writes nothing."""
    folder = Path(args.folder).expanduser().resolve()
    paths = find_pdfs(folder)
    if not paths:
        print(f"No PDFs in {folder}")
        return 1
    report = discover(paths, sample=args.sample, allow_ocr=bool(args.ocr))
    print(f"FOLDER  {folder}\n")
    print(report.render())
    print(
        "\nNothing was written. Use this to write the spec, then `sample` it for "
        "approval before extracting."
    )
    return 0


def cmd_status(args) -> int:
    folder = Path(args.folder).expanduser().resolve()
    store = ExtractionStore(folder)
    book = ExtractionWorkbook(folder / (args.sheet or DEFAULT_FILENAME))
    records = store.records()
    paths = find_pdfs(folder)
    identities = book.existing_identities() | set(store.by_identity())

    print(f"Folder:   {folder}")
    print(f"PDFs:     {len(paths)}")
    print(f"Sheet:    {'present' if book.path.is_file() else 'not created yet'}"
          f"  ({book.path.name})")
    print(f"Recorded: {len(identities)} invoice(s)")
    bindings = store.bindings().get("specs", {})
    if bindings:
        for signature, entry in bindings.items():
            print(f"Bound:    {entry['spec']}  <- signature {signature[:24]}  ({entry['bound_at']})")
    else:
        print("Bound:    nothing yet")
    flagged = [r for r in records if not r.get("verified")]
    if flagged:
        print(f"\nFlagged ({len(flagged)}):")
        for record in flagged[:20]:
            print(f"   {record['identity']:<16} {record['status']}")
            for reason in record.get("failures", [])[:2]:
                print(f"      {reason}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run.py", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_sample = sub.add_parser("sample", help="parse one invoice, write nothing")
    p_sample.add_argument("folder")
    p_sample.add_argument("--spec", required=True)
    p_sample.add_argument("--file", help="specific PDF instead of the auto-picked one")
    p_sample.add_argument("--rows", type=int, default=12)
    p_sample.add_argument("--ocr", action="store_true")
    p_sample.add_argument("--ocr-max-pages", type=int, default=60)
    p_sample.set_defaults(func=cmd_sample)

    p_extract = sub.add_parser("extract", help="parse every new invoice into the sheet")
    p_extract.add_argument("folder")
    p_extract.add_argument("--spec", help="omit to use the spec bound to this folder")
    p_extract.add_argument("--sheet")
    p_extract.add_argument(
        "--ocr",
        action="store_true",
        help="OCR files with no usable text layer instead of refusing them",
    )
    p_extract.add_argument(
        "--ocr-max-pages",
        type=int,
        default=60,
        help="refuse to OCR documents longer than this (default 60)",
    )
    p_extract.set_defaults(func=cmd_extract)

    p_discover = sub.add_parser(
        "discover", help="profile a folder and search for its grammar"
    )
    p_discover.add_argument("folder")
    p_discover.add_argument("--sample", type=int, default=8)
    p_discover.add_argument("--ocr", action="store_true")
    p_discover.set_defaults(func=cmd_discover)

    p_status = sub.add_parser("status", help="report folder state")
    p_status.add_argument("folder")
    p_status.add_argument("--sheet")
    p_status.set_defaults(func=cmd_status)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
