from __future__ import annotations

import argparse
import logging
import sqlite3
from pathlib import Path

from database.schema import COMPETITORS, INDEXES_SQL, TABLES_SQL

DEFAULT_DB_PATH = Path("competitor_data.db")


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )


def init_database(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON;")

        for statement in TABLES_SQL:
            conn.execute(statement)

        for statement in INDEXES_SQL:
            conn.execute(statement)

        conn.executemany(
            """
            INSERT OR IGNORE INTO competitors (domain, base_url)
            VALUES (?, ?)
            """,
            COMPETITORS,
        )

        conn.commit()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Initialize competitor tracker SQLite database")
    parser.add_argument(
        "--db-path",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"Path to SQLite DB file (default: {DEFAULT_DB_PATH})",
    )
    return parser.parse_args()


def main() -> int:
    configure_logging()
    args = parse_args()

    try:
        init_database(args.db_path)
        logging.info("Database initialized at %s", args.db_path)
        return 0
    except sqlite3.Error as exc:
        logging.exception("SQLite error during initialization: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
