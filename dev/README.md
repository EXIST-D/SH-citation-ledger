# dev/ - tests and evaluations of citation-ledger (not part of the Skill runtime)

| file | what |
|---|---|
| `test_all.py` | 54 regression tests (stdlib `unittest`): author splitting, every import format, text-entry parsing, marker detection, formatting, duplicate rules and guards, structural verification, fail-fast online verification, end-to-end md / tex / docx / author-year, contract fields, 40 generated manuscripts (invariants) and 40 manuscripts with seeded defects (audit = ground truth). `python3 dev/test_all.py [-v]` |
| `format_eval.py [gbt7714\|apa7\|ieee] [N_worst]` | agreement of `fmt.py` with citeproc-py + the official CSL styles on the 226 items of the GB/T 7714-2015 CSL repository (needs `pip install --target dev/_deps citeproc-py lxml`) |
| `dedupe_eval.py` | duplicate detection on the DBLP–ACM benchmark |
| `oracle.py` | renders CSL-JSON with a CSL style (the oracle used by `format_eval.py`) |
| `make_docx.py` | builds a small .docx with the standard library (superscript runs) for tests and examples |
| `make_examples.py` | regenerates `submission/examples/*/out` and `run.txt` from real runs |
| `fixtures/` | text spec of the Chinese Word example |

## Data (not in the repository: download it yourself, licences stay with the authors)
Put the files in `dev/ref/`:
- `apa.csl`, `ieee.csl`, `locales-en-US.xml`, `locales-zh-CN.xml`: from the CSL style and locale repositories (https://github.com/citation-style-language/styles, https://github.com/citation-style-language/locales).
- `gbt/style.csl`, `gbt/items.json`, `gbt/cites.json`: the style `chinese-gb7714-2015-numeric` of https://github.com/zotero-chinese/styles with the test items of its documentation page.
- `dblp_acm/DBLP2.csv`, `ACM.csv`, `DBLP-ACM_perfectMapping.csv`: the DBLP-ACM entity-resolution benchmark of the Leipzig database group (https://dbs.uni-leipzig.de/research/projects/benchmark-datasets-for-entity-resolution).
- `dev/_deps/`: `pip install --target dev/_deps citeproc-py lxml` (only `format_eval.py` / `oracle.py` need it).

All example manuscripts, authors, journals and DOIs in `submission/examples` are fictional (DOI prefix 10.9999 is unregistered).
