"""Typed resolution of immutable JSON metadata from the Standards registry."""

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.artifacts.storage import ObjectStorage
from app.common.asset_content import AssetContentError, read_verified_asset_json_object
from app.common.canonical import canonical_json, sha256_hex
from app.common.repository_assets import verify_repository_asset
from app.integration.cdisc_library import CdiscLibraryReader
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


def resolve_live_standard_metadata(
    session: Session,
    standard_version_id: UUID,
    *,
    reader: CdiscLibraryReader,
) -> ResolvedStandardMetadata:
    """Fetch and verify one exact standard root directly from CDISC Library."""

    version = session.get(StandardVersion, standard_version_id)
    product = session.get(StandardProduct, version.product_id) if version is not None else None
    if version is None or product is None:
        raise ValueError("the selected standard version is unavailable")
    if product.provider != "CDISC":
        raise ValueError("live Specification metadata requires a CDISC standard")
    if version.lifecycle not in {"active", "deprecated"}:
        raise ValueError("the selected standard version is not available for use")
    if not version.library_href:
        raise ValueError("the selected standard version has no canonical CDISC Library resource")

    resource = reader.get(version.library_href)
    canonical_href = reader.canonical_href(version.library_href)
    if resource.href != canonical_href:
        raise ValueError("CDISC Library returned a different standard resource")
    links = resource.content.get("_links")
    self_link = links.get("self") if isinstance(links, dict) else None
    self_href = self_link.get("href") if isinstance(self_link, dict) else None
    if not isinstance(self_href, str) or reader.canonical_href(self_href) != canonical_href:
        raise ValueError("CDISC Library response self-link does not match the selected resource")
    live_version = resource.content.get("version")
    registered_version_numbers = tuple(re.findall(r"\d+", version.version))
    live_version_numbers = (
        tuple(re.findall(r"\d+", live_version)) if isinstance(live_version, str) else ()
    )
    if not registered_version_numbers or live_version_numbers != registered_version_numbers:
        raise ValueError("CDISC Library returned a different standard version")
    checksum = sha256_hex(canonical_json(resource.content))
    return ResolvedStandardMetadata(
        version_id=version.id,
        product_code=product.code,
        product_name=product.name,
        version=version.version,
        canonical_href=resource.href,
        checksum=checksum,
        payload=resource.content,
    )


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
