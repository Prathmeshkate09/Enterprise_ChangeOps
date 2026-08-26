# syntax=docker/dockerfile:1.7
FROM node:22-alpine AS dependencies
WORKDIR /app
COPY package.json package-lock.json ./
COPY apps/control-tower/package.json apps/control-tower/package.json
COPY packages/contracts-typescript/package.json packages/contracts-typescript/package.json
RUN --mount=type=cache,target=/root/.npm npm ci

FROM node:22-alpine AS builder
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=dependencies /app/node_modules ./node_modules
COPY --from=dependencies /app/apps/control-tower/node_modules ./apps/control-tower/node_modules
COPY . .
RUN npm run build --workspace @changeops/control-tower

FROM node:22-alpine AS runtime
WORKDIR /app
ENV HOSTNAME=0.0.0.0 \
    NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000

RUN addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 nextjs

COPY --from=builder --chown=nextjs:nodejs /app/apps/control-tower/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/apps/control-tower/.next/static ./apps/control-tower/.next/static
COPY --from=builder --chown=nextjs:nodejs /app/apps/control-tower/public ./apps/control-tower/public

USER nextjs
EXPOSE 3000
CMD ["node", "apps/control-tower/server.js"]
