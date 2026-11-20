# Input and output formats

| Format | Detected by | Notes |
|---|---|---|
| BibTeX / BibLaTeX (`.bib`) | `@type{key,` | `@string`, concatenation with `#`, nested braces, LaTeX accents, `and`-separated authors, `others`; `eprint`+`archiveprefix` → arXiv id |
| RIS (`.ris`, also PubMed/Zotero/Scopus exports) | `TY  - ` | `TY` types, `AU/A1`, `TI/T1`, `JO/JF/T2`, `PY/Y1/DA`, `SP/EP`, `DO`, `UR`, `AB`, `KW`, `SN`, repeated tags |
| EndNote tagged (`.enw`) | `%0 ` | `%A %T %J %D %V %N %P %R %U %X` |
| RefWorks tagged | `RT ` | `A1 T1 JF YR VO IS SP OP` |
| CNKI / NoteExpress / 万方 export | `{Reference Type}:` or `Author-作者:` blocks | Chinese author lists with `;`, 题名/刊名/年/卷/期/页码/DOI |
| CSL-JSON (`.json`) | JSON array of items with `type`, `title` | Zotero / Pandoc native |
| Plain text lists | one entry per paragraph or numbered line | GB/T 7714, APA, IEEE, Vancouver and Chicago-like entries; unrecognised structure → `reference_not_parsed`, raw text kept |

Record fields: `id type authors[{family,given,literal,zh}] title container year volume issue pages publisher place doi url accessed arxiv isbn issn edition language abstract keywords note number date translators editors container_authors authors_role raw source parse{confidence,missing}`. Types: `journal book chapter conference thesis report standard patent web preprint newspaper other`.

Outputs written by `build`: `references.<style>.txt` (the list as placed in the manuscript), `references.bib` (BibTeX of the cited entries; keys = entry ids, so LaTeX `\cite` keys still work), `references.ris`, plus `convert --lib FILE --style S --format txt|bib|ris [--dedupe]` for libraries without a manuscript.

Manuscript formats: `.docx` (paragraphs with fields, hyperlinks, drawings, footnotes are left untouched and reported; superscript runs preserved; tracked-changes copy `manuscript_tracked_changes.docx`), `.md`, `.txt`, `.tex` (`\cite*` commands and `thebibliography`; `\bibliography{…}` is pointed at the generated `references.bib`), `.pdf` (text extracted to Markdown, deliverable is Markdown).

Not handled: footnote-style citations in Word (field codes), Zotero/EndNote field codes inside Word, citations inside tables or text boxes, images of reference lists (no OCR).
