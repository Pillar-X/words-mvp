"""Candidate extraction for words a user may not know."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
import math
import re

from words_mvp.preprocess import PreprocessedDocument, WordToken
from words_mvp.wordlists import WordList, load_default_basic_wordlist, load_default_target_wordlist


LEMMA_RE = re.compile(r"^[a-z][a-z'-]*$")
MIN_WORD_LENGTH = 3
FALLBACK_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "but",
    "by",
    "for",
    "from",
    "if",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "to",
    "was",
    "were",
    "with",
}
PROPER_NOUN_POS = {"PROPN"}


@dataclass(frozen=True)
class WordCandidate:
    word: str
    lemma: str
    frequency: int
    sentence_indices: list[int]
    sample_sentence: str
    unknown_score: float
    difficulty_score: float
    target_vocab_weight: float
    frequency_weight: float
    basic_word_penalty: float
    user_known_penalty: float
    is_basic_word: bool
    in_target_vocab: bool
    reasons: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def extract_word_candidates(
    document: PreprocessedDocument,
    *,
    basic_wordlist: WordList | None = None,
    target_wordlist: WordList | None = None,
    known_words: set[str] | None = None,
    ignored_words: set[str] | None = None,
    limit: int | None = 30,
    min_score: float = 0.0,
) -> list[WordCandidate]:
    """Extract and rank likely unknown words from a preprocessed document."""
    basic_words = basic_wordlist or load_default_basic_wordlist()
    target_words = target_wordlist or load_default_target_wordlist()
    known = _normalize_word_set(known_words)
    ignored = _normalize_word_set(ignored_words)

    grouped: dict[str, list[WordToken]] = defaultdict(list)
    for token in document.tokens:
        lemma = token.lemma
        if not _is_candidate_token(token, target_words=target_words, ignored_words=ignored):
            continue
        grouped[lemma].append(token)

    candidates = [
        _build_candidate(
            lemma,
            tokens,
            document=document,
            basic_words=basic_words,
            target_words=target_words,
            known_words=known,
        )
        for lemma, tokens in grouped.items()
    ]
    ranked = sorted(
        (candidate for candidate in candidates if candidate.unknown_score >= min_score),
        key=lambda candidate: (-candidate.unknown_score, candidate.lemma),
    )
    if limit is None:
        return ranked
    return ranked[:limit]


def candidates_to_dict(document: PreprocessedDocument, candidates: list[WordCandidate]) -> dict:
    return {
        "filename": document.filename,
        "stats": {
            "sentence_count": len(document.sentences),
            "token_count": len(document.tokens),
            "candidate_count": len(candidates),
        },
        "candidates": [candidate.to_dict() for candidate in candidates],
    }


def _is_candidate_token(token: WordToken, *, target_words: WordList, ignored_words: set[str]) -> bool:
    lemma = token.lemma
    in_target = lemma in target_words
    if lemma in ignored_words:
        return False
    if not LEMMA_RE.fullmatch(lemma):
        return False
    if len(lemma) < MIN_WORD_LENGTH and not in_target:
        return False
    if (token.is_stop or lemma in FALLBACK_STOP_WORDS) and not in_target:
        return False
    if token.pos in PROPER_NOUN_POS and not in_target:
        return False
    return True


def _build_candidate(
    lemma: str,
    tokens: list[WordToken],
    *,
    document: PreprocessedDocument,
    basic_words: WordList,
    target_words: WordList,
    known_words: set[str],
) -> WordCandidate:
    frequency = len(tokens)
    is_basic = lemma in basic_words
    in_target = lemma in target_words
    sentence_indices = sorted({token.sentence_index for token in tokens if token.sentence_index >= 0})
    sample_sentence = _sample_sentence(document, sentence_indices)
    display_word = _most_common_surface(tokens)

    difficulty_score = _difficulty_score(lemma, is_basic=is_basic)
    target_vocab_weight = 2.0 if in_target else 0.0
    frequency_weight = min(1.5, math.log1p(frequency) * 0.7)
    basic_word_penalty = 2.5 if is_basic and not in_target else 0.0
    user_known_penalty = 4.0 if lemma in known_words else 0.0
    unknown_score = round(
        difficulty_score + target_vocab_weight + frequency_weight - basic_word_penalty - user_known_penalty,
        3,
    )
    reasons = _candidate_reasons(
        frequency=frequency,
        is_basic=is_basic,
        in_target=in_target,
        known=lemma in known_words,
    )

    return WordCandidate(
        word=display_word,
        lemma=lemma,
        frequency=frequency,
        sentence_indices=sentence_indices,
        sample_sentence=sample_sentence,
        unknown_score=unknown_score,
        difficulty_score=round(difficulty_score, 3),
        target_vocab_weight=target_vocab_weight,
        frequency_weight=round(frequency_weight, 3),
        basic_word_penalty=basic_word_penalty,
        user_known_penalty=user_known_penalty,
        is_basic_word=is_basic,
        in_target_vocab=in_target,
        reasons=reasons,
    )


def _difficulty_score(lemma: str, *, is_basic: bool) -> float:
    if is_basic:
        return 0.6
    length_score = min(2.0, max(0.0, (len(lemma) - 4) * 0.25))
    morphology_bonus = 0.4 if any(suffix in lemma for suffix in ("tion", "ment", "ity", "ive", "ous")) else 0.0
    return 1.0 + length_score + morphology_bonus


def _candidate_reasons(*, frequency: int, is_basic: bool, in_target: bool, known: bool) -> list[str]:
    reasons: list[str] = []
    if in_target:
        reasons.append("target_vocab")
    if frequency > 1:
        reasons.append("repeated_in_text")
    if is_basic:
        reasons.append("basic_word_penalty")
    else:
        reasons.append("not_in_basic_wordlist")
    if known:
        reasons.append("known_word_penalty")
    return reasons


def _sample_sentence(document: PreprocessedDocument, sentence_indices: list[int]) -> str:
    if not sentence_indices:
        return ""
    index = sentence_indices[0]
    if 0 <= index < len(document.sentences):
        return document.sentences[index].text
    return ""


def _most_common_surface(tokens: list[WordToken]) -> str:
    counter = Counter(token.normalized for token in tokens)
    return counter.most_common(1)[0][0]


def _normalize_word_set(words: set[str] | None) -> set[str]:
    if not words:
        return set()
    return {word.strip().lower() for word in words if word.strip()}
