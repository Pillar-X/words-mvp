# 轻量前端规划

本文档规划下一步轻量前端实现。当前目标不是做完整产品，而是把已经跑通的 CLI MVP 包装成一个可点击、可审核、可反复试用的本地 Web 界面。

## 目标

前端第一版只服务当前最小闭环：

1. 选择或上传一个 `.txt` 原始文本。
2. 运行候选生词抽取。
3. 展示候选词、上下文、ECDICT/DeepSeek 选择出的具体义项。
4. 用户对某个具体义项执行操作：加入生词本、标记已知道、暂时忽视。
5. 操作写入 SQLite 的 `user_sense_states` 和 `user_sense_events`。
6. 刷新或重新抽取后，已处理的具体义项不再出现在待处理候选里。

核心原则：用户操作必须绑定 `sense_id`，不能只绑定 lemma。

## 技术选型

建议第一版使用 Python 后端直接提供轻量页面，不引入复杂前端工程。

推荐方案：

- 后端：FastAPI
- 页面：Jinja2 模板 + 原生 HTML/CSS + 少量 JavaScript
- 数据库：继续使用当前 SQLite v2 schema
- 业务逻辑：复用现有 `src/words_mvp/pipeline.py`、`db.py`、`meanings.py`

理由：

- 当前核心逻辑都在 Python 里，FastAPI 可以直接复用。
- 不需要引入 React/Vite/Node 构建链，降低项目复杂度。
- 页面交互简单，服务端渲染足够。
- 后续如果要扩展正式前端，再把 API 层保留下来即可。

## 页面设计

第一版建议只有一个主页面。

### 主页面：阅读生词处理页

页面区域：

1. 顶部工具栏
   - 当前输入文件路径
   - 候选词数量设置
   - 运行抽取按钮
   - DeepSeek 是否启用的状态提示

2. 文件输入区
   - 支持选择 `input_texts/` 下已有 `.txt`
   - 支持上传新的 `.txt` 到 `input_texts/`
   - 上传后自动把该文件作为当前输入

3. 候选词列表
   - 按 `unknown_score` 从高到低展示
   - 每项显示：
     - 原文词形 `word`
     - lemma
     - 中文义项 `meaning_in_context`
     - ECDICT 英文定义 `definition_en`
     - 上下文句子
     - `unknown_score`
     - `frequency`
     - `sense_id`
     - `occurrence_id`
     - 选择方法，例如 DeepSeek 或 fallback

4. 用户操作按钮
   - 加入生词本：写入 `learning`
   - 已经知道：写入 `known`
   - 暂时忽视：写入 `ignored`

5. 状态反馈
   - 操作成功后，该候选项从列表中移除或变灰
   - 页面显示剩余候选数
   - 如果操作失败，展示简短错误信息

页面风格应偏工具型，不做营销页。布局以高密度、可扫描为主。

## 后端接口规划

即使第一版使用服务端模板，也建议保留清晰 API，方便后续前端重构。

### GET `/`

返回主页面。

页面初始数据：

- `input_texts/` 下的 `.txt` 文件列表
- 当前配置中的默认输入文件
- 当前 DeepSeek 配置是否可用

### POST `/upload`

上传 `.txt` 文件到 `input_texts/`。

请求：

- multipart file

处理：

- 校验扩展名必须是 `.txt`
- 文件名做安全清理
- 保存到 `input_texts/`

返回：

- 上传后的文件名
- 可用于抽取的文件路径

### POST `/extract`

运行完整 MVP pipeline。

请求字段：

- `input_path`
- `limit`
- `min_score`
- `persist`

处理：

- 调用 `run_mvp_pipeline`
- 持久化时创建 document、lexeme、word_sense、text_occurrence
- 返回运行时候选词列表

返回候选项字段：

- `word`
- `lemma`
- `frequency`
- `unknown_score`
- `meaning_in_context`
- `definition_en`
- `context`
- `sample_sentence`
- `sense_id`
- `occurrence_id`
- `status`
- `selection_method`
- `confidence`
- `evidence`

### POST `/sense-status`

更新用户对某个具体义项的状态。

请求字段：

- `sense_id`
- `occurrence_id`
- `status`

允许状态：

- `learning`
- `known`
- `ignored`

处理：

- 调用 `update_user_sense_status`
- 写入 `user_sense_states`
- 写入 `user_sense_events`

返回：

- 更新后的状态
- 被更新的 lemma
- 被更新的中文义项

### GET `/database/summary`

可选接口，用于调试和前端显示统计。

返回：

- 文档数
- 词条数
- 义项数
- 文本出现位置数
- 用户已知义项数
- 用户学习中义项数
- 用户忽略义项数

## 数据流

完整前端数据流：

1. 用户打开页面。
2. 后端读取 `input_texts/` 文件列表。
3. 用户选择或上传 `.txt`。
4. 用户点击运行抽取。
5. 后端调用当前 pipeline。
6. pipeline 按 lemma 生成候选词。
7. pipeline 从 ECDICT 取候选义项。
8. pipeline 调用 DeepSeek V4 Flash 选择上下文义项；失败时 fallback。
9. pipeline 写入文档、词条、义项、文本出现位置。
10. 页面展示候选项。
11. 用户点击某个义项的状态按钮。
12. 后端按 `sense_id + occurrence_id` 更新用户义项状态。
13. 前端移除或更新该候选项。

## 文件结构建议

建议新增：

```text
web/
- app.py
- templates/
  - index.html
- static/
  - styles.css
  - app.js
```

其中：

- `web/app.py` 只负责 HTTP 层和调用现有业务模块。
- `templates/index.html` 负责页面结构。
- `static/styles.css` 负责页面样式。
- `static/app.js` 负责上传、抽取、更新状态这些轻量交互。

不建议把业务逻辑写进 `web/`，避免和现有 pipeline 重复。

## 配置变化

`configs/default.yaml` 可以继续作为统一配置。

前端新增配置建议：

```text
web:
- host
- port
- debug
- upload_dir
```

默认：

- host: `127.0.0.1`
- port: `8000`
- upload_dir: `input_texts`

## 依赖变化

如果采用 FastAPI，需要在 `requirements.txt` 增加：

- `fastapi`
- `uvicorn`
- `jinja2`
- `python-multipart`

其中 `python-multipart` 用于处理文件上传。

## 第一版验收标准

前端第一版完成后至少满足：

1. 能在浏览器打开本地页面。
2. 能选择 `input_texts/` 下的 `.txt` 文件。
3. 能上传新的 `.txt` 文件。
4. 能点击按钮运行抽词。
5. 能看到候选词、上下文和具体义项。
6. 每个候选项都有 `sense_id` 和 `occurrence_id`。
7. 能对候选项执行三种操作。
8. 操作后 SQLite 中 `user_sense_states` 和 `user_sense_events` 更新正确。
9. 已标记为 `known`、`ignored`、`learning` 的具体义项不会再次出现在待处理候选列表中。

## 不在第一版做的事

第一版暂不做：

- 用户登录和多用户系统。
- 生词本复习页面。
- 间隔重复算法。
- PDF、网页、Markdown、字幕导入。
- 高级筛选、排序和批量操作。
- 前端路由和复杂状态管理。
- 独立 React/Vue 应用。

这些功能应在最小 Web 闭环稳定后再扩展。

## 风险和注意点

1. DeepSeek 调用可能较慢，前端需要显示 loading 状态。
2. 没有 `DEEPSEEK_API_KEY` 时，页面应明确显示当前使用 fallback。
3. 用户操作必须按 `sense_id` 更新，不能退回到 lemma 级状态。
4. 上传文件名需要清理，避免路径穿越。
5. `input_texts/` 已被 `.gitignore` 忽略，用户上传内容不会进入 Git。
6. SQLite 是本地单用户开发方案，后续如果做多用户，需要重新评估并发和权限。
