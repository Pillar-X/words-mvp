"""ECDICT-backed context meaning selection."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
import csv
import hashlib
import json
import os
import re
import urllib.error
import urllib.request

from words_mvp.config import PROJECT_ROOT
from words_mvp.preprocess import PreprocessedDocument
from words_mvp.vocabulary import WordCandidate


DEFAULT_ECDICT_PATH = PROJECT_ROOT / "data" / "dictionaries" / "ecdict_sample.csv"
NLTK_DATA_DIR = PROJECT_ROOT / "data" / "nltk_data"
WORD_RE = re.compile(r"[a-z]+")
POS_RE = re.compile(r"^([a-zA-Z][a-zA-Z. /-]*?)\s*[.:：]\s*(.+)$")


@dataclass(frozen=True)
class DictionarySense:
    sense_key: str
    meaning_zh: str
    definition_en: str
    pos: str
    source: str
    source_sense_id: str
    sense_rank: int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class LexemeDictionaryEntry:
    lemma: str
    phonetic: str
    pos: str
    exchange: str
    frequency_rank: int | None
    frequency_score: float | None
    frequency_source: str
    senses: list[DictionarySense]


@dataclass(frozen=True)
class DeepSeekConfig:
    enabled: bool = True
    model: str = "deepseek-v4-flash"
    base_url: str = "https://api.deepseek.com"
    api_key_env: str = "DEEPSEEK_API_KEY"
    timeout_seconds: int = 30
    max_tokens: int = 400


@dataclass(frozen=True)
class MeaningResult:
    word: str
    base_form: str
    meaning_in_context: str
    common_meaning: str
    confidence: float
    evidence: str
    fallback_used: bool
    context: str
    sense_key: str
    definition_en: str
    pos: str
    source: str
    source_sense_id: str
    sense_rank: int
    selection_method: str

    def to_dict(self) -> dict:
        return asdict(self)


def load_meaning_dictionary(path: str | Path | None = None) -> dict[str, LexemeDictionaryEntry]:
    """Load ECDICT CSV data into an in-memory dictionary."""
    dictionary_path = Path(path) if path else DEFAULT_ECDICT_PATH
    if not dictionary_path.is_absolute():
        dictionary_path = PROJECT_ROOT / dictionary_path
    if not dictionary_path.exists():
        return {}
    if dictionary_path.suffix.lower() != ".csv":
        raise ValueError(f"ECDICT CSV is required for meaning lookup: {dictionary_path}")
    return _load_meaning_dictionary_cached(str(dictionary_path))


@lru_cache(maxsize=4)
def _load_meaning_dictionary_cached(dictionary_path: str) -> dict[str, LexemeDictionaryEntry]:
    entries: dict[str, LexemeDictionaryEntry] = {}
    with Path(dictionary_path).open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        for row in reader:
            lemma = str(row.get("word", "")).strip().lower()
            if not lemma:
                continue
            senses = _parse_ecdict_senses(row)
            entries[lemma] = LexemeDictionaryEntry(
                lemma=lemma,
                phonetic=str(row.get("phonetic", "") or ""),
                pos=str(row.get("pos", "") or ""),
                exchange=str(row.get("exchange", "") or ""),
                frequency_rank=_ecdict_frequency_rank(row),
                frequency_score=_float_or_none(row.get("collins")),
                frequency_source=_ecdict_frequency_source(row),
                senses=senses,
            )
    return entries


def deepseek_config_from_mapping(config: dict | None) -> DeepSeekConfig:
    config = config or {}
    return DeepSeekConfig(
        enabled=bool(config.get("enabled", True)),
        model=str(config.get("model", "deepseek-v4-flash")),
        base_url=str(config.get("base_url", "https://api.deepseek.com")),
        api_key_env=str(config.get("api_key_env", "DEEPSEEK_API_KEY")),
        timeout_seconds=int(config.get("timeout_seconds", 30)),
        max_tokens=int(config.get("max_tokens", 400)),
    )


def resolve_candidate_meaning(
    candidate: WordCandidate,
    document: PreprocessedDocument,
    dictionary: dict[str, LexemeDictionaryEntry],
    deepseek_config: DeepSeekConfig | None = None,
) -> MeaningResult:
    """Resolve a candidate's meaning by selecting from ECDICT senses."""
    context = get_candidate_context(document, candidate)
    surface = candidate.word.strip().lower()
    entry = dictionary.get(surface) or dictionary.get(candidate.lemma)
    if entry and entry.senses:
        selected_sense, confidence, evidence, method = _select_sense(
            candidate=candidate,
            context=context,
            senses=entry.senses,
            deepseek_config=deepseek_config or DeepSeekConfig(enabled=False),
        )
        return MeaningResult(
            word=candidate.word,
            base_form=candidate.lemma,
            meaning_in_context=selected_sense.meaning_zh,
            common_meaning=entry.senses[0].meaning_zh,
            confidence=confidence,
            evidence=evidence,
            fallback_used=method != "deepseek",
            context=context,
            sense_key=selected_sense.sense_key,
            definition_en=selected_sense.definition_en,
            pos=selected_sense.pos,
            source=selected_sense.source,
            source_sense_id=selected_sense.source_sense_id,
            sense_rank=selected_sense.sense_rank,
            selection_method=method,
        )

    unknown = _unknown_sense(candidate.lemma)
    return MeaningResult(
        word=candidate.word,
        base_form=candidate.lemma,
        meaning_in_context="ECDICT 未覆盖该词，需补充词典数据",
        common_meaning="ECDICT 未覆盖该词，需补充词典数据",
        confidence=0.1,
        evidence="当前配置的 ECDICT 文件中未找到该词。",
        fallback_used=True,
        context=context,
        sense_key=unknown.sense_key,
        definition_en=unknown.definition_en,
        pos=unknown.pos,
        source=unknown.source,
        source_sense_id=unknown.source_sense_id,
        sense_rank=unknown.sense_rank,
        selection_method="missing_ecdict_entry",
    )


def build_related_forms(
    dictionary: dict[str, LexemeDictionaryEntry],
    *,
    lemma: str,
    surface: str,
    selected_sense_key: str,
    limit: int = 16,
) -> list[dict]:
    """Build display-ready ECDICT entries related to a lemma or surface form."""
    normalized_lemma = lemma.strip().lower()
    normalized_surface = surface.strip().lower()
    candidate_words = _related_form_candidates(dictionary, normalized_lemma, normalized_surface, limit=limit)
    forms = []
    for word in candidate_words:
        entry = dictionary.get(word)
        if entry is None:
            continue
        forms.append(
            {
                "word": entry.lemma,
                "phonetic": entry.phonetic,
                "pos": entry.pos,
                "frequency_rank": entry.frequency_rank,
                "meanings": [
                    {
                        "text": sense.meaning_zh,
                        "pos": sense.pos,
                        "definition_en": sense.definition_en,
                        "selected": sense.sense_key == selected_sense_key,
                    }
                    for sense in entry.senses
                ],
            }
        )
    return forms


def get_candidate_context(document: PreprocessedDocument, candidate: WordCandidate) -> str:
    if not candidate.sentence_indices:
        return candidate.sample_sentence
    center = candidate.sentence_indices[0]
    indices = [index for index in range(center - 1, center + 2) if 0 <= index < len(document.sentences)]
    return " ".join(document.sentences[index].text for index in indices)


def _parse_ecdict_senses(row: dict) -> list[DictionarySense]:
    word = str(row.get("word", "")).strip().lower()
    row_pos = str(row.get("pos", "") or "")
    translations = _split_lines(row.get("translation"))
    definitions = _split_lines(row.get("definition"))
    senses: list[DictionarySense] = []
    source_lines = translations or definitions or [""]

    for line_index, raw_translation in enumerate(source_lines):
        definition = definitions[line_index] if line_index < len(definitions) else ""
        pos, meaning_text = _parse_translation_line(raw_translation, row_pos)
        for meaning in _split_translation_meanings(meaning_text or raw_translation or definition or "暂无中文释义"):
            sense_rank = len(senses) + 1
            sense_key = _sense_key(word, pos, meaning, sense_rank)
            senses.append(
                DictionarySense(
                    sense_key=sense_key,
                    meaning_zh=meaning,
                    definition_en=definition,
                    pos=pos,
                    source="ecdict",
                    source_sense_id=f"ecdict:{word}:{sense_rank}",
                    sense_rank=sense_rank,
                )
            )
    return senses


def _split_lines(value: object) -> list[str]:
    if not isinstance(value, str):
        return []
    return [line.strip() for line in value.replace("\\n", "\n").splitlines() if line.strip()]


def _parse_translation_line(value: str, fallback_pos: str) -> tuple[str, str]:
    match = POS_RE.match(value.strip())
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return fallback_pos, value.strip()


def _split_translation_meanings(value: str) -> list[str]:
    parts = [part.strip() for part in re.split(r"[;；]", value) if part.strip()]
    return parts or [value.strip()]


def _related_form_candidates(
    dictionary: dict[str, LexemeDictionaryEntry],
    lemma: str,
    surface: str,
    *,
    limit: int,
) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()

    def add(word: str) -> None:
        normalized = word.strip().lower()
        if not normalized or normalized in seen or normalized not in dictionary:
            return
        seen.add(normalized)
        ordered.append(normalized)

    add(lemma)
    add(surface)

    query_words = _dedupe_words([lemma, surface])
    _add_exchange_forms(dictionary, ordered, add, query_words=query_words)

    for word in _dedupe_words(query_words + ordered):
        for related in _wordnet_related_words(word):
            add(related)
        for related in _heuristic_derivation_candidates(word):
            add(related)
    _add_exchange_forms(dictionary, ordered, add, query_words=query_words)

    stems = _derivation_stems(lemma)
    scored: list[tuple[int, int, str]] = []
    for word in dictionary:
        if word in seen:
            continue
        score = _related_word_score(word, lemma=lemma, surface=surface, stems=stems)
        if score <= 0:
            continue
        frequency_rank = dictionary[word].frequency_rank or 9999999
        scored.append((-score, frequency_rank, word))

    for _, _, word in sorted(scored)[: max(0, limit - len(ordered))]:
        add(word)

    return ordered[:limit]


def _add_exchange_forms(
    dictionary: dict[str, LexemeDictionaryEntry],
    ordered: list[str],
    add,
    *,
    query_words: list[str],
) -> None:
    processed: set[str] = set()
    while True:
        added_count = len(ordered)
        for word in list(ordered):
            if word in processed:
                continue
            processed.add(word)
            entry = dictionary.get(word)
            if entry is None:
                continue
            query_words.append(word)
            for exchanged in _parse_exchange_words(entry.exchange):
                add(exchanged)
        if len(ordered) == added_count:
            return


def _dedupe_words(words: list[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for word in words:
        normalized = word.strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def _parse_exchange_words(value: str) -> list[str]:
    words: list[str] = []
    for part in re.split(r"[/,;\s]+", value):
        if ":" not in part:
            continue
        _, raw_words = part.split(":", 1)
        for word in raw_words.split(","):
            normalized = word.strip().lower()
            if WORD_RE.fullmatch(normalized):
                words.append(normalized)
    return words


@lru_cache(maxsize=4096)
def _wordnet_related_words(word: str) -> tuple[str, ...]:
    normalized = word.strip().lower()
    if not WORD_RE.fullmatch(normalized):
        return ()

    try:
        import nltk.data
        from nltk.corpus import wordnet as wn
    except ImportError:
        return ()

    nltk_data_dir = str(NLTK_DATA_DIR)
    if nltk_data_dir not in nltk.data.path:
        nltk.data.path.insert(0, nltk_data_dir)

    related: set[str] = set()
    try:
        seeds = {normalized}
        for pos in (wn.NOUN, wn.VERB, wn.ADJ, wn.ADV):
            morphy = wn.morphy(normalized, pos)
            if morphy:
                seeds.add(morphy.lower())

        for seed in seeds:
            lemmas = []
            for pos in (wn.NOUN, wn.VERB, wn.ADJ, wn.ADV):
                lemmas.extend(wn.lemmas(seed, pos=pos))
            for synset in wn.synsets(seed):
                lemmas.extend(synset.lemmas())

            for lemma in lemmas:
                _add_wordnet_name(related, lemma.name())
                for derived in lemma.derivationally_related_forms():
                    _add_wordnet_name(related, derived.name())
    except (LookupError, OSError):
        return ()

    related.discard(normalized)
    return tuple(sorted(related))


def _add_wordnet_name(words: set[str], name: str) -> None:
    normalized = name.replace("_", " ").strip().lower()
    if " " in normalized:
        return
    if WORD_RE.fullmatch(normalized):
        words.add(normalized)


def _heuristic_derivation_candidates(word: str) -> list[str]:
    candidates: list[str] = []
    if word.endswith("ification") and len(word) > len("ification"):
        candidates.append(f"{word[: -len('ification')]}ify")
    if word.endswith("ication") and len(word) > len("ication"):
        candidates.append(f"{word[: -len('ication')]}icate")
    return candidates


def _derivation_stems(lemma: str) -> set[str]:
    stems = {lemma}
    if len(lemma) > 4 and lemma.endswith("e"):
        stems.add(lemma[:-1])
    if len(lemma) > 5 and lemma.endswith("al"):
        stems.add(lemma[:-2])
    if len(lemma) > 5 and lemma.endswith("y"):
        stems.add(f"{lemma[:-1]}i")
    return {stem for stem in stems if len(stem) >= 4}


def _related_word_score(word: str, *, lemma: str, surface: str, stems: set[str]) -> int:
    if word == lemma or word == surface:
        return 100
    suffixes = (
        "s",
        "es",
        "ed",
        "ing",
        "er",
        "ers",
        "ion",
        "tion",
        "ation",
        "ment",
        "ness",
        "ity",
        "al",
        "ial",
        "able",
        "ible",
        "ive",
        "ly",
        "ally",
    )
    for stem in stems:
        if not word.startswith(stem):
            continue
        tail = word[len(stem) :]
        if tail in suffixes:
            return 80 - abs(len(word) - len(lemma))
        if 0 < len(tail) <= 8 and any(tail.endswith(suffix) for suffix in suffixes):
            return 55 - abs(len(word) - len(lemma))
    return 0


def _sense_key(word: str, pos: str, meaning: str, rank: int) -> str:
    normalized = "|".join([word.lower(), pos.lower(), meaning.strip().lower(), str(rank)])
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:12]
    return f"ecdict:{word}:{digest}"


def _ecdict_frequency_rank(row: dict) -> int | None:
    for field in ("frq", "bnc"):
        value = _int_or_none(row.get(field))
        if value is not None and value > 0:
            return value
    return None


def _ecdict_frequency_source(row: dict) -> str:
    if _int_or_none(row.get("frq")):
        return "ecdict.frq"
    if _int_or_none(row.get("bnc")):
        return "ecdict.bnc"
    return "ecdict"


def _select_sense(
    *,
    candidate: WordCandidate,
    context: str,
    senses: list[DictionarySense],
    deepseek_config: DeepSeekConfig,
) -> tuple[DictionarySense, float, str, str]:
    if len(senses) == 1:
        return senses[0], 0.72, "ECDICT 只有一个候选义项，直接使用该义项。", "single_ecdict_sense"

    if deepseek_config.enabled:
        selected = _select_with_deepseek(candidate, context, senses, deepseek_config)
        if selected is not None:
            sense, confidence, evidence = selected
            return sense, confidence, evidence, "deepseek"

    sense = _select_by_keyword_overlap(context, senses)
    return sense, 0.55, "未使用 DeepSeek 或调用失败，回退到 ECDICT 义项关键词重叠选择。", "local_fallback"


def _select_with_deepseek(
    candidate: WordCandidate,
    context: str,
    senses: list[DictionarySense],
    config: DeepSeekConfig,
) -> tuple[DictionarySense, float, str] | None:
    api_key = os.environ.get(config.api_key_env)
    if not api_key:
        return None

    sense_payload = [
        {
            "index": index,
            "sense_key": sense.sense_key,
            "meaning_zh": sense.meaning_zh,
            "definition_en": sense.definition_en,
            "pos": sense.pos,
        }
        for index, sense in enumerate(senses)
    ]
    prompt = {
        "word": candidate.lemma,
        "surface": candidate.word,
        "context": context,
        "senses": sense_payload,
        "instruction": "只从 senses 中选择最符合 context 的一个义项，返回 JSON：{\"index\": 数字, \"confidence\": 0到1, \"evidence\": \"中文简短理由\"}。",
    }
    request_body = {
        "model": config.model,
        "messages": [
            {
                "role": "system",
                "content": "你是英语词义消歧助手。必须只在给定 ECDICT 候选义项中选择，不要创造新释义。输出严格 JSON。",
            },
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ],
        "thinking": {"type": "disabled"},
        "response_format": {"type": "json_object"},
        "temperature": 0,
        "max_tokens": config.max_tokens,
        "stream": False,
    }
    url = f"{config.base_url.rstrip('/')}/chat/completions"
    request = urllib.request.Request(
        url,
        data=json.dumps(request_body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=config.timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None

    try:
        content = payload["choices"][0]["message"]["content"]
        decision = json.loads(content)
        index = int(decision["index"])
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if not 0 <= index < len(senses):
        return None

    confidence = _clamp_float(decision.get("confidence"), default=0.75)
    evidence = str(decision.get("evidence") or "DeepSeek 从 ECDICT 候选义项中选择。")
    return senses[index], confidence, evidence


def _select_by_keyword_overlap(context: str, senses: list[DictionarySense]) -> DictionarySense:
    context_words = set(WORD_RE.findall(context.lower()))
    scored: list[tuple[int, int, DictionarySense]] = []
    for sense in senses:
        words = set(WORD_RE.findall(f"{sense.definition_en} {sense.meaning_zh}".lower()))
        score = len(context_words & words)
        scored.append((score, -sense.sense_rank, sense))
    return max(scored, key=lambda item: (item[0], item[1]))[2]


def _unknown_sense(lemma: str) -> DictionarySense:
    return DictionarySense(
        sense_key=f"missing:{lemma}",
        meaning_zh="ECDICT 未覆盖该词，需补充词典数据",
        definition_en="",
        pos="",
        source="missing_ecdict",
        source_sense_id=f"missing:{lemma}",
        sense_rank=999999,
    )


def _int_or_none(value: object) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: object) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp_float(value: object, *, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, number))
