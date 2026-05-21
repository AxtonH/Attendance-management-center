# Frontend Dockerfile (Next.js 14 standalone build).
#
# Build context: ./frontend (default Railway behavior when Root
# Directory is set to "frontend" — see frontend/railway.toml).
#
# NEXT_PUBLIC_API_BASE_URL is read at BUILD TIME, not runtime — Next
# inlines NEXT_PUBLIC_* env vars into the client bundle. Railway must
# set this as a build-time variable (it does by default for build args
# declared like below).

# ---- deps ----
FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci --omit=optional

# ---- builder ----
FROM node:20-alpine AS builder
WORKDIR /app

# Build arg must be declared in this stage to be available during `next build`.
ARG NEXT_PUBLIC_API_BASE_URL
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
ENV NEXT_TELEMETRY_DISABLED=1

COPY --from=deps /app/node_modules ./node_modules
COPY . .

RUN npm run build

# ---- runner ----
FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1

COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./package.json

# Railway sets PORT at runtime; default to 3000 for local docker runs.
ENV PORT=3000
EXPOSE 3000

# next start respects $PORT via -p; passing it explicitly avoids any
# Next.js default that might ignore the env var.
CMD ["sh", "-c", "npx next start -p ${PORT}"]
