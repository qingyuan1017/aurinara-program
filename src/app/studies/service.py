"""Study transaction and authorization service."""

import logging
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.auth import Principal
from app.common.etag import require_matching_etag
from app.common.logging import request_method_context, request_path_context
from app.common.outbox import OutboxEvent
from app.common.problems import ProblemException
from app.platform.authorization import get_platform_authorization
from app.studies.models import Study, StudyMembership
from app.studies.schemas import StudyCreate, StudyPatch

logger = logging.getLogger(__name__)

_PATH_MODULES = {
    "raw": "raw",
    "documents": "documents",
    "sdtms": "sdtm",
    "adams": "adam",
    "tlfs": "tlf",
    "terminology": "terminology",
    "reference": "reference",
    "review": "review",
    "reconciliations": "reconciliation",
    "executions": "execution",
    "validation": "validation",
    "artifacts": "artifacts",
    "packages": "packaging",
    "integrations": "integration",
}
_MANAGE_MODULES = {"standards", "terminology", "reference", "templates", "integration"}


class StudyService:
    """Own study identity, membership checks, and transaction boundaries."""

    def create(self, session: Session, command: StudyCreate, principal: Principal) -> Study:
        """Create a study, owner membership, and outbox event atomically."""

        if get_platform_authorization().mode == "enforced":
            raise ProblemException(
                status_code=409,
                code="canonical_study_managed_externally",
                title="Study is managed by the platform",
                detail="Create the canonical study through the platform control plane.",
            )

        study = Study(code=command.code, name=command.name, created_by=principal.subject)
        session.add(study)
        session.flush()
        session.add(
            StudyMembership(
                study_id=study.id,
                subject=principal.subject,
                role="owner",
                scopes=["*"],
            )
        )
        session.add(
            OutboxEvent(
                id=uuid4(),
                study_id=study.id,
                event_type="studies.created",
                schema_version="1.0.0",
                module_key="integration",
                subject_type="study",
                subject_id=study.id,
                subject_revision=study.revision,
                correlation_id=str(study.id),
                payload={"study_code": study.code},
            )
        )
        try:
            session.commit()
        except IntegrityError as error:
            session.rollback()
            raise ProblemException(
                status_code=409,
                code="duplicate_study_code",
                title="Study code already exists",
                detail=f"Study code '{command.code}' is already in use.",
            ) from error
        return study

    def require_access(
        self,
        session: Session,
        study_id: UUID,
        principal: Principal,
        *,
        action: str | None = None,
    ) -> Study:
        """Resolve a study only when the subject has membership."""

        if action is None:
            method = request_method_context.get()
            path_segments = (request_path_context.get() or "").strip("/").split("/")
            module = next(
                (_PATH_MODULES[segment] for segment in path_segments if segment in _PATH_MODULES),
                "study",
            )
            if method in {None, "GET", "HEAD", "OPTIONS"}:
                verb = "read"
            else:
                verb = (
                    "run"
                    if module in {"validation", "reconciliation", "packaging"}
                    else "manage"
                    if module in _MANAGE_MODULES or module in {"study", "execution"}
                    else "write"
                )
            action = f"aurinara.{module}.{verb}"
        study = session.get(Study, study_id)
        local_allowed = (
            session.scalar(
                select(StudyMembership.id).where(
                    StudyMembership.study_id == study_id,
                    StudyMembership.subject == principal.subject,
                )
            )
            is not None
        )
        gateway = get_platform_authorization()
        allowed = local_allowed
        if gateway.mode != "disabled":
            try:
                decision = gateway.decide(principal, action, study_id)
            except ProblemException:
                if gateway.mode == "enforced":
                    raise
                logger.warning(
                    "platform authorization unavailable in shadow mode",
                    extra={"study_id": str(study_id), "subject": principal.subject},
                )
                decision = None
            if decision is None:
                if study is None or not local_allowed:
                    raise ProblemException(
                        status_code=404,
                        code="study_not_found",
                        title="Study not found",
                        detail="The study does not exist or is not visible to this identity.",
                    )
                return study
            if gateway.mode == "shadow" and decision.allowed != local_allowed:
                logger.warning(
                    "platform authorization shadow mismatch",
                    extra={
                        "study_id": str(study_id),
                        "subject": principal.subject,
                        "local_allowed": local_allowed,
                        "platform_allowed": decision.allowed,
                        "policy_version": decision.policy_version,
                    },
                )
            # Canonical studies have no legacy Aurinara membership by design.
            # During shadow rollout, use a positive central decision for those
            # projected identities while preserving local enforcement for
            # legacy studies. This prevents a correctly projected canonical
            # study from disappearing merely because it was never created by
            # the legacy local membership workflow.
            if (
                gateway.mode == "shadow"
                and study is not None
                and study.platform_managed
                and decision.allowed
            ):
                allowed = True
            if gateway.mode == "enforced":
                allowed = decision.allowed
        if study is None or not allowed:
            raise ProblemException(
                status_code=404,
                code="study_not_found",
                title="Study not found",
                detail="The study does not exist or is not visible to this identity.",
            )
        return study

    def list(self, session: Session, principal: Principal) -> tuple[Study, ...]:
        """List studies visible to the authenticated subject."""

        gateway = get_platform_authorization()
        local_statement = (
            select(Study)
            .join(StudyMembership, StudyMembership.study_id == Study.id)
            .where(StudyMembership.subject == principal.subject)
            .order_by(Study.created_at.desc(), Study.id.desc())
        )
        local_records = tuple(session.scalars(local_statement))
        if gateway.mode == "disabled":
            return local_records

        all_records = tuple(
            session.scalars(select(Study).order_by(Study.created_at.desc(), Study.id.desc()))
        )
        if gateway.mode == "shadow":
            local_ids = {study.id for study in local_records}
            records = tuple(
                study
                for study in all_records
                if study.platform_managed and study.id not in local_ids
            )
        else:
            records = all_records
        decisions = gateway.decide_batch(
            principal,
            "aurinara.study.read",
            tuple(study.id for study in records),
        )
        centrally_allowed = tuple(
            study for study, decision in zip(records, decisions, strict=True) if decision.allowed
        )
        if gateway.mode == "shadow":
            visible_ids = {study.id for study in (*local_records, *centrally_allowed)}
            return tuple(study for study in all_records if study.id in visible_ids)
        return centrally_allowed

    def patch(
        self,
        session: Session,
        study_id: UUID,
        command: StudyPatch,
        principal: Principal,
        if_match: str | None,
    ) -> Study:
        """Update study metadata with optimistic concurrency."""

        study = self.require_access(session, study_id, principal)
        if get_platform_authorization().mode == "enforced":
            raise ProblemException(
                status_code=409,
                code="canonical_study_managed_externally",
                title="Study is managed by the platform",
                detail="Update canonical study fields through the platform control plane.",
            )
        require_matching_etag(if_match, study.revision)
        if command.status is not None:
            study.status = command.status
        study.revision += 1
        session.commit()
        return study
