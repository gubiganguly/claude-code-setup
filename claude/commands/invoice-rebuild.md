---
description: Re-derive an invoice folder's parser after a vendor changes their template, then re-verify without losing existing rows
argument-hint: [folder path] (defaults to ./invoices, or the current directory)
---

Re-derive the parser for: **$ARGUMENTS**

Use this when a vendor has changed their invoice template, when a spec is
producing wrong or flagged output, or after the engine has changed and the folder
needs re-verifying.

If no folder was given, look for `./invoices`, then `./Invoices`, then the current
directory.

Invoke the `invoice-parser-gen` skill first so its workflow and hard rules are
loaded.

## Establish what is actually wrong before changing anything

```bash
cd ~/.claude/skills/invoice-parser-gen && python3 run.py status <folder>
```

Then re-parse the whole folder against the currently bound spec and look at the
failures. Do not start editing until you can state which rung fails on which
invoices and by how much. `engine.reconcile.diagnose` maps a delta to likely
causes: short means something is not captured, over means something is counted
twice.

Two distinctions to make before you touch the spec:

- **A new layout, or the same layout parsed wrongly?** Compare layout signatures
  against the bindings. A new signature means a template change and a new cluster,
  not a broken rule.
- **A parser bug, or the vendor's own arithmetic?** Vendors do print wrong
  subtotals — one reference vendor's `Total Court Fees` is $82 off while its grand
  total is correct. If the vendor is wrong, make that rung advisory and report the
  discrepancy. Do not bend the parser until it agrees with a bad number.

## Rebuild

Fix the spec. If the engine cannot express what the vendor needs, that is a
missing general capability — change the engine, then re-run every other spec's
regression before continuing. Never special-case one vendor inside the engine.

Iterate until unclassified is zero and every required rung passes across the whole
folder.

Then show one invoice and **stop for approval**:

```bash
cd ~/.claude/skills/invoice-parser-gen && python3 run.py sample <folder> --spec <name>
```

## Re-extracting safely

`extract` is append-only and skips invoices already in the sheet, so it will not
re-process anything on its own. To genuinely re-extract after a spec fix, the
existing rows must go first:

```bash
# inspect before removing anything
ls -la <folder>/.invoice-parser/ <folder>/*.xlsx
```

Before deleting or moving either the sheet or `.invoice-parser/`, tell the user
what you found and what will be lost — the `Notes` column is user-typed and is
not recoverable from the store. Get explicit confirmation. If they want the notes
preserved, copy them out first and say how you will restore them.

The store can rebuild a deleted sheet, but a deleted store cannot rebuild
user-typed notes.

## Report

- what was wrong, and which rung proved it
- what changed, in the spec or the engine
- regression results for every other spec, if the engine changed
- before-and-after verified counts
- anything still flagged, and whether it is the parser or the vendor
