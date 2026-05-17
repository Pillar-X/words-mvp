#!/usr/bin/env python
"""Run the complete MVP flow for a .txt file."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from words_mvp.config import DEFAULT_CONFIG_PATH, config_section, load_runtime_config, resolve_project_path  # noqa: E402
from words_mvp.meanings import deepseek_config_from_mapping  # noqa: E402
from words_mvp.pipeline import run_mvp_pipeline  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the complete words MVP flow.")
    parser.add_argument("path", nargs="?", help="Path to a .txt file.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to a YAML runtime config.")
    parser.add_argument("--json", action=argparse.BooleanOptionalAction, default=None, help="Print JSON result.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of candidates.")
    parser.add_argument("--min-score", type=float, default=None, help="Minimum unknown_score to keep.")
    parser.add_argument("--no-persist", action="store_true", help="Do not save document and candidates to SQLite.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_runtime_config(args.config)
    extract_config = config_section(config, "extract_candidates")
    database_config = config_section(config, "database")
    meaning_config = config_section(config, "meaning")
    mvp_config = config_section(config, "mvp")

    input_path = args.path or mvp_config.get("path") or config.get("input_path")
    if not input_path:
        raise SystemExit("Missing input path. Provide a path argument or set input_path in config.")

    json_output = args.json if args.json is not None else bool(mvp_config.get("json", False))
    limit = args.limit if args.limit is not None else int(extract_config.get("limit", 30))
    min_score = args.min_score if args.min_score is not None else float(extract_config.get("min_score", 0.0))
    persist = not args.no_persist and bool(mvp_config.get("persist", True))
    db_path = resolve_project_path(database_config.get("path", "data/words_mvp.sqlite3"))
    dictionary_path = resolve_project_path(meaning_config.get("dictionary", "data/dictionaries/ecdict_sample.csv"))
    deepseek_config = deepseek_config_from_mapping(config_section(meaning_config, "deepseek"))
    user_id = str(mvp_config.get("user_id", "default"))
    basic_wordlist_path = resolve_project_path(extract_config.get("basic_wordlist", "data/wordlists/basic_seed.txt"))
    target_wordlist_path = resolve_project_path(extract_config.get("target_wordlist", "data/wordlists/target_cet_academic_seed.txt"))

    result = run_mvp_pipeline(
        resolve_project_path(input_path),
        db_path=db_path,
        basic_wordlist_path=basic_wordlist_path,
        target_wordlist_path=target_wordlist_path,
        dictionary_path=dictionary_path,
        deepseek_config=deepseek_config,
        user_id=user_id,
        limit=limit,
        min_score=min_score,
        persist=persist,
    )
    result_dict = result.to_dict()

    if json_output:
        print(json.dumps(result_dict, ensure_ascii=False, indent=2))
        return 0

    print(f"document_id: {result_dict['document_id']}")
    print(f"file: {result_dict['filename']}")
    print(f"candidates: {result_dict['stats']['candidate_count']}")
    print()
    for candidate in result_dict["candidates"]:
        print(
            f"- {candidate['lemma']} "
            f"score={candidate['unknown_score']} "
            f"freq={candidate['frequency']} "
            f"status={candidate['status']} "
            f"sense_id={candidate['sense_id']} "
            f"occurrence_id={candidate['occurrence_id']}"
        )
        print(f"  释义: {candidate['meaning_in_context']}")
        print(f"  句子: {candidate['sample_sentence']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
