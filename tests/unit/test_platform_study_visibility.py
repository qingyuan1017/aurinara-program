from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.auth import Principal
from app.common.problems import ProblemException
from app.database import Base
from app.platform.authorization import Decision
from app.studies.models import Study, StudyMembership
from app.studies.service import StudyService


class _EnforcedGateway:
    mode = "enforced"

    def __init__(self, allowed_studies: set[UUID]) -> None:
        self.allowed_studies = allowed_studies

    def decide(self, principal: Principal, action: str, study_id: UUID) -> Decision:
        del principal, action
        return self._decision(study_id in self.allowed_studies)

    def decide_batch(
        self, principal: Principal, action: str, study_ids: tuple[UUID, ...]
    ) -> tuple[Decision, ...]:
        del principal, action
        return tuple(self._decision(study_id in self.allowed_studies) for study_id in study_ids)

    @staticmethod
    def _decision(allowed: bool) -> Decision:
        return Decision(
            allowed=allowed,
            decision_id=uuid4(),
            policy_version=7,
            expires_at=datetime.now(UTC),
            reason_code="permission_granted" if allowed else "permission_not_granted",
        )


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def test_enforced_mode_uses_central_decisions_for_all_studies(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    principal = Principal(subject="person-1", issuer="https://issuer", scopes=frozenset())
    canonical = Study(
        code="CANONICAL-1",
        name="Canonical",
        created_by="aurinara-platform",
        platform_managed=True,
        platform_revision=1,
        platform_registry_status="active",
    )
    legacy = Study(code="LEGACY-1", name="Legacy", created_by=principal.subject)
    session.add_all([canonical, legacy])
    session.flush()
    session.add(
        StudyMembership(
            study_id=legacy.id,
            subject=principal.subject,
            role="owner",
            scopes=["*"],
        )
    )
    session.commit()

    gateway = _EnforcedGateway({canonical.id})
    monkeypatch.setattr("app.studies.service.get_platform_authorization", lambda: gateway)

    service = StudyService()
    assert {study.id for study in service.list(session, principal)} == {canonical.id}
    assert service.require_access(session, canonical.id, principal).id == canonical.id


def test_enforced_mode_can_grant_access_without_local_membership(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    principal = Principal(subject="person-1", issuer="https://issuer", scopes=frozenset())
    legacy = Study(code="LEGACY-1", name="Legacy", created_by="another-user")
    session.add(legacy)
    session.commit()

    gateway = _EnforcedGateway({legacy.id})
    monkeypatch.setattr("app.studies.service.get_platform_authorization", lambda: gateway)

    assert StudyService().require_access(session, legacy.id, principal).id == legacy.id


def test_enforced_mode_denies_local_membership_without_central_access(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    principal = Principal(subject="person-1", issuer="https://issuer", scopes=frozenset())
    study = Study(code="CENTRAL-1", name="Central", created_by=principal.subject)
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
    session.commit()
    monkeypatch.setattr(
        "app.studies.service.get_platform_authorization", lambda: _EnforcedGateway(set())
    )

    with pytest.raises(ProblemException) as caught:
        StudyService().require_access(session, study.id, principal)
    assert caught.value.code == "study_not_found"
