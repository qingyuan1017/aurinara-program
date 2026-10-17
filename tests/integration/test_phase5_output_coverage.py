"""Collective ADaM whole-Specification output-coverage gate.

SDTM coverage is enforced by its explicit Output Selection. This service-level test
retains the ADaM graph-plan coverage invariant and applies migrations through the shared
``clinical_test`` schema.
"""

import os

import pytest
from sqlalchemy import text

from app.adam.contracts import AdamSpecification
from app.adam.models import (
    AdamDependencySelection,
    AdamSpecificationRevision,
    AdamWorkbench,
)
from app.adam.service import AdamCapability
from app.common.canonical import fingerprint
from app.common.problems import ProblemException
from app.database import create_database_engine, create_session_factory
from app.studies.models import Study
from tests.conftest import make_test_settings

pytestmark = pytest.mark.skipif(
    os.getenv("AURINARA_INTEGRATION") != "1",
    reason="set AURINARA_INTEGRATION=1 with the Compose PostgreSQL service running",
)


def _adam_two_derived_datasets() -> AdamSpecification:
    def _dataset(
        code: str,
        dataset_id: str,
        key_variable_id: str,
        value_variable_id: str,
        output_node: str,
    ) -> dict[str, object]:
        return {
            "id": dataset_id,
            "code": code,
            "label": code,
            "dataset_class": "ANALYSIS",
            "structure": "One record per subject",
            "keys": ["USUBJID"],
            "sort_order": ["USUBJID"],
            "expected_output_name": f"{code.lower()}.xpt",
            "variables": [
                {
                    "id": key_variable_id,
                    "name": "USUBJID",
                    "label": "Unique Subject Identifier",
                    "data_type": "character",
                    "length": 40,
                    "role": "Identifier",
                    "origin": {"origin_type": "Assigned"},
                    "output_node_id": output_node,
                },
                {
                    "id": value_variable_id,
                    "name": "AVAL",
                    "label": "Analysis Value",
                    "data_type": "numeric",
                    "length": 8,
                    "role": "Qualifier",
                    "origin": {"origin_type": "Derived"},
                    "method_id": "MT.aval",
                    "output_node_id": output_node,
                },
            ],
        }

    return AdamSpecification.model_validate(
        {
            "datasets": [
                _dataset(
                    "ADSL",
                    "10000000-0000-0000-0000-000000000001",
                    "20000000-0000-0000-0000-000000000001",
                    "20000000-0000-0000-0000-000000000011",
                    "write_adsl",
                ),
                _dataset(
                    "ADLB",
                    "10000000-0000-0000-0000-000000000002",
                    "20000000-0000-0000-0000-000000000002",
                    "20000000-0000-0000-0000-000000000012",
                    "write_adlb",
                ),
            ],
            "methods": [
                {
                    "id": "MT.aval",
                    "name": "AVAL",
                    "description": "Manually authored method.",
                    "plan_node_ids": ["write_adsl", "write_adlb"],
                }
            ],
        }
    )


@pytest.fixture
def factory():
    settings = make_test_settings()
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE studies CASCADE"))
    yield session_factory
    engine.dispose()


def _study(session, code: str) -> Study:
    study = Study(code=code, name=code, created_by="tester")
    session.add(study)
    session.flush()
    return study


def test_adam_output_coverage_incomplete_for_never_authored_dataset(factory) -> None:
    handler = AdamCapability("adam", "adam_workbench", AdamWorkbench, AdamDependencySelection)
    with factory() as session:
        study = _study(session, "COV-ADAM")
        workbench = AdamWorkbench(study_id=study.id, code="ADAM", name="ADAM")
        session.add(workbench)
        session.flush()
        specification = _adam_two_derived_datasets()
        session.add(
            AdamSpecificationRevision(
                aggregate_id=workbench.id,
                study_id=study.id,
                revision=1,
                schema_version="1.0.0",
                payload=specification.model_dump(mode="json"),
                fingerprint=fingerprint(specification.model_dump(mode="json")),
                created_by="tester",
            )
        )
        session.commit()

        sentinel = object()
        with pytest.raises(ProblemException) as captured:
            handler.require_output_coverage(session, workbench.id, {"ADSL": sentinel})  # type: ignore[dict-item]
        assert captured.value.status_code == 409
        assert captured.value.code == "adam_output_coverage_incomplete"
        assert captured.value.issues[0]["missing_datasets"] == ["ADLB"]

        handler.require_output_coverage(
            session,
            workbench.id,
            {"ADSL": sentinel, "ADLB": sentinel},  # type: ignore[dict-item]
        )
