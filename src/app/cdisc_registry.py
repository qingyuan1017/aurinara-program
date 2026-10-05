"""Offline CLI for snapshotting and registering CDISC Library content."""

import argparse
from pathlib import Path

from app.cdisc_library_registry import register_library_snapshot
from app.config import Settings, get_settings
from app.database import create_database_engine, create_session_factory
from app.integration.cdisc_library import HttpCdiscLibraryClient
from app.standards.importer import import_standard_manifest
from app.standards.library_snapshot import create_library_snapshot
from app.terminology.importer import import_terminology_manifest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Snapshot and register repository-pinned CDISC Library content."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    snapshot = commands.add_parser(
        "snapshot-all", help="Fetch the entire linked CDISC Library catalog into pinned files."
    )
    snapshot.add_argument(
        "--max-resources",
        type=int,
        help="Safety ceiling; defaults to CDISC_LIBRARY_MAX_RESOURCES.",
    )

    register_snapshot = commands.add_parser(
        "register-snapshot", help="Register one complete checked Library snapshot."
    )
    register_snapshot.add_argument("manifest", type=Path)

    register_manifests = commands.add_parser(
        "register-manifests", help="Register reviewed hand-maintained package manifests."
    )
    register_manifests.add_argument(
        "--standard-manifest", action="append", default=[], type=Path, metavar="PATH"
    )
    register_manifests.add_argument(
        "--terminology-manifest", action="append", default=[], type=Path, metavar="PATH"
    )
    return parser.parse_args()


def _snapshot_all(settings: Settings, max_resources: int | None) -> None:
    api_key = settings.cdisc_library_api_key
    if api_key is None or not api_key.get_secret_value():
        raise SystemExit("CDISC_LIBRARY_API_KEY is required for snapshot-all")

    def progress(count: int, href: str) -> None:
        if count == 1 or count % 100 == 0:
            print(f"snapshotted {count} resources; current={href}", flush=True)

    with HttpCdiscLibraryClient(
        base_url=settings.cdisc_library_base_url,
        api_key=api_key.get_secret_value(),
        timeout_seconds=settings.cdisc_library_timeout_seconds,
    ) as client:
        manifest_path = create_library_snapshot(
            reader=client,
            repository_root=REPOSITORY_ROOT,
            library_base_url=settings.cdisc_library_base_url,
            max_resources=max_resources or settings.cdisc_library_max_resources,
            parallel_requests=settings.cdisc_library_parallel_requests,
            progress=progress,
        )
    print(f"snapshot manifest: {manifest_path}")


def _register_snapshot(settings: Settings, manifest_path: Path) -> None:
    factory = create_session_factory(create_database_engine(settings))
    with factory.begin() as session:
        manifest = register_library_snapshot(session, manifest_path.resolve(), REPOSITORY_ROOT)
    print(f"registered {manifest.resource_count} CDISC Library resources")


def _register_manifests(settings: Settings, arguments: argparse.Namespace) -> None:
    if not arguments.standard_manifest and not arguments.terminology_manifest:
        raise SystemExit("at least one manifest is required")
    factory = create_session_factory(create_database_engine(settings))
    with factory.begin() as session:
        for manifest_path in arguments.standard_manifest:
            import_standard_manifest(session, manifest_path.resolve(), REPOSITORY_ROOT)
        for manifest_path in arguments.terminology_manifest:
            import_terminology_manifest(session, manifest_path.resolve(), REPOSITORY_ROOT)


def main() -> None:
    """Dispatch a credentialed snapshot or transactional registration operation."""

    arguments = _arguments()
    settings = get_settings()
    if arguments.command == "snapshot-all":
        _snapshot_all(settings, arguments.max_resources)
    elif arguments.command == "register-snapshot":
        _register_snapshot(settings, arguments.manifest)
    else:
        _register_manifests(settings, arguments)


if __name__ == "__main__":
    main()
