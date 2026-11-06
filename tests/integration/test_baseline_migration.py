"""The pre-production baseline creates, drops, and recreates the current schema."""

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from sqlalchemy import create_engine, inspect

from app import model_registry  # noqa: F401
from app.database import Base

pytestmark = pytest.mark.skipif(
    os.getenv("AURINARA_INTEGRATION") != "1",
    reason="set AURINARA_INTEGRATION=1 with the Compose PostgreSQL service running",
)

_ADMIN_URL = os.getenv(
    "AURINARA_MIGRATION_TEST_ADMIN_URL",
    "postgresql://clinical:clinical@localhost:55432/postgres",
)
_DATABASE = "aurinara_baseline_migration_test"
_DATABASE_URL = os.getenv(
    "AURINARA_MIGRATION_TEST_DATABASE_URL",
    f"postgresql+psycopg://clinical:clinical@localhost:55432/{_DATABASE}",
)
_ROOT = Path(__file__).resolve().parents[2]


def _alembic(*arguments: str) -> str:
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=_ROOT,
        env={
            **os.environ,
            "DATABASE_URL": _DATABASE_URL,
            "PLATFORM_AUTHORIZATION_MODE": "disabled",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout


@pytest.fixture
def empty_baseline_database() -> Iterator[None]:
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


def _tables() -> set[str]:
    engine = create_engine(_DATABASE_URL)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def _schema_evidence() -> tuple[set[str], set[str]]:
    engine = create_engine(_DATABASE_URL)
    try:
        inspector = inspect(engine)
        checks = {
            str(item["name"])
            for table in ("artifacts", "source_files")
            for item in inspector.get_check_constraints(table)
        }
        indexes = {
            str(item["name"])
            for table in ("artifacts", "source_files")
            for item in inspector.get_indexes(table)
        }
        return checks, indexes
    finally:
        engine.dispose()


def test_baseline_migration_round_trip(empty_baseline_database: None) -> None:
    _alembic("upgrade", "head")
    assert _tables() == {*Base.metadata.tables, "alembic_version"}
    _alembic("check")
    assert len(_alembic("heads").strip().splitlines()) == 1
    checks, indexes = _schema_evidence()
    assert "ck_artifacts_ck_artifacts_storage_locator" in checks
    assert "ck_artifacts_ck_artifacts_platform_reference" in checks
    assert "ck_source_files_ck_source_files_storage_locator" in checks
    assert "ck_source_files_ck_source_files_platform_reference" in checks
    assert "ix_artifacts_platform_object_id" in indexes
    assert "ix_source_files_platform_object_id" in indexes

    _alembic("downgrade", "base")
    assert _tables() == {"alembic_version"}

    _alembic("upgrade", "head")
    assert _tables() == {*Base.metadata.tables, "alembic_version"}
