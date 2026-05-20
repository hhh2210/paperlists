"""MCP server for the papercopilot/paperlists corpus.

Defaults to talking to the hosted demo API; can be pointed at any deployment
via PAPERLISTS_API_URL. Designed as a thin client so the same code works
across Claude Code / Claude Desktop / Cursor / Codex / any MCP host.

Run via stdio:
    uvx --from . paperlists-mcp
    # or
    python -m paperlists_mcp.server

Env vars:
    PAPERLISTS_API_URL   default: https://paperlists.up.railway.app
    PAPERLISTS_TIMEOUT   default: 30 (seconds)
"""
from __future__ import annotations

import os
from typing import Optional

import httpx
from mcp.server.fastmcp import FastMCP

API_URL = os.environ.get("PAPERLISTS_API_URL", "https://paperlists.up.railway.app").rstrip("/")
TIMEOUT = float(os.environ.get("PAPERLISTS_TIMEOUT", "30"))

mcp = FastMCP("paperlists")
_client = httpx.Client(base_url=API_URL, timeout=TIMEOUT, headers={"User-Agent": "paperlists-mcp/0.1"})


def _get(path: str, **params) -> dict:
    # Drop None params so they don't override defaults on the server side.
    clean = {k: v for k, v in params.items() if v is not None}
    resp = _client.get(path, params=clean)
    if resp.status_code >= 400:
        return {"error": f"HTTP {resp.status_code}", "detail": resp.text[:500]}
    return resp.json()


@mcp.tool()
def list_coverage() -> dict:
    """List which conferences and years are indexed.

    Returns total paper count and a per-conference breakdown. Always call this
    first if you're unsure whether a venue/year is available — it costs no
    quota and saves wasted searches.
    """
    return _get("/v1/coverage")


@mcp.tool()
def search_papers(
    query: str,
    conferences: Optional[str] = None,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    exclude_rejected: bool = True,
    limit: int = 25,
    order_by: str = "relevance",
    include_abstract: bool = False,
) -> dict:
    """Full-text search over title / abstract / keywords / authors.

    Args:
        query: Free-text query. Multi-word terms are AND'd. FTS5 syntax works
            ("foo OR bar", "\"exact phrase\"").
        conferences: Comma-separated venue list (e.g. "iclr,nips,icml").
            Omit to search all.
        year_from / year_to: Inclusive year filter.
        exclude_rejected: Drop Reject/Withdraw entries (recommended).
        limit: Max results (1-200).
        order_by: "relevance" | "year_desc" | "citation_desc" | "rating_desc".
        include_abstract: Set true only if you need full abstracts — they
            cost ~1KB per result.
    """
    return _get(
        "/v1/search",
        q=query, conferences=conferences,
        year_from=year_from, year_to=year_to,
        exclude_rejected=exclude_rejected,
        limit=limit, order_by=order_by,
        include_abstract=include_abstract,
    )


@mcp.tool()
def get_paper(conf: str, paper_id: str) -> dict:
    """Fetch a single paper's full record including abstract and affiliations.

    Args:
        conf: Lowercase venue (e.g. "iclr", "nips").
        paper_id: The paper's `id` field from the JSON (OpenReview ID, etc.).
    """
    return _get(f"/v1/paper/{conf}/{paper_id}")


@mcp.tool()
def topic_trend(
    query: str,
    conferences: Optional[str] = None,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
) -> dict:
    """Yearly publication volume + citation-weighted volume for a topic.

    Use this to see how a research area has grown or declined over time.
    Returns a `series` of `{year, papers, citations, by_conf}` records.

    Example queries: "diffusion model", "retrieval augmented generation",
    "mixture of experts", "constitutional AI".
    """
    return _get(
        "/v1/topic_trend",
        q=query, conferences=conferences,
        year_from=year_from, year_to=year_to,
    )


@mcp.tool()
def topic_evolution(
    query: str,
    year_from: int,
    year_to: int,
    window: int = 1,
    top_k: int = 15,
    conferences: Optional[str] = None,
) -> dict:
    """Track how a research area evolves: per-window top co-occurring keywords,
    top venues, and landmark (highest-cited) papers.

    This is the single best tool for answering "how did <field> change between
    year X and year Y?" It surfaces topic drift inside a query — e.g. asking
    `topic_evolution("retrieval augmented generation", 2020, 2024, window=1)`
    will show RAG morphing from dense-passage-retrieval era into LLM-coupled
    pipelines.

    Args:
        window: years per bucket (1 = annual, 2 = biennial, ...).
        top_k: keywords/venues per window.
    """
    return _get(
        "/v1/topic_evolution",
        q=query, year_from=year_from, year_to=year_to,
        window=window, top_k=top_k, conferences=conferences,
    )


@mcp.tool()
def compare_periods(
    query: str,
    period_a_from: int,
    period_a_to: int,
    period_b_from: int,
    period_b_to: int,
    top_k: int = 15,
) -> dict:
    """Diff a topic between two year ranges. Returns three buckets per
    dimension (keywords, authors, affiliations):

    - **emerged**: present in period B but not period A
    - **faded**: present in period A but not period B
    - **sustained**: present in both, sorted by total volume

    Use when you have a hypothesis like "RLHF moved from RL conferences to
    NLP conferences between 2022 and 2024" — this tool will confirm or refute.
    """
    return _get(
        "/v1/compare_periods",
        q=query,
        period_a_from=period_a_from, period_a_to=period_a_to,
        period_b_from=period_b_from, period_b_to=period_b_to,
        top_k=top_k,
    )


@mcp.tool()
def author_trajectory(
    name: str,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
) -> dict:
    """Papers by an author across years, useful for tracking a researcher's
    topical pivots or productivity. Match is on the `authors` field — use
    the canonical name as it appears in publications.
    """
    return _get(
        "/v1/author_trajectory",
        name=name, year_from=year_from, year_to=year_to,
    )


@mcp.tool()
def field_landscape(query: str, year: int, top_k: int = 10) -> dict:
    """Snapshot a research field in a specific year: top papers (by citation),
    top authors, top affiliations, top keywords, venue distribution.

    Use for "state of <field> in <year>" summaries or to identify the dominant
    labs in a subfield at a point in time.
    """
    return _get("/v1/field_landscape", q=query, year=year, top_k=top_k)


@mcp.tool()
def conference_stats(conf: str, year: int) -> dict:
    """Acceptance breakdown + rating/citation distribution for a single
    venue-year. Useful for "how selective was ICLR 2024?" type questions."""
    return _get(f"/v1/conference_stats/{conf}/{year}")


@mcp.tool()
def top_papers(conf: str, year: int, by: str = "gs_citation", top_k: int = 20) -> dict:
    """Top-N papers from a single venue-year, ranked by `gs_citation` or
    `rating`. Returns title, authors, paper_id, URLs."""
    return _get(f"/v1/top_papers/{conf}/{year}", by=by, top_k=top_k)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
