#!/usr/bin/env python
"""Run text import and preprocessing for a .txt file."""

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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Preprocess a .txt file for the words MVP.")
    parser.add_argument("path", nargs="?", help="Path to a .txt file.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to a YAML runtime config.")
    parser.add_argument("--json", action=argparse.BooleanOptionalAction, default=None, help="Print the full JSON result.")
    parser.add_argument("--limit", type=int, default=None, help="Number of sample tokens to print.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_runtime_config(args.config)
    preprocess_config = config_section(config, "preprocess")

    input_path = args.path or preprocess_config.get("path") or config.get("input_path")
    if not input_path:
        raise SystemExit("Missing input path. Provide a path argument or set input_path in config.")
    json_output = args.json if args.json is not None else bool(preprocess_config.get("json", False))
    limit = args.limit if args.limit is not None else int(preprocess_config.get("limit", 30))

    document = preprocess_txt_file(resolve_project_path(input_path))
    result = document.to_dict()

    if json_output:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(f"file: {result['filename']}")
    print(f"sentences: {result['stats']['sentence_count']}")
    print(f"tokens: {result['stats']['token_count']}")
    print(f"unique lemmas: {result['stats']['unique_lemma_count']}")
    print()
    print("sample sentences:")
    for sentence in result["sentences"][:3]:
        print(f"- [{sentence['index']}] {sentence['text']}")
    print()
    print("sample tokens:")
    for token in result["tokens"][:limit]:
        print(
            f"- {token['text']} -> normalized={token['normalized']}, "
            f"lemma={token['lemma']}, pos={token['pos'] or 'N/A'}, "
            f"sentence={token['sentence_index']}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
