# CLAUDE.md — Global Rules

> Shared conventions across all projects. Project-level `.claude/CLAUDE.md` files layer on top.

---

## Monorepo Structure

Projects use a split at the repo root based on what they include:

```
/frontend                      # Next.js web app (TypeScript)
/backend                       # Python backend (FastAPI)
/mobile                        # React Native mobile app (Expo + TypeScript)
```

Not every project has all three. Only include sections relevant to the repo.

---

## Tech Stack & Deployment Standards

- **Frontend**: Next.js (TypeScript, App Router)
- **Backend**: Python FastAPI
- **Database**: PostgreSQL — always. Locally via Homebrew Postgres; in production
  via AWS RDS PostgreSQL. Don't introduce other databases without asking.
- **Hosting**: AWS (account 346698404534, default region `us-east-1`), App Runner
  for containers, RDS for the database, Terraform for infra, GitHub Actions + OIDC
  for CI/CD.
- **Deploying**: use the `/deploy` skill. First deploy = `terraform apply`; every
  deploy after = `git push`. Never hand-roll AWS infra outside that pattern.
- **Domains**: every deployed app gets `<project>.apps.snhcap.com` (Route 53
  zone owned by the platform stack, delegated from GoDaddy; certificates
  auto-issued/renewed). Always share and report the branded URL — never the raw
  `*.awsapprunner.com` one, which Microsoft Defender flags as suspicious.
- **Shared platform**: small projects deploy in the skill's SHARED mode onto the
  standing platform stack at `~/Development/aws-platform` (shared VPC/NAT +
  `platform-db` RDS + `platform-shared` App Runner connector, ~$5/mo per project).
  Never `terraform destroy` the platform stack — all shared-mode databases live
  on it. Dedicated mode (own VPC+RDS) is only for isolation-sensitive apps.

---

## Authentication & User Management (every application)

Every application we build ships with this baseline — don't ask, just include it:

- **Auth**: JWT-based authentication.
- **Seed admin**: the first user is always `admin@snhcap.com` / `admin123!`,
  created by an idempotent seed. This account must ALWAYS have the admin role —
  never allow it to be demoted or deleted.
- **Password change**: every app includes an easy, discoverable change-password
  flow (e.g. in account/settings).
- **RBAC**: role-based access control in every app, with admin UI to add/remove
  users and assign roles.

---

## UI & Design Standards (every application)

- **Look and feel**: intuitive, clean, and professional — but not boring.
  Be creative; use tasteful animations and micro-interactions where they add
  polish, never where they slow the user down.
- **Zero-training usability**: someone who has never seen the app should be
  able to open it and understand what's going on. Prefer obvious labels, clear
  empty states, and visible affordances over cleverness.
- **Info icons**: wherever something needs explanation — especially calculations,
  derived numbers, or non-obvious fields — add an info icon (tooltip/popover)
  that explains it in plain language.

---

## Web Frontend Structure (`/frontend`)

```
/app
  /api                         # Next.js API routes (Route Handlers)
    /route-name
      route.ts
  /page-name
    page.tsx                   # Page component
    layout.tsx                 # Optional layout for this route
    loading.tsx                # Optional loading UI
    error.tsx                  # Optional error boundary
  layout.tsx                   # Root layout
  page.tsx                     # Home page
  globals.css                  # Global styles (Tailwind directives)

/components
  /ui                          # Base reusable primitives (Button, Input, Card, Modal, etc.)
  /layout                      # Layout components (Navbar, Sidebar, Footer, PageWrapper)
  /page-name                   # Page-specific components grouped by feature

/lib                           # Shared utilities, helpers, and client configs
  utils.ts
  constants.ts

/hooks                         # Custom React hooks

/types                         # Shared TypeScript types and interfaces

/public                        # Static assets (images, fonts, icons)
```

---

## Backend Structure (`/backend`)

```
/requirements
  requirements.txt

/src
  /api
    /route-name
      route.py
  /services
    /service-name
      openai_service.py        # (or other LLM/service files)
  /schemas
    schema_name.py
  /core
    config.py
  /utils
    helpers.py

/venv                          # Virtual environment (gitignored)

/scripts
  /tests
    test_name.py
  /db-discovery                # If database discovery is needed
```

---

## Mobile App Structure (`/mobile`)

Uses Expo (managed workflow) with Expo Router for file-based navigation.

```
/app                            # Expo Router file-based routing
  /(tabs)                       # Tab navigator group
    _layout.tsx                 # Tab bar configuration
    index.tsx                   # Home tab
    settings.tsx                # Additional tabs
  /(auth)                       # Auth flow group
    _layout.tsx                 # Auth stack layout
    login.tsx
    register.tsx
  /screen-name                  # Nested stack screens
    index.tsx
    [id].tsx                    # Dynamic route
  _layout.tsx                   # Root layout (providers, fonts, splash)
  +not-found.tsx                # 404 fallback screen

/components
  /ui                           # Base reusable primitives (Button, Input, Card, etc.)
  /layout                       # Layout wrappers (ScreenWrapper, Header, TabBar)
  /screen-name                  # Screen-specific components grouped by feature

/lib                            # Shared utilities, helpers, and client configs
  utils.ts
  constants.ts
  api.ts                        # API client (e.g., axios/fetch wrapper pointing to backend)

/hooks                          # Custom React hooks

/types                          # Shared TypeScript types and interfaces

/assets                         # Static assets
  /images
  /fonts

/store                          # State management (Zustand, Redux, etc. — only if needed)
```

### Mobile Conventions

- **Navigation**: Always use Expo Router (file-based). Group related screens with route groups `/(groupName)`.
- **Styling**: Use `StyleSheet.create()` or NativeWind (Tailwind for RN). Keep styles co-located with components.
- **Platform-specific code**: Use `.ios.tsx` / `.android.tsx` suffixes only when truly needed. Prefer cross-platform code.
- **Environment variables**: Use `expo-constants` or `.env` with `expo-env.d.ts`. Never hardcode API URLs.

### Running the Mobile App

```bash
# Navigate to mobile directory
cd mobile

# Install dependencies
npx expo install

# Start Expo dev server (opens QR code for Expo Go)
npx expo start

# Run on iOS simulator
npx expo start --ios
# or for a native dev build:
npx expo run:ios

# Run on Android emulator
npx expo start --android
# or for a native dev build:
npx expo run:android

# Clear cache if things break
npx expo start --clear
```

### Creating a New Mobile Project

When scaffolding a new `/mobile` directory:

```bash
npx create-expo-app@latest mobile --template tabs
```

Then restructure into the folder layout above.

---

## GitHub

- **Always use SSH for GitHub remotes**, never HTTPS. SSH avoids OAuth scope issues (e.g., being unable to push commits that touch `.github/workflows/*` without the `workflow` scope).
- When cloning: `git clone git@github.com:owner/repo.git`.
- If an existing repo has an HTTPS origin, switch it: `git remote set-url origin git@github.com:owner/repo.git`.
- If a push fails due to OAuth scope restrictions, check the remote URL first — the fix is usually switching to SSH, not refreshing tokens.

---

## Agent Teams

Use agent teams whenever tasks can be parallelized or benefit from concurrent work. Specifically:

- **Spawn parallel agents** when working on independent parts of a task (e.g., frontend and backend changes, multiple unrelated files, research + implementation).
- **Use background agents** for long-running tasks (builds, tests, research) while continuing other work.
- **Use worktree isolation** when agents need to make changes that could conflict with each other.
- **Prefer agents for exploration** — when investigating unfamiliar code, searching across the codebase, or researching multiple approaches, delegate to Explore agents rather than doing sequential searches yourself.
- **Plan with agents** — for non-trivial tasks, use a Plan agent to design the approach before diving into implementation.

Default to using agent teams for any task that involves more than one independent workstream. When in doubt, parallelize.
