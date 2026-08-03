"""Money parsing for invoice extraction. Decimal only, never float.

Invoice arithmetic has to be exact. Unit prices on real invoices carry three
decimal places while line totals carry two, so a float sum drifts within a
dozen rows and turns a clean reconciliation into a penny mismatch that looks
like a parser bug. Every amount in this engine is a Decimal from the moment it
leaves the PDF until it lands in a cell.

The lenient mode exists for OCR'd documents, where tesseract routinely reads
`1` as `l` or `|`. It is off by default: applying those substitutions to a
clean text layer would corrupt real data.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

__all__ = [
    "MONEY_RE",
    "MONEY_RE_LOOSE",
    "MoneyHit",
    "parse_money",
    "money_tokens",
    "last_money_on_line",
    "looks_like_money",
]

def _money_pattern(min_decimals: int) -> re.Pattern[str]:
    """Build the money pattern for a minimum fractional-digit count.

    The sign is accepted on BOTH sides of the currency symbol. Vendors print it
    either way — `$-1,032.35` and `-$1,032.35` both occur in the reference corpus
    — and accepting only one silently returns None for the other, which then reads
    as "this line has no amount" rather than as a parse failure.
    """
    fraction = f"\\d{{{min_decimals},2}}" if min_decimals < 2 else r"\d{2}"
    core = (
        rf"\d{{1,3}}(?:[,. ]\d{{3}})*[,.]{fraction}"
        rf"|\d+[,.]{fraction}"
    )
    return re.compile(
        r"""
        (?P<open>\()?                 # ( for accounting-style negative
        \s*
        (?P<sign_pre>-)?               # minus before the currency symbol
        \s*
        (?P<cur>[$€£]|USD\s*)?        # optional currency marker
        \s*
        (?P<sign>-)?                  # minus after the currency symbol
        (?P<num>"""
        + core
        + r""")
        (?P<trail>-)?                 # trailing minus (some ERP exports)
        \s*
        (?P<close>\))?                # ) closing an accounting negative
        $
        """,
        re.VERBOSE,
    )


# Requires a decimal part: bare integers are quantities and years far more often
# than they are amounts.
MONEY_RE = _money_pattern(2)
# For vendors that print an unformatted value — one report emits `$45335.1` for a
# subtotal while every other amount on the page is `$45,335.10`. Opt in per call;
# accepting one decimal everywhere would start reading version numbers and rates
# as money.
MONEY_RE_LOOSE = _money_pattern(1)

# tesseract's habitual misreads of `1`. Only applied in lenient mode.
_ONE_LIKE = str.maketrans({"l": "1", "L": "1", "i": "1", "I": "1", "|": "1", "!": "1"})


@dataclass(frozen=True)
class MoneyHit:
    """A money token located within a line of text."""

    raw: str
    value: Decimal
    index: int  # token index within the whitespace-split line
    start: int  # character offset of the token in the original line
    end: int


def _normalise_separators(num: str) -> str:
    """Collapse thousands separators and settle which mark is the decimal point.

    Handles both `1,234.56` and the European `1.234,56`. When both marks are
    present the rightmost one is the decimal separator; when only a comma is
    present it is decimal only if exactly two digits follow it.
    """
    num = num.replace(" ", "")
    has_comma, has_dot = "," in num, "." in num

    if has_comma and has_dot:
        dec_sep = "," if num.rfind(",") > num.rfind(".") else "."
    elif has_comma:
        dec_sep = "," if len(num.rsplit(",", 1)[1]) == 2 else ""
    else:
        dec_sep = "."

    if dec_sep == ",":
        head, tail = num.rsplit(",", 1)
        return head.replace(",", "").replace(".", "") + "." + tail
    if dec_sep == ".":
        head, tail = num.rsplit(".", 1)
        return head.replace(",", "").replace(".", "") + "." + tail
    return num.replace(",", "").replace(".", "")


def parse_money(
    token: str, *, lenient: bool = False, min_decimals: int = 2
) -> Decimal | None:
    """Parse a single token as an amount, or return None if it is not one.

    Returning None rather than zero is deliberate. A parser that defaults an
    unreadable amount to 0.00 produces a total that is wrong but plausible;
    one that returns None forces the caller to decide, and the reconciliation
    ladder then catches it.
    """
    if token is None:
        return None
    tok = token.strip()
    if not tok:
        return None
    if lenient:
        tok = tok.translate(_ONE_LIKE)

    pattern = MONEY_RE if min_decimals >= 2 else MONEY_RE_LOOSE
    m = pattern.match(tok)
    if not m:
        return None

    try:
        value = Decimal(_normalise_separators(m.group("num")))
    except InvalidOperation:
        return None

    negative = bool(
        m.group("sign") or m.group("sign_pre") or m.group("trail")
    ) or bool(m.group("open") and m.group("close"))
    return -value if negative else value


def looks_like_money(
    token: str, *, lenient: bool = False, min_decimals: int = 2
) -> bool:
    return parse_money(token, lenient=lenient, min_decimals=min_decimals) is not None


def money_tokens(
    line: str, *, lenient: bool = False, min_decimals: int = 2
) -> list[MoneyHit]:
    """Every money token on a line, left to right, with positions.

    Character offsets are retained because several discriminator strategies
    key on where an amount sits horizontally, and the offset is the cheapest
    proxy for that when working from `pdftotext -layout` output.
    """
    hits: list[MoneyHit] = []
    offset = 0
    for index, tok in enumerate(line.split()):
        start = line.find(tok, offset)
        offset = start + len(tok)
        value = parse_money(tok, lenient=lenient, min_decimals=min_decimals)
        if value is not None:
            hits.append(MoneyHit(tok, value, index, start, offset))
    return hits


def last_money_on_line(
    line: str, *, lenient: bool = False, min_decimals: int = 2
) -> MoneyHit | None:
    """The rightmost amount on a line.

    On almost every invoice layout the row's own amount is the last money
    token, so this is the workhorse accessor. The returned index lets callers
    inspect what trails the amount, which is how tax flags and no-charge
    markers get read.
    """
    hits = money_tokens(line, lenient=lenient, min_decimals=min_decimals)
    return hits[-1] if hits else None
