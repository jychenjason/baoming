import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
BUSY_TIMEOUT_SECONDS = 5.0


@contextmanager
def open_db(db_path: str) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path, timeout=BUSY_TIMEOUT_SECONDS)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()


def init_db(db_path: str) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with open_db(db_path) as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        # Keep existing databases usable after adding option pricing.
        for table, column, declaration in (
            ("options", "price", "INTEGER NOT NULL DEFAULT 0 CHECK (price >= 0)"),
            ("registration_choices", "option_price", "INTEGER NOT NULL DEFAULT 0 CHECK (option_price >= 0)"),
        ):
            columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
            if column not in columns:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
        conn.commit()


def ping(db_path: str) -> None:
    with open_db(db_path) as conn:
        conn.execute("SELECT 1")
