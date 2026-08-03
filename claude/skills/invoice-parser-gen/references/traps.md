# Invoice parsing traps

Observed across ~600 invoices from 8 vendor families. Every entry here produced a
result that looked correct. Work through this list when a spec is written, and
again when a rung fails.

## The three that silently corrupt output

### 1. Annotation-only text layer

A scanned invoice with AP notes typed over it has a real text layer of 20–230
characters and no invoice content. `if text: parse_text_layer()` returns
successfully with zero line items and raises nothing. 40 files across four
vendors in the reference corpus.

Signatures: GL codes (`50130-1500-125001`), dated initials (`12/4/25 ... -CR`),
payment verbs (`Paid ACH`, `Credit applied`, `CM 80645841 applied to 85441862`),
or a bare integer sequence (form field counters).

**Gate on character count *and* the presence of invoice vocabulary.**
`engine.profile.LayoutProfile.usable_text` does both.

### 2. A restated block

The invoice prints the same charges twice, in a different breakdown. Summing both
overstates, sometimes by exactly 100%.

| Vendor | What is restated | Effect if summed |
|---|---|---|
| Appriss | the **entire** detail block, byte-identical, regrouped by service type | exactly 2× |
| LabCorp | `LOCATION TOTAL` / `ACCOUNT TOTAL` on both summary and detail pages | exactly 2× |
| Eagle Eye | the whole invoice as a per-state front summary | exactly 2× |
| Cintas | program charges as qty × rate under `SPECIAL PROGRAMS BREAKDOWN` | overstates by that block |
| Experian | subtotal 3×, grand total 2× (including a barcode string) | varies |

Cut on the marker with a zone. The restated copy is usually *after* a bare
label line with no value. Where the restatement is complete, declare it as an
advisory rung: it then becomes a free extra check instead of a hazard.

### 3. Wrapped continuation lines

A long description wraps to a bare token on the next line. Money is unaffected,
so **the ladder passes while the text is truncated**. 277 occurrences in the
Cintas corpus; on Baxter it is *every single row*.

Worse: the wrap can cross a page break, landing as the first body line of the
next page with the whole repeated header block in between. Any guard that
requires the immediately preceding row to be a charge fails there — skip the
structural row kinds when looking back.

And beware the inverse: a lone right-shifted all-caps token also describes the
centred `INVOICE` page title. Test known boilerplate **before** anything
shape-based, or 49 page titles end up appended to descriptions.

## Choosing the grand total

**The largest total-like number is routinely wrong.** Rank by semantics.

Never select: `Total Account Balance`, `TOTAL ACCOUNT BALANCE`, `Previous
Account Balance`, `ACCOUNT BALANCE`, `TOTAL AMOUNT DUE`, `PRIOR PERIOD BALANCE`,
`Balance` in a remit stub, `Total:` inside a tax summary, `Total sales tax
calculated by AvaTax`, `Total Court Fees`.

Prefer: `Current Invoice Total`, `INVOICE TOTAL`, `CURRENT PERIOD TOTAL`,
`TOTAL DUE`, `Grand Total` (last occurrence), `TOTAL` on the final page.

Worked examples:

- Appriss `2064631681`: previous 74,680.19 + current 75,059.38 →
  `TOTAL ACCOUNT BALANCE 149,739.57`. Correct answer is 75,059.38. "Pick the
  largest" or "pick the last total on page 1" is wrong on 24 of 33 files.
- LabCorp: `TOTAL AMOUNT DUE $203.50` is the account payable;
  `CURRENT AMOUNT DUE $60.75` is this invoice. The aging bucket reads
  `$204.50CR` — a credit, larger in absolute value than the right answer.
- Data Diver: `Total` is the invoice, `Balance Due` is payable, and they diverge
  when `Payments/Credits Applied -$1,032.35` exists. The minus sits *inside* the
  money token with no separating space.
- Experian: `Total: $3,626.81` inside `Summary of Taxes` holds only the tax.

Pair labels to values **spatially**, not in reading order. `-layout` flattens
multi-column blocks and will pair a label with a neighbouring column's value.
LabCorp splits one label across three physical lines with the value on the first.

## Decoy numbers that are not charges

- **Contingent notices.** `EMPLOYEE 0005 OWES 002 Shirts OR PAY $ 52.56
  REPLACEMENT CHARGE` — a real amount, never billed. 77 in the Cintas corpus.
- **Aging tables.** Per-bucket amounts, often with `CR` suffixes.
- **Statement / transaction ledgers.** Every prior invoice with `BILLED`,
  `PAID BY WIRE TRANSFER`, `PAID BY CHECK # 050023`, plus a running balance
  column.
- **Tax summary tables** whose `Non-Taxable Amount` column restates the whole
  subtotal once per jurisdiction.
- **Marketing lines.** `YOUR ADVANTAGE PROGRAMS PREVENTED YOU FROM AN ADDITIONAL
  EXPENSE OF $ 14.76.`
- **Barcode / scanline strings** that embed the total as a digit run.
- **Template placeholder garbage** emitted as text: literal lines `A`, `a`,
  `asddfgg`, and 12–28 bare `B` lines per page on Experian.
- **A `$0.00` pseudo-row inside the item table** whose label contains the word
  `Total` (`Total sales tax calculated by AvaTax`), which a keyword-based total
  finder will latch onto.

## Structural hazards

- **Sections span page breaks.** Delimit on the printed subtotal, never on the
  page. One Cintas invoice runs a single section across four pages.
- **Column offsets differ between a vendor's own variants.** Cintas puts
  MATERIAL at column 16 on garment invoices and 13 on facility invoices. Read
  offsets from the governing header row; do not hard-code them.
- **Headers repeat on every page** (Experian 30×, Baxter 25×) — or appear exactly
  once and never again (Eagle Eye).
- **Multi-row items** where the money is on the continuation lines, not the item
  row. LabCorp's detail rows work this way.
- **Annotation injected above the header block** pushes `TOTAL DUE` from line 4
  to line 13. A fixed `lines[:12]` window returns nothing.
- **Values printed unformatted.** Experian's per-requester subtotal prints
  `$45335.1` — one decimal, no comma — while every other amount is `$45,335.10`.
  A `\$[\d,]+\.\d\d` pattern misses it entirely.
- **The same label with two layouts in one document.** Appriss prints
  `Service Summary Total` once with the value on the next line and once inline.
- **Container documents.** One LabCorp file is 642 pages holding 494 nested
  sub-invoices spanning two billing periods. No single-level reconciliation
  exists. Detect and refuse.
- **`$0.00` is often the majority case**, not an exception. Filtering
  `amount > 0` destroys row counts and drops real rows.
- **Non-numeric identifiers.** `INVOICE NUMBER = SUMMARY`; Baxter invoice
  numbers are date codes like `241231_CBCI`.
- **Not-an-invoice files** in invoice folders: aging reports, statements, and one
  vendor folder that is entirely XLSX with a file that has no extension at all.

## Decomposition lines that are not charges

A labelled amount indented under a row often *itemises* that row's value rather
than adding to it. Baxter prints `Court Search Fee for Case Number clerk check:
$15.00` beneath a row whose Court Fees cell already reads `$15.00`; a row showing
`$18.00` is followed by `$3.00` and `$15.00`. Summing them doubles the column.
Verified against an 8,298-row invoice where all four rungs close only when these
are excluded.

Classify them as `RESTATEMENT`: captured, never summed, never lost. And match
them **structurally** — an indented label ending in a colon followed by exactly
one amount — rather than by enumerating labels, which is how twelve invoices got
missed over the single unlisted phrase `File Pull Fee`.

## When a vendor prints a row count

`Total Searches: 518`, `Grand Total: 312`, `TOTAL SAMPLES BILLED: 3`. Three of the
reference vendors print one, and it is the only check that catches a dropped
`$0.00` row — which matters because `$0.00` is the majority value in whole
columns (518 of 518 in one Baxter file). Declare it as a count rung.

## Money that does not parse

Three shapes that silently return "no amount on this line" if the parser is naive.
`engine.money` handles all of them; a spec should never re-implement money parsing.

- **Sign on either side of the currency symbol.** `$-1,032.35` and `-$1,032.35`
  both occur. Accepting only one reads the other as "no amount", which looks like
  a missing row rather than a parse failure.
- **Parenthesised negatives**, `($11.40)`, and trailing minus, `1,032.35-`.
- **Unformatted values.** One vendor prints a subtotal as `$45335.1` — one decimal,
  no thousands comma — while every other amount on the page is `$45,335.10`. Pass
  `min_decimals=1` for that field only; accepting one decimal everywhere starts
  reading rates and version numbers as money.

Also: `Payments/Credits Applied -$1,032.35` prints the label and value with **no
separating gap**, so a `\s{2,}` column split does not see two cells.

## Totals that share a line with something else

`-layout` flattens columns, so a label routinely lands on the same physical line as
unrelated text. One vendor prints `PLEASE NOTE OUR REMITTANCE ADDRESS:   Total
$10,238.36`, and *which* address line carries the total varies by template within
the same vendor. Any pattern anchoring a total label to the start of a line will
miss these; match the label by word boundary and require only that it sit left of
the amount.

The same flattening puts several label/value pairs on one line: Baxter's
`Names: 518   Search Fees   $1,111.15` carries a count and a column total
together, and a line can only be one row kind. Give the row one kind and store the
several values as separately-named fields, then let each rung address the field it
needs.

## Diagnosing a failing rung

| Symptom | Likely cause |
|---|---|
| computed **short** | a row or column not captured; check unclassified first |
| computed **over** | double-count: a restated block, or subtotals read as charges |
| delta equals a **single printed value** | that row is on the wrong side (often tax) |
| delta is **exactly 2×** | a fully restated block |
| **over** with a low row count | a multi-row item read as one row per visual line |
| one rung fails, others pass | mis-bucketing, or the vendor's own arithmetic is wrong |

## Before blaming the vendor's arithmetic, look for a component you missed

This one is worth reading twice, because an earlier version of this file got it
wrong and the wrong version was actively dangerous advice.

Eagle Eye appears to print `Total Court Fees $1,775.50` against a true `Fees`
column sum of `$1,857.50` — an $82.00 error. It is not an error. The column
decomposes into **three** printed totals, not one:

```
Total Rush Fees + All Other Fees + Total Court Fees == sum(Fees)
4610:   $0.00 +  $82.00 + $1,775.50 = $1,857.50  ✓
5631:   $0.00 +   $3.00 + $2,281.00 = $2,284.00  ✓
5047:  $10.00 +   $0.00 + $2,564.25 = $2,574.25  ✓
```

`All Other Fees` is printed on 28 of 32 files and `Total Rush Fees` on 2, and
missing them produced a phantom discrepancy that exactly equalled the component
left out. Verified across all 32 files: **zero vendor arithmetic errors, every
rung at zero tolerance.**

The lesson generalises. When a column sum misses a printed total by a clean
amount, the first hypothesis should be *another printed component you have not
found yet* — look for it before concluding the vendor is wrong, and certainly
before adding a tolerance. A tolerance would have buried this permanently.

Related, from the same vendor: the `Court Fees:` / `Alias Fees:` continuation
lines under detail rows *are* exact validators at column level
(`sum(Court Fees:) == Total Court Fees` on all 32). They are still `RESTATEMENT`
and never summed into charges, but they earn a rung rather than being dismissed.
Note `* Total Alias Fees` is asterisked because alias fees live in the **Price**
column, not Fees — the asterisk is the discriminator.

## OCR

300 dpi, `tesseract --psm 3`. `--psm 6` drops header rows; `--psm 4` corrupts
names. Render into a page of the **source dimensions** so coordinates stay valid.

OCR corrupts money digits — a verified case read `14.75` where the truth was
`11.75`, a silent $3.00 error caught only by the printed subtotal. So on the OCR
path the ladder is mandatory, not optional, and a mismatch must flag rather than
emit. Every trap above survives OCR and needs identical handling.
