"""Task B1 tests: database schema and settings persistence."""


def test_init_db_creates_tables_and_version(tmp_db):
    tables = {
        r["name"]
        for r in tmp_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    expected = {
        "materials",
        "question_sets",
        "blanks",
        "attempts",
        "attempt_items",
        "settings",
        "translations",
        "jobs",
    }
    assert expected <= tables
    assert tmp_db.execute("PRAGMA user_version").fetchone()[0] == 1


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


def test_question_sets_has_stale_default_zero(tmp_db):
    cols = {
        r["name"]: r for r in tmp_db.execute("PRAGMA table_info(question_sets)")
    }
    assert "stale" in cols
    assert cols["stale"]["dflt_value"] == "0"
    # material row so the FK is satisfiable
    tmp_db.execute(
        "INSERT INTO materials(id,name,source_type,transcript,transcript_source,"
        "words_json,sentences_json,created_at,updated_at)"
        " VALUES('m1','t','upload','','asr','[]','[]','2026-01-01','2026-01-01')"
    )
    tmp_db.execute(
        "INSERT INTO question_sets(id,material_id,mode,blank_count,params_json,created_at)"
        " VALUES('s1','m1','llm',10,'{}','2026-01-01')"
    )
    row = tmp_db.execute("SELECT stale FROM question_sets WHERE id='s1'").fetchone()
    assert row["stale"] == 0


def test_settings_roundtrip(tmp_db):
    from app import db

    assert db.get_setting(tmp_db, "missing") is None
    db.set_setting(tmp_db, "asr", {"engine": "whisper", "n": 3})
    assert db.get_setting(tmp_db, "asr") == {"engine": "whisper", "n": 3}
    db.set_setting(tmp_db, "asr", {"engine": "parakeet"})
    assert db.get_setting(tmp_db, "asr") == {"engine": "parakeet"}
    db.set_setting(tmp_db, "gen", 15)
    assert db.get_setting(tmp_db, "gen") == 15
