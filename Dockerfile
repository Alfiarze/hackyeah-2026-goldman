# --- dashboard (React + Vite) ---
FROM node:22-alpine AS dashboard
WORKDIR /dashboard
COPY dashboard/package.json dashboard/package-lock.json* ./
RUN npm ci --silent || npm install --silent
COPY dashboard/ ./
RUN npm run build

# --- docker CLI (so the sandbox runner can launch sibling containers via the mounted socket) ---
FROM docker:27-cli AS dockercli

# --- Aegis gateway / tool backends / sandbox runner (same image, different command) ---
FROM python:3.12-slim
COPY --from=dockercli /usr/local/bin/docker /usr/local/bin/docker

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    AEGIS_ROOT=/app

WORKDIR /app

# Dependencies first for layer caching
COPY pyproject.toml ./
RUN mkdir aegis && touch aegis/__init__.py \
    && pip install ".[dev]" \
    && rm -rf aegis

COPY aegis ./aegis
COPY db ./db
COPY demo ./demo
COPY tests ./tests
COPY --from=dashboard /dashboard/dist ./dashboard/dist
# defaults copied into empty policy/feed volumes on first start (docker/entrypoint.sh)
COPY policy ./defaults/policy
COPY feeds ./defaults/feeds
COPY docker/entrypoint.sh /usr/local/bin/aegis-entrypoint
RUN pip install --no-deps . && mkdir -p policy feeds && chmod +x /usr/local/bin/aegis-entrypoint

RUN useradd --create-home --uid 1000 app && chown -R app:app /app/policy /app/feeds
USER app

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status == 200 else 1)"

# Single worker on purpose: in-process state (policy snapshot) stays simple. Budget atomicity is in Postgres,
# so more workers/instances stay correct (each polls the policy file).
ENTRYPOINT ["aegis-entrypoint"]
CMD ["uvicorn", "aegis.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
