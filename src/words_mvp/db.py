"""SQLite persistence for sense-level vocabulary state."""

from __future__ import annotations

from pathlib import Path
import sqlite3

from words_mvp.config import PROJECT_ROOT
from words_mvp.meanings import LexemeDictionaryEntry, MeaningResult
from words_mvp.preprocess import PreprocessedDocument
from words_mvp.vocabulary import WordCandidate


DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "words_mvp_v2.sqlite3"
VALID_STATUSES = {"learning", "known", "ignored", "archived"}
STATUS_ALIASES = {"in_book": "learning"}
USER_ID = "default"
CLEARABLE_TABLES = (
    "user_sense_events",
    "user_sense_states",
    "text_occurrences",
    "word_senses",
    "lexemes",
    "documents",
)


def connect_db(path: str | Path | None = None) -> sqlite3.Connection:
    db_path = Path(path) if path else DEFAULT_DB_PATH
    if not db_path.is_absolute():
        db_path = PROJECT_ROOT / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    init_db(connection)
    return connection


def init_db(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS lexemes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lemma TEXT NOT NULL,
            language TEXT NOT NULL DEFAULT 'en',
            pos TEXT NOT NULL DEFAULT '',
            frequency_rank INTEGER,
            frequency_score REAL,
            frequency_source TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(language, lemma, pos)
        );

        CREATE TABLE IF NOT EXISTS word_senses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lexeme_id INTEGER NOT NULL,
            sense_key TEXT NOT NULL UNIQUE,
            meaning_zh TEXT NOT NULL,
            definition_en TEXT NOT NULL DEFAULT '',
            pos TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL,
            source_sense_id TEXT NOT NULL DEFAULT '',
            sense_rank INTEGER,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(lexeme_id) REFERENCES lexemes(id)
        );

        CREATE TABLE IF NOT EXISTS text_occurrences (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL,
            surface TEXT NOT NULL,
            normalized TEXT NOT NULL,
            lemma TEXT NOT NULL,
            lexeme_id INTEGER,
            sentence_index INTEGER,
            sentence TEXT NOT NULL,
            context TEXT NOT NULL,
            start_offset INTEGER,
            end_offset INTEGER,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(document_id) REFERENCES documents(id),
            FOREIGN KEY(lexeme_id) REFERENCES lexemes(id)
        );

        CREATE TABLE IF NOT EXISTS user_sense_states (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            sense_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            mastery_level INTEGER NOT NULL DEFAULT 0,
            source_document_id INTEGER,
            source_occurrence_id INTEGER,
            last_seen_at TEXT,
            last_action_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, sense_id),
            FOREIGN KEY(sense_id) REFERENCES word_senses(id),
            FOREIGN KEY(source_document_id) REFERENCES documents(id),
            FOREIGN KEY(source_occurrence_id) REFERENCES text_occurrences(id)
        );

        CREATE TABLE IF NOT EXISTS user_sense_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            sense_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            from_status TEXT,
            to_status TEXT NOT NULL,
            document_id INTEGER,
            occurrence_id INTEGER,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(sense_id) REFERENCES word_senses(id),
            FOREIGN KEY(document_id) REFERENCES documents(id),
            FOREIGN KEY(occurrence_id) REFERENCES text_occurrences(id)
        );

        CREATE INDEX IF NOT EXISTS idx_lexemes_lemma ON lexemes(lemma);
        CREATE INDEX IF NOT EXISTS idx_word_senses_lexeme_id ON word_senses(lexeme_id);
        CREATE INDEX IF NOT EXISTS idx_text_occurrences_document_id ON text_occurrences(document_id);
        CREATE INDEX IF NOT EXISTS idx_user_sense_states_status ON user_sense_states(status);
        """
    )
    connection.commit()


def clear_database(connection: sqlite3.Connection) -> dict[str, int]:
    """Delete all runtime vocabulary data while keeping the schema in place."""
    deleted_counts: dict[str, int] = {}
    for table in CLEARABLE_TABLES:
        cursor = connection.execute(f"DELETE FROM {table}")
        deleted_counts[table] = max(int(cursor.rowcount), 0)

    placeholders = ", ".join("?" for _ in CLEARABLE_TABLES)
    connection.execute(f"DELETE FROM sqlite_sequence WHERE name IN ({placeholders})", CLEARABLE_TABLES)
    connection.commit()
    return deleted_counts


def save_document(connection: sqlite3.Connection, document: PreprocessedDocument) -> int:
    cursor = connection.execute(
        "INSERT INTO documents (filename, content) VALUES (?, ?)",
        (document.filename, document.content),
    )
    connection.commit()
    return int(cursor.lastrowid)


def get_or_create_lexeme(
    connection: sqlite3.Connection,
    *,
    lemma: str,
    pos: str = "",
    entry: LexemeDictionaryEntry | None = None,
) -> int:
    normalized_lemma = lemma.strip().lower()
    normalized_pos = pos or (entry.pos if entry else "") or ""
    connection.execute(
        """
        INSERT OR IGNORE INTO lexemes (
            lemma,
            language,
            pos,
            frequency_rank,
            frequency_score,
            frequency_source
        )
        VALUES (?, 'en', ?, ?, ?, ?)
        """,
        (
            normalized_lemma,
            normalized_pos,
            entry.frequency_rank if entry else None,
            entry.frequency_score if entry else None,
            entry.frequency_source if entry else "",
        ),
    )
    connection.execute(
        """
        UPDATE lexemes
        SET
            frequency_rank = COALESCE(frequency_rank, ?),
            frequency_score = COALESCE(frequency_score, ?),
            frequency_source = CASE
                WHEN frequency_source = '' THEN ?
                ELSE frequency_source
            END
        WHERE language = 'en' AND lemma = ? AND pos = ?
        """,
        (
            entry.frequency_rank if entry else None,
            entry.frequency_score if entry else None,
            entry.frequency_source if entry else "",
            normalized_lemma,
            normalized_pos,
        ),
    )
    cursor = connection.execute(
        "SELECT id FROM lexemes WHERE language = 'en' AND lemma = ? AND pos = ?",
        (normalized_lemma, normalized_pos),
    )
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError(f"Failed to create lexeme: {lemma}")
    return int(row["id"])


def get_or_create_word_sense(connection: sqlite3.Connection, lexeme_id: int, meaning: MeaningResult) -> int:
    connection.execute(
        """
        INSERT INTO word_senses (
            lexeme_id,
            sense_key,
            meaning_zh,
            definition_en,
            pos,
            source,
            source_sense_id,
            sense_rank
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(sense_key) DO UPDATE SET
            meaning_zh = excluded.meaning_zh,
            definition_en = excluded.definition_en,
            pos = excluded.pos,
            source = excluded.source,
            source_sense_id = excluded.source_sense_id,
            sense_rank = excluded.sense_rank,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            lexeme_id,
            meaning.sense_key,
            meaning.meaning_in_context,
            meaning.definition_en,
            meaning.pos,
            meaning.source,
            meaning.source_sense_id,
            meaning.sense_rank,
        ),
    )
    cursor = connection.execute("SELECT id FROM word_senses WHERE sense_key = ?", (meaning.sense_key,))
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError(f"Failed to create word sense: {meaning.sense_key}")
    return int(row["id"])


def save_text_occurrence(
    connection: sqlite3.Connection,
    *,
    document_id: int,
    candidate: WordCandidate,
    meaning: MeaningResult,
    lexeme_id: int,
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO text_occurrences (
            document_id,
            surface,
            normalized,
            lemma,
            lexeme_id,
            sentence_index,
            sentence,
            context,
            start_offset,
            end_offset
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            document_id,
            candidate.word,
            candidate.word,
            candidate.lemma,
            lexeme_id,
            candidate.sentence_indices[0] if candidate.sentence_indices else None,
            candidate.sample_sentence,
            meaning.context,
            None,
            None,
        ),
    )
    return int(cursor.lastrowid)


def update_user_sense_status(
    connection: sqlite3.Connection,
    *,
    sense_id: int,
    status: str,
    user_id: str = USER_ID,
    source_document_id: int | None = None,
    source_occurrence_id: int | None = None,
) -> None:
    normalized_status = STATUS_ALIASES.get(status, status)
    if normalized_status not in VALID_STATUSES:
        raise ValueError(f"Unsupported user sense status: {status}")

    previous = connection.execute(
        "SELECT status FROM user_sense_states WHERE user_id = ? AND sense_id = ?",
        (user_id, sense_id),
    ).fetchone()
    from_status = str(previous["status"]) if previous is not None else None
    mastery_level = _mastery_level_for_status(normalized_status)

    connection.execute(
        """
        INSERT INTO user_sense_states (
            user_id,
            sense_id,
            status,
            mastery_level,
            source_document_id,
            source_occurrence_id,
            last_seen_at,
            last_action_at
        )
        VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id, sense_id) DO UPDATE SET
            status = excluded.status,
            mastery_level = excluded.mastery_level,
            source_document_id = COALESCE(excluded.source_document_id, user_sense_states.source_document_id),
            source_occurrence_id = COALESCE(excluded.source_occurrence_id, user_sense_states.source_occurrence_id),
            last_seen_at = CURRENT_TIMESTAMP,
            last_action_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        """,
        (user_id, sense_id, normalized_status, mastery_level, source_document_id, source_occurrence_id),
    )
    connection.execute(
        """
        INSERT INTO user_sense_events (
            user_id,
            sense_id,
            event_type,
            from_status,
            to_status,
            document_id,
            occurrence_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            user_id,
            sense_id,
            _event_type_for_status(normalized_status),
            from_status,
            normalized_status,
            source_document_id,
            source_occurrence_id,
        ),
    )
    connection.commit()


def load_user_sense_states(connection: sqlite3.Connection, *, user_id: str = USER_ID) -> dict[int, str]:
    cursor = connection.execute(
        "SELECT sense_id, status FROM user_sense_states WHERE user_id = ?",
        (user_id,),
    )
    return {int(row["sense_id"]): str(row["status"]) for row in cursor.fetchall()}


def fetch_sense(connection: sqlite3.Connection, sense_id: int) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT
            word_senses.*,
            lexemes.lemma
        FROM word_senses
        JOIN lexemes ON lexemes.id = word_senses.lexeme_id
        WHERE word_senses.id = ?
        """,
        (sense_id,),
    ).fetchone()


def fetch_occurrence(connection: sqlite3.Connection, occurrence_id: int) -> sqlite3.Row | None:
    return connection.execute("SELECT * FROM text_occurrences WHERE id = ?", (occurrence_id,)).fetchone()


def fetch_learning_senses(connection: sqlite3.Connection, *, user_id: str = USER_ID) -> list[sqlite3.Row]:
    return connection.execute(
        """
        SELECT
            user_sense_states.sense_id,
            user_sense_states.status,
            user_sense_states.mastery_level,
            user_sense_states.last_action_at,
            user_sense_states.created_at,
            lexemes.lemma,
            lexemes.frequency_rank,
            word_senses.meaning_zh,
            word_senses.definition_en,
            word_senses.pos,
            text_occurrences.surface,
            text_occurrences.sentence,
            text_occurrences.context,
            documents.filename
        FROM user_sense_states
        JOIN word_senses ON word_senses.id = user_sense_states.sense_id
        JOIN lexemes ON lexemes.id = word_senses.lexeme_id
        LEFT JOIN text_occurrences ON text_occurrences.id = user_sense_states.source_occurrence_id
        LEFT JOIN documents ON documents.id = user_sense_states.source_document_id
        WHERE user_sense_states.user_id = ? AND user_sense_states.status = 'learning'
        ORDER BY user_sense_states.last_action_at DESC, user_sense_states.id DESC
        """,
        (user_id,),
    ).fetchall()


def fetch_word_card(connection: sqlite3.Connection, sense_id: int, *, user_id: str = USER_ID) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT
            user_sense_states.sense_id,
            user_sense_states.status,
            user_sense_states.mastery_level,
            user_sense_states.last_seen_at,
            user_sense_states.last_action_at,
            user_sense_states.created_at AS added_at,
            lexemes.lemma,
            lexemes.frequency_rank,
            lexemes.frequency_score,
            lexemes.frequency_source,
            word_senses.sense_key,
            word_senses.meaning_zh,
            word_senses.definition_en,
            word_senses.pos,
            word_senses.source,
            word_senses.source_sense_id,
            word_senses.sense_rank,
            text_occurrences.surface,
            text_occurrences.sentence,
            text_occurrences.context,
            documents.filename
        FROM user_sense_states
        JOIN word_senses ON word_senses.id = user_sense_states.sense_id
        JOIN lexemes ON lexemes.id = word_senses.lexeme_id
        LEFT JOIN text_occurrences ON text_occurrences.id = user_sense_states.source_occurrence_id
        LEFT JOIN documents ON documents.id = user_sense_states.source_document_id
        WHERE user_sense_states.user_id = ? AND user_sense_states.sense_id = ?
        """,
        (user_id, sense_id),
    ).fetchone()


def _mastery_level_for_status(status: str) -> int:
    if status == "known":
        return 5
    if status == "learning":
        return 1
    return 0


def _event_type_for_status(status: str) -> str:
    if status == "learning":
        return "add_to_book"
    if status == "known":
        return "mark_known"
    if status == "ignored":
        return "ignore_once"
    return "reset_status"
