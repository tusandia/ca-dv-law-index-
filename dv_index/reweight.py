"""Set lexicon weights from the reference-source measurements (source_weights.py).

Rules (documented in CODEBOOK.md, section "How terms are weighted"):

  direct terms (can make a bill DIRECT)
    3  core naming term: a term the sources use as a NAME for domestic violence
       (domestic violence, domestic abuse, intimate partner violence, dating
       violence, family violence), in at least 2 of the 4 sources
    3  statutory term: a citation to, or a defined term of, the DV Prevention
       Act or Pen. Code 273.5 / Evid. Code 1037, or a federal DV-specific law or
       program (VAWA, military protective orders, the Family Advocacy Program). General sources do
       not use these, but California law defines DV with them (Lovell 2025:
       statutes and advocacy use different words)
    3  relationship + abuse: a statutory relationship (cohabitant, household
       member, former spouse, dating relationship, fiance) in the same clause as
       an act of abuse. This is how California statutes describe DV without
       saying "domestic violence"
    2  supporting term used by 3 or more sources
    1  supporting term used by 1-2 sources, or by none
    A supporting term that appears in 2% or more of all bill summaries is too
    common to point to DV, and is moved to the anchors.

  anchors (victim/safety language; support INDIRECT, never make DIRECT)
    2  used by all 4 sources and in under 2% of bill summaries. (All 4, not 3:
       Lovell's article discusses terms like "survivor" at length, so a single
       source can inflate a count; requiring every source guards against that.)
    1  otherwise (a word in 2%+ of all bills, like "abuse" or "victim", is
       common in DV writing but does not single out DV bills)

  area / area_strong / population / exclude: unchanged (they describe what a
  bill does, not how it talks about DV).

Usage:
    python reweight.py reference/source_term_weights.csv reference/source_curated.csv
Rewrites lexicon.csv in place, adding src_* columns that record the evidence.
"""

import argparse
import csv
from pathlib import Path

import pandas as pd

HERE = Path(__file__).parent

CORE_NAMES = {"domestic violence", "domestic abuse", "intimate partner violence", "dating violence", "family violence"}
STATUTORY = {
    "domestic violence prevention act", "coercive control", "forced marriage", "emergency protective order",
    "re:section 6211 of the family code", "re:section 6203 of the family code",
    r"re:section 273\.5 of the penal code", r"re:section 1037(\.\d+)? of the evidence code",
    "re:division 10 (of|of the) (the )?family code",
    r"re:\b(6[23]\d\d|640\d)(\.\d+)?\b[^.;]{0,250}?family code",
    "misdemeanor crime of domestic violence",
    # federal DV-specific laws and programs
    "violence against women act", "military protective order*", "family advocacy program",
}
GENERIC_SHARE = 0.02

# New terms from the sources (measured in source_curated.csv). kind, area, note.
NEW_TERMS = {
    "stalk*": ("anchor", "", "replaces 'stalking'; all 4 sources"),
    "intimidat*": ("anchor", "", "all 4 sources"),
    "physical abuse": ("direct", "", "all 4 sources"),
    "emotional abuse": ("direct", "", "all 4 sources"),
    "psychological abuse": ("direct", "", "all 4 sources"),
    "verbal abuse": ("direct", "", "all 4 sources"),
    "power and control": ("direct", "", "all 4 sources; the Duluth 'power and control wheel'"),
    "abusive relationship*": ("direct", "", "3 sources"),
    "abusive partner*": ("direct", "", "2 sources"),
    "protection order*": ("direct", "courts", "3 sources; like 'protective order', also used for non-DV orders"),
    "financial abuse": ("direct", "financial", "2 sources"),
    "spiritual abuse": ("direct", "", "2 sources; abuse that uses religion or faith"),
    "sexual coercion": ("direct", "health", "2 sources"),
    "reproductive coercion": ("direct", "health", "1 source"),
    "gaslighting": ("direct", "", "1 source"),
    "teen dating violence": ("direct", "education", "2 sources; also matched by 'dating violence'"),
    r"re:\b(cohabitants?|household members?|former spouses?|dating relationships?|fianc[eé]e?s?)\b[^.;]{0,150}\b(abus\w*|batter\w*|injur\w*|threat\w*|stalk\w*|harass\w*|violen\w*)":
        ("direct", "", "relationship + abuse in one clause, as statutes define DV (Lovell 2025)"),
    r"re:\b(abus\w*|batter\w*|injur\w*|threat\w*|stalk\w*|harass\w*|violen\w*)\b[^.;]{0,150}\b(cohabitants?|household members?|former spouses?|dating relationships?|fianc[eé]e?s?)\b":
        ("direct", "", "abuse + relationship in one clause (reverse order)"),
}
DROP = {"stalking"}  # replaced by stalk*


def weight_for(kind, term, src, bills_total):
    """Return (kind, weight, rule) for one term given its source evidence row (or None)."""
    sources = int(src["sources"]) if src is not None else 0
    rate = float(src["per_10k"]) if src is not None else 0.0
    share = (int(src["bills"]) / bills_total) if src is not None else 0.0
    if kind == "direct":
        if term in CORE_NAMES and sources >= 2:
            return "direct", 3, f"core name for DV in {sources}/4 sources"
        if term in STATUTORY:
            return "direct", 3, "statutory term (California or federal DV law)"
        if term.startswith("re:") and ("cohabitant" in term):
            return "direct", 3, "statutory relationship + abuse"
        if share >= GENERIC_SHARE:
            return "anchor", 1 if sources < 4 else 2, f"in {share:.1%} of bills: too common to signal DV alone"
        if sources >= 3:
            return "direct", 2, f"supporting term in {sources}/4 sources"
        return "direct", 1, f"supporting term in {sources}/4 sources"
    if kind == "anchor":
        if share >= GENERIC_SHARE:
            return "anchor", 1, f"in {sources}/4 sources but {share:.1%} of bills: too common for extra weight"
        w = 2 if sources == 4 else 1
        return "anchor", w, f"victim/safety language in {sources}/4 sources"
    return kind, None, ""


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("measured", help="source_term_weights.csv from source_weights.py")
    p.add_argument("curated", help="measurements for NEW_TERMS, same columns")
    p.add_argument("--bills-total", type=int, default=4262)
    p.add_argument("--lexicon", default=HERE / "lexicon.csv")
    args = p.parse_args()

    ev = pd.concat([pd.read_csv(args.measured), pd.read_csv(args.curated)]).drop_duplicates("term").set_index("term")
    with open(args.lexicon, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    header, body = rows[0], rows[1:]
    extra = ["src_sources", "src_per_10k", "src_z", "src_bill_share", "weight_rule"]
    cols = header[:5] + extra
    out, have = [cols], set()
    for r in body:
        r = (r + [""] * 5)[:5]
        term, kind = r[0].strip(), r[1].strip()
        if term.startswith("#") or not term:
            out.append([",".join(x for x in r if x)] if term.startswith("#") else r)
            continue
        if term in DROP:
            continue
        have.add(term)
        src = ev.loc[term] if term in ev.index else None
        new_kind, w, rule = weight_for(kind, term, src, args.bills_total)
        if w is not None:
            r[1], r[3] = new_kind, str(w)
        evid = ([int(src["sources"]), src["per_10k"], src["z"], f"{int(src['bills']) / args.bills_total:.4f}"]
                if src is not None else ["", "", "", ""])
        out.append(r + evid + [rule])
    # add new terms after the matching section header
    for term, (kind, area, note) in NEW_TERMS.items():
        if term in have:
            continue
        src = ev.loc[term] if term in ev.index else None
        k, w, rule = weight_for(kind, term, src, args.bills_total)
        anchor_at = next(i for i, r in enumerate(out) if r and r[0].startswith("# --- anchor" if k == "anchor" else "# --- anchor"))
        evid = ([int(src["sources"]), src["per_10k"], src["z"], f"{int(src['bills']) / args.bills_total:.4f}"]
                if src is not None else ["", "", "", ""])
        out.insert(anchor_at + (1 if k == "anchor" else 0), [term, k, area, str(w), note] + evid + [rule])
    with open(args.lexicon, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(out)
    print(f"rewrote {args.lexicon}")


if __name__ == "__main__":
    main()
