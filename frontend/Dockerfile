# syntax=docker/dockerfile:1

# ---- Build stage ----
FROM node:22-slim AS builder

WORKDIR /build

# Copy package files first so this layer is cached independently of
# source changes -- `npm ci` only re-runs when package*.json actually
# change, not on every source edit.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

# ---- Runtime stage ----
FROM nginx:1.27-alpine AS runtime

# gettext provides envsubst, used by docker-entrypoint.sh to inject
# BACKEND_HOST into the nginx config at container start (not build
# time), so the same built image works against different backend
# hostnames in different environments without rebuilding.
RUN apk add --no-cache gettext curl

COPY --from=builder /build/dist /usr/share/nginx/html
COPY nginx.conf.template /etc/nginx/templates/nginx.conf.template
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost/ || exit 1

ENTRYPOINT ["/docker-entrypoint.sh"]
