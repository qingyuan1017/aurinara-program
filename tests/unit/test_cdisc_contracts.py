"""CDISC package contracts preserve published semantics and reject ambiguity."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.common.repository_assets import verify_repository_asset
from app.standards.contracts import CdiscStandardManifest
from app.terminology.contracts import CdiscTerminologyManifest


def test_standard_manifest_represents_exact_model_guide_relationship() -> None:
    manifest = CdiscStandardManifest.model_validate(
        {
            "schema_version": "1.0.0",
            "provider": "CDISC",
            "product": {
                "id": "10000000-0000-0000-0000-000000000010",
                "code": "SDTMIG",
                "name": "Study Data Tabulation Model Implementation Guide",
                "family": "DataTabulation",
                "product_type": "implementation_guide",
                "scope": "clinical",
            },
            "release": {
                "id": "10000000-0000-0000-0000-000000000011",
                "version": "synthetic-1.0",
                "publication_date": "2026-01-01",
                "applicable_modules": ["sdtm"],
                "purposes": ["implementation_guide"],
                "provenance": {"source": "synthetic-test"},
            },
            "assets": [
                {
                    "id": "10000000-0000-0000-0000-000000000012",
                    "role": "machine_readable_metadata",
                    "media_type": "application/json",
                    "path": "schemas/cdisc/synthetic.json",
                    "sha256": "a" * 64,
                }
            ],
            "compatibilities": [
                {
                    "id": "10000000-0000-0000-0000-000000000013",
                    "target_standard_version_id": "10000000-0000-0000-0000-000000000014",
                    "relationship": "implements",
                    "required": True,
                }
            ],
        }
    )
    assert manifest.product.code == "SDTMIG"
    assert manifest.compatibilities[0].required is True


def test_terminology_manifest_preserves_cdisc_nci_metadata() -> None:
    manifest = CdiscTerminologyManifest.model_validate(
        {
            "schema_version": "1.0.0",
            "provider": "CDISC",
            "release": {
                "id": "20000000-0000-0000-0000-000000000010",
                "code": "SDTM_CT",
                "product": "SDTM",
                "version": "synthetic-2026-01-01",
                "publication_date": "2026-01-01",
                "applicable_modules": ["sdtm"],
                "provenance": {"source": "synthetic-test"},
            },
            "codelists": [
                {
                    "id": "20000000-0000-0000-0000-000000000011",
                    "concept_id": "C66786",
                    "name": "Synthetic Test Code",
                    "submission_value": "TESTCD",
                    "definition": "Synthetic definition.",
                    "preferred_term": "Synthetic Preferred Term",
                    "synonyms": ["Synthetic synonym"],
                    "extensible": False,
                    "terms": [
                        {
                            "id": "20000000-0000-0000-0000-000000000012",
                            "concept_id": "C123456",
                            "submission_value": "SYNTHETIC",
                            "decode": "Synthetic",
                            "definition": "Synthetic term definition.",
                            "preferred_term": "Synthetic",
                            "synonyms": ["Test value"],
                            "status": "retired",
                        }
                    ],
                }
            ],
        }
    )
    codelist = manifest.codelists[0]
    assert codelist.extensible is False
    assert codelist.terms[0].concept_id == "C123456"
    assert codelist.terms[0].status == "retired"


def test_terminology_manifest_rejects_duplicate_submission_values() -> None:
    shared = {
        "submission_value": "DUPLICATE",
        "decode": "Synthetic",
    }
    with pytest.raises(ValidationError, match="submission values must be unique"):
        CdiscTerminologyManifest.model_validate(
            {
                "schema_version": "1.0.0",
                "provider": "CDISC",
                "release": {
                    "id": "20000000-0000-0000-0000-000000000020",
                    "code": "SDTM_CT",
                    "product": "SDTM",
                    "version": "synthetic",
                    "publication_date": "2026-01-01",
                    "applicable_modules": ["sdtm"],
                    "provenance": {"source": "synthetic-test"},
                },
                "codelists": [
                    {
                        "id": "20000000-0000-0000-0000-000000000021",
                        "concept_id": "C111",
                        "name": "Synthetic",
                        "submission_value": "SYN",
                        "extensible": True,
                        "terms": [
                            {
                                "id": "20000000-0000-0000-0000-000000000022",
                                "concept_id": "C112",
                                **shared,
                            },
                            {
                                "id": "20000000-0000-0000-0000-000000000023",
                                "concept_id": "C113",
                                **shared,
                            },
                        ],
                    }
                ],
            }
        )


def test_repository_asset_rejects_path_escape(tmp_path: Path) -> None:
    (tmp_path / "schemas").mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="unsafe repository asset path"):
        verify_repository_asset(tmp_path, "schemas/../outside.json", allowed_root="schemas")
