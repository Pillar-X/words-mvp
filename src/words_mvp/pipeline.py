"""End-to-end MVP pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from words_mvp.db import (
    USER_ID,
    connect_db,
    get_or_create_lexeme,
    get_or_create_word_sense,
    load_user_sense_states,
    save_document,
    save_text_occurrence,
)
from words_mvp.meanings import (
    DeepSeekConfig,
    LexemeDictionaryEntry,
    MeaningResult,
    load_meaning_dictionary,
    resolve_candidate_meaning,
)
from words_mvp.preprocess import preprocess_txt_file
from words_mvp.vocabulary import WordCandidate, extract_word_candidates
from words_mvp.wordlists import load_word_list


FILTERED_SENSE_STATUSES = {"ignored", "learning", "known"}


@dataclass(frozen=True)
class EnrichedCandidate:
    occurrence_id: int | None
    sense_id: int | None
    candidate: WordCandidate
    meaning: MeaningResult
    status: str = "new"

    def to_dict(self) -> dict:
        data = self.candidate.to_dict()
        data.update(self.meaning.to_dict())
        data["occurrence_id"] = self.occurrence_id
        data["sense_id"] = self.sense_id
        data["status"] = self.status
        return data


@dataclass(frozen=True)
class MvpResult:
    document_id: int | None
    filename: str
    candidates: list[EnrichedCandidate]

    def to_dict(self) -> dict:
        return {
            "document_id": self.document_id,
            "filename": self.filename,
            "stats": {
                "candidate_count": len(self.candidates),
            },
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }


def run_mvp_pipeline(
    path: str | Path,
    *,
    db_path: str | Path | None,
    basic_wordlist_path: str | Path,
    target_wordlist_path: str | Path,
    dictionary_path: str | Path | None,
    deepseek_config: DeepSeekConfig | None = None,
    user_id: str = USER_ID,
    limit: int = 30,
    min_score: float = 0.0,
    persist: bool = True,
) -> MvpResult:
    document = preprocess_txt_file(path)
    dictionary = load_meaning_dictionary(dictionary_path)

    connection = connect_db(db_path) if persist else None
    document_id: int | None = save_document(connection, document) if connection is not None else None
    user_sense_states = load_user_sense_states(connection, user_id=user_id) if connection is not None else {}

    raw_limit = max(limit * 2, limit)
    candidates = extract_word_candidates(
        document,
        basic_wordlist=load_word_list(basic_wordlist_path, name="basic"),
        target_wordlist=load_word_list(target_wordlist_path, name="target"),
        limit=raw_limit,
        min_score=min_score,
    )

    enriched: list[EnrichedCandidate] = []
    for candidate in candidates:
        meaning = resolve_candidate_meaning(candidate, document, dictionary, deepseek_config=deepseek_config)
        entry = dictionary.get(candidate.lemma)
        occurrence_id: int | None = None
        sense_id: int | None = None
        status = "new"

        if connection is not None and document_id is not None:
            lexeme_id = get_or_create_lexeme(
                connection,
                lemma=candidate.lemma,
                pos=meaning.pos,
                entry=_entry_for_lexeme(entry),
            )
            sense_id = get_or_create_word_sense(connection, lexeme_id, meaning)
            status = user_sense_states.get(sense_id, "new")
            if status in FILTERED_SENSE_STATUSES:
                continue
            occurrence_id = save_text_occurrence(
                connection,
                document_id=document_id,
                candidate=candidate,
                meaning=meaning,
                lexeme_id=lexeme_id,
            )

        enriched.append(
            EnrichedCandidate(
                occurrence_id=occurrence_id,
                sense_id=sense_id,
                candidate=candidate,
                meaning=meaning,
                status=status,
            )
        )
        if len(enriched) >= limit:
            break

    if connection is not None:
        connection.commit()
        connection.close()

    return MvpResult(document_id=document_id, filename=document.filename, candidates=enriched)


def _entry_for_lexeme(entry: LexemeDictionaryEntry | None) -> LexemeDictionaryEntry | None:
    return entry
