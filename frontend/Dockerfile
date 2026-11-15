# =============================================================================
# Dockerfile cho Frontend Next.js 14 Dashboard (VSICO Zalo Bot)
# Multi-stage build với Node.js 20 Alpine & Standalone Output
# Cổng dịch vụ: 3001
# Context: Root monorepo (.)
# =============================================================================

# Giai đoạn 1: Cài đặt dependencies
FROM node:20-alpine AS deps
RUN apk add --no-cache libc6-compat
WORKDIR /app

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

# Giai đoạn 2: Build ứng dụng Next.js
FROM node:20-alpine AS builder
WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY frontend/package.json frontend/package-lock.json ./
COPY frontend/next.config.mjs frontend/tsconfig.json frontend/tailwind.config.ts frontend/postcss.config.mjs ./
COPY frontend/src ./src
COPY frontend/public ./public

ENV NEXT_TELEMETRY_DISABLED=1
ENV NODE_ENV=production

RUN npm run build

# Giai đoạn 3: Runner siêu nhẹ với standalone output
FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3001
ENV HOSTNAME="0.0.0.0"

# Tạo user không có quyền root để đảm bảo an toàn vận hành
RUN addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 nextjs

# Copy thư mục static và standalone build
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs

EXPOSE 3001

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://localhost:3001 || exit 1

CMD ["node", "server.js"]
