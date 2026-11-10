#!/usr/bin/env python3
"""
Fetch the provisional 2026 feed (mike10010100/elections-2026) with a coverage
check, falling back to the newest upstream commit that passes it.

Why: the upstream feed auto-updates every ~15 minutes and has silently
regressed before (2026-11-09 ~21:30Z it began emitting 2026 House results
("h26") only for at-large states — 164 counties instead of ~3,100). Rebuilding
from such a snapshot extrapolates the whole 2026 surface from a handful of
states and produces nonsense swings (e.g. California "swinging R").

Usage: fetch_2026.py <out_dir> [min_h26_counties]
Writes county_shifts.json, overview.json and source_commit.json to <out_dir>.
Set GITHUB_TOKEN to raise the API rate limit (used in CI).
"""
from __future__ import annotations
import json
import os
import sys
import urllib.request
from pathlib import Path

REPO = "mike10010100/elections-2026"
FILES = ("county_shifts.json", "overview.json")
MAX_COMMITS = 300  # how far back to search for a good snapshot


def _get(url: str, api: bool = False) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "political-weather-fetch"})
    tok = os.environ.get("GITHUB_TOKEN")
    if api and tok:
        req.add_header("Authorization", f"Bearer {tok}")
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def raw(ref: str, name: str) -> bytes:
    return _get(f"https://raw.githubusercontent.com/{REPO}/{ref}/site_data/{name}")


def h26_count(blob: bytes) -> int:
    counties = json.loads(blob)["counties"]
    return sum(1 for c in counties.values() if (c.get("h26") or {}).get("d") is not None)


def commits() -> list[tuple[str, str]]:
    out, page = [], 1
    while len(out) < MAX_COMMITS:
        url = (f"https://api.github.com/repos/{REPO}/commits"
               f"?path=site_data/county_shifts.json&per_page=100&page={page}")
        batch = json.loads(_get(url, api=True))
        if not batch:
            break
        out += [(c["sha"], c["commit"]["committer"]["date"]) for c in batch]
        page += 1
    return out[:MAX_COMMITS]


def main():
    out_dir = Path(sys.argv[1])
    min_n = int(sys.argv[2]) if len(sys.argv) > 2 else 2500
    out_dir.mkdir(parents=True, exist_ok=True)

    hist = commits()  # newest first
    if not hist:
        sys.exit("ERROR: could not list upstream commits")

    cache: dict[int, tuple[bytes, int]] = {}
    def check(i):
        if i not in cache:
            blob = raw(hist[i][0], "county_shifts.json")
            cache[i] = (blob, h26_count(blob))
            print(f"  {hist[i][0][:7]} {hist[i][1]}  h26 counties = {cache[i][1]}")
        return cache[i][1] >= min_n

    print(f"Checking latest upstream snapshot (need >= {min_n} counties with 2026 House)...")
    if check(0):
        good = 0
    else:
        # Find the newest good commit. Probe exponentially back, then bisect
        # between the last bad and first good probe (assumes one transition
        # in that window; the chosen commit is verified good regardless).
        bad, step, lo = 0, 1, None
        while True:
            i = min(bad + step, len(hist) - 1)
            if check(i):
                lo = i
                break
            if i == len(hist) - 1:
                sys.exit(f"ERROR: no upstream snapshot in the last {len(hist)} commits "
                         f"has >= {min_n} counties with 2026 House results")
            bad, step = i, step * 2
        while lo - bad > 1:
            mid = (bad + lo) // 2
            if check(mid):
                lo = mid
            else:
                bad = mid
        good = lo
        print(f"WARNING: latest upstream is degraded; falling back to "
              f"{hist[good][0][:7]} ({hist[good][1]}), {good} commits behind HEAD")

    sha, date = hist[good]
    (out_dir / "county_shifts.json").write_bytes(cache[good][0])
    (out_dir / "overview.json").write_bytes(raw(sha, "overview.json"))
    json.dump({"repo": REPO, "sha": sha, "commit_date": date,
               "h26_counties": cache[good][1], "latest_sha": hist[0][0],
               "fell_back": good != 0, "commits_behind": good},
              open(out_dir / "source_commit.json", "w"), indent=1)
    print(f"Wrote 2026 feed from {sha[:7]} ({date}) to {out_dir}")


if __name__ == "__main__":
    main()
