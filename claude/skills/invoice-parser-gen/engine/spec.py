"""What a vendor spec is, and what parsing one produces.

A spec is data plus a few small callbacks: the rules that classify lines, the
zones that change their meaning, the ladder of sums to verify, and the header
fields to pull. Everything generic — loading, classifying, reconciling, writing
— lives in the engine, so a new vendor is a spec and nothing else.

The split matters for the failure mode this project is trying to avoid. When a
vendor breaks, the fix belongs in its spec; when the *engine* needs changing to
fit a vendor, that is a signal the engine is missing a general capability, and
patching around it in the spec would hide that.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from .classify import ClassifiedRow, Classifier, RowKind, Rule, ZoneMarker
from .reconcile import LevelCheck, Reconciliation, reconcile
from .text import Document, load

__all__ = ["InvoiceSpec", "ExtractedInvoice"]


@dataclass
class ExtractedInvoice:
    """The result of parsing one PDF."""

    source: Path
    spec_name: str
    fields: dict[str, str] = field(default_factory=dict)
    line_items: list[dict] = field(default_factory=list)
    reconciliation: Reconciliation = field(default_factory=Reconciliation)
    rows: list[ClassifiedRow] = field(default_factory=list)
    page_count: int = 0
    ocr_applied: bool = False
    sha256: str = ""

    @property
    def identity(self) -> str:
        return self.fields.get("invoice_number", "")

    @property
    def verified(self) -> bool:
        """Fully verified: charges were found, they reconcile, every line understood.

        An extraction with no line items is never verified, however clean its
        arithmetic looks. "This invoice has no charges" and "this parser found no
        charges" are indistinguishable from the inside, so the honest answer is to
        flag it and let a human look.
        """
        if not self.line_items:
            return False
        return self.reconciliation.passed

    @property
    def grand_total(self) -> Decimal | None:
        return self.reconciliation.value_of("grand_total")

    @property
    def computed_total(self) -> Decimal:
        return sum(
            (r.amount for r in self.rows if r.kind is RowKind.CHARGE and r.amount),
            Decimal("0.00"),
        )

    @property
    def status(self) -> str:
        if self.verified:
            return "verified"
        if not self.line_items:
            return "no line items found"
        if self.reconciliation.depth == 0:
            return "nothing could be verified"
        return self.reconciliation.status_label

    def failure_reasons(self) -> list[str]:
        reasons: list[str] = []
        if not self.line_items:
            reasons.append(
                "no line items matched — either this document has no charges or "
                "the spec does not fit it"
            )
        if self.line_items and self.reconciliation.depth == 0:
            # Deliberately does not assert a cause. Depth 0 can mean no printed
            # sum exists, or that a spec refused the document and marked every
            # rung not-applicable on purpose — asserting the first would
            # contradict the spec's own, more accurate explanation below.
            reasons.append(
                f"nothing was verified: {len(self.line_items)} line items were "
                "extracted but no rung compared them against anything"
            )
        reasons += [str(f) for f in self.reconciliation.failures]
        # Excerpt generously. A spec can deliberately emit an explanatory line
        # here to refuse a document, and clipping it at 70 characters threw away
        # the explanation while keeping the complaint.
        for row in self.reconciliation.unclassified:
            reasons.append(f"unclassified {row.location}: {row.raw.strip()[:400]}")
        return reasons


@dataclass
class InvoiceSpec:
    name: str
    rules: Sequence[Rule]
    ladder: Sequence[LevelCheck]
    header_fields: dict[str, str] = field(default_factory=dict)
    zone_markers: Sequence[ZoneMarker] = ()
    postprocess: Callable[[list[ClassifiedRow]], None] | None = None
    line_item_fields: Sequence[str] = ()
    # Which header fields identify an invoice for deduplication. Invoice number
    # alone is the norm, but vendors that reuse numbers across accounts need a
    # composite key, and discovering that after the fact means a corrupted sheet.
    identity_fields: Sequence[str] = ("invoice_number",)
    description: str = ""

    def classifier(self) -> Classifier:
        return Classifier(self.rules, self.zone_markers)

    def extract_header(self, doc: Document) -> dict[str, str]:
        """Pull header fields from the document.

        Searched over the whole document rather than page one because vendors
        repeat identifying fields in continuation-page headers, and a
        first-match-wins search over everything is more robust than assuming
        which page carries them.
        """
        out: dict[str, str] = {}
        text = doc.text
        for name, pattern in self.header_fields.items():
            match = re.search(pattern, text, re.MULTILINE)
            out[name] = match.group(1).strip() if match else ""
        return out

    def identity_key(self, fields: dict[str, str]) -> str:
        return "|".join(fields.get(f, "") for f in self.identity_fields)

    def parse(self, path: str | Path, *, doc: Document | None = None) -> ExtractedInvoice:
        doc = doc if doc is not None else load(path)
        rows = self.classifier().classify(doc)
        if self.postprocess is not None:
            self.postprocess(rows)

        line_items = [
            {
                "amount": row.amount,
                **{k: row.fields.get(k, "") for k in self.line_item_fields},
                "page": row.page,
            }
            for row in rows
            if row.kind is RowKind.CHARGE
        ]

        return ExtractedInvoice(
            source=Path(doc.path),
            spec_name=self.name,
            fields=self.extract_header(doc),
            line_items=line_items,
            reconciliation=reconcile(rows, self.ladder),
            rows=rows,
            page_count=doc.page_count,
            ocr_applied=doc.ocr_applied,
            sha256=doc.sha256,
        )
