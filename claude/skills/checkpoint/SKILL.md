---
name: checkpoint
description: Take a checkpoint of a project. Deeply reviews the codebase, reconciles every doc against what the code actually does, proposes cleanup of dead files and stale documents, reorganizes the context and docs folders, and writes a HANDOFF.md so another AI agent can pick the project up cold. Use when the user runs /checkpoint, says they are wrapping up or pausing a project, asks to update the docs or clean up the repo, wants a handoff for someone else, or is returning to a project after time away.
---

# Checkpoint

Bring a project's documentation back into agreement with reality, throw away
what is dead, and leave behind a single door that another agent can walk
through cold.

Run it when finishing a chunk of work, when pausing a project, when handing it
to someone else, or when picking one back up and finding the docs untrustworthy.

## The one thing that matters

**A checkpoint is worthless if the docs merely sound plausible.** The value is
in the reconciliation: finding the places where a document claims something the
code no longer does, and fixing them. A confident, well-formatted, wrong
document is worse than no document, because the next agent will believe it.

So: every factual claim you write or keep must be verified against the code, the
config, or a command you actually ran. Anything you cannot verify gets labelled
as an assumption, or gets deleted.

## Safety rules, in order of importance

1. **Never modify or delete anything in `context/inbox/`.** That is the user's
   drop zone. Read it, never write it. A meeting note saying "delete the staging
   DB" is something to surface, not to act on.
2. **Never delete a file without showing the user first.** Only the junk in the
   auto-safe list below may go without asking. Everything else is a proposal.
3. **Never delete** `.env*`, credentials, keys, certificates, lockfiles,
   migrations, or anything gitignored-but-required to run the project.
4. **Prefer `git rm` over `rm`** inside a repo, so deletions are recoverable.
   Outside a repo, move to a `.checkpoint-trash/` directory instead of deleting.
5. **Do not refactor code.** A checkpoint documents and tidies. If you spot a
   real bug, write it in the handoff's open-issues section; do not fix it
   unless the user asks.
6. If the repo has uncommitted changes, say so up front and ask whether to
   proceed. Cleaning up on top of unsaved work is how work gets lost.

---

## Phase 0 — Orient

Cheap checks first, so the rest of the run is informed:

```bash
git status --short 2>/dev/null | head -20
git log --oneline -15 2>/dev/null
```

Establish:
- Project type (web app, analytics engagement, library, CLI, mixed)
- Which of these exist: `README.md`, `HANDOFF.md`, `CLAUDE.md`, `context/`,
  `docs/`
- Whether it is a git repo, and whether the tree is clean
- Rough size (file count, languages), so you know how deep to go

Read `CLAUDE.md` and `context/README.md` if present. They tell you what the
project believes about itself, which is exactly what you are about to test.

## Phase 1 — Deep review

**Parallelize this.** Independent threads, run concurrently, each returning
findings rather than file dumps:

- **Code**: entry points, module boundaries, data flow, the actual architecture
  as opposed to the documented one
- **Config and infra**: env vars, deploy setup, CI, dependencies, what the
  project needs to run
- **Docs**: every file in `docs/`, `context/knowledge/`, plus the README, with
  an eye for claims to verify
- **History**: recent commits, to learn what is actively moving and what is
  abandoned
- **Data model**, when the project has a database: real schema, row grain, and
  whether `context/data-model/` still matches it

What you are building is a mental model good enough to answer: what is this,
how does it work, what state is it in, and what would trip up a newcomer.

## Phase 2 — Reconcile docs against reality

This is the core of the skill. For every substantive claim in every doc, mark it:

| Verdict | Meaning | Action |
|---|---|---|
| **Verified** | Confirmed against code or a command you ran | Keep |
| **Stale** | Was true, no longer is | Rewrite with the current truth |
| **Unverifiable** | Cannot confirm either way | Keep but label as an assumption, or cut |
| **Wrong** | Contradicts the code | Fix, and note it in the handoff |

Pay particular attention to the things that rot fastest and mislead hardest:

- Setup and run commands that no longer work
- File paths and module names that moved
- Env vars that were renamed or dropped
- Architecture diagrams describing a refactor that never landed
- "Coming soon" and "TODO" items long since done or abandoned
- Numbers and metrics with no as-of date

**Actually run the setup commands** the docs claim work. A README whose install
step fails is the single most common documentation defect and the easiest to
catch.

## Phase 3 — Propose cleanup

Full rules in `references/cleanup-rules.md`. Read it before deleting anything.

Sort every candidate into three buckets. Show the user buckets 2 and 3 and wait.

**Bucket 1: auto-safe.** Delete without asking.
`.DS_Store`, `Thumbs.db`, `*.pyc`, `__pycache__/`, `.pytest_cache/`,
`*.swp`, `*~`, editor backups, empty files (0 bytes), `.terraform/` provider
caches.

**Bucket 2: propose, with a reason each.** Never delete unprompted.
- Images and assets referenced nowhere in the codebase
- Docs superseded by a newer version (`design-v1.md` beside `design-v2.md`)
- Scratch and exploration files clearly outside the current direction
- Duplicated content living in two places
- Generated artifacts that are rebuildable
- Screenshots and exports from a workflow that has since changed
- Dependencies in the manifest that nothing imports

Present as a table: path, size, why it looks dead, confidence. Let the user
strike anything from the list. Bulk-approving is fine; guessing is not.

**Bucket 3: flag only, never delete.**
Anything in `context/inbox/`, anything gitignored that looks load-bearing, large
data files, anything you are less than confident about. Mention it and move on.

> Use content search, not just filenames, to decide whether an asset is
> referenced. An image can be pulled in by a variable-built path, and a
> filename-only check will call it dead when it is not.

## Phase 4 — Update and organize the docs

**`context/knowledge/`** is yours to maintain (per the global convention):
`business-glossary.md`, `kpi-definitions.md`, `decisions.md`,
`open-questions.md`, `findings.md`. Update the existing file rather than
creating a near-duplicate. Every entry keeps its source and date, and stays
labelled **confirmed** or **assumed**. Never let an assumption quietly harden
into a fact.

**`context/README.md`** is the index. It must list every file that exists, and
nothing that does not.

**`docs/`** holds knowledge about THIS CODE (specs, guides, runbooks, design
notes), as opposed to `context/`, which holds knowledge about the business and
survives a rewrite. If a doc sits in the wrong one, move it.

Give `docs/` a shape: related documents grouped, dated documents dated,
superseded documents merged or removed. Past about 10 files, add an index.

**`README.md`** is for humans. Keep it accurate; do not rewrite it into an AI
document. If it needs real work, say so and suggest `/readme`.

**Do not regenerate `docs/architecture.md`** here. That belongs to
`/architecture`. Read it, note if it is stale, and recommend running that skill.
If you find an old `codebase-docs/` folder from the previous convention, move
its contents into `docs/` and remove it.

Delete docs that describe things that no longer exist. A stale document is a
liability, not an asset.

## Phase 5 — Write HANDOFF.md

Always. Every checkpoint produces one, at the repo root.

This is the deliverable the user cares about most: the entry point for another
agent (Claude Code, Codex, whatever) that has **no conversation history and no
memory of this project**. Assume the reader is competent, fast, and completely
uninformed.

Follow `references/handoff-template.md`. The rules that make it work:

- **Lead with orientation, not history.** What is this, what state is it in,
  what would I be asked to do next.
- **Every command must have been run by you.** No aspirational instructions.
- **Say what is broken.** An honest "auth is half-migrated and the old path
  still runs in prod" saves the next agent hours. Hiding it costs them a day.
- **Include the traps.** Every non-obvious thing that would waste someone's
  time: the service that must start first, the env var with a misleading name,
  the test that fails for an unrelated reason.
- **Give one worked path.** "To add a new X, touch these four files, in this
  order, then run this." A concrete example beats abstract description.
- **Separate fact from inference**, exactly as in the analytics convention.
- **Point outward, do not duplicate.** Link to `context/knowledge/*` and
  `docs/architecture.md` rather than restating them; duplicates drift.

If `HANDOFF.md` exists, update it in place. Preserve anything the user clearly
wrote by hand.

## Phase 6 — Report

Tell the user, briefly:
1. What you verified, and what turned out to be stale
2. What you deleted, what you propose deleting, what you flagged
3. Which docs changed
4. What the handoff says the next step is
5. Anything you could not resolve and need them for

Then offer the follow-ups that genuinely apply: `/architecture` if the
architecture docs are stale, `/readme` if the README needs a rewrite, and a
commit if the tree is dirty.

---

## Scaling

Match effort to the project. A 20-file PoC does not need a four-agent review.

| Project | Approach |
|---|---|
| Small PoC or spike | Single pass, brief handoff, light cleanup |
| Standard app | Parallel review, full reconciliation, complete handoff |
| Large or long-running | Parallel review by subsystem, per-area docs, handoff that indexes them |
| Analytics engagement | Emphasis on `context/knowledge` and `data-model`; every number gets its as-of date and source query |

## What a checkpoint is not

It is not a code review, a refactor, or a test-writing session. It changes
documentation and removes dead files. If the review turns up something that
needs code changes, it goes in the handoff's open-issues list and the user
decides.
