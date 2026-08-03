"""Per-folder extraction state, so a re-run only does the new work.

State lives in `.invoice-parser/` beside the invoices:

    extractions.jsonl   one record per invoice, append-only
    bindings.json       which spec is bound to this folder

The spreadsheet is the deliverable, not the database. Identities are read back
from *both* the store and the sheet, so deleting either one degrades gracefully
rather than causing silent duplicates: with the store gone the sheet still says
what was reported, and with the sheet gone the store can rebuild it.

Dedup keys on the invoice's own identity fields rather than the filename,
because the same invoice routinely arrives twice under different names. It also
distinguishes "seen this exact document" from "seen this invoice number with
different content" — the second is a re-issued invoice and must be surfaced, not
quietly skipped.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path

from .spec import ExtractedInvoice, InvoiceSpec

__all__ = ["ExtractionStore", "Verdict", "Triage"]

STATE_DIR = ".invoice-parser"


class Verdict(str, Enum):
    NEW = "new"
    DUPLICATE = "duplicate"  # same identity, same bytes: nothing to do
    CHANGED = "changed"  # same identity, different content: needs a human


@dataclass
class Triage:
    verdict: Verdict
    identity: str
    detail: str = ""
    previous: dict | None = None


def _json_default(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"not JSON serialisable: {type(value)!r}")


class ExtractionStore:
    def __init__(self, folder: str | Path) -> None:
        self.folder = Path(folder)
        self.dir = self.folder / STATE_DIR
        self.records_path = self.dir / "extractions.jsonl"
        self.bindings_path = self.dir / "bindings.json"

    # -- lifecycle ---------------------------------------------------------

    def ensure(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)

    def records(self) -> list[dict]:
        if not self.records_path.is_file():
            return []
        out = []
        for line in self.records_path.read_text().splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
        return out

    def by_identity(self) -> dict[str, dict]:
        # Later records win, so a corrected re-extraction supersedes the old one.
        return {r["identity"]: r for r in self.records() if r.get("identity")}

    def append(self, records: list[dict]) -> None:
        if not records:
            return
        self.ensure()
        with self.records_path.open("a") as handle:
            for record in records:
                handle.write(json.dumps(record, default=_json_default) + "\n")

    # -- bindings ----------------------------------------------------------

    def bindings(self) -> dict:
        if not self.bindings_path.is_file():
            return {}
        return json.loads(self.bindings_path.read_text())

    def bind(self, spec_name: str, signature: str, notes: str = "") -> None:
        self.ensure()
        data = self.bindings()
        data.setdefault("specs", {})[signature] = {
            "spec": spec_name,
            "bound_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "notes": notes,
        }
        self.bindings_path.write_text(json.dumps(data, indent=2) + "\n")

    def spec_for_signature(self, signature: str) -> str | None:
        entry = self.bindings().get("specs", {}).get(signature)
        return entry["spec"] if entry else None

    # -- dedup -------------------------------------------------------------

    def triage(
        self, invoice: ExtractedInvoice, spec: InvoiceSpec, known: dict[str, dict]
    ) -> Triage:
        identity = spec.identity_key(invoice.fields)
        if not identity.strip("|"):
            return Triage(
                Verdict.CHANGED,
                identity,
                "no invoice identity could be extracted — cannot safely dedupe",
            )

        previous = known.get(identity)
        if previous is None:
            return Triage(Verdict.NEW, identity)

        if previous.get("sha256") == invoice.sha256:
            return Triage(Verdict.DUPLICATE, identity, "same document already recorded")

        old_total = previous.get("printed_total")
        new_total = str(invoice.grand_total) if invoice.grand_total is not None else ""
        if old_total != new_total:
            return Triage(
                Verdict.CHANGED,
                identity,
                f"already recorded with total {old_total}, this copy says {new_total}",
                previous,
            )
        return Triage(
            Verdict.CHANGED,
            identity,
            "same invoice number and total but a different document",
            previous,
        )

    # -- serialisation -----------------------------------------------------

    @staticmethod
    def record_from(invoice: ExtractedInvoice, spec: InvoiceSpec) -> dict:
        rec = invoice.reconciliation
        return {
            "identity": spec.identity_key(invoice.fields),
            "spec": invoice.spec_name,
            "source": invoice.source.name,
            "sha256": invoice.sha256,
            "extracted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "page_count": invoice.page_count,
            "ocr_applied": invoice.ocr_applied,
            "verified": invoice.verified,
            "status": invoice.status,
            "checks_passed": sum(1 for r in rec.results if r.ok),
            "checks_total": len(rec.results),
            "depth": rec.depth,
            "printed_total": str(invoice.grand_total) if invoice.grand_total else "",
            "computed_total": str(invoice.computed_total),
            "fields": dict(invoice.fields),
            "line_items": [
                {k: (str(v) if isinstance(v, Decimal) else v) for k, v in item.items()}
                for item in invoice.line_items
            ],
            "failures": invoice.failure_reasons(),
        }
