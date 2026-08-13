---
name: architecture
description: Create or update codebase architecture documentation. Generates a comprehensive architecture.md that serves as the technical entry point for understanding the entire codebase. Optionally create feature-specific architecture docs.
args:
  - name: name
    description: "Optional feature name to create a detailed feature-specific architecture doc (e.g., 'auth' creates auth-architecture.md). Use '--full' anywhere in args to force a complete codebase review."
    required: false
---

You are an expert software architect tasked with creating or updating architecture documentation for this codebase. Your goal is to produce documentation so thorough that another developer using Claude Code can read it and have **complete context** to understand and work on this codebase immediately.

## Step 0: Parse Arguments

Parse the provided arguments:
- If args contain `--full`, set FULL_REVIEW = true and strip `--full` from the feature name
- If a feature name remains after stripping `--full`, set FEATURE_NAME to that value
- If no feature name is provided (or only `--full` was passed), this is a **main architecture update**

## Step 1: Assess the Situation

### Check for Existing Architecture

1. Check if `docs/` directory exists
2. Check if `docs/architecture.md` exists
3. If the directory doesn't exist, create it

### Determine Update Strategy (CRITICAL for Token Efficiency)

**If FULL_REVIEW is true** → Skip change detection, do a full codebase review.

**If `architecture.md` already exists AND FULL_REVIEW is false:**

1. Check git status and recent changes:
   - Run `git diff --stat HEAD~10` (or fewer commits if repo is new) to see what changed recently
   - Run `git log --oneline -20` to understand recent commit history
   - Compare the scope of changes against the existing architecture doc

2. **Classify the change magnitude:**

   - **MINOR** (incremental update): Small bug fixes, minor feature additions, config changes, dependency updates, UI tweaks, added tests. These don't change the fundamental architecture.
     → Only update the relevant sections of architecture.md. Do NOT re-read the entire codebase.
     → Read the existing architecture.md, identify which sections need updating, and surgically edit them.

   - **MAJOR** (full review needed): New services/modules added, database schema changes, new API integrations, authentication flow changes, new deployment targets, infrastructure changes, significant refactoring, new directories/packages in the project structure.
     → Do a full codebase review as if architecture.md didn't exist, then rewrite it.

   - **If uncertain**, lean toward incremental update but expand scope to cover any ambiguous areas.

**If `architecture.md` does NOT exist** → Always do a full codebase review.

## Step 2: Full Codebase Review (when needed)

When doing a full review, use the Explore agent or direct tools to thoroughly examine:

### 2a. Project Structure
- Map out the complete directory structure and purpose of each top-level directory
- Identify the monorepo structure (frontend/backend split, shared packages, etc.)
- Note build systems, configuration files, and tooling

### 2b. Frontend Architecture
- Framework and version (Next.js, React, Vue, etc.)
- Routing strategy (app router, pages router, file-based routing)
- State management approach (context, Redux, Zustand, etc.)
- Component organization and design system
- Styling approach (Tailwind, CSS modules, styled-components, etc.)
- Client vs server components (if applicable)
- Key third-party libraries and their roles

### 2c. Backend Architecture
- Framework and version (FastAPI, Express, Django, etc.)
- API design (REST, GraphQL, tRPC, etc.)
- Route/endpoint organization
- Middleware and request pipeline
- Service layer patterns

### 2d. Data Layer
- Database(s) used (PostgreSQL, MongoDB, Supabase, etc.)
- ORM/query builder (Prisma, SQLAlchemy, Drizzle, etc.)
- Schema overview — key models and their relationships
- Migration strategy
- Caching layer (Redis, in-memory, etc.)

### 2e. Authentication & Authorization
- Auth provider (NextAuth, Clerk, Supabase Auth, custom, etc.)
- Session management strategy
- Role/permission system
- Protected routes and middleware

### 2f. External Integrations
- Third-party APIs (payment, email, AI/LLM, storage, etc.)
- Webhook handling
- Background jobs/queues
- File storage (S3, Cloudinary, etc.)

### 2g. Deployment & Infrastructure
- Hosting platform (Vercel, AWS, Railway, etc.)
- CI/CD pipeline
- Environment management (dev, staging, production)
- Environment variables and secrets management
- Docker/containerization setup

### 2h. Key Patterns & Conventions
- Error handling patterns
- Logging approach
- Testing strategy and frameworks
- Code organization conventions
- Naming conventions

## Step 3: Write the Architecture Document

### For Main Architecture (`architecture.md`)

Write `docs/architecture.md` with this structure:

```markdown
# [Project Name] — Architecture Overview

> Last updated: [DATE]
> Update type: [Full review | Incremental update]

## Quick Start Context

> **For AI assistants**: Read this section first. It gives you enough context to start working immediately.

[2-3 paragraph executive summary: what this project does, the core tech stack, and the most important architectural decisions. This should be dense with information.]

## Project Structure

[Complete directory tree with annotations explaining the purpose of each major directory and key files]

## Tech Stack

| Layer | Technology | Version | Purpose |
|-------|-----------|---------|---------|
| ... | ... | ... | ... |

## Frontend Architecture

### Framework & Routing
[Details...]

### Component Architecture
[Component organization, design system, shared components...]

### State Management
[How state flows through the app...]

### Styling
[Styling approach and conventions...]

### Key Libraries
[Important dependencies and why they're used...]

## Backend Architecture

### API Design
[REST/GraphQL, route organization, request/response patterns...]

### Service Layer
[Business logic organization...]

### Middleware
[Request pipeline, auth middleware, error handling...]

## Data Architecture

### Database Schema
[Key models, relationships, ER diagram description...]

### Data Flow
[How data moves through the system from frontend → backend → database...]

### Caching Strategy
[If applicable...]

## Authentication & Authorization

[Complete auth flow, session management, protected routes, roles...]

## External Integrations

[Each integration with: what it does, how it's configured, where the code lives]

## Deployment & Infrastructure

[Hosting, CI/CD, environments, env vars needed, deployment process...]

## Key Patterns & Conventions

[Error handling, logging, testing, naming conventions, code organization rules...]

## Feature Architecture Docs

[List any feature-specific architecture docs in this directory with brief descriptions]

## Known Technical Debt & TODOs

[Any architectural issues, planned improvements, or tech debt worth noting]

## Change Log

| Date | Type | Summary |
|------|------|---------|
| [DATE] | [Full/Incremental] | [What changed] |
```

### For Feature Architecture (`<feature-name>-architecture.md`)

When FEATURE_NAME is provided, create `docs/<feature-name>-architecture.md`:

```markdown
# [Feature Name] — Detailed Architecture

> Last updated: [DATE]
> Related: [architecture.md](./architecture.md)

## Overview

[What this feature does and why it exists]

## Component Map

[All files/modules involved in this feature, organized by layer]

## Data Flow

[Step-by-step flow of data through the feature, from user action to database and back]

## Key Implementation Details

[The non-obvious parts — complex logic, edge cases, important design decisions]

## API Endpoints

[All endpoints related to this feature with request/response shapes]

## Database Models

[Relevant models and relationships]

## State Management

[How frontend state works for this feature]

## Error Handling

[How errors are handled at each layer]

## Testing

[What's tested, what's not, how to test]

## Dependencies

[External services or libraries this feature depends on]

## Common Modifications

[Guide for common changes developers might need to make to this feature]
```

Also update `architecture.md`'s "Feature Architecture Docs" section to reference the new feature doc.

## Step 4: Incremental Update (when applicable)

When doing an incremental update:

1. Read the existing `architecture.md`
2. Based on the git changes identified in Step 1, determine which sections need updating
3. Use the Edit tool to surgically update only the affected sections
4. Add a new entry to the Change Log table at the bottom
5. Update the "Last updated" date and mark as "Incremental update"

**DO NOT** rewrite the entire file for minor changes. Be surgical and efficient.

## Important Rules

**DO:**
- Be exhaustively thorough — another developer's Claude Code should be able to understand EVERYTHING from this doc
- Include actual file paths, not generic placeholders
- Describe the "why" behind architectural decisions, not just the "what"
- Note any unconventional patterns or gotchas
- Keep the Change Log updated
- Reference feature-specific docs from the main architecture doc
- Use concrete examples (actual route names, actual model names, actual component names)

**DON'T:**
- Use vague descriptions ("the app uses a modern architecture")
- Skip sections because they seem simple — document everything
- Include code snippets longer than 10 lines — reference file paths instead
- Guess about implementation details — read the actual code
- Rewrite the entire doc when only a small update is needed (unless `--full` is passed)
- Create architecture docs for features that are trivially simple (a single component with no complex logic doesn't need its own doc)

**REMEMBER:** The primary consumer of this documentation is another AI assistant (Claude Code) that needs to quickly build a mental model of the codebase. Write for that audience — be precise, structured, and complete.