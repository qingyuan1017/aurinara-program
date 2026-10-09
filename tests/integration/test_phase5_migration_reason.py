"""Migration 0012 split-backfill preserves the alignment-reasons invariant (Finding 4).

Design 2.3 states ``alignment_reasons`` is empty iff ``state == "aligned"``. A legacy
single-plan row that was already *misaligned* at migration time must therefore split into
per-domain rows that carry a non-empty reason, not ``[]``. This test seeds a pre-0012
(revision 0011) legacy misaligned SDTM plan spanning two domains, runs the real ``0012``
upgrade through Alembic (migrations applied from the recorded head, not metadata.create_all),
and asserts every emitted per-domain row is ``misaligned`` with a non-empty
``alignment_reasons``. It uses a dedicated, disposable database so it never touches the
shared ``clinical_test`` schema other integration tests rely on.
"""

import json
import os
import subprocess
import sys
from uuid import uuid4

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
_DB_NAME = "clinical_mig_reason_test"
_DB_URL = f"postgresql+psycopg://clinical:clinical@localhost:55432/{_DB_NAME}"
_PSYCOPG_URL = f"postgresql://clinical:clinical@localhost:55432/{_DB_NAME}"

_WORKTREE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_LEGACY_PAYLOAD = {
    "schema_version": "1.0.0",
    "specification_revision": 1,
    "input_selection_revision": 1,
    "nodes": [
        {"node_type": "raw_read", "id": "read", "raw_dataset_code": "DEMOG"},
        {
            "node_type": "derive",
            "id": "derive_dm",
            "target_domain": "DM",
            "assignments": {"USUBJID": {"kind": "column", "dataset": "DEMOG", "column": "SUBJID"}},
        },
        {"node_type": "domain_write", "id": "write_dm", "domain": "DM"},
        {
            "node_type": "derive",
            "id": "derive_lb",
            "target_domain": "LB",
            "assignments": {"USUBJID": {"kind": "column", "dataset": "DEMOG", "column": "SUBJID"}},
        },
        {"node_type": "domain_write", "id": "write_lb", "domain": "LB"},
    ],
    "edges": [
        {"source_node": "read", "target_node": "derive_dm"},
        {"source_node": "derive_dm", "target_node": "write_dm"},
        {"source_node": "read", "target_node": "derive_lb"},
        {"source_node": "derive_lb", "target_node": "write_lb"},
    ],
}


def _alembic(target: str) -> None:
    env = {**os.environ, "DATABASE_URL": _DB_URL}
    completed = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", target]
        if target != "down"
        else [sys.executable, "-m", "alembic", "downgrade", "-1"],
        cwd=_WORKTREE,
        env=env,
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


def test_split_backfill_sets_reason_for_legacy_misaligned_rows(migration_db) -> None:
    # Bring the dedicated DB to the pre-split head.
    _alembic("20261008_0011")

    study_id = uuid4()
    sdtm_id = uuid4()
    with psycopg.connect(_PSYCOPG_URL, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO studies (id, revision, code, name, status, created_by, "
            "created_at, updated_at) VALUES (%s, 1, 'MIG-01', 'Mig', 'active', 'tester', "
            "now(), now())",
            (study_id,),
        )
        conn.execute(
            "INSERT INTO sdtm_workbenches (id, revision, study_id, code, name, status, "
            "created_at, updated_at) VALUES (%s, 1, %s, 'SDTM', 'SDTM', 'draft', now(), now())",
            (sdtm_id, study_id),
        )
        conn.execute(
            "INSERT INTO sdtm_specification_revisions (id, aggregate_id, study_id, revision, "
            "schema_version, payload, fingerprint, created_by, created_at) VALUES "
            "(%s, %s, %s, 1, '1.0.0', %s, %s, 'tester', now())",
            (uuid4(), sdtm_id, study_id, json.dumps({"domains": []}), "f" * 64),
        )
        # A legacy, already-misaligned single plan spanning DM and LB.
        conn.execute(
            "INSERT INTO sdtm_derivation_plan_revisions (id, aggregate_id, study_id, revision, "
            "schema_version, specification_revision, input_selection_revision, state, payload, "
            "fingerprint, created_by, created_at) VALUES "
            "(%s, %s, %s, 1, '1.0.0', 1, 1, 'misaligned', %s, %s, 'tester', now())",
            (uuid4(), sdtm_id, study_id, json.dumps(_LEGACY_PAYLOAD), "a" * 64),
        )

    # Run the real split-backfill migration.
    _alembic("20261009_0012")

    with psycopg.connect(_PSYCOPG_URL) as conn:
        rows = conn.execute(
            "SELECT domain_code, state, alignment_reasons FROM "
            "sdtm_derivation_plan_revisions WHERE aggregate_id = %s ORDER BY domain_code",
            (sdtm_id,),
        ).fetchall()

    assert {row[0] for row in rows} == {"DM", "LB"}
    for _code, state, reasons in rows:
        assert state == "misaligned"
        # Invariant: a misaligned row must carry a non-empty reason, never [].
        assert reasons, "misaligned split rows must carry a non-empty alignment_reasons"
