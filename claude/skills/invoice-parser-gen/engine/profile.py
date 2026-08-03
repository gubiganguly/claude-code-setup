"""Fingerprint a PDF's layout, so a folder can be checked for format drift.

The signature answers one question: is this the same kind of document as the one
the bound spec was approved against? It has to be stable across invoices of the
same template (different amounts, different page counts, different employees)
and change when the template itself changes.

Three components, cheapest first:

  generator   Producer and Creator strings. A vendor switching from SAP to a new
              billing system changes these, and it is nearly free to read.
  columns     The set of column NAMES in the strongest header row. An earlier
              version hashed their x-positions instead and was unusably brittle:
              one vendor's report generator auto-sizes columns per file, which
              reported 16 distinct layouts for a single template, and another
              shifts MATERIAL between columns 13 and 16 across its own variants.
              What actually changes when a template changes is which columns
              exist, so that is what the signature keys on.
  anchors     Whether recognisable invoice vocabulary is present at all.

`anchors` exists because of a specific failure: a scanned invoice carrying only
AP-team annotations (a GL code, "Paid ACH 12/4/25") has a real text layer with a
few hundred characters and no invoice content whatsoever. A character-count gate
passes it, and the parser then reports zero line items and no error. Requiring an
anchor token distinguishes "text layer" from "usable text layer".
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from .text import Document

__all__ = ["LayoutProfile", "profile", "cluster", "ANCHOR_TOKENS"]

# Vocabulary that appears on essentially every invoice but never in an
# annotation-only text layer.
ANCHOR_TOKENS = (
    "INVOICE",
    "TOTAL",
    "AMOUNT",
    "SUBTOTAL",
    "BALANCE",
    "QUANTITY",
    "DESCRIPTION",
    "REMIT",
    "BILL TO",
    "DUE",
)

# Words that mark a row as a table header rather than an address or a total.
_HEADER_HINTS = (
    "DESCRIPTION",
    "QTY",
    "QUANTITY",
    "AMOUNT",
    "PRICE",
    "RATE",
    "TOTAL",
    "MATERIAL",
    "ITEM",
    "DATE",
    "FEES",
    "CODE",
    "REFERENCE",
    "UNIT",
    "TAX",
)

# Signatures of a text layer that is only AP annotation.
_ANNOTATION_SIGNS = (
    re.compile(r"\b\d{5}\s*-\s*\d{4}\s*-\s*\d{6}"),  # GL coding, e.g. 50130-1500-125001
    re.compile(r"\bPaid (ACH|by|via)\b", re.I),
    re.compile(r"\bCM \d+ applied to \d+", re.I),
    re.compile(r"\bcredit(s)? (applied|taken)\b", re.I),
    re.compile(r"\bper [A-Z][a-z]+ [A-Z][a-z]+\b"),  # "Per Roberta Phillips, ..."
)


@dataclass
class LayoutProfile:
    signature: str
    generator: str
    page_count: int
    chars_per_page: float
    needs_ocr: bool
    has_anchors: bool
    annotation_only: bool
    column_row: str = ""
    column_positions: tuple[int, ...] = field(default_factory=tuple)
    sparse_pages: tuple[int, ...] = field(default_factory=tuple)

    @property
    def usable_text(self) -> bool:
        """A text layer worth parsing: present, anchored, and not just AP notes."""
        return not self.needs_ocr and self.has_anchors and not self.annotation_only

    def describe(self) -> str:
        if self.annotation_only:
            state = "ANNOTATION-ONLY text layer (AP notes over a scan) — needs OCR"
        elif self.needs_ocr:
            state = "no usable text layer — needs OCR"
        elif not self.has_anchors:
            state = "text present but no invoice vocabulary — suspect"
        else:
            state = "text layer usable"
        return (
            f"{self.page_count}p  {self.chars_per_page:.0f} chars/page  "
            f"{state}\n  generator: {self.generator}\n  signature: {self.signature}"
        )


def _best_header_row(doc: Document) -> tuple[str, tuple[int, ...]]:
    """The line that most looks like a column header, with its token offsets.

    Scored by how many header words it contains rather than by position. Taking
    the topmost row instead would almost always return the logo or the address
    block, which carry no table geometry at all.
    """
    best_score = 0
    best_line = ""
    for line in doc.lines[:400]:
        stripped = line.strip()
        if not stripped or len(stripped) < 12:
            continue
        upper = stripped.upper()
        score = sum(1 for hint in _HEADER_HINTS if hint in upper)
        if score > best_score:
            best_score, best_line = score, line
    if best_score < 2:
        return "", ()
    offsets = tuple(m.start() for m in re.finditer(r"\S+", best_line))
    # Round to 5-character buckets so incidental shifts do not change the
    # signature while a genuinely moved column does.
    return best_line, tuple(sorted({(o // 5) * 5 for o in offsets}))


def profile(doc: Document) -> LayoutProfile:
    text = doc.text
    upper = text.upper()
    has_anchors = sum(1 for token in ANCHOR_TOKENS if token in upper) >= 2

    stripped = text.strip()
    annotation_only = bool(
        stripped
        and not has_anchors
        and any(sign.search(text) for sign in _ANNOTATION_SIGNS)
    )
    # Short, unanchored text over a multi-page document is annotation even when
    # it matches none of the known note shapes.
    if stripped and not has_anchors and doc.chars_per_page < 300:
        annotation_only = True

    column_row, positions = _best_header_row(doc)
    generator = f"{doc.producer or '?'} / {doc.creator or '?'}"
    # Keyed on the header's TOKEN SET rather than its character offsets. Offsets
    # are far too brittle: one vendor's report generator auto-sizes columns per
    # file, which produced 16 "different layouts" for a single template, and
    # another shifts MATERIAL between columns 13 and 16 across its own variants.
    # The set of column names is what actually changes when a template changes.
    tokens = sorted({t.upper() for t in re.findall(r"[A-Za-z#/]{2,}", column_row)})
    payload = "|".join([generator, ",".join(tokens)])
    signature = hashlib.sha256(payload.encode()).hexdigest()[:16]

    return LayoutProfile(
        signature=signature,
        generator=generator,
        page_count=doc.page_count,
        chars_per_page=doc.chars_per_page,
        needs_ocr=doc.needs_ocr,
        has_anchors=has_anchors,
        annotation_only=annotation_only,
        column_row=column_row.rstrip(),
        column_positions=positions,
        sparse_pages=tuple(doc.sparse_pages),
    )


def cluster(profiles: dict[str, LayoutProfile]) -> dict[str, list[str]]:
    """Group filenames by layout signature, largest cluster first."""
    groups: dict[str, list[str]] = {}
    for name, prof in profiles.items():
        groups.setdefault(prof.signature, []).append(name)
    return dict(sorted(groups.items(), key=lambda kv: -len(kv[1])))
