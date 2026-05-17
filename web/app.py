"""FastAPI frontend for the words MVP."""

from __future__ import annotations

from pathlib import Path
import os
import re
import shutil
import sqlite3
import sys

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from words_mvp.config import DEFAULT_CONFIG_PATH, config_section, load_runtime_config, resolve_project_path  # noqa: E402
from words_mvp.db import clear_database, connect_db, fetch_occurrence, fetch_sense, update_user_sense_status  # noqa: E402
from words_mvp.db import fetch_learning_senses, fetch_word_card  # noqa: E402
from words_mvp.meanings import build_related_forms, deepseek_config_from_mapping, load_meaning_dictionary  # noqa: E402
from words_mvp.pipeline import run_mvp_pipeline  # noqa: E402


WEB_DIR = Path(__file__).resolve().parent
SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
ALLOWED_STATUSES = {"learning", "known", "ignored"}


app = FastAPI(title="Words MVP", version="0.1.0")
app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
templates = Jinja2Templates(directory=WEB_DIR / "templates")


class ExtractRequest(BaseModel):
    input_path: str | None = None
    limit: int = Field(default=30, ge=1, le=200)
    min_score: float = 0.0
    persist: bool = True


class SenseStatusRequest(BaseModel):
    sense_id: int
    occurrence_id: int | None = None
    status: str


@app.get("/")
def index(request: Request):
    settings = _settings()
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "files": _list_input_files(settings["upload_dir"]),
            "default_input_path": settings["input_path"],
            "default_limit": settings["limit"],
            "default_min_score": settings["min_score"],
            "deepseek": settings["deepseek_status"],
            "database_path": settings["db_path"],
        },
    )


@app.get("/files")
def files():
    settings = _settings()
    return {"files": _list_input_files(settings["upload_dir"]), "default_input_path": settings["input_path"]}


@app.post("/upload")
def upload(file: UploadFile = File(...)):
    settings = _settings()
    upload_dir = settings["upload_dir"]
    upload_dir.mkdir(parents=True, exist_ok=True)

    original_name = Path(file.filename or "").name
    filename = _safe_filename(original_name)
    if Path(filename).suffix.lower() != ".txt":
        raise HTTPException(status_code=400, detail="Only .txt files are supported.")

    destination = _deduplicate_path(upload_dir / filename)
    with destination.open("wb") as output:
        shutil.copyfileobj(file.file, output)

    rel_path = destination.relative_to(PROJECT_ROOT).as_posix()
    return {"filename": destination.name, "input_path": rel_path, "files": _list_input_files(upload_dir)}


@app.post("/extract")
def extract(payload: ExtractRequest):
    settings = _settings()
    input_path = _resolve_input_path(payload.input_path or settings["input_path"], settings["upload_dir"])
    result = run_mvp_pipeline(
        input_path,
        db_path=settings["db_path"],
        basic_wordlist_path=settings["basic_wordlist_path"],
        target_wordlist_path=settings["target_wordlist_path"],
        dictionary_path=settings["dictionary_path"],
        deepseek_config=settings["deepseek_config"],
        user_id=settings["user_id"],
        limit=payload.limit,
        min_score=payload.min_score,
        persist=payload.persist,
    )
    return result.to_dict()


@app.post("/sense-status")
def sense_status(payload: SenseStatusRequest):
    if payload.status not in ALLOWED_STATUSES:
        raise HTTPException(status_code=400, detail="Unsupported status.")

    settings = _settings()
    connection = connect_db(settings["db_path"])
    try:
        sense = fetch_sense(connection, payload.sense_id)
        if sense is None:
            raise HTTPException(status_code=404, detail="Unknown sense_id.")

        occurrence = fetch_occurrence(connection, payload.occurrence_id) if payload.occurrence_id is not None else None
        update_user_sense_status(
            connection,
            sense_id=payload.sense_id,
            status=payload.status,
            user_id=settings["user_id"],
            source_document_id=int(occurrence["document_id"]) if occurrence is not None else None,
            source_occurrence_id=payload.occurrence_id,
        )
        return {
            "sense_id": payload.sense_id,
            "occurrence_id": payload.occurrence_id,
            "status": payload.status,
            "lemma": sense["lemma"],
            "meaning_zh": sense["meaning_zh"],
        }
    finally:
        connection.close()


@app.get("/database/summary")
def database_summary():
    settings = _settings()
    connection = connect_db(settings["db_path"])
    try:
        table_counts = {
            table: _count_rows(connection, table)
            for table in (
                "documents",
                "lexemes",
                "word_senses",
                "text_occurrences",
                "user_sense_states",
                "user_sense_events",
            )
        }
        status_counts = {
            row["status"]: row["count"]
            for row in connection.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM user_sense_states
                WHERE user_id = ?
                GROUP BY status
                """,
                (settings["user_id"],),
            ).fetchall()
        }
        return {"tables": table_counts, "user_sense_statuses": status_counts}
    finally:
        connection.close()


@app.get("/vocabulary")
def vocabulary():
    settings = _settings()
    connection = connect_db(settings["db_path"])
    try:
        items = []
        for row in fetch_learning_senses(connection, user_id=settings["user_id"]):
            word = row["surface"] or row["lemma"]
            items.append(
                {
                    "sense_id": row["sense_id"],
                    "word": word,
                    "lemma": row["lemma"],
                    "pos": row["pos"],
                    "meaning_zh": row["meaning_zh"],
                    "definition_en": row["definition_en"],
                    "sentence": row["sentence"],
                    "context": row["context"],
                    "filename": row["filename"],
                    "frequency_rank": row["frequency_rank"],
                    "status": row["status"],
                    "added_at": row["last_action_at"] or row["created_at"],
                }
            )
        return {"items": items}
    finally:
        connection.close()


@app.get("/vocabulary/{sense_id}")
def vocabulary_card(sense_id: int):
    settings = _settings()
    connection = connect_db(settings["db_path"])
    try:
        row = fetch_word_card(connection, sense_id, user_id=settings["user_id"])
        if row is None:
            raise HTTPException(status_code=404, detail="Vocabulary card not found.")

        word = row["surface"] or row["lemma"]
        dictionary = load_meaning_dictionary(settings["dictionary_path"])
        forms = build_related_forms(
            dictionary,
            lemma=row["lemma"],
            surface=word,
            selected_sense_key=row["sense_key"],
        )
        return {
            "sense_id": row["sense_id"],
            "word": word,
            "lemma": row["lemma"],
            "pos": row["pos"],
            "meaning_zh": row["meaning_zh"],
            "definition_en": row["definition_en"],
            "source": row["source"],
            "source_sense_id": row["source_sense_id"],
            "sense_rank": row["sense_rank"],
            "frequency_rank": row["frequency_rank"],
            "frequency_score": row["frequency_score"],
            "frequency_source": row["frequency_source"],
            "status": row["status"],
            "added_at": row["added_at"],
            "last_action_at": row["last_action_at"],
            "sentence": row["sentence"],
            "context": row["context"],
            "filename": row["filename"],
            "forms": forms,
        }
    finally:
        connection.close()


@app.post("/database/clear")
def database_clear():
    settings = _settings()
    connection = connect_db(settings["db_path"])
    try:
        deleted_counts = clear_database(connection)
        return {"cleared": True, "deleted": deleted_counts}
    finally:
        connection.close()


@app.exception_handler(HTTPException)
def http_exception_handler(_: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


def _settings() -> dict:
    config = load_runtime_config(DEFAULT_CONFIG_PATH)
    extract_config = config_section(config, "extract_candidates")
    database_config = config_section(config, "database")
    meaning_config = config_section(config, "meaning")
    mvp_config = config_section(config, "mvp")
    web_config = config_section(config, "web")
    deepseek_config = deepseek_config_from_mapping(config_section(meaning_config, "deepseek"))

    upload_dir = Path(resolve_project_path(web_config.get("upload_dir", "input_texts")))
    input_path = str(web_config.get("input_path") or mvp_config.get("path") or config.get("input_path", ""))
    db_path = resolve_project_path(database_config.get("path", "data/words_mvp_v2.sqlite3"))
    api_key = os.environ.get(deepseek_config.api_key_env)

    return {
        "input_path": input_path,
        "upload_dir": upload_dir,
        "db_path": db_path,
        "dictionary_path": resolve_project_path(meaning_config.get("dictionary", "data/dictionaries/ecdict_sample.csv")),
        "basic_wordlist_path": resolve_project_path(extract_config.get("basic_wordlist", "data/wordlists/basic_seed.txt")),
        "target_wordlist_path": resolve_project_path(extract_config.get("target_wordlist", "data/wordlists/target_cet_academic_seed.txt")),
        "limit": int(extract_config.get("limit", 30)),
        "min_score": float(extract_config.get("min_score", 0.0)),
        "user_id": str(mvp_config.get("user_id", "default")),
        "deepseek_config": deepseek_config,
        "deepseek_status": {
            "enabled": deepseek_config.enabled,
            "model": deepseek_config.model,
            "api_key_env": deepseek_config.api_key_env,
            "api_key_set": bool(api_key),
        },
    }


def _list_input_files(upload_dir: Path) -> list[dict]:
    if not upload_dir.exists():
        return []
    files = []
    for path in sorted(upload_dir.glob("*.txt")):
        if not path.is_file():
            continue
        files.append({"name": path.name, "path": path.relative_to(PROJECT_ROOT).as_posix(), "size": path.stat().st_size})
    return files


def _safe_filename(filename: str) -> str:
    cleaned = SAFE_FILENAME_RE.sub("_", filename.strip())
    cleaned = cleaned.strip("._")
    if not cleaned:
        raise HTTPException(status_code=400, detail="Invalid file name.")
    return cleaned


def _deduplicate_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for index in range(1, 1000):
        candidate = path.with_name(f"{stem}_{index}{suffix}")
        if not candidate.exists():
            return candidate
    raise HTTPException(status_code=400, detail="Too many files with similar names.")


def _resolve_input_path(value: str, upload_dir: Path) -> str:
    if not value:
        raise HTTPException(status_code=400, detail="input_path is required.")
    path = Path(resolve_project_path(value)).resolve()
    upload_root = upload_dir.resolve()
    if path.suffix.lower() != ".txt":
        raise HTTPException(status_code=400, detail="Only .txt files are supported.")
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Input file not found: {value}")
    try:
        path.relative_to(upload_root)
    except ValueError as error:
        raise HTTPException(status_code=400, detail="Input file must be inside input_texts.") from error
    return str(path)


def _count_rows(connection: sqlite3.Connection, table: str) -> int:
    return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
