# Standalone landing page: build the static Astro site, serve it with nginx.
#   docker build -t aegis-landing --build-arg PUBLIC_DASHBOARD_URL=https://demo.example.com/dashboard/ landing
#   docker run -p 8080:80 -e DASHBOARD_URL=https://app.example.com/dashboard/ aegis-landing
# DASHBOARD_URL is read at start (no rebuild per domain); the build arg is only the fallback.
FROM node:22-alpine AS build
WORKDIR /site
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
ARG PUBLIC_DASHBOARD_URL=http://localhost:8000/dashboard/
ARG LANDING_BASE=/
ARG LANDING_SITE=https://aegis.local
ENV PUBLIC_DASHBOARD_URL=$PUBLIC_DASHBOARD_URL LANDING_BASE=$LANDING_BASE LANDING_SITE=$LANDING_SITE
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY docker/40-dashboard-url.sh /docker-entrypoint.d/40-dashboard-url.sh
RUN chmod +x /docker-entrypoint.d/40-dashboard-url.sh
COPY --from=build /site/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=15s --timeout=3s CMD wget -qO- http://127.0.0.1/ >/dev/null || exit 1
