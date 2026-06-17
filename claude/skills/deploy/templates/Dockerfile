# syntax=docker/dockerfile:1

# Production image for CSIP — Next.js 16 standalone server on AWS App Runner.
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

# Migration toolchain — lets the container run `prisma migrate deploy` on boot.
# The standalone trace ships only a minimal node_modules (no Prisma CLI / schema
# engine and their transitive deps). Overlay the full node_modules so the CLI
# and everything it needs are present; server.js works fine against the superset.
COPY --from=build --chown=nextjs:nodejs /app/node_modules ./node_modules
COPY --from=build --chown=nextjs:nodejs /app/prisma ./prisma
COPY --from=build --chown=nextjs:nodejs /app/prisma.config.ts ./prisma.config.ts
COPY --from=build --chown=nextjs:nodejs /app/tsconfig.json ./tsconfig.json
# Generated Prisma client — the seed scripts import it directly via tsx.
COPY --from=build --chown=nextjs:nodejs /app/src/generated ./src/generated
COPY --chown=nextjs:nodejs docker-entrypoint.sh ./docker-entrypoint.sh
RUN chmod +x ./docker-entrypoint.sh

USER nextjs
EXPOSE 3000

# Runs `prisma migrate deploy` then starts the server.
CMD ["./docker-entrypoint.sh"]
