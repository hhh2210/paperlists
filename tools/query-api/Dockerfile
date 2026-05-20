# --- Stage 1: build sqlite FTS5 index from the JSON corpus ---
FROM python:3.11-slim AS builder

WORKDIR /build
RUN pip install --no-cache-dir orjson

# Build context is the repo root (set in railway.json).
# Copy only what we need to keep image small.
COPY tools/query-api/paperlists_api ./paperlists_api
COPY 3dv aaai acl acml aistats alt automl coling colm colt corl cvpr \
     eccv emnlp iccv iclr icml icra ijcai iros kdd naacl nips rss \
     siggraph siggraphasia uai wacv www \
     /data/

# ai4x is optional / future; tolerate it being absent.
RUN if [ -d /data/ai4x ]; then echo "ai4x present"; fi

RUN python -m paperlists_api.indexer /data /build/papers.db && \
    sqlite3 /build/papers.db "VACUUM;" 2>/dev/null || true && \
    ls -lh /build/papers.db

# --- Stage 2: lean runtime ---
FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PAPERLISTS_DB=/app/papers.db

COPY tools/query-api/pyproject.toml ./pyproject.toml
COPY tools/query-api/paperlists_api ./paperlists_api
RUN pip install --no-cache-dir .

COPY --from=builder /build/papers.db /app/papers.db

EXPOSE 8000
CMD ["uvicorn", "paperlists_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
