# RUNBOOK

当前 MVP 阶段核心运行步骤。

## 1. 进入项目环境

```bash
conda activate words-mvp
```

也可以不激活环境，直接用 `conda run` 执行后续命令。

## 2. 安装依赖

```bash
conda run -n words-mvp python -m pip install -r requirements.txt
```

安装 spaCy 英文模型：

```bash
conda run -n words-mvp python -m spacy download en_core_web_sm
```

## 3. 运行 MVP 闭环

待抽词的原始 `.txt` 文件放在 `input_texts/` 目录，并在 `configs/default.yaml` 里设置 `input_path`。

如需启用 DeepSeek V4 Flash 进行上下文义项选择，先设置 `DEEPSEEK_API_KEY`。

```bash
python scripts/run_mvp.py --config configs/default.yaml
```



## 4. 更新单词状态

从 `run_mvp.py` 输出中复制对应的 `sense_id` 和 `occurrence_id`。

```bash
python scripts/update_word_status.py 1 learning --occurrence-id 1
python scripts/update_word_status.py 2 known --occurrence-id 2
python scripts/update_word_status.py 3 ignored --occurrence-id 3
```

## 5. 单独运行预处理

```bash
python scripts/preprocess_text.py --config configs/default.yaml
```

## 6. 单独抽取候选生词

```bash
python scripts/extract_candidates.py --config configs/default.yaml
```

## 7. 常用参数

输出完整 JSON：

```bash
python scripts/run_mvp.py --config configs/default.yaml --json
```

限制候选词数量：

```bash
python scripts/run_mvp.py --config configs/default.yaml --limit 25
```

保存 JSON 结果：

```bash
python scripts/run_mvp.py --config configs/default.yaml --json > mvp_result.json
```

不写入 SQLite：

```bash
python scripts/run_mvp.py --config configs/default.yaml --no-persist
```
