#!/usr/bin/env python
"""Update a user's sense-level word status."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from words_mvp.config import DEFAULT_CONFIG_PATH, config_section, load_runtime_config, resolve_project_path  # noqa: E402
from words_mvp.db import connect_db, fetch_occurrence, fetch_sense, update_user_sense_status  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Set a user's status for a specific word sense.")
    parser.add_argument("sense_id", type=int, help="Specific word sense id from run_mvp output.")
    parser.add_argument("status", choices=["learning", "in_book", "known", "ignored", "archived"], help="New sense status.")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to a YAML runtime config.")
    parser.add_argument("--occurrence-id", type=int, default=None, help="Optional source occurrence id from run_mvp output.")
    parser.add_argument("--user-id", default=None, help="User id. Defaults to config mvp.user_id.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_runtime_config(args.config)
    database_config = config_section(config, "database")
    mvp_config = config_section(config, "mvp")
    db_path = resolve_project_path(database_config.get("path", "data/words_mvp_v2.sqlite3"))
    user_id = args.user_id or str(mvp_config.get("user_id", "default"))

    connection = connect_db(db_path)
    sense = fetch_sense(connection, args.sense_id)
    if sense is None:
        raise SystemExit(f"Unknown sense_id: {args.sense_id}")

    occurrence = fetch_occurrence(connection, args.occurrence_id) if args.occurrence_id is not None else None
    update_user_sense_status(
        connection,
        sense_id=args.sense_id,
        status=args.status,
        user_id=user_id,
        source_document_id=int(occurrence["document_id"]) if occurrence is not None else None,
        source_occurrence_id=args.occurrence_id,
    )
    connection.close()

    print(f"{sense['lemma']} / {sense['meaning_zh']} -> {args.status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
