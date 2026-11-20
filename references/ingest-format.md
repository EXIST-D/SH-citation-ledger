# Decision blocks (`cl.py ingest WORK FILE|-`)

A block starts with a line `=== <kind> <target>` (also `## ` or `**`-wrapped is accepted) followed by `key: value` lines; a value may continue on the next lines. Blocks can be given any number of times and in any order; the same decision twice replaces the earlier one (re-running a file changes nothing). Rejected blocks are printed with the reason and the exit code is 2.

| Block | Keys | Effect |
|---|---|---|
| `=== cite S012` | `keys` (entry ids, comma separated), `after` (phrase inside the sentence; optional), `place` (`before`/`after` the final punctuation; default before), `reason` | adds a marker in the document's own form (`[n]`, superscript, `(Author, Year)`, `\cite{}`); a key already cited in that sentence is not added again |
| `=== uncite S012` | `keys` (entry ids, or the number / key of an unresolved marker) | removes those references from that sentence's markers; a marker left empty is removed with its space |
| `=== merge` | `canonical`, `members`, `reason` | members become one entry (fields filled from the others, conflicts listed in `changes.md`); markers pointing to any member now point to the canonical entry |
| `=== keepsep` | `a`, `b`, `reason` | the pair is never proposed again |
| `=== replace` | `old`, `new`, `reason` | old entry id **or the unresolved number/key a marker uses** → new entry |
| `=== meta ENTRY` | `title year authors doi container volume issue pages publisher type url`, `reason` | corrects fields before formatting; the entry is marked `corrected` |
| `=== judge S012` | `key`, `verdict` (`supported partial unsupported unverifiable`), `note` | stored in `ledger.json`; non-supported verdicts go to the review checklist |

Sentence ids come from `show` (`S001` …) and are stable for one prepared work folder. Entry ids come from `show --refs`: library ids (BibTeX key, RIS/EndNote id or `refNNN`), `L<n>` for list entries that matched no library entry.

Ranges of sentences in `show`: `--sids S004-S009,S012`.
