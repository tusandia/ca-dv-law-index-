"""Collect news headlines about California domestic violence law from RSS/Atom feeds.

Reads the feed list in ../web/data/news_sources.json, keeps items the lexicon
says are DV-related (and about California: a feed marked "california": true is a
California outlet, so its stories count without naming the state), notes any bill numbers they mention (so the site can link
a story to the bill), and merges them into ../web/data/news.json.

Only headlines, links, source names and dates are stored, never article text.
A feed that fails is skipped; the others still update.

Usage:
    python news.py
    python news.py --sources my_feeds.json
"""

import argparse
import datetime as dt
import email.utils
import html
import json
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

from flag import classify, load_lexicon

HERE = Path(__file__).parent
WEB_DATA = Path(os.environ.get("DV_WEB_DATA", HERE.parent / "web" / "data"))
UA = "dv-law-index/1.0 (+https://github.com/tusandia/ca-dv-law-index-)"
MAX_ITEMS = 300
MAX_AGE_DAYS = 365
BILL_RX = re.compile(r"\b(AB|SB)\s?-?(\d{1,4})\b")


def local(tag):
    return tag.rsplit("}", 1)[-1]


def text_of(el):
    return html.unescape(re.sub(r"<[^>]+>", " ", "".join(el.itertext()) if el is not None else "")).strip()


def parse_date(s):
    if not s:
        return ""
    try:
        d = email.utils.parsedate_to_datetime(s)        # RSS: RFC 822
    except (TypeError, ValueError):
        try:
            d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))  # Atom: ISO 8601
        except ValueError:
            return ""
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d.astimezone(dt.timezone.utc).isoformat(timespec="minutes")


def first(fields, *names):
    # Not `a or b`: an XML element with no children is falsy, even when it has text.
    for n in names:
        if fields.get(n) is not None:
            return fields[n]
    return None


def parse_feed(xml_bytes, feed_name):
    root = ET.fromstring(xml_bytes)
    out = []
    for item in root.iter():
        if local(item.tag) not in ("item", "entry"):
            continue
        f = {local(c.tag): c for c in item}
        link = f.get("link")
        href = (link.get("href") or link.text or "").strip() if link is not None else ""
        source = text_of(f.get("source")) or feed_name
        title = text_of(f.get("title"))
        if source and title.endswith(" - " + source):   # Google News appends the source
            title = title[: -len(source) - 3].rstrip()
        out.append({
            "title": title,
            "summary": text_of(first(f, "description", "summary", "content"))[:600],
            "link": href,
            "published": parse_date(text_of(first(f, "pubDate", "published", "updated"))),
            "source": source,
            "feed": feed_name,
        })
    return out


CA_RX = re.compile(
    r"california|\bCalif\.|\bCA\b|newsom|\b(AB|SB) ?\d+|cal ?oes|calmatters|"
    r"los angeles|\bL\.?A\.?\b|san francisco|oakland|san diego|san jose|sacramento|fresno|bay area|"
    r"silicon valley|alameda|contra costa|santa clara|san mateo|orange county|riverside|san bernardino|"
    r"long beach|bakersfield|stockton|napa|sonoma|ventura|santa barbara|santa monica|berkeley|"
    r"arden-arcade|inland empire|central valley")
LAW_RX = re.compile(r"\b(bills?|laws?|legislat\w*|statutes?|codes?|courts?|judges?|rulings?|polic(y|ies)|"
                    r"ordinances?|ballot|measures?|restraining orders?|protective orders?|assembly|senate|"
                    r"governor|gov\.|signs?|signed|vetoe?d?|veto|lawmakers?|attorney general|prosecut\w*|"
                    r"sentenc\w*|charged?|funding|budget|grants?)\b", re.I)


def judge(item, lexicon, california_source=False):
    """(classification, None) if the story is about California, about law or
    policy, and DV-relevant by the lexicon; otherwise (None, reason).
    Stories from a feed marked "california": true (a California outlet or
    section) are taken to be about California; others must say so."""
    text = f"{item['title']}. {item['summary']}"
    if not california_source and not re.search(CA_RX.pattern, f"{text} {item['source']}", re.I):
        return None, "not California"
    if not LAW_RX.search(text):
        return None, "no law/policy word"
    r = classify(text, lexicon)
    if r["pred_label"] not in ("direct", "indirect"):
        return None, "not DV"
    return r, None


def relevant(item, lexicon):
    return judge(item, lexicon)[0]


def norm_title(t):
    t = re.sub(r"\s+-\s+[^-]+$", "", t)  # Google News appends " - Source"
    return re.sub(r"\W+", " ", t).lower().strip()


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sources", default=WEB_DATA / "news_sources.json")
    p.add_argument("--reset", action="store_true", help="drop saved headlines and start over")
    args = p.parse_args()

    lexicon = load_lexicon()
    sources = json.loads(Path(args.sources).read_text(encoding="utf-8"))
    path = WEB_DATA / "news.json"
    items = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    if args.reset:
        items = []
    seen = {i["link"] for i in items} | {norm_title(i["title"]) for i in items}
    added = 0
    for src in sources:
        try:
            req = urllib.request.Request(src["url"], headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                entries = parse_feed(r.read(), src["name"])
        except Exception as e:  # noqa: BLE001 - one bad feed must not stop the others
            print(f"{src['name']}: {e}, skipped", file=sys.stderr)
            continue
        before = added
        why = Counter()
        for e in entries:
            if not e["title"] or not e["link"]:
                why["no title/link"] += 1
                continue
            if e["link"] in seen or norm_title(e["title"]) in seen:
                why["already saved"] += 1
                continue
            r, reason = judge(e, lexicon, src.get("california", False))
            if not r:
                why[reason] += 1
                continue
            e["label"] = r["pred_label"]
            e["areas"] = [a for a in r["pred_areas"].split(";") if a]
            e["bills"] = sorted({f"{k} {int(n)}" for k, n in BILL_RX.findall(e["title"] + " " + e["summary"])})
            e.pop("summary")
            items.append(e)
            seen |= {e["link"], norm_title(e["title"])}
            added += 1
        dropped = ", ".join(f"{n} {k}" for k, n in why.most_common())
        print(f"{src['name']}: {len(entries)} read, {added - before} kept" + (f"; dropped: {dropped}" if dropped else ""))

    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=MAX_AGE_DAYS)).isoformat()
    items = [i for i in items if not i["published"] or i["published"] >= cutoff]
    items.sort(key=lambda i: i["published"], reverse=True)
    items = items[:MAX_ITEMS]
    WEB_DATA.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{added} new headline(s); {len(items)} kept -> {path}")


if __name__ == "__main__":
    main()
