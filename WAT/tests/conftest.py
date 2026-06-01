import sqlite3
import pytest


@pytest.fixture
def tmp_db(tmp_path):
    """임시 SQLite 경로. 각 테스트 격리."""
    return str(tmp_path / "accounting_test.db")
