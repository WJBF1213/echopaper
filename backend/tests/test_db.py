"""Database schema tests: fresh v3 world (redesign §5.1, Task 19).

The cloze-era tables (question_sets/blanks/attempts/attempt_items) are
dropped on init — no compatibility layer survives (design §三, user
requirement 1: 数据库全新开始).
"""

KEPT_TABLES = {
    "materials",
    "settings",
    "translations",
    "batches",
    "jobs",
    "papers",
    "paper_attempts",
    "paper_attempt_items",
    "material_translations",
    "llm_cache",
}
LEGACY_TABLES = ("question_sets", "blanks", "attempts", "attempt_items")
LEGACY_INDEXES = (
    "idx_sets_material",
    "idx_blanks_set",
    "idx_attempts_material",
    "idx_attempt_items_attempt",
)

# The v2-era cloze DDL, frozen here so the migration test can build a
# realistic legacy database even though db.py no longer creates these.
LEGACY_SCHEMA = """
CREATE TABLE question_sets(
  id TEXT PRIMARY KEY,
  material_id TEXT NOT NULL REFERENCES materials(id) ON DELETE CASCADE,
  mode TEXT NOT NULL CHECK(mode IN ('llm','nouns','manual')),
  blank_count INTEGER NOT NULL,
  params_json TEXT NOT NULL DEFAULT '{}',
  stale INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
CREATE TABLE blanks(
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
CREATE TABLE attempts(
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
CREATE TABLE attempt_items(
  attempt_id TEXT NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
  blank_id TEXT,
  word_index INTEGER,
  user_text TEXT,
  correct INTEGER NOT NULL DEFAULT 0,
  expected TEXT
);
CREATE INDEX idx_sets_material ON question_sets(material_id);
CREATE INDEX idx_blanks_set ON blanks(set_id);
CREATE INDEX idx_attempts_material ON attempts(material_id);
CREATE INDEX idx_attempt_items_attempt ON attempt_items(attempt_id);
"""


def _tables(conn):
    return {
        r["name"]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }


def _indexes(conn):
    return {
        r["name"]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )
    }


def _make_legacy_v2_db(tmp_path):
    """A realistic user_version=2 database: legacy cloze tables WITH rows,
    kept tables WITH rows — the exact world an upgrading user has."""
    from app import db

    conn = db.connect(tmp_path / "legacy.db")
    conn.executescript(LEGACY_SCHEMA)
    # Kept tables as they existed at v2 (CREATE IF NOT EXISTS no-ops on
    # the legacy tables this script may still mention).
    conn.executescript(db.SCHEMA)
    conn.executescript(
        """
        INSERT INTO materials(id,name,source_type,transcript,transcript_source,
          words_json,sentences_json,created_at,updated_at)
        VALUES('m1','Legacy talk','upload','hello world','asr',
          '[]','[]','2026-01-01','2026-01-01');
        INSERT INTO question_sets(id,material_id,mode,blank_count,params_json,created_at)
        VALUES('s1','m1','llm',10,'{}','2026-01-01');
        INSERT INTO blanks(id,set_id,position,answer,word_start,word_end)
        VALUES('b1','s1',0,'castle',0,1);
        INSERT INTO attempts(id,set_id,material_id,mode,started_at,total)
        VALUES('a1','s1','m1','llm','2026-01-01',10);
        INSERT INTO attempt_items(attempt_id,blank_id,user_text,correct,expected)
        VALUES('a1','b1','castel',0,'castle');
        INSERT INTO settings(key,value_json) VALUES('asr','{"n":3}');
        INSERT INTO translations(hash,src,dst,created_at)
        VALUES('h1','hello','你好','2026-01-01');
        INSERT INTO batches(id,name,total,created_at,updated_at)
        VALUES('bt1','batch',1,'2026-01-01','2026-01-01');
        INSERT INTO jobs(id,state,created_at,updated_at,batch_id)
        VALUES('j1','done','2026-01-01','2026-01-01','bt1');
        INSERT INTO papers(id,material_id,spec_json,paper_json,generation_json,created_at)
        VALUES('p1','m1','[]','{"title":"legacy paper"}','[]','2026-01-01');
        INSERT INTO paper_attempts(id,paper_id,material_id,created_at)
        VALUES('pa1','p1','m1','2026-01-01');
        INSERT INTO paper_attempt_items(attempt_id,item_number,item_type,user_answer,correct,expected)
        VALUES('pa1',1,'completion','castle',1,'castle');
        INSERT INTO material_translations(material_id,sentence_index,src,dst,created_at)
        VALUES('m1',0,'hello','你好','2026-01-01');
        INSERT INTO llm_cache(cache_key,task,model,response_json,created_at)
        VALUES('k1','scene','gpt','{}','2026-01-01');
        """
    )
    conn.execute("PRAGMA user_version=2")
    conn.commit()
    return conn


def test_fresh_db_creates_only_new_world_tables(tmp_path):
    from app import db

    conn = db.connect(tmp_path / "fresh.db")
    try:
        db.init_db(conn)
        tables = {t for t in _tables(conn) if not t.startswith("sqlite_")}
        assert tables == KEPT_TABLES
        for idx in LEGACY_INDEXES:
            assert idx not in _indexes(conn)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
    finally:
        conn.close()


def test_init_migrates_legacy_v2_db(tmp_path):
    """The critical migration (plan Review Focus #5): a v2 database with
    cloze tables full of rows → init drops the legacy tables, keeps every
    kept table's data, stamps user_version=3, and does not raise."""
    from app import db

    conn = _make_legacy_v2_db(tmp_path)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
        db.init_db(conn)  # must not raise

        tables = {t for t in _tables(conn) if not t.startswith("sqlite_")}
        assert tables == KEPT_TABLES
        for idx in LEGACY_INDEXES:
            assert idx not in _indexes(conn)

        # Kept-table data survived untouched.
        m = conn.execute(
            "SELECT name, transcript FROM materials WHERE id='m1'"
        ).fetchone()
        assert m["name"] == "Legacy talk" and m["transcript"] == "hello world"
        assert db.get_setting(conn, "asr") == {"n": 3}
        assert conn.execute(
            "SELECT dst FROM translations WHERE hash='h1'"
        ).fetchone()["dst"] == "你好"
        assert conn.execute(
            "SELECT state FROM jobs WHERE id='j1'"
        ).fetchone()["state"] == "done"
        assert conn.execute(
            "SELECT paper_json FROM papers WHERE id='p1'"
        ).fetchone()["paper_json"] == '{"title":"legacy paper"}'
        assert conn.execute(
            "SELECT expected FROM paper_attempt_items"
            " WHERE attempt_id='pa1' AND item_number=1"
        ).fetchone()["expected"] == "castle"
        assert conn.execute(
            "SELECT dst FROM material_translations"
            " WHERE material_id='m1' AND sentence_index=0"
        ).fetchone()["dst"] == "你好"
        assert conn.execute(
            "SELECT task FROM llm_cache WHERE cache_key='k1'"
        ).fetchone()["task"] == "scene"

        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
    finally:
        conn.close()


def test_init_migrates_legacy_v2_db_twice_is_idempotent(tmp_path):
    """Re-running init on an already-migrated database is a no-op."""
    from app import db

    conn = _make_legacy_v2_db(tmp_path)
    try:
        db.init_db(conn)
        db.init_db(conn)
        tables = {t for t in _tables(conn) if not t.startswith("sqlite_")}
        assert tables == KEPT_TABLES
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 3
        assert db.get_setting(conn, "asr") == {"n": 3}
    finally:
        conn.close()


def test_jobs_has_batch_columns(tmp_db):
    cols = {r["name"] for r in tmp_db.execute("PRAGMA table_info(jobs)")}
    assert {"batch_id", "file_name", "position"} <= cols


def test_wal_mode_and_row_factory(tmp_path):
    from app import db

    conn = db.connect(tmp_path / "wal.db")
    try:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert str(mode).lower() == "wal"
        row = conn.execute("SELECT 1 AS one").fetchone()
        assert row["one"] == 1  # sqlite3.Row access
    finally:
        conn.close()


def test_foreign_keys_enabled(tmp_db):
    fk = tmp_db.execute("PRAGMA foreign_keys").fetchone()[0]
    assert fk == 1


def test_settings_roundtrip(tmp_db):
    from app import db

    assert db.get_setting(tmp_db, "missing") is None
    db.set_setting(tmp_db, "asr", {"engine": "whisper", "n": 3})
    assert db.get_setting(tmp_db, "asr") == {"engine": "whisper", "n": 3}
    db.set_setting(tmp_db, "asr", {"engine": "parakeet"})
    assert db.get_setting(tmp_db, "asr") == {"engine": "parakeet"}
    db.set_setting(tmp_db, "gen", 15)
    assert db.get_setting(tmp_db, "gen") == 15


def test_get_setting_concurrent_same_sql_no_errors(tmp_path):
    # The settings-500 bug: concurrent identical-SQL reads on one shared
    # connection corrupt the cached statement. 8 threads x 500 iterations.
    import threading

    from app import db as db_mod

    conn = db_mod.connect(tmp_path / "stress.db")
    try:
        db_mod.init_db(conn)
        db_mod.set_setting(conn, "llm", {"provider": "zhipu"})
        errors: list[Exception] = []

        def hammer():
            for _ in range(500):
                try:
                    value = db_mod.get_setting(conn, "llm")
                    assert value is not None
                except Exception as exc:  # noqa: BLE001 - collect every failure kind
                    errors.append(exc)

        threads = [threading.Thread(target=hammer) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
    finally:
        conn.close()
