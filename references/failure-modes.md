# Failure modes seen in citation work, and what this skill does about them

| Failure | Symptom | Handling |
|---|---|---|
| Citation at paragraph end / in caption | one marker for six sentences; marker in a figure caption | `needs` lists claim sentences; audit flags `single_citation_for_long_paragraph`, `citation_in_caption`, `citation_in_heading`; `cite … after:` places a clause-level marker |
| Numbers do not follow first appearance after edits | `[3]` appears before `[1]`; gaps; a list longer than the cited numbers | `build` renumbers from the document order, rewrites every marker with its original form, regenerates the list, and re-parses its own output to check 1..N |
| Range written as `[3, 4, 5, 6]` | audit `range_not_compressed` | rebuilt as `[3–6]` (or the document's own range character) |
| Marker points to nothing | `[8]` with 7 entries | `unresolved_citation`; stays visible as `?8` / unchanged until `replace` or `uncite` |
| Reference never cited | list entry without marker | `uncited_reference`; dropped by default, listed in `changes.md` |
| Same work twice | Chinese + English title, preprint + published, two exports | `dedupe` with rule and conflicts; homonym guard |
| Invented / wrong entry | no DOI, impossible year, ISBN check digit fails | `verify` (offline structure; `--online` Crossref) → `structural_problem`, `mismatch`, `not_found` in the review list |
| Claim not supported by source | sentence about 14%, abstract says 9% | `support` screens topic overlap and numbers; you `judge` by reading; anything not checkable is `unverifiable` |
| Format drift on conversion | lost DOI, volume/issue merged, Chinese punctuation wrong | typed records, field-by-field formatter, GB/T type marks; missing fields reported, never invented |
| Word file with superscript markers | superscripts flattened to plain digits | superscript runs are read as `<sup>…</sup>` and written back as superscript runs |
| Manuscript without a reference list | numeric markers, only a library | resolved by library order and flagged as an assumption; list appended |

Reading limits: no OCR; PDFs go through text extraction; fields/hyperlinks/footnotes in Word are not touched; Crossref lookup needs network access; claim-to-source judgement is yours, the tool only screens.
