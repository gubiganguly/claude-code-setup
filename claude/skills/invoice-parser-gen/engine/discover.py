"""Work out an invoice's grammar from the documents themselves.

This does not write a spec. It produces the evidence a spec is written from, and
it answers the one question that otherwise costs the most iterations: **which
discriminator, paired with which printed total, actually reconciles.**

That search is the core of the module. Given a document it enumerates candidate
rules for "this line is a charge" (a trailing flag character, a specific count of
money tokens, presence or absence of a currency symbol, a distinctive rate
format), enumerates candidate grand totals with a semantic ranking, optionally
cuts the document at a suspected restatement marker, and reports every
combination whose arithmetic closes exactly. When exactly one combination closes
across a whole folder, the spec practically writes itself. When several do, or
none, that is the signal to go and read the PDF.

Two deliberate choices:

*Candidate totals are ranked by meaning, not by size.* The largest total-like
number on an invoice is routinely the wrong one — `Total Account Balance` is
previous balance plus current charges, and `TOTAL AMOUNT DUE` includes aging. A
blocklist of those labels matters more than any scoring heuristic.

*Every distinct line shape is inventoried.* The tripwire requires that a spec
account for every line in the corpus, so the practical question when writing one
is "what shapes exist and how many of each", not "what does a charge look like".
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from .money import money_tokens
from .text import Document

__all__ = [
    "LineShape",
    "TotalCandidate",
    "DiscriminatorResult",
    "DiscoveryReport",
    "discover",
    "shape_of",
]

# ---------------------------------------------------------------------------
# Total candidates
# ---------------------------------------------------------------------------

# Ranked by what the label MEANS. Priority 1 is "the charges on this invoice
# only"; priority 2 may include prior balances or aging and is almost never the
# figure line items should reconcile against.
_TOTAL_LABELS: tuple[tuple[int, str], ...] = (
    (1, r"current\s+invoice\s+total"),
    (1, r"invoice\s+total"),
    (1, r"current\s+period\s+total"),
    (1, r"current\s+amount\s+due"),
    (1, r"current\s+invoice\s+subtotal"),
    (1, r"grand\s+total"),
    (1, r"total\s+due"),
    (1, r"total\s+usd"),
    (2, r"period\s+subtotal"),
    (2, r"sub\s*total"),
    # Not anchored to line start: `-layout` routinely leaves the label sharing a
    # line with the address block, so one vendor prints `PLEASE NOTE OUR
    # REMITTANCE ADDRESS:   Total   $10,238.36`. `\btotal\b` cannot match inside
    # "Subtotal" (no word boundary there), and the wrong-answer labels that do
    # contain the word are all on the blocklist.
    (2, r"\btotal\b"),
    (3, r"amount\s+due"),
    (3, r"balance\s+due"),
    (3, r"amount\s+enclosed"),
)

# Labels that look like a grand total and are not one. Each of these is a
# verified wrong answer on a real vendor.
_TOTAL_BLOCKLIST = (
    r"account\s+balance",
    r"previous\s+balance",
    r"prior\s+period",
    r"past\s+due",
    r"aging",
    r"amount\s+past",
    r"sales\s+tax\s+calculated",
    r"summary\s+of\s+taxes",
    r"non-?taxable",
    r"payments?\s*/?\s*credits",
    r"total\s+samples",
)

_BLOCK = re.compile("|".join(_TOTAL_BLOCKLIST), re.I)


@dataclass
class TotalCandidate:
    label: str
    value: Decimal
    priority: int
    page: int
    raw: str

    def __str__(self) -> str:
        return f"p{self.page} [{self.priority}] {self.label!r} = {self.value}"


def total_candidates(doc: Document) -> list[TotalCandidate]:
    """Every plausible grand total, best first.

    Searched over the whole document rather than the last page: vendors put the
    figure in a header block, a footer, and a remittance stub, and which one is
    authoritative differs by vendor.
    """
    found: list[TotalCandidate] = []
    for page in doc.pages:
        for line in page.lines:
            if not line.strip() or _BLOCK.search(line):
                continue
            hits = money_tokens(line)
            if not hits:
                continue
            for priority, pattern in _TOTAL_LABELS:
                match = re.search(pattern, line, re.I)
                if not match:
                    continue
                # The label must sit left of the amount, or the "label" is really
                # part of a neighbouring column that -layout flattened onto this
                # line.
                if match.start() > hits[-1].start:
                    continue
                found.append(
                    TotalCandidate(
                        label=match.group(0).strip(),
                        value=hits[-1].value,
                        priority=priority,
                        page=page.number,
                        raw=line.strip()[:110],
                    )
                )
                break
    # Deduplicate on (label, value); keep the best-ranked instance.
    best: dict[tuple[str, Decimal], TotalCandidate] = {}
    for candidate in found:
        key = (candidate.label.lower(), candidate.value)
        if key not in best or candidate.priority < best[key].priority:
            best[key] = candidate
    return sorted(best.values(), key=lambda c: (c.priority, -c.value))


# ---------------------------------------------------------------------------
# Line shapes
# ---------------------------------------------------------------------------

_WORD = re.compile(r"[A-Za-z][A-Za-z'./&-]*")
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def shape_of(line: str) -> str:
    """Collapse a line to its structural form, so like rows group together.

    Words become `W`, numbers `N`, money `$`, and runs of two or more spaces
    become a column break. Two rows differing only in their values collapse to
    one shape; a row with an extra column does not.
    """
    text = line.rstrip()
    if not text.strip():
        return ""
    for hit in reversed(money_tokens(text)):
        text = text[: hit.start] + "$" + text[hit.end :]
    text = _NUMBER.sub("N", text)
    text = _WORD.sub("W", text)
    text = re.sub(r"\s{2,}", " | ", text.strip())
    text = re.sub(r"(?:W[ ]?)+", "W ", text)
    text = re.sub(r"(?:N[ ]?)+", "N ", text)
    return re.sub(r"\s+", " ", text).strip()[:90]


@dataclass
class LineShape:
    shape: str
    count: int
    examples: list[str] = field(default_factory=list)
    money_count: int = 0

    def __str__(self) -> str:
        return f"{self.count:6d}  {self.shape[:64]:<64} eg: {self.examples[0][:60] if self.examples else ''}"


def line_shapes(docs: list[Document], limit: int = 40) -> list[LineShape]:
    counter: Counter[str] = Counter()
    examples: dict[str, list[str]] = {}
    money: dict[str, int] = {}
    for doc in docs:
        for line in doc.lines:
            if not line.strip():
                continue
            key = shape_of(line)
            counter[key] += 1
            if len(examples.setdefault(key, [])) < 3:
                examples[key].append(line.strip())
            money.setdefault(key, len(money_tokens(line)))
    return [
        LineShape(shape=k, count=v, examples=examples[k], money_count=money[k])
        for k, v in counter.most_common(limit)
    ]


# ---------------------------------------------------------------------------
# Discriminator search
# ---------------------------------------------------------------------------


def _last_amount(line: str) -> Decimal | None:
    hits = money_tokens(line)
    return hits[-1].value if hits else None


def _all_amounts(line: str) -> Decimal:
    return sum((h.value for h in money_tokens(line)), Decimal("0.00"))


# How a row's contribution is computed. `last` suits the common single-amount
# row; `all` is required whenever a row carries several money columns whose sum
# is the row's charge — two vendors bill that way (court fee plus search fee,
# fees plus price), and without this dimension their arithmetic can never close.
_AGGREGATES = (
    ("last_money", lambda ln: _last_amount(ln) or Decimal("0.00")),
    ("sum_of_row_money", _all_amounts),
)


def _sel_trailing_flag(line: str) -> bool:
    return bool(re.search(r"[\d,]+\.\d{2}\s+[A-Za-z]\s*$", line))


def _sel_money_count(n: int):
    def select(line: str) -> bool:
        return len(money_tokens(line)) == n

    return select


def _sel_no_symbol(line: str) -> bool:
    hits = money_tokens(line)
    return bool(hits) and "$" not in hits[-1].raw and "$" not in line


def _sel_symbol(line: str) -> bool:
    hits = money_tokens(line)
    return bool(hits) and "$" in line


def _sel_rate_signature(line: str) -> bool:
    """A row carrying a unit rate with more decimals than money uses."""
    return bool(re.search(r"\d\.\d{3,5}(?:/[A-Z]{2})?\s", line)) and bool(
        money_tokens(line)
    )


def _sel_leading_date(line: str) -> bool:
    return bool(re.match(r"\s*\d{1,2}/\d{1,2}/\d{2,4}\b", line)) and bool(
        money_tokens(line)
    )


_STRATEGIES: tuple[tuple[str, object], ...] = (
    ("trailing_flag_char", _sel_trailing_flag),
    ("exactly_1_money", _sel_money_count(1)),
    ("exactly_2_money", _sel_money_count(2)),
    ("exactly_3_money", _sel_money_count(3)),
    ("no_currency_symbol", _sel_no_symbol),
    ("has_currency_symbol", _sel_symbol),
    ("rate_signature", _sel_rate_signature),
    ("leading_date", _sel_leading_date),
)

# Lines that are obviously sums, excluded from every candidate charge set. Without
# this almost no strategy closes, because printed subtotals get counted as
# charges and inflate every sum.
_SUMMARY_WORDS = re.compile(
    r"\b(sub\s*total|subtotal|total|balance|amount\s+due|tax|enclosed|"
    r"past\s+due|aging|samples?:|count:)\b",
    re.I,
)


@dataclass
class DiscriminatorResult:
    strategy: str
    aggregate: str
    total_label: str
    total_value: Decimal
    computed: Decimal
    rows: int
    cut_marker: str | None = None

    @property
    def exact(self) -> bool:
        return self.computed == self.total_value

    def __str__(self) -> str:
        cut = f"  cut@{self.cut_marker!r}" if self.cut_marker else ""
        return (
            f"{self.strategy:<20} +{self.aggregate:<17} {self.rows:5d} rows  "
            f"computed {self.computed:>12,.2f}  vs {self.total_label!r} "
            f"{self.total_value:>12,.2f}{cut}"
        )


def _restatement_markers(doc: Document) -> list[str]:
    """Lines that plausibly begin a restated copy of the detail block.

    A bare label with no amount, appearing once, whose wording suggests a summary.
    Every vendor observed that duplicates its detail block introduces the copy
    with exactly this shape.
    """
    markers: list[str] = []
    for page in doc.pages:
        for line in page.lines:
            text = line.strip()
            if not text or money_tokens(line):
                continue
            if re.search(
                r"(summary|breakdown|recap|detail|by\s+\w+\s+type|programs)",
                text,
                re.I,
            ) and len(text) < 60:
                markers.append(text)
    seen: list[str] = []
    for marker in markers:
        if marker not in seen:
            seen.append(marker)
    return seen[:6]


def search_discriminators(
    doc: Document, *, totals: list[TotalCandidate] | None = None
) -> list[DiscriminatorResult]:
    """Try every (strategy, total, cut) combination and report exact closes."""
    totals = totals if totals is not None else total_candidates(doc)
    if not totals:
        return []

    cuts: list[str | None] = [None, *_restatement_markers(doc)]
    results: list[DiscriminatorResult] = []

    for cut in cuts:
        if cut is None:
            body = doc.lines
        else:
            body = []
            for line in doc.lines:
                if line.strip() == cut:
                    break
                body.append(line)
            if len(body) == len(doc.lines):
                continue

        candidate_lines = [ln for ln in body if not _SUMMARY_WORDS.search(ln)]

        for name, select in _STRATEGIES:
            rows = [ln for ln in candidate_lines if select(ln)]  # type: ignore[operator]
            if not rows:
                continue
            for agg_name, aggregate in _AGGREGATES:
                computed = sum(
                    (aggregate(ln) for ln in rows), Decimal("0.00")
                )
                for candidate in totals:
                    if computed == candidate.value:
                        results.append(
                            DiscriminatorResult(
                                strategy=name,
                                aggregate=agg_name,
                                total_label=candidate.label,
                                total_value=candidate.value,
                                computed=computed,
                                rows=len(rows),
                                cut_marker=cut,
                            )
                        )
    # Prefer no-cut, fewer-rows-is-not-better; just dedupe on the tuple.
    unique: dict[tuple, DiscriminatorResult] = {}
    for result in results:
        unique.setdefault(
            (result.strategy, result.aggregate, result.total_label, result.cut_marker),
            result,
        )
    return list(unique.values())


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


@dataclass
class DiscoveryReport:
    files: int
    usable: int
    unusable: list[tuple[str, str]]
    clusters: dict[str, list[str]]
    shapes: list[LineShape]
    totals: dict[str, list[TotalCandidate]]
    discriminators: dict[str, list[DiscriminatorResult]]
    column_headers: list[str]
    restatement_markers: list[str]

    def consensus(self) -> list[tuple[str, str, str, str | None, int]]:
        """(strategy, total label, cut, files) combinations that close everywhere.

        A combination that reconciles on one invoice may be coincidence. One that
        reconciles on every invoice in the folder is the answer.
        """
        tally: Counter[tuple[str, str, str, str | None]] = Counter()
        for results in self.discriminators.values():
            for result in results:
                if result.exact:
                    tally[
                        (
                            result.strategy,
                            result.aggregate,
                            result.total_label,
                            result.cut_marker,
                        )
                    ] += 1
        return [
            (strategy, aggregate, label, cut, count)
            for (strategy, aggregate, label, cut), count in tally.most_common()
        ]

    def ambiguities(self) -> list[str]:
        """What genuinely needs a human decision."""
        questions: list[str] = []

        agreed = [c for c in self.consensus() if c[-1] == len(self.discriminators)]
        if not agreed:
            questions.append(
                "No single discriminator/total pair reconciles across every invoice. "
                "Read the documents; the grammar is not uniform or a row type is "
                "being missed."
            )
        elif len(agreed) > 1:
            labels = {c[2] for c in agreed}
            if len(labels) > 1:
                questions.append(
                    "Several totals reconcile equally well "
                    f"({', '.join(sorted(labels))}). Which is this invoice's own "
                    "charges, as opposed to an account balance? This is the "
                    "highest-stakes choice in the spec."
                )

        distinct_totals = {c.label.lower() for cs in self.totals.values() for c in cs}
        if len(distinct_totals) > 3:
            questions.append(
                f"{len(distinct_totals)} total-like labels found "
                f"({', '.join(sorted(distinct_totals))}). Confirm which one the "
                "line items must sum to."
            )

        if len(self.clusters) > 1:
            questions.append(
                f"{len(self.clusters)} layout clusters. One spec each, or are some "
                "of these not invoices (aging reports and statements do turn up in "
                "invoice folders)?"
            )

        if self.unusable:
            questions.append(
                f"{len(self.unusable)} file(s) have no usable text layer. OCR them, "
                "or leave them for manual handling?"
            )

        if self.restatement_markers:
            questions.append(
                "Possible restated blocks after: "
                + ", ".join(repr(m) for m in self.restatement_markers[:4])
                + ". Confirm these restate charges already billed rather than "
                "adding new ones."
            )

        return questions

    def render(self) -> str:
        out: list[str] = []
        out.append(f"FILES  {self.files} total, {self.usable} with a usable text layer")
        for name, reason in self.unusable[:8]:
            out.append(f"   unusable  {name}: {reason}")
        if len(self.unusable) > 8:
            out.append(f"   ... {len(self.unusable) - 8} more unusable")

        out.append(f"\nLAYOUT CLUSTERS  {len(self.clusters)}")
        for signature, names in self.clusters.items():
            out.append(f"   {len(names):5d} files  {signature}  eg {names[0][:50]}")

        out.append("\nCOLUMN HEADER CANDIDATES")
        for header in self.column_headers[:6]:
            out.append(f"   {header[:118]}")

        out.append("\nTOTAL CANDIDATES (ranked by meaning, blocklist applied)")
        seen: set[str] = set()
        for candidates in self.totals.values():
            for candidate in candidates:
                key = candidate.label.lower()
                if key in seen:
                    continue
                seen.add(key)
                out.append(f"   {candidate}")

        out.append("\nDISCRIMINATOR SEARCH — combinations that reconcile exactly")
        consensus = self.consensus()
        if not consensus:
            out.append("   none. Read the documents.")
        for strategy, aggregate, label, cut, count in consensus[:12]:
            mark = " <-- all files" if count == len(self.discriminators) else ""
            cutting = f"  cut@{cut!r}" if cut else ""
            out.append(
                f"   {count:4d}/{len(self.discriminators)} files  {strategy:<20} "
                f"+{aggregate:<17} -> {label!r}{cutting}{mark}"
            )

        out.append(f"\nLINE SHAPES  ({len(self.shapes)} most common)")
        for shape in self.shapes[:24]:
            out.append(f"   {shape}")

        questions = self.ambiguities()
        if questions:
            out.append("\nASK THE USER")
            for question in questions:
                out.append(f"   - {question}")
        return "\n".join(out)


def _column_header_candidates(docs: list[Document]) -> list[str]:
    hints = (
        "DESCRIPTION",
        "QTY",
        "QUANTITY",
        "AMOUNT",
        "PRICE",
        "RATE",
        "MATERIAL",
        "ITEM",
        "DATE",
        "FEES",
        "REFERENCE",
        "UNIT",
    )
    scored: dict[str, int] = {}
    for doc in docs:
        for line in doc.lines:
            upper = line.upper()
            score = sum(1 for hint in hints if hint in upper)
            if score >= 2:
                scored[line.rstrip()] = score
    return [h for h, _ in sorted(scored.items(), key=lambda kv: -kv[1])]


def discover(
    paths: list[Path], *, sample: int = 8, allow_ocr: bool = False
) -> DiscoveryReport:
    """Profile a folder and search for the grammar.

    Only a sample of documents is analysed in depth. The discriminator search is
    the expensive part and its answer converges quickly; profiling still covers
    every file, because deciding whether the folder is one format is not something
    a sample can answer.
    """
    from .ocr import load_or_ocr
    from .profile import cluster, profile

    profiles = {}
    unusable: list[tuple[str, str]] = []
    usable_docs: list[Document] = []

    for path in paths:
        try:
            doc, reason = load_or_ocr(path, allow_ocr=allow_ocr)
        except Exception as exc:
            unusable.append((path.name, f"{type(exc).__name__}: {exc}"))
            continue
        profiles[path.name] = profile(doc)
        if reason:
            unusable.append((path.name, reason))
        elif len(usable_docs) < sample:
            usable_docs.append(doc)

    usable_count = sum(1 for p in profiles.values() if p.usable_text)

    totals: dict[str, list[TotalCandidate]] = {}
    discriminators: dict[str, list[DiscriminatorResult]] = {}
    markers: list[str] = []
    for doc in usable_docs:
        name = Path(doc.path).name
        candidates = total_candidates(doc)
        totals[name] = candidates
        discriminators[name] = search_discriminators(doc, totals=candidates)
        for marker in _restatement_markers(doc):
            if marker not in markers:
                markers.append(marker)

    return DiscoveryReport(
        files=len(paths),
        usable=usable_count,
        unusable=unusable,
        clusters=cluster(profiles),
        shapes=line_shapes(usable_docs),
        totals=totals,
        discriminators=discriminators,
        column_headers=_column_header_candidates(usable_docs),
        restatement_markers=markers[:6],
    )
