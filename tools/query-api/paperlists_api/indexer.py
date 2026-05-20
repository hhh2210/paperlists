"""Build a sqlite FTS5 index from the paperlists JSON corpus.

Run directly:  python -m paperlists_api.indexer <repo_root> <out.db>

The repo root is expected to contain conference subdirectories
(iclr/, nips/, cvpr/, ...) holding `<conf><year>.json` files.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Iterable

FILENAME_RE = re.compile(r"^([a-z0-9]+?)(\d{4})\.json$")

# Directories under repo root that hold paperlist JSON files.
# Anything else (tools/, .git/, etc.) is ignored.
KNOWN_CONF_DIRS = {
    "3dv", "aaai", "acl", "acml", "aistats", "alt", "automl", "coling",
    "colm", "colt", "corl", "cvpr", "eccv", "emnlp", "iccv", "iclr",
    "icml", "icra", "ijcai", "iros", "kdd", "naacl", "nips", "rss",
    "siggraph", "siggraphasia", "uai", "wacv", "www", "ai4x",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    id           INTEGER PRIMARY KEY,
    conf         TEXT NOT NULL,
    year         INTEGER NOT NULL,
    paper_id     TEXT,
    title        TEXT NOT NULL,
    abstract     TEXT,
    keywords     TEXT,
    authors      TEXT,
    affiliations TEXT,
    primary_area TEXT,
    status       TEXT,
    track        TEXT,
    site         TEXT,
    openreview   TEXT,
    pdf          TEXT,
    rating_avg   REAL,
    confidence_avg REAL,
    gs_citation  INTEGER,
    UNIQUE(conf, year, paper_id)
);

CREATE INDEX IF NOT EXISTS idx_papers_conf_year   ON papers(conf, year);
CREATE INDEX IF NOT EXISTS idx_papers_status      ON papers(status);
CREATE INDEX IF NOT EXISTS idx_papers_rating      ON papers(rating_avg);
CREATE INDEX IF NOT EXISTS idx_papers_citation    ON papers(gs_citation);

CREATE VIRTUAL TABLE IF NOT EXISTS papers_fts USING fts5(
    title, abstract, keywords, authors,
    content='papers', content_rowid='id',
    tokenize='porter unicode61'
);

CREATE TABLE IF NOT EXISTS source_files (
    path  TEXT PRIMARY KEY,
    mtime REAL NOT NULL,
    rows  INTEGER NOT NULL,
    indexed_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS papers_ai AFTER INSERT ON papers BEGIN
    INSERT INTO papers_fts(rowid, title, abstract, keywords, authors)
    VALUES (new.id, new.title, new.abstract, new.keywords, new.authors);
END;
CREATE TRIGGER IF NOT EXISTS papers_ad AFTER DELETE ON papers BEGIN
    INSERT INTO papers_fts(papers_fts, rowid, title, abstract, keywords, authors)
    VALUES ('delete', old.id, old.title, old.abstract, old.keywords, old.authors);
END;
CREATE TRIGGER IF NOT EXISTS papers_au AFTER UPDATE ON papers BEGIN
    INSERT INTO papers_fts(papers_fts, rowid, title, abstract, keywords, authors)
    VALUES ('delete', old.id, old.title, old.abstract, old.keywords, old.authors);
    INSERT INTO papers_fts(rowid, title, abstract, keywords, authors)
    VALUES (new.id, new.title, new.abstract, new.keywords, new.authors);
END;
"""


def _coerce_float(v):
    """Convert to float. Handles paperlists' [mean, std] list format."""
    if v is None or v == "":
        return None
    if isinstance(v, list):
        if not v:
            return None
        v = v[0]
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _coerce_int(v):
    if v is None or v == "":
        return None
    if isinstance(v, list):
        if not v:
            return None
        v = v[0]
    try:
        f = float(v)
        # paperlists uses -1 as a sentinel for "not crawled yet" on citations.
        # Store as NULL so it doesn't pollute aggregates.
        if f < 0:
            return None
        return int(f)
    except (TypeError, ValueError):
        return None


def _norm_str(v) -> str:
    if v is None:
        return ""
    return str(v).strip()


def discover_files(repo_root: Path) -> list[tuple[str, int, Path]]:
    """Return list of (conf, year, path) for every conference JSON file."""
    out: list[tuple[str, int, Path]] = []
    for conf_dir in sorted(repo_root.iterdir()):
        if not conf_dir.is_dir():
            continue
        if conf_dir.name not in KNOWN_CONF_DIRS:
            continue
        for fp in sorted(conf_dir.iterdir()):
            m = FILENAME_RE.match(fp.name)
            if not m:
                continue
            conf, year = m.group(1), int(m.group(2))
            out.append((conf, year, fp))
    return out


def iter_records(fp: Path) -> Iterable[dict]:
    with fp.open() as f:
        data = json.load(f)
    if isinstance(data, list):
        yield from data
    elif isinstance(data, dict):
        yield data


def ingest_file(conn: sqlite3.Connection, conf: str, year: int, fp: Path) -> int:
    cur = conn.cursor()
    cur.execute("DELETE FROM papers WHERE conf=? AND year=?", (conf, year))
    rows = []
    for rec in iter_records(fp):
        title = _norm_str(rec.get("title"))
        if not title:
            continue
        rows.append((
            conf,
            year,
            _norm_str(rec.get("id")),
            title,
            _norm_str(rec.get("abstract")),
            _norm_str(rec.get("keywords")),
            _norm_str(rec.get("author") or rec.get("author_site")),
            _norm_str(rec.get("aff_unique_norm") or rec.get("aff")),
            _norm_str(rec.get("primary_area")),
            _norm_str(rec.get("status")),
            _norm_str(rec.get("track")),
            _norm_str(rec.get("site")),
            _norm_str(rec.get("openreview")),
            _norm_str(rec.get("pdf")),
            _coerce_float(rec.get("rating_avg")),
            _coerce_float(rec.get("confidence_avg")),
            _coerce_int(rec.get("gs_citation")),
        ))
    cur.executemany(
        """
        INSERT OR IGNORE INTO papers
        (conf, year, paper_id, title, abstract, keywords, authors,
         affiliations, primary_area, status, track, site, openreview, pdf,
         rating_avg, confidence_avg, gs_citation)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        rows,
    )
    return len(rows)


def build_index(repo_root: Path, db_path: Path, *, force: bool = False) -> dict:
    repo_root = repo_root.resolve()
    db_path = db_path.resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.executescript("PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;")
    conn.executescript(SCHEMA)
    conn.executescript(TRIGGERS)

    files = discover_files(repo_root)
    existing = {row[0]: (row[1], row[2]) for row in conn.execute("SELECT path, mtime, rows FROM source_files")}

    stats = {"files_total": len(files), "files_indexed": 0, "rows_indexed": 0, "skipped": 0}
    t0 = time.time()
    for conf, year, fp in files:
        rel = str(fp.relative_to(repo_root))
        mtime = fp.stat().st_mtime
        if not force and rel in existing and abs(existing[rel][0] - mtime) < 1e-6:
            stats["skipped"] += 1
            continue
        n = ingest_file(conn, conf, year, fp)
        conn.execute(
            "INSERT OR REPLACE INTO source_files(path, mtime, rows, indexed_at) VALUES (?,?,?,?)",
            (rel, mtime, n, time.time()),
        )
        stats["files_indexed"] += 1
        stats["rows_indexed"] += n
        conn.commit()
        print(f"  indexed {rel}: {n} rows", file=sys.stderr)

    conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('built_at', ?)", (str(time.time()),))
    conn.commit()
    conn.execute("ANALYZE")
    conn.close()
    stats["elapsed_sec"] = round(time.time() - t0, 2)
    return stats


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print("usage: python -m paperlists_api.indexer <repo_root> <out.db> [--force]", file=sys.stderr)
        return 2
    force = "--force" in argv[3:]
    stats = build_index(Path(argv[1]), Path(argv[2]), force=force)
    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
