#!/usr/bin/env python3
"""Render CSL-JSON items with a CSL style through citeproc-py (development oracle, not a runtime dependency)."""
import json
import os
import sys
import warnings

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "_deps"))  # pip install --target dev/_deps citeproc-py lxml
from citeproc import Citation, CitationItem, CitationStylesBibliography, CitationStylesStyle, formatter
from citeproc.source.json import CiteProcJSON

REF = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ref")


def render(items, style_path, ids=None):
    src = CiteProcJSON(items)
    st = CitationStylesStyle(style_path, validate=False)
    bib = CitationStylesBibliography(st, src, formatter.plain)
    for it in items:
        if ids is None or it["id"] in ids:
            bib.register(Citation([CitationItem(it["id"])]))
    out = {}
    for item, ent in zip([i for i in items if ids is None or i["id"] in ids], bib.bibliography()):
        out[item["id"]] = str(ent)
    return out


if __name__ == "__main__":
    items = json.load(open(os.path.join(REF, "gbt", "items.json"), encoding="utf-8"))
    r = render(items[:12], os.path.join(REF, "gbt", "style.csl"))
    for k, v in list(r.items())[:12]:
        print(k, "|", v)
