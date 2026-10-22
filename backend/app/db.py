"""SQLite storage layer (Task B1). Schema per design spec §5, user_version=2."""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

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

CREATE TABLE IF NOT EXISTS question_sets(
  id TEXT PRIMARY KEY,
  material_id TEXT NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
  mode TEXT NOT NULL CHECK(mode IN ('llm','nouns','manual')),
  blank_count INTEGER NOT NULL,
  params_json TEXT NOT NULL DEFAULT '{}',
  stale INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS blanks(
  id TEXT PRIMARY KEY,
  set_id TEXT NOT NULL REFERENCES question_sets(id) ON DELETE CASCADE,
  position INTEGER NOT NULL,
  answer TEXT NOT NULL,
  alternatives_json TEXT NOT NULL DEFAULT '[]',
  word_start INTEGER NOT NULL,
  word_end INTEGER NOT NULL,
  t_start REAL,
  t_end REAL,
  type TEXT,
  word_limit TEXT
);

CREATE TABLE IF NOT EXISTS attempts(
  id TEXT PRIMARY KEY,
  set_id TEXT REFERENCES question_sets(id) ON DELETE SET NULL,
  material_id TEXT NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
  mode TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT,
  ok INTEGER NOT NULL DEFAULT 0,
  total INTEGER NOT NULL DEFAULT 0,
  duration_s REAL
);

CREATE TABLE IF NOT EXISTS attempt_items(
  attempt_id TEXT NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
  blank_id TEXT,
  word_index INTEGER,
  user_text TEXT,
  correct INTEGER NOT NULL DEFAULT 0,
  expected TEXT
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

-- Local exact-match LLM response cache (design §8.3). user_version stays
-- at 2: CREATE TABLE IF NOT EXISTS migrates existing databases on init.
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

CREATE INDEX IF NOT EXISTS idx_blanks_set ON blanks(set_id);
CREATE INDEX IF NOT EXISTS idx_attempt_items_attempt ON attempt_items(attempt_id);
CREATE INDEX IF NOT EXISTS idx_attempts_material ON attempts(material_id);
CREATE INDEX IF NOT EXISTS idx_sets_material ON question_sets(material_id);
"""


# Writes are serialised process-wide: FastAPI handlers run in a threadpool
# and share this module's connection, so a module-level RLock is enough.
_write_lock = threading.RLock()


def connect(path: str | Path) -> sqlite3.Connection:
    """Open the database: WAL journal, foreign keys on, Row rows."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(path), check_same_thread=False, timeout=30.0
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


# Columns added after v1. Existing databases only get CREATE TABLE IF NOT
# EXISTS, so additive migrations are applied explicitly below.
_JOB_COLUMNS = {
    "batch_id": "TEXT",
    "file_name": "TEXT",
    "position": "INTEGER",
}


def _add_missing_columns(
    conn: sqlite3.Connection, table: str, columns: dict[str, str]
) -> None:
    # PRAGMA table_info column 1 is the column name; use indices so this
    # works on bare sqlite3 connections without a Row factory.
    existing = {
        row[1]
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }
    for name, decl in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


def init_db(conn: sqlite3.Connection) -> None:
    with _write_lock:
        with conn:
            conn.executescript(SCHEMA)
            _add_missing_columns(conn, "jobs", _JOB_COLUMNS)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_jobs_batch ON jobs(batch_id)"
            )
            conn.execute("PRAGMA user_version=2")


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
