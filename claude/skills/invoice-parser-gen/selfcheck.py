#!/usr/bin/env python3
"""Verify an installation without needing any invoices.

A coworker installing this will not have the corpus the specs were built against,
so the usual proof (309 invoices reconciling) is unavailable to them. This checks
the things that can be checked from nothing: the external tools are present, the
modules import, money parses correctly at every awkward edge, and a synthetic
invoice runs the whole classify-and-reconcile path end to end.

    python3 selfcheck.py

Exits non-zero on the first real problem, with the fix.
"""

from __future__ import annotations

import importlib
import shutil
import sys
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

FAILURES: list[str] = []
NOTES: list[str] = []


def check(label: str, ok: bool, fix: str = "") -> bool:
    print(f"  {'ok  ' if ok else 'FAIL'}  {label}")
    if not ok and fix:
        FAILURES.append(f"{label}\n        fix: {fix}")
    elif not ok:
        FAILURES.append(label)
    return ok


print("1. external tools")
poppler = shutil.which("pdftotext") and shutil.which("pdfinfo")
check(
    "pdftotext and pdfinfo (poppler)",
    bool(poppler),
    "macOS: brew install poppler   ·   Debian/Ubuntu: apt-get install poppler-utils",
)
if not shutil.which("tesseract"):
    NOTES.append(
        "tesseract is absent. Everything works except --ocr, which is only needed "
        "for scanned invoices. Install with: brew install tesseract"
    )
    print("  --    tesseract (optional, only for --ocr)")
else:
    print("  ok    tesseract")

print("\n2. python packages")
for module, package in (("fitz", "pymupdf"), ("openpyxl", "openpyxl")):
    try:
        importlib.import_module(module)
        check(f"{package}", True)
    except ImportError:
        check(f"{package}", False, f"pip3 install {package}")

print("\n3. engine modules")
engine_ok = True
for name in (
    "text", "money", "classify", "columns", "reconcile",
    "spec", "profile", "discover", "ocr", "store", "sheet",
):
    try:
        importlib.import_module(f"engine.{name}")
    except Exception as exc:
        engine_ok = False
        check(f"engine.{name}", False, str(exc)[:120])
if engine_ok:
    check("all 11 engine modules import", True)

print("\n4. vendor specs")
# Resolved against this file, not the working directory. Relative to the cwd it
# silently found zero specs and still reported the install healthy — checking
# nothing and passing, which is the exact failure this project exists to catch.
specs = sorted(p.stem for p in (HERE / "specs").glob("*.py") if p.stem != "__init__")
if not check("found vendor specs to check", bool(specs),
             f"no *.py under {HERE / 'specs'} — the copy is incomplete"):
    specs = []
for name in specs:
    try:
        module = importlib.import_module(f"specs.{name}")
        spec = getattr(module, "SPEC")
        ok = bool(spec.rules) and bool(spec.ladder)
    except Exception as exc:
        ok = False
        NOTES.append(f"specs.{name} failed to load: {str(exc)[:100]}")
    check(f"specs.{name}", ok)

print("\n5. money parsing edge cases")
if not FAILURES:
    from engine.money import parse_money

    cases = [
        ("210.00", "210.00", {}),
        ("$1,234.56", "1234.56", {}),
        ("-$1,032.35", "-1032.35", {}),      # sign outside the symbol
        ("$-1,032.35", "-1032.35", {}),      # sign inside the symbol
        ("(11.40)", "-11.40", {}),           # accounting negative
        ("1,032.35-", "-1032.35", {}),       # trailing minus
        ("1.234,56", "1234.56", {}),         # European separators
        ("$45335.1", "45335.1", {"min_decimals": 1}),
        ("0.589", None, {}),                 # a 3dp rate is not money
        ("2026", None, {}),                  # a bare integer is not money
    ]
    bad = []
    for token, want, kwargs in cases:
        got = parse_money(token, **kwargs)
        expected = None if want is None else Decimal(want)
        if got != expected:
            bad.append(f"{token!r} gave {got} want {expected}")
    check(f"{len(cases)} money cases", not bad, "; ".join(bad))

print("\n6. end-to-end on a synthetic invoice")
if not FAILURES:
    from engine.classify import Classifier, RowKind, Rule
    from engine.money import parse_money
    from engine.reconcile import LevelCheck, reconcile
    from engine.text import Document, Page

    NUM = r"[\d,]+\.\d{2}"
    rules = [
        Rule(RowKind.CHARGE, rf"^\s+(?P<d>.+?)\s{{2,}}(?P<a>{NUM})\s+Y\s*$",
             extract=lambda m, ln, c: {"amount": parse_money(m.group("a")),
                                       "desc": m.group("d")}, name="charge"),
        Rule(RowKind.INVOICE_SUBTOTAL, rf"^\s*SUBTOTAL\s+(?P<a>{NUM})\s*$",
             extract=lambda m, ln, c: {"amount": parse_money(m.group("a"))},
             name="subtotal"),
        Rule(RowKind.TAX, rf"^\s*TAX\s+(?P<a>{NUM})\s*$",
             extract=lambda m, ln, c: {"amount": parse_money(m.group("a"))}, name="tax"),
        Rule(RowKind.GRAND_TOTAL, rf"^\s*TOTAL\s+(?P<a>{NUM})\s*$",
             extract=lambda m, ln, c: {"amount": parse_money(m.group("a"))}, name="total"),
    ]
    ladder = [
        LevelCheck("subtotal", (RowKind.CHARGE,), RowKind.INVOICE_SUBTOTAL),
        LevelCheck("grand_total", (RowKind.INVOICE_SUBTOTAL, RowKind.TAX),
                   RowKind.GRAND_TOTAL),
    ]
    lines = [
        "   WIDGET A                 10.00   Y",
        "   WIDGET B                 15.50   Y",
        "SUBTOTAL   25.50",
        "TAX   2.04",
        "TOTAL   27.54",
    ]
    doc = Document(path=Path("synthetic.pdf"),
                   pages=[Page(number=1, width=612, height=792, lines=lines)])
    rows = Classifier(rules).classify(doc)
    rec = reconcile(rows, ladder)
    check("classifies every line (tripwire clean)", not rec.unclassified,
          f"unclassified: {[r.raw for r in rec.unclassified]}")
    check("ladder reconciles at depth 2", rec.passed and rec.depth == 2,
          rec.summary())

    # And the guard that matters most: a ladder that checked nothing must not pass.
    empty = reconcile([], ladder)
    check("an invoice where nothing was checked does NOT pass", not empty.passed,
          "a vacuous reconciliation reported as verified")

print()
if FAILURES:
    print(f"{len(FAILURES)} problem(s):\n")
    for item in FAILURES:
        print(f"  - {item}")
    sys.exit(1)

print("INSTALL OK — all checks passed.")
for note in NOTES:
    print(f"\nnote: {note}")
print("\nNext: run  /invoice-extract <folder-of-pdfs>")
