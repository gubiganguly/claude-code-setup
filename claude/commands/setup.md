---
name: setup
description: Scaffold a project's documentation skeleton — the context and docs folders, a project-level CLAUDE.md, and local permissions. Run once at the start of a project, or on an existing project that never got one.
args:
  - name: flags
    description: "Use '--minimal' for a spike or throwaway (skips docs/ and the Design Context block)."
    required: false
---

Set up this project's documentation skeleton so there is always an obvious place
for knowledge to land.

**What you create:** the `context/` and `docs/` folders, a project-level
`CLAUDE.md`, and `.claude/settings.local.json`.

**What you do NOT create:** `HANDOFF.md`, `README.md`, or `docs/architecture.md`.
Those describe a project that exists; this runs before there is much to describe.
They come from `/checkpoint`, `/readme`, and `/architecture` once there is code.

---

## Step 0 — Look before you write

Read what is already here: `README.md`, `package.json`, `requirements.txt`,
`.env.example`, and any existing `CLAUDE.md`. You are filling in real details,
not emitting a template with TODOs everywhere.

Note whether the project has a database. It changes what you create.

**If a file already exists, do not overwrite it.** Show the user what you would
change and ask. This command is run on existing projects too.

## Step 1 — `context/`

Business knowledge that survives the code being rewritten. Every project gets
one, even a data-reporting engagement with no application code.

```
context/
  README.md
  inbox/         .gitkeep      user drop zone
  knowledge/     .gitkeep      Claude-maintained
  data-model/    .gitkeep      only if the project has a database
```

`.gitkeep` in each empty directory so the layout survives a clone.

`context/README.md`:

```markdown
# Context

Business knowledge for this project. Survives the code being rewritten.
For knowledge about the code itself, see `docs/`.

## `inbox/` — yours

Drop anything relevant here raw: meeting notes, call transcripts, forwarded
emails, PDFs, spreadsheets, screenshots. No naming or cleanup needed. Claude
reads from here and never edits or deletes what you put in it.

## `knowledge/` — Claude's

Durable knowledge derived and maintained by Claude: business glossary, KPI
definitions, decision log, open questions, findings. Every entry is dated,
names its source, and is marked **confirmed** (by a human) or **assumed**
(by Claude).

## Index

<one line per file, added as files are created>

## Not committed

<list gitignored files here — raw exports, anything with PII or credentials —
so their existence is known even though the data is not in git>
```

## Step 2 — `docs/`

Knowledge about *this code*: specs, guides, runbooks, design notes. Skip on
`--minimal`.

Create the directory with a `.gitkeep`. Do not invent documents. If the project
already has scattered docs (a stray `codebase-docs/`, a `docs/` inside
`backend/`), note it and suggest `/checkpoint` to consolidate rather than moving
things yourself.

## Step 3 — Project `CLAUDE.md`

At the repo root, unless `.claude/CLAUDE.md` already exists, in which case
update that one instead.

**Only what is unique to THIS project.** The global `~/.claude/CLAUDE.md`
already covers the stack, folder conventions, security baseline, design
standards, and writing rules. Repeating any of it means two copies that will
disagree within a month.

```markdown
# CLAUDE.md — <project name>

> Layers on top of the global `~/.claude/CLAUDE.md`. Stack, security, design,
> and writing conventions live there and are not repeated here.

## What this is
<one or two sentences a newcomer would understand>

## Running it
<dev-server commands, ports, anything non-obvious. Only commands you verified.>

## Environment
<which env files exist and where the real values come from. Never values.>

## Design Context
<From the two kickoff questions in the global Design Workflow section.
Omit this whole block on --minimal.>

- **Workflow depth**: TODO — Full | Standard | Minimal
- **Brand identity**: TODO — SNH "The Ledger" (`snh-ledger`) | own identity
- **Identity kit**: TODO — display + UI font, accent (OKLCH), neutral tint,
  light/dark strategy, icon set, motion personality

## Gotchas
<anything that deviates from the global conventions. Delete if none.>
```

Fill in what you can from Step 0. Leave a short TODO for what genuinely needs
the user, and tell them which ones at the end.

If the project type makes the Design Context obvious, infer it and say so:
PoC or spike → Minimal, internal tool → Standard, user-facing product → Full.
Internal or SNH-facing → The Ledger. Portco or client-facing → own identity.

## Step 4 — `.claude/settings.local.json`

Only if it does not already exist. A starting allowlist so routine work stops
prompting:

```json
{
  "permissions": {
    "allow": [
      "Bash(python3 -m venv:*)",
      "Bash(source:*)",
      "Bash(python3:*)",
      "Bash(pip install:*)",
      "Bash(pip3 install:*)",
      "Bash(pip freeze:*)",
      "Bash(pip3 freeze:*)",
      "Bash(python -m uvicorn:*)",
      "Bash(npm run dev:*)",
      "Bash(npm install:*)",
      "Bash(npm run build:*)",
      "Bash(npx prisma:*)",
      "Bash(chmod:*)",
      "Bash(brew install:*)",
      "Bash(brew services start:*)",
      "Bash(brew services stop:*)",
      "Bash(psql:*)",
      "Bash(createdb:*)",
      "Bash(tee:*)",
      "Bash(tree:*)",
      "Bash(lsof:*)",
      "Bash(kill:*)",
      "Bash(xargs kill:*)",
      "Bash(open:*)"
    ]
  }
}
```

## Step 5 — `.gitignore`

Create or extend. The point is that raw context and secrets never get
committed, while definitions and findings do.

```gitignore
# Raw context — may contain client data, PII, or credentials.
# Definitions and findings in context/knowledge/ ARE committed.
context/inbox/*
!context/inbox/.gitkeep
!context/inbox/*.md

# Secrets
.env
.env.*
!.env.example
```

Keep `.md` files in the inbox trackable, since meeting notes are usually safe
and useful to share. Anything with real client data belongs in one of the
excluded formats, or should be added explicitly.

If the repo already has a `.gitignore`, append only what is missing.

## Step 6 — Report

Say what you created, what you skipped because it already existed, and list the
TODOs that need the user. If the project has scattered docs that want
consolidating, mention `/checkpoint`.

---

## Rules

- Never overwrite an existing file without asking
- Never touch anything already in `context/inbox/`
- Do not invent documentation for code that does not exist yet
- Do not repeat anything the global CLAUDE.md already says
- Every command you write into the project CLAUDE.md must be one you ran
