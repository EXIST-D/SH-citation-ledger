#!/usr/bin/env python3
"""Entity-matching evaluation of dedupe.compare() on the public DBLP-ACM benchmark (Koepcke & Rahm, Univ. Leipzig; 2,616 DBLP and 2,294 ACM bibliographic records,
2,224 gold matches). Records have title / authors / venue / year only (no DOI, no pages): a hard setting for explainable rules.
Every pair that blocking proposes is classified by compare(); 'same' = merge, 'candidate' = left to a person. Precision / recall are computed on merged pairs; the candidate pairs are reported separately.
usage: dedupe_eval.py     data: dev/ref/dblp_acm/{DBLP2.csv, ACM.csv, DBLP-ACM_perfectMapping.csv}"""
import csv
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, next(p for p in (os.path.join(HERE, "..", "submission", "scripts"), os.path.join(HERE, "..", "scripts")) if os.path.isdir(p)))  # work tree or repository layout
import bib  # noqa: E402
import dedupe  # noqa: E402

D = os.path.join(HERE, "ref", "dblp_acm")


def load(fn, prefix):
    out = []
    for row in csv.DictReader(open(os.path.join(D, fn), encoding="utf-8", errors="replace")):
        r = bib.new_record("csv")
        r["id"] = prefix + row["id"]
        r["title"] = row["title"]
        r["authors"] = bib.split_authors(row["authors"] or "")
        r["container"] = row["venue"]
        r["year"] = row["year"]
        r["type"] = "journal" if any(w in (row["venue"] or "").lower() for w in ("sigmod record", "vldb j", "tods", "tkde", "journal", "transactions")) else "conference"
        out.append(bib.finish(r))
    return out


def main():
    a, b = load("DBLP2.csv", "d:"), load("ACM.csv", "a:")
    gold = {("d:" + r["idDBLP"], "a:" + r["idACM"]) for r in csv.DictReader(open(os.path.join(D, "DBLP-ACM_perfectMapping.csv"), encoding="utf-8"))}
    recs = a + b
    t0 = time.time()
    pairs = dedupe.blocks(recs)
    tp = fp = 0
    cand_tp = cand_fp = 0
    missed = []
    pred = set()
    for i, j in pairs:
        ri, rj = recs[i], recs[j]
        if ri["id"][0] == rj["id"][0]:
            continue  # cross-source pairs only (each source is duplicate-free)
        c = dedupe.compare(ri, rj)
        key = (ri["id"], rj["id"]) if ri["id"][0] == "d" else (rj["id"], ri["id"])
        if c["decision"] == "same":
            pred.add(key)
            if key in gold:
                tp += 1
            else:
                fp += 1
        elif c["decision"] == "candidate":
            if key in gold:
                cand_tp += 1
            else:
                cand_fp += 1
    fn = len(gold - pred)
    p = tp / max(1, tp + fp)
    r = tp / len(gold)
    print("blocking proposed %d cross-source pairs (of %d possible), %.1fs" % (len([1 for i, j in pairs if recs[i]["id"][0] != recs[j]["id"][0]]), len(a) * len(b), time.time() - t0))
    print("merged ('same'): TP %d FP %d FN %d | precision %.3f recall %.3f F1 %.3f" % (tp, fp, fn, p, r, 2 * p * r / (p + r)))
    print("left to a person ('candidate'): %d pairs, of which %d are true matches (%d gold matches still missing after candidates)" % (cand_tp + cand_fp, cand_tp, len(gold - pred) - cand_tp))
    miss = sorted(gold - pred)[:0]


if __name__ == "__main__":
    main()
