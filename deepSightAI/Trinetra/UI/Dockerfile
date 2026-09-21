# deepSightAI Trinetra — Next.js 14 UI Dockerfile (Issue #19)
# Multi-stage build: deps → builder → runner
#
# Build from repository root (root build context — CODING_STANDARDS.md §5):
#   docker build -t trinetra-ui:latest -f deepSightAI/Trinetra/UI/Dockerfile .
#
# Non-root execution: runs as user "nextjs" (UID/GID 1001).
# Standalone output: relies on `output: 'standalone'` in next.config.js.

# ── Stage 1: dependency installer ──────────────────────────────────────────
FROM node:18-alpine AS deps

RUN apk add --no-cache libc6-compat

WORKDIR /app

COPY deepSightAI/Trinetra/UI/package.json deepSightAI/Trinetra/UI/package-lock.json* ./
RUN npm ci --omit=dev --ignore-scripts

# ── Stage 2: Next.js builder ────────────────────────────────────────────────
FROM node:18-alpine AS builder

WORKDIR /app

ENV NEXT_TELEMETRY_DISABLED=1

COPY --from=deps /app/node_modules ./node_modules
COPY deepSightAI/Trinetra/UI/ .

RUN npm run build

# ── Stage 3: minimal production runner ─────────────────────────────────────
FROM node:18-alpine AS runner

WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

# Platform environment variables (overridable via docker-compose / Kubernetes)
ENV SEARCH_SERVICE_URL=http://search-service:8081
ENV AUTH_SERVICE_URL=http://auth-service:8002
ENV WATCHLIST_SERVICE_URL=http://watchlist-matcher:8083
ENV SERVER_HOST=http://main-api:8080
ENV MINIO_URL=http://minio:9000
ENV NEXTAUTH_SECRET=changeme
ENV NEXTAUTH_URL=http://localhost:3000

# Create non-root group and user (GID/UID 1001)
RUN addgroup --system --gid 1001 nodejs \
    && adduser  --system --uid 1001 nextjs

# Copy standalone output produced by Next.js
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static   ./.next/static

USER nextjs

EXPOSE 3000

CMD ["node", "server.js"]
