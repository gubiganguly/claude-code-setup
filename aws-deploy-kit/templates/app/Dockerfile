# syntax=docker/dockerfile:1

# Production image — Next.js standalone server on Amazon ECS Express (Fargate).
# Debian slim (glibc + openssl) keeps Prisma happy. Built for linux/amd64.

FROM node:22-bookworm-slim AS base
ENV NEXT_TELEMETRY_DISABLED=1
WORKDIR /app
# OpenSSL + CA certs: Prisma's schema engine wants OpenSSL present, and CA
# certs are good hygiene for TLS connections to RDS.
RUN apt-get update && apt-get install -y --no-install-recommends openssl ca-certificates \
  && rm -rf /var/lib/apt/lists/*

# ── Dependencies (cached on package files + prisma schema for postinstall generate) ──
FROM base AS deps
COPY package.json package-lock.json ./
COPY prisma ./prisma
RUN npm ci

# ── Build (runs `prisma generate && next build`, emits .next/standalone) ──
FROM base AS build
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# No DB or secrets needed at build time — dashboard routes render dynamically.
RUN npm run build

# ── Runtime ──
FROM base AS runner
ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

RUN groupadd --system --gid 1001 nodejs \
  && useradd --system --uid 1001 --gid nodejs nextjs

# Standalone output: server.js + traced node_modules, static assets, public dir.
COPY --from=build /app/public ./public
COPY --from=build --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=build --chown=nextjs:nodejs /app/.next/static ./.next/static

# Migration toolchain. The SAME image is used both to serve the app and to run
# the one-shot migration task in CI (migrate-entrypoint.sh), so the migrations
# applied are always exactly the ones that shipped with this build.
#
# The standalone trace ships only a minimal node_modules (no Prisma CLI or
# schema engine). Overlay the full node_modules so the CLI is present;
# server.js works fine against the superset.
COPY --from=build --chown=nextjs:nodejs /app/node_modules ./node_modules
COPY --from=build --chown=nextjs:nodejs /app/prisma ./prisma
COPY --from=build --chown=nextjs:nodejs /app/prisma.config.ts ./prisma.config.ts
COPY --from=build --chown=nextjs:nodejs /app/tsconfig.json ./tsconfig.json
# Generated Prisma client — the seed scripts import it directly via tsx.
COPY --from=build --chown=nextjs:nodejs /app/src/generated ./src/generated
COPY --chown=nextjs:nodejs docker-entrypoint.sh ./docker-entrypoint.sh
COPY --chown=nextjs:nodejs migrate-entrypoint.sh ./migrate-entrypoint.sh
RUN chmod +x ./docker-entrypoint.sh ./migrate-entrypoint.sh

USER nextjs
EXPOSE 3000

# Default: start the server. Migrations do NOT run here — the CI workflow
# overrides the command to ./migrate-entrypoint.sh in a one-shot task before
# the rollout, so a failed migration never crash-loops the service.
CMD ["./docker-entrypoint.sh"]
