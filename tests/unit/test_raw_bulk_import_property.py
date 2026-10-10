"""Property invariants for bulk dataset import all-or-nothing semantics."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from hypothesis import given
from hypothesis import strategies as st

from app.raw.contracts import RawDatasetImportEntry, RawPhysicalColumn, RawPhysicalSnapshot
from app.raw.models import RawDataset, RawDatasetFileBinding, RawWorkbench
from app.raw.service import ResolvedSource, apply_bulk_dataset_import
from tests.unit.test_raw_bulk_import import FakeRegistry, FakeSession

_CODE = st.from_regex(r"[A-Za-z][A-Za-z0-9_]{0,7}", fullmatch=True)


def _raw(study_id: UUID) -> RawWorkbench:
    raw = RawWorkbench(study_id=study_id, code="RAW", name="Raw")
    raw.id = uuid4()
    raw.revision = 1
    return raw


def _snapshot() -> RawPhysicalSnapshot:
    return RawPhysicalSnapshot(
        columns=(RawPhysicalColumn(name="A", physical_type="string", ordinal=1),),
        row_count=1,
    )


def _resolved(study_id: UUID) -> ResolvedSource:
    sid = uuid4()
    return ResolvedSource(
        id=sid,
        artifact_id=uuid4(),
        object_key=f"sha256/{sid}",
        sha256="0" * 64,
        filename="data.csv",
        study_id=study_id,
        size=10,
    )


@given(codes=st.lists(_CODE, min_size=1, max_size=12, unique_by=lambda c: c.upper()))
def test_unique_batch_yields_one_dataset_per_entry_and_one_bump(codes: list[str]) -> None:
    study_id = uuid4()
    raw = _raw(study_id)
    before = raw.revision
    session = FakeSession()
    registry = FakeRegistry()
    entries = [RawDatasetImportEntry(code=c, label="x", source_file_id=uuid4()) for c in codes]
    resolved: list[ResolvedSource | None] = [_resolved(study_id) for _ in codes]
    snapshots: list[RawPhysicalSnapshot | None] = [_snapshot() for _ in codes]

    created = apply_bulk_dataset_import(
        session,  # type: ignore[arg-type]
        registry,  # type: ignore[arg-type]
        raw=raw,
        entries=entries,
        resolved_sources=resolved,
        snapshots=snapshots,
        created_by="user-1",
    )

    datasets = [r for r in session.added if isinstance(r, RawDataset)]
    bindings = [r for r in session.added if isinstance(r, RawDatasetFileBinding)]
    assert len(created) == len(codes)
    assert len(datasets) == len(codes)
    assert len(bindings) == len(codes)
    assert raw.revision == before + 1


@given(
    codes=st.lists(_CODE, min_size=1, max_size=8, unique_by=lambda c: c.upper()),
    bad_index=st.integers(min_value=0, max_value=7),
)
def test_batch_with_an_invalid_entry_writes_zero_datasets(codes: list[str], bad_index: int) -> None:
    study_id = uuid4()
    raw = _raw(study_id)
    session = FakeSession()
    registry = FakeRegistry()
    entries = [RawDatasetImportEntry(code=c, label="x", source_file_id=uuid4()) for c in codes]
    # Simulate one position that failed resolution/inspection (None).
    index = bad_index % len(codes)
    resolved: list[ResolvedSource | None] = [_resolved(study_id) for _ in codes]
    snapshots: list[RawPhysicalSnapshot | None] = [_snapshot() for _ in codes]
    resolved[index] = None
    snapshots[index] = None

    raised = False
    try:
        apply_bulk_dataset_import(
            session,  # type: ignore[arg-type]
            registry,  # type: ignore[arg-type]
            raw=raw,
            entries=entries,
            resolved_sources=resolved,
            snapshots=snapshots,
            created_by="user-1",
        )
    except RuntimeError:
        raised = True

    # apply is never reached with a None in practice (the worker short-circuits);
    # the invariant we assert is that a None aborts before any dataset is created.
    assert raised
    assert not any(isinstance(r, RawDataset) for r in session.added)


def _unused(_: Any) -> None:  # pragma: no cover - import anchor
    return None
