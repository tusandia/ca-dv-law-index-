"""Cross-check the flagging tool against LegiScan's full-text bill search.

The tool reads only each bill's title, subject and Legislative Counsel's Digest.
LegiScan (https://legiscan.com) searches the full text with its own engine. Bills
LegiScan finds that the tool did not flag are candidates for new lexicon terms
or codebook rules; flagged bills LegiScan never returns show where the tool
reaches further than plain keyword search.

LegiScan is NOT a gold standard. It is a second, independent keyword system, so
report it next to the hand-coded evaluation, not instead of it.

Needs a free API key from https://legiscan.com/legiscan, in the environment
variable LEGISCAN_API_KEY, and network access to api.legiscan.com.

Usage:
    python legiscan_check.py                       # current session, default queries
    python legiscan_check.py --year 3              # 1 all, 2 current, 3 recent, 4 prior
    python legiscan_check.py --flags ../web/data/bills.json

Writes results/legiscan_check.md and results/legiscan_hits.csv.
API responses are cached in data/raw/legiscan/ so re-runs don't spend queries
(the free tier allows 30,000 queries a month; one run uses about 20).
"""

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
CACHE = HERE / "data" / "raw" / "legiscan"
API = "https://api.legiscan.com/"

# One query per codebook concept. LegiScan supports quoted phrases, AND, OR, NOT.
QUERIES = {
    "domestic violence": '"domestic violence"',
    "intimate partner / dating / family violence": '"intimate partner" OR "dating violence" OR "family violence"',
    "coercive control / economic abuse": '"coercive control" OR "economic abuse" OR "coerced debt"',
    "protective and restraining orders": '"protective order" OR "restraining order"',
    "U and T visas, VAWA": '"U visa" OR "T visa" OR "Violence Against Women Act" OR "nonimmigrant status"',
    "victims and housing": 'victim AND (tenant OR lease OR eviction OR "unlawful detainer")',
    "victims and custody": 'victim AND (custody OR visitation)',
    "victims and firearms": '(victim OR abuse) AND (firearm OR ammunition) AND order',
    "survivors": 'survivor AND (abuse OR violence OR assault)',
    "forced marriage, dowry, abandonment": '"forced marriage" OR "coerced marriage" OR dowry OR "transnational abandonment"',
    "address confidentiality": '"Safe at Home" OR "address confidentiality"',
    "interpreters for victims": '(interpreter OR "language access") AND victim',
}


def call(op, key, **params):
    params = {"key": key, "op": op, **params}
    tag = hashlib.sha256(json.dumps({k: v for k, v in params.items() if k != "key"}, sort_keys=True).encode()).hexdigest()[:16]
    cached = CACHE / f"{op}_{tag}.json"
    if cached.exists():
        return json.loads(cached.read_text())
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "dv-law-index/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read().decode("utf-8"))
    if data.get("status") != "OK":
        raise RuntimeError(f"LegiScan {op} failed: {data.get('alert', data)}")
    CACHE.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps(data))
    time.sleep(0.5)
    return data


def search_all(key, state, query, year, max_pages=10):
    """All results for one query, following pages."""
    hits, page = [], 1
    while page <= max_pages:
        res = call("getSearch", key, state=state, query=query, year=year, page=page)["searchresult"]
        summary = res.get("summary", {})
        hits += [v for k, v in res.items() if k != "summary"]
        if page >= int(summary.get("page_total", 1) or 1):
            break
        page += 1
    return hits


def measure(bill_number):
    """'AB1753' -> 'AB 1753'; None for resolutions and other measure types."""
    m = re.match(r"^(AB|SB)\s*0*(\d+)$", bill_number or "")
    return f"{m.group(1)} {m.group(2)}" if m else None


def load_flags(path):
    path = Path(path)
    if path.suffix == ".json":
        return {b["m"]: b for b in json.loads(path.read_text())}
    with open(path, newline="", encoding="utf-8") as f:
        return {r["measure"]: {"m": r["measure"], "l": r["pred_label"], "s": r["subject"]}
                for r in csv.DictReader(f) if r["pred_label"] in ("direct", "indirect")}


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--state", default="CA")
    p.add_argument("--year", type=int, default=2, help="1 all, 2 current, 3 recent, 4 prior (LegiScan codes)")
    p.add_argument("--flags", default=HERE.parent / "web" / "data" / "bills.json")
    p.add_argument("--out", default=HERE / "results")
    args = p.parse_args()

    key = os.environ.get("LEGISCAN_API_KEY")
    if not key:
        sys.exit("Set LEGISCAN_API_KEY (free key from https://legiscan.com/legiscan).")

    flagged = load_flags(args.flags)
    found = {}   # measure -> {"title", "url", "last_action", "queries": set(), "relevance": max}
    for name, q in QUERIES.items():
        for h in search_all(key, args.state, q, args.year):
            m = measure(h.get("bill_number"))
            if not m:
                continue
            rec = found.setdefault(m, {"title": h.get("title", ""), "url": h.get("url", ""),
                                       "last_action": h.get("last_action", ""), "queries": set(), "relevance": 0})
            rec["queries"].add(name)
            rec["relevance"] = max(rec["relevance"], int(h.get("relevance") or 0))
        print(f"{name}: {sum(name in r['queries'] for r in found.values())} bills")

    both = sorted(set(found) & set(flagged))
    only_ls = sorted(set(found) - set(flagged), key=lambda m: (-found[m]["relevance"], m))
    only_tool = sorted(set(flagged) - set(found))

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "legiscan_hits.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["measure", "in_tool", "tool_label", "legiscan_relevance", "queries", "title", "last_action", "legiscan_url"])
        for m in sorted(found, key=lambda m: (-found[m]["relevance"], m)):
            r = found[m]
            w.writerow([m, m in flagged, flagged.get(m, {}).get("l", ""), r["relevance"],
                        "; ".join(sorted(r["queries"])), r["title"], r["last_action"], r["url"]])

    lines = [
        "# LegiScan full-text search vs. the flagging tool", "",
        f"{len(found)} AB/SB bills returned by {len(QUERIES)} LegiScan searches ({args.state}, year code {args.year}); "
        f"{len(flagged)} bills flagged by the tool.", "",
        "| | Bills |", "|---|---|",
        f"| Found by both | {len(both)} |",
        f"| LegiScan only (candidate misses) | {len(only_ls)} |",
        f"| Tool only | {len(only_tool)} |", "",
        "LegiScan is a second keyword system, not a gold standard. Read the "
        "\"LegiScan only\" bills and code them: each one that is truly relevant "
        "points to a missing term or rule; each one that isn't shows a false hit "
        "the tool avoided.", "",
        "## LegiScan only: candidate misses", "",
        "| Bill | Relevance | Found by | Title |", "|---|---|---|---|",
    ]
    lines += [f"| [{m}]({found[m]['url']}) | {found[m]['relevance']} | {'; '.join(sorted(found[m]['queries']))} | "
              f"{found[m]['title'][:140]} |" for m in only_ls]
    lines += ["", "## Tool only: flagged, but no LegiScan search returned them", "",
              "| Bill | Label | Subject |", "|---|---|---|"]
    lines += [f"| {m} | {flagged[m].get('l', '')} | {flagged[m].get('s', '')[:120]} |" for m in only_tool]
    (out / "legiscan_check.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"both {len(both)}, LegiScan only {len(only_ls)}, tool only {len(only_tool)} -> {out / 'legiscan_check.md'}")


if __name__ == "__main__":
    main()
