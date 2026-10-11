"""Export reviewed Aurinara study memberships for the shared control plane."""

import argparse
import json
from pathlib import Path
from uuid import UUID, uuid5

from sqlalchemy import select

from app.config import get_settings
from app.database import create_database_engine, create_session_factory
from app.studies.models import Study, StudyMembership


def export_memberships(mapping_path: Path, output_path: Path) -> None:
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    issuer = str(mapping["issuer"])
    users = {str(key): UUID(str(value)) for key, value in mapping["users"].items()}
    studies = {UUID(str(key)): UUID(str(value)) for key, value in mapping["studies"].items()}
    role_id = UUID(str(mapping["artifact_role_id"]))
    assigned_by = UUID(str(mapping["assigned_by"]))
    factory = create_session_factory(create_database_engine(get_settings()))
    with factory() as session:
        local_studies = list(session.scalars(select(Study)))
        memberships = list(session.scalars(select(StudyMembership)))

    missing_studies = {item.id for item in local_studies} - studies.keys()
    missing_users = {item.subject for item in memberships} - users.keys()
    if missing_studies or missing_users:
        raise ValueError(
            "reviewed mapping is incomplete: "
            f"studies={sorted(map(str, missing_studies))}, "
            f"subjects={sorted(missing_users)}"
        )

    permissions = [
        "artifact.study.read",
        "artifact.object.upload",
        "artifact.object.download",
        "artifact.object.reference",
        "artifact.package.build",
    ]
    assignments = []
    for item in memberships:
        canonical_study = studies[item.study_id]
        user_id = users[item.subject]
        assignment_id = uuid5(role_id, f"{user_id}:{canonical_study}:{item.role}")
        assignments.append(
            {
                "id": str(assignment_id),
                "user_id": str(user_id),
                "role_id": str(role_id),
                "study_id": str(canonical_study),
                "site_id": None,
                "assigned_by": str(assigned_by),
            }
        )
    snapshot = {
        "schema_version": "1.0.0",
        "users": [],
        "studies": [],
        "roles": [
            {
                "id": str(role_id),
                "product": "aurinara",
                "name": "Artifact Author",
                "description": "Access to Aurinara study artifacts and packaging",
                "permissions": permissions,
            }
        ],
        "assignments": assignments,
        "migration_metadata": {"issuer": issuer},
    }
    # The importer intentionally forbids migration-only metadata.
    snapshot.pop("migration_metadata")
    output_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mapping", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    export_memberships(args.mapping, args.output)


if __name__ == "__main__":
    main()
