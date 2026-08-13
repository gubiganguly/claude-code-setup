# HANDOFF.md template

Written for an AI agent with **no conversation history and no memory of this
project**. Competent, fast, completely uninformed.

Adapt the sections to the project. Drop what does not apply. Never pad a
section to look complete: an empty section is honest, a padded one misleads.

Target length is 150 to 400 lines. Past that, split into `context/knowledge/`
and link out. The handoff is a door, not a warehouse.

---

## The template

````markdown
# HANDOFF — <project name>

**Last checkpoint:** <YYYY-MM-DD>
**Status:** <one of: active / paused / blocked / shipped and maintained>
**Read time:** <n> minutes

> Start here. Read this whole file before touching anything. Follow the links
> only when you need the detail they hold.

## 1. What this is

Three to five sentences. What the project does, who it is for, and why it
exists. Plain language, no jargon a newcomer would not have.

Then one line on the shape of it:

**Type:** <web app / analytics engagement / CLI / library / pipeline>
**Stack:** <the four or five things that actually matter>
**Runs on:** <local only / deployed at URL / scheduled job / handed to client>

## 2. Where things stand right now

The most important section. Be specific and be honest.

**Working:**
- <feature>, verified <date>
- <feature>, verified <date>

**Partly done:**
- <thing>: <what exists, what is missing, and where the work stopped>

**Known broken:**
- <thing>: <symptom, what you know about the cause, why it was left>

**Not started but expected:**
- <thing>, and who is waiting on it

If someone stopped mid-task, say exactly where. "The migration script handles
the first two tables; the third has a column-type conflict that is unresolved"
is worth an hour of a reader's time.

## 3. Run it

Only commands you have actually executed. If one is untested, mark it.

```bash
# setup
<command>

# run locally
<command>

# tests
<command>
```

**Prerequisites:** <versions, tools, accounts, access that must exist first>

**Environment:** <which env vars are needed, where the real values come from.
Never paste secret values here.>

**Expected result:** <what a correct run looks like, so the reader can tell
whether it worked>

## 4. How it works

The mental model, not a file listing. A reader can run `ls` themselves; what
they cannot get from the filesystem is why the code is shaped this way.

- The main flow, end to end, in a few sentences or a small diagram
- The two or three decisions that explain most of the structure
- Where the real complexity lives, and why it is there

```
<a small ASCII diagram of the main flow, when it helps>
```

**Key files** — only the ones that matter, with why:

| Path | Why it matters |
|---|---|
| `<path>` | <the reason a reader would need to open it> |

For deeper detail, link out:
- Architecture: `docs/architecture.md`
- Domain knowledge: `context/knowledge/`
- Data model: `context/data-model/`

## 5. Conventions specific to this project

Only what is NOT obvious from the code or covered by the global CLAUDE.md.
Things a reasonable agent would otherwise get wrong.

- <convention, and the reason for it>
- <naming or structural pattern that must be followed>
- <the thing that looks wrong but is deliberate>

## 6. Traps

Every non-obvious thing that would cost the next agent time. This section
earns the whole document.

| Trap | What happens | What to do |
|---|---|---|
| <the trap> | <the symptom you would see> | <the fix or the avoidance> |

Examples worth capturing: a service that must start before another; an env var
whose name suggests the wrong thing; a test that fails for unrelated reasons; a
file that looks generated but is hand-edited; an API with an undocumented rate
limit; a dependency pinned for a non-obvious reason.

## 7. Adding a feature

One worked path through the codebase. Concrete beats abstract.

**To add a <typical unit of work for this project>:**

1. `<file>` — <what to change>
2. `<file>` — <what to change>
3. `<file>` — <what to change>
4. Run `<command>` to verify
5. <anything to update: docs, types, tests, migrations>

**Worked example:** <point at a recent commit or existing feature that followed
exactly this path, so the reader can copy a real one>

## 8. Do not

Things that look reasonable and are not. Each with its reason, because a rule
without a reason gets discarded the moment it becomes inconvenient.

- **Do not <action>.** <Why. What breaks.>
- **Do not <action>.** <Why. What breaks.>

## 9. Open questions

What is genuinely undecided, and who can settle it. Distinguish a question
needing a human from one the next agent can resolve by reading code.

| Question | Blocks | Who decides |
|---|---|---|
| <question> | <what is stuck behind it> | <person or "can be resolved from the code"> |

## 10. Next steps

Ordered. The first item should be genuinely the first thing to do.

1. <the single most valuable next action>
2. <next>
3. <next>

## 11. Facts and assumptions

Everything above that is inferred rather than verified, so the reader knows
which ground is solid.

**Verified:** <what was confirmed, and how>
**Assumed:** <what is believed but unconfirmed, and what would confirm it>
````

---

## Writing rules

Follow the global writing standards. Specifically here:

- **No em dashes.** Comma, colon, parentheses, or two sentences.
- **No filler.** Every line either orients the reader or is cut. No "this
  document aims to provide a comprehensive overview."
- **Second person, direct.** "Run this", "do not touch that."
- **Concrete over abstract.** "The seed script assumes an empty users table"
  beats "seeding has certain prerequisites."
- **Dates on anything perishable.** A status without a date is unreadable in
  three months.
- **Never invent.** If you did not verify it, label it or leave it out. The
  handoff's only value is that it can be trusted.

## Common failure modes

| Failure | Why it hurts |
|---|---|
| Restating the file tree | The reader can run `ls`. It burns their attention for nothing |
| Hiding the broken parts | The next agent finds them anyway, having wasted hours, and now distrusts the whole document |
| Untested commands | The reader's first action fails, and they stop believing the rest |
| Duplicating architecture docs | Two copies drift; the reader cannot tell which is current |
| Vague status ("mostly working") | Unactionable. Name what works and what does not |
| No date | The reader cannot judge whether any of it still holds |
