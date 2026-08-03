"""The reconciliation ladder: declare the sums an invoice prints, then check them.

Checking only the grand total is not enough, and the failure it misses is not
hypothetical. A parser can pull subtotal rows into its line items *and* read an
inflated total off a summary block, and then agree with itself perfectly while
reporting several times the real invoice value. Self-consistency is not
correctness.

Every intermediate sum a vendor prints is a free independent constraint. Cintas
prints three (per-employee, per-department, invoice subtotal) plus a restatement
block, so a mis-bucketed row has four chances to be caught instead of one. The
`depth` of a reconciliation, meaning how many distinct levels actually ran, is
therefore the honest measure of how much the result can be trusted:

    depth >= 2   the arithmetic is cross-checked from more than one direction
    depth == 1   only the grand total was verifiable; an independent read is
                 warranted before trusting the line items
    depth == 0   nothing was verified

Tolerance defaults to exactly zero. These documents are internally consistent to
the cent, so any drift is a parser bug rather than rounding, and a tolerance
would hide the double-count it exists to catch. Only OCR'd sources should ever
relax it.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum

from .classify import ClassifiedRow, RowKind

__all__ = [
    "ZERO",
    "CheckMode",
    "CheckStatus",
    "LevelCheck",
    "CheckResult",
    "Reconciliation",
    "reconcile",
    "diagnose",
]

ZERO = Decimal("0.00")


class CheckMode(str, Enum):
    """What a rung compares.

    SUM is the usual case. COUNT exists because a printed row count is an
    independent constraint that no sum can replace: a dropped $0.00 row leaves
    every total correct. Three of the reference vendors print one.
    """

    SUM = "sum"
    COUNT = "count"


class CheckStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    # A declared-advisory rung that disagreed. Reported prominently but does not
    # fail the invoice. `required=False` only covers a printed value being
    # *absent*; this covers one being *present and different*, which is what a
    # figure you do not fully trust actually needs.
    ADVISORY_MISMATCH = "advisory_mismatch"
    MISSING_PRINTED = "missing_printed"  # charges present, no printed sum to check
    ORPHAN_PRINTED = "orphan_printed"  # printed sum present, no charges behind it
    NOT_APPLICABLE = "not_applicable"  # this invoice prints no such level


@dataclass(frozen=True)
class LevelCheck:
    """One rung of the ladder, declared rather than coded.

    `computed_from` names the row kinds whose amounts add up; `printed_kind`
    names the kind carrying the figure the invoice printed. With `group_by` set,
    both sides are bucketed by that field and compared per bucket, which is how
    per-employee and per-department subtotals are expressed without any
    check-specific code.
    """

    name: str
    computed_from: tuple[RowKind, ...]
    printed_kind: RowKind
    mode: CheckMode = CheckMode.SUM
    # Which field is summed on the computed rows, and which field carries the
    # printed figure. Named rather than assumed, because a row with several money
    # columns needs each column checked separately.
    computed_field: str = "amount"
    printed_field: str = "amount"
    group_by: str | None = None
    where: Callable[[ClassifiedRow], bool] | None = None
    # Filters the printed side only. Defaults to `where`, which is right when a
    # rung selects both sides the same way, but the two genuinely diverge: a
    # vendor may print several sums of the same kind distinguished only by which
    # field they carry, and gating the printed rows with a predicate written for
    # charge rows would reject all of them.
    where_printed: Callable[[ClassifiedRow], bool] | None = None
    tolerance: Decimal = ZERO
    required: bool = True
    # Report a mismatch without failing the invoice. For a printed figure whose
    # reliability is genuinely unknown — never as a way to quiet a rung you have
    # not explained.
    advisory: bool = False
    description: str = ""

    def selects(self, row: ClassifiedRow) -> bool:
        if self.where is not None and not self.where(row):
            return False
        return True

    def selects_printed(self, row: ClassifiedRow) -> bool:
        predicate = self.where_printed if self.where_printed is not None else self.where
        if predicate is not None and not predicate(row):
            return False
        return True


@dataclass(frozen=True)
class CheckResult:
    check: str
    status: CheckStatus
    computed: Decimal | None = None
    printed: Decimal | None = None
    group: str | None = None
    detail: str = ""

    @property
    def delta(self) -> Decimal | None:
        if self.computed is None or self.printed is None:
            return None
        return self.computed - self.printed

    @property
    def ok(self) -> bool:
        return self.status in (
            CheckStatus.PASS,
            CheckStatus.NOT_APPLICABLE,
            CheckStatus.ADVISORY_MISMATCH,
        )

    def __str__(self) -> str:
        label = f"{self.check}" + (f"[{self.group}]" if self.group else "")
        if self.status is CheckStatus.NOT_APPLICABLE:
            return f"{label}: not applicable"
        if self.delta is None:
            return f"{label}: {self.status.value} — {self.detail}"
        return (
            f"{label}: computed {self.computed} vs printed {self.printed} "
            f"(delta {self.delta:+}) {self.status.value}"
        )


@dataclass
class Reconciliation:
    results: list[CheckResult] = field(default_factory=list)
    unclassified: list[ClassifiedRow] = field(default_factory=list)

    @property
    def failures(self) -> list[CheckResult]:
        return [r for r in self.results if not r.ok]

    @property
    def advisories(self) -> list[CheckResult]:
        """Advisory rungs that disagreed. Not failures, but never hide them."""
        return [
            r for r in self.results if r.status is CheckStatus.ADVISORY_MISMATCH
        ]

    @property
    def depth(self) -> int:
        """How many distinct levels actually verified something."""
        return len({r.check for r in self.results if r.status is CheckStatus.PASS})

    @property
    def levels_run(self) -> int:
        return len({r.check for r in self.results})

    @property
    def passed(self) -> bool:
        """Fully verified: something was checked, it held, and every line was understood.

        Three clauses, none redundant.

        `depth >= 1` requires that at least one rung actually *compared* two
        figures. Without it, an invoice whose every rung came back "not
        applicable" reported as verified — which is what happens when a spec is
        pointed at a document it does not fit: it matches no charges, finds no
        totals, has nothing to check, and passes vacuously. That is the same
        failure as a parser agreeing with itself about the wrong number, and it is
        the one this whole design exists to prevent.

        `not failures` is the arithmetic. `not unclassified` is the tripwire: a
        dropped row whose amount is zero, or a description truncated by a wrapped
        continuation, reconciles perfectly and is still wrong.
        """
        return (
            self.depth >= 1 and not self.failures and not self.unclassified
        )

    @property
    def status_label(self) -> str:
        if self.passed:
            return "verified"
        if self.unclassified and not self.failures:
            return "unclassified rows"
        return "reconciliation failed"

    def value_of(self, check: str) -> Decimal | None:
        for r in self.results:
            if r.check == check and r.printed is not None:
                return r.printed
        return None

    def summary(self) -> str:
        lines = [
            f"{self.status_label}  "
            f"({sum(1 for r in self.results if r.ok)}/{len(self.results)} checks, "
            f"depth {self.depth})"
        ]
        for r in self.failures:
            lines.append(f"  FAIL  {r}")
        for r in self.advisories:
            lines.append(f"  ADVISORY  {r}")
        for row in self.unclassified[:10]:
            lines.append(f"  UNCLASSIFIED  {row.location}: {row.raw.strip()[:80]}")
        if len(self.unclassified) > 10:
            lines.append(f"  ... {len(self.unclassified) - 10} more unclassified")
        return "\n".join(lines)


def _bucket(
    rows: Iterable[ClassifiedRow], group_by: str | None
) -> dict[str | None, list[ClassifiedRow]]:
    out: dict[str | None, list[ClassifiedRow]] = {}
    for row in rows:
        key = None if group_by is None else str(row.fields.get(group_by, ""))
        out.setdefault(key, []).append(row)
    return out


def _sum(rows: Iterable[ClassifiedRow], field_name: str = "amount") -> Decimal:
    total = ZERO
    for row in rows:
        value = row.decimal_field(field_name)
        if value is not None:
            total += value
    return total


def _computed(rows: Sequence[ClassifiedRow], check: "LevelCheck") -> Decimal:
    if check.mode is CheckMode.COUNT:
        return Decimal(len(rows))
    return _sum(rows, check.computed_field)


def _printed(rows: Sequence[ClassifiedRow], check: "LevelCheck") -> Decimal:
    # A printed count appears once, not once per row, so summing it would be
    # wrong when a vendor repeats the header on every page.
    if check.mode is CheckMode.COUNT:
        values = [r.decimal_field(check.printed_field) for r in rows]
        found = [v for v in values if v is not None]
        return found[0] if found else ZERO
    return _sum(rows, check.printed_field)


def _run_check(check: LevelCheck, rows: Sequence[ClassifiedRow]) -> list[CheckResult]:
    computed_rows = [
        r for r in rows if r.kind in check.computed_from and check.selects(r)
    ]
    printed_rows = [
        r for r in rows if r.kind is check.printed_kind and check.selects_printed(r)
    ]

    if not printed_rows:
        if check.required and computed_rows:
            return [
                CheckResult(
                    check.name,
                    CheckStatus.MISSING_PRINTED,
                    computed=_computed(computed_rows, check),
                    detail=(
                        f"{len(computed_rows)} rows to verify but the invoice printed "
                        f"no {check.printed_kind.value}"
                    ),
                )
            ]
        return [CheckResult(check.name, CheckStatus.NOT_APPLICABLE)]

    computed_buckets = _bucket(computed_rows, check.group_by)
    printed_buckets = _bucket(printed_rows, check.group_by)

    results: list[CheckResult] = []
    for key in sorted(set(computed_buckets) | set(printed_buckets), key=lambda k: k or ""):
        printed_here = printed_buckets.get(key)
        computed_here = computed_buckets.get(key, [])

        if printed_here is None:
            results.append(
                CheckResult(
                    check.name,
                    CheckStatus.MISSING_PRINTED if check.required else CheckStatus.NOT_APPLICABLE,
                    computed=_computed(computed_here, check),
                    group=key,
                    detail="no printed sum for this group",
                )
            )
            continue

        printed = _printed(printed_here, check)
        if not computed_here:
            results.append(
                CheckResult(
                    check.name,
                    CheckStatus.ORPHAN_PRINTED,
                    computed=ZERO,
                    printed=printed,
                    group=key,
                    detail="printed a sum with no rows behind it",
                )
            )
            continue

        computed = _computed(computed_here, check)
        ok = abs(computed - printed) <= check.tolerance
        if ok:
            status = CheckStatus.PASS
        else:
            status = (
                CheckStatus.ADVISORY_MISMATCH if check.advisory else CheckStatus.FAIL
            )
        results.append(
            CheckResult(
                check.name,
                status,
                computed=computed,
                printed=printed,
                group=key,
            )
        )
    return results


def reconcile(
    rows: Sequence[ClassifiedRow], ladder: Sequence[LevelCheck]
) -> Reconciliation:
    """Run every rung of the ladder over a classified row stream."""
    results: list[CheckResult] = []
    for check in ladder:
        results.extend(_run_check(check, rows))
    return Reconciliation(
        results=results,
        unclassified=[r for r in rows if r.kind is RowKind.UNCLASSIFIED],
    )


def diagnose(delta: Decimal, rows: Sequence[ClassifiedRow]) -> list[str]:
    """Turn a non-zero delta into concrete things to go and look at.

    Written for the build loop, where the useful question is never "is it
    wrong" but "which of the four usual mistakes is this". The sign narrows it
    immediately: short means something is not being captured, over means
    something is being counted twice.
    """
    if delta == ZERO:
        return []

    hints: list[str] = []
    charges = [r for r in rows if r.kind is RowKind.CHARGE]
    unclassified = [r for r in rows if r.kind is RowKind.UNCLASSIFIED]

    if delta < ZERO:
        hints.append(
            "Computed is SHORT: a row or a column is being missed. Check "
            "unclassified lines first, then look for a charge column the row "
            "pattern does not capture."
        )
        if unclassified:
            hints.append(
                f"{len(unclassified)} unclassified line(s) — likely the missing rows. "
                f"First: {unclassified[0].raw.strip()[:70]!r}"
            )
    else:
        hints.append(
            "Computed is OVER: something is counted twice. The usual causes are a "
            "restatement or summary block being read as charges, printed subtotals "
            "being classified as CHARGE, or a repeated header block on later pages."
        )

    magnitude = abs(delta)
    for row in rows:
        if row.kind in (RowKind.TAX, RowKind.RESTATEMENT, RowKind.GROUP_SUBTOTAL):
            if row.amount is not None and abs(row.amount) == magnitude:
                hints.append(
                    f"The delta exactly equals a {row.kind.value} row "
                    f"({row.raw.strip()[:60]!r}) — that row is on the wrong side."
                )
                break

    if charges and magnitude == abs(_sum(charges[:1])):
        hints.append("The delta equals the first charge row — check for an off-by-one.")

    return hints
