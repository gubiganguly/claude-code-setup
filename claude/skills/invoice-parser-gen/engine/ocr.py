"""OCR a scanned invoice into something the normal pipeline can read.

The output is a **searchable PDF sidecar**, not raw text. That matters: every spec
in this engine depends on `pdftotext -layout` column alignment and on word
coordinates, and tesseract's plain text output has neither. Round-tripping through
a PDF means an OCR'd invoice takes exactly the same path as a native one, so a
spec needs no OCR-specific branch.

Two details are load-bearing:

*Source dimensions.* Each OCR'd page is rendered into a page of the **original**
page's size. Skip that and every page ends up sized to the raster — a 612x791
page becomes 2550x3295 at 300dpi — and every x-coordinate a spec derived from a
native invoice is wrong by the scale factor.

*psm 3.* The default page-segmentation mode. `--psm 6` drops header rows entirely
and `--psm 4` corrupts names; both verified against the reference corpus.

OCR gets **no tolerance relaxation.** Tesseract misreads digits: one verified case
returned `14.75` where the truth was `11.75`, a silent $3.00 error that only the
printed subtotal caught. Holding the ladder at zero tolerance means such an
invoice is flagged for a human instead of quietly emitted. That is the entire
reason for running the ladder on the OCR path.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
from pathlib import Path

from .text import Document, PdfToolMissing, load

__all__ = [
    "OCR_DPI",
    "OcrError",
    "ocr_pdf",
    "load_ocr",
    "load_or_ocr",
    "tesseract_available",
]

OCR_DPI = 300
_CACHE_DIRNAME = "ocr-cache"


class OcrError(RuntimeError):
    pass


def tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


def _cache_path(src: Path, dpi: int, cache_dir: Path) -> Path:
    digest = hashlib.sha256(src.read_bytes()).hexdigest()[:32]
    return cache_dir / f"{digest}-{dpi}.pdf"


def ocr_pdf(
    src: str | Path,
    *,
    dpi: int = OCR_DPI,
    cache_dir: str | Path | None = None,
    max_pages: int | None = None,
) -> Path:
    """Produce a searchable-PDF copy of `src`, cached by content hash.

    Cached on the file's bytes rather than its path, so the same invoice arriving
    under a second filename costs nothing the second time. OCR is by a wide margin
    the most expensive step in the pipeline.
    """
    src = Path(src)
    if not tesseract_available():
        raise PdfToolMissing("tesseract not found on PATH (brew install tesseract)")

    try:
        import fitz
    except ImportError as exc:  # pragma: no cover
        raise PdfToolMissing("PyMuPDF required: pip install pymupdf") from exc

    cache = (
        Path(cache_dir)
        if cache_dir
        else src.parent / ".invoice-parser" / _CACHE_DIRNAME
    )
    cache.mkdir(parents=True, exist_ok=True)
    destination = _cache_path(src, dpi, cache)
    if destination.is_file():
        return destination

    with fitz.open(str(src)) as source_doc:
        page_count = source_doc.page_count
        if max_pages is not None and page_count > max_pages:
            raise OcrError(
                f"{page_count} pages, above the OCR page limit of {max_pages}. "
                f"At {dpi}dpi this would take roughly "
                f"{max(1, page_count * 3 // 60)} minutes; raise --ocr-max-pages "
                "to proceed."
            )

        output = fitz.open()
        with tempfile.TemporaryDirectory() as workspace:
            work = Path(workspace)
            for index in range(page_count):
                page = source_doc[index]
                raster = page.get_pixmap(dpi=dpi)
                image = work / f"page-{index:04d}.png"
                raster.save(str(image))
                # Release the pixmap before spawning tesseract. At 300dpi these
                # run to tens of megabytes, and holding one alongside the
                # tesseract process is what pushes a long invoice into swap.
                raster = None

                stem = work / f"ocr-{index:04d}"
                result = subprocess.run(
                    ["tesseract", str(image), str(stem), "--psm", "3", "pdf"],
                    capture_output=True,
                    text=True,
                )
                produced = stem.with_suffix(".pdf")
                if result.returncode != 0 or not produced.is_file():
                    raise OcrError(
                        f"tesseract failed on page {index + 1}: "
                        f"{result.stderr.strip()[:200]}"
                    )

                with fitz.open(str(produced)) as ocr_page:
                    # Render into a page of the ORIGINAL size so coordinates
                    # derived from native invoices stay valid.
                    target = output.new_page(
                        width=page.rect.width, height=page.rect.height
                    )
                    target.show_pdf_page(target.rect, ocr_page, 0)

        output.save(str(destination), deflate=True)
        output.close()

    return destination


def load_ocr(
    path: str | Path,
    *,
    dpi: int = OCR_DPI,
    cache_dir: str | Path | None = None,
    max_pages: int | None = None,
) -> Document:
    """OCR a PDF and load the result, flagged so reports can say so."""
    sidecar = ocr_pdf(path, dpi=dpi, cache_dir=cache_dir, max_pages=max_pages)
    doc = load(sidecar)
    # Keep the original path. The sidecar is an implementation detail, and every
    # report, exception row and dedup key should name the file the user has.
    doc.path = Path(path)
    doc.ocr_applied = True
    return doc


def load_or_ocr(
    path: str | Path,
    *,
    allow_ocr: bool = False,
    dpi: int = OCR_DPI,
    max_pages: int | None = None,
) -> tuple[Document, str | None]:
    """Load a PDF, escalating to OCR when it has no usable text layer.

    Returns the document plus, when it could not be made usable, the reason.
    Escalating only on demand keeps the common case fast, and returning the reason
    rather than raising lets a bulk run record the problem per file and carry on.
    """
    from .profile import profile  # local: profile imports text, not ocr

    doc = load(path)
    prof = profile(doc)
    if prof.usable_text:
        return doc, None

    reason = (
        "annotation-only text layer (AP notes over a scan)"
        if prof.annotation_only
        else "no usable text layer"
        if prof.needs_ocr
        else "no invoice vocabulary in the text layer"
    )
    if not allow_ocr:
        return doc, f"{reason} — re-run with --ocr to attempt OCR"

    try:
        ocr_doc = load_ocr(path, dpi=dpi, max_pages=max_pages)
    except (OcrError, PdfToolMissing) as exc:
        return doc, f"{reason}; OCR failed: {exc}"

    if not profile(ocr_doc).usable_text:
        return ocr_doc, f"{reason}; OCR produced no usable text either"
    return ocr_doc, None
