# citation-ledger · 参考文献与引用管理（挂得对 · 编得顺 · 收得净 · 对得上）

面向「写作04｜参考文献与引用管理」：**判断由模型做，记账由脚本做**。一份稿件里的每个引用标记、每条参考文献、每个决定都记在一本「账」里；模型决定哪句话要引什么、哪些条目是同一篇、来源是否支撑论断，`scripts/cl.py` 负责找全标记、对上条目、按首次出现重排编号、**按原文件格式**改写标记、重生成文末列表、合并重复条目并写明依据、核验条目、记录每一处改动（旧号→新号）。

> 文中数字都来自开发自测（公开基准 + 自造稿件），**不是平台成绩**；没有跑过 DeepSeek 官方 Harness，也没有做过「不加载 Skill 的基础 Agent」对照，因此不宣称相对基线的提升。

## 对应题面的四个问题
| 题面问题 | 做法 | 自查手段 |
|---|---|---|
| 挂得对 | `needs` 用线索（"已被研究 / 广泛使用 / 数字 / 归因方法"）找出缺来源的论断句；`suggest` 按标题/摘要/关键词的共有词给候选条目；`cite … after:` 在句内某短语后（子句级）插入，默认插在句末标点前；审计报告「整段一个引用」「图表注里的引用」「标题里的引用」 | 候选只是线索：逐句读，没有候选就写「材料缺口」，不编造来源 |
| 编得顺 | `build` 对插入/删除/合并后的全文按**首次出现顺序**重排编号、压缩范围（`[3,4,5,6]`→`[3–6]`）、保持标记原样（`[1]`、`<sup>1,2</sup>`、Word 上标 run、`\cite{}`、`(Smith, 2020)`），重生成文末列表，并**重新解析自己的输出**检查「编号 1..N 连续、与列表同步、首次出现有序」 | 对生成稿件的不变量测试：每个标记重排前后指向同一篇文献，第二次 build 不再改动 |
| 收得净 | `dedupe`：DOI / arXiv / ISBN / 标题+首作者 / 预印本↔正式版 / 中英文题名（姓氏拼音）/ 期刊卷页，并带「同名异文」保护；每个合并写明命中的规则和字段冲突（年份、页码），正式版优先 | DBLP–ACM 公开基准：自动合并精确率 0.958、召回 0.943（见下） |
| 对得上 | `verify`：离线只查结构（年份范围、页码顺序、ISBN/ISSN 校验位、DOI 格式、占位文本），**离线从不写"已核验"**；`--online` 查 Crossref，给出 verified / mismatch（列出差异）/ not_found；`support` 筛论断句与所引条目的主题重合与数字；`judge` 由你读后记录 supported / partial / unsupported / unverifiable | 无网络时两次失败即停并如实说明；证据不足的句子进入人工确认清单 |

## 目录
```
SKILL.md                         Agent 入口：何时用、步骤、决定块格式、质量规则、异常处理
README.md                        本文件
scripts/cl.py                    命令行：run / prepare / audit / needs / suggest / dedupe / verify / support / show / ingest / build / convert
scripts/bib.py                   读取 BibTeX / RIS / EndNote / RefWorks / CNKI·NoteExpress / CSL-JSON / 文本条目，统一记录
scripts/cite.py                  识别正文标记（方括号、上标、著者-出版年、\cite、pandoc）与文末列表
scripts/dedupe.py                可解释的重复判定与合并
scripts/fmt.py                   GB/T 7714-2015、APA 7、IEEE、Vancouver 格式化；BibTeX / RIS 导出
scripts/verify.py                结构核验 + Crossref 在线核验
scripts/segment.py, nlib.py, parse_pdf.py   读取 md/txt/tex/docx/pdf、句子定位、写回原格式（Word 修订痕迹）
references/                      决定块格式、样式与实测一致率、导入导出格式、去重规则与基准、故障处置
examples/                        自造稿件（Markdown / LaTeX / 中文 Word / APA 著者-年）+ 决定文件 + 真实运行输出
GITHUB_URL.txt                   作品的 GitHub 公开链接
dev/ （仅仓库）                  55 个回归测试、与 CSL 参考实现的格式对照、DBLP–ACM 去重评测、示例生成脚本
```

## 依赖与安装
- Python 3.9+，只用标准库（已在系统 Python 3.9.6 上跑通）。`.docx` 用 zipfile/XML 读写；PDF 输入需要环境里有 `pymupdf`、`pdfplumber` 或 `pypdf` 之一（结果以 Markdown 交付）；在线核验需要能访问 api.crossref.org（没有也不影响其他功能）。
- 输入：`.md` `.txt` `.tex` `.docx` `.pdf`（有文本层）+ 文献库（`.bib` `.ris` `.enw` `.json` CSL、CNKI/NoteExpress 导出、纯文本列表），或 `/input/case.json` 指向的文件；中文与英文。

## 使用步骤
```bash
python3 scripts/cl.py run manuscript.docx --lib refs.bib --lib export.ris --style gbt7714 --out out --online
python3 scripts/cl.py show out/.work --refs                 # 句子编号 S012、标记、条目 id
python3 scripts/cl.py ingest out/.work decisions.txt        # cite / uncite / merge / keepsep / replace / meta / judge
python3 scripts/cl.py build out/.work --out out             # 重排、改写、重生成列表、写 result.json
python3 scripts/cl.py convert --lib refs.bib --style apa7 --dedupe --out refs.apa.txt   # 只转格式
```
`run` 一次完成准备、审计、高置信度合并、缺来源论断清单、候选来源、离线结构核验（`--online` 时在线）、重建与 `result.json`；它**不会替你插入或判断**任何引用。决定块语法见 `references/ingest-format.md`。

## 输出
`manuscript.<ext>`（Word 另有 `manuscript_tracked_changes.docx`，有 LibreOffice 时再给 PDF 预览）、`references.<style>.txt`、`references.bib`、`references.ris`、`changes.md/json`（标记旧→新、插入、删除、丢弃的未引用条目、合并依据与字段冲突）、`numbering_map.csv/json`、`ledger.json`（每个引用→条目→决定）、`review_checklist.md`、`result.json`（按 `output_contract` 的字段填充，推导不出的置 `null` 并列在 `_meta.unfilled_fields`）。

## 实测（开发自测，不是平台成绩）
| 项 | 结果 |
|---|---|
| 回归测试 | `python3 dev/test_all.py`：55 个测试通过，含 40 份随机生成稿件的不变量（重排前后每个标记指向同一篇、编号 1..N 且按首次出现、二次 build 幂等）和 40 份植入缺陷稿件（审计检出的无法解析/未引用数与植入数完全一致） |
| 解析 | BibTeX / RIS / EndNote / CSL-JSON / NoteExpress 同一条目解析一致；GB/T、APA、IEEE、Vancouver 文本条目的类型/年/卷/期/页解析；多作者 `Family, I., Family, I., & Family, I.` |
| 格式与 CSL 参考实现的一致率 | GB/T 7714-2015：168 条中 134 条逐字相同（80%，字符相似度 0.989；期刊 36/39）；APA 7：27/47（57%）；IEEE：28/47（60%）。这是**与 CSL 实现的一致**，不是与标准本身的一致；规则在这批条目上调过，对未见类型偏乐观；章节/报告/学位论文差距较大 |
| 去重（DBLP–ACM 公开基准） | 自动合并 TP 2098 / FP 92 / FN 126：精确率 0.958、召回 0.943、F1 0.951；另有 193 对留给人确认（其中 61 对为真）。阈值在同一数据上调过，无基线对照 |
| 在线核验 | 4 条公开记录实测：正确 DOI → verified；年份被改 → mismatch（指出 2016 vs 2015）；伪造 DOI → not_found；仅标题 → verified。无网络时 2 次失败即停 |
| 格式保真 | Markdown / LaTeX / 中文 Word（上标 run 保留，修订痕迹版 XML 有效）/ 著者-年 APA 稿件端到端跑通；Word 修订痕迹**未在 Word 里打开验证**（本机无 Word / LibreOffice，只验证了 XML 可解析与 ins/del 存在） |

## 限制（如实写在这里）
- 不找新文献：只用稿件与文献库里有的条目；论断—来源是否匹配由读摘要的人/模型判断，脚本只做词汇筛查，**不读全文**。
- 不处理 Word 脚注式引用、Zotero/EndNote 域代码、表格/文本框内的引用、参考文献图片（无 OCR）；含域/超链接的 Word 段落原样保留并报告。
- 拼音表只覆盖约 190 个常见姓氏，罕见姓氏的中英文条目最多到「候选」；格式化器对章节编者/丛书/报告号/学位论文措辞有已知差距（`references/styles.md`）。
- 同一决定重复提交会替换前一条；句子编号只在同一个工作目录内稳定（重新 `prepare` 前后可能不同）。

## 方法说明
1. **读取层**：`segment.py` 把稿件拆成段与句（Word 上标 run 读作 `<sup>…</sup>`；含域/超链接/图的段落冻结），`cite.py` 在段文本里找标记并记录精确偏移，所以改写只替换标记本身。
2. **条目层**：`bib.py` 把所有来源统一成同一种记录；稿件文末列表与文献库按 DOI/标题匹配（预印本与正式版**不**自动当作同一条，留给 `dedupe` 写明依据）。
3. **账本**：每个标记 → 条目；`ingest` 的决定追加到账本；`build` 从「原稿 + 决定」重新计算，所以可重复、幂等。
4. **重建**：合并重定向 → 删除/插入 → 按首次出现编号 → 标记按原形式改写 → 列表按目标样式重生成 → 重新解析输出自检。
5. **诚实**：未核验、未判断、无法解析、假设（按文献库顺序解析编号）都进入 `uncertainty` / `review_checklist.md`，不写成已完成。

## 复现
`python3 dev/test_all.py`；格式对照与去重评测的数据来源与复现步骤见 `dev/README.md`。示例输出由 `dev/make_examples.py` 用真实命令生成，**是示例，不是任何评测案例的结果**。


## 示例文件的后缀
平台只接受部分文件类型作为 Skill 资源，所以示例里这些文件的名字后面加了 `.txt`：`examples/md/library.ris`。去掉 `.txt` 就是脚本实际读写的文件名；脚本本身的输出文件名没有变。
