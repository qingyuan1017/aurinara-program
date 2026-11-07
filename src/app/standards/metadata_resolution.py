"""Typed resolution of immutable JSON metadata from the Standards registry."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.artifacts.storage import ObjectStorage
from app.common.asset_content import AssetContentError, read_verified_asset_json_object
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
    storage: ObjectStorage,
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
    local_fallback: Callable[[], Path] | None = None
    if storage.local_fallback_enabled and asset.asset_path.startswith("schemas/"):

        def load_local_asset() -> Path:
            return verify_repository_asset(
                repository_root,
                asset.asset_path,
                asset.checksum,
                allowed_root="schemas",
            )[0]

        local_fallback = load_local_asset
    try:
        raw_payload = read_verified_asset_json_object(
            storage,
            asset.checksum,
            local_fallback=local_fallback,
        )
    except AssetContentError as error:
        raise ValueError(
            f"the selected standard metadata asset is unavailable ({error.reason})"
        ) from error
    return ResolvedStandardMetadata(
        version_id=version.id,
        product_code=product.code,
        product_name=product.name,
        version=version.version,
        canonical_href=version.library_href,
        checksum=asset.checksum,
        payload=raw_payload,
    )
