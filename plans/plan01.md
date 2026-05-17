# MVP计划
当前文档用于制定计划。

# 目标：
先完成最小闭环：
1.用户传入一段文本（.txt），从中抽取出用户可能不会的单词
2.给出单词在这段文本中的释义，如果上下文判断不了准确的含义，就给出最常见的释义
3.用户可以选择：把这个词放进生词本 / 标记为已经知道 / 这次暂时忽视这个词

# 实现方法

## 1. 文本导入与预处理

用户上传 `.txt` 文件后，系统先读取纯文本内容，并做基础清洗：

- 统一编码为 UTF-8。
- 去掉多余空行、重复空格、不可见字符。
- 保留原始段落和句子边界，方便后面给单词提供上下文。
- 使用英文分词工具把文本拆成 token，例如单词、标点、数字。
- 对单词做标准化处理：统一小写，去掉前后标点，并做词形还原，例如 `studies` 还原为 `study`，`went` 还原为 `go`。

推荐方法：

- MVP 阶段可以使用 Python 后端实现。
- 分词和词形还原可以用 `spaCy` 或 `nltk`。
- 如果前端先做原型，也可以用 JavaScript 做简单正则分词，但正式版本建议后端处理，准确性更高。

## 2. 抽取用户可能不会的单词

“用户可能不会”不能只靠单词是否出现。建议第一版使用规则评分，后续再用用户学习数据优化。

候选词过滤规则：

- 去掉停用词，例如 `the`、`a`、`is`、`and`、`of`。
- 去掉数字、网址、邮箱、人名中明显不需要背的部分。
- 去掉过短词，例如 1-2 个字母的词，除非它在目标词库中。
- 合并同一词的不同词形，例如 `learn`、`learned`、`learning` 只算一个词。
- 统计词频：同一个词在文本中出现越多，越值得优先处理。
- 结合基础词表：如果是非常基础的高频词，可以默认不推荐，除非它在上下文中出现熟词僻义。
- 结合考试/目标词库：如果词在 CET4/CET6/考研/雅思等词库中，提升优先级。

可以给每个词计算一个 `unknown_score`：

```text
unknown_score = 词汇难度分 + 目标词库加权 + 文本出现频次加权 - 基础高频词扣分 - 用户已知词扣分
```

第一版不需要追求完美，只要能把明显值得学的词排在前面即可。

需要维护三类用户词表：

- `known_words`：用户已经知道的词，以后默认不再推荐。
- `vocabulary_book`：用户加入生词本的词。
- `ignored_words`：用户本次暂时忽视的词，只在当前文本或短期内不再提示。

## 3. 判断单词在上下文中的释义

每个候选词都要绑定它在原文中的句子或相邻句子，然后根据上下文判断含义。

推荐流程：

1. 找到目标词出现的句子。
2. 如果句子太短或上下文不足，额外取前一句和后一句。
3. 把目标词、原句、上下文和候选释义交给 AI 或词义消歧模块。
4. 如果 AI 能明确判断上下文义项，就返回“上下文释义”。
5. 如果判断不明确，就返回该词最常见释义，并标记为“上下文不足”。

MVP 阶段可以直接使用大模型完成释义判断，但要限制输出格式。例如要求返回 JSON：

```json
{
  "word": "charge",
  "base_form": "charge",
  "meaning_in_context": "指控，控告",
  "common_meaning": "收费；指控；充电",
  "confidence": 0.86,
  "evidence": "句子中出现了 court 和 crime，说明这里更接近法律语境。",
  "fallback_used": false
}
```

为了降低 AI 幻觉，建议结合词典数据：

- 先从本地词典或开源词库拿到常见释义。
- 再让 AI 只在这些候选释义中选择最符合上下文的一项。
- 如果 AI 判断不出，就返回词典中的最高频释义。

## 4. 用户选择与状态更新

对每个候选词展示三种操作：

- 加入生词本。
- 标记为已经知道。
- 本次暂时忽视。

三种操作对应不同数据更新：

| 用户操作 | 数据变化 | 后续行为 |
| --- | --- | --- |
| 加入生词本 | 写入 `vocabulary_book` | 后续进入复习、例句、测验 |
| 已经知道 | 写入 `known_words` | 后续抽词时降低推荐优先级或直接过滤 |
| 暂时忽视 | 写入当前文本的 `ignored_words` | 当前文本不再展示，未来可再次出现 |

建议记录的不只是单词本身，还要记录上下文：

- 原始单词形态，例如 `charged`。
- 词形还原，例如 `charge`。
- 原文句子。
- 本文中的释义。
- 用户操作。
- 操作时间。
- 来源文件。

这样后续可以继续扩展到复习、阅读回顾和 AI 造题。

## 5. 建议的数据结构

可以先用 SQLite 做 MVP，不需要一开始上复杂数据库。

核心表：

```text
documents
- id
- filename
- content
- created_at

lexemes
- id
- lemma
- language
- pos
- frequency_rank
- frequency_score
- frequency_source
- created_at

word_senses
- id
- lexeme_id
- sense_key
- meaning_zh
- definition_en
- pos
- source
- source_sense_id
- sense_rank
- created_at
- updated_at

text_occurrences
- id
- document_id
- surface
- normalized
- lemma
- lexeme_id
- sentence_index
- sentence
- context
- start_offset
- end_offset
- created_at

user_sense_states
- id
- user_id
- sense_id
- status
- mastery_level
- source_document_id
- source_occurrence_id
- last_seen_at
- last_action_at
- created_at
- updated_at

user_sense_events
- id
- user_id
- sense_id
- event_type
- from_status
- to_status
- document_id
- occurrence_id
- created_at
```

其中 `user_sense_states.status` 可以是：

```text
new
learning
known
ignored
archived
```

注意：候选词列表不需要作为独立数据库表长期保存。候选词是运行时结果，由当前文档、词频、词表、上下文义项和用户义项状态动态计算。用户掌握状态必须绑定到具体 `sense_id`，不能只绑定到 lemma。

## 6. MVP 技术路线

推荐第一版采用：

- 前端：上传 `.txt`、展示候选词列表、展示释义和上下文、提供三个操作按钮。
- 后端：处理文本、抽词、调用 AI 生成释义、保存用户选择。
- 数据库：SQLite。
- AI：使用 DeepSeek V4 Flash 从 ECDICT 候选义项中选择上下文最合适的词义。
- 本地词库：ECDICT 用于候选释义，基础词表和目标词库用于过滤、加权和难度分级。

处理流程：

```text
上传 txt
-> 保存 document
-> 清洗文本
-> 分句和分词
-> 词形还原
-> 过滤停用词和基础词
-> 根据词频、难度、用户义项状态计算候选分
-> 取 Top N 候选词
-> 为每个词提取上下文
-> 从 ECDICT 读取候选义项
-> 调用 DeepSeek V4 Flash 在候选义项中选择上下文词义
-> 展示给用户
-> 用户选择加入生词本 / 已知道 / 忽视
-> 更新 user_sense_states 和 user_sense_events
```

## 7. 第一版验收标准

完成后至少要满足：

- 用户可以上传一个 `.txt` 文件。
- 系统能返回一组候选生词，而不是把所有单词都列出来。
- 每个候选词都有原文句子和中文释义。
- 对上下文无法判断的词，系统能回退到常见释义。
- 用户可以对每个词执行三种操作。
- 用户选择会被保存，下次处理文本时能影响推荐结果。

## 8. 后续可扩展方向

在最小闭环稳定后，再加入：

- 生词本复习。
- 间隔重复算法。
- AI 根据生词生成填空题、选择题、阅读题。
- 熟词僻义识别。
- 用户词汇水平诊断。
- 浏览器插件，从网页或论文中直接抽词。
- 支持 PDF、网页、Markdown、字幕文件等更多文本来源。
