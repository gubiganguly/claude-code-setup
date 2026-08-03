"""Load a PDF into the two text representations the engine needs.

Both are required, for different reasons.

`pdftotext -layout` preserves column alignment, which is what makes row-shape
regexes viable at all: the amount stays in the amount column and a padded gap
survives as whitespace. PyMuPDF's reading-order extraction flattens multi-column
layouts and would pair labels with the wrong values.

PyMuPDF supplies word coordinates, which `pdftotext` throws away. The
strongest general discriminator between a real charge row and a decoy number
is whether the amount's x-position falls inside the detail table's amount
column, and that needs geometry.

So: lines from pdftotext, geometry from PyMuPDF, keyed to the same page.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

__all__ = [
    "Word",
    "Page",
    "Document",
    "load",
    "TEXT_DENSITY_THRESHOLD",
    "PdfToolMissing",
]

# Below this many non-whitespace characters on a page, treat the page as an
# image rather than text. 200 rather than a lower bound because of the failure
# mode it exists to catch: a scanned invoice whose only real text is a header
# stamp or a footer disclaimer lands around 80-120 chars/page, passes a lower
# gate, and then parses to a confidently wrong near-empty result. LabCorp sits
# at 83.
TEXT_DENSITY_THRESHOLD = 200


class PdfToolMissing(RuntimeError):
    pass


@dataclass(frozen=True)
class Word:
    """One word with its bounding box, in PDF points, origin top-left."""

    text: str
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def x_mid(self) -> float:
        return (self.x0 + self.x1) / 2


@dataclass
class Page:
    number: int  # 1-based, matching what the invoice prints
    width: float
    height: float
    lines: list[str] = field(default_factory=list)
    # Populated on first access. Only geometry-based discriminators need words,
    # and extracting them for a long document costs far more than the line pass.
    _words: list[Word] | None = None
    _word_loader: object = None

    @property
    def words(self) -> list[Word]:
        if self._words is None:
            loader = self._word_loader
            self._words = list(loader(self.number)) if callable(loader) else []
        return self._words

    @cached_property
    def text(self) -> str:
        return "\n".join(self.lines)

    @cached_property
    def char_count(self) -> int:
        return len("".join(self.lines).replace(" ", "").replace("\t", ""))

    @property
    def is_image_only(self) -> bool:
        return self.char_count < TEXT_DENSITY_THRESHOLD

    def words_in_x_band(self, x_min: float, x_max: float) -> list[Word]:
        return [w for w in self.words if x_min <= w.x_mid < x_max]


@dataclass
class Document:
    path: Path
    pages: list[Page]
    producer: str | None = None
    creator: str | None = None
    sha256: str = ""
    ocr_applied: bool = False

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @cached_property
    def text(self) -> str:
        return "\n".join(p.text for p in self.pages)

    @cached_property
    def lines(self) -> list[str]:
        return [ln for p in self.pages for ln in p.lines]

    @cached_property
    def chars_per_page(self) -> float:
        if not self.pages:
            return 0.0
        return sum(p.char_count for p in self.pages) / len(self.pages)

    @property
    def image_only_pages(self) -> list[int]:
        return [p.number for p in self.pages if p.is_image_only]

    @property
    def needs_ocr(self) -> bool:
        """True if the document as a whole has no usable text layer.

        Judged on the document mean, not per page. An earlier version refused a
        document if *any* page fell below the threshold, which was wrong in the
        common case and badly so: one vendor ends every invoice with a page
        reading `**** Intentionally left blank****` (38 characters), which refused
        all 51 of its files, and another has 15 files whose last page carries only
        a grand-total line. Sparse pages are normal.

        The separation at document level is wide enough to be unambiguous —
        readable invoices in the reference corpus run 500-3,300 chars/page and
        scans run 0-22 — so the mean is both safer and more accurate here.

        The residual risk this gives up is a mostly-text document with one image
        page whose line items are lost. `sparse_pages` reports those so a human
        can look, which is a better trade than refusing every document with a
        blank page to guard against a rarer one.
        """
        return self.chars_per_page < TEXT_DENSITY_THRESHOLD

    @property
    def sparse_pages(self) -> list[int]:
        """Pages with almost no text in an otherwise readable document.

        Usually benign (a blank page, a footer-only page, a remittance stub) but
        occasionally an image page whose rows are being lost, so it is surfaced
        rather than acted on automatically.
        """
        if self.needs_ocr:
            return []
        return [p.number for p in self.pages if p.is_image_only]

    def numbered_lines(self) -> list[tuple[int, int, str]]:
        """(page_number, line_index, line) for every line, for error reporting.

        A flag that says "page 4, line 17" is actionable; one that says
        "somewhere in this invoice" is not.
        """
        return [
            (p.number, i, ln) for p in self.pages for i, ln in enumerate(p.lines)
        ]


def _require(tool: str) -> str:
    found = shutil.which(tool)
    if not found:
        raise PdfToolMissing(
            f"{tool!r} not found on PATH. Install poppler (brew install poppler)."
        )
    return found


def _pdfinfo(path: Path) -> dict[str, str]:
    out = subprocess.run(
        [_require("pdfinfo"), str(path)], capture_output=True, text=True
    ).stdout
    info: dict[str, str] = {}
    for line in out.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            info[key.strip()] = value.strip()
    return info


def _layout_lines_per_page(path: Path, page_count: int) -> list[list[str]]:
    """Extract layout-preserved lines for every page.

    One pdftotext pass over the whole document, split on the form feeds it emits
    between pages. Calling it once per page is cleaner to reason about but costs a
    subprocess spawn per page, and real invoices run long: one file in the
    reference corpus is 417 pages, which turned a 2-second parse into minutes.

    The split is verified against the page count from pdfinfo. If they disagree,
    fall back to the per-page calls rather than silently mis-aligning every
    page's content.
    """
    exe = _require("pdftotext")
    proc = subprocess.run(
        [exe, "-layout", str(path), "-"], capture_output=True, text=True
    )
    chunks = proc.stdout.split("\f")
    # pdftotext emits a trailing form feed, leaving a final empty chunk.
    if chunks and not chunks[-1].strip():
        chunks.pop()

    if len(chunks) == page_count:
        return [chunk.split("\n") for chunk in chunks]

    pages: list[list[str]] = []
    for n in range(1, page_count + 1):
        one = subprocess.run(
            [exe, "-layout", "-f", str(n), "-l", str(n), str(path), "-"],
            capture_output=True,
            text=True,
        )
        pages.append(one.stdout.replace("\f", "").split("\n"))
    return pages


def _import_fitz():
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:  # pragma: no cover
        raise PdfToolMissing("PyMuPDF required: pip install pymupdf") from exc
    return fitz


def _page_dimensions(path: Path) -> list[tuple[float, float]]:
    fitz = _import_fitz()
    with fitz.open(str(path)) as doc:
        return [(p.rect.width, p.rect.height) for p in doc]


def _word_loader(path: Path):
    """Return a callable that extracts words for one 1-based page number."""

    def load_words(page_number: int) -> list[Word]:
        fitz = _import_fitz()
        with fitz.open(str(path)) as doc:
            page = doc[page_number - 1]
            return [
                Word(text=w[4], x0=w[0], y0=w[1], x1=w[2], y1=w[3])
                for w in page.get_text("words")
            ]

    return load_words


def load(path: str | Path) -> Document:
    """Load a PDF. Does not OCR; check `needs_ocr` and route explicitly."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)

    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    info = _pdfinfo(path)
    dimensions = _page_dimensions(path)
    line_pages = _layout_lines_per_page(path, len(dimensions))
    loader = _word_loader(path)

    pages = [
        Page(number=i + 1, width=w, height=h, lines=lines, _word_loader=loader)
        for i, ((w, h), lines) in enumerate(zip(dimensions, line_pages))
    ]

    return Document(
        path=path,
        pages=pages,
        producer=info.get("Producer") or None,
        creator=info.get("Creator") or None,
        sha256=sha,
    )
