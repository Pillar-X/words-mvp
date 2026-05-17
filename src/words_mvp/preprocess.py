"""Text import and preprocessing utilities.

This module implements the first MVP step from ``plans/plan01.md``:
read a .txt document, normalize the text, preserve sentence context, tokenize
English words, and derive a lemma for each word token.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
import re
import unicodedata


WORD_RE = re.compile(r"[A-Za-z]+(?:['-][A-Za-z]+)*")
SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+(?=[\"'(\[]?[A-Z0-9])")
WHITESPACE_RE = re.compile(r"[ \t\f\v]+")
BLANK_LINES_RE = re.compile(r"\n{3,}")


@dataclass(frozen=True)
class WordToken:
    text: str
    normalized: str
    lemma: str
    pos: str
    is_stop: bool
    sentence_index: int
    start: int
    end: int


@dataclass(frozen=True)
class Sentence:
    index: int
    text: str
    start: int
    end: int


@dataclass(frozen=True)
class PreprocessedDocument:
    filename: str
    content: str
    sentences: list[Sentence]
    tokens: list[WordToken]

    def to_dict(self) -> dict:
        return {
            "filename": self.filename,
            "content": self.content,
            "sentences": [asdict(sentence) for sentence in self.sentences],
            "tokens": [asdict(token) for token in self.tokens],
            "stats": {
                "sentence_count": len(self.sentences),
                "token_count": len(self.tokens),
                "unique_lemma_count": len({token.lemma for token in self.tokens}),
            },
        }


def read_txt_file(path: str | Path) -> str:
    """Read a .txt file as UTF-8 text."""
    file_path = Path(path)
    if file_path.suffix.lower() != ".txt":
        raise ValueError(f"Only .txt files are supported: {file_path}")
    return file_path.read_text(encoding="utf-8-sig")


def clean_text(text: str) -> str:
    """Normalize Unicode, line endings, spaces, and excessive blank lines."""
    normalized = unicodedata.normalize("NFKC", text)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = "\n".join(WHITESPACE_RE.sub(" ", line).strip() for line in normalized.split("\n"))
    normalized = BLANK_LINES_RE.sub("\n\n", normalized)
    return normalized.strip()


def split_sentences(text: str) -> list[Sentence]:
    """Split text into sentence-like units while preserving offsets.

    The normal path uses spaCy's tokenizer and sentencizer. A regex fallback is
    kept only so the CLI can fail gracefully in an environment without spaCy.
    """
    doc = _spacy_doc_or_none(text)
    if doc is not None:
        return [
            Sentence(index=index, text=span.text.strip(), start=span.start_char, end=span.end_char)
            for index, span in enumerate(doc.sents)
            if span.text.strip()
        ]
    return _fallback_split_sentences(text)


def normalize_word(word: str) -> str:
    """Normalize a token for vocabulary lookup."""
    return word.strip("'").lower()


def lemmatize_word(word: str) -> str:
    """Return a spaCy lookup lemma for a single word."""
    normalized = normalize_word(word)
    lemma = _spacy_lemma_or_none(normalized)
    return lemma or normalized


def tokenize_sentences(sentences: list[Sentence]) -> list[WordToken]:
    """Tokenize all sentences into English word tokens with document offsets."""
    content = _join_sentences_for_lookup(sentences)
    doc = _spacy_doc_or_none(content)
    if doc is not None:
        return _tokenize_with_spacy(doc, sentences)

    return _fallback_tokenize_sentences(sentences)


@lru_cache(maxsize=1)
def _load_spacy_pipeline():
    """Load the best available English spaCy pipeline."""
    try:
        import spacy
    except ImportError:
        return None

    try:
        return spacy.load("en_core_web_sm", exclude=["ner"])
    except OSError:
        pass

    nlp = spacy.blank("en")
    nlp.add_pipe("sentencizer")
    nlp.add_pipe("lemmatizer", config={"mode": "lookup"})
    nlp.initialize()
    return nlp


def _spacy_doc_or_none(text: str):
    nlp = _load_spacy_pipeline()
    if nlp is None:
        return None
    return nlp(text)


@lru_cache(maxsize=4096)
def _spacy_lemma_or_none(word: str) -> str | None:
    doc = _spacy_doc_or_none(word)
    if doc is None:
        return None
    for token in doc:
        if token.is_alpha:
            return _clean_spacy_lemma(token)
    return None


def _clean_spacy_lemma(token) -> str:
    lemma = token.lemma_ or token.text
    if lemma == token.text and token.text != token.text.lower():
        lower_doc = _spacy_doc_or_none(token.text.lower())
        if lower_doc is not None:
            lower_alpha_tokens = [lower_token for lower_token in lower_doc if lower_token.is_alpha]
            if len(lower_alpha_tokens) == 1 and lower_alpha_tokens[0].lemma_:
                lemma = lower_alpha_tokens[0].lemma_
    return normalize_word(lemma)


def _tokenize_with_spacy(doc, sentences: list[Sentence]) -> list[WordToken]:
    sentence_by_offset = {(sentence.start, sentence.end): sentence.index for sentence in sentences}
    sentence_spans = [(sentence.start, sentence.end, sentence.index) for sentence in sentences]
    tokens: list[WordToken] = []

    for token in doc:
        if not token.is_alpha:
            continue
        sentence_index = sentence_by_offset.get((token.sent.start_char, token.sent.end_char))
        if sentence_index is None:
            sentence_index = _find_sentence_index(token.idx, sentence_spans)
        normalized = normalize_word(token.text)
        tokens.append(
            WordToken(
                text=token.text,
                normalized=normalized,
                lemma=_clean_spacy_lemma(token),
                pos=token.pos_,
                is_stop=token.is_stop,
                sentence_index=sentence_index,
                start=token.idx,
                end=token.idx + len(token.text),
            )
        )
    return tokens


def _find_sentence_index(offset: int, sentence_spans: list[tuple[int, int, int]]) -> int:
    for start, end, index in sentence_spans:
        if start <= offset < end:
            return index
    return -1


def _join_sentences_for_lookup(sentences: list[Sentence]) -> str:
    if not sentences:
        return ""
    end = max(sentence.end for sentence in sentences)
    chars = [" "] * end
    for sentence in sentences:
        chars[sentence.start : sentence.end] = sentence.text
    return "".join(chars).rstrip()


def _fallback_split_sentences(text: str) -> list[Sentence]:
    if not text:
        return []

    sentences: list[Sentence] = []
    start = 0
    index = 0
    for match in SENTENCE_END_RE.finditer(text):
        end = match.start() + 1
        sentence_text = text[start:end].strip()
        if sentence_text:
            trimmed_start = start + len(text[start:end]) - len(text[start:end].lstrip())
            sentences.append(Sentence(index=index, text=sentence_text, start=trimmed_start, end=trimmed_start + len(sentence_text)))
            index += 1
        start = match.end()

    tail = text[start:].strip()
    if tail:
        trimmed_start = start + len(text[start:]) - len(text[start:].lstrip())
        sentences.append(Sentence(index=index, text=tail, start=trimmed_start, end=trimmed_start + len(tail)))
    return sentences


def _fallback_tokenize_sentences(sentences: list[Sentence]) -> list[WordToken]:
    tokens: list[WordToken] = []
    for sentence in sentences:
        for match in WORD_RE.finditer(sentence.text):
            text = match.group(0)
            normalized = normalize_word(text)
            tokens.append(
                WordToken(
                    text=text,
                    normalized=normalized,
                    lemma=normalized,
                    pos="",
                    is_stop=False,
                    sentence_index=sentence.index,
                    start=sentence.start + match.start(),
                    end=sentence.start + match.end(),
                )
            )
    return tokens


def preprocess_text(text: str, filename: str = "<memory>") -> PreprocessedDocument:
    """Clean, sentence-split, tokenize, and lemmatize text."""
    content = clean_text(text)
    sentences = split_sentences(content)
    tokens = tokenize_sentences(sentences)
    return PreprocessedDocument(filename=filename, content=content, sentences=sentences, tokens=tokens)


def preprocess_txt_file(path: str | Path) -> PreprocessedDocument:
    """Read and preprocess a .txt document."""
    file_path = Path(path)
    return preprocess_text(read_txt_file(file_path), filename=file_path.name)
