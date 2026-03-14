import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Iterable


class DedupStore:
    def __init__(self, path: str = "data/alerts.db"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS processed (
                    raw_id TEXT PRIMARY KEY,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.commit()

    def seen(self, raw_id: str) -> bool:
        with closing(sqlite3.connect(self.path)) as conn:
            cur = conn.execute("SELECT 1 FROM processed WHERE raw_id = ?", (raw_id,))
            row = cur.fetchone()
            return bool(row)

    def mark(self, raw_ids: Iterable[str]) -> None:
        if not raw_ids:
            return
        with closing(sqlite3.connect(self.path)) as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO processed(raw_id) VALUES (?)",
                [(rid,) for rid in raw_ids],
            )
            conn.commit()

    def clear(self) -> None:
        if not self.path.exists():
            return
        with closing(sqlite3.connect(self.path)) as conn:
            conn.execute("DELETE FROM processed")
            conn.commit()

    def backup_exists(self) -> bool:
        return self.path.exists()
