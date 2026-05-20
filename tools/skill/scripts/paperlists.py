#!/usr/bin/env python3
"""Bundled CLI client for the paperlists hosted API.

Used by the paperlists skill when MCP isn't configured. Calls the same
endpoints as paperlists-mcp.

Usage:
    paperlists.py <endpoint> [key=value ...]

Examples:
    paperlists.py coverage
    paperlists.py search q="diffusion model" year_from=2022 limit=10
    paperlists.py topic_trend q="rlhf" year_from=2020 year_to=2025
    paperlists.py topic_evolution q="retrieval augmented" year_from=2020 year_to=2025 window=1
    paperlists.py compare_periods q="moe" period_a_from=2018 period_a_to=2020 period_b_from=2022 period_b_to=2024
    paperlists.py field_landscape q="mechanistic interpretability" year=2024
    paperlists.py author_trajectory name="Yann LeCun" year_from=2020
    paperlists.py paper conf=iclr paper_id=00SnKBGTsz
    paperlists.py conference_stats conf=iclr year=2024
    paperlists.py top_papers conf=nips year=2023 by=gs_citation top_k=10

Env: PAPERLISTS_API_URL (default https://paperlists.up.railway.app)
Dependencies: only stdlib (no requests/httpx required).
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request

API_URL = os.environ.get("PAPERLISTS_API_URL", "https://paperlists.up.railway.app").rstrip("/")

# Maps the CLI verb to (path_template, list_of_url_args).
# Path args are pulled out of kwargs; the rest become querystring.
ENDPOINTS = {
    "coverage":            ("/v1/coverage", []),
    "search":              ("/v1/search", []),
    "paper":               ("/v1/paper/{conf}/{paper_id}", ["conf", "paper_id"]),
    "topic_trend":         ("/v1/topic_trend", []),
    "topic_evolution":     ("/v1/topic_evolution", []),
    "compare_periods":     ("/v1/compare_periods", []),
    "author_trajectory":   ("/v1/author_trajectory", []),
    "field_landscape":     ("/v1/field_landscape", []),
    "conference_stats":    ("/v1/conference_stats/{conf}/{year}", ["conf", "year"]),
    "top_papers":          ("/v1/top_papers/{conf}/{year}", ["conf", "year"]),
}


def _parse_kv(args: list[str]) -> dict:
    out: dict[str, str] = {}
    for a in args:
        if "=" not in a:
            raise SystemExit(f"bad argument {a!r}; expected key=value")
        k, _, v = a.partition("=")
        out[k.strip()] = v.strip()
    return out


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(__doc__)
        return 0
    verb = argv[1]
    if verb not in ENDPOINTS:
        print(f"unknown endpoint {verb!r}. Available: {', '.join(ENDPOINTS)}", file=sys.stderr)
        return 2
    path_tpl, path_args = ENDPOINTS[verb]
    kv = _parse_kv(argv[2:])

    try:
        path = path_tpl.format(**{k: kv.pop(k) for k in path_args})
    except KeyError as e:
        print(f"missing required path arg: {e.args[0]}", file=sys.stderr)
        return 2

    qs = urllib.parse.urlencode(kv)
    url = f"{API_URL}{path}" + (f"?{qs}" if qs else "")

    req = urllib.request.Request(url, headers={"User-Agent": "paperlists-skill/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read()
    except urllib.error.HTTPError as e:
        body = e.read()
        print(f"HTTP {e.code} from {url}", file=sys.stderr)
        print(body.decode("utf-8", "replace"), file=sys.stderr)
        return 1
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    try:
        parsed = json.loads(body)
        json.dump(parsed, sys.stdout, indent=2, ensure_ascii=False)
        print()
    except json.JSONDecodeError:
        sys.stdout.write(body.decode("utf-8", "replace"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
