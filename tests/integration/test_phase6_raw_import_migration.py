"""The raw_dataset_imports migration applies up/down/up from an empty database.

Uses a dedicated, disposable database so it never touches the shared
``clinical_test`` schema other integration tests rely on.
"""

import os
import subprocess
import sys

import psycopg
import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("AURINARA_INTEGRATION") != "1",
    reason="set AURINARA_INTEGRATION=1 with the Compose PostgreSQL service running",
)

_ADMIN_URL = os.getenv(
    "AURINARA_MIGRATION_TEST_ADMIN_URL",
    "postgresql://clinical:clinical@localhost:55432/postgres",
)
_DB_NAME = "clinical_raw_import_mig_test"
_DB_URL = f"postgresql+psycopg://clinical:clinical@localhost:55432/{_DB_NAME}"
_PSYCOPG_URL = f"postgresql://clinical:clinical@localhost:55432/{_DB_NAME}"

_WORKTREE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _alembic(*arguments: str) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=_WORKTREE,
        env={**os.environ, "DATABASE_URL": _DB_URL},
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


@pytest.fixture
def migration_db():
    with psycopg.connect(_ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{_DB_NAME}"')
        admin.execute(f'CREATE DATABASE "{_DB_NAME}"')
    try:
        yield
    finally:
        with psycopg.connect(_ADMIN_URL, autocommit=True) as admin:
            admin.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (_DB_NAME,),
            )
            admin.execute(f'DROP DATABASE IF EXISTS "{_DB_NAME}"')


def _table_exists() -> bool:
    with psycopg.connect(_PSYCOPG_URL) as connection:
        row = connection.execute("SELECT to_regclass('public.raw_dataset_imports')").fetchone()
    assert row is not None
    return row[0] is not None


def test_raw_dataset_imports_migration_round_trip(migration_db) -> None:
    _alembic("upgrade", "head")
    assert _table_exists()

    with psycopg.connect(_PSYCOPG_URL) as connection:
        indexes = {
            row[0]
            for row in connection.execute(
                "SELECT indexname FROM pg_indexes WHERE tablename = 'raw_dataset_imports'"
            ).fetchall()
        }
    assert "ix_raw_dataset_imports_raw_id" in indexes
    assert "ix_raw_dataset_imports_study_id" in indexes

    # Downgrade to the parent of the migration under test. Later migrations may
    # be added after this test is written, so a relative single-step downgrade
    # would only remove the repository's newest revision.
    _alembic("downgrade", "20261009_0013")
    assert not _table_exists()

    _alembic("upgrade", "head")
    assert _table_exists()
