#!/usr/bin/env python3
"""cl.py - citation ledger: every citation of a manuscript, every reference, and every decision about them, kept consistent.

You decide which sentence needs which source and which entries are the same work; the tool finds the markers and the reference list, audits them (unresolved / uncited / out-of-order / duplicate /
badly placed), proposes duplicate merges with the rule that fired, checks references (offline structure; Crossref when asked), applies your decisions and REBUILDS the manuscript in the same file format:
markers renumbered in order of first appearance (or kept), ranges compressed, reference list regenerated in the target style (GB/T 7714-2015, APA 7, IEEE, Vancouver), BibTeX / RIS exported,
a change log with old -> new numbers, merges, insertions and deletions.

  cl.py prepare [MANUSCRIPT] --work W [--lib FILE ...] [--case /input/case.json] [--style gbt7714|apa7|ieee|vancouver]
  cl.py audit W | needs W | suggest W [--sids S004-S009] | dedupe W [--auto] | verify W [--online] | support W | show W [--sids ...]
  cl.py ingest W [FILE|-]          cite / uncite / merge / keepsep / replace / judge / meta blocks
  cl.py build W --out OUT [--style S] [--numbering first|keep] [--uncited drop|keep] [--place before|after] [--case ...]
  cl.py run [MANUSCRIPT] --out OUT [--lib FILE ...] [--case ...]   everything above with default decisions in one call
  cl.py convert --lib FILE --style S [--out FILE] [--format txt|bib|ris]      no manuscript: reformat a library
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import time
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bib  # noqa: E402
import cite  # noqa: E402
import dedupe  # noqa: E402
import fmt  # noqa: E402
import nlib  # noqa: E402
import segment  # noqa: E402
import verify  # noqa: E402

VERSION = "1.0.0"
SCHEMA = "citation-ledger/1"


# ------------------------------------------------------------------------------------------------ io
def wtext(path, text):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def jload(p, default=None):
    if not os.path.isfile(p):
        return default
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def jsave(p, obj):
    os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def find_key(obj, names):
    if isinstance(obj, dict):
        for k in names:
            if k in obj:
                return obj[k]
        for v in obj.values():
            r = find_key(v, names)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = find_key(v, names)
            if r is not None:
                return r
    return None


def load(work):
    doc = jload(os.path.join(work, "doc.json"))
    if doc is None:
        raise SystemExit("no doc.json in %s: run `prepare` first" % work)
    return doc, jload(os.path.join(work, "ledger.json")), jload(os.path.join(work, "ops.json"), {"cite": [], "uncite": [], "merge": [], "keepsep": [], "replace": [], "judge": [], "meta": []})


def save_ops(work, ops):
    jsave(os.path.join(work, "ops.json"), ops)


def sentences(doc):
    for p in doc["paragraphs"]:
        for s in p["sentences"]:
            yield p, s


def sent_of(doc, par, pos):
    p = next(x for x in doc["paragraphs"] if x["id"] == par)
    best = None
    for s in p["sentences"]:
        if s["start"] <= pos < s["end"] + 1:
            return s["id"]
        if s["start"] <= pos:
            best = s["id"]
    return best


# ------------------------------------------------------------------------------------------------ prepare
LIB_EXT = (".bib", ".bibtex", ".ris", ".enw", ".nbib")
MS_EXT = (".docx", ".tex", ".md", ".markdown", ".txt", ".pdf")
MS_KEYS = re.compile(r"manuscript|draft|paper|document|article|source|input|稿|论文|正文", re.I)
LIB_KEYS = re.compile(r"librar|bib|reference|literature|citation|endnote|zotero|文献|参考", re.I)
SKIP_NAMES = {"task.md", "case.json", "readme.md", "readme.txt"}


def string_leaves(obj, key=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from string_leaves(v, k)
    elif isinstance(obj, list):
        for v in obj:
            yield from string_leaves(v, key)
    elif isinstance(obj, str):
        yield key, obj


def walk_files(roots, depth=3):
    out = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        base = root.rstrip(os.sep).count(os.sep)
        for dp, dn, fn in os.walk(root):
            dn[:] = [d for d in sorted(dn) if not d.startswith(".") and d not in ("__pycache__", "output", "work")]
            if dp.count(os.sep) - base >= depth:
                dn[:] = []
            for f in sorted(fn):
                p = os.path.join(dp, f)
                if f.lower() not in SKIP_NAMES and not f.startswith(".") and p not in out:
                    out.append(p)
    return out


def is_library(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in LIB_EXT:
        return True
    if ext in (".txt", ".json"):
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                head = fh.read(20000)
        except OSError:
            return False
        kind = bib.sniff(head, os.path.basename(path))
        if kind != "text":
            return True
        return ext == ".txt" and bool(re.search(r"ref|lib|bib|cite|文献|参考", os.path.basename(path), re.I)) and not re.search(r"^\s*#", head)
    return False


def discover(a):
    case = jload(a.case) if a.case and os.path.isfile(a.case) else None
    base = os.path.dirname(os.path.abspath(a.case)) if a.case else "/input"
    walk_roots = list(dict.fromkeys([base, "/input"]))
    roots = walk_roots + [os.getcwd()]  # the working directory only resolves relative paths named by the case; it is never searched
    files = walk_files(walk_roots)
    named = []  # files the case names, with the key they sit under
    if case:
        for key, val in string_leaves(case):
            if re.search(r"\.(?:docx|tex|md|markdown|txt|pdf|bib|bibtex|ris|enw|nbib|json)\b", val, re.I) and len(val) < 300:
                for root in roots + [""]:
                    pth = os.path.join(root, val) if root and not os.path.isabs(val) else val
                    if os.path.isfile(pth) and os.path.basename(pth).lower() not in SKIP_NAMES:
                        named.append((key, os.path.abspath(pth)))
                        if os.path.abspath(pth) not in files:
                            files.append(os.path.abspath(pth))
                        break
    if a.input and not os.path.isfile(a.input):
        raise SystemExit("ERROR: manuscript file not found: %s" % a.input)
    libs = [os.path.abspath(x) for x in (a.lib or [])]
    ms = os.path.abspath(a.input) if a.input else None
    if not libs:
        libs = [f for f in files if is_library(f) and f != ms]
    if not ms:
        cands = [f for f in files if os.path.splitext(f)[1].lower() in MS_EXT and f not in libs]
        by_key = [p for k, p in named if p in cands and MS_KEYS.search(k) and not LIB_KEYS.search(k)]
        order = {e: i for i, e in enumerate(MS_EXT)}
        cands.sort(key=lambda f: (order[os.path.splitext(f)[1].lower()], -os.path.getsize(f)))
        ms = (by_key or cands or [None])[0]
        a.others = [f for f in cands if f != ms]
    if ms and ms.lower().endswith(".tex"):
        with open(ms, encoding="utf-8", errors="replace") as fh:
            txt = fh.read()
        for m in re.finditer(r"\\(?:bibliography|addbibresource)\{([^}]*)\}", txt):
            for nm in m.group(1).split(","):
                nm = nm.strip()
                for cand in (nm, nm + ".bib"):
                    pth = os.path.join(os.path.dirname(os.path.abspath(ms)), cand)
                    if os.path.isfile(pth) and pth not in libs:
                        libs.append(pth)
    if not ms:
        raise SystemExit("no manuscript found: pass MANUSCRIPT, or --case with a file path (looked in %s)" % ", ".join(walk_roots))
    return ms, libs, case


def link_entries(list_entries, lib_recs):
    """match the manuscript's reference list to the library; -> entries {id: rec}, list_no -> id"""
    entries, by_no, links = {}, {}, []
    for r in lib_recs:
        entries[r["id"]] = r
        r["origin"] = "library"
    for e in list_entries:
        rec = e["record"]
        best, bs = None, 0.0
        for r in lib_recs:
            c = dedupe.compare(rec, r)
            vp = "version_pair" in c["rules"] or (rec["year"] and r["year"] and rec["year"] != r["year"] and not (rec["doi"] and rec["doi"] == r["doi"]))
            if (c["decision"] == "same" and not vp) or (rec["doi"] and rec["doi"] == r["doi"]):
                s = dedupe.title_sim(rec["title"], r["title"]) + (1 if c["decision"] == "same" else 0)
                if s > bs:
                    best, bs = r, s
        if best:
            for k in ("place", "publisher", "edition", "volume", "issue", "pages", "doi", "container", "isbn", "url", "accessed"):
                if rec.get(k) and not best.get(k):
                    best[k] = rec[k]
                    best.setdefault("filled_from_list", []).append(k)
            by_no[e["no"]] = best["id"]
            best.setdefault("list_nos", []).append(e["no"])
            links.append({"list_no": e["no"], "library": best["id"], "raw": e["raw"][:120]})
        else:
            rec["id"] = "L%d" % e["no"]
            rec["origin"] = "list"
            rec["list_nos"] = [e["no"]]
            entries[rec["id"]] = rec
            by_no[e["no"]] = rec["id"]
    return entries, by_no, links


def resolve_instances(doc, entries, by_no, region):
    insts, n = [], 0
    for p in doc["paragraphs"]:
        if p.get("in_refs") and p["kind"] == "frozen" and p.get("frozen_reason", "").startswith("reference"):
            continue
        if "\\bibitem" in p["text"]:
            continue
        for it in cite.find_instances(p["text"], p["id"]):
            n += 1
            it["id"] = "C%03d" % n
            it["sid"] = sent_of(doc, p["id"], it["start"]) if p["sentences"] else None
            it["in_frozen"] = p["kind"] == "frozen"
            it["entries"], it["unresolved"] = [], []
            if it["style"] in ("bracket", "sup"):
                for no in it["nums"]:
                    if no in by_no:
                        it["entries"].append(by_no[no])
                    else:
                        it["unresolved"].append(str(no))
            elif it["style"] in ("latex", "pandoc"):
                for k in it["keys"]:
                    if k in entries:
                        it["entries"].append(k)
                    else:
                        it["unresolved"].append(k)
            else:
                for fam, yr in it["ay"]:
                    hits = cite.resolve_ay(fam, yr, list(entries.values()))
                    if len(hits) == 1:
                        it["entries"].append(hits[0]["id"])
                    elif hits:
                        it["entries"].append(hits[0]["id"])
                        it.setdefault("ambiguous", []).append("%s %s: %d candidates" % (fam, yr, len(hits)))
                    else:
                        it["unresolved"].append("%s %s" % (fam, yr))
            insts.append(it)
    return insts


def uniq_ids(recs):
    """entries from different files may share an id (`ref001`): the later ones get the file name as suffix, then a counter"""
    seen = set()
    for r in recs:
        rid, k = r["id"], 1
        if rid in seen:
            rid = "%s__%s" % (r["id"], r.get("lib_file", "x"))
            while rid in seen:
                k += 1
                rid = "%s__%s_%d" % (r["id"], r.get("lib_file", "x"), k)
            r["id"] = rid
        seen.add(rid)
    return recs


def detect_list_style(list_entries):
    """the style the manuscript's own reference list is written in (kept unless --style says otherwise): majority of the entries, at least 60%"""
    votes = Counter()
    for e in list_entries:
        raw = e["raw"]
        if re.search(r"\[(?:J|M|C|D|R|S|P|N|EB/OL|J/OL|M/OL)\]", raw):
            votes["gbt7714"] += 1
        elif re.search(r"\((?:1[5-9]|20)\d{2}[a-z]?\)\.", raw):
            votes["apa7"] += 1
        elif re.search(r"[\"“].+?[,.][\"”]", raw) and re.search(r"\b(?:vol|pp|no)\.", raw):
            votes["ieee"] += 1
        elif re.search(r"\.\s*(?:1[5-9]|20)\d{2}\s*;\s*\d+", raw):
            votes["vancouver"] += 1
    if not votes:
        return None
    st, n = votes.most_common(1)[0]
    return st if n >= 0.6 * len(list_entries) else None


def cmd_prepare(a):
    os.makedirs(a.work, exist_ok=True)
    a.others = []
    ms, libs, case = discover(a)
    doc = segment.build(ms, a.work)
    doc["input_path"] = ms
    lang = nlib.detect_lang(" ".join(p["text"] for p in doc["paragraphs"] if p["kind"] != "frozen")[:4000])
    list_entries, region = cite.parse_reflist(doc)
    lib_recs, lib_info = [], []
    for lp in libs:
        with open(lp, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        try:
            kind, recs = bib.parse_any(text, os.path.basename(lp))
        except Exception as e:  # a damaged or unexpected library file must not stop the run
            lib_info.append({"file": os.path.basename(lp), "format": "unreadable", "entries": 0, "error": "%s: %s" % (type(e).__name__, str(e)[:80])})
            print("WARNING: library file %s could not be parsed (%s): skipped" % (os.path.basename(lp), lib_info[-1]["error"]))
            continue
        for r in recs:
            r["lib_file"] = os.path.basename(lp)
        lib_recs += recs
        lib_info.append({"file": os.path.basename(lp), "format": kind, "entries": len(recs)})
    uniq_ids(lib_recs)
    entries, by_no, links = link_entries(list_entries, lib_recs)
    assumption = None
    if not list_entries and lib_recs:
        probe = [i for p in doc["paragraphs"] for i in cite.find_instances(p["text"], p["id"]) if i["style"] in ("bracket", "sup")]
        if probe:
            by_no = {i + 1: r["id"] for i, r in enumerate(lib_recs)}
            assumption = "the manuscript has no reference list: numeric markers were resolved by the order of the library file(s) (marker [n] = n-th library entry); confirm this is how the numbers were assigned"
    insts = resolve_instances(doc, entries, by_no, region)
    styles = Counter(i["style"] for i in insts)
    numeric = [i for i in insts if i["style"] in ("bracket", "sup")]
    form = (numeric[0].get("form") if numeric else {}) or {}
    detected = detect_list_style(list_entries)
    target = a.style or detected or ("apa7" if styles.get("authyear", 0) > styles.get("bracket", 0) + styles.get("sup", 0) else ("gbt7714" if lang == "zh" else "ieee"))
    doc.update({"lang": lang, "version": VERSION, "task": (find_key(case, ["task", "instruction", "prompt", "requirements", "description"]) if case else None)})
    jsave(os.path.join(a.work, "doc.json"), doc)
    ledger = {"entries": entries, "by_no": {str(k): v for k, v in by_no.items()}, "links": links, "instances": insts, "region": region, "styles": dict(styles), "form": form, "target_style": target, "detected_list_style": detected, "libs": lib_info, "assumption": assumption,
              "list_entries": [{"no": e["no"], "raw": e["raw"], "par": e["par"], "entry": by_no.get(e["no"]), "confidence": e["record"]["parse"].get("confidence"), "missing": e["record"]["parse"].get("missing")} for e in list_entries]}
    jsave(os.path.join(a.work, "ledger.json"), ledger)
    if not os.path.isfile(os.path.join(a.work, "ops.json")):
        save_ops(a.work, {"cite": [], "uncite": [], "merge": [], "keepsep": [], "replace": [], "judge": [], "meta": []})
    nsent = sum(len(p["sentences"]) for p in doc["paragraphs"])
    print(json.dumps({"ok": True, "work": a.work, "file": doc["file"], "format": doc["format"], "lang": lang, "paragraphs": len(doc["paragraphs"]), "sentences": nsent, "citations": len(insts), "citation_styles": dict(styles),
                      "reference_list_entries": len(list_entries), "reference_list_label": region["label"], "libraries": lib_info, "entries_total": len(entries), "library_matches": len(links), "unresolved_citations": sum(1 for i in insts if i["unresolved"]),
                      "target_style": target}, ensure_ascii=False))
    if doc.get("note"):
        print("NOTE: " + doc["note"])
    print("manuscript: %s | libraries: %s" % (os.path.basename(ms), ", ".join(os.path.basename(x) for x in libs) or "(none)"))
    if a.others:
        print("NOTE: other files that could be manuscripts were NOT used: %s (pass one explicitly if the task means another)" % ", ".join(os.path.basename(x) for x in a.others[:6]))
    if doc.get("task"):
        print("TASK (from the case file): " + str(doc["task"])[:600])
    if not insts:
        print("WARNING: no citation markers were recognised in the manuscript (markers in Word footnotes / field codes / images are not read): check the format before trusting an empty result")
    if not list_entries and not lib_recs:
        print("WARNING: neither a reference list in the manuscript nor a library file was found")
    print("Next: `audit`, `dedupe`, `needs`, `verify`, then decisions via `ingest`, then `build`.")


# ------------------------------------------------------------------------------------------------ helpers over the ledger
def alive_entries(L, ops):
    """entry id -> canonical id after applying accepted merges (union of decisions)"""
    redirect = {}
    for m in ops["merge"]:
        for x in m["members"]:
            if x != m["canonical"]:
                redirect[x] = m["canonical"]

    def canon(x):
        seen = 0
        while x in redirect and seen < 20:
            x, seen = redirect[x], seen + 1
        return x
    return canon


def final_instances(doc, L, ops):
    """instances after uncite / replace / merge, plus virtual instances for cite blocks -> list in document order with 'entries' final"""
    canon = alive_entries(L, ops)
    rep = {r["old"]: r["new"] for r in ops["replace"]}
    out = []
    unc = defaultdict(set)
    for u in ops["uncite"]:
        for k in u["keys"]:
            unc[u["sid"]].add(canon(k))
    for it in L["instances"]:
        ents = []
        for e in it["entries"]:
            e = canon(rep.get(e, e))
            if e not in unc.get(it["sid"], set()) and e not in ents:
                ents.append(e)
        left = []
        for u in it["unresolved"]:
            if u in unc.get(it["sid"], set()):
                continue
            tgt = rep.get(u)
            if tgt and tgt in L["entries"]:
                tgt = canon(tgt)
                if tgt not in ents:
                    ents.append(tgt)
            else:
                left.append(u)
        out.append({**it, "final_entries": ents, "final_unresolved": left, "virtual": False, "removed": bool(it["entries"] or it["unresolved"]) and not ents and not left})
    for c in ops["cite"]:
        keys = [canon(rep.get(k, k)) for k in c["keys"] if canon(k) in L["entries"] or k in L["entries"]]
        p = next((p for p in doc["paragraphs"] if any(s["id"] == c["sid"] for s in p["sentences"])), None)
        if not p or not keys:
            continue
        s = next(s for s in p["sentences"] if s["id"] == c["sid"])
        pos = insert_position(p["text"], s, c.get("after"), L["form"], c.get("place", "before"))
        out.append({"id": "N%s%d" % (c["sid"], len(out)), "par": p["id"], "start": pos, "end": pos, "raw": "", "style": L["styles_main"] if "styles_main" in L else main_style(L), "sid": c["sid"], "final_entries": list(dict.fromkeys(keys)), "final_unresolved": [], "virtual": True, "removed": False,
                    "unresolved": [], "entries": [], "form": L["form"]})
    out.sort(key=lambda x: (int(x["par"][1:]), x["start"], x["virtual"]))
    return out


def main_style(L):
    st = L["styles"]
    if not st:
        return "bracket"
    return max(("bracket", "sup", "authyear", "latex", "pandoc"), key=lambda k: st.get(k, 0))


def insert_position(ptext, s, after, form, place):
    seg = ptext[s["start"]:s["end"]]
    if after:
        k = seg.find(after)
        if k < 0:
            k = seg.lower().find(after.lower())
        if k >= 0:
            return s["start"] + k + len(after)
    m = re.search(r"([.。!?！？;；]+[\"'”’)\]]*)\s*$", seg)
    if m and place == "before":
        return s["start"] + m.start()
    return s["end"]


# ------------------------------------------------------------------------------------------------ audit
def entry_label(L, e):
    r = L["entries"].get(e)
    if not r:
        return e
    a = r["authors"][0]["family"] or r["authors"][0]["literal"] if r["authors"] else "?"
    return "%s %s %s" % (e, a, r["year"])


def run_audit(doc, L, ops=None):
    issues = []
    insts = L["instances"]
    list_n = len(L["list_entries"])
    for it in insts:
        if it["unresolved"]:
            issues.append({"kind": "unresolved_citation", "severity": "error", "sid": it["sid"], "marker": it["raw"], "detail": "marker %s points to %s that is not in the reference list / library" % (it["raw"], ", ".join(it["unresolved"]))})
        for amb in it.get("ambiguous", []):
            issues.append({"kind": "ambiguous_author_year", "severity": "warn", "sid": it["sid"], "marker": it["raw"], "detail": amb})
        if it["style"] in ("bracket", "sup") and len(it["nums"]) != len(set(it["nums"])):
            issues.append({"kind": "repeated_number_in_marker", "severity": "warn", "sid": it["sid"], "marker": it["raw"], "detail": "the same number appears twice in %s" % it["raw"]})
        if it["style"] in ("bracket", "sup") and it["nums"] != sorted(it["nums"]):
            issues.append({"kind": "unsorted_marker", "severity": "low", "sid": it["sid"], "marker": it["raw"], "detail": "numbers inside %s are not in ascending order" % it["raw"]})
        if it["style"] in ("bracket", "sup") and re.search(r"\d\s*[,，]\s*\d+\s*[,，]\s*\d+", it["raw"]):
            nums = it["nums"]
            if any(nums[i + 1] == nums[i] + 1 == nums[i + 2] - 1 for i in range(len(nums) - 2)):
                issues.append({"kind": "range_not_compressed", "severity": "low", "sid": it["sid"], "marker": it["raw"], "detail": "%s lists three or more consecutive numbers: write a range" % it["raw"]})
    if L.get("assumption"):
        issues.append({"kind": "numbers_resolved_by_library_order", "severity": "warn", "sid": None, "marker": "", "detail": L["assumption"]})
    cited = {e for it in insts for e in it["entries"]}
    for no, eid in sorted((int(k), v) for k, v in L["by_no"].items()):
        if eid not in cited:
            issues.append({"kind": "uncited_reference", "severity": "warn", "sid": None, "marker": "[%d]" % no, "detail": "reference %d (%s) is never cited in the text" % (no, entry_label(L, eid))})
    numeric = [it for it in insts if it["style"] in ("bracket", "sup")]
    if numeric:
        first = []
        for it in sorted(numeric, key=lambda x: (int(x["par"][1:]), x["start"])):
            for n in it["nums"]:
                if n not in first:
                    first.append(n)
        if first != sorted(first) or first != list(range(1, len(first) + 1)):
            bad = next((i for i, n in enumerate(first) if n != i + 1), 0)
            issues.append({"kind": "numbering_not_by_first_appearance", "severity": "warn", "sid": None, "marker": "", "detail": "numbers are not in order of first citation (first citations appear as %s ...; expected 1, 2, 3 ...): `build` renumbers" % ", ".join(map(str, first[:10]))})
        gaps = sorted(set(range(1, (max(first) if first else 0) + 1)) - set(first))
        if gaps:
            issues.append({"kind": "number_gap", "severity": "warn", "sid": None, "marker": "", "detail": "numbers never cited between 1 and %d: %s" % (max(first), ", ".join(map(str, gaps[:12])))})
    styles = {k: v for k, v in L["styles"].items() if v}
    if len([k for k in styles if k in ("bracket", "sup", "authyear", "latex", "pandoc")]) > 1:
        issues.append({"kind": "mixed_citation_styles", "severity": "warn", "sid": None, "marker": "", "detail": "several marker styles in one manuscript: %s" % dict(styles)})
    sep = Counter((it.get("form") or {}).get("rng") for it in numeric if len(it["nums"]) > 2 and (it.get("form") or {}).get("rng"))
    if len(sep) > 1:
        issues.append({"kind": "mixed_range_characters", "severity": "low", "sid": None, "marker": "", "detail": "ranges written with different characters: %s" % dict(sep)})
    # placement
    pmap = {p["id"]: p for p in doc["paragraphs"]}
    for it in insts:
        p = pmap[it["par"]]
        if re.match(r"\s*(?:Figure|Fig\.?|Table|图|表)\s*\d", p["text"]) and it["style"] != "latex":
            issues.append({"kind": "citation_in_caption", "severity": "low", "sid": it["sid"], "marker": it["raw"], "detail": "citation inside a figure / table caption: check that the caption needs it"})
        if p["kind"] == "heading":
            issues.append({"kind": "citation_in_heading", "severity": "warn", "sid": it["sid"], "marker": it["raw"], "detail": "citation inside a heading"})
        after = p["text"][it["end"]:it["end"] + 2]
        before = p["text"][max(0, it["start"] - 2):it["start"]]
        if re.match(r"\s*[.。,，;；]", before[-1:]) and it["style"] in ("bracket", "sup"):
            issues.append({"kind": "citation_after_punctuation", "severity": "low", "sid": it["sid"], "marker": it["raw"], "detail": "marker placed after punctuation; the document's other markers sit before it" if L["styles"].get("bracket", 0) + L["styles"].get("sup", 0) else ""})
    for p in doc["paragraphs"]:
        if p["kind"] == "frozen" or len(p["sentences"]) < 4:
            continue
        pi = [it for it in insts if it["par"] == p["id"]]
        if len(pi) == 1 and pi[0]["end"] >= len(p["text"]) - 3:
            issues.append({"kind": "single_citation_for_long_paragraph", "severity": "warn", "sid": pi[0]["sid"], "marker": pi[0]["raw"], "detail": "paragraph %s has %d sentences and one citation at its end: which sentences does it support? (use `needs`)" % (p["id"], len(p["sentences"]))})
    # reference list quality
    for e in L["list_entries"]:
        if (e["confidence"] or 0) < 0.5:
            issues.append({"kind": "reference_not_parsed", "severity": "warn", "sid": None, "marker": "[%d]" % e["no"], "detail": "reference %d could not be parsed into fields (%s): %s" % (e["no"], ", ".join(e["missing"] or []), e["raw"][:90])})
        elif e["missing"]:
            issues.append({"kind": "reference_fields_missing", "severity": "low", "sid": None, "marker": "[%d]" % e["no"], "detail": "reference %d lacks: %s" % (e["no"], ", ".join(e["missing"]))})
    return issues


def cmd_audit(a):
    doc, L, ops = load(a.work)
    iss = run_audit(doc, L)
    jsave(os.path.join(a.work, "audit.json"), iss)
    cnt = Counter((i["severity"], i["kind"]) for i in iss)
    print("citations %d (%s) | reference list %d entries | entries total %d | issues: %d" % (len(L["instances"]), L["styles"], len(L["list_entries"]), len(L["entries"]), len(iss)))
    for (sev, kind), n in sorted(cnt.items(), key=lambda kv: ({"error": 0, "warn": 1, "low": 2}[kv[0][0]], -kv[1])):
        ex = next(i for i in iss if i["kind"] == kind)
        print("  %-5s %-34s x%-3d e.g. %s%s" % (sev, kind, n, (ex["sid"] + " ") if ex["sid"] else "", ex["detail"][:110]))
    dd = dedupe.clusters(list(L["entries"].values()), prefer_zh=doc.get("lang") == "zh")
    print("duplicate clusters: %d (run `dedupe`)" % len(dd[0]))


# ------------------------------------------------------------------------------------------------ needs
CLAIM_CUES = [(r"\b(?:has|have|had)\s+been\s+(?:shown|reported|demonstrated|proposed|developed|widely|extensively|used|applied|studied|investigated|observed|suggested)\b", "reports prior work"),
              (r"\b(?:studies|research|work|literature|reports|evidence)\s+(?:has|have|shows?|showed|suggests?|indicates?|demonstrates?)\b", "refers to prior studies"),
              (r"\b(?:it\s+is\s+(?:well\s+)?(?:known|established|accepted|recognized|recognised)|is\s+widely\s+(?:used|accepted|known)|commonly\s+(?:used|referred)|well[- ]known)\b", "general knowledge claim"),
              (r"\b(?:previous(?:ly)?|prior|earlier|recent(?:ly)?)\s+(?:work|studies|study|research|reports?|methods?|approaches|findings)\b", "refers to earlier work"),
              (r"\b(?:state-of-the-art|baseline|benchmark|standard\s+(?:method|approach|protocol)|conventional)\b", "named comparison / standard"),
              (r"\b(?:according\s+to|as\s+(?:reported|described|shown|proposed)\s+(?:by|in)|following|based\s+on)\b[^.]{0,40}\b(?:[A-Z][a-z]+|et\s+al)", "attributed content"),
              (r"\b\d+(?:\.\d+)?\s?(?:%|percent\b|fold\b|million\b|billion\b)", "quantitative statement"),
              (r"\b(?:increases?|decreases?|reduces?|improves?|causes?|leads?\s+to|is\s+associated\s+with|correlat\w+)\b", "causal / association claim"),
              (r"\b(?:first|originally|pioneered|introduced|proposed|developed)\s+(?:by|in)\b", "priority / origin"),
              (r"已(?:有|被)?(?:研究|报道|证明|表明|发现)|研究表明|文献|众所周知|广泛(?:应用|使用)|近年来|(?:最早|首次)(?:由|提出)", "prior-work claim (zh)"),
              (r"[\d.]+\s?(?:%|倍)", "quantitative statement (zh)")]
OWN = re.compile(r"\b(?:we|our|this\s+(?:study|paper|work)|here\s+we|in\s+this\s+(?:study|paper|work))\b|本文|本研究|我们|笔者", re.I)


def clause_end(seg, cue_end):
    m = re.search(r"[,;，；]\s*(?:and|while|whereas|but|which)?|\s+(?:while|whereas|but)\s", seg[cue_end:])
    return cue_end + m.start() if m else len(seg)


def cmd_needs(a):
    doc, L, ops = load(a.work)
    cited_sids = {it["sid"] for it in L["instances"]}
    rows = []
    for p, s in sentences(doc):
        if p["kind"] != "text" or s["id"] in cited_sids:
            continue
        txt = p["text"][s["start"]:s["end"]]
        if re.match(r"\s*(?:Figure|Fig\.?|Table|图|表)\s*\d", txt) or len(txt) < (10 if re.search(r"[一-鿿]", txt) else 25):
            continue
        reasons, pos = [], None
        zh = bool(re.search(r"[一-鿿]", txt))
        for pat, why in CLAIM_CUES:
            if why.endswith("(zh)") and not zh:
                continue
            m = re.search(pat, txt, re.I)
            if m:
                reasons.append(why)
                pos = pos or m.end()
        if not reasons:
            continue
        own = bool(OWN.search(txt))
        score = len(reasons) + (0.5 if re.search(r"\b(?:Introduction|Background|Related|Literature)\b|引言|背景|相关", p.get("section") or "", re.I) else 0) - (1.5 if own and not re.search(r"based on|following|according", txt, re.I) else 0)
        if score >= 1:
            rows.append((score, s["id"], p["id"], txt, reasons, s["start"] + (clause_end(txt, pos) if pos else len(txt)), own))
    rows.sort(key=lambda r: -r[0])
    print("%d sentence(s) without a citation that look like they need a source (hints, not truth; your own results do not need one):" % len(rows))
    for sc, sid, pid, txt, reasons, pos, own in rows[:a.top]:
        print("  %s [%s] %.1f %s%s: %s" % (sid, pid, sc, "/".join(sorted(set(reasons)))[:50], " (own wording: check)" if own else "", txt[:170].replace("\n", " ")))
    print("  place a marker with `=== cite S012` / `keys: key1, key2` (default: before the sentence's final punctuation; `after: \"phrase\"` for a clause)")
    pl = [i for i in run_audit(doc, L) if i["kind"] == "single_citation_for_long_paragraph"]
    for i in pl[:6]:
        print("  PARAGRAPH %s" % i["detail"])


def cmd_suggest(a):
    """rank library entries for sentences that look like they need a source (lexical evidence only: title, abstract, keywords, venue)"""
    import math
    doc, L, ops = load(a.work)
    ents = effective_entries(L, ops)
    canon = alive_entries(L, ops)
    pool = {e: r for e, r in ents.items() if canon(e) == e}
    words = {e: nlib.content_words(" ".join([r["title"], r["abstract"], " ".join(r["keywords"]), r["container"]])) for e, r in pool.items()}
    df = Counter(w for ws in words.values() for w in ws)
    n = max(1, len(pool))
    idf = lambda w: math.log(1 + n / (1 + df.get(w, 0)))
    want = set()
    for part in re.split(r"[,\s]+", a.sids or ""):
        m = re.fullmatch(r"S(\d+)-S?(\d+)", part)
        if m:
            want |= {"S%03d" % k for k in range(int(m.group(1)), int(m.group(2)) + 1)}
        elif part:
            want.add(part)
    cited = {it["sid"] for it in L["instances"]}
    rows = []
    for p, s in sentences(doc):
        if p["kind"] != "text":
            continue
        if want and s["id"] not in want:
            continue
        if not want and s["id"] in cited:
            continue
        txt = cite_strip(p["text"][s["start"]:s["end"]])
        sw = nlib.content_words(txt)
        if len(sw) < 4:
            continue
        reasons = [why for pat, why in CLAIM_CUES if re.search(pat, txt, re.I)]
        if not want and not reasons:
            continue
        tot = sum(idf(w) for w in sw) or 1.0
        sc = []
        for e, ws in words.items():
            common = sw & ws
            if common:
                sc.append((sum(idf(w) for w in common) / tot, e, sorted(common)[:6]))
        sc.sort(reverse=True)
        rows.append({"sid": s["id"], "sentence": txt[:160], "candidates": [{"entry": e, "score": round(v, 2), "shared": sh, "title": pool[e]["title"][:80], "has_abstract": len(pool[e]["abstract"].split()) >= 30} for v, e, sh in sc[:3] if v >= a.min_score]})
    jsave(os.path.join(a.work, "suggest.json"), rows)
    print("%d sentence(s) looked at; candidates are ranked by shared content words with title / abstract / keywords (no semantic model: read before you cite)" % len(rows))
    for r in rows:
        print("  %s: %s" % (r["sid"], r["sentence"][:120]))
        if not r["candidates"]:
            print("      no library entry shares enough words: a material gap unless you know better (report it, do not invent a source)")
        for c in r["candidates"]:
            print("      %s  %.2f  shared: %s | %s%s" % (c["entry"], c["score"], ", ".join(c["shared"]), c["title"], "" if c["has_abstract"] else "  [title only]"))


# ------------------------------------------------------------------------------------------------ dedupe
def cmd_dedupe(a):
    doc, L, ops = load(a.work)
    cl, cands, guarded = dedupe.clusters(list(L["entries"].values()), prefer_zh=doc.get("lang") == "zh")
    dec = {frozenset(m["members"]) for m in ops["merge"]}
    keep = {frozenset((k["a"], k["b"])) for k in ops["keepsep"]}
    cl = [c for c in cl if not any(frozenset((x, y)) in keep for x in c["members"] for y in c["members"] if x != y)]
    cands = [c for c in cands if frozenset((c["a"], c["b"])) not in keep]
    jsave(os.path.join(a.work, "dedupe.json"), {"clusters": cl, "candidates": cands, "guarded": guarded})
    print("%d duplicate cluster(s), %d candidate pair(s) to confirm, %d guarded pair(s) (similar but kept apart)" % (len(cl), len(cands), len(guarded)))
    for k, c in enumerate(cl, 1):
        print("CLUSTER %d [%s%s] canonical %s <- %s" % (k, c["confidence"], ", work pair: keep the published version" if c["work_pair"] else "", c["canonical"], ", ".join(m for m in c["members"] if m != c["canonical"])))
        for e in c["evidence"][:3]:
            print("    %s ~ %s: %s" % (e["a"], e["b"], "; ".join(e["reasons"])))
        for cf in c["conflicts"][:3]:
            print("    CONFLICT %s: kept '%s' vs '%s' (%s)" % (cf["field"], cf["kept"], cf["other"], cf["from"]))
        for rid in c["members"][:3]:
            r = L["entries"][rid]
            print("      - %s: %s | %s | %s %s" % (rid, r["title"][:70], "; ".join(x["family"] or x["literal"] for x in r["authors"][:3]), r["container"][:30], r["year"]))
        if a.auto and c["confidence"] in ("certain", "high") and frozenset(c["members"]) not in dec:
            add_op(ops, "merge", {"canonical": c["canonical"], "members": c["members"], "reason": "; ".join(sum((e["reasons"] for e in c["evidence"]), []))[:300], "auto": True})
    for c in cands[:20]:
        print("CANDIDATE %s ~ %s (%s): %s" % (c["a"], c["b"], c["confidence"], "; ".join(c["reasons"])))
    for g in guarded[:8]:
        print("GUARD %s ~ %s: %s (title similarity %.2f)" % (g["a"], g["b"], "; ".join(g["guards"]), g["title_sim"]))
    if a.auto:
        save_ops(a.work, ops)
        print("auto: accepted %d high-confidence merge(s); medium / candidate pairs need `=== merge` or `=== keepsep`" % sum(1 for m in ops["merge"] if m.get("auto")))
    elif cl or cands:
        print("accept with `=== merge` (canonical: ID, members: A, B) or `dedupe W --auto` for high-confidence clusters; reject with `=== keepsep` (a: ID, b: ID, reason: ...)")


# ------------------------------------------------------------------------------------------------ ingest
BLOCK_KEYS = {"keys": "keys", "key": "keys", "after": "after", "position": "place", "place": "place", "canonical": "canonical", "members": "members", "reason": "reason", "a": "a", "b": "b", "old": "old", "new": "new", "verdict": "verdict", "note": "note",
              "title": "title", "year": "year", "authors": "authors", "doi": "doi", "container": "container", "volume": "volume", "issue": "issue", "pages": "pages", "publisher": "publisher", "entry": "entry", "style": "style", "type": "type", "url": "url"}


def parse_blocks(text):
    recs, cur, key = [], None, None
    for ln in text.splitlines():
        s = ln.rstrip()
        if re.match(r"^\s*```\w*\s*$", s):
            continue
        m = re.match(r"^\s*[#=*]{2,}\s*(cite|uncite|merge|keepsep|replace|judge|meta)\b\s*(.*?)[*=#]*\s*$", s, re.I)
        if m:
            cur = {"kind": m.group(1).lower(), "target": m.group(2).strip(), "f": {}}
            recs.append(cur)
            key = None
            continue
        if cur is None:
            continue
        mk = re.match(r"^\s*(?:[-*]\s*)?([A-Za-z_]+)\s*[:：]\s*(.*)$", s)
        if mk and mk.group(1).lower() in BLOCK_KEYS:
            key = BLOCK_KEYS[mk.group(1).lower()]
            cur["f"][key] = mk.group(2).strip().strip('"')
            continue
        if key and s.strip():
            cur["f"][key] += " " + s.strip()
    return recs


def add_op(ops, kind, rec):
    """same decision twice replaces the earlier one (re-running an ingest file changes nothing)"""
    ident = {"cite": ("sid", "after"), "uncite": ("sid",), "merge": ("canonical",), "keepsep": ("a", "b"), "replace": ("old",), "judge": ("sid", "key"), "meta": ("entry",)}[kind]
    ops[kind] = [o for o in ops[kind] if tuple(o.get(k) for k in ident) != tuple(rec.get(k) for k in ident)]
    ops[kind].append(rec)


def split_keys(v):
    return [k.strip() for k in re.split(r"[,;]", v or "") if k.strip()]


def cmd_ingest(a):
    doc, L, ops = load(a.work)
    text = sys.stdin.read() if (not a.file or a.file == "-") else open(a.file, encoding="utf-8").read()
    recs = parse_blocks(text)
    if not recs:
        raise SystemExit("no blocks found: '=== cite S012' + keys:, '=== uncite', '=== merge', '=== keepsep', '=== replace', '=== judge', '=== meta'")
    sids = {s["id"] for _, s in sentences(doc)}
    lines, n, bad = [], Counter(), 0
    canon = alive_entries(L, ops)
    for r in recs:
        k, f, tgt = r["kind"], r["f"], r["target"]
        if k in ("cite", "uncite"):
            sid = re.match(r"S\d+", tgt)
            sid = ("S%03d" % int(sid.group(0)[1:])) if sid else None
            keys = split_keys(f.get("keys"))
            if sid not in sids:
                lines.append("%s '%s': unknown sentence id (see `show`)" % (k, tgt))
                bad += 1
                continue
            loose = {u for it in L["instances"] if it["sid"] == sid for u in it["unresolved"]} if k == "uncite" else set()
            unknown = [x for x in keys if x not in L["entries"] and x not in loose]
            if unknown or not keys:
                lines.append("%s %s: unknown key(s) %s (library ids: %s ...)" % (k, sid, unknown or "(none given)", ", ".join(list(L["entries"])[:6])))
                bad += 1
                continue
            if k == "cite":
                have = {canon(e) for it in L["instances"] if it["sid"] == sid for e in it["entries"]} | {canon(x["keys"][i]) for x in ops["cite"] if x["sid"] == sid and x.get("after", "") != f.get("after", "") for i in range(len(x["keys"]))}
                dup = [x for x in keys if canon(x) in have]
                if dup:
                    lines.append("cite %s: %s already cited in that sentence: not added again" % (sid, ", ".join(dup)))
                    keys = [x for x in keys if canon(x) not in have]
                if not keys:
                    continue
            if f.get("after"):
                p = next(p for p in doc["paragraphs"] if any(s["id"] == sid for s in p["sentences"]))
                s = next(s for s in p["sentences"] if s["id"] == sid)
                if f["after"].lower() not in p["text"][s["start"]:s["end"]].lower():
                    lines.append("%s %s: anchor text '%s' is not in the sentence (the marker would go to the sentence end)" % (k, sid, f["after"]))
            add_op(ops, k, {"sid": sid, "keys": keys, "after": f.get("after", ""), "place": f.get("place", "before"), "reason": f.get("reason", "")})
            n[k] += 1
        elif k == "merge":
            mem = split_keys(f.get("members"))
            cn = f.get("canonical") or (mem[0] if mem else "")
            if not mem or any(x not in L["entries"] for x in mem + [cn]):
                lines.append("merge: unknown entry id in %s" % ", ".join(mem + [cn]))
                bad += 1
                continue
            if cn not in mem:
                mem.append(cn)
            add_op(ops, "merge", {"canonical": cn, "members": mem, "reason": f.get("reason", "")})
            n["merge"] += 1
        elif k == "keepsep":
            add_op(ops, "keepsep", {"a": f.get("a", ""), "b": f.get("b", ""), "reason": f.get("reason", "")})
            n["keepsep"] += 1
        elif k == "replace":
            loose_all = {u for it in L["instances"] for u in it["unresolved"]}
            if (f.get("old") in L["entries"] or f.get("old") in loose_all) and f.get("new") in L["entries"]:
                add_op(ops, "replace", {"old": f["old"], "new": f["new"], "reason": f.get("reason", "")})
                n["replace"] += 1
            else:
                lines.append("replace: unknown id %s / %s" % (f.get("old"), f.get("new")))
                bad += 1
        elif k == "judge":
            sid = ("S%03d" % int(re.match(r"S(\d+)", tgt).group(1))) if re.match(r"S\d+", tgt) else None
            if f.get("verdict", "").lower() not in ("supported", "partial", "unsupported", "unverifiable"):
                lines.append("judge %s: verdict must be supported | partial | unsupported | unverifiable" % tgt)
                bad += 1
                continue
            add_op(ops, "judge", {"sid": sid, "key": f.get("keys") or f.get("key") or f.get("entry", ""), "verdict": f["verdict"].lower(), "note": f.get("note", "")})
            n["judge"] += 1
        elif k == "meta":
            e = tgt.strip()
            if e not in L["entries"]:
                lines.append("meta: unknown entry %s" % e)
                bad += 1
                continue
            ch = {x: f[x] for x in ("title", "year", "authors", "doi", "container", "volume", "issue", "pages", "publisher", "type", "url") if x in f}
            add_op(ops, "meta", {"entry": e, "changes": ch, "reason": f.get("reason", "")})
            n["meta"] += 1
    save_ops(a.work, ops)
    print("recorded: " + ", ".join("%s %d" % kv for kv in n.items()) + (" | rejected %d" % bad if bad else ""))
    for ln in lines[:20]:
        print("  " + ln)
    sys.exit(2 if bad else 0)


# ------------------------------------------------------------------------------------------------ verify / support / show
def effective_entries(L, ops):
    """entries with `meta` corrections applied (copy)"""
    ents = copy.deepcopy(L["entries"])
    for m in ops["meta"]:
        r = ents[m["entry"]]
        for k, v in m["changes"].items():
            if k == "authors":
                r["authors"] = bib.split_authors(v)
            else:
                r[k] = v
        r["corrected"] = sorted(m["changes"])
    return ents


def cmd_verify(a):
    doc, L, ops = load(a.work)
    ents = effective_entries(L, ops)
    canon = alive_entries(L, ops)
    cited = {e for it in final_instances(doc, L, ops) for e in it["final_entries"]}
    # merged-away duplicates are not looked up; library entries nobody cites only with --all
    recs = [r for r in ents.values() if canon(r["id"]) == r["id"] and (r["id"] in cited or a.all)]
    res = verify.check_all(recs, online=a.online, timeout=a.timeout)
    jsave(os.path.join(a.work, "verification.json"), res)
    cnt = Counter(v["status"] for v in res.values())
    print("verification of %d entr%s (%s): %s" % (len(res), "y" if len(res) == 1 else "ies", "online" if a.online else "offline: structure only, nothing is claimed as verified", dict(cnt)))
    for rid, v in res.items():
        if v["status"] in ("mismatch", "not_found", "structural_problem") or (v["structural"] and a.verbose):
            print("  %-16s %s: %s" % (rid, v["status"], "; ".join(v["structural"] + (v["details"] if v["status"] != "unchecked" else []))[:200]))
    if not a.online:
        print("  `verify W --online` looks DOIs / titles up at Crossref when the network is reachable (otherwise entries stay 'unchecked')")


def cmd_support(a):
    doc, L, ops = load(a.work)
    ents = effective_entries(L, ops)
    judged = {(j["sid"], j["key"]): j for j in ops["judge"]}
    rows = []
    pmap = {p["id"]: p for p in doc["paragraphs"]}
    for it in final_instances(doc, L, ops):
        if it["virtual"] or not it["sid"] or it["removed"]:
            continue
        p = pmap[it["par"]]
        s = next((s for s in p["sentences"] if s["id"] == it["sid"]), None)
        if not s:
            continue
        sent = cite_strip(p["text"][s["start"]:s["end"]])
        sw = nlib.content_words(sent)
        for e in it["final_entries"]:
            r = ents[e]
            txt = " ".join([r["title"], r["abstract"], " ".join(r["keywords"]), r["container"]])
            rw = nlib.content_words(txt)
            cov = len(sw & rw) / max(1, len(sw))
            has_abs = len(r["abstract"].split()) >= 30
            nums = set(nlib.numbers(sent))
            miss = [n for n in nums if has_abs and n not in set(nlib.numbers_ev(r["abstract"]))][:3]
            flag = "no_text_to_check" if not has_abs and len(r["title"].split()) < 4 else ("low_topic_overlap" if cov < (0.08 if has_abs else 0.04) else ("numbers_not_in_abstract" if miss else "plausible"))
            if not has_abs and flag == "plausible":
                flag = "title_only_plausible"
            j = judged.get((it["sid"], e))
            rows.append({"sid": it["sid"], "entry": e, "overlap": round(cov, 2), "flag": flag, "has_abstract": has_abs, "numbers_missing": miss, "judgement": j["verdict"] if j else None, "sentence": sent[:160], "title": r["title"][:90]})
    jsave(os.path.join(a.work, "support.json"), rows)
    cnt = Counter(r["flag"] for r in rows)
    print("%d citation-reference pairs: %s | judged by you: %d" % (len(rows), dict(cnt), sum(1 for r in rows if r["judgement"])))
    for r in rows:
        if r["flag"] in ("low_topic_overlap", "numbers_not_in_abstract") and not r["judgement"]:
            print("  %s %s %s (overlap %.2f%s): \"%s\" <- \"%s\"" % (r["sid"], r["entry"], r["flag"], r["overlap"], (", missing numbers " + ",".join(r["numbers_missing"])) if r["numbers_missing"] else "", r["sentence"][:100], r["title"]))
    print("  this is a lexical screen only: read the source for every pair you can; record the verdict with `=== judge S012` (key: ID, verdict: supported | partial | unsupported | unverifiable)")


def cite_strip(s):
    for ins in sorted(cite.find_instances(s, "x"), key=lambda i: -i["start"]):
        s = s[:ins["start"]] + s[ins["end"]:]
    return s


def cmd_show(a):
    doc, L, ops = load(a.work)
    want = set()
    for part in re.split(r"[,\s]+", a.sids or ""):
        m = re.fullmatch(r"S(\d+)-S?(\d+)", part)
        if m:
            want |= {"S%03d" % n for n in range(int(m.group(1)), int(m.group(2)) + 1)}
        elif part:
            want.add(part)
    byst = defaultdict(list)
    for it in L["instances"]:
        byst[it["sid"]].append(it)
    last = None
    for p, s in sentences(doc):
        if want and s["id"] not in want:
            continue
        if p["id"] != last:
            print("\n## %s %s" % (p["id"], (p.get("section") or "")[:40]))
            last = p["id"]
        marks = ""
        if byst.get(s["id"]):
            marks = "  <" + "; ".join("%s -> %s%s" % (i["raw"], ",".join(i["entries"]) or "?", (" UNRESOLVED " + ",".join(i["unresolved"])) if i["unresolved"] else "") for i in byst[s["id"]]) + ">"
        print("%s %s%s" % (s["id"], p["text"][s["start"]:s["end"]].replace("\n", " "), marks))
    if a.refs:
        print("\n## entries")
        for eid, r in L["entries"].items():
            print("%s [%s] %s | %s | %s %s %s" % (eid, r["origin"], r["title"][:70], "; ".join(x["family"] or x["literal"] for x in r["authors"][:3]), r["container"][:28], r["year"], ("DOI " + r["doi"]) if r["doi"] else ""))


# ------------------------------------------------------------------------------------------------ build
AY_NAME_ET = 3


def ay_text(r, style, narrative=False):
    au = r["authors"]
    zh = bool(bib.CJK.search(r["title"] or ""))

    def nm(a):
        return a["literal"] or (a["family"] if not a.get("zh") else a["family"] + a["given"])
    if not au:
        who = (r["container"] or r["title"])[:30]
    elif len(au) == 1:
        who = nm(au[0])
    elif len(au) == 2:
        who = nm(au[0]) + ((" 和 " if zh else (" and " if narrative else " & ")) + nm(au[1]))
    else:
        who = nm(au[0]) + (" 等" if zh else " et al.")
    y = r["year"] or "n.d."
    return ("%s (%s)" % (who, y)) if narrative else ("%s, %s" % (who, y))


def render_author_year(inst, ents, L, fmtstyle):
    parts = [ay_text(e, fmtstyle) for e in sorted(ents, key=lambda r: ((r["authors"][0]["family"] if r["authors"] else "").lower(), r["year"]))]
    if inst.get("narrative") and len(ents) == 1:
        return ay_text(ents[0], fmtstyle, True)
    zh = bool(bib.CJK.search(ents[0]["title"] or "")) if ents else False
    return ("（%s）" if zh else "(%s)") % ("；" if zh else "; ").join(parts)


def doc_text_before(doc, it):
    p = next(p for p in doc["paragraphs"] if p["id"] == it["par"])
    return p["text"][max(0, it["start"] - 1):it["start"]]


def numbering(final, L, ents, mode):
    """entry id -> number, plus order list"""
    order = []
    for it in final:
        if it["removed"]:
            continue
        for e in it["final_entries"]:
            if e not in order:
                order.append(e)
    if mode == "keep":
        keep = [v for _, v in sorted((int(k), v) for k, v in L["by_no"].items()) if v in order]
        # canonical redirects may point to an entry with a smaller number first
        seen, res = set(), []
        for e in keep + [x for x in order if x not in keep]:
            if e not in seen:
                seen.add(e)
                res.append(e)
        order = res
    return {e: i + 1 for i, e in enumerate(order)}, order


def build_text(doc, L, ops, ents, style, mode, place):
    final = final_instances(doc, L, ops)
    numeric = main_style(L) in ("bracket", "sup")
    authyear = main_style(L) == "authyear" or style == "apa7" and not numeric and L["styles"].get("authyear")
    keybased = main_style(L) in ("latex", "pandoc")
    nums, order = numbering(final, L, ents, mode)
    form = L["form"] or {}
    by_par = defaultdict(list)
    for it in final:
        by_par[it["par"]].append(it)
    changes, newtext = [], {}
    pre = [doc_text_before(doc, i) for i in final if not i["virtual"] and i["style"] in ("bracket", "authyear")]
    lead_space = bool(pre) and sum(1 for x in pre if x.endswith(" ")) * 2 > len(pre)
    for p in doc["paragraphs"]:
        its = by_par.get(p["id"], [])
        if not its:
            continue
        t, out, last = p["text"], [], 0
        for it in sorted(its, key=lambda x: (x["start"], x["virtual"])):
            if it["start"] < last:
                continue
            out.append(t[last:it["start"]])
            if it["virtual"] and it["style"] == "latex" and out and not "".join(out).endswith((" ", "~", "\n")):
                out.append(" ")
            if it["virtual"] and lead_space and out and not "".join(out).endswith((" ", "\n")) and (it["style"] in ("bracket", "authyear") or authyear):
                out.append(" ")
            if it["removed"]:
                new = ""
                if out and out[-1].endswith(" ") and not t[it["end"]:it["end"] + 1].isalnum():
                    out[-1] = out[-1][:-1]
            elif not it["final_entries"] and not it.get("final_unresolved"):
                new = it["raw"]
            elif not it["final_entries"]:
                new = it["raw"]
            elif keybased or it["style"] in ("latex", "pandoc"):
                keys = it["final_entries"] + it.get("final_unresolved", [])
                if it["style"] == "pandoc":
                    new = "[" + "; ".join("@" + k for k in keys) + "]"
                elif it["virtual"]:
                    cmds = Counter(i.get("cmd") for i in final if i.get("cmd"))
                    new = "\\%s{%s}" % (cmds.most_common(1)[0][0] if cmds else "cite", ",".join(keys))
                else:
                    new = re.sub(r"\{[^}]*\}\s*$", "{%s}" % ",".join(keys), it["raw"])
            elif (it["style"] == "authyear" or authyear) and it.get("final_unresolved"):
                new = it["raw"]
            elif it["style"] == "authyear" or authyear:
                new = render_author_year(it, [ents[e] for e in it["final_entries"]], L, style)
            else:
                st = it["style"] if it["style"] in ("bracket", "sup") else main_style(L)
                ns = [nums[e] for e in it["final_entries"]]
                f = it.get("form") or form
                new = cite.render_marker(it, ns, st, rng=f.get("rng", "–" if style != "gbt7714" else "-"), sep=f.get("sep", ","), space=f.get("space", False), wide=f.get("wide", False))
                if it.get("final_unresolved"):
                    extra = f.get("sep", ",").join("?" + u for u in it["final_unresolved"])
                    new = re.sub(r"([\]］]|</sup>)$", lambda m_: f.get("sep", ",") + extra + m_.group(1), new) if re.search(r"([\]］]|</sup>)$", new) else new + extra
            if it.get("in_frozen") and not it["virtual"] and new != it["raw"]:
                # fields / hyperlinks / tables / code: rewriting would damage the paragraph, so the marker stays and the new text is handed over for a manual edit
                changes.append({"instance": it["id"], "sid": it["sid"], "paragraph": it["par"], "old": it["raw"], "new": new, "kind": "manual", "entries": it["final_entries"]})
                new = it["raw"]
            elif new != it["raw"]:
                changes.append({"instance": it["id"], "sid": it["sid"], "old": it["raw"], "new": new, "kind": "insert" if it["virtual"] else ("remove" if it["removed"] else "renumber"), "entries": it["final_entries"]})
            out.append(new)
            last = it["end"]
        out.append(t[last:])
        s = "".join(out)
        if s != t:
            newtext[p["id"]] = s
    return final, nums, order, newtext, changes


def entry_texts(order, nums, ents, style, L, label_style, punct):
    lines = []
    if style == "apa7" and main_style(L) == "authyear" or (style in ("apa7",) and not label_style):
        order = sorted(order, key=lambda e: ((ents[e]["authors"][0]["family"] if ents[e]["authors"] else "").lower(), ents[e]["year"], ents[e]["title"].lower()))
    for e in order:
        txt = fmt.format_entry(ents[e], style, punct=punct)
        lines.append((e, txt))
    return lines


def cmd_build(a):
    doc, L, ops = load(a.work)
    style = a.style or L["target_style"]
    ents = effective_entries(L, ops)
    canon = alive_entries(L, ops)
    # merged records: canonical gets the filled fields
    merge_log = []
    for m in ops["merge"]:
        recs = [ents[x] for x in m["members"] if x in ents]
        merged, det = dedupe.merge_records(recs, m["canonical"])
        merged["id"] = m["canonical"]
        ents[m["canonical"]] = merged
        merge_log.append({"canonical": m["canonical"], "members": m["members"], "reason": m["reason"], "filled": det["filled"], "conflicts": det["conflicts"]})
    mode = a.numbering
    final, nums, order, newtext, changes = build_text(doc, L, ops, ents, style, mode, a.place)
    cited = set(order)
    uncited = [e for e in ents if canon(e) == e and e not in cited]
    uncited_cited_in_list = [e for e in uncited if ents[e].get("origin") == "list" or ents[e].get("list_nos")]
    if a.uncited == "keep":
        order = order + [e for e in uncited_cited_in_list if e not in order]
        nums = {e: i + 1 for i, e in enumerate(order)}
    lines = entry_texts(order, nums, ents, style, L, main_style(L) in ("bracket", "sup"), a.punct)
    numeric_main = main_style(L) in ("bracket", "sup")
    label = L["region"]["label"]
    out_lines = []
    for i, (e, txt) in enumerate(lines, 1):
        if numeric_main and label in ("bracket", "none", "bibitem"):
            out_lines.append("[%d] %s" % (nums.get(e, i), txt))
        elif numeric_main and label == "dot":
            out_lines.append("%d. %s" % (nums.get(e, i), txt))
        elif numeric_main and label == "paren":
            out_lines.append("(%d) %s" % (nums.get(e, i), txt))
        else:
            out_lines.append(txt)
    outdir = a.out
    os.makedirs(outdir, exist_ok=True)
    ext = {"md": ".md", "txt": ".txt", "tex": ".tex", "docx": ".docx"}[doc["format"]]
    files = []
    region = L["region"]
    ref_pars = [p for p in doc["paragraphs"] if p["id"] in region["pars"]]
    if doc["format"] == "docx":
        ptexts = {pid: (next(p for p in doc["paragraphs"] if p["id"] == pid)["text"], txt) for pid, txt in newtext.items()}
        extras = {}
        if ref_pars and out_lines:
            auto = region["label"] == "auto" or all(p.get("numbered") for p in ref_pars)
            body = [re.sub(r"^(?:\[\d+\]|\(\d+\)|\d+\.)\s+", "", ln) if auto else ln for ln in out_lines]
            for i, p in enumerate(ref_pars):
                ptexts[p["id"]] = (p["text"], body[i] if i < len(body) else None)
            if len(body) > len(ref_pars):
                extras[ref_pars[-1]["docx_index"]] = body[len(ref_pars):]
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        if not ref_pars and out_lines and doc["paragraphs"]:
            heading = "参考文献" if L.get("lang_zh") or doc.get("lang") == "zh" else "References"
            extras[doc["paragraphs"][-1]["docx_index"]] = [heading] + out_lines
        segment.write_docx(doc["input_path"], os.path.join(outdir, "manuscript.docx"), ptexts, doc, tracked=False, extras=extras, date=stamp)
        segment.write_docx(doc["input_path"], os.path.join(outdir, "manuscript_tracked_changes.docx"), ptexts, doc, tracked=True, extras=extras, date=stamp)
        files += ["manuscript.docx", "manuscript_tracked_changes.docx"]
        import shutil
        import subprocess
        soffice = shutil.which("soffice") or shutil.which("libreoffice")
        if soffice:
            try:
                subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", outdir, os.path.join(outdir, "manuscript.docx")], capture_output=True, timeout=120)
                if os.path.isfile(os.path.join(outdir, "manuscript.pdf")):
                    files.append("manuscript.pdf")
            except (OSError, subprocess.SubprocessError):
                pass
        final_text = "\n\n".join(p["text"] if p["id"] not in newtext else newtext[p["id"]] for p in doc["paragraphs"] if p["id"] not in region["pars"]) + "\n\n" + "\n".join(out_lines)
    else:
        raw = doc["raw"]
        repl = [(p["start"], p["end"], newtext[p["id"]]) for p in doc["paragraphs"] if p["id"] in newtext and p["kind"] != "frozen"]
        repl += [(p["start"], p["end"], newtext[p["id"]]) for p in doc["paragraphs"] if p["id"] in newtext and p["kind"] == "frozen"]
        if ref_pars and out_lines and doc["format"] in ("md", "txt"):
            a0, b0 = ref_pars[0]["start"], ref_pars[-1]["end"]
            sep = "\n\n" if re.search(r"\n[ \t]*\n", raw[a0:b0]) and "```" not in raw[a0:b0] else "\n"
            repl.append((a0, b0, sep.join(out_lines) + ("\n" if raw[a0:b0].endswith("\n") else "")))
        elif ref_pars and doc["format"] == "tex" and label == "bibitem":
            body = "\n".join("\\bibitem{%s} %s" % (e, txt) for e, txt in lines)
            for p in ref_pars:
                if "\\bibitem" in p["text"]:
                    head = p["text"][:p["text"].index("\\bibitem")]
                    tail = p["text"][p["text"].rindex("\\end{thebibliography}"):] if "\\end{thebibliography}" in p["text"] else ""
                    repl.append((p["start"], p["end"], head + body + "\n" + tail))
        appended = ""
        if not ref_pars and out_lines and doc["format"] in ("md", "txt"):
            appended = "\n" + ("## 参考文献" if doc.get("lang") == "zh" else "## References") + "\n\n" + "\n".join(out_lines) + "\n"
        out_raw, last = [], 0
        for s0, e0, new in sorted(repl):
            if s0 < last:
                continue
            out_raw.append(raw[last:s0])
            out_raw.append(new)
            last = e0
        out_raw.append(raw[last:])
        if appended:
            out_raw.append(("" if raw.endswith("\n") else "\n") + appended)
        final_text = "".join(out_raw)
        if doc["format"] == "tex" and label != "bibitem":
            final_text = re.sub(r"\\bibliography\{[^}]*\}", r"\\bibliography{references}", final_text)
            final_text = re.sub(r"\\addbibresource\{[^}]*\}", r"\\addbibresource{references.bib}", final_text)
        wtext(os.path.join(outdir, "manuscript" + ext), final_text)
        files.append("manuscript" + ext)
    wtext(os.path.join(outdir, "references.%s.txt" % style), "\n".join(out_lines) + "\n")
    cited_recs = [ents[e] for e in order]
    wtext(os.path.join(outdir, "references.bib"), fmt.to_bibtex(cited_recs))
    wtext(os.path.join(outdir, "references.ris"), fmt.to_ris(cited_recs))
    files += ["references.%s.txt" % style, "references.bib", "references.ris"]
    # numbering map old -> new
    mapping = []
    for no, eid in sorted((int(k), v) for k, v in L["by_no"].items()):
        ce = canon(eid)
        mapping.append({"old_number": no, "entry": eid, "canonical": ce, "new_number": nums.get(ce), "status": "dropped (uncited)" if ce not in nums else ("merged into %s" % ce if ce != eid else ("renumbered" if nums.get(ce) != no else "unchanged"))})
    jsave(os.path.join(outdir, "numbering_map.json"), mapping)
    csvl = ["old_number,entry,new_number,status"] + ["%d,%s,%s,%s" % (m["old_number"], m["entry"], m["new_number"] if m["new_number"] else "", m["status"]) for m in mapping]
    wtext(os.path.join(outdir, "numbering_map.csv"), "\n".join(csvl) + "\n")
    ledger_rows = []
    for it in final:
        ledger_rows.append({"citation": it["id"], "paragraph": it["par"], "sentence": it["sid"], "old_marker": it["raw"], "entries": it["final_entries"], "new_numbers": [nums.get(e) for e in it["final_entries"]] if numeric_main else None, "virtual": it["virtual"], "removed": it["removed"]})
    jsave(os.path.join(outdir, "ledger.json"), {"schema": SCHEMA, "style": style, "numbering": mode, "citations": ledger_rows, "entries": {e: ents[e] for e in order}, "decisions": ops})
    audit_after = None
    chg = {"citation_changes": changes, "merges": merge_log, "uncited_dropped": [e for e in uncited_cited_in_list if a.uncited == "drop"], "numbering_map": mapping, "inserted": [c for c in changes if c["kind"] == "insert"], "removed": [c for c in changes if c["kind"] == "remove"]}
    jsave(os.path.join(outdir, "changes.json"), chg)
    with open(os.path.join(outdir, "changes.md"), "w", encoding="utf-8") as fh:
        fh.write("# Changes\n\n## Marker changes\n| sentence | old | new | kind |\n|---|---|---|---|\n")
        for c in changes:
            fh.write("| %s | %s | %s | %s |\n" % (c["sid"], c["old"] or "-", c["new"] or "(removed)", c["kind"]))
        fh.write("\n## Dropped (uncited in the text)\n" + ("\n".join("- %s: %s" % (e, entry_label(L, e)) for e in chg["uncited_dropped"]) or "- none") + "\n\n## Merges\n" + ("\n".join("- %s <- %s: %s" % (m["canonical"], ", ".join(x for x in m["members"] if x != m["canonical"]), m["reason"][:160]) for m in merge_log) or "- none") + "\n\n## Numbering (old -> new)\n" + "\n".join("- [%d] %s -> %s (%s)" % (m["old_number"], m["entry"], m["new_number"] or "-", m["status"]) for m in mapping) + "\n")
    # verification of the result: re-parse the new manuscript's markers and list
    problems = []
    if doc["format"] != "docx":
        tmp = os.path.join(outdir, ".check")
        os.makedirs(tmp, exist_ok=True)
        chk = segment.build(os.path.join(outdir, "manuscript" + ext), tmp)
        le, rg = cite.parse_reflist(chk)
        found = [i for p in chk["paragraphs"] if not (p.get("in_refs") and p["kind"] == "frozen") for i in cite.find_instances(p["text"], p["id"])]
        used = sorted({n for i in found if i["style"] in ("bracket", "sup") for n in i["nums"]})
        if numeric_main:
            if used and used != list(range(1, len(used) + 1)):
                problems.append("cited numbers are not 1..N without gaps: %s" % used[:15])
            if used and len(le) != len(used) and le:
                problems.append("reference list has %d entries but %d distinct numbers are cited" % (len(le), len(used)))
            first = []
            for i in sorted(found, key=lambda x: (int(x["par"][1:]), x["start"])):
                for n in i.get("nums", []):
                    if n not in first:
                        first.append(n)
            if first != sorted(first):
                problems.append("numbers are not in order of first appearance after the build")
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    rep = {"entries_in_list": len(order), "citations": len(final), "inserted": len(chg["inserted"]), "removed": len(chg["removed"]), "merges": len(merge_log), "renumbered": sum(1 for m in mapping if m["status"] == "renumbered"), "dropped_uncited": len(chg["uncited_dropped"]),
           "post_build_problems": problems, "unresolved_left": sum(1 for it in final if it.get("final_unresolved"))}
    # review checklist, verification file, result.json
    ver = jload(os.path.join(a.work, "verification.json"), {})
    sup = jload(os.path.join(a.work, "support.json"), [])
    review = []
    for it in final:
        if it.get("final_unresolved"):
            review.append({"kind": "unresolved_citation", "sentence": it["sid"], "detail": "%s -> %s" % (it["raw"], ", ".join(it["final_unresolved"]))})
    for ch in changes:
        if ch["kind"] == "manual":
            review.append({"kind": "manual_marker_update", "sentence": ch.get("paragraph", ""), "detail": "%s must become %s by hand (the paragraph holds fields / hyperlinks / a table / code and was not rewritten)" % (ch["old"], ch["new"] or "(removed)")})
    for m in merge_log:
        for cf in m["conflicts"]:
            review.append({"kind": "merge_conflict", "entry": m["canonical"], "detail": "%s: kept '%s', other '%s'" % (cf["field"], cf["kept"], cf["other"])})
    for rid, v in ver.items():
        if v["status"] in ("mismatch", "not_found", "structural_problem"):
            review.append({"kind": "reference_" + v["status"], "entry": rid, "detail": "; ".join(v["structural"] + v["details"])[:200]})
    grp = {}
    for r in sup:
        if r["flag"] in ("low_topic_overlap", "numbers_not_in_abstract", "no_text_to_check") and not r["judgement"]:
            grp.setdefault((r["sid"], r["flag"]), []).append(r["entry"])
    for (sid, flag), es in grp.items():
        review.append({"kind": "support_unchecked", "sentence": sid, "entry": ", ".join(es), "detail": "%s (lexical screen only: read the source%s)" % (flag, "s" if len(es) > 1 else "")})
    for j in ops["judge"]:
        if j["verdict"] in ("unsupported", "partial", "unverifiable"):
            review.append({"kind": "judged_" + j["verdict"], "sentence": j["sid"], "entry": j["key"], "detail": j["note"]})
    with open(os.path.join(outdir, "review_checklist.md"), "w", encoding="utf-8") as fh:
        fh.write("# Review checklist\n\nMachine-assisted citation work: nothing here is approved by the author.\n\n")
        for r in review or [{"kind": "none", "detail": "no open item"}]:
            fh.write("- [ ] %s %s: %s\n" % (r["kind"], " ".join(x for x in (r.get("sentence"), r.get("entry")) if x), r["detail"]))
        fh.write("\n## Always verify by hand\n- that every inserted citation really supports its sentence (the tool places markers where you decided; it cannot read the source)\n- merged entries that were decided with a `work pair` (preprint / published)\n- references with status `unchecked` (offline) or `not_found`\n")
    files += ["changes.md", "changes.json", "numbering_map.json", "numbering_map.csv", "ledger.json", "review_checklist.md"]
    unc = []
    for r in review:
        unc.append({"kind": r["kind"], "detail": ("%s %s " % (r.get("sentence", ""), r.get("entry", ""))).strip() + ": " + r["detail"]})
    for pb in problems:
        unc.append({"kind": "post_build_problem", "detail": pb})
    if not final:
        unc.append({"kind": "no_citations_found", "detail": "no citation markers were recognised in the manuscript; nothing could be audited or renumbered"})
    if L.get("assumption"):
        unc.append({"kind": "assumption", "detail": L["assumption"]})
    if not ref_pars and out_lines and doc["format"] != "tex":
        unc.append({"kind": "reference_list_added", "detail": "the manuscript had no reference list: one was appended at the end"})
    if not ver:
        unc.append({"kind": "references_not_verified", "detail": "no verification run (`verify`): entries are not checked against any bibliographic source"})
    elif all(v["status"] == "unchecked" for v in ver.values()):
        unc.append({"kind": "references_unchecked_offline", "detail": "verification ran offline: only structure was checked"})
    status = "success" if final and not problems and not rep["unresolved_left"] and not any(r["kind"] in ("reference_not_found", "reference_mismatch", "unresolved_citation", "manual_marker_update") for r in review) else "partial"
    ctx = {"status": status, "rep": rep, "changes": chg, "review": review, "uncertainty": unc, "files": files, "style": style, "final_text": final_text, "refs": out_lines, "ledger": ledger_rows, "verification": ver, "support": sup, "merges": merge_log, "mapping": mapping,
           "entries": [ents[e] for e in order], "doc": doc, "ops": ops}
    case = jload(a.case) if a.case and os.path.isfile(a.case) else None
    fields = contract_fields(case)
    answers = jload(a.answers, {}) if a.answers else {}
    cid = (find_key(case, ["case_id", "caseId"]) or find_key(case, ["id"])) if case else None
    result = {"case_id": cid}
    unfilled = []
    for fld in fields:
        if fld == "case_id":
            continue
        if fld in answers:
            result[fld] = answers[fld]
            continue
        ok, v = derive_field(fld, ctx)
        result[fld] = v if ok else None
        if not ok:
            unfilled.append(fld)
    for nm in ("status", "manuscript", "references", "change_log", "numbering_map", "merges", "verification", "human_review", "uncertainty", "sources", "files"):
        if nm not in result:
            result[nm] = answers.get(nm, derive_field(nm, ctx)[1])
    for k, v in answers.items():
        result.setdefault(k, v)
    if case is not None and cid is None:
        unfilled.append("case_id")
    result["_meta"] = {"generator": "citation-ledger/cl.py %s" % VERSION, "contract_fields": fields, "unfilled_fields": unfilled, "contract_found": bool(fields), "files": files}
    jsave(os.path.join(outdir, "result.json"), result)
    print(json.dumps({"written": outdir, "status": status, **rep, "style": style, "unfilled_contract_fields": unfilled, "contract_found": bool(fields)}, ensure_ascii=False))
    for pb in problems:
        print("POST-BUILD PROBLEM: " + pb)
    if unfilled:
        print("UNFILLED contract fields (put them in answers.json and re-run build --answers): " + ", ".join(unfilled))
    if not fields and a.case:
        print("WARNING: no output_contract found in the case file: read /input/case.json and task.md and add the fields by hand via --answers")
    sys.exit(0 if ((not unfilled and fields) or not a.case) else 2)


def contract_fields(case):
    oc = find_key(case, ["output_contract", "outputContract", "output_schema", "outputs"]) if case else None
    fields = []

    def add(x):
        if isinstance(x, str) and x not in fields:
            fields.append(x)
    if isinstance(oc, list):
        for it in oc:
            add(it if isinstance(it, str) else (it.get("name") or it.get("field") or it.get("key")) if isinstance(it, dict) else None)
    elif isinstance(oc, dict):
        inner = oc.get("fields") or oc.get("required") or oc.get("properties") or oc.get("required_fields")
        if isinstance(inner, list):
            for it in inner:
                add(it if isinstance(it, str) else (it.get("name") or it.get("field") or it.get("key")) if isinstance(it, dict) else None)
        elif isinstance(inner, dict):
            for k in inner:
                add(k)
        else:
            for k in oc:
                if k not in ("type", "description", "title", "version", "schema", "$schema", "additionalProperties"):
                    add(k)
    return fields


def derive_field(name, ctx):
    n = name.lower()
    if n in ("status", "run_status", "state", "outcome"):
        return True, ctx["status"]
    if n in ("manuscript", "revised_manuscript", "target", "product", "deliverable", "polished_text", "text", "revised_text", "稿件", "改稿", "target_product"):
        return True, {"files": [f for f in ctx["files"] if f.startswith("manuscript")], "text": ctx["final_text"]}
    if n in ("references", "reference_list", "bibliography", "formatted_references", "reference_entries", "参考文献", "参考文献列表"):
        return True, {"style": ctx["style"], "entries": ctx["refs"], "files": [f for f in ctx["files"] if f.startswith("references")]}
    if n in ("change_log", "changes", "edits", "revision_log", "modifications", "change_records", "修改记录", "diff"):
        return True, ctx["changes"]
    if n in ("numbering_map", "renumbering", "number_mapping", "编号映射"):
        return True, ctx["mapping"]
    if n in ("merges", "duplicates", "dedup", "deduplication", "merged_entries", "去重"):
        return True, ctx["merges"]
    if n in ("citations", "ledger", "citation_ledger", "citation_list", "inserted_citations", "引用"):
        return True, ctx["ledger"]
    if n in ("facts", "fact_map", "source_map", "source_mapping", "evidence", "provenance", "事实与来源映射", "sources_map"):
        return True, {"citations": ctx["ledger"], "entries": ctx["entries"], "support": ctx["support"], "verification": ctx["verification"]}
    if n in ("verification", "checks", "qa", "validation", "source_verification", "reference_verification", "来源核验"):
        return True, {"entries": ctx["verification"], "support": ctx["support"], "post_build": ctx["rep"]}
    if n in ("human_review", "needs_review", "review_items", "manual_review", "to_confirm", "open_items", "人工确认项"):
        return True, ctx["review"]
    if n in ("uncertainty", "uncertainties", "caveats", "risks", "limits", "boundaries", "limitations", "gaps"):
        return True, ctx["uncertainty"]
    if n in ("sources", "source", "input", "inputs", "input_id", "input_files"):
        return True, [{"file": ctx["doc"]["file"], "format": ctx["doc"]["format"], "tool": "citation-ledger %s" % VERSION}]
    if n in ("files", "output_files", "artifacts"):
        return True, ctx["files"]
    if n in ("summary", "overview", "report"):
        return True, "%d citations, %d references in %s, %d inserted, %d removed, %d merges, %d renumbered; post-build problems: %s" % (ctx["rep"]["citations"], ctx["rep"]["entries_in_list"], ctx["style"], ctx["rep"]["inserted"], ctx["rep"]["removed"], ctx["rep"]["merges"], ctx["rep"]["renumbered"], ctx["rep"]["post_build_problems"] or "none")
    words = set(re.split(r"[^a-z]+", n))

    def has(ascii_words=(), cjk=()):
        return bool(words & set(ascii_words)) or any(x in n for x in cjk)
    if has(("boundary", "boundaries", "limits", "limitations"), ("边界", "版本")):
        return True, {"changes": ctx["changes"], "human_review": ctx["review"], "uncertainty": ctx["uncertainty"], "post_build_checks": ctx["rep"]}
    if has(("source", "sources", "provenance", "evidence", "mapping"), ("来源", "映射")):
        return derive_field("facts", ctx)
    if has(("product", "manuscript", "deliverable", "target", "draft"), ("产物", "稿")):
        return derive_field("manuscript", ctx)
    if has(("uncertainty", "uncertainties", "caveats"), ("不确定",)):
        return derive_field("uncertainty", ctx)
    if has(("confirm", "confirmation"), ("确认",)) or (("review" in words or "reviews" in words) and not words & {"reviewer", "score"}):
        return derive_field("human_review", ctx)
    if has(("changes", "change", "diff", "log", "edits"), ("修改", "改动")):
        return derive_field("change_log", ctx)
    if has(("status",), ("状态",)):
        return derive_field("status", ctx)
    return False, None


# ------------------------------------------------------------------------------------------------ convert
def cmd_convert(a):
    recs = []
    for lp in a.lib:
        with open(lp, encoding="utf-8", errors="replace") as fh:
            kind, rs = bib.parse_any(fh.read(), os.path.basename(lp))
        for r in rs:
            r["lib_file"] = os.path.basename(lp)
        recs += rs
    uniq_ids(recs)
    merged = []
    if a.dedupe:
        cl, cands, guarded = dedupe.clusters(recs, prefer_zh={"zh": True, "en": False}.get(a.prefer))
        drop = set()
        for c in cl:
            if c["confidence"] in ("certain", "high"):
                m, det = dedupe.merge_records([r for r in recs if r["id"] in c["members"]], c["canonical"])
                m["id"] = c["canonical"]
                recs = [m if r["id"] == c["canonical"] else r for r in recs]
                drop |= set(x for x in c["members"] if x != c["canonical"])
                merged.append("%s <- %s" % (c["canonical"], ", ".join(x for x in c["members"] if x != c["canonical"])))
        recs = [r for r in recs if r["id"] not in drop]
    if a.format == "bib":
        out = fmt.to_bibtex(recs)
    elif a.format == "ris":
        out = fmt.to_ris(recs)
    else:
        out = "\n".join("[%d] %s" % (i, fmt.format_entry(r, a.style, punct=a.punct)) for i, r in enumerate(recs, 1)) + "\n"
    if a.out:
        wtext(a.out, out)
        print("wrote %d entr%s to %s (%s)" % (len(recs), "y" if len(recs) == 1 else "ies", a.out, a.format if a.format != "txt" else a.style))
    else:
        print(out)
    if merged:
        print("merged duplicates: " + "; ".join(merged))
    miss = [(r["id"], r["parse"]["missing"]) for r in recs if r["parse"].get("missing")]
    if miss:
        print("fields missing in the source (not invented): " + "; ".join("%s: %s" % (i, ",".join(m)) for i, m in miss[:8]))


# ------------------------------------------------------------------------------------------------ run (one shot)
def cmd_run(a):
    """prepare + audit + dedupe --auto + needs + verify(offline) + build with defaults: a complete, honest first deliverable in one call; refine with ingest + build afterwards"""
    import io
    import contextlib
    a.work = a.work or os.path.join(a.out, ".work")
    cmd_prepare(a)
    for fn, ns in ((cmd_audit, argparse.Namespace(work=a.work)), (cmd_dedupe, argparse.Namespace(work=a.work, auto=True)), (cmd_needs, argparse.Namespace(work=a.work, top=15)), (cmd_suggest, argparse.Namespace(work=a.work, sids=None, min_score=0.12)),
                   (cmd_verify, argparse.Namespace(work=a.work, online=a.online, timeout=10, all=False, verbose=False)), (cmd_support, argparse.Namespace(work=a.work))):
        print("\n--- %s" % fn.__name__[4:])
        fn(ns)
    print("\n--- build")
    b = argparse.Namespace(work=a.work, out=a.out, style=a.style, numbering="first", uncited="drop", place="before", punct="ascii", case=a.case, answers=a.answers)
    try:
        cmd_build(b)
    except SystemExit as e:
        if e.code not in (0, 2, None):
            raise
        print("(build exit code %s: see UNFILLED lines above)" % e.code if e.code else "")
    print("\nNothing was inserted or judged automatically: `needs` lists sentences that may need sources, `support` lists doubtful pairs. Record your decisions with `ingest` and run `build` again (same --out).")


# ------------------------------------------------------------------------------------------------ main
def main(argv=None):
    ap = argparse.ArgumentParser(prog="cl.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def P(name, fn):
        p = sub.add_parser(name)
        p.set_defaults(fn=fn)
        return p
    p = P("prepare", cmd_prepare)
    p.add_argument("input", nargs="?")
    p.add_argument("--work", required=True)
    p.add_argument("--lib", action="append")
    p.add_argument("--case")
    p.add_argument("--style", choices=fmt.STYLES)
    p = P("run", cmd_run)
    p.add_argument("input", nargs="?")
    p.add_argument("--out", required=True)
    p.add_argument("--work")
    p.add_argument("--lib", action="append")
    p.add_argument("--case")
    p.add_argument("--answers")
    p.add_argument("--style", choices=fmt.STYLES)
    p.add_argument("--online", action="store_true")
    p = P("suggest", cmd_suggest)
    p.add_argument("work")
    p.add_argument("--sids")
    p.add_argument("--min-score", dest="min_score", type=float, default=0.12)
    for nm, fn in (("audit", cmd_audit), ("needs", cmd_needs), ("dedupe", cmd_dedupe), ("support", cmd_support)):
        p = P(nm, fn)
        p.add_argument("work")
        if nm == "needs":
            p.add_argument("--top", type=int, default=25)
        if nm == "dedupe":
            p.add_argument("--auto", action="store_true")
    p = P("verify", cmd_verify)
    p.add_argument("work")
    p.add_argument("--online", action="store_true")
    p.add_argument("--timeout", type=int, default=10)
    p.add_argument("--all", action="store_true", help="also entries nothing cites")
    p.add_argument("-v", "--verbose", action="store_true")
    p = P("show", cmd_show)
    p.add_argument("work")
    p.add_argument("--sids")
    p.add_argument("--refs", action="store_true")
    p = P("ingest", cmd_ingest)
    p.add_argument("work")
    p.add_argument("file", nargs="?")
    p = P("build", cmd_build)
    p.add_argument("work")
    p.add_argument("--out", required=True)
    p.add_argument("--style", choices=fmt.STYLES)
    p.add_argument("--numbering", choices=["first", "keep"], default="first")
    p.add_argument("--uncited", choices=["drop", "keep"], default="drop")
    p.add_argument("--place", choices=["before", "after"], default="before")
    p.add_argument("--punct", choices=["ascii", "fullwidth"], default="ascii")
    p.add_argument("--case")
    p.add_argument("--answers")
    p = P("convert", cmd_convert)
    p.add_argument("--lib", action="append", required=True)
    p.add_argument("--style", choices=fmt.STYLES, default="gbt7714")
    p.add_argument("--format", choices=["txt", "bib", "ris"], default="txt")
    p.add_argument("--punct", choices=["ascii", "fullwidth"], default="ascii")
    p.add_argument("--out")
    p.add_argument("--dedupe", action="store_true", help="merge duplicate entries that are certain / high confidence before formatting")
    p.add_argument("--prefer", choices=["zh", "en"], help="with --dedupe: keep the Chinese or the Latin-title entry of a bilingual pair (default: the more complete / published one)")
    a = ap.parse_args(argv)
    import zipfile
    import xml.etree.ElementTree as ET
    try:
        a.fn(a)
    except zipfile.BadZipFile:
        raise SystemExit("ERROR: the input is not a valid .docx (corrupt, truncated, or not a Word file). Re-export it from Word as .docx, or give the Markdown / LaTeX source.")
    except ET.ParseError as e:
        raise SystemExit("ERROR: the Word document's XML cannot be read (%s). Re-save it from Word." % e)
    except FileNotFoundError as e:
        raise SystemExit("ERROR: file not found: %s" % e.filename)
    except PermissionError as e:
        raise SystemExit("ERROR: cannot read %s" % e.filename)


if __name__ == "__main__":
    main()
