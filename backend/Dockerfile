# AI Incident Resolution Assistant - API (+ FAISS + SQLite/Postgres)
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

# psycopg2-binary ships its own libpq; curl is used by the healthcheck
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . ./
RUN mkdir -p /data

# Ingest the sample corpus at build time so `docker compose up` is immediately
# useful. Remove this line to keep the knowledge base empty and start it with
# `docker compose run backend python ../scripts/seed_demo.py` instead.
RUN DATA_DIR=/data AIRA_ENV=production LLM_ENABLED=false \
    python ../scripts/seed_demo.py || true

EXPOSE 8000
HEALTHCHECK --interval=20s --timeout=5s --retries=5 \
  CMD curl -fsS http://localhost:8000/api/health || exit 1
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
