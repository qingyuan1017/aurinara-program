from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.common.problems import ProblemException
from app.database import Base
from app.platform.models import PlatformProjectionEvent
from app.platform.projections import PlatformEvent, apply_platform_event
from app.studies.models import Study


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def _event(study_id, sequence, *, name="Canonical", status="active", event_id=None):
    return PlatformEvent(
        id=event_id or uuid4(),
        type=("platform.study.created.v1" if sequence == 1 else "platform.study.updated.v1"),
        aggregate_id=study_id,
        sequence=sequence,
        data={
            "study_id": str(study_id),
            "code": "CANONICAL-1",
            "display_name": name,
            "status": status,
        },
    )


def test_projection_is_idempotent_and_rejects_out_of_order_updates(session: Session) -> None:
    study_id = uuid4()
    created = _event(study_id, 1)
    assert apply_platform_event(session, created) is True
    session.commit()
    assert apply_platform_event(session, created) is False

    current = _event(study_id, 3, name="Current", status="archived")
    stale = _event(study_id, 2, name="Stale")
    assert apply_platform_event(session, current) is True
    assert apply_platform_event(session, stale) is True
    session.commit()

    study = session.get(Study, study_id)
    assert study is not None
    assert study.name == "Current"
    assert study.status == "active"
    assert study.platform_registry_status == "archived"
    assert study.platform_revision == 3
    assert (
        session.scalar(
            select(PlatformProjectionEvent.id).where(PlatformProjectionEvent.id == stale.id)
        )
        == stale.id
    )


def test_projection_refuses_code_collision(session: Session) -> None:
    session.add(Study(code="CANONICAL-1", name="Local", created_by="legacy"))
    session.commit()

    with pytest.raises(ProblemException) as caught:
        apply_platform_event(session, _event(uuid4(), 1))

    assert caught.value.code == "canonical_study_conflict"
