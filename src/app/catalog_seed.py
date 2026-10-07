"""Verify and register repository-pinned Phase 1 provider assets."""

import json
from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session

from app import model_registry as _model_registry  # noqa: F401 - populate FK metadata
from app.artifacts.storage import ObjectStorage, S3ObjectStorage
from app.common.asset_content import publish_verified_asset
from app.common.canonical import sha256_hex
from app.config import get_settings
from app.database import create_database_engine, create_session_factory
from app.standards.models import StandardProduct, StandardVersion
from app.templates.models import TemplateFamily, TemplateVersion
from app.terminology.models import TerminologyCodelist, TerminologyRelease, TerminologyTerm
from app.validation.models import ValidationRule, ValidationRulePack

ROOT = Path(__file__).resolve().parents[2]
MODULES = ["raw", "documents", "sdtm", "adam", "tlf"]


def _checksum(path: Path) -> str:
    if not path.is_file() or ROOT not in path.resolve().parents:
        raise RuntimeError(f"pinned catalog asset is unavailable: {path}")
    return sha256_hex(path.read_bytes())


def seed(session: Session, storage: ObjectStorage) -> None:
    """Idempotently seed exact assets after verifying repository bytes."""

    standard_path = ROOT / "schemas/platform/dependency-selection-1.0.0.json"
    terminology_path = ROOT / "terminology/platform/issue-severity-1.0.0.json"
    template_path = ROOT / "templates/platform/report-layout-1.0.0.json"
    document_template_path = ROOT / "templates/platform/document-layout-2.0.0.json"
    # Publish the four pinned JSON files unconditionally (before the DB-exists
    # guards) so seed() self-heals a DB-exists/object-missing state and stays an
    # idempotent content-addressed no-op.
    for pinned_path in (
        standard_path,
        terminology_path,
        template_path,
        document_template_path,
    ):
        publish_verified_asset(storage, pinned_path, _checksum(pinned_path), "application/json")

    product_id = UUID("10000000-0000-0000-0000-000000000001")
    standard_version_id = UUID("10000000-0000-0000-0000-000000000002")
    if session.get(StandardProduct, product_id) is None:
        session.add(
            StandardProduct(
                id=product_id,
                code="AURINARA_CONTRACTS",
                name="Aurinara Platform Contracts",
                provider="AURINARA",
                family="platform",
                product_type="foundational",
                scope="cross_domain",
            )
        )
    if session.get(StandardVersion, standard_version_id) is None:
        session.add(
            StandardVersion(
                id=standard_version_id,
                product_id=product_id,
                version="1.0.0",
                lifecycle="active",
                checksum=_checksum(standard_path),
                asset_path=str(standard_path.relative_to(ROOT)).replace("\\", "/"),
                provenance={"source": "repository", "license": "project"},
                applicable_modules=MODULES,
                purposes=["dependency_contract"],
                compatibility={"schema": "2020-12"},
            )
        )

    release_id = UUID("20000000-0000-0000-0000-000000000001")
    codelist_id = UUID("20000000-0000-0000-0000-000000000002")
    if session.get(TerminologyRelease, release_id) is None:
        session.add(
            TerminologyRelease(
                id=release_id,
                code="AURINARA_PLATFORM",
                version="1.0.0",
                provider="AURINARA",
                product="PLATFORM",
                lifecycle="active",
                checksum=_checksum(terminology_path),
                asset_path=str(terminology_path.relative_to(ROOT)).replace("\\", "/"),
                applicable_modules=MODULES,
                provenance={"source": "repository", "license": "project"},
            )
        )
        session.flush()
        session.add(
            TerminologyCodelist(
                id=codelist_id,
                release_id=release_id,
                code="ISSUE_SEVERITY",
                name="Validation Issue Severity",
                extensible=True,
            )
        )
        for index, item in enumerate(
            json.loads(terminology_path.read_text(encoding="utf-8"))["codelists"][0]["terms"],
            start=1,
        ):
            session.add(
                TerminologyTerm(
                    id=UUID(f"20000000-0000-0000-0000-{index:012d}"),
                    codelist_id=codelist_id,
                    synonyms=[],
                    **item,
                )
            )

    family_id = UUID("30000000-0000-0000-0000-000000000001")
    template_version_id = UUID("30000000-0000-0000-0000-000000000002")
    if session.get(TemplateFamily, family_id) is None:
        session.add(TemplateFamily(id=family_id, code="REPORT_LAYOUT", name="Shared Report Layout"))
    if session.get(TemplateVersion, template_version_id) is None:
        content = json.loads(template_path.read_text(encoding="utf-8"))
        session.add(
            TemplateVersion(
                id=template_version_id,
                family_id=family_id,
                version="1.0.0",
                lifecycle="active",
                checksum=_checksum(template_path),
                asset_path=str(template_path.relative_to(ROOT)).replace("\\", "/"),
                applicable_modules=MODULES,
                artifact_types=["validation_report", "reconciliation_report_pdf"],
                content_schema_versions=["1.0.0"],
                renderer_versions=[content["renderer"]],
                blank_structure={"sections": content["blank_structure"]},
                provenance={"source": "repository", "license": "project"},
            )
        )

    document_template_id = UUID("30000000-0000-0000-0000-000000000003")
    if session.get(TemplateVersion, document_template_id) is None:
        document_template = json.loads(document_template_path.read_text(encoding="utf-8"))
        session.add(
            TemplateVersion(
                id=document_template_id,
                family_id=family_id,
                version="2.0.0",
                lifecycle="active",
                checksum=_checksum(document_template_path),
                asset_path=str(document_template_path.relative_to(ROOT)).replace("\\", "/"),
                applicable_modules=["documents"],
                artifact_types=[
                    "protocol_summary_docx",
                    "protocol_summary_pdf",
                    "protocol_annotated_evidence",
                    "protocol_amendment_summary_of_change_pdf",
                    "protocol_deviation_document_pdf",
                    "aggregate_study_risk_profile_pdf",
                    "data_management_plan_pdf",
                    "statistical_analysis_plan_docx",
                    "statistical_analysis_plan_pdf",
                    "centralized_monitoring_platform_setup_documentation_pdf",
                    "protocol_deviation_dataset_xlsx",
                    "aggregate_study_brief_pdf",
                    "study_data_summary_pdf",
                    "standard_quality_dashboard_qe_details_xlsx",
                    "standard_quality_dashboard_sqe_audit_capa_details_xlsx",
                    "standard_quality_dashboard_audit_observation_detail_xlsx",
                    "signals_report_xlsx",
                    "actions_report_xlsx",
                    "document_validation_report_pdf",
                ],
                content_schema_versions=["1.0.0"],
                renderer_versions=[document_template["renderer"]],
                blank_structure={"sections": document_template["blank_structure"]},
                provenance={"source": "repository", "license": "project"},
            )
        )

    csdrg_template_id = UUID("30000000-0000-0000-0000-000000000004")
    if session.get(TemplateVersion, csdrg_template_id) is None:
        csdrg_template = json.loads(document_template_path.read_text(encoding="utf-8"))
        session.add(
            TemplateVersion(
                id=csdrg_template_id,
                family_id=family_id,
                version="2.1.0",
                lifecycle="active",
                checksum=_checksum(document_template_path),
                asset_path=str(document_template_path.relative_to(ROOT)).replace("\\", "/"),
                applicable_modules=["sdtm"],
                artifact_types=["sdtm_csdrg_docx", "sdtm_csdrg_pdf"],
                content_schema_versions=["1.0.0"],
                renderer_versions=[csdrg_template["renderer"]],
                blank_structure={"sections": csdrg_template["blank_structure"]},
                provenance={"source": "repository", "license": "project"},
            )
        )

    validation_rule_id = UUID("40000000-0000-0000-0000-000000000001")
    rule_pack_id = UUID("40000000-0000-0000-0000-000000000002")
    if session.get(ValidationRule, validation_rule_id) is None:
        session.add(
            ValidationRule(
                id=validation_rule_id,
                rule_id="platform.artifact_checksum",
                version="1.0.0",
                module_key="validation",
                applicability={"entity_types": ["artifact"]},
                parameter_schema={"type": "object", "additionalProperties": False},
                default_severity="error",
                mandatory=True,
            )
        )
    if session.get(ValidationRulePack, rule_pack_id) is None:
        session.add(
            ValidationRulePack(
                id=rule_pack_id,
                study_id=None,
                code="PLATFORM_INTEGRITY",
                name="Platform Integrity",
                lifecycle="active",
                selections=[
                    {
                        "validation_rule_id": str(validation_rule_id),
                        "parameters": {},
                        "severity": "error",
                    }
                ],
            )
        )
    session.commit()


def main() -> None:
    """Seed the configured database."""

    settings = get_settings()
    storage = S3ObjectStorage(settings)
    factory = create_session_factory(create_database_engine(settings))
    with factory() as session:
        seed(session, storage)


if __name__ == "__main__":
    main()
