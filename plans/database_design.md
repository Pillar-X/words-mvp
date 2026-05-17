# 数据库设计规划：按义项记录用户掌握状态

本文档规划下一版数据库设计。目标不是只记录用户是否掌握某个单词，而是记录用户是否掌握这个单词的某个具体意思。

例如用户可能知道 `charge` 表示“收费”，但不知道它在法律语境中表示“指控”；也可能知道 `progress` 表示“进展”，但不知道 `Progress` 在航天新闻里可能是“进步号货运飞船”。因此数据库不能只以 lemma 作为用户状态的唯一单位。

## 当前设计的问题

当前 MVP 数据库里，`user_words` 使用 `lemma` 作为唯一键，并直接记录 `status`。

这个设计能快速跑通 MVP，但存在几个问题：

- 一个词只有一个全局状态，无法区分不同义项。
- 用户把 `charge` 标记为已知道后，系统会默认用户知道 `charge` 的所有意思。
- 用户把某个熟词僻义加入生词本后，系统无法表达“基础义已掌握，特殊义未掌握”。
- 候选词推荐只能根据 lemma 降权或过滤，无法根据上下文中的具体义项判断。
- 后续做复习、测验、熟词僻义识别时，会缺少稳定的义项级学习记录。

下一版设计要把“词条”和“义项”拆开。

## 设计目标

数据库需要支持以下能力：

1. 同一个 lemma 可以有多个义项。
2. 用户状态必须绑定到具体义项，而不是只绑定到 lemma。
3. 同一个词在不同上下文中可以识别为不同义项。
4. 用户可以对某个义项执行三种操作：加入生词本、标记为已知道、暂时忽视。
5. 下次抽词时，应根据“当前上下文预测出的义项”读取用户状态。
6. 仍然保留原文句子和上下文，方便后续解释、复习和追溯。
7. 支持未来接入更完整词典或 AI 义项消歧，而不破坏用户历史数据。

## 核心概念

### 词条 Lexeme

词条表示一个标准化后的词，例如 `charge`、`progress`、`station`。

词条不是用户掌握状态的最终单位，只是义项的归属对象。

建议字段：

| 字段 | 说明 |
| --- | --- |
| id | 内部主键 |
| lemma | 标准词形，例如 `charge` |
| language | 语言，当前为 `en` |
| pos | 词性，可为空 |
| frequency_rank | 词条常见程度排序，数字越小越常见 |
| frequency_score | 词条频率分，可为空 |
| frequency_source | 频率来源，例如 NGSL、wordfreq、COCA |
| created_at | 创建时间 |

唯一约束建议使用 `language + lemma + pos`。如果 MVP 阶段词性不稳定，也可以先使用 `language + lemma`，但要保留 `pos` 字段。

`frequency_rank` 属于词条层信息，用来表达这个词本身在通用语料或学习词表中的常见程度。例如 `make` 的词条常见程度应该高于 `purification`。这和义项层的 `sense_rank` 不同：前者比较的是词与词之间的常见程度，后者比较的是同一个词内部不同意思的常见程度。

### 义项 Word Sense

义项表示词条的一个具体意思。

用户掌握状态应当绑定到这一层。

建议字段：

| 字段 | 说明 |
| --- | --- |
| id | 内部主键 |
| lexeme_id | 所属词条 |
| sense_key | 稳定义项键 |
| meaning_zh | 中文释义，例如“指控，控告” |
| definition_en | 英文释义，可为空 |
| pos | 该义项词性，可为空 |
| source | 义项来源，例如 seed_dictionary、external_dictionary、ai_provisional |
| source_sense_id | 外部词典义项 ID，可为空 |
| sense_rank | 常见程度排序，数字越小越常见 |
| created_at | 创建时间 |
| updated_at | 更新时间 |

`sense_key` 很重要。它需要尽量稳定，不能每次 AI 生成不同文本就创建一个新义项。

MVP 阶段可以用以下方式生成：

- 如果来自正式词典，优先使用外部词典的 sense id。
- 如果来自本地 seed 词典，可以使用 `lemma + pos + normalized_meaning_zh` 生成稳定 key。
- 如果来自 AI 临时判断，可以先标记为 `ai_provisional`，后续再归并到正式义项。

### 文档 Document

文档保存用户输入的文本来源。

建议字段：

| 字段 | 说明 |
| --- | --- |
| id | 内部主键 |
| filename | 文件名 |
| content | 清洗后的全文 |
| created_at | 创建时间 |

### 文本出现位置 Text Occurrence

文本出现位置表示某个词在某篇文档中的一次出现。

它用于追踪“这个词在这句话里出现过”，但不直接表示用户掌握状态。

建议字段：

| 字段 | 说明 |
| --- | --- |
| id | 内部主键 |
| document_id | 所属文档 |
| surface | 原文形态，例如 `charged` |
| normalized | 标准化原词 |
| lemma | 词形还原结果 |
| lexeme_id | 对应词条，可为空 |
| sentence_index | 所在句子序号 |
| sentence | 原文句子 |
| context | 前后文 |
| start_offset | 文档内起始位置 |
| end_offset | 文档内结束位置 |
| created_at | 创建时间 |

### 运行时候选词 Runtime Candidate

候选词是一次文本处理过程中的运行时结果，当前阶段不需要作为独立表持久化到数据库。

系统仍然需要在内存或接口返回结果中表达候选词信息，例如推荐分数、频次、上下文和预测义项。但这些信息不必长期保存成一张 `word_candidates` 表。

如果用户对某个候选词执行操作，数据库只需要保存：

- 这个词在原文中的出现位置，即 `text_occurrences`；
- 这个上下文预测出的具体义项，即 `word_senses`；
- 用户对该义项的状态，即 `user_sense_states`；
- 可选的操作日志，即 `user_sense_events`。

运行时候选词建议包含的信息：

| 字段 | 说明 |
| --- | --- |
| occurrence_id | 对应文本出现位置 |
| lexeme_id | 对应词条 |
| predicted_sense_id | 当前上下文预测出的义项 |
| unknown_score | 生词推荐分数 |
| difficulty_score | 难度分 |
| frequency | 文本中出现频次 |
| sense_confidence | 义项判断置信度 |
| fallback_used | 是否使用常见释义回退 |

这些字段可以作为 API 响应、CLI 输出或前端展示数据存在，但不进入长期数据库表。

### 用户义项状态 User Sense State

这是新设计的核心表。它记录用户对某个具体义项的掌握状态。

建议字段：

| 字段 | 说明 |
| --- | --- |
| id | 内部主键 |
| user_id | 用户 ID，单用户 MVP 可先固定为 `default` 或 `1` |
| sense_id | 具体义项 ID |
| status | 用户对该义项的状态 |
| mastery_level | 掌握程度，建议 0 到 5 |
| source_document_id | 最近一次来源文档 |
| source_occurrence_id | 最近一次来源上下文 |
| last_seen_at | 最近一次看到该义项 |
| last_action_at | 最近一次用户操作时间 |
| created_at | 创建时间 |
| updated_at | 更新时间 |

唯一约束应为 `user_id + sense_id`。

推荐的 `status`：

| 状态 | 含义 |
| --- | --- |
| new | 系统识别到，但用户还没有明确处理 |
| learning | 用户加入生词本，正在学习 |
| known | 用户明确表示已经掌握该义项 |
| ignored | 用户暂时忽视该义项 |
| archived | 用户不再学习但保留历史 |

`mastery_level` 用于后续复习系统。MVP 阶段可以先简单设置：

- `known` 对应 5
- `learning` 对应 1 或 2
- `ignored` 不代表掌握，建议保持 0 或单独不参与复习
- `new` 默认为 0

### 用户操作日志 User Sense Event

用户操作日志用于记录状态变化历史。它不是必需的最小表，但强烈建议保留，因为后续做复习算法、学习统计和错误分析会用到。

建议字段：

| 字段 | 说明 |
| --- | --- |
| id | 内部主键 |
| user_id | 用户 ID |
| sense_id | 具体义项 ID |
| event_type | 操作类型 |
| from_status | 操作前状态 |
| to_status | 操作后状态 |
| document_id | 来源文档 |
| occurrence_id | 来源上下文 |
| created_at | 操作时间 |

推荐的 `event_type`：

- add_to_book
- mark_known
- ignore_once
- review_correct
- review_wrong
- reset_status

## 推荐表关系

整体关系应是：

- 一个 `lexeme` 可以有多个 `word_senses`。
- 一个 `document` 可以有多个 `text_occurrences`。
- 一个 `text_occurrence` 对应一个词在文档中的一次出现。
- 运行时候选词来源于一个 `text_occurrence`，并指向一个预测出的 `word_sense`，但不作为独立表持久化。
- 一个 `user_sense_state` 记录用户对某个 `word_sense` 的长期状态。
- 一个 `user_sense_event` 记录用户对某个 `word_sense` 的状态变化历史。

关键原则是：用户状态绑定 `sense_id`，不是绑定 `lemma`。

## 候选词推荐如何读取用户状态

抽取候选词时，流程应调整为：

1. 预处理文本，得到 token 和 lemma。
2. 根据 lemma 找到或创建 `lexeme`。
3. 根据上下文判断候选词最可能对应哪个 `word_sense`。
4. 用 `user_id + predicted_sense_id` 查询用户状态。
5. 如果该义项是 `known`，则降低优先级或过滤。
6. 如果该义项是 `ignored`，则在当前策略下过滤或短期降权。
7. 如果该义项是 `learning`，通常不再作为“待处理生词”展示，但可以进入复习队列。
8. 如果同一个 lemma 的另一个义项没有掌握，仍然可以推荐。

这能解决一个关键问题：用户知道 `station` 表示“车站”，但如果文本中是 “space station”，系统仍可以把“空间站”这个义项作为单独状态判断。

## 页面或命令行操作应绑定什么 ID

用户点击“加入生词本 / 已知道 / 忽视”时，不应该只提交 lemma。

正确做法是提交：

- occurrence_id，代表用户当前看到的原文出现位置；
- sense_id，代表用户当前操作的具体义项；
- 同时保留 occurrence_id，方便追溯这个判断来自哪句话。

MVP 里更推荐提交 `occurrence_id + sense_id`。后端直接更新 `user_sense_states`，并可在 `user_sense_events` 中记录这次操作来自哪个上下文。

这样可以避免用户操作 `charge` 时，系统不知道用户到底操作的是“收费”还是“指控”。

## 与当前数据库的迁移思路

当前数据库可以按以下步骤迁移：

1. 新建 `lexemes` 表，把现有 `word_candidates.lemma` 去重后写入，并补充词条常见程度排序。
2. 新建 `word_senses` 表，把现有 `meaning_in_context` 作为临时义项写入。
3. 新建 `text_occurrences` 表，把旧候选记录里的句子、上下文和原词形态迁移为文本出现位置。
4. 新建 `user_sense_states` 表。
5. 将旧 `user_words` 中的状态迁移到义项层。
6. 如果旧记录只有 lemma 没有明确义项，只能迁移到该词最常见义项，或标记为 `legacy_unspecified` 待用户后续确认。
7. 迁移完成后，不再需要长期保留 `word_candidates` 表。候选词应在每次处理文本时重新计算。

迁移时要注意：旧数据无法百分百还原用户到底掌握的是哪个义项。因此旧 `user_words` 不应该被视为强语义事实，最多作为弱信号。

## MVP 阶段建议采用的最小版本

为了不过度设计，下一步代码实现可以先采用以下最小表集合：

1. `documents`
2. `lexemes`
3. `word_senses`
4. `text_occurrences`
5. `user_sense_states`

`user_sense_events` 可以同步建立，但如果想保持实现更轻，也可以在第二步加入。

最小可用标准是：

- 运行时候选词必须有 `predicted_sense_id`。
- 用户状态必须写入 `user_sense_states`。
- 同一个 lemma 的不同 sense 可以拥有不同状态。
- 后续推荐必须按 `predicted_sense_id` 判断，而不是按 lemma 判断。
- 数据库不持久化候选词表，候选词列表由当前文档、词表、词频、上下文义项和用户义项状态动态计算。

## 示例场景

假设文本中出现两个 `charge`：

- `charge customers a fee`，义项是“收费”。
- `face a criminal charge`，义项是“指控，控告”。

数据库中应有：

- 一个 lexeme：`charge`
- 至少两个 word senses：`收费`、`指控`
- 两条 text occurrences，分别对应两个上下文
- 运行时生成两个候选项，分别指向不同的 `predicted_sense_id`
- 用户可以把“收费”标记为已知道，同时把“指控”加入生词本

下次推荐时，如果上下文中再次出现 `charge` 的“收费”义项，系统可以不推荐；如果出现“指控”义项，系统仍应推荐或进入复习。

## 结论

下一版数据库设计必须把用户状态从 `lemma` 层下移到 `sense` 层。

可以保留词条表用于归类和检索，但任何表达用户是否掌握、是否加入生词本、是否忽略的状态，都应该以 `user_id + sense_id` 为唯一判断单位。

这会让后续熟词僻义、上下文释义、个性化推荐和复习系统都有正确的数据基础。
