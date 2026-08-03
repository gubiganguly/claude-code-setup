---
description: Report what an invoice folder contains, which parser is bound, what is extracted and what is flagged. Read-only.
argument-hint: [folder path] (defaults to ./invoices, or the current directory)
---

Report the state of the invoice folder: **$ARGUMENTS**

If no folder was given, look for `./invoices`, then `./Invoices`, then the current
directory.

This command is **read-only**. Do not extract, do not write a spreadsheet, do not
create or modify a spec. If the user seems to want extraction, tell them to run
`/invoice-extract` rather than doing it here.

```bash
cd ~/.claude/skills/invoice-parser-gen && python3 run.py status <folder>
```

Then profile the folder so the report covers files that have never been
extracted:

```bash
cd ~/.claude/skills/invoice-parser-gen && python3 -c "
import sys, glob; sys.path.insert(0,'.')
from engine.text import load
from engine.profile import profile, cluster
import os
folder = '<folder>'
paths = sorted(set(glob.glob(os.path.join(folder,'*.pdf'))) | set(glob.glob(os.path.join(folder,'*.PDF'))))
profs = {}
for p in paths:
    try: profs[os.path.basename(p)] = profile(load(p))
    except Exception as e: print('unreadable:', os.path.basename(p), e)
for sig, names in cluster(profs).items():
    p = profs[names[0]]
    state = 'usable' if p.usable_text else ('annotation-only' if p.annotation_only else 'needs OCR')
    print(f'{len(names):5d} files  sig={sig}  {state:16s} {p.chars_per_page:7.0f} chars/pg  {p.generator[:60]}')
"
```

Report as a short table:

- total PDFs, how many recorded, how many new
- which spec is bound to which layout signatures
- layout clusters found, and whether each has a usable text layer
- flagged invoices, each with the rung that failed
- anything unreadable or refused

Call out two things explicitly if present:

- **A layout cluster with no bound spec** — those invoices are not being
  extracted, and a re-run will not pick them up until a spec is built.
- **Annotation-only files** — these have a text layer made of AP sticky notes over
  a scan. They are not extractable without OCR and must never be counted as
  successfully processed.

Finish with the single most useful next action, and nothing more.
