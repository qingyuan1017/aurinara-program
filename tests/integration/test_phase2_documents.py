"""PostgreSQL and immutable-storage Phase 2 Documents workflows."""

import io
import os
from collections.abc import AsyncIterator
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from reportlab.pdfgen.canvas import Canvas
from sqlalchemy import text

from app.artifacts.builds import resolve_build_input
from app.catalog_seed import seed
from app.common.canonical import fingerprint
from app.config import Settings
from app.database import create_database_engine, create_session_factory
from app.documents.rendering import normalized_docx_text, normalized_pdf_text
from app.execution.jobs import JobService
from app.main import create_app
from tests.integration.test_phase1_core import MemoryStorage, TestTokenVerifier
from workers.job_worker import _process_job

pytestmark = pytest.mark.skipif(
    os.getenv("AURINARA_INTEGRATION") != "1",
    reason="set AURINARA_INTEGRATION=1 with the Compose PostgreSQL service running",
)


@pytest.fixture
async def phase2_client() -> AsyncIterator[AsyncClient]:
    settings = Settings(_env_file=None, app_env="test")
    engine = create_database_engine(settings)
    factory = create_session_factory(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE protocol_evidence, protocol_usdm_documents, document_contents, "
                "document_dependency_selections, documents, integration_delivery_attempts, "
                "integration_subscriptions, integration_secret_versions, external_identifiers, "
                "integrations, reconciliation_runs, validation_runs, source_files, artifacts, "
                "jobs, idempotency_records, outbox_events, study_memberships, studies CASCADE"
            )
        )
    storage = MemoryStorage()
    with factory() as session:
        seed(session, storage)
    app = create_app(
        settings=settings,
        session_factory=factory,
        object_storage=storage,
        token_verifier=TestTokenVerifier(),
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield client
    engine.dispose()


def _pdf() -> bytes:
    output = io.BytesIO()
    canvas = Canvas(output, pagesize=(612, 792), invariant=1)
    canvas.drawString(72, 720, "Synthetic protocol objective and endpoint evidence")
    canvas.save()
    return output.getvalue()


async def _run_build(client: AsyncClient, build_id: str) -> dict[str, object]:
    application = client._transport.app  # type: ignore[attr-defined]
    factory = application.state.session_factory
    with factory.begin() as session:
        job = JobService().claim(session, worker_id="phase2-worker", lease_seconds=60)
        assert job is not None
    _process_job(factory, application.state.module_registry, application.state.object_storage, job)
    response = await client.get(
        f"/api/v1/artifact-builds/{build_id}", headers={"Authorization": "Bearer test-token"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "succeeded", response.text
    return response.json()


@pytest.mark.anyio
async def test_protocol_sap_and_quality_workbook_workflow(phase2_client: AsyncClient) -> None:
    client = phase2_client
    headers = {"Authorization": "Bearer test-token"}
    study = await client.post(
        "/api/v1/studies", headers=headers, json={"code": "DOC-001", "name": "Documents"}
    )
    study_id = study.json()["id"]
    upload = await client.post(
        f"/api/v1/studies/{study_id}/source-files",
        headers=headers,
        files={"file": ("protocol.pdf", _pdf(), "application/pdf")},
    )
    assert upload.status_code == 201, upload.text
    protocol = await client.post(
        f"/api/v1/studies/{study_id}/documents",
        headers=headers,
        json={
            "document_code": "PROTO-001",
            "name": "Synthetic Protocol",
            "document_type": "protocol",
            "source_pdf_file_id": upload.json()["id"],
        },
    )
    assert protocol.status_code == 201, protocol.text
    protocol_id = protocol.json()["id"]
    dependencies = await client.put(
        f"/api/v1/documents/{protocol_id}/dependencies",
        headers={**headers, "If-Match": protocol.headers["etag"]},
        json={
            "templates": [
                {
                    "purpose": "protocol_summary_docx",
                    "artifact_type": "protocol_summary_docx",
                    "template_version_id": "30000000-0000-0000-0000-000000000003",
                },
                {
                    "purpose": "protocol_summary_pdf",
                    "artifact_type": "protocol_summary_pdf",
                    "template_version_id": "30000000-0000-0000-0000-000000000003",
                },
            ]
        },
    )
    assert dependencies.status_code == 200, dependencies.text
    protocol_content = await client.put(
        f"/api/v1/documents/{protocol_id}/content",
        headers={**headers, "If-Match": dependencies.headers["etag"]},
        json={
            "document_type": "protocol",
            "title": "Synthetic Protocol",
            "version": "1",
            "sections": [
                {
                    "section_id": "overview",
                    "heading": "Study Overview",
                    "paragraphs": ["A manually authored synthetic study."],
                }
            ],
        },
    )
    assert protocol_content.status_code == 200, protocol_content.text
    usdm_payload = {
        "usdm_version": "4.0",
        "study_version": "1",
        "entities": [
            {"id": "STUDY1", "entity_type": "study", "name": "Synthetic Study"},
            {"id": "OBJ1", "entity_type": "objective", "name": "Primary objective"},
            {"id": "END1", "entity_type": "endpoint", "name": "Primary endpoint"},
        ],
        "relationships": [
            {
                "relationship_type": "measured_by",
                "source_entity_id": "OBJ1",
                "target_entity_id": "END1",
            }
        ],
    }
    usdm = await client.put(
        f"/api/v1/documents/{protocol_id}/usdm",
        headers={**headers, "If-Match": protocol_content.headers["etag"]},
        json=usdm_payload,
    )
    assert usdm.status_code == 200, usdm.text
    evidence = await client.post(
        f"/api/v1/documents/{protocol_id}/evidence",
        headers={**headers, "If-Match": usdm.headers["etag"]},
        json={
            "source_pdf_file_id": upload.json()["id"],
            "page_number": 1,
            "region": {
                "coordinate_system": "pdf_points_top_left",
                "page_width": 612,
                "page_height": 792,
                "rectangle": [60, 55, 360, 30],
            },
            "excerpt": "Synthetic protocol objective and endpoint evidence",
            "linked_usdm_entity_ids": ["OBJ1", "END1"],
            "status": "resolved",
        },
    )
    assert evidence.status_code == 201, evidence.text
    protocol_validation = await client.post(
        f"/api/v1/documents/{protocol_id}/validate", headers=headers
    )
    assert protocol_validation.status_code == 202, protocol_validation.text
    assert protocol_validation.json()["status"] == "succeeded"

    application = client._transport.app  # type: ignore[attr-defined]
    factory = application.state.session_factory
    artifact_types = (
        "protocol_usdm",
        "protocol_summary_docx",
        "protocol_summary_pdf",
        "protocol_annotated_evidence",
        "protocol_evidence_manifest_json",
    )
    with factory() as session:
        _, _, resolved = resolve_build_input(
            session,
            application.state.module_registry,
            study_id=UUID(study_id),
            owner_type="document",
            owner_id=UUID(protocol_id),
            artifact_types=artifact_types,
            options={},
        )
    build = await client.post(
        f"/api/v1/documents/{protocol_id}/artifacts",
        headers={**headers, "Idempotency-Key": "protocol-artifacts-1"},
        json={
            "artifact_types": artifact_types,
            "expected_input_fingerprint": fingerprint(resolved),
        },
    )
    assert build.status_code == 202, build.text
    protocol_build = await _run_build(client, build.json()["id"])
    assert len(protocol_build["result_artifact_ids"]) == len(artifact_types)

    sap = await client.post(
        f"/api/v1/studies/{study_id}/documents",
        headers=headers,
        json={
            "document_code": "SAP-001",
            "name": "Synthetic SAP",
            "document_type": "statistical_analysis_plan",
            "related_document_ids": [protocol_id],
        },
    )
    sap_dependencies = await client.put(
        f"/api/v1/documents/{sap.json()['id']}/dependencies",
        headers={**headers, "If-Match": sap.headers["etag"]},
        json={
            "templates": [
                {
                    "purpose": "statistical_analysis_plan_docx",
                    "artifact_type": "statistical_analysis_plan_docx",
                    "template_version_id": "30000000-0000-0000-0000-000000000003",
                },
                {
                    "purpose": "statistical_analysis_plan_pdf",
                    "artifact_type": "statistical_analysis_plan_pdf",
                    "template_version_id": "30000000-0000-0000-0000-000000000003",
                },
            ]
        },
    )
    assert sap_dependencies.status_code == 200, sap_dependencies.text
    context = await client.get(
        f"/api/v1/documents/{sap.json()['id']}/protocol-context", headers=headers
    )
    assert {item["usdm_entity_id"] for item in context.json()["entities"]} == {"OBJ1", "END1"}
    sap_content = await client.put(
        f"/api/v1/documents/{sap.json()['id']}/content",
        headers={**headers, "If-Match": sap_dependencies.headers["etag"]},
        json={
            "document_type": "statistical_analysis_plan",
            "title": "Synthetic SAP",
            "version": "1",
            "protocol_alignment": [
                {
                    "id": "AL1",
                    "name": "Alignment",
                    "description": "Manual link",
                    "protocol_entity_ids": ["OBJ1"],
                }
            ],
            "objectives": [{"id": "O1", "name": "Objective", "description": "Text"}],
            "endpoints": [{"id": "E1", "name": "Endpoint", "description": "Text"}],
            "estimands": [
                {
                    "id": "EST1",
                    "name": "Estimand",
                    "description": "Text",
                    "population_id": "POP1",
                    "treatment_condition": "A versus B",
                    "variable": "Change",
                    "intercurrent_event_strategy": "Treatment policy",
                    "summary_measure": "Difference",
                    "protocol_entity_ids": ["END1"],
                }
            ],
            "populations": [{"id": "POP1", "name": "ITT", "description": "Text"}],
            "methods": [{"id": "M1", "name": "ANCOVA", "description": "Text"}],
            "missing_data": [{"id": "MD1", "name": "Missing", "description": "Text"}],
            "output_requirements": [{"id": "OUT1", "name": "Table", "description": "Text"}],
            "qc_items": [{"id": "QC1", "name": "QC", "description": "Text"}],
            "narrative_sections": [
                {"section_id": "methods", "heading": "Methods", "paragraphs": ["Text"]}
            ],
        },
    )
    assert sap_content.status_code == 200, sap_content.text
    sap_validation = await client.post(
        f"/api/v1/documents/{sap.json()['id']}/validate", headers=headers
    )
    assert sap_validation.json()["status"] == "succeeded", sap_validation.text
    sap_artifact_types = (
        "statistical_analysis_plan_docx",
        "statistical_analysis_plan_pdf",
    )
    with factory() as session:
        _, _, sap_resolved = resolve_build_input(
            session,
            application.state.module_registry,
            study_id=UUID(study_id),
            owner_type="document",
            owner_id=UUID(sap.json()["id"]),
            artifact_types=sap_artifact_types,
            options={},
        )
    sap_build_response = await client.post(
        f"/api/v1/documents/{sap.json()['id']}/artifacts",
        headers={**headers, "Idempotency-Key": "sap-artifacts-1"},
        json={
            "artifact_types": sap_artifact_types,
            "expected_input_fingerprint": fingerprint(sap_resolved),
        },
    )
    assert sap_build_response.status_code == 202, sap_build_response.text
    sap_build = await _run_build(client, sap_build_response.json()["id"])
    docx_download = await client.get(
        f"/api/v1/artifacts/{sap_build['result_artifact_ids'][0]}/download", headers=headers
    )
    pdf_download = await client.get(
        f"/api/v1/artifacts/{sap_build['result_artifact_ids'][1]}/download", headers=headers
    )
    assert "Synthetic SAP" in " ".join(normalized_docx_text(docx_download.content))
    assert "Synthetic SAP" in " ".join(normalized_pdf_text(pdf_download.content))

    actions = await client.post(
        f"/api/v1/studies/{study_id}/documents",
        headers=headers,
        json={
            "document_code": "ACT-001",
            "name": "Actions",
            "document_type": "actions_report",
        },
    )
    action_dependencies = await client.put(
        f"/api/v1/documents/{actions.json()['id']}/dependencies",
        headers={**headers, "If-Match": actions.headers["etag"]},
        json={
            "templates": [
                {
                    "purpose": "actions_report_xlsx",
                    "artifact_type": "actions_report_xlsx",
                    "template_version_id": "30000000-0000-0000-0000-000000000003",
                }
            ]
        },
    )
    assert action_dependencies.status_code == 200, action_dependencies.text
    action_content = await client.put(
        f"/api/v1/documents/{actions.json()['id']}/content",
        headers={**headers, "If-Match": action_dependencies.headers["etag"]},
        json={
            "document_type": "actions_report",
            "title": "Actions",
            "rows": [
                {
                    "row_id": "ACT-1",
                    "description": "Review synthetic evidence",
                    "category": "quality",
                    "status": "open",
                    "owner": "Data Management",
                    "action_type": "review",
                }
            ],
        },
    )
    assert action_content.status_code == 200, action_content.text
    action_validation = await client.post(
        f"/api/v1/documents/{actions.json()['id']}/validate", headers=headers
    )
    assert action_validation.json()["status"] == "succeeded"
    with factory() as session:
        _, _, action_resolved = resolve_build_input(
            session,
            application.state.module_registry,
            study_id=UUID(study_id),
            owner_type="document",
            owner_id=UUID(actions.json()["id"]),
            artifact_types=("actions_report_xlsx",),
            options={},
        )
    action_build_response = await client.post(
        f"/api/v1/documents/{actions.json()['id']}/artifacts",
        headers={**headers, "Idempotency-Key": "action-artifacts-1"},
        json={
            "artifact_types": ["actions_report_xlsx"],
            "expected_input_fingerprint": fingerprint(action_resolved),
        },
    )
    action_build = await _run_build(client, action_build_response.json()["id"])
    action_download = await client.get(
        f"/api/v1/artifacts/{action_build['result_artifact_ids'][0]}/download", headers=headers
    )
    assert action_download.content.startswith(b"PK")

    changed_usdm = await client.put(
        f"/api/v1/documents/{protocol_id}/usdm",
        headers={**headers, "If-Match": evidence.headers["etag"]},
        json={**usdm_payload, "study_version": "2"},
    )
    assert changed_usdm.status_code == 200, changed_usdm.text
    retained_protocol_artifact = await client.get(
        f"/api/v1/artifacts/{protocol_build['result_artifact_ids'][0]}", headers=headers
    )
    assert retained_protocol_artifact.json()["status"] == "stale"
    stale_sap_artifact = await client.get(
        f"/api/v1/artifacts/{sap_build['result_artifact_ids'][0]}", headers=headers
    )
    assert stale_sap_artifact.json()["status"] == "stale"


@pytest.mark.anyio
async def test_every_operational_document_type_validates_and_generates(
    phase2_client: AsyncClient,
) -> None:
    client = phase2_client
    headers = {"Authorization": "Bearer test-token"}
    study = await client.post(
        "/api/v1/studies",
        headers=headers,
        json={"code": "DOC-OPS", "name": "Operational Documents"},
    )
    study_id = study.json()["id"]
    narratives = {
        "protocol_amendment_summary_of_change": (
            "protocol_amendment_summary_of_change_pdf",
            {"amendment_number": "1"},
        ),
        "protocol_deviation_document": ("protocol_deviation_document_pdf", {}),
        "aggregate_study_risk_profile": ("aggregate_study_risk_profile_pdf", {}),
        "data_management_plan": ("data_management_plan_pdf", {}),
        "centralized_monitoring_platform_setup_documentation": (
            "centralized_monitoring_platform_setup_documentation_pdf",
            {},
        ),
        "aggregate_study_brief": ("aggregate_study_brief_pdf", {}),
        "study_data_summary": ("study_data_summary_pdf", {}),
    }
    workbooks = {
        "protocol_deviation_dataset": ("protocol_deviation_dataset_xlsx", {}),
        "standard_quality_dashboard_qe_details": (
            "standard_quality_dashboard_qe_details_xlsx",
            {},
        ),
        "standard_quality_dashboard_sqe_audit_capa_details": (
            "standard_quality_dashboard_sqe_audit_capa_details_xlsx",
            {},
        ),
        "standard_quality_dashboard_audit_observation_detail": (
            "standard_quality_dashboard_audit_observation_detail_xlsx",
            {"observation": "Synthetic observation"},
        ),
        "signals_report": ("signals_report_xlsx", {"signal_type": "quality"}),
        "actions_report": ("actions_report_xlsx", {"action_type": "review"}),
    }
    application = client._transport.app  # type: ignore[attr-defined]
    factory = application.state.session_factory

    for index, (document_type, (artifact_type, extra)) in enumerate(
        {**narratives, **workbooks}.items(), start=1
    ):
        created = await client.post(
            f"/api/v1/studies/{study_id}/documents",
            headers=headers,
            json={
                "document_code": f"DOC-{index:02d}",
                "name": document_type,
                "document_type": document_type,
            },
        )
        assert created.status_code == 201, created.text
        document_id = created.json()["id"]
        dependencies = await client.put(
            f"/api/v1/documents/{document_id}/dependencies",
            headers={**headers, "If-Match": created.headers["etag"]},
            json={
                "templates": [
                    {
                        "purpose": artifact_type,
                        "artifact_type": artifact_type,
                        "template_version_id": "30000000-0000-0000-0000-000000000003",
                    }
                ]
            },
        )
        assert dependencies.status_code == 200, dependencies.text
        if document_type in narratives:
            payload = {
                "document_type": document_type,
                "title": f"Synthetic {document_type}",
                "version": "1",
                "sections": [
                    {
                        "section_id": "body",
                        "heading": "Authored Content",
                        "paragraphs": ["Synthetic manually maintained content."],
                    }
                ],
                **extra,
            }
        else:
            payload = {
                "document_type": document_type,
                "title": f"Synthetic {document_type}",
                "rows": [
                    {
                        "row_id": f"ROW-{index}",
                        "description": "Synthetic manually maintained row",
                        "category": "quality",
                        "status": "open",
                        "owner": "Study Team",
                        **extra,
                    }
                ],
            }
        if document_type == "actions_report":
            import_headers = {
                **headers,
                "If-Match": dependencies.headers["etag"],
                "Idempotency-Key": "actions-import",
            }
            saved = await client.post(
                f"/api/v1/documents/{document_id}/content/import",
                headers=import_headers,
                json=payload,
            )
            replay = await client.post(
                f"/api/v1/documents/{document_id}/content/import",
                headers=import_headers,
                json=payload,
            )
            assert replay.json()["id"] == saved.json()["id"]
        else:
            saved = await client.put(
                f"/api/v1/documents/{document_id}/content",
                headers={**headers, "If-Match": dependencies.headers["etag"]},
                json=payload,
            )
        assert saved.status_code == 200, saved.text
        validation = await client.post(f"/api/v1/documents/{document_id}/validate", headers=headers)
        assert validation.json()["status"] == "succeeded", validation.text
        with factory() as session:
            _, _, resolved = resolve_build_input(
                session,
                application.state.module_registry,
                study_id=UUID(study_id),
                owner_type="document",
                owner_id=UUID(document_id),
                artifact_types=(artifact_type,),
                options={},
            )
        build = await client.post(
            f"/api/v1/documents/{document_id}/artifacts",
            headers={**headers, "Idempotency-Key": f"ops-{index}"},
            json={
                "artifact_types": [artifact_type],
                "expected_input_fingerprint": fingerprint(resolved),
            },
        )
        assert build.status_code == 202, build.text
        completed = await _run_build(client, build.json()["id"])
        downloaded = await client.get(
            f"/api/v1/artifacts/{completed['result_artifact_ids'][0]}/download",
            headers=headers,
        )
        assert downloaded.status_code == 200
        if artifact_type.endswith("_pdf"):
            assert downloaded.content.startswith(b"%PDF")
        else:
            assert downloaded.content.startswith(b"PK")
