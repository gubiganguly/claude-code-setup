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

## Instructions

- Create the `.claude` directory if it doesn't exist
- If either file already exists, ask the user before overwriting
- After creating the files, confirm what was created
