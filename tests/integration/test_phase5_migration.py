"""Phase 5 migration applies from empty, downgrades, and reapplies."""

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

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
_DATABASE = "clinical_phase5_migration_test"
_DATABASE_URL = f"postgresql+psycopg://clinical:clinical@localhost:55432/{_DATABASE}"
_PSYCOPG_URL = f"postgresql://clinical:clinical@localhost:55432/{_DATABASE}"
_ROOT = Path(__file__).resolve().parents[2]


def _alembic(*arguments: str) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=_ROOT,
        env={**os.environ, "DATABASE_URL": _DATABASE_URL},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


@pytest.fixture
def empty_phase5_database() -> Iterator[None]:
    with psycopg.connect(_ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{_DATABASE}"')
        admin.execute(f'CREATE DATABASE "{_DATABASE}"')
    try:
        yield
    finally:
        with psycopg.connect(_ADMIN_URL, autocommit=True) as admin:
            admin.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (_DATABASE,),
            )
            admin.execute(f'DROP DATABASE IF EXISTS "{_DATABASE}"')


def test_phase5_migration_round_trip(empty_phase5_database: None) -> None:
    _alembic("upgrade", "head")
    with psycopg.connect(_PSYCOPG_URL) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            ).fetchall()
        }
        foreign_keys = {
            row[0]
            for row in connection.execute(
                "SELECT constraint_name FROM information_schema.table_constraints "
                "WHERE table_schema = 'public' AND table_name = 'submission_packages' "
                "AND constraint_type = 'FOREIGN KEY'"
            ).fetchall()
        }
    assert {"tlf_authoring_revisions", "submission_packages"}.issubset(tables)
    assert len(foreign_keys) == 3

    _alembic("downgrade", "20261009_0012")
    with psycopg.connect(_PSYCOPG_URL) as connection:
        remaining = connection.execute(
            "SELECT to_regclass('public.submission_packages'), "
            "to_regclass('public.tlf_authoring_revisions')"
        ).fetchone()
    assert remaining == (None, None)
    _alembic("upgrade", "head")
