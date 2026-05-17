#!/usr/bin/env python
"""Extract likely unknown words from a .txt file."""

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
from words_mvp.preprocess import preprocess_txt_file  # noqa: E402
from words_mvp.vocabulary import candidates_to_dict, extract_word_candidates  # noqa: E402
from words_mvp.wordlists import load_default_basic_wordlist, load_default_target_wordlist, load_word_list  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract likely unknown words from a .txt file.")
    parser.add_argument("path", nargs="?", help="Path to a .txt file.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to a YAML runtime config.")
    parser.add_argument("--json", action=argparse.BooleanOptionalAction, default=None, help="Print the full JSON result.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of candidates to print.")
    parser.add_argument("--min-score", type=float, default=None, help="Minimum unknown_score to keep.")
    parser.add_argument("--basic-wordlist", help="Optional txt/csv/json basic word list path.")
    parser.add_argument("--target-wordlist", help="Optional txt/csv/json target word list path.")
    parser.add_argument("--known-word", action="append", default=None, help="Known word to penalize. Can be repeated.")
    parser.add_argument("--ignored-word", action="append", default=None, help="Ignored word to filter. Can be repeated.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_runtime_config(args.config)
    extract_config = config_section(config, "extract_candidates")

    input_path = args.path or extract_config.get("path") or config.get("input_path")
    if not input_path:
        raise SystemExit("Missing input path. Provide a path argument or set input_path in config.")
    json_output = args.json if args.json is not None else bool(extract_config.get("json", False))
    limit = args.limit if args.limit is not None else int(extract_config.get("limit", 30))
    min_score = args.min_score if args.min_score is not None else float(extract_config.get("min_score", 0.0))
    basic_wordlist_path = args.basic_wordlist or extract_config.get("basic_wordlist")
    target_wordlist_path = args.target_wordlist or extract_config.get("target_wordlist")
    known_words = args.known_word if args.known_word is not None else list(extract_config.get("known_words", []))
    ignored_words = args.ignored_word if args.ignored_word is not None else list(extract_config.get("ignored_words", []))

    document = preprocess_txt_file(resolve_project_path(input_path))
    basic_wordlist = (
        load_word_list(resolve_project_path(basic_wordlist_path), name="basic")
        if basic_wordlist_path
        else load_default_basic_wordlist()
    )
    target_wordlist = (
        load_word_list(resolve_project_path(target_wordlist_path), name="target")
        if target_wordlist_path
        else load_default_target_wordlist()
    )
    candidates = extract_word_candidates(
        document,
        basic_wordlist=basic_wordlist,
        target_wordlist=target_wordlist,
        known_words=set(known_words),
        ignored_words=set(ignored_words),
        limit=limit,
        min_score=min_score,
    )
    result = candidates_to_dict(document, candidates)

    if json_output:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(f"file: {result['filename']}")
    print(f"candidates: {result['stats']['candidate_count']}")
    print()
    for candidate in result["candidates"]:
        print(
            f"- {candidate['lemma']} "
            f"score={candidate['unknown_score']} "
            f"freq={candidate['frequency']} "
            f"target={candidate['in_target_vocab']} "
            f"basic={candidate['is_basic_word']}"
        )
        print(f"  {candidate['sample_sentence']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
