"""Offline CLI for importing and registering immutable CDISC Library content."""

import argparse
import logging
import tempfile
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.artifacts.storage import (
    ObjectStorage,
    S3ObjectStorage,
    checksum_object_key,
)
from app.cdisc_library_registry import (
    publish_library_selection,
    register_library_selection_rows,
)
from app.common.asset_content import publish_verified_asset
from app.common.canonical import sha256_hex
from app.common.persistence import UuidPrimaryKey
from app.common.repository_assets import verify_repository_asset
from app.config import Settings, get_settings
from app.database import create_database_engine, create_session_factory
from app.integration.cdisc_library import HttpCdiscLibraryClient
from app.standards.importer import import_standard_manifest, publish_standard_manifest
from app.standards.library_selection import fetch_library_selection
from app.standards.models import StandardAsset, StandardVersion
from app.terminology.importer import import_terminology_manifest, publish_terminology_manifest
from app.terminology.models import TerminologyAsset, TerminologyRelease

logger = logging.getLogger(__name__)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import exact CDISC Library selections into immutable object storage."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    import_selection = commands.add_parser(
        "import-selection",
        help="Fetch and register one exact CDISC release without retaining repository files.",
    )
    import_selection.add_argument(
        "href",
        help="Concrete Library href, for example /mdr/sdtmig/3-4.",
    )
    import_selection.add_argument(
        "--max-resources",
        type=int,
        help="Safety ceiling; defaults to CDISC_LIBRARY_MAX_RESOURCES.",
    )

    register_manifests = commands.add_parser(
        "register-manifests", help="Register reviewed hand-maintained package manifests."
    )
    register_manifests.add_argument(
        "--standard-manifest", action="append", default=[], type=Path, metavar="PATH"
    )
    register_manifests.add_argument(
        "--terminology-manifest", action="append", default=[], type=Path, metavar="PATH"
    )

    publish_assets = commands.add_parser(
        "publish-assets",
        help="Backfill checksum-addressed object storage from registered asset rows.",
    )
    publish_assets.add_argument("--batch-size", type=int, default=500)
    publish_assets.add_argument("--dry-run", action="store_true")
    publish_assets.add_argument("--verify-existing", action="store_true")
    publish_assets.add_argument("--force", action="store_true")
    return parser.parse_args()


def _import_selection(settings: Settings, href: str, max_resources: int | None) -> None:
    api_key = settings.cdisc_library_api_key
    if api_key is None or not api_key.get_secret_value():
        raise SystemExit("CDISC_LIBRARY_API_KEY is required for import-selection")

    def progress(count: int, current_href: str) -> None:
        if count == 1 or count % 100 == 0:
            print(f"fetched {count} resources; current={current_href}", flush=True)

    with tempfile.TemporaryDirectory(prefix="aurinara-cdisc-") as temporary_directory:
        with HttpCdiscLibraryClient(
            base_url=settings.cdisc_library_base_url,
            api_key=api_key.get_secret_value(),
            timeout_seconds=settings.cdisc_library_timeout_seconds,
        ) as client:
            selection = fetch_library_selection(
                reader=client,
                staging_root=Path(temporary_directory) / "selection",
                library_base_url=settings.cdisc_library_base_url,
                selected_href=href,
                max_resources=(
                    max_resources
                    if max_resources is not None
                    else settings.cdisc_library_max_resources
                ),
                parallel_requests=settings.cdisc_library_parallel_requests,
                progress=progress,
            )
        storage = S3ObjectStorage(settings)
        publish_library_selection(storage, selection)
        factory = create_session_factory(create_database_engine(settings))
        with factory.begin() as session:
            register_library_selection_rows(
                session,
                selection.manifest,
                selection.local_files,
                REPOSITORY_ROOT,
            )
    print(
        f"registered {selection.manifest.resource_count} resources from "
        f"{selection.manifest.selected_href}",
        flush=True,
    )


def _register_manifests(settings: Settings, arguments: argparse.Namespace) -> None:
    if not arguments.standard_manifest and not arguments.terminology_manifest:
        raise SystemExit("at least one manifest is required")
    storage = S3ObjectStorage(settings)
    for manifest_path in arguments.standard_manifest:
        publish_standard_manifest(storage, manifest_path.resolve(), REPOSITORY_ROOT)
    for manifest_path in arguments.terminology_manifest:
        publish_terminology_manifest(storage, manifest_path.resolve(), REPOSITORY_ROOT)
    factory = create_session_factory(create_database_engine(settings))
    with factory.begin() as session:
        for manifest_path in arguments.standard_manifest:
            import_standard_manifest(session, manifest_path.resolve(), REPOSITORY_ROOT)
        for manifest_path in arguments.terminology_manifest:
            import_terminology_manifest(session, manifest_path.resolve(), REPOSITORY_ROOT)


def _publish_asset_row(
    storage: ObjectStorage,
    *,
    asset_path: str,
    checksum: str,
    media_type: str,
    allowed_root: str,
    verify_existing: bool,
    force: bool,
    dry_run: bool,
) -> str:
    """Publish one real file-backed asset row; return a terminal action label."""

    key = checksum_object_key(checksum)
    present = storage.exists(key)
    if dry_run:
        return "present" if present else "would-upload"
    if present and not force:
        if not verify_existing:
            return "skipped"
        with storage.open(key) as body:
            if sha256_hex(body.read()) == checksum:
                return "verified"
    path, _ = verify_repository_asset(
        REPOSITORY_ROOT, asset_path, checksum, allowed_root=allowed_root
    )
    publish_verified_asset(storage, path, checksum, media_type)
    return "uploaded"


def _is_group_digest(asset_path: str, stored_checksum: str, allowed_root: str) -> bool:
    """A row whose on-disk file sha256 differs from its stored checksum owns no file object."""

    _, actual = verify_repository_asset(
        REPOSITORY_ROOT, asset_path, None, allowed_root=allowed_root
    )
    return actual != stored_checksum


def _is_repository_asset(asset_path: str, allowed_root: str) -> bool:
    """Return whether an asset locator names a file under its reviewed repository root."""

    return asset_path.startswith(f"{allowed_root}/")


def _publish_assets(settings: Settings, arguments: argparse.Namespace) -> None:
    if arguments.batch_size <= 0:
        raise SystemExit("--batch-size must be positive")
    storage = S3ObjectStorage(settings)
    factory = create_session_factory(create_database_engine(settings))
    processed = 0
    skipped_group_digests = 0
    skipped_external_assets = 0

    def _progress(label: str, identifier: str) -> None:
        nonlocal processed
        processed += 1
        if processed == 1 or processed % 100 == 0:
            logger.debug("publish-assets %s current=%s", label, identifier)
            print(f"publish-assets processed {processed}; last={label}", flush=True)

    # Repository-backed per-asset rows carry a real file sha256 and are publishable.
    for standard_asset in _stream_rows(factory, StandardAsset, arguments.batch_size):
        if not _is_repository_asset(standard_asset.asset_path, "schemas"):
            skipped_external_assets += 1
            continue
        label = _publish_asset_row(
            storage,
            asset_path=standard_asset.asset_path,
            checksum=standard_asset.checksum,
            media_type=standard_asset.media_type,
            allowed_root="schemas",
            verify_existing=arguments.verify_existing,
            force=arguments.force,
            dry_run=arguments.dry_run,
        )
        _progress(label, str(standard_asset.id))
    for terminology_asset in _stream_rows(factory, TerminologyAsset, arguments.batch_size):
        if not _is_repository_asset(terminology_asset.asset_path, "terminology"):
            skipped_external_assets += 1
            continue
        label = _publish_asset_row(
            storage,
            asset_path=terminology_asset.asset_path,
            checksum=terminology_asset.checksum,
            media_type=terminology_asset.media_type,
            allowed_root="terminology",
            verify_existing=arguments.verify_existing,
            force=arguments.force,
            dry_run=arguments.dry_run,
        )
        _progress(label, str(terminology_asset.id))

    # Hand-maintained manifest files; synthetic group-digest rows own no file object.
    for standard_version in _stream_rows(factory, StandardVersion, arguments.batch_size):
        if not _is_repository_asset(standard_version.asset_path, "schemas"):
            skipped_external_assets += 1
            continue
        if _is_group_digest(standard_version.asset_path, standard_version.checksum, "schemas"):
            skipped_group_digests += 1
            continue
        label = _publish_asset_row(
            storage,
            asset_path=standard_version.asset_path,
            checksum=standard_version.checksum,
            media_type="application/json",
            allowed_root="schemas",
            verify_existing=arguments.verify_existing,
            force=arguments.force,
            dry_run=arguments.dry_run,
        )
        _progress(label, str(standard_version.id))
    for release in _stream_rows(factory, TerminologyRelease, arguments.batch_size):
        if not _is_repository_asset(release.asset_path, "terminology"):
            skipped_external_assets += 1
            continue
        if _is_group_digest(release.asset_path, release.checksum, "terminology"):
            skipped_group_digests += 1
            continue
        label = _publish_asset_row(
            storage,
            asset_path=release.asset_path,
            checksum=release.checksum,
            media_type="application/json",
            allowed_root="terminology",
            verify_existing=arguments.verify_existing,
            force=arguments.force,
            dry_run=arguments.dry_run,
        )
        _progress(label, str(release.id))

    print(
        f"publish-assets complete: processed={processed}, "
        f"group-digests-skipped={skipped_group_digests}, "
        f"external-assets-skipped={skipped_external_assets}",
        flush=True,
    )


def _stream_rows[RowT: UuidPrimaryKey](
    factory: sessionmaker[Session],
    model: type[RowT],
    batch_size: int,
) -> Iterator[RowT]:
    """Yield rows ordered by primary key in short read-only sessions per batch."""

    last_id: UUID | None = None
    while True:
        with factory() as session:
            statement = select(model).order_by(model.id).limit(batch_size)
            if last_id is not None:
                statement = statement.where(model.id > last_id)
            rows = list(session.scalars(statement))
        if not rows:
            return
        yield from rows
        last_id = rows[-1].id


def main() -> None:
    """Dispatch on-demand selection import or repository asset publication."""

    arguments = _arguments()
    settings = get_settings()
    if arguments.command == "import-selection":
        _import_selection(settings, arguments.href, arguments.max_resources)
    elif arguments.command == "publish-assets":
        _publish_assets(settings, arguments)
    else:
        _register_manifests(settings, arguments)


if __name__ == "__main__":
    main()
