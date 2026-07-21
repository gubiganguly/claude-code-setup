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
- **Hosting**: AWS (account 346698404534, default region `us-east-1`), Amazon ECS
  Express Mode (Fargate) for containers, RDS for the database, Terraform for infra,
  GitHub Actions + OIDC for CI/CD. (App Runner is deprecated — AWS stopped accepting
  new customers on 2026-04-30; existing App Runner services keep running, but all
  new deploys go to ECS Express Mode.)
- **Deploying**: use the `/deploy` skill. First deploy = `terraform apply`; every
  deploy after = `git push`. Never hand-roll AWS infra outside that pattern.
- **Domains**: every deployed app gets `<project>.apps.snhcap.com`, served by
  CloudFront in front of the ECS Express service (Route 53 zone owned by the
  platform stack, delegated from GoDaddy; ACM cert auto-issued/renewed). Always
  share and report the branded URL — never the raw `*.on.aws` Express URL, which
  Microsoft Defender flags as suspicious.
- **Shared platform**: small projects deploy in the skill's SHARED mode onto the
  standing platform stack at `~/Development/aws-platform` (shared VPC +
  `platform-db` RDS; ECS Express tasks run in the platform public subnets wearing
  the `platform-ecs-egress` SG, sharing one ALB across services). Never
  `terraform destroy` the platform stack — all shared-mode databases live on it.
  Dedicated mode (own VPC+RDS, no NAT) is only for isolation-sensitive apps.

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

## Security Standards (every application)

Pragmatic baseline, not enterprise theater. The goal is zero gaping holes:
the OWASP top risks (broken access control, misconfiguration, injection)
covered by default in every app.

### Authentication & sessions

- JWTs: short-lived access tokens (15-60 min) plus refresh token rotation.
  Store tokens in `HttpOnly` + `Secure` + `SameSite=Lax` cookies, never in
  localStorage.
- Passwords hashed with bcrypt or argon2. Never plaintext, never reversible.
- Login returns a generic "invalid email or password" (no user enumeration),
  and login/signup/password endpoints are rate-limited (e.g. slowapi on
  FastAPI).
- The seed admin keeps its standard `admin@snhcap.com` / `admin123!`
  credentials in all environments, including production (deliberate choice
  for convenience). Don't add forced-change or password-expiry logic to this
  account.

### Authorization (OWASP #1 risk)

- EVERY API endpoint and server action re-checks authentication AND
  authorization server-side. Middleware or UI hiding is never the only gate.
- Object-level checks always: a user can only read/modify rows they own.
  Never trust an ID from the client without verifying ownership (no IDOR).
- RBAC enforced in the backend on every admin route, not just by hiding
  admin UI.

### Input & data handling

- Validate every input at the boundary: Pydantic schemas on FastAPI, Zod on
  Next.js API routes and server actions. Reject, don't sanitize-and-hope.
- Database access only through the ORM or parameterized queries. Never
  string-concatenate SQL.
- Never render user content as raw HTML (`dangerouslySetInnerHTML` only for
  trusted, sanitized content).
- Errors to the client are human messages, never stack traces or internals.
  No secrets, tokens, or PII in logs.

### Secrets & config

- Secrets live in env vars locally and AWS SSM/Secrets Manager in production.
  Never committed; `.env*` is always gitignored.
- Never prefix a secret with `NEXT_PUBLIC_` (it ships to the browser).
- CORS locked to the app's known origins. Never `*` with credentials.
- HTTPS everywhere (CloudFront/ALB already provide it); cookies get `Secure`.

### Infra & dependencies

- RDS is never publicly accessible; security groups are least-privilege.
- Run `npm audit` / `pip-audit` before first deploys and when adding
  dependencies; don't ship known-critical CVEs.
- Set basic security headers: `X-Content-Type-Options: nosniff`,
  `frame-ancestors` (or `X-Frame-Options: DENY`), and a CSP where practical.

### Pre-ship gut check

Before calling an app done, verify: Can an anonymous user reach any
authenticated endpoint? Can user A read or modify user B's data by changing
an ID? Is any secret in the client bundle or git history? Is login
rate-limited? Do errors leak internals? All five must be "no".

---

## UI & Design Standards (every application)

The goal is UI that looks like a designed product, not an AI template. The
generic "AI look" — indigo→purple gradients, centered hero + three feature
cards, emoji icons, uniform border-radius, Inter-everywhere with no hierarchy —
is the statistical median of training data. Escape it by making explicit
choices on typography, color, and motion at project start, then applying them
consistently.

### Baseline

- **Look and feel**: intuitive, clean, and professional — but not boring.
- **Zero-training usability**: someone who has never seen the app should be
  able to open it and understand what's going on. Prefer obvious labels, clear
  empty states, and visible affordances over cleverness.
- **Info icons**: wherever something needs explanation — especially calculations,
  derived numbers, or non-obvious fields — add an info icon (tooltip/popover)
  that explains it in plain language.

### UX psychology (apply everywhere)

- **Aesthetic-usability effect**: users perceive attractive UIs as more usable
  and forgive small flaws in them — visual polish is functional, not cosmetic.
- **Hick's law**: fewer, simpler choices per screen. Use progressive disclosure —
  hide advanced options until they're needed.
- **Fitts's law**: primary actions are large and near the user's attention;
  touch targets ≥ 44×44px on mobile.
- **Doherty threshold**: acknowledge every interaction in < 400ms — optimistic
  UI, instant pressed states, skeletons for anything slower.
- **Cognitive load**: avoid clutter, match existing mental models, offload work
  from the user (smart defaults, autofill, remembered state).
- **Peak–end rule**: over-invest in the first-run experience and in success
  moments (confirmations, completions) — those are what users remember.

### Typography

Choose fonts deliberately per project — never one default font for everything.

- **App/dashboard UI**: Inter or Geist (screen-optimized, tall x-height,
  legible at 13px). Use `tabular-nums` on any column of numbers.
- **Headings/display**: pick ONE distinctive font per project for identity —
  e.g. Bricolage Grotesque, Space Grotesk, Sora, Fraunces, Instrument Serif.
  Pair fonts that contrast in style but share a similar x-height.
- **Long-form reading**: a readable serif (Lora, Newsreader, Source Serif 4).
- **Code/monospace data**: JetBrains Mono or Geist Mono.
- Load via `next/font` (self-hosted, no layout shift); prefer variable fonts
  (40–60% smaller payload). Mobile: system fonts or `expo-font` with the same picks.
- **Scale & rhythm**: fixed type scale (e.g. 12/14/16/18/20/24/30/36/48);
  body 14–16px, dense tables ≥ 12px; line-height ~1.5 body, 1.1–1.2 headings;
  line length 45–75 characters; build hierarchy with weight and color, not
  size alone.

### Color

- Define the palette at project start using **60-30-10**: ~60% neutral
  surfaces, ~30% secondary, ~10% accent. The accent is what makes the UI feel
  alive — spend it deliberately (primary buttons, active states, key data),
  never everywhere.
- Pick a real brand accent per project. **Banned**: the default indigo→purple
  gradient (#6366F1→#A855F7) and generic blue-500-on-white template look.
- Tint neutrals warm or cool — never flat pure grays; near-black text on
  near-white (e.g. #0A0A0A on #FAFAFA), not #000 on #FFF.
- Use **semantic tokens** (`background`, `surface`, `border`, `muted`,
  `primary`, `success`, `warning`, `danger`) — components never hardcode hex.
- Define colors in **OKLCH** where practical (Tailwind v4 native): perceptually
  uniform lightness keeps generated shades consistent across hues.
- **Dark mode is not inverted light mode**: elevation = lighter surfaces (≥ 4
  surface levels), desaturated accents, minimal shadows, dark gray base — never
  pure black.
- Contrast: ≥ 4.5:1 body text, ≥ 3:1 large text and UI elements.

### Motion & micro-interactions

How things move matters more than that they move — easing quality is the
difference between polished and cheap.

- **Libraries**: web → Motion (framer-motion; MIT, small) as default; anime.js
  for staggered/SVG/timeline flourishes on marketing pages; plain CSS
  transitions for simple state changes; View Transitions API for page
  transitions. Mobile → React Native Reanimated (+ Moti). Lottie for
  illustrated animation. (GSAP is powerful but Webflow-owned with license
  restrictions — default to Motion.)
- **Durations**: 100–200ms micro-interactions (hover, press, toggle), 200–300ms
  standard transitions (modals, dropdowns), 300–500ms large moves only.
  Nothing over 500ms outside deliberate hero/onboarding moments. The more
  frequent the action, the faster its animation.
- **Easing**: ease-out (quart/expo) for entrances, ease-in or a fast fade for
  exits, ease-in-out for on-screen moves, springs for gesture-driven mobile
  motion. Linear only for loaders/tickers. No bounce or elastic in product UI.
- Animate only `transform` and `opacity`; never animate layout properties.
- **Purposeful only**: every animation must orient (where did this come from?),
  give feedback (did that work?), or add personality in low-frequency moments.
  Total animation wait per task under ~3 seconds.
- The touches that make UIs feel alive: staggered list entrances (20–40ms/item),
  count-up number transitions, pressed states on every button, subtle
  hover lifts on cards.
- Always respect `prefers-reduced-motion`.

### Craft details (designed vs. generated)

- **Empty states are first-class screens**: informative copy + supporting
  visual + a prominent CTA to create the first item; hide filters/tabs that do
  nothing until content exists.
- **Loading**: skeletons that match the final layout (not spinners) for content;
  optimistic updates for user actions; inline spinners for form submissions.
- **Shadows**: layered and subtle (two low-opacity shadows, slight y-offset),
  optionally tinted toward the surface hue — never one heavy black blur.
- **Spacing**: fixed scale only (4/8/12/16/24/32/48/64px), no arbitrary values.
  Start with generous whitespace and remove — roomy reads as quality.
- **Icons**: one consistent set (Lucide by default; Phosphor for personality).
  Never emoji as UI icons.
- **Polish pass before "done"**: consistent radii, aligned optical edges,
  visible focus states, hover states on everything interactive, and real
  designed error/success states.

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

## Writing & Copywriting Standards (copy, emails, docs, any prose)

Every word shipped in an app, site, or email should sound like a sharp human
wrote it. Sources: the direct-response canon (Ogilvy, Halbert's Boron Letters,
Sugarman, Schwartz, Caples, Cashvertising) and modern practitioners (Harry Dry,
Julian Shapiro, Joanna Wiebe, Hormozi, Sam Parr).

### Never sound AI (hard rules)

- **Never use em dashes** in anything written for humans: UI copy, marketing
  copy, emails, documentation, README files, error messages, etc. Rewrite the
  sentence instead: use a comma, colon, parentheses, or split it into two
  sentences.
- **Banned words**: delve, elevate, seamless, effortless, unleash, unlock,
  supercharge, empower, revolutionize, game-changer, cutting-edge, robust,
  leverage (as a verb), streamline, harness, journey, dive in, landscape,
  realm, tapestry, "in today's fast-paced world".
- **Banned constructions**: "It's not just X, it's Y", "Whether you're A or B",
  "Look no further", rhetorical-question openers, three-item parallel triads in
  every paragraph, exclamation-mark enthusiasm, generic intros and wrap-up
  conclusions.
- **The read-aloud test**: if a sentence would sound odd said out loud to a
  friend, rewrite it. Vary sentence length. Short beats long.

### Voice (all writing)

- Write like you talk, to ONE person, as "you". Never "users" or "customers"
  in copy they will read.
- Third-to-fifth grade reading level. Short words, short sentences, short
  paragraphs. A great sentence is a good sentence made shorter.
- Steal the customer's own words (reviews, support tickets, interviews) instead
  of inventing marketing-speak. The best copy is assembled, not written.
- Specifics beat superlatives: "Groceries in 1 hour" beats "Lightning-fast
  delivery". Numbers, timeframes, and concrete nouns build trust.

### The three tests (run on every headline and tagline)

1. **Can you visualize it?** If the reader can't picture it, make it concrete.
2. **Can you falsify it?** Provable claims beat vague praise.
3. **Could anyone else say it?** If a competitor could paste it on their site,
   it says nothing. Rewrite until only this product can claim it.

### Marketing pages (landing pages, heroes, feature sections)

- Formula: conversion = desire minus (labor + confusion). Every element either
  raises desire or cuts effort/confusion, or it gets deleted.
- **Header**: fully descriptive of what the product does. Test: reading only
  this line, does a stranger know exactly what's being sold? Add a hook (bold
  specific claim, or answer the biggest objection).
- **Subheader**: one or two sentences on how it works or why the claim is
  believable.
- Bold claim at the top, then spend the rest of the page proving it: numbers,
  screenshots of the real product, testimonials showing transformation.
  Proof over promise.
- Value prop exercise: what bad alternative do people use today, how is this
  better, turn that into an action statement.
- **Headlines are 80% of the work** (Ogilvy). Write 10 variants, keep the one
  that passes the three tests. Match the copy to the reader's awareness stage
  (Schwartz): unaware readers need the problem named; product-aware readers
  need the differentiator.
- **CTAs**: value over action. "Get my report" beats "Submit". Put the
  objection-killer next to the button ("Free. No credit card.").

### In-app microcopy (UX writing)

- One message = one idea. One concept = one term, used identically everywhere.
- **Buttons** are verbs that say exactly what happens next, and should complete
  the sentence "I want to ___".
- **Error messages**: say what happened and how to fix it, in plain words.
  Never a bare "Something went wrong", never blame the user, never show raw
  error codes without a human sentence first.
- **Empty states, tooltips, placeholders**: short, helpful, zero jargon.
  Front-load the key words; people skim.
- Sound like a competent human helping a friend, not a system emitting output.

### Emails

- Subject line: curiosity plus specificity, under about 7 words.
- Body reads like a note to one friend: short, plain, one clear ask.
- Structure when persuading: problem, agitate, solve (PAS). Give a reason why
  for every ask.

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
