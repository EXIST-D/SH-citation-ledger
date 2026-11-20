#!/usr/bin/env python3
"""Agreement of fmt.py with the CSL reference implementation (citeproc-py + official CSL styles) on the 226 test items of the GB/T 7714-2015 style repository
(zotero-chinese/styles, derived from the standard's own examples). Comparison is done on normalised text (full-width -> ASCII punctuation, spaces and case ignored, citation number removed).
usage: format_eval.py [style]   (gbt7714 | apa7 | ieee)   data: dev/ref/gbt/items.json + style.csl, dev/ref/apa.csl, dev/ref/ieee.csl"""
import json
import os
import re
import sys
import difflib
import collections

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, next(p for p in (os.path.join(HERE, "..", "submission", "scripts"), os.path.join(HERE, "..", "scripts")) if os.path.isdir(p)))  # work tree or repository layout
sys.path.insert(0, HERE)
import bib  # noqa: E402
import fmt  # noqa: E402
import oracle  # noqa: E402

REF = os.path.join(HERE, "ref")
FW = str.maketrans("，：；（）［］。！？、“”‘’—–", ",:;()[].!?,\"\"''--")


STRICT = [True]


def norm(s):
    s = re.sub(r"^\s*\[\d+\]\s*", "", s).translate(FW)
    s = re.sub(r"[*_]", "", s)
    s = re.sub(r"\[(?:J|M|C|D|R|S|P|EB|N|A|G|Z|DB|CP)(?:/OL)?\]", "", s)   # the CSL reference prints type marks only for some types
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"\s+", "", s).lower()
    if not STRICT[0]:
        s = re.sub(r"[^\w]", "", s)
    return s.rstrip(".")


def main(style):
    items = json.load(open(os.path.join(REF, "gbt", "items.json"), encoding="utf-8"))
    STRICT[0] = style != "ieee"
    csl = {"gbt7714": os.path.join(REF, "gbt", "style.csl"), "apa7": os.path.join(REF, "apa.csl"), "ieee": os.path.join(REF, "ieee.csl")}[style]
    if style != "gbt7714":
        items = [i for i in items if not any(ord(c) > 0x2e80 for c in i.get("title", "")) and i["type"] in ("article-journal", "book", "chapter", "paper-conference", "thesis", "report")]
    ref = oracle.render(items, csl)
    items = [i for i in items if i.get("title")]
    ref = {k: v for k, v in ref.items()}
    n = eq = 0
    sim = []
    bytype = collections.defaultdict(lambda: [0, 0])
    worst = []
    for it in items:
        rec = bib.parse_csl(json.dumps([it]))[0]
        mine = fmt.format_entry(rec, style)
        a, b = norm(mine), norm(ref[it["id"]])
        n += 1
        ok = a == b
        eq += ok
        bytype[it["type"]][0] += 1
        bytype[it["type"]][1] += ok
        s = difflib.SequenceMatcher(None, a, b).ratio()
        sim.append(s)
        if not ok:
            worst.append((s, it["id"], mine, ref[it["id"]]))
    print("%s: %d items | identical after normalisation %d (%.0f%%) | mean character similarity %.3f" % (style, n, eq, 100.0 * eq / n, sum(sim) / n))
    print("  by type: " + ", ".join("%s %d/%d" % (k, v[1], v[0]) for k, v in sorted(bytype.items())))
    if len(sys.argv) > 2:
        for s, i, m, r in sorted(worst)[:int(sys.argv[2])]:
            print("  %.2f %s\n     mine: %s\n     csl : %s" % (s, i, m, re.sub(r"^\[\d+\]", "", r)))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "gbt7714")
