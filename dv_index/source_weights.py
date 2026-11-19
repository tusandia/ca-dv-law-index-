"""Measure how strongly DV reference sources use each lexicon term, and
suggest new terms, so lexicon weights rest on evidence rather than judgment.

For every term in lexicon.csv (and for frequent phrases from the sources that
the lexicon lacks) it reports:
    sources      how many of the reference texts use it (breadth)
    per_10k      mean rate per 10,000 words across the texts, each text counted
                 equally so a long article doesn't outweigh a short glossary
    z            weighted log-odds z-score, reference texts vs. the bill
                 summaries (Monroe, Colaresi & Quinn 2008, informative
                 Dirichlet prior). High z = distinctive of DV writing; near 0 =
                 just as common in ordinary bills
    bills        how many bill summaries contain it

The reference texts themselves are not committed (several are copyrighted).
Put them as .txt files in one folder, e.g. with `pdftotext`, and pass it:

    python source_weights.py SOURCES_DIR --bills data/flags_2025.csv

Writes reference/source_term_weights.csv and reference/source_candidates.csv.
"""

import argparse
import math
import re
from collections import Counter
from pathlib import Path

import pandas as pd

from flag import load_lexicon

HERE = Path(__file__).parent
STOP = set("""a an and are as at be been but by can could did do does for from had has have he her his how i if
in into is it its may me might more most my no not of on or other our out over own she should so some such
than that the their them then there these they this those through to too under up us was we were what when
where which while who whom why will with would you your also any all each per within without between about
upon whether one two three may shall must et al id supra see note page vol law j rev ann stat""".split())


def words(text):
    return re.findall(r"[a-z][a-z'-]*", text.lower())


def ngram_counts(tokens, n_max=3):
    c = Counter()
    for n in range(1, n_max + 1):
        for i in range(len(tokens) - n + 1):
            g = tokens[i:i + n]
            if g[0] in STOP or g[-1] in STOP or any(len(w) < 3 for w in (g[0], g[-1])):
                continue
            c[" ".join(g)] += 1
    return c


def log_odds_z(y_ref, n_ref, y_bill, n_bill, prior_scale=1000):
    """Monroe et al. (2008) weighted log-odds with an informative Dirichlet prior."""
    p = (y_ref + y_bill + 0.5) / (n_ref + n_bill)
    a = prior_scale * p
    a0 = prior_scale
    d = (math.log((y_ref + a) / (n_ref + a0 - y_ref - a))
         - math.log((y_bill + a) / (n_bill + a0 - y_bill - a)))
    return d / math.sqrt(1 / (y_ref + a) + 1 / (y_bill + a))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("sources", help="folder of .txt reference texts")
    p.add_argument("--bills", default=HERE / "data" / "flags_2025.csv")
    p.add_argument("--out", default=HERE / "reference")
    args = p.parse_args()

    texts = {f.stem: f.read_text(encoding="utf-8", errors="replace") for f in sorted(Path(args.sources).glob("*.txt"))}
    bills = pd.read_csv(args.bills, dtype=str).fillna("")
    bill_text = (bills["title"] + " " + bills["subject"] + " " + bills["digest"]).tolist()
    n_src = {k: len(words(t)) for k, t in texts.items()}
    n_ref = sum(n_src.values())
    n_bill = sum(len(words(t)) for t in bill_text)
    big_bills = " \n ".join(bill_text)
    print(f"{len(texts)} sources, {n_ref:,} words; {len(bill_text):,} bill summaries, {n_bill:,} words")

    def measure(name, pattern, kind="", area="", weight=""):
        per = {k: len(pattern.findall(t)) for k, t in texts.items()}
        y_ref = sum(per.values())
        y_bill = len(pattern.findall(big_bills))
        return {
            "term": name, "kind": kind, "area": area, "weight": weight,
            "sources": sum(v > 0 for v in per.values()),
            "per_10k": round(sum(per[k] / n_src[k] * 1e4 for k in texts) / len(texts), 2),
            "ref_count": y_ref, "bill_count": y_bill,
            "bills": sum(bool(pattern.search(t)) for t in bill_text),
            "z": round(log_odds_z(y_ref, n_ref, y_bill, n_bill), 2),
            **{f"n_{k}": v for k, v in per.items()},
        }

    lex = [t for t in load_lexicon() if t.kind not in ("exclude", "population")]
    rows = [measure(t.term, t.pattern, t.kind, t.area, t.weight) for t in lex]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).sort_values("z", ascending=False).to_csv(out / "source_term_weights.csv", index=False)

    # Candidate phrases: frequent in at least two sources, not already matched by a lexicon term.
    grams = {k: ngram_counts(words(t)) for k, t in texts.items()}
    pool = Counter()
    for c in grams.values():
        pool.update(c)
    cands = []
    for g, total in pool.items():
        breadth = sum(g in c for c in grams.values())
        if breadth < 2 or total < 3:
            continue
        if any(t.pattern.search(g) for t in lex):
            continue
        pat = re.compile(r"\b" + r"\s+".join(map(re.escape, g.split())) + r"\b", re.I)
        cands.append(measure(g, pat, "candidate"))
    c = pd.DataFrame(cands)
    if not c.empty:
        c = c[c["z"] > 2].sort_values("z", ascending=False)
    c.to_csv(out / "source_candidates.csv", index=False)
    print(f"{len(rows)} lexicon terms measured; {len(c)} candidate phrases -> {out}")


if __name__ == "__main__":
    main()
