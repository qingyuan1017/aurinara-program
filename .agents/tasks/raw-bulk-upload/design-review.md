# Design review: Bulk upload of raw datasets (revision 3)

Reviewer: design-review subagent (fresh read, no authoring context).
Scope reviewed: `.agents/tasks/raw-bulk-upload/design.md` (rev 3) against the worktree
`e:\Work\EDETEK\Python\aurinara\.worktrees\raw-bulk-upload` — AGENTS.md, `docs/api-contract.md`,
`src/app/raw/`, `src/app/artifacts/`, `src/app/execution/jobs.py`, `src/app/common/idempotency.py`,
`src/app/kernel/registry.py`, `workers/job_worker.py`, `src/app/reference/routes.py`, and the Alembic
migration chain.

This is revision 3 of a design that has already cleared two review rounds. I re-verified the
revision-2 and revision-3 claims against source rather than trusting the §12 change log. The design is
unusually thorough and most of its load-bearing claims are correct. The findings below are what remains.

## Verdict basis

Count of blocking findings: **0 HIGH, 0 MEDIUM** (3 NIT). Verdict: **APPROVED**.

---

## Verified assumptions (checked against source)

1. **`JobService.fail` requeues; `complete` is idempotent.** `src/app/execution/jobs.py`: `fail()` sets
   `status="queued"` and bumps `available_at` while `attempt_count < max_attempts`, only marking
   `failed` on exhaustion. `complete()` returns early if already `succeeded`, raises if not `running`.
   The design's §3.5 "a rejected batch is a completed job, never `fail()`" rule is correct and necessary.
2. **Artifact-build worker guards only `cancelled`, not terminal success/failure.**
   `workers/job_worker.py:_handle_artifact_build` checks `cancellation_requested_at`/`status=="cancelled"`
   at both T1 and T2 but has no `succeeded`/`failed` short-circuit. The design (§3.5, §7) correctly states
   its new terminal-state guard is additive, not inherited.
3. **Worker skeleton is T1 → untransacted middle → T2 with no middle transaction.** Confirmed in all three
   handlers (`_handle_artifact_build`, `_handle_reconciliation`, `_handle_validation`). The design's §3.6
   control flow and the §3.4 "no middle session to persist a live counter" rationale are accurate.
4. **`inspect_file`/`read_rows` issue codes.** `src/app/raw/files.py` raises exactly
   `raw_file_format_unsupported`, `raw_json_shape_invalid`, and `raw_physical_schema_invalid`
   (all `status_code=422`). §5.3's "forward verbatim" claim is correct.
5. **`read_rows` materializes all rows.** CSV builds `[list(row) for row in reader]`; JSON builds a full
   list; XLSX appends every row. NFR1's memory argument (bounded by the single largest file + accumulated
   snapshots) is sound.
6. **`_source` raises `422 raw_source_file_invalid` for missing/foreign-study** (`routes.py`). The refactor
   to `resolve_bulk_sources` returning issues is a real change of shape, correctly described.
7. **`_stale` fans out to Raw artifacts, Raw validation runs, and SDTM via STALENESS capability.** Confirmed
   in `routes._stale`. Relocating it to `service.stale_raw_consumers` preserves behavior.
8. **`create_dataset` maps `IntegrityError` → `409 duplicate_raw_dataset_code`** and bumps `raw.revision`
   once, calls `_stale`, adds `binding_for(...)`. The worker reproduction in §3.6/§7 matches.
9. **`binding_for`, `RawCapability`, `RAW_ARTIFACT_TYPES` live in `src/app/raw/service.py`.** Confirmed, so
   "the worker imports only service.py, never routes.py" is achievable; `routes.py` already imports from
   `service.py` today.
10. **`IdempotencyRecord` shape and unique constraint.** `src/app/common/idempotency.py`: columns
    `subject, route, study_id, key, request_fingerprint, resource_type, resource_id`, unique on
    `(subject, route, study_id, key)`. §4.2/§6 reuse plan fits exactly.
11. **`import_references` template.** `src/app/reference/routes.py`: `fingerprint(command.model_dump(mode="json"))`,
    idempotency replay/reuse, intra-batch duplicate-key `422`, single `commit()`, `IntegrityError`→`409`.
    The design's cited all-or-nothing template is accurate.
12. **`create_artifact_build` replay returns `202`.** Decorated `status_code=HTTP_202_ACCEPTED`; replay branch
    is a bare `return ArtifactBuildResponse.model_validate(prior)` with no `response.status_code` override and
    no new `Location`. Revision-3 Finding 1's "replay is 202" resolution is byte-accurate.
13. **Raw descriptor `entity_types=("raw_workbench","raw_dataset","raw_variable")`.** §3.3/§8's decision NOT
    to register `raw_dataset_import` as an entity type is consistent with the `ArtifactBuild`/`ReconciliationRun`/
    `ValidationRun` operation-row precedent (none are entity types).
14. **`ModuleRegistry._OWNED_COLLECTIONS` has no `job_types`.** Confirmed: entity_types, relationship_types,
    artifact_types, source_plan_types, reconciliation_types, event_types. §8's "job-type uniqueness is code
    review, not startup" is correct.
15. **Migration head is `20261009_0012` in the worktree.** No migration lists it as a `down_revision`;
    the chain terminates there. §6's `down_revision="20261009_0012"` is correct.
16. **`RawDatasetCreate.code` pattern** is `^[A-Za-z][A-Za-z0-9_]{0,63}$` and `RawPhysicalSnapshot` carries
    `schema_version`, `columns`, `row_count`. §4.3's "matches RawDatasetCreate" and the snapshot references hold.
17. **`RawReconcileRequest` uses `ge=1`.** Confirmed in `routes.py`; §5.4's rationale for mirroring it is real.
18. **`docs/api-contract.md` §4.4 async-operation table and the action-suffix table exist.** §10's doc-update
    points are real targets.

---

## Unverified / wrong assumptions

1. **`ArtifactService.create_source_file` is `async`, but §4.1's `create_source_files_bulk` is written as
   a sync `def`.** See Finding 1 — this is a real signature error, not a style nit, because the per-file loop
   it reuses is `await upload.read(...)`.
2. **`RawCapability.build_artifact_payload` signature.** The live method is
   `build_artifact_payload(self, session, aggregate_id, study_id, artifact_type)` — it does **not** accept
   `domain_code` (that kwarg exists on the `ArtifactBuilderCapability` Protocol in `builds.py`, not on the
   Raw handler). The design never relies on `domain_code` for Raw, so this is not a finding, only a note that
   the Raw handler is narrower than the Protocol.
3. Everything else the design asserts about existing code was verifiable and correct.

---

## Findings

### Finding 1 — NIT — §4.1: `create_source_files_bulk` must be `async` to reuse the streaming loop

`src/app/artifacts/service.py:create_source_file` is declared `async def` and streams with
`while chunk := await upload.read(1024 * 1024)`. The design's §4.1 shows the new method as
`ArtifactService.create_source_files_bulk(session, storage, settings, study_id, uploads, principal) -> list[SourceFile]`
(a plain `def`) while also saying it reuses "the exact per-file loop of `create_source_file`". A sync method
cannot `await upload.read(...)`, and the route handler is itself `async`. This is a signature inconsistency
that an implementer could trip on, but the fix is mechanical and does not change any decision or data flow.

Concrete fix: declare the method `async def create_source_files_bulk(...)` and the route handler `async def`,
mirroring `create_source_file`/`create_source_file` route exactly. State in §4.1 that both passes are inside
the async method and that `await upload.read` / `await upload.close()` are used per part.

### Finding 2 — NIT — §3.4 vs `docs/api-contract.md` §4.4: "progress phase" field divergence

`docs/api-contract.md` §4.4 says every async status resource "includes `id`, `status`, timestamps,
**progress phase**, cancellation state, input fingerprint, result artifact IDs, and a typed failure object".
The design (§3.4, §4.3) deliberately exposes only the lifecycle `status` plus a terminal-only
`files_inspected` counter and explicitly removes live-progress framing. That is a defensible engineering call
(there is no middle transaction to persist a phase), but it is a small, unacknowledged divergence from the
documented contract shape, and §10 lists api-contract.md as an update target without calling this out.

Concrete fix: in §10, add one line stating that the `raw-dataset-imports` status resource intentionally
reports progress solely through the lifecycle `status` (there is no separate `progress_phase` field, matching
the fact that `ValidationRun`/`ArtifactBuild` responses also carry no distinct phase field), and that
`docs/api-contract.md` §4.4 wording will be reconciled to say "progress phase (lifecycle status)".

### Finding 3 — NIT — §6: `entry_count`/`files_inspected` as plain non-defaulted vs defaulted columns

§6 lists `entry_count Integer not null` with no default and `files_inspected Integer not null default 0`.
`entry_count` is set at insert time by the create handler (fine), but the migration review checklist in §6
only mentions JSONB defaults and the `status` string; it does not state whether `entry_count` and
`files_inspected` get a DB-side server_default or rely on ORM-side `default=`. The rest of the design is
careful to say JSONB defaults are "ORM-side `default=` only (consistent with `artifact_builds`)". For the two
integer columns the intended mechanism is left implicit, which could lead to an autogenerated server_default
the review checklist is meant to catch.

Concrete fix: in §6 state explicitly that `files_inspected` uses ORM-side `default=0` with **no** DB
server_default (matching the `artifact_builds` idiom), and that `entry_count` has neither a default nor a
server_default because the create handler always supplies it; add both to the migration review checklist line.

---

## Summary

The two previously-blocking tensions are now genuinely resolved and verified against source: (a) the
job-success-vs-business-failure rule (§3.5) correctly uses `complete()` for content rejections and reserves
`fail()`+requeue for transient infra, matching `JobService` semantics; and (b) all-or-nothing commit is
honored by doing all object-store I/O in the untransacted middle and all writes in a single T2 transaction,
with no transaction held across storage. The two-phase upload decision (§3.1), the operation-row (not
entity-type) status resource (§3.3/§8), idempotency pinning (§4.2/§6), positional entry→source→snapshot
correlation with shared-file caching (§7), the terminal-state guard, cancellation lifecycle, migration head,
and the reused issue codes all check out against the worktree.

The three remaining findings are NITs: an `async` signature correction, a one-line contract-doc reconciliation
about the absent progress-phase field, and an explicit statement of the integer-column default mechanism in the
migration checklist. None blocks implementation. Verdict: APPROVED.
