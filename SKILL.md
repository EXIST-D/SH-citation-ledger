---
name: citation-ledger
description: Manage the citations of a manuscript (Word .docx, Markdown, LaTeX, plain text, PDF) together with its reference list and bibliography files (BibTeX, RIS, EndNote, RefWorks, CNKI/NoteExpress, CSL-JSON). Audits markers against the list, places citations on the sentence that needs them, renumbers by first appearance and rewrites markers (ranges, superscripts, author-year) with the list in GB/T 7714-2015, APA 7, IEEE or Vancouver, merges duplicate entries with an explainable rule, screens references for invented or wrong metadata, checks claim-to-source fit, and writes a tracked-changes manuscript, change log and result.json. Use for "add / fix / renumber / dedupe / convert / verify citations and references". Python 3.9+ standard library only.
---

# citation-ledger

Every citation of a manuscript, every reference, and every decision about them live in one **ledger**. You make the judgement calls (which sentence needs which source, which entries are the same work, whether a source supports a claim); `scripts/cl.py` does the bookkeeping that language models get wrong: finding every marker, resolving it to an entry, renumbering, rewriting in the document's own format, regenerating the list, and recording old → new.

Use it for: inserting citations at the right sentence, fixing numbering after insert / delete / reorder, merging duplicates (Chinese + English title, preprint + published, different database exports), converting between BibTeX / RIS / EndNote / CNKI and GB/T 7714-2015 / APA 7 / IEEE / Vancouver, checking whether references exist and say what the text says.
Not for: finding new literature (it never adds a work that is not in the materials), writing prose, or peer review.

```bash
S=/skills/weekly-skill/scripts/cl.py      # or the scripts/ folder next to this SKILL.md
```
Budget (64 model requests, 900 s): one `run` call gives a complete, honest first deliverable; spend the remaining requests on judgement, not on retyping.

## Procedure

1. **Read the task and the case** (`/input/task.md`, `/input/case.json`): which file is the manuscript, which are libraries, target style, what must be inserted / deleted / merged. Task wording beats every default here.
2. **One call does everything mechanical:**
   ```bash
   python3 $S run --case /input/case.json --out /app/output --online
   ```
   (or `python3 $S run MANUSCRIPT --lib lib1.bib --lib lib2.ris --style gbt7714 --out /app/output --case /input/case.json --online`). `--online` looks references up at api.crossref.org (only DOI / title / first authors / year of each reference are sent, nothing of the manuscript); with no network it gives up after two failures and says so, so it is safe to leave on. Without `--style` the list keeps the style it already has (detected); pass `--style` when the task names a target. It prepares, audits, auto-merges high-confidence duplicates, lists claim sentences without a source (`needs`), screens each pair (`support`), checks reference structure (offline), rebuilds the manuscript with renumbering, and writes `result.json`. Nothing is inserted or judged for you at this stage. Read its output top to bottom.
3. **Read the manuscript with the ledger** when the task needs insertions, doubtful merges or claim checks:
   `python3 $S show /app/output/.work --refs` prints every sentence with its id (`S012`), the markers on it and what they resolve to, and every entry (id, title, authors, venue, year, DOI); `--sids S004-S020` limits it for long papers.
   `python3 $S suggest /app/output/.work [--sids …]` ranks library entries for sentences that need a source by shared content words with title / abstract / keywords (a screen, not a judge; "no entry shares enough words" means a material gap, not a reason to invent).
4. **Record decisions** (plain text blocks, any number per file, re-runnable; full syntax in `references/ingest-format.md`):
   ```
   === cite S012
   keys: smith2020, lee2019
   after: reduces cooling load          # optional: put the marker right after this phrase (clause-level); default: before the sentence's final punctuation
   === uncite S020
   keys: lee2018
   === merge
   canonical: smith2020
   members: smith2020, ref014
   reason: same DOI; ref014 is the RIS export of the same article
   === keepsep
   a: wang2019a
   b: wang2019b
   reason: same first author and year, different titles and venues
   === replace
   old: 9              # an unresolved marker number / key, or an entry id
   new: smith2020
   === meta ref007
   year: 2021
   doi: 10.xxxx/yyyy
   reason: the library had the online-first year
   === judge S012
   key: smith2020
   verdict: partial     # supported | partial | unsupported | unverifiable
   note: the paper reports 9%, the sentence says 14%
   ```
   `python3 $S ingest /app/output/.work decisions.txt`  (rejected lines are printed with the reason; fix and re-run).
5. **Rebuild** with the same output folder: `python3 $S build /app/output/.work --out /app/output --case /input/case.json [--style apa7] [--numbering keep] [--uncited keep]`. It prints `POST-BUILD PROBLEM` lines when the rebuilt manuscript fails its own checks (numbers not 1..N, list and citations out of step): fix the cause, never hide it.
6. **Fill what the contract needs.** `result.json` is derived from the case's `output_contract`: fields it can compute are filled; the rest are `null` and listed in `_meta.unfilled_fields` and on the console as `UNFILLED`. Put your own content for those fields in `answers.json` (`{"field": value}`) and re-run `build --answers answers.json`. Never leave a contract field out and never invent content for it.
7. **Final check before you stop** (all must hold): `post_build_problems` empty or explained; no marker still shown as `?N` / unresolved unless the materials really lack the source (then it is in the human-review list); every inserted citation was decided by you from the sentence and the source's title / abstract; `references_not_verified` / `unchecked` stated as such.

## Rules that decide quality

- **Put the citation where the claim is.** A citation belongs to the sentence (or clause, with `after:`) that makes the claim, not the paragraph end, not a caption, not the heading. One sentence with two independent claims may take two markers (`after:` for the first); several consecutive sentences resting on the same source take a marker at the sentence where the source is first used and, if the passage is long, again at its last sentence: say in `reason:` which sentences a marker covers. Your own results, definitions you introduce, and common knowledge need none. `needs` is a screen with cues (reports prior work, "widely used", numbers, attributed methods), not an oracle: read the sentence.
- **Only cite what the materials contain.** Keys must exist in the library or the reference list. If a sentence needs a source and no entry fits, do not invent or recall a reference: leave it, and list it as a material gap in `answers.json` / the review list.
- **Merge only with a reason, and say it.** `dedupe` shows the rule that fired (same DOI / arXiv id / ISBN, same normalised title and first author, preprint + published version, Chinese + English title of one work via pinyin of the surname). Same first author and year with different titles are different works (homonym guard): keep them apart with `keepsep`. Canonical = published version over preprint, complete over partial. Conflicting fields (year, pages) are listed, not silently overwritten.
- **Offline is not verification.** Without network access `verify` only checks structure (year range, page order, ISBN / ISSN check digits, malformed DOI, placeholders) and says `unchecked`. `verify --online` queries Crossref when reachable; `mismatch` and `not_found` go to the human-review list with the differences. Never write "verified" for an entry nothing external confirmed.
- **Claim-to-source fit is judged by reading.** `support` flags pairs with no topical overlap or numbers absent from the abstract; it cannot read full text. Judge what you can from title + abstract, record `judge` verdicts, and mark the rest `unverifiable`: say which sentences have insufficient evidence.
- **Keep the author's format.** Markers keep their form (`[1]`, `[1, 2]`, `<sup>1,2</sup>`, `\cite{}`, `(Smith, 2020)`); ranges compress to `1–3`; Word output keeps superscript runs and offers `manuscript_tracked_changes.docx`. The reference list is regenerated in the target style; uncited entries are dropped by default (listed in `changes.md`; `--uncited keep` retains them).
- **Chinese and English together.** GB/T 7714 gets the type marks ([J] [M] [C] [D] [R] [S] [P] [EB/OL] [N]), `等` / `et al.` after three authors, initials without dots for Western names; APA / IEEE keep Chinese names unreversed.

## Outputs (in `/app/output`)

`manuscript.<ext>` (+ `manuscript_tracked_changes.docx` for Word), `references.<style>.txt`, `references.bib`, `references.ris`, `changes.md` / `changes.json` (marker old → new, inserted, removed, dropped, merges with rationale and field conflicts), `numbering_map.csv|json`, `ledger.json` (each citation → entries → decisions), `review_checklist.md`, `result.json` (contract fields + `_meta`). Optional: `verification.json`, `support.json`, `audit.json` in `.work`.

## Exceptions

| Situation | Do |
|---|---|
| Marker points to nothing (`unresolved_citation`) | `replace` it with the right entry if the text tells you which, `uncite` it if it is a typo; otherwise leave and report |
| Several library files with clashing ids | ids get the file name suffix automatically; use the ids `show --refs` prints |
| Manuscript has no reference list | numeric markers are resolved by library order (flagged as an assumption in `uncertainty`), a list is appended |
| PDF manuscript | needs `pymupdf`, `pdfplumber` or `pypdf` in the environment; text is extracted to Markdown, the deliverable is Markdown, say so; if extraction fails the message says why: ask for / use another format |
| Only libraries, no manuscript (convert / dedupe / format task) | `python3 $S convert --lib a.bib --lib b.ris --style gbt7714 [--dedupe] [--prefer zh\|en] [--format txt\|bib\|ris] --out refs.txt`; read its `merged duplicates:` line and report the rule for each merge from `dedupe` |
| Entry cannot be parsed (`reference_not_parsed`) | keep its raw text, fix fields with `meta`, or report it |
| Style not supported | tell the user which of GB/T 7714-2015, APA 7, IEEE, Vancouver is closest; do not fake another |
| Tracked-changes docx cannot be previewed | no LibreOffice here: the `.docx` XML is valid but not rendered; say so |

More: `references/ingest-format.md` (decision blocks), `references/styles.md` (what each style produces and its measured agreement with CSL), `references/formats.md` (import/export formats and fields), `references/dedupe-rules.md`, `references/failure-modes.md`. A worked example is in `examples/`; its outputs are examples, not results of any evaluation case.
