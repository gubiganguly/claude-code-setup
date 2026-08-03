---
name: invoice-parser-gen
description: Build a deterministic parser for a folder of same-format invoice PDFs, validate it on one invoice for human approval, then extract every invoice into a spreadsheet with line-item-to-total reconciliation and red flagging of anything that does not fully verify. Use when the user points at a folder of invoices and wants them extracted, tabulated, audited, or reconciled — or asks to add a new vendor to an existing extraction. Handles re-runs incrementally: dropping more invoices into the folder and running again appends only the new ones.
---

# Invoice parser generator

Turn a folder of invoice PDFs into a verified spreadsheet. The parser is
deterministic Python: a model helps author it once, and nothing calls a model at
extraction time, so the same folder always produces the same numbers.

## The guarantee, and its limits

Three independent gates, because no one of them is sufficient:

1. **The reconciliation ladder.** Every sum the invoice prints becomes a check.
   Nothing is missed and nothing is double-counted.
2. **The unclassified-line tripwire.** Every non-blank line must match a known
   row type or the invoice is flagged. This is what catches a row type appearing
   in invoice #92 instead of silently dropping it.
3. **Human approval on one invoice** before anything is written.

What this does *not* prove: that a text field is right. A truncated description
reconciles perfectly. The tripwire flags lines it does not *recognise*, not lines
it *misreads* — during the Cintas build, 49 page-title lines were being appended
to descriptions while all 91 invoices reported clean. Read the sample output.

## Commands

```bash
cd ~/.claude/skills/invoice-parser-gen

python3 run.py discover <folder>                # find the grammar; writes nothing
python3 run.py sample   <folder> --spec <name>  # parse one invoice, write nothing
python3 run.py extract  <folder> --spec <name>  # parse all new invoices into the sheet
python3 run.py extract  <folder>                # re-run; spec comes from the folder binding
python3 run.py extract  <folder> --ocr          # also OCR files with no text layer
python3 run.py status   <folder>                # what is bound, done, flagged
```

Users reach these through `/invoice-extract`, `/invoice-status` and
`/invoice-rebuild`.

`extract` is append-only and idempotent. It skips invoices already in the sheet,
never rewrites a row, and reports re-issued invoices rather than overwriting
them. The trailing `Notes` column survives every re-run.

## Workflow

### 1. Discover

```bash
python3 run.py discover <folder>
```

This does the mechanical work: profiles and clusters every file, inventories every
distinct line shape with counts and examples, ranks candidate grand totals with the
blocklist applied, guesses restatement markers, and — the part that saves the most
time — **searches for the (discriminator, aggregate, total, cut) combination whose
arithmetic closes exactly**, reporting how many sampled files each one closes on.

Read the output as follows:

- **One combination closing on all files** is your answer. Validated against four
  vendors whose specs were written independently, and it recovered the right pair
  for every one:

  | vendor | what discovery found |
  |---|---|
  | Cintas | `trailing_flag_char + last_money -> SUBTOTAL` |
  | Baxter | `exactly_2_money + sum_of_row_money -> TOTAL DUE` |
  | Data Diver | `no_currency_symbol + last_money -> Total` |
  | Experian | `no_currency_symbol + last_money -> Subtotal` |
- **Several closing on all files** usually means they select the same rows by
  different means. Pick the one that expresses the vendor's actual convention, and
  check they are not agreeing on the *wrong* total.
- **None closing** means the grammar is not uniform, a row type is being missed, or
  the real total is not in the candidate list. Go and read the PDF.

The `LINE SHAPES` inventory is what the tripwire needs: every shape listed has to
end up matched by some rule.

### 2. Ask, in one batch

Run `report.ambiguities()` — `discover` prints it as `ASK THE USER`. Ask only what
the corpus cannot answer, and ask it all at once:

- **Which total is the reconciliation target**, when several rank equally. Highest
  stakes: `Total Account Balance` and `TOTAL AMOUNT DUE` include prior balances and
  are wrong, and picking the largest number is wrong on most invoices with aging.
- **$0.00 rows** — keep or drop. Default to keeping.
- **Tax** — its own field or a line item.
- **Several clusters** — one spec each, or is a subset not an invoice at all?
- **Files with no usable text layer** — OCR, or leave for manual handling?

If the corpus answers it, do not ask.

### 3. Read the actual documents

Discovery narrows the search; it does not replace reading. `pdftotext -layout` on
the largest file, the smallest, and one mid-size. Map the grammar: header fields,
section structure, line item shape, every printed sum, and every block that is
merely informational. Check `references/traps.md` against what you see.

### 4. Confirm the discriminator

What separates a real charge row from a decoy number. `discover` searches these
automatically; this is the vocabulary for reading its output and for the cases it
cannot reach:

| Strategy | Works when |
|---|---|
| trailing token class | rows end in a flag (`Y`/`N`) that sums never carry |
| money-token count | charge rows have exactly N amounts, sums have one |
| `$`-sign presence | items print bare numbers, totals print `$` |
| column type signature | a distinctive rate format (`0.15000`, `68.95/FL`) |
| money-token x-band | the amount column is geometrically separate |
| section/page scoping | charges only exist inside one document region |

Prefer a textual discriminator to geometry where one exists. An x-band fails on
Cintas (charges at x≈566, grand total at x≈562) and on any vendor whose report
generator auto-sizes columns.

### 5. Write the spec

Copy `specs/cintas.py` as the model. A spec is rules, zone markers, a ladder,
and header field patterns. Order matters — first match wins, so specific rules
precede general ones and known boilerplate precedes anything shape-based.

Declare **every** printed sum as a ladder rung. They are free independent
constraints, and the grand total alone cannot catch a parser that mis-buckets
rows across groups while still totalling correctly.

Iterate until, across the whole folder, unclassified is **zero** and every
required rung passes. `engine.reconcile.diagnose` maps a delta to likely causes:
short means something is missed, over means something is counted twice.

### 6. Sample, and stop

```bash
python3 run.py sample <folder> --spec <name>
```

Show the user the ladder, the row classification, the header fields, and the
first line items. Confirm the printed total against the PDF itself rather than
trusting the parse. **Wait for approval. Write nothing.**

### 7. Extract

```bash
python3 run.py extract <folder> --spec <name>
```

Then report the summary table and name every flagged invoice.

## Scanned invoices

`extract` refuses a file with no usable text layer and records it in Exceptions.
`--ocr` renders each page at 300dpi through tesseract into a searchable-PDF
sidecar at the original page dimensions, so the OCR'd document takes exactly the
same path as a native one and no spec needs an OCR branch. Results cache on file
content, so a re-run is free.

Set expectations honestly. Tesseract misreads digits *and* labels — a verified
case read `14.75` for `11.75`, and another mangled `Total` into `ota`, which means
a label-matching total rule simply will not fire. So OCR'd invoices frequently
land in Exceptions rather than verifying, and that is the correct outcome. The
ladder stays at zero tolerance on the OCR path; that is the entire reason for
running it there.

`--ocr-max-pages` (default 60) stops a 600-page scan from hanging a bulk run.

## Hard rules

- **Never bulk-extract before the user approves a sample.**
- **Zero tolerance by default.** These documents are internally exact; a
  tolerance hides the double-count it was added to suppress. Relax only for OCR,
  and say so in the report.
- **Never default an unreadable amount to zero.** Fail loudly. A zero produces a
  total that is wrong and plausible.
- **Never recompute a line total from quantity × unit price.** Unit prices carry
  more decimals than the printed total; recomputing breaks the subtotal check on
  most rows. Take the printed figure.
- **Never drop a column you do not understand.** Capture it as a field. An
  unlabelled Cintas sub-column is the only thing distinguishing two otherwise
  identical rows.
- **When a rung misses by a clean amount, look for a printed component you have
  not found.** One vendor looked like it printed a `Total Court Fees` $82.00 short;
  in fact its fee column decomposes into three printed totals and the shortfall was
  exactly the one that had been overlooked. Across the whole reference corpus there
  are **no** vendor arithmetic errors. Suspect the spec first, and never add a
  tolerance to close a gap you have not explained.
- **Refuse rather than guess.** A document with no usable text layer goes to the
  Exceptions sheet, not through the parser. So does a document the ladder cannot
  reach: one LabCorp file is 642 pages holding 494 nested sub-invoices whose totals
  sum to $220,290.70 against a printed $174,380.14 and $110,138.35 — three figures,
  none of them an invoice value. `specs/labcorp.py` marks every rung not-applicable
  and refuses with that explanation. A clear refusal is a correct outcome.
- **Never let a sparse page decide for the document.** Judge the text layer on the
  document mean. Refusing anything with one thin page rejected 65 good invoices
  over blank pages and footer-only pages.

## Output

`Invoice Extraction.xlsx` in the invoice folder:

- **Invoices** — one row each; rows that did not fully verify are filled red
- **Line Items** — one per charge, invoice fields denormalised on
- **Exceptions** — only what needs a human, with the specific failing check

State lives in `.invoice-parser/` beside it: `extractions.jsonl` and the
signature→spec bindings.

## Reference

- `references/traps.md` — the failure catalogue, from ~900 invoices
- `engine/` — `text` `money` `classify` `columns` `reconcile` `spec` `profile`
  `discover` `ocr` `store` `sheet`

Six worked specs, all at zero tolerance with zero unclassified lines. Read the one
closest in shape to the vendor in front of you:

| spec | what it demonstrates | verified | depth |
|---|---|---|---|
| `cintas` | grouped subtotals, zones, wrapped descriptions, header-offset slicing | 91/91 | 3–5 |
| `baxter` | no in-body subtotals: reconciles per column plus a row count | 53/53 | 4 |
| `datadiver` | `$`-absence discriminator, credits, shallow ladder | 34/34 | 1–2 |
| `experian` | rate-unit signature, four description grammars, cross-page wraps | 26/26 | 5–6 |
| `appriss` | a fully restated detail block cut by zone; 13 total labels | 33/33 | 10 |
| `eagleeye` | front-summary cut, three-way fee decomposition | 32/32 | 14 |
| `labcorp` | two templates in one spec, zone-scoped pages, multi-row items, container refusal | 39/40 | 0–16 |

## Two rules learned the hard way

**Match structure, not labels.** A fee-breakdown rule that enumerated the
prefixes it had seen (`Court`, `Miscellaneous`, `Clerk`, `Filing`) failed on
twelve invoices carrying `File Pull Fee`. The shape — indented label, colon, one
amount — identifies them all and cannot collide with a charge row.

**Fix the engine, not the spec.** If a vendor needs something the engine cannot
express, that is a missing general capability. Baxter needed per-column
reconciliation, count checks, and shared header-offset slicing; all three went
into the engine and Cintas kept passing.
