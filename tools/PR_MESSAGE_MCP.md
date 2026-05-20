# Proposal + implementation: MCP-native query layer for paperlists

Hi @jingyangcarl 👋 — long time no see. I'm the contributor of #7 (the
Streamlit local search tool). Two threads of context before the proposal:

1. Thank you again for the back-and-forth during my junior research days —
   that conversation shaped how I think about open data infra.
2. I've since started a few research projects of my own, and this dataset
   has been the single most useful conference-paper resource I keep coming
   back to. The cross-venue, multi-year, review-score coverage is genuinely
   hard to find elsewhere.

## Motivation

In the year since #7 landed, the "interface to data" has shifted from
human-facing UIs to AI-agent-facing tool calls. Spinning up a localhost
Streamlit each time is strictly worse UX than letting a coding agent
(Claude Code / Cursor / Codex / Claude Desktop) query the corpus directly.
I think `paperlists` is ready for a first-class AI-native entry point —
and as a bonus, this further offloads work from papercopilot.com's web
search (the same motivation that drove #7).

Plain keyword search is already well served by your website. The killer
feature of an MCP layer isn't another search box — it's **research
evolution tracking**: "how did RAG evolve 2020→2025", "what changed in
vision-transformer research between 2018–2020 and 2022–2024", "state of
mechanistic interpretability in 2024". These questions are awkward on a
web UI and natural for an agent. I've built the verbs around that.

## What's in this PR

A three-tier architecture, all under `tools/`. Nothing outside `tools/` is
touched (zero changes to the data layout):

```
tools/
  query-api/        # FastAPI + sqlite FTS5 service (deployable)
    paperlists_api/
      indexer.py    # builds papers.db from the JSON files
      queries.py    # all query primitives (separable, testable)
      main.py       # FastAPI app with rate limiting + abstract gating
      db.py         # read-only sqlite connection helper
    Dockerfile      # multi-stage: builder bakes the index, runtime is lean
    railway.json    # one-click deploy config
    pyproject.toml
    README.md
  mcp-server/       # thin MCP client, ~5MB install
    paperlists_mcp/
      server.py     # 10 MCP tools mapped to the API endpoints
    pyproject.toml
    README.md
  skill/            # cross-tool Skill (Claude Code / Cursor / Codex / ...)
    paperlists.md   # frontmatter + worked patterns
    scripts/
      paperlists.py # stdlib-only CLI client (when MCP isn't configured)
```

### Endpoints (the trend-focused ones are first-class)

| Endpoint | Purpose |
|---|---|
| `GET /v1/topic_trend` | **Yearly paper count + citation-weighted volume** for a query, broken down by venue |
| `GET /v1/topic_evolution` | **Per-window top co-occurring keywords + landmark papers** — surfaces topic drift |
| `GET /v1/compare_periods` | **Diff a topic across two year ranges** — emerged / faded / sustained, on keywords/authors/affiliations |
| `GET /v1/author_trajectory` | A researcher's papers grouped by year |
| `GET /v1/field_landscape` | Single-year snapshot of a field: top papers, authors, affiliations, keywords |
| `GET /v1/conference_stats/{conf}/{year}` | Acceptance + rating/citation summary |
| `GET /v1/top_papers/{conf}/{year}` | Ranked by citation or rating |
| `GET /v1/search` | Standard FTS5 search |
| `GET /v1/paper/{conf}/{id}` | Single-record full schema |
| `GET /v1/coverage` | Self-describing — what venues/years are indexed |

The MCP server exposes the same surface as 10 tools. Tool descriptions
explicitly steer agents toward `topic_evolution` / `compare_periods` when
the user asks evolution-shaped questions.

## What I've already verified (locally)

- Index builds in **~30s** from the 293 JSON files; final DB **~578 MB**.
- 218k papers (after `(conf, year, paper_id)` dedup) indexed across 30 conferences.
- All endpoints return real, well-shaped data. A couple of examples:
  - `topic_trend("diffusion model", 2018, 2024)` → 17 → 17 → 22 → 58 → 131 → **739** → **2401** papers/year (matches the well-known explosion).
  - `topic_evolution("in-context learning", 2020, 2024, window=2)` → top keywords drift from `deep learning / reinforcement learning` (2020-21) to `in-context learning / large language models` (2022+); venue mix shifts ICLR/NeurIPS → +EMNLP.
  - `compare_periods("vision transformer", 2018-2020 vs 2022-2024)` → 111 → 2112 papers; `vision transformer` itself surfaces as the dominant emerged keyword.
  - `author_trajectory("Yann LeCun", year_from=2018)` → 91 papers across years with correct landmark works.
- Sqlite FTS5 query sanitization handles hyphens and special chars (e.g. `"in-context learning"` works without breaking FTS syntax).
- Rate limiter (token bucket, default 60 req/min/IP) tested with a burst.

## Deployment plan (egress + sustainability)

Two things to flag honestly:

**Hosting**: I'll deploy a demo to **Railway** under my account (env-var-driven; nothing repo-private). The MCP/Skill default to that URL but anyone can point at their own instance via `PAPERLISTS_API_URL`. If you'd rather it live on `papercopilot` infra (Railway, HF Spaces under `papercopilot` org, your own server), I'm happy to hand it over or co-administer — no strings attached.

**Egress / cost control**:
- `include_abstract` defaults to `false` on `/v1/search`; abstracts only go out through `/v1/paper/{conf}/{id}` (one-at-a-time).
- Token-bucket rate limiter at 60 req/min/IP (configurable).
- If traffic grows beyond the free tier, the same Dockerfile redeploys to **Cloudflare Workers + D1** (near-zero idle cost) or **HF Spaces** (free, ML-community-native). No code changes required, only the DB driver.

## What's intentionally NOT in this PR

- No changes to existing data layout (still your `<conf>/<conf><year>.json` layout)
- No removal of `app.py` or `extract.py` — the Streamlit tool stays
- No embedding-based / semantic search — deferred; would need a vector DB
- No affiliation normalization across `aff_unique_norm` variants — left for v2

## What I'm asking before merge

1. **Location**: is `tools/{query-api,mcp-server,skill}/` the right home, or
   would you prefer a separate repo under `papercopilot/`? (e.g.
   `papercopilot/paperlists-mcp`)
2. **Naming**: `paperlists-mcp` vs `papercopilot-mcp` — your call.
3. **Hosting ownership**: happy to host the demo myself for v1; happy to
   hand it to you once it stabilizes. Whichever you prefer.
4. **API surface**: anything missing? `aff_*` fields are the obvious one I
   underweighted — easy to add if useful.

I tried to keep the diff strictly additive so it's easy to revert if any
piece doesn't land. Looking forward to your read.

— @hhh2210
