import sys
from pathlib import Path

import pytest

# Make the backend package importable as `app.*` regardless of cwd.
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


@pytest.fixture()
def tmp_db(tmp_path):
    """A fresh initialised database connection per test."""
    from app import db

    conn = db.connect(tmp_path / "test.db")
    db.init_db(conn)
    try:
        yield conn
    finally:
        conn.close()
