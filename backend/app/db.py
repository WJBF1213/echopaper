"""SQLite storage layer. Fresh-schema world (design §5.1), user_version=3.

数据库全新开始 (design §三): no compatibility with cloze-era data. init_db
DROPs the legacy question_sets/blanks/attempts/attempt_items tables on every
run; kept tables are created if missing and their existing data is never
touched. Column sets of kept tables are unchanged from v2 so existing
readers/writers keep working.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path
from typing import Any

# Legacy cloze tables removed by the EchoPaper 0.1.0 redesign (design §三,
# user requirement 1). Children first so foreign_keys=ON never sees an
# orphaned reference during the drops. Their indexes (idx_sets_material,
# idx_blanks_set, idx_attempts_material, idx_attempt_items_attempt) die with
# the tables automatically.
_DROPS = """
DROP TABLE IF EXISTS attempt_items;
DROP TABLE IF EXISTS attempts;
DROP TABLE IF EXISTS blanks;
DROP TABLE IF EXISTS question_sets;
"""

SCHEMA = """
CREATE TABLE IF NOT EXISTS materials(
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  source_type TEXT NOT NULL CHECK(source_type IN ('upload','url')),
  audio_path TEXT,
  audio_url TEXT,
  duration_s REAL,
  transcript TEXT NOT NULL DEFAULT '',
  transcript_source TEXT NOT NULL DEFAULT 'asr',
  words_json TEXT NOT NULL DEFAULT '[]',
  sentences_json TEXT NOT NULL DEFAULT '[]',
  asr_model TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings(
  key TEXT PRIMARY KEY,
  value_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS translations(
  hash TEXT PRIMARY KEY,
  src TEXT NOT NULL,
  dst TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS batches(
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  total INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs(
  id TEXT PRIMARY KEY,
  state TEXT NOT NULL,
  message TEXT,
  percent REAL,
  material_id TEXT,
  batch_id TEXT,
  file_name TEXT,
  position INTEGER,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- Local exact-match LLM response cache (design §8.3).
CREATE TABLE IF NOT EXISTS llm_cache(
  cache_key TEXT PRIMARY KEY,   -- sha256(PROMPTS_VERSION|base_url|model|temperature|max_tokens|canonical_messages)
  task TEXT NOT NULL,           -- 'exam:<type>' | 'scene' | 'translate' | ...
  model TEXT NOT NULL,
  response_json TEXT NOT NULL,  -- parsed response, canonical JSON
  prompt_tokens INTEGER,
  completion_tokens INTEGER,
  cached_tokens INTEGER,
  created_at TEXT NOT NULL
);

-- Whole-paper persistence (design §5.1).
CREATE TABLE IF NOT EXISTS papers(
  id TEXT PRIMARY KEY,
  material_id TEXT NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
  spec_json TEXT NOT NULL,      -- user request: blocks + layout_hint + regenerate
  paper_json TEXT NOT NULL,     -- full paper dict (incl. visual scene)
  generation_json TEXT NOT NULL DEFAULT '[]',  -- per-call usage accounting (§8)
  stale INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
-- Server-graded answering (design §5.1): no score history, only the
-- per-item correct flag; stats aggregate per-item accuracy.
CREATE TABLE IF NOT EXISTS paper_attempts(
  id TEXT PRIMARY KEY,
  paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
  material_id TEXT NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS paper_attempt_items(
  attempt_id TEXT NOT NULL REFERENCES paper_attempts(id) ON DELETE CASCADE,
  item_number INTEGER NOT NULL,
  item_type TEXT NOT NULL,
  user_answer TEXT,
  correct INTEGER NOT NULL DEFAULT 0,
  expected TEXT
);
-- Intensive-listening material-level per-sentence translation snapshot
-- (design §7).
CREATE TABLE IF NOT EXISTS material_translations(
  material_id TEXT NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
  sentence_index INTEGER NOT NULL,
  src TEXT NOT NULL,
  dst TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY(material_id, sentence_index)
);

CREATE INDEX IF NOT EXISTS idx_jobs_batch ON jobs(batch_id);
CREATE INDEX IF NOT EXISTS idx_papers_material ON papers(material_id);
CREATE INDEX IF NOT EXISTS idx_paper_attempts_paper ON paper_attempts(paper_id);
CREATE INDEX IF NOT EXISTS idx_paper_attempt_items_attempt ON paper_attempt_items(attempt_id);
"""


# ALL access to the shared connection is serialised process-wide: FastAPI
# handlers run in a threadpool and share one connection opened with
# check_same_thread=False, and CPython's per-connection statement cache
# corrupts under interleaved bind/step/fetch of the same SQL (the
# intermittent settings-500 bug), so even reads must take this lock.
_write_lock = threading.RLock()


class LockedCursor:
    """sqlite3.Cursor proxy: every access takes db._write_lock.

    Each call (fetchone/step, fetchall, ...) is one lock-held critical
    section, so no other thread can reset the shared cached statement
    while this cursor is mid-fetch.
    """

    _UNSET = object()

    def __init__(self, cursor: sqlite3.Cursor) -> None:
        self._cursor = cursor

    def fetchone(self) -> Any:
        with _write_lock:
            return self._cursor.fetchone()

    def fetchall(self) -> list[Any]:
        with _write_lock:
            return self._cursor.fetchall()

    def fetchmany(self, size=_UNSET) -> list[Any]:
        with _write_lock:
            if size is LockedCursor._UNSET:
                return self._cursor.fetchmany()
            return self._cursor.fetchmany(size)

    def close(self) -> None:
        with _write_lock:
            self._cursor.close()

    def __iter__(self) -> Iterator[Any]:
        # Generator: every row fetch re-acquires the lock.
        while True:
            with _write_lock:
                row = self._cursor.fetchone()
            if row is None:
                return
            yield row

    def __getattr__(self, name: str) -> Any:
        # rowcount / lastrowid / description / future attributes.
        if name == "_cursor":
            raise AttributeError(name)
        return getattr(self._cursor, name)


class LockedConnection:
    """sqlite3.Connection proxy: every access takes db._write_lock.

    Threads share ONE connection (app.state.conn). Serialising all calls
    through the module RLock (reentrant, so nested execute-under-`with conn`
    in one thread is fine) closes the statement-cache race; SQLite is
    single-writer anyway and this is a local single-user app.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def execute(self, sql: str, parameters: Sequence[Any] = ()) -> LockedCursor:
        with _write_lock:
            return LockedCursor(self._conn.execute(sql, parameters))

    def executemany(
        self, sql: str, seq_of_parameters: Iterable[Sequence[Any]]
    ) -> LockedCursor:
        with _write_lock:
            return LockedCursor(
                self._conn.executemany(sql, seq_of_parameters)
            )

    def commit(self) -> None:
        with _write_lock:
            self._conn.commit()

    def rollback(self) -> None:
        with _write_lock:
            self._conn.rollback()

    def close(self) -> None:
        with _write_lock:
            self._conn.close()

    def cursor(self, *args: Any, **kwargs: Any) -> LockedCursor:
        with _write_lock:
            return LockedCursor(self._conn.cursor(*args, **kwargs))

    def __enter__(self) -> LockedConnection:
        with _write_lock:
            self._conn.__enter__()
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> bool:
        with _write_lock:
            return self._conn.__exit__(exc_type, exc_value, traceback)

    def __getattr__(self, name: str) -> Any:
        # in_transaction / total_changes / executescript (init_db already
        # holds the lock) / properties / future methods pass through.
        if name == "_conn":
            raise AttributeError(name)
        return getattr(self._conn, name)


def connect(path: str | Path) -> LockedConnection:
    """Open the database: WAL journal, foreign keys on, Row rows.

    Returns a LockedConnection so every later use from any thread is
    serialised through the module _write_lock.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(path), check_same_thread=False, timeout=30.0
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return LockedConnection(conn)


def init_db(conn: sqlite3.Connection) -> None:
    with _write_lock:
        with conn:
            conn.executescript(_DROPS)
            conn.executescript(SCHEMA)
            conn.execute("PRAGMA user_version=3")


def get_setting(conn: sqlite3.Connection, key: str) -> Any | None:
    row = conn.execute(
        "SELECT value_json FROM settings WHERE key=?", (key,)
    ).fetchone()
    if row is None:
        return None
    return json.loads(row["value_json"])


def set_setting(conn: sqlite3.Connection, key: str, value: Any) -> None:
    with _write_lock:
        with conn:
            conn.execute(
                "INSERT INTO settings(key, value_json) VALUES(?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                (key, json.dumps(value, ensure_ascii=False)),
            )
