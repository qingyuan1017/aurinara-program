"""The platform schema reconciliation repairs drift and remains reversible."""

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
_DATABASE = "clinical_platform_reconcile_mig_test"
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
def migration_db() -> Iterator[None]:
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


def _schema_state() -> tuple[set[str], set[str], set[str], set[str]]:
    with psycopg.connect(_PSYCOPG_URL) as connection:
        artifact_columns = {
            row[0]
            for row in connection.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'artifacts'"
            ).fetchall()
        }
        source_columns = {
            row[0]
            for row in connection.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'source_files'"
            ).fetchall()
        }
        unique_constraints = {
            row[0]
            for row in connection.execute(
                "SELECT constraint_name FROM information_schema.table_constraints "
                "WHERE table_schema = 'public' "
                "AND table_name IN ('artifacts', 'source_files') "
                "AND constraint_type = 'UNIQUE'"
            ).fetchall()
        }
        package_foreign_keys = {
            row[0]
            for row in connection.execute(
                "SELECT constraint_name FROM information_schema.table_constraints "
                "WHERE table_schema = 'public' AND table_name = 'submission_packages' "
                "AND constraint_type = 'FOREIGN KEY'"
            ).fetchall()
        }
    return artifact_columns, source_columns, unique_constraints, package_foreign_keys


def test_platform_schema_reconciliation_round_trip(migration_db: None) -> None:
    _alembic("upgrade", "20261010_0014")
    with psycopg.connect(_PSYCOPG_URL, autocommit=True) as connection:
        connection.execute(
            "ALTER TABLE submission_packages "
            "DROP CONSTRAINT IF EXISTS fk_submission_packages_zip_artifact_id_artifacts"
        )
        connection.execute(
            "ALTER TABLE submission_packages "
            "DROP CONSTRAINT IF EXISTS fk_submission_packages_report_artifact_id_artifacts"
        )

    _alembic("upgrade", "head")
    artifact_columns, source_columns, unique_constraints, package_foreign_keys = _schema_state()
    assert "platform_reference_id" in artifact_columns
    assert "platform_reference_id" in source_columns
    assert "uq_artifacts_platform_reference_id" in unique_constraints
    assert "uq_source_files_platform_reference_id" in unique_constraints
    assert "fk_submission_packages_zip_artifact_id_artifacts" in package_foreign_keys
    assert "fk_submission_packages_report_artifact_id_artifacts" in package_foreign_keys
    _alembic("check")

    # Target the parent of the reconciliation migration rather than whichever
    # unrelated revision currently happens to be the repository head.
    _alembic("downgrade", "20261010_0014")
    artifact_columns, source_columns, _, package_foreign_keys = _schema_state()
    assert "platform_reference_id" not in artifact_columns
    assert "platform_reference_id" not in source_columns
    assert "fk_submission_packages_zip_artifact_id_artifacts" in package_foreign_keys
    assert "fk_submission_packages_report_artifact_id_artifacts" in package_foreign_keys

    _alembic("upgrade", "head")
    _alembic("check")
