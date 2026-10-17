"""Publish reviewed Aurinara artifact metadata into the central Repository.

The exporter never reads or copies object bytes. It uses the exact Platform
object-reference ID already persisted with each immutable Aurinara artifact.
"""

import argparse
from uuid import UUID

from sqlalchemy import select

from app.artifacts.models import Artifact, SourceFile
from app.config import get_settings
from app.database import create_database_engine, create_session_factory
from app.platform.objects import get_platform_objects
from app.raw.models import RawDataset, RawWorkbench


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Publish after validating every row")
    parser.add_argument("--study-id", type=UUID)
    args = parser.parse_args()

    settings = get_settings()
    engine = create_database_engine(settings)
    factory = create_session_factory(engine)
    try:
        with factory() as session:
            statement = (
                select(Artifact, SourceFile)
                .outerjoin(SourceFile, SourceFile.artifact_id == Artifact.id)
                .where(Artifact.status == "available")
                .order_by(Artifact.created_at, Artifact.id)
            )
            if args.study_id is not None:
                statement = statement.where(Artifact.study_id == args.study_id)
            rows = list(session.execute(statement))
            location_rows = session.execute(
                select(
                    RawDataset.current_source_file_id,
                    RawWorkbench.id,
                    RawWorkbench.code,
                    RawWorkbench.name,
                )
                .join(RawWorkbench, RawWorkbench.id == RawDataset.raw_id)
                .where(RawDataset.status != "retired")
                .order_by(RawWorkbench.code, RawWorkbench.id)
            ).all()

        source_locations: dict[UUID, dict[UUID, tuple[str, str]]] = {}
        for source_id, workbench_id, code, name in location_rows:
            source_locations.setdefault(source_id, {})[workbench_id] = (code, name)

        missing = [
            artifact.id
            for artifact, _ in rows
            if artifact.platform_object_id is None or artifact.platform_reference_id is None
        ]
        unsupported = [artifact.id for artifact, source_file in rows if source_file is None]
        if missing or unsupported:
            raise RuntimeError(
                "Backfill blocked: "
                f"missing Platform identity={len(missing)}, "
                f"artifacts without exact source classification={len(unsupported)}"
            )

        print(f"validated={len(rows)}")
        if not args.apply:
            print("dry_run=true; rerun with --apply to publish")
            return

        gateway = get_platform_objects()
        for artifact, source_file in rows:
            assert artifact.platform_reference_id is not None
            assert source_file is not None
            locations = source_locations.get(source_file.id, {})
            if len(locations) == 1:
                workbench_id, (code, name) = next(iter(locations.items()))
                solution = f"raw-workbench:{workbench_id}"
                solution_label = f"{code} · {name}"
            elif locations:
                solution = "shared-sources"
                solution_label = "Shared Sources"
            else:
                solution = "unassigned"
                solution_label = "Unassigned"
            gateway.publish_existing_repository_reference(
                artifact.platform_reference_id,
                {
                    "filename": artifact.filename,
                    "source_type": "source_file",
                    "source_id": str(source_file.id),
                    "source_status": artifact.status,
                    "module": artifact.module_key,
                    "solution": solution,
                    "solution_label": solution_label,
                    "purpose": "source-files",
                    "classification": "source-file",
                    "access": {
                        "read_action": "artifact.study.read",
                        "write_action": "artifact.study.write",
                    },
                    "provenance": {"artifact_id": str(artifact.id)},
                },
            )
        print(f"published={len(rows)}")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
