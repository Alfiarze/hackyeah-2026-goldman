FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first for layer caching
COPY pyproject.toml ./
RUN mkdir mandate && touch mandate/__init__.py \
    && pip install ".[dev]" \
    && rm -rf mandate

COPY mandate ./mandate
RUN pip install --no-deps .

RUN useradd --create-home --uid 1000 app
USER app

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status == 200 else 1)"

# Single worker on purpose: in-process state (policy snapshot, locks) stays consistent.
CMD ["uvicorn", "mandate.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
