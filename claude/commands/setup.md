Create a `.claude` folder in the current project root with the following files:

## 1. `.claude/CLAUDE.md`

The global `~/.claude/CLAUDE.md` already defines the standard stack and folder
structure (Next.js frontend, FastAPI backend, Expo mobile) — do NOT repeat any of
that here. This file is only for what's unique to THIS project.

Look briefly at the repo (README, package.json, requirements, env examples) and
create the file with this skeleton, filling in what you can and leaving concise
TODO placeholders for what you can't:

```markdown
# CLAUDE.md — Project Rules

> Layers on top of the global `~/.claude/CLAUDE.md` (stack + folder conventions live there).

## What this project is
<one or two sentences>

## Running it
<dev-server commands, ports, anything non-obvious>

## Environment / secrets
<which env files exist, where secrets come from — never values>

## Design Context
<Answers to the two kickoff questions from the global CLAUDE.md Design
Workflow section. Leave as TODO if not yet asked.>

- **Workflow depth**: TODO — Full | Standard | Minimal
- **Brand identity**: TODO — SNH "The Ledger" (`snh-ledger` plugin) | own identity
- **Identity kit**: TODO — display + UI font, accent (OKLCH), neutral tint,
  light/dark strategy, icon set, motion personality
- **Approved design direction**: TODO — filled in after mockup approval (Full tier)

## Project-specific gotchas
<anything that deviates from the global conventions; delete if none>
```

## 2. `.claude/settings.local.json`

Create this file with exactly this content:

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

## 3. The `/context` folder

Every project gets one (see the Context Folder section in the global
`~/.claude/CLAUDE.md`). Create this structure at the repo root, with a
`.gitkeep` in each empty directory so the layout survives a clone:

```
/context
  README.md
  /inbox                       # User drop zone — raw notes, transcripts, emails
  /knowledge                   # Claude-maintained derived knowledge
```

For projects with a database, also create `/context/data-model`.

Write `/context/README.md` with this content, adjusted to the project:

```markdown
# Context

Shared memory for this project.

## `/inbox` — yours

Drop anything relevant in here raw: meeting notes, call transcripts,
forwarded emails, PDFs, spreadsheets, screenshots. No naming convention or
cleanup needed. Claude reads from here and never edits or deletes it.

## `/knowledge` — Claude's

Durable knowledge Claude derives and maintains: business glossary, KPI
definitions, decision log, open questions, findings. Every entry is dated,
names its source, and is marked confirmed (by a human) or assumed (by Claude).

## Index

<one line per file as they get created>

## Not committed

<list any gitignored files here — raw exports, anything with PII or
credentials — so their existence is known even though the data isn't in git>
```

Add to the project `.gitignore` (create it if missing) so sensitive raw
context never gets committed:

```
context/inbox/*.csv
context/inbox/*.xlsx
```

## Instructions

- Create the `.claude` and `/context` directories if they don't exist
- If any file already exists, ask the user before overwriting
- Never overwrite or delete anything already in `/context/inbox`
- After creating the files, confirm what was created
