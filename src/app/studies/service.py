"""Study transaction and authorization service."""

from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.auth import Principal
from app.common.etag import require_matching_etag
from app.common.outbox import OutboxEvent
from app.common.problems import ProblemException
from app.studies.models import Study, StudyMembership
from app.studies.schemas import StudyCreate, StudyPatch


class StudyService:
    """Own study identity, membership checks, and transaction boundaries."""

    def create(self, session: Session, command: StudyCreate, principal: Principal) -> Study:
        """Create a study, owner membership, and outbox event atomically."""

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

    def require_access(self, session: Session, study_id: UUID, principal: Principal) -> Study:
        """Resolve a study only when the subject has membership."""

        statement = (
            select(Study)
            .join(StudyMembership, StudyMembership.study_id == Study.id)
            .where(Study.id == study_id, StudyMembership.subject == principal.subject)
        )
        study = session.scalar(statement)
        if study is None:
            raise ProblemException(
                status_code=404,
                code="study_not_found",
                title="Study not found",
                detail="The study does not exist or is not visible to this identity.",
            )
        return study

    def list(self, session: Session, principal: Principal) -> tuple[Study, ...]:
        """List studies visible to the authenticated subject."""

        statement = (
            select(Study)
            .join(StudyMembership, StudyMembership.study_id == Study.id)
            .where(StudyMembership.subject == principal.subject)
            .order_by(Study.created_at.desc(), Study.id.desc())
        )
        return tuple(session.scalars(statement))

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
        require_matching_etag(if_match, study.revision)
        if command.name is not None:
            study.name = command.name
        if command.status is not None:
            study.status = command.status
        study.revision += 1
        session.commit()
        return study
