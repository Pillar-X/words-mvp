"""Vocabulary list loading for candidate scoring."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import csv
import json


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WORDLIST_DIR = PROJECT_ROOT / "data" / "wordlists"
DEFAULT_BASIC_WORDLIST = DEFAULT_WORDLIST_DIR / "basic_seed.txt"
DEFAULT_TARGET_WORDLIST = DEFAULT_WORDLIST_DIR / "target_cet_academic_seed.txt"


@dataclass(frozen=True)
class WordList:
    name: str
    words: frozenset[str]

    def __contains__(self, lemma: str) -> bool:
        return lemma in self.words


def load_word_list(path: str | Path, name: str | None = None) -> WordList:
    """Load a word list from txt, csv, or json.

    TXT files are one word per line. CSV files use the first column unless a
    ``word`` or ``lemma`` column exists. JSON files may be a list of strings,
    list of objects with ``word``/``lemma``, or a mapping whose keys are words.
    """
    file_path = Path(path)
    words = _read_words(file_path)
    return WordList(name=name or file_path.stem, words=frozenset(words))


def load_default_basic_wordlist() -> WordList:
    return load_word_list(DEFAULT_BASIC_WORDLIST, name="basic")


def load_default_target_wordlist() -> WordList:
    return load_word_list(DEFAULT_TARGET_WORDLIST, name="target")


def _read_words(path: Path) -> set[str]:
    suffix = path.suffix.lower()
    if suffix in {"", ".txt", ".list"}:
        return _read_txt_words(path)
    if suffix == ".csv":
        return _read_csv_words(path)
    if suffix == ".json":
        return _read_json_words(path)
    raise ValueError(f"Unsupported word list format: {path}")


def _clean_word(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    word = value.strip().lower()
    if not word or word.startswith("#"):
        return None
    return word


def _read_txt_words(path: Path) -> set[str]:
    words: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        word = _clean_word(line.split("#", 1)[0])
        if word:
            words.add(word)
    return words


def _read_csv_words(path: Path) -> set[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        sample = file.read(2048)
        file.seek(0)
        has_header = csv.Sniffer().has_header(sample)
        if has_header:
            reader = csv.DictReader(file)
            field = _pick_word_field(reader.fieldnames or [])
            return {word for row in reader if (word := _clean_word(row.get(field)))}

        reader = csv.reader(file)
        return {word for row in reader if row and (word := _clean_word(row[0]))}


def _read_json_words(path: Path) -> set[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return {word for key in data if (word := _clean_word(key))}
    if isinstance(data, list):
        words: set[str] = set()
        for item in data:
            if word := _clean_word(item):
                words.add(word)
            elif isinstance(item, dict):
                value = item.get("lemma") or item.get("word") or item.get("headword")
                if word := _clean_word(value):
                    words.add(word)
        return words
    raise ValueError(f"Unsupported JSON word list structure: {path}")


def _pick_word_field(fieldnames: list[str]) -> str:
    lowered = {field.lower(): field for field in fieldnames}
    for candidate in ("lemma", "word", "headword"):
        if candidate in lowered:
            return lowered[candidate]
    return fieldnames[0]
