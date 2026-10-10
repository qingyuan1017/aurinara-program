"""Typed module package-contribution boundary."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy.orm import Session

from app.artifacts.models import Artifact


@dataclass(frozen=True, slots=True)
class PackageContribution:
    """One exact artifact and its owning module's trusted archive path."""

    artifact_id: UUID
    archive_path: str
    required: bool = True


class PackageContributionCapability(Protocol):
    """Implemented by modules that may contribute to a submission package."""

    module_key: str

    def package_contributions(
        self,
        session: Session,
        study_id: UUID,
        artifacts: tuple[Artifact, ...],
        options: dict[str, object],
    ) -> tuple[PackageContribution, ...]: ...
