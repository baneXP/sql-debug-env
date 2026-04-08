# ── Build stage ───────────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.11-slim

RUN useradd -m -u 1000 appuser

WORKDIR /app

COPY --from=builder /install /usr/local

# Root-level files
COPY --chown=appuser:appuser app.py          ./app.py
COPY --chown=appuser:appuser models.py       ./models.py
COPY --chown=appuser:appuser tasks.py        ./tasks.py
COPY --chown=appuser:appuser openenv.yaml    ./openenv.yaml
COPY --chown=appuser:appuser env.py          ./env.py
COPY --chown=appuser:appuser inference.py    ./inference.py
COPY --chown=appuser:appuser pyproject.toml  ./pyproject.toml
COPY --chown=appuser:appuser requirements.txt ./requirements.txt

# server/ package
COPY --chown=appuser:appuser server/ ./server/
RUN touch /app/server/__init__.py && chown appuser:appuser /app/server/__init__.py

USER appuser

EXPOSE 7860

HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:7860/health')" || exit 1

CMD ["uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "7860", "--workers", "1"]
