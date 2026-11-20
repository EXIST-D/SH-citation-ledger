# Duplicate decisions: rules, guards, evidence

`dedupe.compare(a, b)` returns `same | candidate | different` with the rule that fired and a reason string; `dedupe.clusters` joins `same` pairs transitively and elects the canonical entry (published over preprint, complete over partial, library over list text).

## Rules (each pair gets every rule that fired, a decision and a confidence)
| Rule | Condition | Decision |
|---|---|---|
| `doi` | same DOI | same (certain) |
| `arxiv` | same arXiv id, version suffix ignored | same (certain) |
| `isbn` | same ISBN and same edition | same (certain) |
| `bilingual` | one Chinese and one Latin title, same year, same volume and first page, and (Chinese first author's pinyin = Latin family name, or same issue) | same (high); only volume + first page, or first page + pinyin → candidate |
| `title+author` | identical normalised title (accents, case, stop words removed), same first author, years within 1 | same (high) |
| `version_pair` | title similarity ≥ 0.88, same first author, years within 3, one side a preprint or journal / conference / preprint types differ | same (high), `work pair`: canonical = the published version |
| `fuzzy` | title similarity ≥ 0.90, same first author, years within 1, pages not contradicting → same (medium); similarity 0.80–0.90 → candidate | same / candidate |
| `venue` | same journal, volume, pages, year, first author, title similarity ≥ 0.7 | same (high) |

The pinyin table covers about 190 common surnames incl. compound ones (欧阳, 司马…); an uncommon surname never matches, so such a Chinese–English pair stays a candidate at best.

## Guards against false merges
- different DOIs and different titles (< 0.8 similar) → different; different DOIs with similar titles are kept as evidence (`preprint / published?`);
- same title (≥ 0.9) but no common author family name → different ("Introduction", "Editorial" style titles);
- short titles (≤ 4 content words) need more author agreement and the same year;
- author overlap is Jaccard on family names with encoding-noise tolerance (`Müller` / `Muller`, `FAN` / `Fan`); a single-author record is not treated as a disagreement;
- same first author and year with unrelated titles are `guarded`: listed with the reason they were kept apart.

## Measured on a public benchmark
DBLP–ACM entity matching (2,616 + 2,294 records, 2,224 true matches; `dev/dedupe_eval.py`): blocking proposes 50,625 candidate pairs; merged automatically precision 0.958, recall 0.943, F1 0.951; 193 pairs are left to a person as `candidate` (61 of them true matches). The thresholds were tuned on the same data, there is no comparison with a baseline, and bibliographic-database duplicates differ from manuscript libraries (more DOI-bearing entries there), so read the numbers as an indication of the rules' behaviour, not a guarantee.

## What the person must still do
`candidate` pairs and every `work pair` (preprint + published) need a decision: `=== merge` or `=== keepsep`. Merging replaces the markers of all members by the canonical entry; the change log lists each merge, the rule, and every field conflict (year, pages, venue).
