# paperlists-api

A small FastAPI service that exposes the [papercopilot/paperlists](https://github.com/papercopilot/paperlists) corpus over HTTPS, so AI agents (via the companion MCP server, or any HTTP client) can run **trend-focused** queries without downloading the ~830 MB of raw JSON.

## What it does

Built around the observation that flat keyword search is already well served by [papercopilot.com](https://papercopilot.com). The API's first-class verbs are about **how research areas evolve**:

| Endpoint | Use case |
|---|---|
| `GET /v1/topic_trend` | Yearly paper count + citation-weighted volume for a topic |
| `GET /v1/topic_evolution` | Per-year (or per-window) top co-occurring keywords + landmark papers |
| `GET /v1/compare_periods` | Diff a topic across two year ranges — what emerged / faded / sustained |
| `GET /v1/author_trajectory` | Papers by an author across years |
| `GET /v1/field_landscape` | Single-year snapshot for a field: top papers, authors, affiliations, keywords |
| `GET /v1/conference_stats/{conf}/{year}` | Acceptance breakdown + rating/citation summary stats |
| `GET /v1/top_papers/{conf}/{year}` | Ranked by citation or rating |
| `GET /v1/search` | Standard FTS5 search (title/abstract/keywords/authors) |
| `GET /v1/paper/{conf}/{paper_id}` | Single record (full schema, including abstract) |
| `GET /v1/coverage` | What conferences/years are indexed |

Implementation: sqlite FTS5 over a flattened `papers` table built from the repo's JSON files. Index lives in `papers.db`. Build it locally with:

```bash
cd tools/query-api
pip install -e .
python -m paperlists_api.indexer ../.. ./papers.db
PAPERLISTS_DB=$PWD/papers.db uvicorn paperlists_api.main:app --reload
```

Then `open http://localhost:8000/docs` for the interactive API browser.

## Deployment

### Railway
- Connect this fork to Railway, set the **build context to the repo root** (so the Dockerfile can `COPY` the conference directories).
- Railway reads `tools/query-api/railway.json` and uses `tools/query-api/Dockerfile`.
- Free hobby tier (~$5/mo credit) is sufficient for the demo.
- Egress is the main cost driver. Two mitigations baked in:
  1. `include_abstract` defaults to `false` on `/v1/search` — abstracts are only sent on `/v1/paper/{conf}/{id}`.
  2. Token-bucket rate limiter (default 60 req/min/IP, configurable via `PAPERLISTS_RATE_PER_MIN`).

### HF Spaces / Fly.io / self-hosted
Same Dockerfile, just point at a different host. The index step is the slow part (~1–2 min on cold build).

## Future / out of scope for v1
- Incremental re-indexing on JSON updates (current build is full rebuild)
- Affiliation normalization across `aff_unique_norm` variants
- Embedding-based semantic search (would require a vector DB; deferred)
- Cloudflare Workers + D1 port for near-zero idle cost
