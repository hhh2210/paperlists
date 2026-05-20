"""Query primitives over the sqlite index.

Kept separate from the FastAPI layer so the same functions can be reused
from CLI tests, notebooks, or an offline `--mode local` MCP fallback.
"""
from __future__ import annotations

import re
import sqlite3
from collections import Counter
from typing import Iterable, Optional

EXCLUDED_STATUSES_DEFAULT = ("Withdraw", "Reject", "Withdrawn", "Rejected", "Desk Reject")

# FTS5 sanitizer.
# - Strip characters that aren't word/space/quote.
# - Treat hyphens as spaces (FTS5 reads `-token` as "NOT token", which breaks
#   queries like "in-context learning"). Quoted hyphens are also fragile, so
#   the safest behavior is plain whitespace AND.
_FTS_BAD = re.compile(r"[^\w\s\"]+", flags=re.UNICODE)


def sanitize_fts(q: str) -> str:
    q = (q or "").replace("-", " ")
    q = _FTS_BAD.sub(" ", q)
    return " ".join(q.split())


def _conf_filter(confs: Optional[list[str]]) -> tuple[str, list]:
    if not confs:
        return "", []
    placeholders = ",".join("?" * len(confs))
    return f" AND p.conf IN ({placeholders})", [c.lower() for c in confs]


def _year_filter(year_from: Optional[int], year_to: Optional[int]) -> tuple[str, list]:
    parts, params = [], []
    if year_from is not None:
        parts.append("p.year >= ?")
        params.append(year_from)
    if year_to is not None:
        parts.append("p.year <= ?")
        params.append(year_to)
    if not parts:
        return "", []
    return " AND " + " AND ".join(parts), params


def _exclude_rejected_filter(exclude: bool) -> tuple[str, list]:
    if not exclude:
        return "", []
    placeholders = ",".join("?" * len(EXCLUDED_STATUSES_DEFAULT))
    return f" AND (p.status IS NULL OR p.status NOT IN ({placeholders}))", list(EXCLUDED_STATUSES_DEFAULT)


def _row_to_card(row: dict, *, include_abstract: bool) -> dict:
    out = {
        "conf": row["conf"],
        "year": row["year"],
        "paper_id": row["paper_id"],
        "title": row["title"],
        "authors": row["authors"],
        "status": row["status"],
        "track": row["track"],
        "site": row["site"],
        "openreview": row["openreview"],
        "pdf": row["pdf"],
        "rating_avg": row["rating_avg"],
        "gs_citation": row["gs_citation"],
        "keywords": row["keywords"],
        "primary_area": row["primary_area"],
    }
    if include_abstract:
        out["abstract"] = row["abstract"]
    return out


def search_papers(
    conn: sqlite3.Connection,
    *,
    q: str,
    conferences: Optional[list[str]] = None,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    exclude_rejected: bool = True,
    limit: int = 50,
    offset: int = 0,
    order_by: str = "relevance",
    include_abstract: bool = False,
) -> dict:
    """Full-text search across title/abstract/keywords/authors."""
    q_clean = sanitize_fts(q)
    if not q_clean:
        return {"total": 0, "results": []}

    conf_sql, conf_params = _conf_filter(conferences)
    year_sql, year_params = _year_filter(year_from, year_to)
    excl_sql, excl_params = _exclude_rejected_filter(exclude_rejected)

    order_sql = {
        "relevance": "bm25(papers_fts)",
        "year_desc": "p.year DESC, bm25(papers_fts)",
        "citation_desc": "p.gs_citation DESC NULLS LAST, bm25(papers_fts)",
        "rating_desc": "p.rating_avg DESC NULLS LAST, bm25(papers_fts)",
    }.get(order_by, "bm25(papers_fts)")

    sql = f"""
        SELECT p.*
        FROM papers_fts
        JOIN papers p ON p.id = papers_fts.rowid
        WHERE papers_fts MATCH ?
          {conf_sql}{year_sql}{excl_sql}
        ORDER BY {order_sql}
        LIMIT ? OFFSET ?
    """
    params = [q_clean, *conf_params, *year_params, *excl_params, limit, offset]
    rows = conn.execute(sql, params).fetchall()

    count_sql = f"""
        SELECT COUNT(*) AS n
        FROM papers_fts
        JOIN papers p ON p.id = papers_fts.rowid
        WHERE papers_fts MATCH ?
          {conf_sql}{year_sql}{excl_sql}
    """
    total = conn.execute(count_sql, [q_clean, *conf_params, *year_params, *excl_params]).fetchone()["n"]

    return {
        "total": total,
        "results": [_row_to_card(r, include_abstract=include_abstract) for r in rows],
    }


def get_paper(conn: sqlite3.Connection, conf: str, paper_id: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT * FROM papers WHERE conf=? AND paper_id=? LIMIT 1",
        (conf.lower(), paper_id),
    ).fetchone()
    if not row:
        return None
    out = _row_to_card(row, include_abstract=True)
    out["affiliations"] = row["affiliations"]
    out["confidence_avg"] = row["confidence_avg"]
    return out


def coverage(conn: sqlite3.Connection) -> dict:
    rows = conn.execute(
        "SELECT conf, year, COUNT(*) AS n FROM papers GROUP BY conf, year ORDER BY conf, year"
    ).fetchall()
    by_conf: dict[str, dict] = {}
    total = 0
    for r in rows:
        d = by_conf.setdefault(r["conf"], {"years": {}, "total": 0})
        d["years"][r["year"]] = r["n"]
        d["total"] += r["n"]
        total += r["n"]
    built_at = conn.execute("SELECT value FROM meta WHERE key='built_at'").fetchone()
    return {
        "total_papers": total,
        "conferences": by_conf,
        "built_at": float(built_at["value"]) if built_at else None,
    }


# ---------- Research-evolution endpoints ----------

def topic_trend(
    conn: sqlite3.Connection,
    *,
    q: str,
    conferences: Optional[list[str]] = None,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    exclude_rejected: bool = True,
) -> dict:
    """Yearly paper count + citation-weighted volume for a topic query."""
    q_clean = sanitize_fts(q)
    if not q_clean:
        return {"query": q, "series": []}

    conf_sql, conf_params = _conf_filter(conferences)
    year_sql, year_params = _year_filter(year_from, year_to)
    excl_sql, excl_params = _exclude_rejected_filter(exclude_rejected)

    sql = f"""
        SELECT p.year AS year,
               p.conf AS conf,
               COUNT(*) AS papers,
               COALESCE(SUM(p.gs_citation), 0) AS citations,
               AVG(p.rating_avg) AS avg_rating
        FROM papers_fts
        JOIN papers p ON p.id = papers_fts.rowid
        WHERE papers_fts MATCH ?
          {conf_sql}{year_sql}{excl_sql}
        GROUP BY p.year, p.conf
        ORDER BY p.year, p.conf
    """
    params = [q_clean, *conf_params, *year_params, *excl_params]
    rows = conn.execute(sql, params).fetchall()

    # Also yearly totals (any conference matching) for denominator/visualization.
    yearly: dict[int, dict] = {}
    for r in rows:
        bucket = yearly.setdefault(r["year"], {"year": r["year"], "papers": 0, "citations": 0, "by_conf": {}})
        bucket["papers"] += r["papers"]
        bucket["citations"] += r["citations"]
        bucket["by_conf"][r["conf"]] = {"papers": r["papers"], "citations": r["citations"]}
    return {
        "query": q,
        "series": [yearly[y] for y in sorted(yearly)],
    }


# Stop-words to drop when extracting keyword/term drift.
_STOPWORDS = set("""
a an and are as at be by for from has have in is it its of on or such that the their then there these to was were will with we our you your this they them than but not no any all can may use using used new novel model models method methods learning deep neural network networks based approach paper task tasks
""".split())


def _tokenize_keywords(s: str) -> Iterable[str]:
    if not s:
        return []
    # paperlists separates keywords with semicolons; fall back to splitting on commas/newlines.
    parts = re.split(r"[;,\n]", s)
    out = []
    for p in parts:
        kw = p.strip().lower()
        if kw and kw not in _STOPWORDS and len(kw) > 1:
            out.append(kw)
    return out


def topic_evolution(
    conn: sqlite3.Connection,
    *,
    q: str,
    year_from: int,
    year_to: int,
    window: int = 1,
    top_k: int = 15,
    conferences: Optional[list[str]] = None,
) -> dict:
    """Per-year (or per-window) top co-occurring keywords and top venues.

    For each year window, fetch papers matching `q` and aggregate keyword
    frequencies. Surfaces topic drift inside a research area.
    """
    q_clean = sanitize_fts(q)
    if not q_clean or year_from > year_to:
        return {"query": q, "windows": []}

    conf_sql, conf_params = _conf_filter(conferences)

    windows = []
    y = year_from
    while y <= year_to:
        w_end = min(y + window - 1, year_to)
        sql = f"""
            SELECT p.keywords AS keywords, p.conf AS conf, p.title AS title,
                   p.gs_citation AS cites, p.year AS year, p.paper_id AS paper_id
            FROM papers_fts
            JOIN papers p ON p.id = papers_fts.rowid
            WHERE papers_fts MATCH ?
              AND p.year BETWEEN ? AND ?
              {conf_sql}
        """
        rows = conn.execute(sql, [q_clean, y, w_end, *conf_params]).fetchall()

        kw_counter: Counter[str] = Counter()
        conf_counter: Counter[str] = Counter()
        for r in rows:
            for kw in _tokenize_keywords(r["keywords"]):
                kw_counter[kw] += 1
            if r["conf"]:
                conf_counter[r["conf"]] += 1

        # Surface top-cited paper of the window as a "landmark".
        landmarks = sorted(
            [r for r in rows if r["cites"]],
            key=lambda r: r["cites"] or 0,
            reverse=True,
        )[:5]

        windows.append({
            "year_from": y,
            "year_to": w_end,
            "n_papers": len(rows),
            "top_keywords": kw_counter.most_common(top_k),
            "top_venues": conf_counter.most_common(10),
            "landmark_papers": [
                {"conf": r["conf"], "year": r["year"], "paper_id": r["paper_id"],
                 "title": r["title"], "gs_citation": r["cites"]}
                for r in landmarks
            ],
        })
        y = w_end + 1

    return {"query": q, "window": window, "windows": windows}


def author_trajectory(
    conn: sqlite3.Connection,
    *,
    name: str,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
) -> dict:
    """List papers by an author across years, grouped for trajectory analysis."""
    if not name or not name.strip():
        return {"name": name, "by_year": []}

    # We match against the `authors` FTS column as an exact-phrase token.
    q_phrase = f'authors:"{sanitize_fts(name)}"'
    year_sql, year_params = _year_filter(year_from, year_to)
    sql = f"""
        SELECT p.year, p.conf, p.paper_id, p.title, p.authors, p.gs_citation, p.status
        FROM papers_fts
        JOIN papers p ON p.id = papers_fts.rowid
        WHERE papers_fts MATCH ?
          {year_sql}
        ORDER BY p.year DESC, p.gs_citation DESC NULLS LAST
    """
    rows = conn.execute(sql, [q_phrase, *year_params]).fetchall()

    by_year: dict[int, list] = {}
    for r in rows:
        # Confirm name actually appears (case-insensitive) — FTS porter stemming can over-match.
        if name.lower() not in (r["authors"] or "").lower():
            continue
        by_year.setdefault(r["year"], []).append({
            "conf": r["conf"], "paper_id": r["paper_id"], "title": r["title"],
            "authors": r["authors"], "gs_citation": r["gs_citation"], "status": r["status"],
        })

    return {
        "name": name,
        "total_papers": sum(len(v) for v in by_year.values()),
        "by_year": [
            {"year": y, "papers": by_year[y]} for y in sorted(by_year, reverse=True)
        ],
    }


def field_landscape(
    conn: sqlite3.Connection,
    *,
    q: str,
    year: int,
    top_k: int = 10,
) -> dict:
    """Single-year snapshot for a field: top papers, top authors, top affiliations,
    top keywords. Useful for 'state of <field> in <year>' summaries."""
    q_clean = sanitize_fts(q)
    if not q_clean:
        return {"query": q, "year": year}

    rows = conn.execute(
        """
        SELECT p.conf, p.year, p.paper_id, p.title, p.authors, p.affiliations,
               p.keywords, p.gs_citation, p.rating_avg, p.status, p.openreview, p.site
        FROM papers_fts
        JOIN papers p ON p.id = papers_fts.rowid
        WHERE papers_fts MATCH ? AND p.year = ?
        """,
        [q_clean, year],
    ).fetchall()

    author_counter: Counter[str] = Counter()
    aff_counter: Counter[str] = Counter()
    kw_counter: Counter[str] = Counter()
    venue_counter: Counter[str] = Counter()
    for r in rows:
        for a in (r["authors"] or "").split(";"):
            a = a.strip()
            if a:
                author_counter[a] += 1
        for af in (r["affiliations"] or "").split(";"):
            af = af.strip()
            if af:
                aff_counter[af] += 1
        for kw in _tokenize_keywords(r["keywords"]):
            kw_counter[kw] += 1
        if r["conf"]:
            venue_counter[r["conf"]] += 1

    top_papers = sorted(
        rows, key=lambda r: (r["gs_citation"] or 0, r["rating_avg"] or 0), reverse=True
    )[:top_k]

    return {
        "query": q,
        "year": year,
        "n_papers": len(rows),
        "top_papers": [
            {"conf": r["conf"], "paper_id": r["paper_id"], "title": r["title"],
             "authors": r["authors"], "gs_citation": r["gs_citation"],
             "rating_avg": r["rating_avg"], "openreview": r["openreview"], "site": r["site"]}
            for r in top_papers
        ],
        "top_authors": author_counter.most_common(top_k),
        "top_affiliations": aff_counter.most_common(top_k),
        "top_keywords": kw_counter.most_common(top_k),
        "venue_distribution": venue_counter.most_common(),
    }


def compare_periods(
    conn: sqlite3.Connection,
    *,
    q: str,
    period_a: tuple[int, int],
    period_b: tuple[int, int],
    top_k: int = 15,
) -> dict:
    """Diff a topic between two year ranges. Returns keywords/authors/affiliations
    that emerged, disappeared, or stayed across the two periods."""
    def _bucket(years: tuple[int, int]) -> dict:
        q_clean = sanitize_fts(q)
        rows = conn.execute(
            """
            SELECT p.authors, p.affiliations, p.keywords, p.title, p.paper_id, p.conf, p.year, p.gs_citation
            FROM papers_fts
            JOIN papers p ON p.id = papers_fts.rowid
            WHERE papers_fts MATCH ? AND p.year BETWEEN ? AND ?
            """,
            [q_clean, years[0], years[1]],
        ).fetchall()
        authors: Counter[str] = Counter()
        affs: Counter[str] = Counter()
        kws: Counter[str] = Counter()
        for r in rows:
            for a in (r["authors"] or "").split(";"):
                a = a.strip()
                if a:
                    authors[a] += 1
            for af in (r["affiliations"] or "").split(";"):
                af = af.strip()
                if af:
                    affs[af] += 1
            for kw in _tokenize_keywords(r["keywords"]):
                kws[kw] += 1
        return {"n_papers": len(rows), "authors": authors, "affiliations": affs, "keywords": kws}

    a = _bucket(period_a)
    b = _bucket(period_b)

    def _diff(ca: Counter, cb: Counter, k: int):
        emerged = [(x, cb[x]) for x in cb if x not in ca]
        emerged.sort(key=lambda t: t[1], reverse=True)
        faded = [(x, ca[x]) for x in ca if x not in cb]
        faded.sort(key=lambda t: t[1], reverse=True)
        sustained = [(x, ca[x], cb[x]) for x in ca if x in cb]
        sustained.sort(key=lambda t: t[1] + t[2], reverse=True)
        return {
            "emerged": emerged[:k],
            "faded": faded[:k],
            "sustained": sustained[:k],
        }

    return {
        "query": q,
        "period_a": {"years": period_a, "n_papers": a["n_papers"]},
        "period_b": {"years": period_b, "n_papers": b["n_papers"]},
        "keyword_diff": _diff(a["keywords"], b["keywords"], top_k),
        "author_diff": _diff(a["authors"], b["authors"], top_k),
        "affiliation_diff": _diff(a["affiliations"], b["affiliations"], top_k),
    }


def conference_stats(conn: sqlite3.Connection, *, conf: str, year: int) -> dict:
    rows = conn.execute(
        "SELECT status, track, rating_avg, gs_citation FROM papers WHERE conf=? AND year=?",
        (conf.lower(), year),
    ).fetchall()
    status_counter: Counter[str] = Counter()
    track_counter: Counter[str] = Counter()
    ratings = []
    cites = []
    for r in rows:
        status_counter[r["status"] or "(unknown)"] += 1
        track_counter[r["track"] or "(unknown)"] += 1
        if r["rating_avg"] is not None:
            ratings.append(r["rating_avg"])
        if r["gs_citation"] is not None:
            cites.append(r["gs_citation"])

    def _summary(xs: list[float]) -> dict:
        if not xs:
            return {"n": 0}
        xs_sorted = sorted(xs)
        n = len(xs_sorted)
        return {
            "n": n,
            "min": xs_sorted[0],
            "p25": xs_sorted[n // 4],
            "median": xs_sorted[n // 2],
            "p75": xs_sorted[(3 * n) // 4],
            "max": xs_sorted[-1],
            "mean": sum(xs_sorted) / n,
        }

    return {
        "conf": conf,
        "year": year,
        "n_papers": len(rows),
        "status_breakdown": status_counter.most_common(),
        "track_breakdown": track_counter.most_common(),
        "rating_summary": _summary(ratings),
        "citation_summary": _summary([float(c) for c in cites]),
    }


def top_papers(
    conn: sqlite3.Connection,
    *,
    conf: str,
    year: int,
    by: str = "gs_citation",
    top_k: int = 20,
) -> dict:
    by_col = {
        "gs_citation": "gs_citation",
        "rating": "rating_avg",
        "rating_avg": "rating_avg",
    }.get(by, "gs_citation")
    rows = conn.execute(
        f"""
        SELECT conf, year, paper_id, title, authors, status, track, site,
               openreview, rating_avg, gs_citation
        FROM papers
        WHERE conf=? AND year=? AND {by_col} IS NOT NULL
        ORDER BY {by_col} DESC
        LIMIT ?
        """,
        (conf.lower(), year, top_k),
    ).fetchall()
    return {"conf": conf, "year": year, "ranked_by": by_col, "results": rows}
