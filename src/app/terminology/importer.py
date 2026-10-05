"""Atomic registration of reviewed, repository-pinned CDISC CT manifests."""

import json
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.repository_assets import verify_repository_asset
from app.standards.models import StandardVersion
from app.terminology.contracts import CdiscTerminologyManifest
from app.terminology.models import (
    TerminologyCodelist,
    TerminologyRelease,
    TerminologyReleaseCompatibility,
    TerminologyTerm,
)


def load_terminology_manifest(
    manifest_path: Path, repository_root: Path
) -> tuple[CdiscTerminologyManifest, str, str]:
    """Validate a repository-pinned CDISC CT package."""

    relative_path = manifest_path.resolve().relative_to(repository_root.resolve()).as_posix()
    _, checksum = verify_repository_asset(
        repository_root, relative_path, allowed_root="terminology"
    )
    try:
        manifest = CdiscTerminologyManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        raise ValueError(f"invalid CDISC terminology manifest: {manifest_path}") from error
    return manifest, relative_path, checksum


def import_terminology_manifest(
    session: Session, manifest_path: Path, repository_root: Path
) -> TerminologyRelease:
    """Register one exact CDISC CT package without committing the caller's transaction."""

    manifest, relative_path, checksum = load_terminology_manifest(manifest_path, repository_root)
    existing = session.get(TerminologyRelease, manifest.release.id)
    if existing is not None:
        if existing.checksum != checksum:
            raise ValueError("terminology release identity conflicts with immutable content")
        return existing
    duplicate = session.scalar(
        select(TerminologyRelease.id).where(
            TerminologyRelease.code == manifest.release.code,
            TerminologyRelease.version == manifest.release.version,
        )
    )
    if duplicate is not None:
        raise ValueError("terminology code/version already exists under another identity")
    for compatibility in manifest.compatibilities:
        if session.get(StandardVersion, compatibility.standard_version_id) is None:
            raise ValueError("terminology compatibility target standard is not registered")

    release = TerminologyRelease(
        id=manifest.release.id,
        code=manifest.release.code,
        version=manifest.release.version,
        provider=manifest.provider,
        product=manifest.release.product,
        publication_date=manifest.release.publication_date,
        library_href=manifest.release.library_href,
        content_schema_version=manifest.schema_version,
        lifecycle=manifest.release.lifecycle,
        checksum=checksum,
        asset_path=relative_path,
        applicable_modules=manifest.release.applicable_modules,
        provenance=manifest.release.provenance,
    )
    session.add(release)
    session.flush()
    for codelist_contract in manifest.codelists:
        codelist = TerminologyCodelist(
            id=codelist_contract.id,
            release_id=release.id,
            code=codelist_contract.concept_id,
            concept_id=codelist_contract.concept_id,
            name=codelist_contract.name,
            submission_value=codelist_contract.submission_value,
            definition=codelist_contract.definition,
            preferred_term=codelist_contract.preferred_term,
            synonyms=codelist_contract.synonyms,
            extensible=codelist_contract.extensible,
        )
        session.add(codelist)
        session.add_all(
            [
                TerminologyTerm(
                    id=term.id,
                    codelist_id=codelist.id,
                    code=term.concept_id,
                    concept_id=term.concept_id,
                    submission_value=term.submission_value,
                    decode=term.decode,
                    definition=term.definition,
                    preferred_term=term.preferred_term,
                    synonyms=term.synonyms,
                    status=term.status,
                )
                for term in codelist_contract.terms
            ]
        )
    session.add_all(
        [
            TerminologyReleaseCompatibility(
                id=item.id,
                release_id=release.id,
                standard_version_id=item.standard_version_id,
                terminology_scope=item.terminology_scope,
                standard_purpose=item.standard_purpose,
                relationship=item.relationship,
                evidence=item.evidence,
            )
            for item in manifest.compatibilities
        ]
    )
    return release
