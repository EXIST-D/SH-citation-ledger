# Target styles and how well they agree with a reference implementation

`--style` is one of `gbt7714` (GB/T 7714-2015, numeric), `apa7`, `ieee`, `vancouver`. Default: author-year manuscripts → `apa7`; Chinese-language manuscripts → `gbt7714`; otherwise `ieee`. `--punct fullwidth` writes full-width punctuation in GB/T entries of Chinese works.

## What is produced

- **GB/T 7714-2015**: type marks `[J] [M] [C] [D] [R] [S] [P] [EB/OL] [N]`; up to three authors then `等` (Chinese) / `et al.` (Western); Western names `FAMILY G I` (upper-case family, initials without dots, space between initials); `. 年, 卷(期): 页.`; translators `译`; chapters `A//B. 出版地: 出版者, 年: 页`; patents `P. 国别, 号: 日期`; web `[EB/OL]. (更新日期)[引用日期]. URL`.
- **APA 7**: `Family, G. I., & Family, G. I. (Year). Title. *Journal*, *vol*(issue), pages. https://doi.org/…`; 21+ authors elided; sentence-case titles are kept as stored (never re-cased); in-text `(Smith & Lee, 2020)`, `(Smith et al., 2020)`.
- **IEEE**: `G. I. Family, "Title," *Journal*, vol. v, no. n, pp. a–b, Year, doi: …`; `et al.` after six authors; web adds `Accessed: Mon. D, YYYY. [Online]. Available: …`.
- **Vancouver**: `Family GI, Family GI. Title. Journal. Year;vol(issue):pages.`; six authors then `et al.`.

Fields that the source does not have are left out, never invented (a missing field is reported by `reference_fields_missing`).

## Measured agreement (development oracle)

`dev/format_eval.py` renders the 226 test items of the public GB/T 7714-2015 CSL style repository (and the same records for APA / IEEE) with citeproc-py and the official CSL styles, and compares after whitespace/quote normalisation. These are **agreement with the CSL implementation, not with the standard**, which the CSL itself approximates in places; the rules were tuned on these items, so they are optimistic for unseen entry types.

| Style | items | identical | mean character similarity | best types | weakest types |
|---|---|---|---|---|---|
| GB/T 7714-2015 | 168 | 80% | 0.989 | journal 36/39, newspaper 5/5, thesis 4/4, web 7/7, standard 6/7 | chapter 5/13, book 60/73, report 3/7 |
| APA 7 | 47 | 57% | 0.960 | journal 16/20 | chapter 0/3, conference 0/1 |
| IEEE | 47 | 60% | 0.985 | book 16/19 | journal 12/20, chapter 0/3 |

Known gaps: container editors and series information in chapters, report numbers, thesis degree wording, some corporate-author forms. Check these entry types by eye after conversion; `review_checklist.md` does not flag them because the tool cannot know which form the target journal wants.
