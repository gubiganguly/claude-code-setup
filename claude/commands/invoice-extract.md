---
description: Extract a folder of invoice PDFs into a verified spreadsheet, building the parser first if the folder is new
argument-hint: [folder path] (defaults to ./invoices, or the current directory)
---

Extract invoices from: **$ARGUMENTS**

If no folder was given, look for `./invoices`, then `./Invoices`, then use the
current directory. If none contains PDFs, say so and stop.

Use the `invoice-parser-gen` skill. Invoke it now with the Skill tool so its full
workflow and hard rules are loaded, then follow them.

## Decide which state you are in first

```bash
cd ~/.claude/skills/invoice-parser-gen && python3 run.py status <folder>
```

**A spec is already bound and there are new PDFs** — this is the common case.
Go straight to extraction:

```bash
cd ~/.claude/skills/invoice-parser-gen && python3 run.py extract <folder>
```

No approval is needed: the spec was approved when it was built. Report the
summary table and name every flagged invoice.

**A spec is bound and nothing is new** — say so in one line and stop. Do not
re-extract.

**Nothing is bound** — the folder is new, so build a parser. Follow the skill's
workflow: profile, read the documents, find the grand total carefully, pick a
discriminator, write the spec, iterate until unclassified is zero and every
required rung passes across the whole folder.

Then show one invoice and **stop for approval**:

```bash
cd ~/.claude/skills/invoice-parser-gen && python3 run.py sample <folder> --spec <name>
```

Present the ladder, the row classification, the header fields, and the first line
items. Confirm the printed total against the PDF itself, not against your own
parse. Ask the user to approve before writing anything.

**A new layout appears in a folder that already has a bound spec** — build a spec
for that cluster only, and ask approval for just the new one. Do not assume the
existing rules cover it.

## Ask before guessing

Ask the user only where the corpus is genuinely ambiguous, and ask in one batch:

- **Which total is the reconciliation target**, when several total-like labels
  exist. This is the highest-stakes question — `Total Account Balance` and
  `TOTAL AMOUNT DUE` include prior balances and are wrong, and picking the largest
  number is wrong on most invoices that have any aging.
- **$0.00 / no-charge rows** — keep or drop. Default to keeping them.
- **Tax** — its own column or a line item.
- **Several layout clusters** — one parser each, or is a subset not an invoice at
  all (aging reports and statements do turn up in invoice folders).

If the corpus answers the question, do not ask it.

## Scanned invoices

Files with no usable text layer are refused by default and listed in the
Exceptions sheet. To attempt OCR:

```bash
cd ~/.claude/skills/invoice-parser-gen && python3 run.py extract <folder> --ocr
```

Be honest in the report about what OCR did. Tesseract misreads digits *and*
labels, so OCR'd invoices frequently fail a rung and get flagged rather than
verified. That is the intended outcome, not a bug — never relax a tolerance to
make an OCR'd invoice pass.

## When you are done

Report:
- the summary table
- how many were verified out of how many
- every flagged invoice, with the specific rung that failed and the delta
- anything refused, and why
- the path to the spreadsheet

Never claim an invoice verified without the harness output showing it.
