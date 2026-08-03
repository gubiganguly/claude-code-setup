---
name: readme
description: Create or update a polished, human-friendly README.md at the project root. Reads existing architecture docs for context and produces a clear, scannable README meant for humans first, with an AI assistant entry point at the bottom.
args:
  - name: flags
    description: "Use '--full' to force a complete rewrite even if README.md already exists."
    required: false
---

You are a technical writer creating a README that is **clear, scannable, and welcoming**. The README is the front door of this project — it should make a human feel oriented within 30 seconds of reading.

## Step 0: Parse Arguments

- If args contain `--full`, set FULL_REWRITE = true
- Otherwise, FULL_REWRITE = false

## Step 1: Gather Context

### Read Architecture Docs (Primary Source)

1. Check if `codebase-docs/architecture/architecture.md` exists
   - If it exists, read it thoroughly — this is your **primary source of truth** for understanding the project
   - Extract: project purpose, tech stack, features, project structure, setup requirements, deployment info
2. Check for any feature-specific architecture docs in `codebase-docs/architecture/`
   - Note their names — you'll reference them in the AI section

### Read Existing Files

3. Check if `README.md` already exists at the project root
   - If it exists and FULL_REWRITE is false, read it and do an **incremental update** (preserve any custom sections the user may have added, update outdated info)
   - If it exists and FULL_REWRITE is true, rewrite from scratch
4. Read `package.json`, `pyproject.toml`, `requirements.txt`, or similar to confirm tech stack and available scripts
5. Check for `.env.example` or `.env.local.example` to understand required environment variables
6. Check for `docker-compose.yml`, `Dockerfile`, `Makefile`, or similar to understand setup/run methods
7. Check for `CLAUDE.md` or `.claude/CLAUDE.md` for project conventions

### If No Architecture Docs Exist

If there are no architecture docs, do a **light codebase scan** to understand:
- What the project does (check app entry points, landing pages, API routes)
- Tech stack (check configs, package files, framework indicators)
- Project structure (top-level directory layout)

Do NOT do a full architecture review — that's what `/architecture` is for. Gather just enough to write a good README.

## Step 2: Write the README

Write `README.md` at the project root with the following structure. **Every section should be concise and scannable.** Use short paragraphs, bullet points, and tables. No walls of text.

### Writing Style Rules

- **Conversational but professional** — not dry, not overly casual
- **Short sentences** — if a sentence has a comma, consider splitting it
- **Bullet points over paragraphs** — whenever listing more than 2 things
- **Tables for structured info** — tech stack, env vars, scripts
- **Headers for scanability** — a reader skimming headers should understand the project
- **No filler** — every sentence should carry information. Cut "This project is a..." type openers
- **Concrete over abstract** — "Processes PDF invoices using GPT-4" not "Leverages AI for document processing"

### README Structure

```markdown
# [Project Name]

[One-liner: What this project does in plain English. Max 15 words.]

[Optional: 2-3 sentence expanded description if the one-liner isn't enough. What problem does it solve? Who is it for?]

## Features

- **[Feature name]** — [What it does in one sentence]
- **[Feature name]** — [What it does in one sentence]
- ...

[Keep this to the most important 5-8 features. Not an exhaustive list.]

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | [e.g., Next.js 14, TypeScript, Tailwind CSS] |
| Backend | [e.g., FastAPI, Python 3.11] |
| Database | [e.g., PostgreSQL via Supabase] |
| Auth | [e.g., Clerk] |
| Deployment | [e.g., Vercel + Railway] |

## Getting Started

### Prerequisites

- [e.g., Node.js 18+]
- [e.g., Python 3.11+]
- [e.g., PostgreSQL / Docker]

### Setup

[Step-by-step setup instructions. Number each step. Include actual commands.]

1. **Clone the repo**
   ```bash
   git clone <repo-url>
   cd <project-name>
   ```

2. **Install dependencies**
   ```bash
   # Frontend
   cd frontend && npm install

   # Backend
   cd backend && python -m venv venv && source venv/bin/activate && pip install -r requirements.txt
   ```

3. **Configure environment**
   ```bash
   cp .env.example .env
   ```
   [List the key env vars that need to be set, with brief descriptions]

4. **Run the app**
   ```bash
   # Frontend
   npm run dev

   # Backend
   uvicorn src.main:app --reload
   ```

[Adapt these steps to the ACTUAL project setup. Don't guess — read the actual config files.]

### Available Scripts

| Command | Description |
|---------|-------------|
| `npm run dev` | Start frontend dev server |
| `npm run build` | Production build |
| ... | ... |

[Only include scripts that actually exist in the project.]

## Project Structure

```
[Simplified directory tree — show top 2 levels max, annotate key directories]
├── frontend/          # Next.js application
│   ├── app/           # Pages and API routes
│   ├── components/    # React components
│   └── lib/           # Utilities and configs
├── backend/           # FastAPI server
│   ├── src/           # Source code
│   └── requirements/  # Python dependencies
└── codebase-docs/     # Architecture documentation
```

[This should be a simplified, human-friendly version. Not exhaustive.]

## Architecture Overview

[2-4 paragraphs giving a high-level overview of how the system works. Think: "If I had to explain this to a new team member in 2 minutes, what would I say?"]

[Cover the main data flow: User does X → Frontend sends Y → Backend does Z → Database stores W]

[Mention any non-obvious architectural decisions briefly.]

> For a deep dive into the architecture, see [`codebase-docs/architecture/architecture.md`](codebase-docs/architecture/architecture.md).

## Contributing

[Keep this brief — 3-5 bullet points on conventions]

- [Branch naming, PR process, etc.]
- [Code style / linting requirements]
- [Testing expectations]

[If the project has a CONTRIBUTING.md, reference it instead of duplicating.]

---

## For AI Assistants

> **If you're Claude Code (or another AI assistant) trying to understand this codebase, start here.**

### Entry Point

Read [`codebase-docs/architecture/architecture.md`](codebase-docs/architecture/architecture.md) first. It contains:
- Complete project structure with file-level annotations
- Frontend and backend architecture details
- Database schema and data flow
- Authentication and authorization flows
- External integrations and API documentation
- Deployment and infrastructure setup
- Code patterns and conventions

### Feature-Specific Docs

[List any feature architecture docs that exist, e.g.:]
- [`auth-architecture.md`](codebase-docs/architecture/auth-architecture.md) — Authentication and authorization deep dive
- ...

[If no feature docs exist, omit this subsection.]

### Project Conventions

[Reference CLAUDE.md if it exists:]
- See [`.claude/CLAUDE.md`](.claude/CLAUDE.md) for project-specific coding conventions and rules

### Quick Context

- **Monorepo**: `frontend/` (Next.js) + `backend/` (FastAPI)
- **[Any other one-liner context an AI needs to know immediately]**
```

## Step 3: Incremental Updates

When README.md already exists and FULL_REWRITE is false:

1. Read the existing README
2. Check if architecture docs have been updated since the README was last modified
3. Check git changes for anything that would affect the README (new features, changed setup, new dependencies)
4. **Preserve any custom sections** the user has added that don't match the template above
5. Surgically update only what's changed using the Edit tool
6. If nothing meaningful has changed, tell the user the README is already up to date — don't make pointless edits

## Important Rules

**DO:**
- Make the README something a human would actually enjoy reading
- Use real project names, real commands, real file paths — never placeholders
- Test that setup instructions would actually work by checking the files they reference
- Keep the "For AI Assistants" section at the very bottom — humans come first
- Adapt the template to the project — skip sections that don't apply, add sections that do

**DON'T:**
- Write a novel — the whole README should be readable in under 3 minutes
- Include implementation details — that's what architecture docs are for
- Guess about setup steps — read the actual config files and scripts
- Add badges, shields, or decorative elements unless the project already has them
- Use corporate buzzwords ("leverage", "utilize", "streamline", "cutting-edge")
- Put the AI section prominently — it should be at the bottom, after the human-readable content