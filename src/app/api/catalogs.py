"""Read-only exact-version provider catalog APIs."""

import json
from datetime import date, datetime
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import Principal, get_principal
from app.api.dependencies import get_session
from app.common.problems import ProblemException
from app.common.repository_assets import verify_repository_asset
from app.standards.models import (
    StandardAsset,
    StandardProduct,
    StandardVersion,
    StandardVersionCompatibility,
)
from app.templates.models import TemplateFamily, TemplateVersion
from app.terminology.models import (
    TerminologyAsset,
    TerminologyCodelist,
    TerminologyRelease,
    TerminologyReleaseCompatibility,
    TerminologyTerm,
)

router = APIRouter(tags=["provider-catalogs"])
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class CatalogIdentity(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    code: str
    name: str


class StandardProductResponse(CatalogIdentity):
    provider: str
    family: str
    product_type: str
    scope: str


class StandardVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    product_id: UUID
    version: str
    publication_date: date | None
    library_href: str | None
    content_schema_version: str
    lifecycle: str
    checksum: str
    provenance: dict[str, object]
    applicable_modules: list[str]
    purposes: list[str]
    compatibility: dict[str, object]
    created_at: datetime


class StandardAssetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    version_id: UUID
    role: str
    media_type: str
    checksum: str
    required: bool
    canonical_href: str | None
    title: str | None
    resource_type: str | None
    content_schema_version: str


class StandardCompatibilityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    source_version_id: UUID
    target_version_id: UUID
    relationship: str
    required: bool
    evidence: dict[str, object]


class TemplateVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    family_id: UUID
    version: str
    lifecycle: str
    checksum: str
    applicable_modules: list[str]
    artifact_types: list[str]
    content_schema_versions: list[str]
    renderer_versions: list[str]
    blank_structure: dict[str, object]
    provenance: dict[str, object]
    created_at: datetime


class TerminologyReleaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    code: str
    version: str
    provider: str
    product: str
    publication_date: date | None
    library_href: str | None
    content_schema_version: str
    lifecycle: str
    checksum: str
    applicable_modules: list[str]
    provenance: dict[str, object]
    created_at: datetime


class CodelistResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    release_id: UUID
    code: str
    name: str
    concept_id: str | None
    submission_value: str | None
    definition: str | None
    preferred_term: str | None
    synonyms: list[str]
    extensible: bool


class TermResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    codelist_id: UUID
    code: str
    concept_id: str | None
    submission_value: str
    decode: str
    definition: str | None
    preferred_term: str | None
    synonyms: list[str]
    status: str


class TerminologyCompatibilityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    release_id: UUID
    standard_version_id: UUID
    terminology_scope: str
    standard_purpose: str
    relationship: str
    evidence: dict[str, object]


class TerminologyAssetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    release_id: UUID
    role: str
    media_type: str
    checksum: str
    canonical_href: str
    title: str | None
    resource_type: str | None
    content_schema_version: str


def _require(session: Session, model: type, identifier: UUID, code: str) -> object:
    record = session.get(model, identifier)
    if record is None:
        raise ProblemException(
            status_code=404,
            code=code,
            title="Catalog record not found",
            detail="The exact catalog identity does not exist.",
        )
    return record


@router.get("/standards", response_model=list[StandardProductResponse])
def list_standards(
    session: Annotated[Session, Depends(get_session)],
    _principal: Annotated[Principal, Depends(get_principal)],
    provider: Annotated[str | None, Query(max_length=64)] = None,
    family: Annotated[str | None, Query(max_length=64)] = None,
    product_type: Annotated[str | None, Query(max_length=64)] = None,
    scope: Annotated[str | None, Query(max_length=64)] = None,
) -> list[StandardProductResponse]:
    statement = select(StandardProduct)
    for column, value in (
        (StandardProduct.provider, provider),
        (StandardProduct.family, family),
        (StandardProduct.product_type, product_type),
        (StandardProduct.scope, scope),
    ):
        if value is not None:
            statement = statement.where(column == value)
    return [
        StandardProductResponse.model_validate(item)
        for item in session.scalars(statement.order_by(StandardProduct.code))
    ]


@router.get("/standards/{standard_id}", response_model=StandardProductResponse)
def get_standard(
    standard_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    _principal: Annotated[Principal, Depends(get_principal)],
) -> StandardProductResponse:
    return StandardProductResponse.model_validate(
        _require(session, StandardProduct, standard_id, "standard_not_found")
    )


@router.get("/standards/{standard_id}/versions", response_model=list[StandardVersionResponse])
def list_standard_versions(
    standard_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    _principal: Annotated[Principal, Depends(get_principal)],
    module: Annotated[str | None, Query(max_length=32)] = None,
    purpose: Annotated[str | None, Query(max_length=64)] = None,
    lifecycle: Annotated[str | None, Query(max_length=32)] = None,
    compatible_with: Annotated[UUID | None, Query()] = None,
) -> list[StandardVersionResponse]:
    _require(session, StandardProduct, standard_id, "standard_not_found")
    statement = select(StandardVersion).where(StandardVersion.product_id == standard_id)
    if module is not None:
        statement = statement.where(StandardVersion.applicable_modules.contains([module]))
    if purpose is not None:
        statement = statement.where(StandardVersion.purposes.contains([purpose]))
    if lifecycle is not None:
        statement = statement.where(StandardVersion.lifecycle == lifecycle)
    if compatible_with is not None:
        compatible_sources = select(StandardVersionCompatibility.source_version_id).where(
            StandardVersionCompatibility.target_version_id == compatible_with
        )
        statement = statement.where(StandardVersion.id.in_(compatible_sources))
    return [
        StandardVersionResponse.model_validate(item)
        for item in session.scalars(statement.order_by(StandardVersion.publication_date))
    ]


@router.get("/standard-versions/{version_id}", response_model=StandardVersionResponse)
def get_standard_version(
    version_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    _principal: Annotated[Principal, Depends(get_principal)],
) -> StandardVersionResponse:
    return StandardVersionResponse.model_validate(
        _require(session, StandardVersion, version_id, "standard_version_not_found")
    )


@router.get("/standard-versions/{version_id}/assets", response_model=list[StandardAssetResponse])
def list_standard_assets(
    version_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    _principal: Annotated[Principal, Depends(get_principal)],
) -> list[StandardAssetResponse]:
    _require(session, StandardVersion, version_id, "standard_version_not_found")
    return [
        StandardAssetResponse.model_validate(item)
        for item in session.scalars(
            select(StandardAsset).where(StandardAsset.version_id == version_id)
        )
    ]


@router.get("/standard-assets/{asset_id}/content", response_model=dict[str, object])
def get_standard_asset_content(
    asset_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    _principal: Annotated[Principal, Depends(get_principal)],
) -> dict[str, object]:
    asset = _require(session, StandardAsset, asset_id, "standard_asset_not_found")
    assert isinstance(asset, StandardAsset)
    path, _ = verify_repository_asset(
        REPOSITORY_ROOT,
        asset.asset_path,
        asset.checksum,
        allowed_root="schemas",
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("registered standard asset is not a JSON object")
    return payload


@router.get(
    "/standard-versions/{version_id}/compatibilities",
    response_model=list[StandardCompatibilityResponse],
)
def list_standard_compatibilities(
    version_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    _principal: Annotated[Principal, Depends(get_principal)],
) -> list[StandardCompatibilityResponse]:
    _require(session, StandardVersion, version_id, "standard_version_not_found")
    return [
        StandardCompatibilityResponse.model_validate(item)
        for item in session.scalars(
            select(StandardVersionCompatibility).where(
                StandardVersionCompatibility.source_version_id == version_id
            )
        )
    ]


@router.get("/templates", response_model=list[CatalogIdentity])
def list_templates(
    session: Annotated[Session, Depends(get_session)],
    _principal: Annotated[Principal, Depends(get_principal)],
) -> list[CatalogIdentity]:
    return [
        CatalogIdentity.model_validate(item) for item in session.scalars(select(TemplateFamily))
    ]


@router.get("/templates/{template_id}", response_model=CatalogIdentity)
def get_template(
    template_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    _principal: Annotated[Principal, Depends(get_principal)],
) -> CatalogIdentity:
    return CatalogIdentity.model_validate(
        _require(session, TemplateFamily, template_id, "template_not_found")
    )


@router.get("/templates/{template_id}/versions", response_model=list[TemplateVersionResponse])
def list_template_versions(
    template_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    _principal: Annotated[Principal, Depends(get_principal)],
) -> list[TemplateVersionResponse]:
    _require(session, TemplateFamily, template_id, "template_not_found")
    return [
        TemplateVersionResponse.model_validate(item)
        for item in session.scalars(
            select(TemplateVersion).where(TemplateVersion.family_id == template_id)
        )
    ]


@router.get("/template-versions/{version_id}", response_model=TemplateVersionResponse)
def get_template_version(
    version_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    _principal: Annotated[Principal, Depends(get_principal)],
) -> TemplateVersionResponse:
    return TemplateVersionResponse.model_validate(
        _require(session, TemplateVersion, version_id, "template_version_not_found")
    )


@router.get("/terminology-releases", response_model=list[TerminologyReleaseResponse])
def list_releases(
    session: Annotated[Session, Depends(get_session)],
    _principal: Annotated[Principal, Depends(get_principal)],
    provider: Annotated[str | None, Query(max_length=64)] = None,
    product: Annotated[str | None, Query(max_length=64)] = None,
    module: Annotated[str | None, Query(max_length=32)] = None,
    lifecycle: Annotated[str | None, Query(max_length=32)] = None,
    compatible_standard_version_id: Annotated[UUID | None, Query()] = None,
) -> list[TerminologyReleaseResponse]:
    statement = select(TerminologyRelease)
    if provider is not None:
        statement = statement.where(TerminologyRelease.provider == provider)
    if product is not None:
        statement = statement.where(TerminologyRelease.product == product)
    if module is not None:
        statement = statement.where(TerminologyRelease.applicable_modules.contains([module]))
    if lifecycle is not None:
        statement = statement.where(TerminologyRelease.lifecycle == lifecycle)
    if compatible_standard_version_id is not None:
        compatible_releases = select(TerminologyReleaseCompatibility.release_id).where(
            TerminologyReleaseCompatibility.standard_version_id == compatible_standard_version_id
        )
        statement = statement.where(TerminologyRelease.id.in_(compatible_releases))
    return [
        TerminologyReleaseResponse.model_validate(item)
        for item in session.scalars(
            statement.order_by(
                TerminologyRelease.product,
                TerminologyRelease.publication_date,
                TerminologyRelease.version,
            )
        )
    ]


@router.get("/terminology-releases/{release_id}", response_model=TerminologyReleaseResponse)
def get_release(
    release_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    _principal: Annotated[Principal, Depends(get_principal)],
) -> TerminologyReleaseResponse:
    return TerminologyReleaseResponse.model_validate(
        _require(session, TerminologyRelease, release_id, "terminology_release_not_found")
    )


@router.get(
    "/terminology-releases/{release_id}/compatibilities",
    response_model=list[TerminologyCompatibilityResponse],
)
def list_terminology_compatibilities(
    release_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    _principal: Annotated[Principal, Depends(get_principal)],
) -> list[TerminologyCompatibilityResponse]:
    _require(session, TerminologyRelease, release_id, "terminology_release_not_found")
    return [
        TerminologyCompatibilityResponse.model_validate(item)
        for item in session.scalars(
            select(TerminologyReleaseCompatibility).where(
                TerminologyReleaseCompatibility.release_id == release_id
            )
        )
    ]


@router.get(
    "/terminology-releases/{release_id}/assets",
    response_model=list[TerminologyAssetResponse],
)
def list_terminology_assets(
    release_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    _principal: Annotated[Principal, Depends(get_principal)],
) -> list[TerminologyAssetResponse]:
    _require(session, TerminologyRelease, release_id, "terminology_release_not_found")
    return [
        TerminologyAssetResponse.model_validate(item)
        for item in session.scalars(
            select(TerminologyAsset)
            .where(TerminologyAsset.release_id == release_id)
            .order_by(TerminologyAsset.canonical_href)
        )
    ]


@router.get("/terminology-assets/{asset_id}/content", response_model=dict[str, object])
def get_terminology_asset_content(
    asset_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    _principal: Annotated[Principal, Depends(get_principal)],
) -> dict[str, object]:
    asset = _require(session, TerminologyAsset, asset_id, "terminology_asset_not_found")
    assert isinstance(asset, TerminologyAsset)
    path, _ = verify_repository_asset(
        REPOSITORY_ROOT,
        asset.asset_path,
        asset.checksum,
        allowed_root="terminology",
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("registered terminology asset is not a JSON object")
    return payload


@router.get("/terminology-releases/{release_id}/codelists", response_model=list[CodelistResponse])
def list_codelists(
    release_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    _principal: Annotated[Principal, Depends(get_principal)],
    concept_id: Annotated[str | None, Query(max_length=64)] = None,
    submission_value: Annotated[str | None, Query(max_length=255)] = None,
    extensible: Annotated[bool | None, Query()] = None,
) -> list[CodelistResponse]:
    _require(session, TerminologyRelease, release_id, "terminology_release_not_found")
    statement = select(TerminologyCodelist).where(TerminologyCodelist.release_id == release_id)
    if concept_id is not None:
        statement = statement.where(TerminologyCodelist.concept_id == concept_id)
    if submission_value is not None:
        statement = statement.where(TerminologyCodelist.submission_value == submission_value)
    if extensible is not None:
        statement = statement.where(TerminologyCodelist.extensible == extensible)
    return [
        CodelistResponse.model_validate(item)
        for item in session.scalars(statement.order_by(TerminologyCodelist.code))
    ]


@router.get("/terminology-codelists/{codelist_id}", response_model=CodelistResponse)
def get_codelist(
    codelist_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    _principal: Annotated[Principal, Depends(get_principal)],
) -> CodelistResponse:
    return CodelistResponse.model_validate(
        _require(session, TerminologyCodelist, codelist_id, "terminology_codelist_not_found")
    )


@router.get("/terminology-codelists/{codelist_id}/terms", response_model=list[TermResponse])
def list_terms(
    codelist_id: UUID,
    session: Annotated[Session, Depends(get_session)],
    _principal: Annotated[Principal, Depends(get_principal)],
    concept_id: Annotated[str | None, Query(max_length=64)] = None,
    submission_value: Annotated[str | None, Query(max_length=255)] = None,
    status: Annotated[str | None, Query(pattern=r"^(active|retired)$")] = None,
) -> list[TermResponse]:
    _require(session, TerminologyCodelist, codelist_id, "terminology_codelist_not_found")
    statement = select(TerminologyTerm).where(TerminologyTerm.codelist_id == codelist_id)
    if concept_id is not None:
        statement = statement.where(TerminologyTerm.concept_id == concept_id)
    if submission_value is not None:
        statement = statement.where(TerminologyTerm.submission_value == submission_value)
    if status is not None:
        statement = statement.where(TerminologyTerm.status == status)
    return [
        TermResponse.model_validate(item)
        for item in session.scalars(statement.order_by(TerminologyTerm.code))
    ]
