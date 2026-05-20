"""FastAPI service exposing the paperlists corpus over HTTPS.

Designed for hosted deployment (Railway / HF Spaces / Fly.io) so that
casual users — including AI agents via the MCP wrapper — can query the
full corpus without downloading the ~830MB of raw JSON.

Endpoints are intentionally compact and trend-focused, since plain
keyword search is already well served by papercopilot.com.
"""
from __future__ import annotations

import os
import time
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import __version__, queries
from .db import DB_PATH, connect

API_TITLE = "Paperlists Query API"
DEFAULT_LIMIT = 50
MAX_LIMIT = 200

app = FastAPI(
    title=API_TITLE,
    version=__version__,
    description=(
        "AI-native query layer over the papercopilot/paperlists corpus. "
        "Trend-focused endpoints (topic_trend, topic_evolution, "
        "compare_periods, author_trajectory, field_landscape) are first-class — "
        "raw keyword search remains available as /v1/search."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# ---------- Tiny in-memory rate limiter ----------
# Hosted demo on Railway free tier — protect egress. Per-IP token bucket.
_RATE_BUCKET: dict[str, tuple[float, float]] = {}
_RATE_PER_MIN = float(os.environ.get("PAPERLISTS_RATE_PER_MIN", "60"))
_RATE_BURST = float(os.environ.get("PAPERLISTS_RATE_BURST", "20"))


def _client_ip(req: Request) -> str:
    fwd = req.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return req.client.host if req.client else "unknown"


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    if request.url.path in ("/", "/healthz", "/v1/coverage"):
        return await call_next(request)
    ip = _client_ip(request)
    now = time.time()
    tokens, last = _RATE_BUCKET.get(ip, (_RATE_BURST, now))
    tokens = min(_RATE_BURST, tokens + (now - last) * (_RATE_PER_MIN / 60.0))
    if tokens < 1.0:
        return JSONResponse(
            {"error": "rate_limited", "retry_after_sec": int((1.0 - tokens) * 60.0 / _RATE_PER_MIN)},
            status_code=429,
        )
    _RATE_BUCKET[ip] = (tokens - 1.0, now)
    return await call_next(request)


# ---------- Routes ----------


@app.get("/")
def root():
    return {
        "name": API_TITLE,
        "version": __version__,
        "docs": "/docs",
        "endpoints": [
            "/v1/coverage",
            "/v1/search",
            "/v1/paper/{conf}/{paper_id}",
            "/v1/topic_trend",
            "/v1/topic_evolution",
            "/v1/author_trajectory",
            "/v1/field_landscape",
            "/v1/compare_periods",
            "/v1/conference_stats/{conf}/{year}",
            "/v1/top_papers/{conf}/{year}",
        ],
        "source": "https://github.com/papercopilot/paperlists",
    }


@app.get("/healthz")
def healthz():
    return {"ok": True, "db": str(DB_PATH), "db_exists": DB_PATH.exists()}


@app.get("/v1/coverage")
def coverage():
    with connect() as conn:
        return queries.coverage(conn)


@app.get("/v1/search")
def search(
    q: str = Query(..., min_length=1, max_length=200, description="Query string. FTS5 syntax accepted."),
    conferences: Optional[str] = Query(None, description="Comma-separated conf list, e.g. 'iclr,nips,icml'."),
    year_from: Optional[int] = Query(None, ge=1990, le=2100),
    year_to: Optional[int] = Query(None, ge=1990, le=2100),
    exclude_rejected: bool = Query(True),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
    order_by: str = Query("relevance", pattern="^(relevance|year_desc|citation_desc|rating_desc)$"),
    include_abstract: bool = Query(False, description="Include abstract in each result. Off by default to control egress."),
):
    confs = [c.strip().lower() for c in conferences.split(",")] if conferences else None
    with connect() as conn:
        return queries.search_papers(
            conn,
            q=q, conferences=confs,
            year_from=year_from, year_to=year_to,
            exclude_rejected=exclude_rejected,
            limit=limit, offset=offset, order_by=order_by,
            include_abstract=include_abstract,
        )


@app.get("/v1/paper/{conf}/{paper_id}")
def get_paper(conf: str, paper_id: str):
    with connect() as conn:
        paper = queries.get_paper(conn, conf, paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail="paper not found")
    return paper


@app.get("/v1/topic_trend")
def topic_trend(
    q: str = Query(..., min_length=1, max_length=200),
    conferences: Optional[str] = Query(None),
    year_from: Optional[int] = Query(None),
    year_to: Optional[int] = Query(None),
    exclude_rejected: bool = Query(True),
):
    confs = [c.strip().lower() for c in conferences.split(",")] if conferences else None
    with connect() as conn:
        return queries.topic_trend(
            conn, q=q, conferences=confs,
            year_from=year_from, year_to=year_to,
            exclude_rejected=exclude_rejected,
        )


@app.get("/v1/topic_evolution")
def topic_evolution(
    q: str = Query(..., min_length=1, max_length=200),
    year_from: int = Query(..., ge=1990, le=2100),
    year_to: int = Query(..., ge=1990, le=2100),
    window: int = Query(1, ge=1, le=5),
    top_k: int = Query(15, ge=1, le=50),
    conferences: Optional[str] = Query(None),
):
    confs = [c.strip().lower() for c in conferences.split(",")] if conferences else None
    with connect() as conn:
        return queries.topic_evolution(
            conn, q=q, year_from=year_from, year_to=year_to,
            window=window, top_k=top_k, conferences=confs,
        )


@app.get("/v1/author_trajectory")
def author_trajectory(
    name: str = Query(..., min_length=2, max_length=120),
    year_from: Optional[int] = Query(None),
    year_to: Optional[int] = Query(None),
):
    with connect() as conn:
        return queries.author_trajectory(
            conn, name=name, year_from=year_from, year_to=year_to,
        )


@app.get("/v1/field_landscape")
def field_landscape(
    q: str = Query(..., min_length=1, max_length=200),
    year: int = Query(..., ge=1990, le=2100),
    top_k: int = Query(10, ge=1, le=50),
):
    with connect() as conn:
        return queries.field_landscape(conn, q=q, year=year, top_k=top_k)


@app.get("/v1/compare_periods")
def compare_periods(
    q: str = Query(..., min_length=1, max_length=200),
    period_a_from: int = Query(..., ge=1990, le=2100),
    period_a_to: int = Query(..., ge=1990, le=2100),
    period_b_from: int = Query(..., ge=1990, le=2100),
    period_b_to: int = Query(..., ge=1990, le=2100),
    top_k: int = Query(15, ge=1, le=50),
):
    with connect() as conn:
        return queries.compare_periods(
            conn, q=q,
            period_a=(period_a_from, period_a_to),
            period_b=(period_b_from, period_b_to),
            top_k=top_k,
        )


@app.get("/v1/conference_stats/{conf}/{year}")
def conference_stats(conf: str, year: int):
    with connect() as conn:
        return queries.conference_stats(conn, conf=conf, year=year)


@app.get("/v1/top_papers/{conf}/{year}")
def top_papers(
    conf: str, year: int,
    by: str = Query("gs_citation", pattern="^(gs_citation|rating|rating_avg)$"),
    top_k: int = Query(20, ge=1, le=100),
):
    with connect() as conn:
        return queries.top_papers(conn, conf=conf, year=year, by=by, top_k=top_k)
