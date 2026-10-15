"""Typed resolution of immutable JSON metadata from the Standards registry."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.repository_assets import verify_repository_asset
from app.standards.models import StandardAsset, StandardProduct, StandardVersion


@dataclass(frozen=True, slots=True)
class ResolvedStandardMetadata:
    """One verified root JSON resource for an exact registered standard version."""

    version_id: UUID
    product_code: str
    product_name: str
    version: str
    canonical_href: str
    checksum: str
    payload: dict[str, object]


def resolve_standard_metadata(
    session: Session,
    standard_version_id: UUID,
    *,
    repository_root: Path,
) -> ResolvedStandardMetadata:
    """Resolve and verify the root JSON asset for one exact standard version.

    The registry owns lookup and checksum verification. Clinical modules consume
    this immutable DTO rather than querying Standards persistence directly.
    """

    version = session.get(StandardVersion, standard_version_id)
    product = session.get(StandardProduct, version.product_id) if version is not None else None
    if version is None or product is None:
        raise ValueError("the selected standard version is unavailable")
    if version.lifecycle not in {"active", "deprecated"}:
        raise ValueError("the selected standard version is not available for use")
    if not version.library_href:
        raise ValueError("the selected standard version has no canonical root resource")
    asset = session.scalar(
        select(StandardAsset).where(
            StandardAsset.version_id == version.id,
            StandardAsset.canonical_href == version.library_href,
        )
    )
    if asset is None or asset.media_type != "application/json":
        raise ValueError("the selected standard version has no JSON root metadata asset")
    path, _ = verify_repository_asset(
        repository_root,
        asset.asset_path,
        asset.checksum,
        allowed_root="schemas",
    )
    try:
        raw_payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("the selected standard metadata asset is invalid JSON") from error
    if not isinstance(raw_payload, dict):
        raise ValueError("the selected standard metadata root must be a JSON object")
    return ResolvedStandardMetadata(
        version_id=version.id,
        product_code=product.code,
        product_name=product.name,
        version=version.version,
        canonical_href=version.library_href,
        checksum=asset.checksum,
        payload=cast(dict[str, object], raw_payload),
    )
