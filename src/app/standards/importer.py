"""Atomic registration of reviewed, repository-pinned CDISC standard manifests."""

import json
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.repository_assets import verify_repository_asset
from app.standards.contracts import CdiscStandardManifest
from app.standards.models import (
    StandardAsset,
    StandardProduct,
    StandardVersion,
    StandardVersionCompatibility,
)


def load_standard_manifest(
    manifest_path: Path, repository_root: Path
) -> tuple[CdiscStandardManifest, str, str]:
    """Validate a pinned CDISC standard manifest and every referenced asset."""

    relative_path = manifest_path.resolve().relative_to(repository_root.resolve()).as_posix()
    _, manifest_checksum = verify_repository_asset(
        repository_root, relative_path, allowed_root="schemas"
    )
    try:
        manifest = CdiscStandardManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        raise ValueError(f"invalid CDISC standard manifest: {manifest_path}") from error
    for asset in manifest.assets:
        verify_repository_asset(repository_root, asset.path, asset.sha256, allowed_root="schemas")
    return manifest, relative_path, manifest_checksum


def import_standard_manifest(
    session: Session, manifest_path: Path, repository_root: Path
) -> StandardVersion:
    """Register one exact CDISC release without committing the caller's transaction."""

    manifest, relative_path, manifest_checksum = load_standard_manifest(
        manifest_path, repository_root
    )
    product = session.get(StandardProduct, manifest.product.id)
    if product is None:
        product = StandardProduct(
            id=manifest.product.id,
            code=manifest.product.code,
            name=manifest.product.name,
            provider=manifest.provider,
            family=manifest.product.family,
            product_type=manifest.product.product_type,
            scope=manifest.product.scope,
        )
        session.add(product)
    elif (
        product.code != manifest.product.code
        or product.name != manifest.product.name
        or product.provider != manifest.provider
        or product.family != manifest.product.family
        or product.product_type != manifest.product.product_type
        or product.scope != manifest.product.scope
    ):
        raise ValueError("standard product identity conflicts with the pinned manifest")

    existing = session.get(StandardVersion, manifest.release.id)
    if existing is not None:
        if existing.checksum != manifest_checksum or existing.product_id != product.id:
            raise ValueError("standard version identity conflicts with immutable registry content")
        return existing

    duplicate = session.scalar(
        select(StandardVersion.id).where(
            StandardVersion.product_id == product.id,
            StandardVersion.version == manifest.release.version,
        )
    )
    if duplicate is not None:
        raise ValueError("standard product/version already exists under another identity")

    for compatibility in manifest.compatibilities:
        if session.get(StandardVersion, compatibility.target_standard_version_id) is None:
            raise ValueError(
                "compatibility target must be imported before the dependent standard release"
            )

    release = StandardVersion(
        id=manifest.release.id,
        product_id=product.id,
        version=manifest.release.version,
        publication_date=manifest.release.publication_date,
        library_href=manifest.release.library_href,
        content_schema_version=manifest.schema_version,
        lifecycle=manifest.release.lifecycle,
        checksum=manifest_checksum,
        asset_path=relative_path,
        provenance=manifest.release.provenance,
        applicable_modules=manifest.release.applicable_modules,
        purposes=manifest.release.purposes,
        compatibility={"manifest_relationship_count": len(manifest.compatibilities)},
    )
    session.add(release)
    session.flush()
    session.add_all(
        [
            StandardAsset(
                id=asset.id,
                version_id=release.id,
                role=asset.role,
                media_type=asset.media_type,
                asset_path=asset.path,
                checksum=asset.sha256,
                required=asset.required,
            )
            for asset in manifest.assets
        ]
    )
    session.add_all(
        [
            StandardVersionCompatibility(
                id=item.id,
                source_version_id=release.id,
                target_version_id=item.target_standard_version_id,
                relationship=item.relationship,
                required=item.required,
                evidence=item.evidence,
            )
            for item in manifest.compatibilities
        ]
    )
    return release
