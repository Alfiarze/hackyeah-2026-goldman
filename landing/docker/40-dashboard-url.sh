#!/bin/sh
# Runs at container start (nginx image hook). Writes the dashboard URL the page links to, so the
# same image works on any domain: set DASHBOARD_URL (Coolify: ${SERVICE_URL_GATEWAY}/dashboard/).
set -e
url="${DASHBOARD_URL:-}"
printf 'window.MANDATE_DASHBOARD_URL = %s;\n' "$( [ -n "$url" ] && printf '"%s"' "$url" || printf 'null' )" \
  > /usr/share/nginx/html/env.js
