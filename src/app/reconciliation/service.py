"""Typed reconciliation execution boundary used by the durable worker."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy.orm import Session

from app.artifacts.storage import ObjectStorage


@dataclass(frozen=True, slots=True)
class ReconciliationEvaluation:
    issues: tuple[dict[str, object], ...]
    evidence: dict[str, object]


class ReconciliationCapability(Protocol):
    def resolve_reconciliation(
        self,
        session: Session,
        study_id: UUID,
        reconciliation_type: str,
        inputs: list[dict[str, object]],
        options: dict[str, object],
    ) -> dict[str, object]: ...

    def evaluate_reconciliation(
        self, payload: dict[str, object], storage: ObjectStorage
    ) -> ReconciliationEvaluation: ...


class ExactInputReconciliationCapability:
    """Foundation reconciler that records an exact-input comparison with no domain rules."""

    def resolve_reconciliation(
        self,
        session: Session,
        study_id: UUID,
        reconciliation_type: str,
        inputs: list[dict[str, object]],
        options: dict[str, object],
    ) -> dict[str, object]:
        del session
        return {
            "study_id": str(study_id),
            "reconciliation_type": reconciliation_type,
            "inputs": inputs,
            "options": options,
        }

    def evaluate_reconciliation(
        self, payload: dict[str, object], storage: ObjectStorage
    ) -> ReconciliationEvaluation:
        del storage
        return ReconciliationEvaluation(issues=(), evidence={"resolved": payload})
