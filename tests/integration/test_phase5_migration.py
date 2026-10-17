"""Phase 5 migration applies from empty, downgrades, and reapplies."""

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.artifacts.models import Artifact, SourceFile
from app.sdtm.models import (
    SdtmAcrfAnnotation,
    SdtmImportedDomainRevision,
    SdtmWorkbench,
)
from app.studies.models import Study
from app.validation.models import ValidationRun

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
    _alembic("upgrade", "20261015_0018")
    engine = create_engine(_DATABASE_URL)
    graph_artifact_id = uuid4()
    annotation_id = uuid4()
    imported_id = uuid4()
    with Session(engine) as session, session.begin():
        study = Study(code="MIG-SDTM", name="Migration SDTM", created_by="migration-test")
        session.add(study)
        session.flush()
        workbench = SdtmWorkbench(
            study_id=study.id,
            code="SDTM",
            name="SDTM",
            status="draft",
        )
        session.add(workbench)
        session.flush()
        source_artifact = Artifact(
            study_id=study.id,
            module_key="sdtm",
            artifact_type="source_pdf",
            owner_type="sdtm_workbench",
            owner_id=workbench.id,
            filename="crf.pdf",
            media_type="application/pdf",
            object_key="migration/crf.pdf",
            sha256="a" * 64,
            size=1,
            input_fingerprint="b" * 64,
            manifest={},
            generator_name="migration-test",
            generator_version="1.0.0",
            created_by="migration-test",
        )
        graph_artifact = Artifact(
            id=graph_artifact_id,
            study_id=study.id,
            module_key="sdtm",
            artifact_type="sdtm_dataset_xpt",
            owner_type="sdtm_workbench",
            owner_id=workbench.id,
            filename="old-dm.xpt",
            media_type="application/x-sas-xport",
            object_key="migration/old-dm.xpt",
            sha256="c" * 64,
            size=1,
            input_fingerprint="d" * 64,
            source_plan_type="sdtm_derivation_plan",
            source_plan_revision=1,
            manifest={"dataset": "DM"},
            generator_name="migration-test",
            generator_version="1.0.0",
            created_by="migration-test",
        )
        session.add_all((source_artifact, graph_artifact))
        session.flush()
        source_file = SourceFile(
            study_id=study.id,
            artifact_id=source_artifact.id,
            filename="dm.xpt",
            media_type="application/x-sas-xport",
            object_key="migration/dm.xpt",
            sha256="e" * 64,
            size=1,
            created_by="migration-test",
        )
        validation = ValidationRun(
            study_id=study.id,
            module_key="sdtm",
            owner_type="sdtm_workbench",
            owner_id=workbench.id,
            status="succeeded",
            validator_name="migration-test",
            validator_version="1.0.0",
            input_fingerprint="f" * 64,
            input_manifest={},
            issues=[],
            report_artifact_ids=[],
            created_by="migration-test",
        )
        imported_artifact = Artifact(
            study_id=study.id,
            module_key="sdtm",
            artifact_type="sdtm_dataset_xpt",
            owner_type="sdtm_workbench",
            owner_id=workbench.id,
            filename="dm.xpt",
            media_type="application/x-sas-xport",
            object_key="migration/dm.xpt",
            sha256="e" * 64,
            size=1,
            input_fingerprint="1" * 64,
            source_plan_type="sdtm_imported_domain",
            source_plan_revision=1,
            manifest={"dataset": "DM"},
            generator_name="migration-test",
            generator_version="1.0.0",
            created_by="migration-test",
        )
        session.add_all((source_file, validation, imported_artifact))
        session.flush()
        session.add_all(
            (
                SdtmAcrfAnnotation(
                    id=annotation_id,
                    sdtm_id=workbench.id,
                    study_id=study.id,
                    source_pdf_artifact_id=source_artifact.id,
                    page_number=1,
                    region={"x": 0, "y": 0, "width": 1, "height": 1},
                    links=[
                        {
                            "target_type": "derivation_plan_node",
                            "domain": "DM",
                            "plan_revision": 1,
                            "node_id": "read",
                        }
                    ],
                    status="open",
                    fingerprint="2" * 64,
                    created_by="migration-test",
                ),
                SdtmImportedDomainRevision(
                    id=imported_id,
                    aggregate_id=workbench.id,
                    study_id=study.id,
                    domain_code="DM",
                    revision=1,
                    specification_revision=1,
                    source_file_id=source_file.id,
                    artifact_id=imported_artifact.id,
                    validation_run_id=validation.id,
                    state="aligned",
                    alignment_reasons=[],
                    extracted_schema={"domain": "DM"},
                    issues=[],
                    fingerprint="3" * 64,
                    created_by="migration-test",
                ),
            )
        )
    engine.dispose()

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
    assert {
        "tlf_authoring_revisions",
        "submission_packages",
        "sdtm_domain_mapping_revisions",
        "sdtm_variable_mapping_revisions",
        "sdtm_code_workareas",
        "sdtm_code_revisions",
        "sdtm_output_selections",
    }.issubset(tables)
    assert "sdtm_derivation_plan_revisions" not in tables
    assert len(foreign_keys) == 3
    with psycopg.connect(_PSYCOPG_URL) as connection:
        artifact_status = connection.execute(
            "SELECT status FROM artifacts WHERE id = %s", (graph_artifact_id,)
        ).fetchone()
        annotation_state = connection.execute(
            "SELECT status, revision FROM sdtm_acrf_annotations WHERE id = %s",
            (annotation_id,),
        ).fetchone()
        imported_state = connection.execute(
            "SELECT state FROM sdtm_imported_domain_revisions WHERE id = %s", (imported_id,)
        ).fetchone()
    assert artifact_status == ("stale",)
    assert annotation_state == ("deleted", 2)
    assert imported_state == ("aligned",)

    _alembic("downgrade", "20261009_0012")
    with psycopg.connect(_PSYCOPG_URL) as connection:
        remaining = connection.execute(
            "SELECT to_regclass('public.submission_packages'), "
            "to_regclass('public.tlf_authoring_revisions')"
        ).fetchone()
    assert remaining == (None, None)
    _alembic("upgrade", "head")
