# 雅思听力全量出题规则参考文档

> 用途：开源项目出题质量对照参考（**不直接喂给 LLM**，暂不接入任何提示词）。
> 编制日期：2026-10-22。资料来源：British Council / ielts.org / IDP 官方页面、剑桥真题（Cambridge IELTS 系列）、权威备考站（IELTS Liz、IELTS Jacky、ielts-up 等），文末附全部链接。
> 说明：雅思官方机构为 British Council、IDP、Cambridge University Press & Assessment 三方共有，官方口径以 ielts.org 与 takeielts.britishcouncil.org 为准；具体题目惯例以剑桥真题（Cambridge IELTS 4–19）为准。

---

## 1. 考试总体结构（官方事实）

| 项目 | 官方规则 |
|---|---|
| 时长 | 约 30 分钟（录音只播放一遍，"You will hear a number of different recordings and you have to answer questions on what you hear. There will be time for you to read the instructions and questions and you have 30 seconds to check your answers."） |
| 结构 | 4 个 Part（2020 年 1 月前称 Section），每 Part 10 题，共 40 题 |
| 场景 | Part 1–2 日常生活/社交场景；Part 3–4 教育与培训场景 |
| 各 Part 形式 | Part 1：双人社交对话（如咨询/报名）；Part 2：单人社交独白；Part 3：2–4 人教育/培训对话（如小组讨论）；Part 4：单人学术讲座 |
| 口音 | 官方明确 "a range of accents"（英/澳/新/美/加等） |
| 答题 | 纸笔考试有 10 分钟誊写答案时间；机考只有 2 分钟检查时间（无誊写） |
| 2020-01-04 起的变化 | 取消 Part 1 开头的例题（example）；"Sections" 改称 "Parts"；题册不再标注页码。录音直接从第 1 题开始，难度设计上仍保持由浅入深 |

来源：ielts.org Listening test format；takeielts.britishcouncil.org Listening Test Format；IDP "IELTS Focus – Listening" 官方 PDF；ieltsliz.com 2020 changes。

---

## 2. 官方题型全集（Task Types）

British Council 官方页面表述为 **"There are six task types in the IELTS Listening section"**，并在页面上逐一定义。结合 ielts.org 的 "Question type 1–6" 定义与剑桥真题惯例，全集如下（官方英文定义保留原文）：

### 2.1 Form / Note / Table / Flow-chart / Summary completion（表格/笔记/流程图/摘要填空）
- 官方定义（BC/ielts.org）："This task type requires you to fill in gaps in an outline of the recording using words from the recording. The outline may be a form, a set of notes, a table, or a flow-chart."
- 典型分布：**Part 1 几乎必考**（Form/Table 为主，对话填表场景）；**Part 4 几乎必考**（Note/Summary completion，学术讲座笔记）。Part 2/3 偶见 Note/Flow-chart。
- 题量惯例：每组 5–10 题。Part 1 与 Part 4 通常各占 10 题的大部或全部。
- 计分方式：从录音中取词填空，须遵守指令中的词数限制。

### 2.2 Sentence completion（句子填空）
- 官方定义（ielts.org 措辞）："This task type requires you to complete a sentence using words from the recording."
- 典型分布：Part 2、Part 3 较常见；近年真题中出现频率中等。
- 指令惯例："Complete the sentences below. Write ONE WORD ONLY for each answer." 等。

### 2.3 Short-answer questions（简答题）
- 官方定义："This task type requires you to answer questions about the recording using words from it."
- 典型分布：任一 Part 均可出现，频率较低，通常 3–5 题一组。
- 指令惯例："Answer the questions below. Write NO MORE THAN THREE WORDS AND/OR A NUMBER for each answer."

### 2.4 Multiple choice（单选/多选）
- 官方定义（ielts.org）："This task type requires you to select the correct option(s) from a list (A, B, C…). There may be more than one correct answer."
- 单选惯例：3 选项（A/B/C）为主，每组 3–5 题；**典型分布 Part 3（对话讨论）为高频区**，Part 2 也常见，Part 4 偶见。
- 多选惯例：5–7 个选项（A–E 或 A–F）选 2 个（"Choose TWO letters, A–E"）或选 3 个（A–G 选 THREE）；占两个连续题号（如 Questions 21 and 22）。**两个答案都选对才得满分；只对一个不得分（无部分得分）**；两个字母任意顺序书写均有效。多选常在 Part 2/3。
- 干扰项（distractor option）为本题型核心设计，见第 6 节。

### 2.5 Matching（匹配）
- 官方定义（BC 页面 "Matching information"）："This task type requires you to match a list of items to a set of options in a box."
- 典型分布：**Part 3 高频**（如：学生观点匹配、课程特征匹配），Part 2 常见（如：活动匹配地点/日期）。
- 惯例：题干（数字编号项）按录音顺序出现；选项（字母项）在录音中**乱序**出现；选项是否可重复使用以指令为准（"NB You may use any letter more than once" 出现与否必须明示）。
- 两种呈现：带选项框（box）匹配；或题干与选项分列两栏的匹配。

### 2.6 Map / Plan / Diagram labelling（地图/平面图/示意图标注）
- 官方定义（ielts.org）："This task type requires you to select the correct label for a map, plan, or diagram, or to complete labels with words from the recording."
- 典型分布：**Map/Plan 集中在 Part 2**（校园/小镇/场馆导览独白）；Diagram（机械/流程示意图）偶见 Part 4。
- 两种作答形式：① 从选项框选字母（"Write the correct letter, A–I, next to Questions 15–20"）；② 直接填词（受词数限制约束）。
- 专项规则见第 7 节。

> 权威口径差异说明：BC 页面把填空类合并算 1 种并给出 "six task types"；剑桥真题与多数备考站按上面 6 大类（填空细分后与 BC 口径可对齐）或 8–10 个细分类型（IELTS Jacky 列 10 类：Matching / Multiple Choice / Sentence Completion / Form-Note-Table Completion / Labelling a Map or Plan / Short Answer / Labelling a Diagram / Summary Completion / Classification / Picking from a list）计。出题对照时建议按本节 6 大类归档。

---

## 3. 官方指令句原文全集（Instruction Wording）

按题型整理标准措辞变体（源自剑桥真题与官方样题，保留英文原文）：

### 3.1 填空类（Form/Note/Table/Flow-chart/Summary/Sentence completion）
- `Complete the notes below.` / `Complete the table below.` / `Complete the form below.` / `Complete the flow-chart below.` / `Complete the summary below.` / `Complete the sentences below.`
- 词数限制副指令（紧跟其后的第二行，五种标准变体）：
  - `Choose ONE WORD ONLY for each answer.`
  - `Choose ONE WORD AND/OR A NUMBER for each answer.`
  - `Write NO MORE THAN ONE WORD AND/OR A NUMBER for each answer.`
  - `Write NO MORE THAN TWO WORDS AND/OR A NUMBER for each answer.`
  - `Write NO MORE THAN THREE WORDS AND/OR A NUMBER for each answer.`
- 结尾固定句：`Write your answers in boxes XX–XX on your answer sheet.`（机考无此句）

### 3.2 简答题
- `Answer the questions below.` + `Choose NO MORE THAN THREE WORDS AND/OR A NUMBER from the passage for each answer.`（听力版本通常为 `Write NO MORE THAN THREE WORDS AND/OR A NUMBER for each answer.`）

### 3.3 单选/多选
- 单选：`Choose the correct letter, A, B or C.`；题干可为完整问句（Which…? What…? Why…?）或半句续写（The speaker thinks…）
- 多选：`Choose TWO letters, A–E.` + 具体问句如 `Which TWO facilities at the leisure club have recently been improved?`；三选变体：`Choose THREE letters, A–G.`
- 图表选项选字母：`Write the correct letter, A–I, next to Questions 15–20.`

### 3.4 匹配
- 带选项框：`Choose your answers from the box and write the correct letter, A–G, next to Questions 23–27.`
- 可重复使用提示（出现时必须遵守）：`NB You may use any letter more than once.`
- 无提示时默认每个选项只用一次。

### 3.5 地图/平面图/示意图
- `Label the map below.` / `Label the plan below.` / `Label the diagram below.`
- `Write the correct letter, A–H, next to Questions 16–20.`（选字母型）
- `Write NO MORE THAN TWO WORDS for each answer.`（填词型）

---

## 4. 词数限制与答案书写规范

### 4.1 计数规则（以剑桥答案键与 IELTS Liz 规则汇编为准）
- **连字符词算 1 个词**：`brother-in-law`、`two-bedroom`、`well-known` 均为 1 词（无论几个连字符）；拼写须含连字符才算对。
- **数字算 1 个 number**：`30,000`、`312`、`9.30AM`、`01392 466`（电话号码整体）各算 1 个数字；用数字或英文文字拼写均可（`21` 或 `twenty-one` 等价，后者含连字符算 1 词）。
- **日期算 1 个 number**；`22nd November` = 1 数字 + 1 词（共占 "a number AND a word"）。
- **货币**：`$25` / `25 dollars` 均按数字计（写货币符号或文字均可，答案键两者通用）。
- **AND/OR 含义**：`NO MORE THAN TWO WORDS AND/OR A NUMBER` = 最多"2 词"、"2 词 + 1 数字"、"1 词 + 1 数字"、"仅数字"等组合均合法；超限即 0 分。
- **冠词/介词等虚词**计入词数（不豁免）。

### 4.2 答案键判定规范
- **大小写不敏感**：全大写、首字母大写、全小写均判对（官方答题卡明确 letters can be written in capitals or lower case）。
- **拼写必须精确**：拼错即 0 分（BC 官方视频明确 "strict rules about spelling"）。
- **美式/英式拼写均接受**：`colour/color`、`organise/organize`、`centre/center` 均判对，但同一词内不得混拼。
- **复数必须匹配**：录音用复数、答案写单数判错（反之亦然，视语法与录音而定）。
- 填空答案必须来自录音本身的内容（不要求逐字原词照抄题干外的任何词，但答案词必在录音中出现过）。

---

## 5. 出题顺序与引导规则

- **总原则**：填空、单选、简答、句子填空——答案严格按题号顺序在录音中出现（ielts.org 官方与各备考站一致确认）。
- **例外与细化**：
  - **匹配题**：题号项（数字项）按录音顺序；选项（字母项）乱序出现，且可能复用或不用。
  - **多选题**：两（三）个正确选项在录音中出现的先后与字母顺序无关；正确项之间可能隔着大量错误项讨论。
  - **地图题**：题号仍按录音顺序，但图上空间位置与讲解顺序无关（讲解者从入口开始走动描述，见第 7 节）。
  - **流程图/表格**：内部子题也按顺序，但注意表格分栏时录音可能先讲完一列主题再讲另一列（以表头归类为准）。
- **引导词（题干在录音中的定位）**：业内通称 **signposting / cue words**（注："word steering" 并非官方或行业标准术语）。设计惯例：
  - 录音中不会逐字重复题干，而是**同义替换（paraphrase）**——题干/选项原词在录音中听到时往往是干扰信号，正确答案以同义词出现（如题干 `allocate` ↔ 录音 `give out`；`preferred` ↔ `would rather`）。
  - 答案前常有话语标记引路：`now / moving on to / next / one more thing / as far as X is concerned / let's turn to…`；Part 4 讲座依赖讲义式 signposting（`firstly / however / finally / to sum up`）。
  - 数字/时间/专有名词（拼写）类答案常有字母拼写提示（`That's B-double-O-K…`）和纠错提示（见第 6 节）。

---

## 6. 干扰项与陷阱设计规则（Distractors）

剑桥听力设计的核心陷阱类型（出题自查清单）：
1. **修正语陷阱（correction distractor）**：说话人先给出一个错误值再自我修正——`I thought it was 150 miles… but it's actually 147 miles`、`Let's meet at 3:00… Oh, actually, let's make that 3:30`。**只有修正后的信息是答案**。修正触发词：`actually / sorry / no, wait / on second thought / I'm afraid not / let me correct that`。
2. **首现陷阱**：正确答案出现前先出现一个"像答案"的信息（常为另一说话人提到、或被否定的信息），惩罚"听到什么写什么"的考生。
3. **否定词陷阱**：选项原文被提到但被否定（`It's not cheap`→排除 cheap 项）；否定形式多样：`rather than / instead of / no longer / although / despite`。
4. **同音/近音干扰**：填空答案与近音词竞争（如 `15/50`）；数字、日期、价格为高发区。
5. **多选中"两人共识"限定**：Part 3 多选常要求 `both speakers agree`——仅一人提及、另一人未表态的选项为干扰项。
6. **匹配中的相似选项**：选项语义相近但修饰语不同（`long-term gain` vs `short-term profit`），录音用近义表达区分。
7. **地图中的路径干扰**：先描述途经地标（非答案）再描述目标位置。

---

## 7. 地图/平面图题专项规则

- **底图要素惯例**：图中必给出**入口标注（ENTRANCE / You are here 箭头）**作为起始参照；常有街道名/房间名/指南针（N 箭头）或明确的左右参照系；比例尺一般不出现（不考距离计算）。
- **讲解结构惯例**：说话人从入口出发、按行进路线描述（"walk along / go past / take the first turning on the left / until you reach…"），题号顺序=讲解顺序≠空间顺序。
- **方位词体系**（出题必备词表）：
  - 相对位置：`opposite / across from / facing / next to / beside / alongside / adjoining / adjacent to / between / near / in the corner of`
  - 前后内外：`in front of / behind / at the back of / inside / outside / at the entrance to / by the gate`
  - 超越/末端：`beyond / just past / a little beyond / at the end of (the corridor/path) / past the entrance`
  - 方位极点：`at the top of the map / at the bottom / in the middle of / in the centre of / to the left (of) / to the east of`
  - 行进动词：`go straight ahead / head north / turn left at… / take the second turning on the left / cross the bridge / walk along / go through the doors`
  - 序数与分支：`the first/second/third door on your right / as you go in, X is on your left`
- **陷阱惯例**：描述顺序常"路过非答案地标→再定位答案"；方位参照系可切换（以入口为参照 vs 以另一建筑为参照）。

---

## 8. 各 Part 题型配比惯例（基于剑桥真题通行分布）

| Part | 场景/形式 | 高频题型（按出现频率） | 低频/偶见 |
|---|---|---|---|
| Part 1 | 社交对话（报名/咨询/租房） | Form completion（几乎必考）、Table completion、Note completion | 简答、单选（偶见） |
| Part 2 | 社交独白（导览/介绍） | 单选、Map/Plan labelling、Matching、Note/Table completion、句子填空 | 多选（Which TWO…） |
| Part 3 | 教育/培训对话（讨论/辅导） | 单选（含多选 Which TWO）、Matching、句子填空、Note/Flow-chart completion | 简答、图表填空 |
| Part 4 | 学术讲座 | Note completion / Summary completion（10 题全填空为最常见形态） | 单选、Diagram labelling、Table completion、简答 |

- 全卷 40 题中，**填空类（form/note/table/flow-chart/summary/sentence）通常占约 20–28 题（约 50–70%）**，选择题、匹配题、地图题分食其余；无官方公布比例，以上为剑桥真题（Cambridge IELTS 10–19）通行统计口径（各备考站与教师社区一致口径，如 ieltsjacky.com、myieltsclassroom.com）。
- 每组题目惯例 5–10 题；一个 Part 可含 1–3 个题型组。
- 难度梯度：官方与教师社区共识为 Part 1→Part 4 递增（2020 年取消例题后 Part 1 从第 1 题直接开始，仍最易）。

---

## 9. 评分规则（官方）

- **每题 1 分**：官方原文 "Each correct answer receives 1 mark."
- **无倒扣**（no negative marking）：答错不扣分。
- **无半分题**：单题只有 0/1；多选题（TWO/THREE）按题号合并计分，全对才得该题号分数（一个题号 1 分；Cambridge 答案键将 "Questions 21 and 22" 合并为 2 分，两字母须全对，任意顺序）。
- **最终分数**：40 分原始分换算 1–9 分 band score，**整分或半分**（whole or half bands, e.g. 5.5 or 7.0）——半分出现在 band 换算层面，不在单题层面。
- 通行换算表（各版本略有浮动，以官方当次换算为准）：

| 原始分 | Band | 原始分 | Band |
|---|---|---|---|
| 39–40 | 9.0 | 23–25 | 6.0 |
| 37–38 | 8.5 | 18–22 | 5.5 |
| 35–36 | 8.0 | 16–17 | 5.0 |
| 32–34 | 7.5 | 13–15 | 4.5 |
| 30–31 | 7.0 | 10–12 | 4.0 |
| 26–29 | 6.5 | 8–9 | 3.5 |

---

## 10. 出题自查速查清单（供项目对照用）

1. 每 Part 恰 10 题、全卷 40 题、4 个 Part 场景与人数符合第 1 节。
2. 每组题目有标准指令句（第 3 节原文措辞），词数限制明确且与答案键一致。
3. 填空答案逐词校验：词数 ≤ 限制（连字符/数字/日期按第 4.1 节计数）、拼写精确（英美式均可）、复数匹配。
4. 顺序校验：填空/单选/简答严格顺序；匹配选项乱序、多选正确项位置与字母无关。
5. 题干与录音同义替换；录音不逐字复述题干。
6. 每个 Part 至少含 1 处修正语/否定/首现陷阱（第 6 节）。
7. 地图题有入口参照、方位词覆盖第 7 节体系、题号=讲解顺序。
8. 多选题两个正确项 + 至少 3 个强干扰项；无部分得分。

---

## 参考来源

**官方（IELTS 三方）**
- IELTS Listening Test Format – British Council: https://takeielts.britishcouncil.org/what-is-ielts/how-it-works/test-format/listening
- IELTS Listening Sample Tasks (PDF) – British Council: https://takeielts.britishcouncil.org/sites/default/files/%5Bdownloads%5D/ielts-listening-sample-tasks-2023.pdf
- IELTS Academic Listening Format – ielts.org: https://ielts.org/take-a-test/test-types/ielts-academic-test/ielts-academic-format-listening
- Tables, Forms and Notes in the IELTS Listening Test – IDP: https://ielts.idp.com/prepare/article-tables-forms-and-notes-in-the-ielts-listening-test
- IELTS Listening Tips for Map, Plan & Diagram Questions – IDP: https://ielts.idp.com/prepare/article-ielts-listening-tips-for-map-plan-diagram-questions
- Strategies for IELTS Listening Part 2 – IDP: https://ielts.idp.com/vietnam/about/news-and-articles/article-ielts-listening-part-2/en-gb
- IELTS Focus – Listening (官方 PDF) – IDP: https://info.ielts.idp.com/rs/561-EIU-022/images/IELTS%20Focus%20-%20Listening%20-%20Student%20Updated.pdf
- IELTS test format – Cambridge English: https://www.cambridgeenglish.org/exams-and-tests/ielts/test-format
- How is IELTS assessed – British Council: https://takeielts.britishcouncil.org/results/how-is-ielts-assessed
- British or American English – British Council: https://takeielts.britishcouncil.org/blog/british-or-american-english-ielts

**权威备考站**
- IELTS Tips: How Words Are Counted – IELTS Liz: https://ieltsliz.com/ielts-tips-how-words-are-counted
- IELTS Spelling: US or UK – IELTS Liz: https://ieltsliz.com/ielts-spelling-us-or-uk
- Listening Multiple Choice Essential Tips – IELTS Liz: https://ieltsliz.com/ielts-listening-multiple-choice-essential-tips
- IELTS Map Listening Practice – IELTS Liz: https://ieltsliz.com/ielts-map-listening-practice/
- IELTS Listening Test Changes Jan 2020 – IELTS Liz: https://ieltsliz.com/ielts-listening-test-changes-2020
- Types of IELTS Listening Questions – IELTS Jacky: https://www.ieltsjacky.com/types-of-ielts-listening-questions.html
- IELTS Listening Map Vocabulary – IELTS Jacky: https://www.ieltsjacky.com/ielts-listening-map-vocabulary.html
- IELTS Listening Sample Test (Map & Plan) – IELTS Jacky: https://www.ieltsjacky.com/ielts-listening-sample-test.html
- IELTS Listening Matching – IELTS Jacky: https://www.ieltsjacky.com/ielts-listening-matching.html
- Word Count Questions – IELTS Material: https://ieltsmaterial.com/ielts-listening/articles/word-count-questions
- Avoid Scoring Zero – IDP/IELTS Material: https://ielts.idp.com/prepare/article-avoid-scoring-zero-ielts-reading-listening
- IELTS Listening Spelling Rules – Parrot Talk: https://www.parrottalk.app/blog/ielts-listening-spelling-rules
- IELTS Listening Question Types – BestMyTest: https://www.bestmytest.com/ielts/listening-question-types
- Listening Test Format & Question Types – IELTS Mentor: https://www.ieltsmentor.ai/guides/ielts-listening-test-format-and-question-types
- IELTS Listening Multiple Choice & Matching – IELTS Mentor: https://www.ieltsmentor.ai/guides/ielts-listening-multiple-choice-and-matching-questions
- Matching in IELTS Listening – IELTS Studio: https://www.ieltsstudio.com/blog/ielts-listening-matching
- Changes to the IELTS Listening Test (Jan 2020) – My IELTS Classroom: https://blog.myieltsclassroom.com/changes-to-the-ielts-listening-test-jan-2020
- Listening Part 3: Signals, Signposts & Distractors – IELTS with Fiona: https://ieltsetc.com/listening-section-3
- Core Listening Strategies: Distractors & Signposting – Past Paper Hero: https://www.pastpaperhero.com/resources/ielts-core-listening-strategies-handling-distractors-and-signposting
- British vs American Spelling – Past Paper Hero: https://www.pastpaperhero.com/resources/ielts-spelling-numbers-and-conventions-british-vs-american-spelling
- Signpost Expressions in IELTS Listening – IELTS Grade: https://grade-online.com/ielts/blog/signpost-expressions-in-ielts-listening
- IELTS Band Score Chart（换算表）: https://www.scribd.com/document/1038573553/IELTS-Band-Score-Chart
- 剑桥真题原文措辞样例（Cambridge IELTS Vol 9 Test 3 等，Studocu 转录）: https://www.studocu.com/row/document/uzbekistan-state-university-of-world-languages/ielts/vol-9-test-3-listening-ielts-practice-questions/168697137

---

**编制备注**：① "word steering" 不是官方/行业标准术语，标准说法是 signposting / cue words / paraphrase steering，第 5 节已按标准术语撰写并加注；② 题型配比无官方公布数字，第 8 节比例来自剑桥真题通行统计的教师社区共识，已如实标注口径；③ ielts.org 页面有反爬（403），其内容经搜索摘要与 BC 页面交叉验证。
