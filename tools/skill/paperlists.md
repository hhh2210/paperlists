---
name: paperlists
description: |
  Search and analyze how AI research has evolved over time, using the
  papercopilot/paperlists corpus (236k papers across 30 conferences,
  2010-present). First-class verbs are trend-focused — topic_trend,
  topic_evolution, compare_periods, author_trajectory, field_landscape —
  not just keyword search. Backed by a hosted HTTPS API; no local data
  download required.
triggers:
  - "how has <topic> evolved"
  - "trend of <topic> over years"
  - "papers on <topic> in <conference>"
  - "who is publishing on <topic>"
  - "compare <topic> between <year_a> and <year_b>"
  - "state of <field> in <year>"
  - "top papers at <conference> <year>"
  - "rating distribution of <conference>"
  - "research evolution"
  - "literature survey"
---

# Paperlists — AI research evolution tracker

Use this skill whenever the user asks how a research area has changed
over time, who publishes in a field, what landmark papers exist in a
venue/year, or wants to do **literature-survey-style analysis** without
clicking through papercopilot.com / OpenReview manually.

## When to use

Strong fit:
- "How has retrieval-augmented generation evolved 2020–2025?"
- "Compare mixture-of-experts research between 2019–2021 and 2022–2024."
- "Top-cited diffusion model papers at NeurIPS 2023."
- "Yann LeCun's papers since 2020."
- "State of mechanistic interpretability in 2024."

Weak fit (other tools are better):
- A single paper lookup by exact title → just google it.
- Live ArXiv preprints → this corpus is conference-published only.
- Full-text PDF reading → fetch the `pdf` URL separately.

## How it works

The skill is backed by a hosted HTTPS API at
**`$PAPERLISTS_API_URL`** (default: `https://paperlists.up.railway.app`).
You can call it three ways:

1. **MCP** — if `paperlists-mcp` is registered with your host, just use
   the tool names below. Prefer this when available.
2. **HTTP via the bundled script** — `scripts/paperlists.py <endpoint> [k=v ...]`.
   Use when MCP isn't configured.
3. **Direct curl** — for one-off ad-hoc queries.

## Tools / endpoints

| Tool | Endpoint | Purpose |
|---|---|---|
| `list_coverage` | `GET /v1/coverage` | What's indexed — call first if uncertain |
| `search_papers` | `GET /v1/search` | FTS5 search over title/abstract/keywords/authors |
| `get_paper` | `GET /v1/paper/{conf}/{paper_id}` | Single paper full record |
| `topic_trend` | `GET /v1/topic_trend` | Yearly volume + citation-weight for a query |
| `topic_evolution` | `GET /v1/topic_evolution` | Per-window top keywords, venues, landmark papers |
| `compare_periods` | `GET /v1/compare_periods` | Diff a topic across two year ranges |
| `author_trajectory` | `GET /v1/author_trajectory` | Researcher's papers grouped by year |
| `field_landscape` | `GET /v1/field_landscape` | Single-year snapshot of a field |
| `conference_stats` | `GET /v1/conference_stats/{conf}/{year}` | Acceptance + rating/citation summary |
| `top_papers` | `GET /v1/top_papers/{conf}/{year}` | Ranked by citation or rating |

Common params: `q` (query), `conferences` (comma list like `iclr,nips,icml`),
`year_from`/`year_to`. Abstracts are off by default to control egress —
pass `include_abstract=true` only if you need the full text.

## Worked patterns

### Pattern 1 — Research evolution in one shot
```bash
scripts/paperlists.py topic_evolution q="retrieval augmented generation" year_from=2020 year_to=2025 window=1
```
Returns per-year top keywords (e.g. dense passage → llm → multi-hop),
top venues (emnlp → iclr/nips), and landmark cited papers each year.
**This is usually the single best call** for "how did <field> evolve" questions.

### Pattern 2 — Topic drift between two eras
```bash
scripts/paperlists.py compare_periods q="vision transformer" period_a_from=2018 period_a_to=2020 period_b_from=2022 period_b_to=2024
```
Returns `emerged` / `faded` / `sustained` for keywords, authors, and
affiliations. Great for "what's new" or "what's been abandoned" narratives.

### Pattern 3 — Surveying a venue-year
```bash
scripts/paperlists.py top_papers conf=nips year=2023 by=gs_citation top_k=20
scripts/paperlists.py conference_stats conf=iclr year=2024
```

### Pattern 4 — Author-centric
```bash
scripts/paperlists.py author_trajectory name="Yann LeCun" year_from=2020
```
Use the canonical name as it appears on publications.

## Efficiency tips for agents

- **Always `list_coverage` first** if you're unsure whether a venue/year is
  available. It's free and saves wasted calls.
- **Don't fetch abstracts unless you need them.** `include_abstract=true`
  multiplies response size ~30×.
- **Prefer `topic_evolution` over many `search_papers` calls** when the user
  wants temporal analysis — one call gives you the structured story.
- **Set `limit` aggressively low** (5–10) on exploratory `search_papers`
  calls; raise it only after the user confirms direction.
- **Hyphens and stop-words are handled** server-side ("in-context learning"
  works; FTS5 syntax like `"exact phrase"` and `term1 OR term2` works too).

## Bundled script

`scripts/paperlists.py` is a minimal Python CLI that talks to the same API
the MCP server uses. Useful when MCP isn't available. See `scripts/paperlists.py --help`.
