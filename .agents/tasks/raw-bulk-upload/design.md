# Design: Bulk upload of raw datasets

> Revision 3. This document was revised across two review rounds. Revision 2 resolved the
> first-round findings (recorded in §12.1). Revision 3 resolves every finding in the
> second-round `.agents/tasks/raw-bulk-upload/design-review.json` (verdict
> `CHANGES_REQUESTED`, 3 MEDIUM + 2 NIT), recorded in §12.2. The body above is corrected.

## 1. Summary and requirements

### 1.1 What the user asked for

Support bulk upload for raw datasets. The confirmed scope (authoritative, from the
user) is a single feature that covers **both**:

1. **Bulk upload of raw source-file bytes** into object storage, and
2. **Bulk creation/binding of many `RawDataset` records** to those files.

The bulk import contract is a **JSON array** of dataset entries. The user expects
**large and many files**, so the dataset half of the feature **must be asynchronous**:
return `202 Accepted` with a status resource, backed by the durable PostgreSQL job
queue and the `workers/` package. No heavy work (byte streaming, checksum
verification, file inspection, variable initialization) runs inline in the API or
while a database transaction is held open.

### 1.2 Functional requirements

- **FR1 — Bulk byte upload.** A caller can upload many raw source files in one request
  and obtain one immutable, checksum-addressed `SourceFile` per file, reusing the
  existing `source_files` model, object layout, and checksum rules. User filenames
  remain display metadata only.
- **FR2 — Bulk dataset import (JSON array).** A caller can POST a typed, versioned JSON
  array of dataset entries to one Raw workbench. Each entry carries `code`, `label`,
  optional `description`, and a reference to an already-uploaded source file. The import
  creates one `RawDataset` + one `RawDatasetFileBinding` per entry, bumps the workbench
  revision once, and stales consumers exactly as the single-dataset create does.
- **FR3 — Asynchronous processing.** The dataset import returns `202 Accepted` and a
  status resource. A durable job performs file inspection and (optionally) variable
  initialization outside any held transaction.
- **FR4 — Validate completely before commit.** The entire array is validated (schema,
  intra-batch duplicate codes, source-file resolution, study ownership, file
  inspection) before any `RawDataset` is committed. Partial commits are prohibited:
  either every entry commits in one transaction or none does.
- **FR5 — Idempotency.** The import requires an `Idempotency-Key` header. Replaying the
  same key with the same canonical request returns the original run; reusing the key
  with a different request returns `409 idempotency_key_reused`.
- **FR6 — Typed failure reporting.** On validation failure the run terminates `failed`
  with per-entry issues expressed in the common validation issue model
  (`app.validation.contracts.ValidationIssue`); the status resource exposes them. No
  `RawDataset` rows are written.
- **FR7 — Status + cancellation.** The run is addressable by UUID with
  `queued | running | succeeded | failed | cancelled` lifecycle and supports cooperative
  cancellation while queued or running.
- **FR8 — Owned-entity registration.** The one new owned entity type
  (`raw_dataset_import`) is registered in the Raw `ModuleDescriptor`; startup validation
  fails on a duplicate owned entity type. The new **job type** is a worker/dispatch
  concern (there is no registry collection for job types — see §8); its uniqueness is a
  code-review guarantee, not a startup check.

### 1.3 Non-functional requirements

- **NFR1 — Large/many files, bounded memory.** Byte streaming and per-file inspection
  run in the worker, never inline. The API transaction for enqueue is short and
  O(array length) in metadata only. In the worker, **distinct** source files are
  inspected **one at a time** (cached by `source_file_id`, so entries sharing a file are
  inspected once; §7) and the stream is released before the next is opened; only the small
  per-file `RawPhysicalSnapshot` (column metadata + `row_count`) and any per-entry issues
  are retained across the batch, not raw rows. Because `read_rows` (`src/app/raw/files.py`) materializes an entire
  file's rows into memory while building a snapshot, total resident memory is bounded by
  the single largest referenced file plus the accumulated snapshots, not by the sum of
  all files. A new `raw_bulk_import_max_total_bytes` setting caps the summed byte size of
  all referenced files so a batch of very large files is rejected deterministically
  before inspection (see §5.3), and `raw_bulk_import_max_entries` caps the array length.
- **NFR2 — Safety.** Uploaded bytes and filenames are untrusted; size, media-type,
  checksum, and path controls are reused from the existing upload service. Object-store
  keys, credentials, and internal paths are never returned.
- **NFR3 — Determinism/auditability.** The run records a canonical input fingerprint,
  the resolved source-file IDs/checksums, and typed outcomes, consistent with existing
  immutable-evidence conventions.

### 1.4 Acceptance criteria

1. `POST /api/v1/studies/{study_id}/source-files:bulk` accepts a multipart request with
   many file parts and returns `201` with one `SourceFileResponse` per file in request
   order; a single rejected file (size/media type/filename) fails the whole request with
   `problem+json` and commits no `source_files` rows.
2. `POST /api/v1/raw/{raw_id}/datasets/import` with a JSON array and an `Idempotency-Key`
   returns `202 Accepted`, a `Location: /api/v1/raw-dataset-imports/{import_id}`, and a
   `RawDatasetImportResponse` with `status="queued"`.
3. Omitting `Idempotency-Key` returns `400 idempotency_key_required`; replaying the same
   key+body returns the original run with `202 Accepted` (the create route's declared
   status — no new `Location` header is required on replay); a different body with the
   same key returns `409 idempotency_key_reused`.
4. `GET /api/v1/raw-dataset-imports/{import_id}` returns the current status, and on
   success lists the created `raw_dataset` IDs; on failure it returns the full typed
   issue list and creates no datasets.
5. A batch whose entries contain a duplicate `code`, a `code` already present in the
   workbench, or an unresolvable/foreign-study `source_file_id` terminates `failed` with
   a per-entry issue and writes no `raw_datasets`/`raw_dataset_file_bindings` rows, and
   the backing job is marked `succeeded` (business failure is a completed job, never a
   requeue — see §3.6, §7).
6. On success the workbench `revision` is bumped exactly once, Raw validation runs and
   Raw/SDTM artifacts are staled exactly as a single-dataset create would, and each new
   dataset has an immutable `raw_dataset_file_bindings` row.
7. The worker streams and inspects files and performs optional variable initialization
   outside any open database transaction. Cancelling a `queued` import transitions it to
   `cancelled` **synchronously in the cancel handler** (so an unclaimed job never runs);
   cancelling a `running` import sets `cancellation_requested_at` and the worker observes
   it at the next transaction boundary. Neither path writes datasets.
8. The new Alembic migration applies up/down from an empty database and is reversible;
   descriptor startup validation passes with the new `raw_dataset_import` entity type
   registered and still fails if a duplicate owned entity type is injected.

### 1.5 Out of scope

- No change to single-dataset create/patch/initialize/validate/preview endpoints.
- No new file formats (`SUPPORTED_SUFFIXES` stays `.csv/.json/.xlsx`).
- No partial-success state, no AI/mapping/recommendation, no new RBAC/signatures.
- No bulk _patch_ or bulk _retire_ of existing datasets (create/bind only).
- No new registry collection for job types (deferred; see §8 and Finding 2 in §12).

## 2. Context: patterns this design reuses

The Raw and shared modules already contain every building block, and this design
composes them rather than inventing new mechanisms:

- **Immutable, checksum-addressed uploads.** `ArtifactService.create_source_file`
  (`src/app/artifacts/service.py`) validates filename + media type **first**, streams an
  `UploadFile` to a temp file enforcing `source_file_max_bytes`, computes SHA-256,
  derives the key via `checksum_object_key`, uploads via `storage.put_file`, then commits
  an `Artifact` + `SourceFile` pair, with a `finally` temp-file `unlink`. We reuse this
  shape per file in the bulk variant but defer the single commit (§5.1).
- **Single-dataset create.** `create_dataset` in `src/app/raw/routes.py` resolves the
  source via `_source`, inspects it with `inspect_file`, creates `RawDataset`, adds
  `binding_for(...)`, bumps `raw.revision`, calls `_stale(...)`, and maps
  `IntegrityError` → `409 duplicate_raw_dataset_code`. The async worker reproduces this
  for every entry inside one transaction, through an extracted service helper (§7, §8).
- **Async operation + durable job.** `ArtifactBuild` (`src/app/artifacts/models.py`) +
  `create_artifact_build` / `cancel_artifact_build` (`src/app/artifacts/builds.py`) +
  `job_worker._handle_artifact_build` are the template: a persistent operation row, a
  `jobs` row with `operation_id` unique and a `job_type` string, idempotency via
  `IdempotencyRecord`, `202 + Location`, and a worker that claims with
  `FOR UPDATE SKIP LOCKED` (`JobService.claim`), does expensive work between two short
  `factory.begin()` transactions, and transitions the operation idempotently.
- **Operation-row study ownership.** `ArtifactBuild`, `ReconciliationRun`, and
  `ValidationRun` are **not** registered as `entity_types`; their status endpoints
  enforce ownership directly via `StudyService.require_access` in `_require_build` and
  equivalents. The bulk-import status resource follows this operation-row precedent
  (§3.3, §8).
- **Atomic JSON array import.** `import_references` (`src/app/reference/routes.py`) +
  `ReferenceImportBatch` is the template for _all-or-nothing_ array imports with an
  intra-batch duplicate-key check and an idempotency replay that returns the prior
  created records. We follow its validate-then-commit shape, but move the commit into the
  worker because inspection of large files must not run inline.
- **Common issue model.** `ValidationIssue` (`app.validation.contracts`) and Raw's
  `_issue(...)` constructor in `routes.py` give the exact typed issue shape to reuse for
  per-entry failures.

The key tension — "validate completely before commit" vs. "async + object storage, no
held transaction" — is resolved in §3.6.

## 3. Decisions (resolved explicitly)

### 3.1 Byte upload: two-phase, not multipart-carrying-datasets. **CHOSEN: two phase.**

Two viable approaches were considered.

- **(A) Two-phase.** Clients first upload file bytes (one or many) to obtain immutable
  `source_file_id`s, then POST a JSON array of dataset entries that _reference_ those
  IDs. This matches the user's "JSON array" contract directly and the immutable,
  checksum-addressed `SourceFile` model: bytes become an immutable artifact _before_ any
  dataset references them, exactly as single-dataset create already requires
  (`RawDatasetCreate.source_file_id`).
- **(B) Multipart bulk.** One multipart request carries both file parts and a JSON
  metadata part. The API contract does allow multipart for upload endpoints, but binding
  this to the dataset array forces the heavy byte work to be entangled with the dataset
  transaction and makes idempotent async replay awkward (the uploaded bytes are consumed
  by the request and cannot be replayed).

**Decision: (A) two-phase.** It is the approach most consistent with AGENTS.md's
"source files immutable + checksum-addressed" and "stream uploads" rules, with the
existing `source_file_id` reference on `RawDatasetCreate`, and with idempotent async
replay (the dataset-import body is pure JSON referencing stable IDs, so the same body
replays deterministically). To make the _upload_ half genuinely bulk we add one new
synchronous multipart endpoint that uploads **many files in one request** (§4.1); each
file still becomes its own immutable `SourceFile`. The dataset-import endpoint (§4.2) is
the asynchronous JSON-array half.

### 3.2 Does the bulk upload endpoint need to be async? **CHOSEN: synchronous, bounded.**

Each file upload is independent, streamed to a temp file, and bounded by
`source_file_max_bytes`. The existing single-file upload is synchronous. Making the bulk
upload synchronous keeps it consistent and avoids a second async machine for work that is
already bounded per file. "Large/many files" is addressed by (a) bounding the number of
parts per request and (b) letting clients call the endpoint repeatedly (each call is
idempotent at the object layer because identical bytes map to the same checksum key). The
genuinely expensive, order-dependent work — per-file _inspection_ and _variable
initialization_ across the whole batch — lives in the async dataset import.

A per-request cap (`raw_bulk_upload_max_files`, default 50) and the existing per-file
byte cap keep any single synchronous request bounded; clients with thousands of files
loop over the endpoint. This endpoint does **not** hold a transaction open while
streaming: each file is validated (filename/media type) up front, then streamed to a
temp file and uploaded to object storage, and only the metadata rows are committed, once,
at the end (§5.1).

### 3.3 New persistent entity: `RawDatasetImport`. **CHOSEN: yes, as an operation row (not an owned `entity_type` for artifact building).**

The async operation needs a durable, addressable status resource with an immutable
request snapshot, lifecycle, result dataset IDs, and a typed failure. `ArtifactBuild` is
not reusable because its owner/artifact-type semantics and worker handler are specific to
artifact generation. `ReferenceImportBatch` is only success evidence, not a lifecycle
resource. We therefore add one new table, `raw_dataset_imports`, modeled on
`ArtifactBuild` (status, timestamps, `input_fingerprint`, `result_*_ids`, `failure`
JSONB) plus the request snapshot (`entries` JSONB) and the owning `raw_id`. Migration
shape in §6.

Crucially, `raw_dataset_imports` is an **operation row**, exactly like `artifact_builds`,
`reconciliation_runs`, and `validation_runs`. It is **not** added to the Raw
`ModuleDescriptor.entity_types`. Those three precedent operation tables are deliberately
not owned entity types; adding `raw_dataset_import` to `entity_types` would make it
resolvable through `resolve_build_input`/`RawCapability.resolve_entity` and let a client
POST `/artifact-builds` with `owner_type="raw_dataset_import"`, conflating a lifecycle
operation with a clinical entity. Study ownership for the status resource is instead
enforced directly in the import's own `GET`/`cancel` handlers via
`StudyService.require_access`, mirroring `_require_build` (§4.2, §8). The only new owned
entity type registered is therefore **none for the operation**; see §8 for exactly what
the descriptor changes.

### 3.4 Status resource shape and lifecycle. **CHOSEN: all-or-nothing, no partial state.**

Lifecycle: `queued → running → (succeeded | failed | cancelled)`. There is **no**
partial-success state, consistent with "validate completely before commit." Progress is
reported as the lifecycle `status` itself plus the static `entry_count`; the terminal
state carries either `result_dataset_ids` (success) or a `failure` object plus a full
`issues` array (failure).

**`files_inspected` is a terminal counter, not live progress.** The worker's control
flow (§3.6) opens transactions only at T1 (sets `running`) and T2 (sets the terminal
state); file inspection runs in the deliberately untransacted middle (§3.6 step 2), where
there is no session to commit an intermediate counter. We therefore do **not** advertise
`files_inspected` as live progress: it is written **once**, in the single T2 transaction,
and equals `entry_count` on a successful run (every entry's source was inspected) or the
number of files inspected before the first collected issue short-circuited the batch on a
failed run. A `GET` while the run is `running` returns the column's default `0`; a `GET`
on a terminal run returns the final count. Keeping it a terminal-only field avoids a
middle transaction that would otherwise have to be opened across object-store I/O, which
the no-held-transaction rule forbids. Coarse "how far along" is answered by the lifecycle
`status` (`queued`/`running`/terminal), which is the only observable progress signal. `problem+json` is used only for _synchronous request
rejection_ (bad JSON shape, missing idempotency key, workbench/study access, idempotency
reuse). Per-entry _content_ problems discovered during async validation are the common
issue model stored on the run and surfaced through the status `GET`, mirroring how a
`ValidationRun` carries `issues` rather than returning `422` from the worker. **The worker
never returns an HTTP status code**: every async outcome is a run state (§5.3).

### 3.5 Job-level success vs. business-level failure. **CHOSEN: a rejected batch is a _completed_ job.**

This is the decision the review flagged as blocking (Finding 1). The durable
`JobService.fail(job, ...)` (`src/app/execution/jobs.py`) **requeues** the job while
`attempt_count < max_attempts`. Therefore a deterministic content rejection (duplicate
code, unresolvable `source_file_id`, checksum mismatch, unsupported file, stale
revision, late `IntegrityError`) must **not** call `fail()` — doing so would re-claim and
re-run the batch up to `max_attempts` times and flap the status.

The rule, applied throughout §5.3 and §7:

- A run that finishes validation and is **rejected for content reasons** is a
  _successfully processed job with a `failed` business result_. The worker sets
  `import.status="failed"`, writes the typed `issues`/`failure`, and calls
  `JobService().complete(job)` — never `fail()`. The job is terminal and never requeued.
- `JobService().fail(job, ...)` (which requeues, then marks the job `failed` only on
  exhausted attempts) is reserved for **transient infrastructure errors** (object store
  unavailable, DB deadlock, unexpected exception). The worker's outer boundary and
  `_record_failure` map the import row to `failed` only when the job itself reaches
  `failed` (attempts exhausted), exactly as `_record_failure` already does for
  `artifact_build`.
- **Terminal-state guard.** At both transaction boundaries (T1 and T2), before doing any
  work, the handler re-reads the import row and if `import.status in {"succeeded",
"failed", "cancelled"}` it calls `JobService().complete(job)` and returns. This makes an
  at-least-once redelivery after a committed terminal state a true no-op (the cited
  `_handle_artifact_build` template guards only `cancelled`; our handler must add the
  `succeeded`/`failed` short-circuit explicitly — it is new, not inherited).

### 3.6 Reconciling "validate completely before commit" with async + object storage.

The worker performs two short transactions around the expensive middle (same skeleton as
`_handle_artifact_build`, with the §3.5 rules applied):

1. **T1 (short):** `JobService.claim` has already committed the claim. Load the import +
   job. Apply the terminal-state guard (§3.5). If `cancellation_requested_at` is set or
   `import.status == "cancelled"`, set `import.status="cancelled"`, `completed_at`, call
   `JobService().complete(job)`, return. Otherwise set `import.status="running"`,
   `started_at`, read the immutable request snapshot (entries + referenced
   `source_file_id`s), call `resolve_bulk_sources` to resolve each `SourceFile`'s
   `object_key`/`sha256`/`filename`/`study_id`/`size` into a plain `ResolvedSource` value
   (collecting a `raw_source_file_invalid` issue, and leaving `None` at that position, for
   any entry whose source is missing or foreign-study — but **not** raising), yielding a
   `list[ResolvedSource | None]` positionally aligned to `entries` (§7). Capture the
   current `raw.revision`, then **commit/close**. No file bytes are touched here.
2. **Middle (no transaction):** verify the summed `size` of resolved files against
   `raw_bulk_import_max_total_bytes` (fail the run with `raw_bulk_import_too_large` if
   exceeded, before any inspection). Then, iterating positions in entry order and
   inspecting each **distinct** `source_file_id` **once** (cache by `source_file_id`, so
   entries sharing a file cost one stream), open the object stream **one file at a time**,
   verify the SHA-256 against the stored checksum (as `validate_raw` does), and call
   `inspect_file(stream, filename)`; close the stream before opening the next. Build a
   `list[RawPhysicalSnapshot | None]` positionally aligned to `entries`: the cached
   snapshot at each position whose source resolved and inspected cleanly, `None` at any
   position that already failed resolution or whose inspection raised a typed issue.
   Retain only these per-position snapshots and the accumulated issues — never raw rows.
   This is where "validate completely" happens — every entry is checked and inspected
   before anything is written.
3. **T2 (short, atomic):** re-open a transaction. Re-apply the terminal-state and
   cancellation guards. If `expected_raw_revision` was pinned and `raw.revision` changed
   since T1, terminate the run `failed` with issue code `stale_raw_revision` and
   `complete(job)`. If **any** issue was collected (any `None` in the aligned
   source/snapshot lists), set the import `failed` with the full issue list and
   `complete(job)`, writing **no** datasets — `apply_bulk_dataset_import` is **not**
   called. Otherwise (issue list empty, so every position in the aligned
   `entries`/`resolved_sources`/`snapshots` lists is non-`None`), call
   `apply_bulk_dataset_import(session, registry, raw=raw, entries=..., resolved_sources=...,
snapshots=..., created_by=...)` to create every `RawDataset` + `RawDatasetFileBinding`
   by position, optionally initialize variables from each position's snapshot, bump the
   workbench `revision` **once**, call the shared staleness routine, set the import
   `succeeded` with `result_dataset_ids` and `files_inspected` (the count of distinct
   files inspected), and `complete(job)`. A late `IntegrityError` (a
   code created concurrently between T1 and T2) rolls back the T2 transaction; a fresh
   transaction then marks the run `failed` with `duplicate_raw_dataset_code` and
   `complete(job)` — still all-or-nothing, still a completed job.

Because object storage is only read in the untransacted middle and bytes are never
written by this feature (datasets only _reference_ existing immutable files), no
transaction is ever held open across object-store I/O.

## 4. API design

All routes are mounted under `app_api_prefix` (`/api/v1`) exactly as the existing Raw
routes are (the Raw router is included at the app prefix in `main.py`). Request/response
models are strict Pydantic 2 (`extra="forbid"`), `snake_case`, UUIDs, RFC 3339 UTC.

### 4.1 Bulk source-file upload (synchronous)

```
POST /api/v1/studies/{study_id}/source-files:bulk      (multipart/form-data)
  parts: files: UploadFile[]   (1..raw_bulk_upload_max_files)
  -> 201 Created
     { "items": [ SourceFileResponse, ... ] }           # one per file, request order
```

Added to `src/app/artifacts/routes.py` next to `create_source_file`. A new method
`ArtifactService.create_source_files_bulk(session, storage, settings, study_id, uploads,
principal) -> list[SourceFile]` performs an explicit two-pass flow so the batch is atomic
and orphan blobs are minimized (§5.1):

1. **Metadata pass (no I/O to object store):** `require_access`, then for every part
   validate the display filename via `_safe_display_filename` and the media type against
   the `source_file_allowed_media_types` allow-list. Any failure rejects the **whole**
   request (`422`/`415`) before a single byte is streamed. (A part count outside
   `1..raw_bulk_upload_max_files` is rejected here too.)
2. **Upload pass:** for every part, strictly **one at a time**, stream to its own temp
   file enforcing `source_file_max_bytes` (reusing the exact per-file loop of
   `create_source_file`), compute SHA-256, derive the key via `checksum_object_key`,
   `storage.put_file`, and `unlink` the temp file in a `finally` — **before the next part
   is streamed**. At most one temp file exists at any moment, so local disk is bounded to
   a single `source_file_max_bytes` regardless of `raw_bulk_upload_max_files`; parts are
   never staged concurrently to disk. Stage (do not commit) only the small `Artifact` +
   `SourceFile` metadata rows in memory.
3. **Single commit:** `session.commit()` once for all staged rows.

Deduplication is natural: identical bytes across files resolve to the same `object_key`;
distinct `SourceFile` rows may share one `object_key`, which the immutable model already
permits. A `413` (size overflow, only knowable mid-stream) or an object-store error in
the upload pass can leave orphan **bytes** (content-addressed, immutable, dedup-safe,
unreferenced) but writes **no** `source_files`/`artifacts` rows — compliant with "do not
publish partial files as available artifacts," since an unreferenced blob is not a
published artifact.

Why a `:bulk` suffix rather than overloading `POST .../source-files`: the single-file
endpoint takes `file: UploadFile`; a list part is a distinct contract, and a suffixed
collection action keeps the OpenAPI operation IDs unambiguous and backward compatible.

### 4.2 Bulk dataset import (asynchronous, JSON array)

```
POST /api/v1/raw/{raw_id}/datasets/import              (application/json)
  headers: Idempotency-Key (required)
  body: RawDatasetImportRequest  (JSON array envelope)
  -> 202 Accepted
     Location: /api/v1/raw-dataset-imports/{import_id}
     RawDatasetImportResponse  (status="queued")

GET  /api/v1/raw-dataset-imports/{import_id}           -> 200 RawDatasetImportResponse
POST /api/v1/raw-dataset-imports/{import_id}/cancel    -> 200 RawDatasetImportResponse
```

These live in `src/app/raw/routes.py`, with the worker handler registered in
`workers/job_worker.py`.

**Create handler (thin).** authenticate; `_raw(session, registry, raw_id, principal)` to
require workbench + study access; require `Idempotency-Key` (else `400
idempotency_key_required`); compute `input_fingerprint = fingerprint(
command.model_dump(mode="json"))` using `app.common.canonical.fingerprint` (a 64-char
sha256 hex, compatible with `IdempotencyRecord.request_fingerprint`); run the idempotency
replay/reuse check against an `IdempotencyRecord` scoped to
`route="raw-dataset-import"`, `study_id=raw.study_id`, `subject=principal.subject`,
`key=idempotency_key` — same shape as `create_artifact_build`:

- No existing record → create `RawDatasetImport` + a `Job` + the `IdempotencyRecord`
  (with `study_id=raw.study_id`, `request_fingerprint=input_fingerprint`,
  `resource_type="raw_dataset_import"`, `resource_id=import.id`) in one transaction,
  commit, set `Location`, return `202`.
- Existing record, same `request_fingerprint` → return the prior
  `RawDatasetImportResponse` (replay). This replay returns under the route's declared
  `status_code=202` decorator exactly as `create_artifact_build` does — the handler does
  **not** override `response.status_code`, so FastAPI emits `202 Accepted` on replay (not
  `200`), and no new `Location` header is set. This matches the cited template byte-for-byte.
- Existing record, different `request_fingerprint` → `409 idempotency_key_reused`.

The create handler does **not** require `If-Match` on the workbench: this is a
collection-creating async operation (like `create_artifact_build`), not a direct edit of
the mutable workbench aggregate. The optional `expected_raw_revision` body field
(mirroring `RawReconcileRequest`) is the explicit staleness control; if the caller pins
it and the workbench revision moves before T2, the **run terminates `failed` with issue
code `stale_raw_revision`** — the worker never returns `409`. The pin is `None` by
default; because `RawWorkbench.revision` bumps on nearly every Raw edit (dataset/variable
create/patch/delete, initialize, `patch_raw`), any concurrent edit between enqueue and T2
invalidates the pin, so callers should pin only when they need strict isolation (§5.3).

**Cancel handler.** Mirror `cancel_artifact_build` exactly: resolve the import row and
`StudyService.require_access`; if `import.status not in {"queued","running"}`, raise
`409 invalid_lifecycle_transition`; otherwise set `import.status="cancelled"`,
`completed_at=utc_now()`, look up the `Job` by `operation_id == import.id` and set its
`cancellation_requested_at=utc_now()`; commit; return the response. Setting the import row
to `cancelled` **synchronously** is what guarantees a `queued`-but-never-claimed import
reaches `cancelled` (AC7); the worker's T1/T2 cancellation guards then `complete(job)` for
a mid-flight job.

**Get handler.** resolve the import row and `StudyService.require_access`; return the
response. (No `entity_types` registration; ownership is enforced here directly — §3.3.)

### 4.3 Request/response contracts (`src/app/raw/contracts.py`)

```python
class RawDatasetImportEntry(StrictModel):
    code: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,63}$")   # matches RawDatasetCreate
    label: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    source_file_id: UUID
    initialize_variables: bool = False                            # per-entry opt-in

class RawDatasetImportRequest(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"                    # versioned, per AGENTS
    expected_raw_revision: int | None = Field(default=None, ge=1)
    entries: tuple[RawDatasetImportEntry, ...] = Field(
        min_length=1, max_length=RAW_BULK_IMPORT_MAX_ENTRIES
    )

    @model_validator(mode="after")
    def unique_codes(self): ...   # intra-batch duplicate codes -> 422 at request parse
```

`entries` is the JSON array the user asked for, wrapped in a small envelope that carries
`schema_version` (AGENTS requires every versioned structure to carry an explicit schema
version) and the optional staleness pin. `initialize_variables` lets the caller request
the same metadata fill that the single-dataset `initialize_variables` endpoint performs,
done in the worker. Intra-batch duplicate codes are caught at parse time (cheap, no I/O);
duplicates against _existing_ workbench datasets and unresolvable source files are caught
in the worker (they need DB/object-store reads) and reported as per-entry issues.

```python
ImportStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]

class RawDatasetImportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    raw_id: UUID
    study_id: UUID
    status: ImportStatus              # closed literal, not str (AGENTS: enums for finite states)
    schema_version: str
    entry_count: int
    files_inspected: int                 # terminal-only counter (§3.4): 0 until T2, then final
    input_fingerprint: str
    result_dataset_ids: list[UUID]
    issues: list[ValidationIssue]     # common issue model; empty unless failed
    failure: dict[str, object] | None
    started_at: datetime | None
    completed_at: datetime | None
    created_by: str
    created_at: datetime
```

`status` is a closed `Literal` so the OpenAPI schema is accurate (the persisted column
stays `String(32)`, matching `artifact_builds`). `issues` is typed as the common
`ValidationIssue` model so the transport contract and OpenAPI carry the full issue fields;
the worker stores issues as dicts in JSONB and the response validates them back into
`ValidationIssue` on read (`ValidationIssue.model_validate` per row in the handler, or a
`field_validator` on the response). The response never includes object-store keys, source
bytes, or internal paths.

## 5. Error handling (per operation)

### 5.1 Bulk upload endpoint (`:bulk`)

| Failure                                 | Status                                                       | Recoverable?    | Caller receives                                                            | Logged           |
| --------------------------------------- | ------------------------------------------------------------ | --------------- | -------------------------------------------------------------------------- | ---------------- |
| No files / too many files               | 422 `raw_bulk_upload_empty` / 413 `raw_bulk_upload_too_many` | yes             | problem+json; nothing uploaded or committed                                | no               |
| Disallowed media type (metadata pass)   | 415 `unsupported_media_type`                                 | yes             | problem+json; nothing uploaded or committed                                | no               |
| Unsafe/empty filename (metadata pass)   | 422 `invalid_filename` / `filename_required`                 | yes             | problem+json; nothing uploaded or committed                                | no               |
| A file exceeds byte limit (upload pass) | 413 `source_file_too_large`                                  | yes             | problem+json; whole batch rejected, no rows committed; temp files unlinked | no               |
| Object-store upload fails               | 503 `object_store_unavailable`                               | retry by client | problem+json; no rows committed; temp files unlinked                       | yes (no secrets) |
| Study access denied                     | 403 / 404                                                    | no              | problem+json                                                               | no               |

All reuse the exact checks in `create_source_file` (`_safe_display_filename`, the
allow-list, the per-file byte cap, the `finally`-unlink). Because filename/media-type
validation happens in the metadata pass **before** any byte streaming, the only failures
that can leave an orphan blob are a mid-stream `413` or an object-store error during the
upload pass; neither writes `source_files`/`artifacts` rows.

### 5.2 Dataset-import create endpoint

| Failure                                            | Status                                         | Recoverable? | Caller receives                 | Logged |
| -------------------------------------------------- | ---------------------------------------------- | ------------ | ------------------------------- | ------ |
| Malformed JSON / extra fields / bad `code` pattern | 422                                            | yes          | problem+json (FastAPI/Pydantic) | no     |
| Intra-batch duplicate code                         | 422 `raw_bulk_import_duplicate_code`           | yes          | problem+json                    | no     |
| Missing `Idempotency-Key`                          | 400 `idempotency_key_required`                 | yes          | problem+json                    | no     |
| Key reused with different body                     | 409 `idempotency_key_reused`                   | yes          | problem+json                    | no     |
| Key replay, same body                              | returns prior `RawDatasetImportResponse` (202) | n/a          | prior run                       | no     |
| Workbench/study not found or denied                | 404 `raw_not_found` / 403                      | no           | problem+json                    | no     |

### 5.3 Worker (async) outcomes — all become run state, never HTTP

Every row below ends with `JobService().complete(job)` (business failures are _completed_
jobs, never requeued — §3.5). `fail()` (requeue) is used **only** for the transient-infra
row.

| Condition                                                                 | Terminal run state                                                    | Job call                                           | Issue code(s)                                            | Datasets written |
| ------------------------------------------------------------------------- | --------------------------------------------------------------------- | -------------------------------------------------- | -------------------------------------------------------- | ---------------- |
| `source_file_id` missing / foreign study                                  | `failed`                                                              | `complete`                                         | `raw_source_file_invalid`                                | none             |
| Summed file bytes over cap                                                | `failed`                                                              | `complete`                                         | `raw_bulk_import_too_large`                              | none             |
| Checksum mismatch on bound file                                           | `failed`                                                              | `complete`                                         | `raw_source_checksum_mismatch`                           | none             |
| Unsupported file suffix                                                   | `failed`                                                              | `complete`                                         | `raw_file_format_unsupported`                            | none             |
| Invalid physical schema / JSON shape                                      | `failed`                                                              | `complete`                                         | `raw_physical_schema_invalid` / `raw_json_shape_invalid` | none             |
| Code already exists in workbench                                          | `failed`                                                              | `complete`                                         | `duplicate_raw_dataset_code`                             | none             |
| Workbench revision moved (if pinned)                                      | `failed`                                                              | `complete`                                         | `stale_raw_revision`                                     | none             |
| Late `IntegrityError` in T2                                               | `failed`                                                              | `complete`                                         | `duplicate_raw_dataset_code`                             | none (rollback)  |
| Cancellation requested                                                    | `cancelled`                                                           | `complete`                                         | —                                                        | none             |
| Transient infra error (object store down, deadlock, unexpected exception) | stays `running`/`queued`; becomes `failed` only on exhausted attempts | `fail` (requeue) → `_record_failure` on exhaustion | `job_processing_failed` / typed infra code               | none             |
| All entries valid                                                         | `succeeded`                                                           | `complete`                                         | —                                                        | one per entry    |

The three content codes `raw_file_format_unsupported`, `raw_physical_schema_invalid`,
and `raw_json_shape_invalid` are the **exact** codes raised by `inspect_file`/`read_rows`
in `src/app/raw/files.py` (verified); the worker forwards `error.code`/`error.detail`
verbatim, exactly as `validate_raw` does, rather than inventing new codes.
`raw_source_checksum_mismatch` is Raw's existing checksum code; `duplicate_raw_dataset_code`
is the existing single-create conflict code; `raw_source_file_invalid` is the existing
`_source` code. `raw_bulk_import_too_large` and `stale_raw_revision` are new codes owned
by this feature. The worker boundary logs unexpected exceptions with the job ID and a
non-sensitive type name only, exactly as the existing `_process_job` does — no filenames,
bytes, or secrets.

### 5.4 External-input validation rules

- **Entry `code`**: required, pattern `^[A-Za-z][A-Za-z0-9_]{0,63}$` (identical to
  `RawDatasetCreate`), unique within the batch (parse-time, `422
raw_bulk_import_duplicate_code`) and against the workbench (worker, `failed` run with
  `duplicate_raw_dataset_code`).
- **`label`**: required, 1–255 chars. **`description`**: optional, ≤4000.
- **`source_file_id`**: required UUID; must resolve to a `SourceFile` in the same study
  (worker check, mirroring `_source` semantics). Failure → `failed` run with
  `raw_source_file_invalid`.
- **`entries`**: 1..`raw_bulk_import_max_entries` (new setting, default 500). Over limit →
  `422` at parse time.
- **`expected_raw_revision`**: optional int, `ge=1`. The bound deliberately mirrors
  `RawReconcileRequest` (which also uses `ge=1`) for contract consistency. When present,
  the worker compares it for **equality** against the live `raw.revision` in T2: if
  `raw.revision != expected_raw_revision` the run terminates `failed` with
  `stale_raw_revision` (no HTTP `409` from the worker). `None` disables the pin (default).
- **Summed referenced file bytes**: ≤ `raw_bulk_import_max_total_bytes` (new setting,
  default 2 GiB), checked in the worker middle before inspection. Over cap → `failed` run
  with `raw_bulk_import_too_large`.
- **Upload parts**: 1..`raw_bulk_upload_max_files` (new setting, default 50); each bounded
  by the existing `source_file_max_bytes` and `source_file_allowed_media_types`.

New settings added to `src/app/config.py` (the settings layer, no env reads elsewhere):
`raw_bulk_upload_max_files: int = 50`, `raw_bulk_import_max_entries: int = 500`,
`raw_bulk_import_max_total_bytes: int = 2_147_483_648`.

### 5.5 Invariant ownership

- **All-or-nothing commit** is owned by the worker's single T2 transaction (service
  layer), not the API — because the expensive validation precedes it and must not hold a
  lock.
- **Workbench revision bumps once per import** is owned by the worker T2 and matches the
  single-dataset invariant (one create = one bump). Staleness of Raw validation runs and
  Raw/SDTM artifacts is delegated to the shared staleness helper (moved to the service
  layer — §7, §8) so the bulk path cannot drift from the single path.
- **Study ownership** is enforced at the API (`_raw` → `studies.require_access`) for the
  request, and re-checked in the worker when resolving each `SourceFile` (study match) via
  the shared service-layer source resolver (§7, §8), consistent with "enforce study
  ownership at service boundaries."
- **Immutability of bytes** is owned by `ArtifactService`/object storage; this feature
  only references existing immutable files and writes immutable `RawDatasetFileBinding`
  rows.

## 6. Persistence and migration

New table `raw_dataset_imports` (owned by Raw), modeled on `artifact_builds`:

```
raw_dataset_imports
  id                 UUID  PK
  raw_id             UUID  FK raw_workbenches.id      ondelete=RESTRICT, index
  study_id           UUID  FK studies.id             ondelete=RESTRICT, index
  schema_version     String(16)  not null
  status             String(32)  not null default 'queued'   # queued|running|succeeded|failed|cancelled
  entries            JSONB       not null                     # immutable request snapshot (list of entry dicts)
  input_fingerprint  String(64)  not null
  entry_count        Integer     not null
  files_inspected    Integer     not null default 0
  result_dataset_ids JSONB       not null default list
  issues             JSONB       not null default list
  failure            JSONB       nullable
  started_at         DateTime(tz) nullable
  completed_at       DateTime(tz) nullable
  created_by         String(255) not null
  created_at         DateTime(tz) not null default utc_now
```

- SQLAlchemy model `RawDatasetImport` added to `src/app/raw/models.py` (same column
  idioms as `RawDataset`/`ArtifactBuild`; `UuidPrimaryKey` mixin; explicit
  `JSONB default=list`/`dict` at the ORM layer; `status` as plain `String(32)` matching
  the existing operation tables).
- One new Alembic migration appended to the single ordered history, with
  `down_revision = "20261009_0012"` (verified current head: the linear chain terminates
  at `20261009_0012`, which no other migration lists as a parent). The migration creates
  the table and its two indexes (`ix_raw_dataset_imports_raw_id`,
  `ix_raw_dataset_imports_study_id`) with explicit constraint names following the existing
  naming (`fk_...`, `ix_...`), `ondelete=RESTRICT` FKs, and a complete `downgrade()` that
  drops indexes then the table. Review checklist: JSONB defaults are ORM-side `default=`
  only (consistent with `artifact_builds`, which sets no DB-side default); the enum-like
  `status` is a plain `String` (no PG enum); reversibility verified by applying up/down
  from an empty DB in integration tests.

No change to `raw_datasets`, `raw_variables`, `raw_dataset_file_bindings`, or
`source_files` schemas — the import _writes_ existing shapes.

No new `IdempotencyRecord` schema is needed; the import reuses the existing table with
`route="raw-dataset-import"`, `resource_type="raw_dataset_import"`,
`study_id=raw.study_id`, and `request_fingerprint=fingerprint(command.model_dump(
mode="json"))` (§4.2).

## 7. Jobs and worker

- New `job_type = "raw_dataset_import"`. The create handler enqueues a `Job` with
  `payload={"import_id": str(import.id)}`, `operation_id=import.id` (unique; enables the
  cancel lookup and `_record_failure` branch), and `max_attempts=settings.job_max_attempts`
  (3), mirroring `create_artifact_build`.
- `workers/job_worker.py` gains `_handle_raw_dataset_import(factory, registry, storage,
job_id)` and registers `"raw_dataset_import"` in (a) the `claim(..., job_types=...)`
  tuple in `main()`, (b) the `_process_job` dispatch, and (c) a new `_record_failure`
  branch that marks the `RawDatasetImport` `failed` **only when `job.status == "failed"`**
  (attempts exhausted), exactly as the `artifact_build` branch does.
- The handler follows the T1 / untransacted-middle / T2 structure in §3.6 and the
  job-success-vs-business-failure rules in §3.5. The dataset creation in T2 calls the
  **same** service helpers the single-dataset route uses, through an extracted Raw service
  function that returns typed issues instead of raising HTTP-shaped exceptions:

```python
# src/app/raw/service.py  (new module-level functions, not route code)

def resolve_bulk_sources(
    session, *, study_id, entries,
) -> tuple[list[ResolvedSource | None], list[ValidationIssue]]:
    """Resolve each entry's SourceFile within the study.

    Returns a list POSITIONALLY ALIGNED to ``entries`` (index i -> entries[i]):
    a ``ResolvedSource`` where the source exists in the study, or ``None`` where a
    ``raw_source_file_invalid`` issue was collected for that position. The second
    tuple element is the accumulated issue list (empty on full success). Resolution
    never raises for a missing/foreign source; it records the typed issue instead."""

def apply_bulk_dataset_import(
    session, registry, *, raw, entries, resolved_sources, snapshots, created_by,
) -> list[RawDataset]:
    """Create every dataset+binding atomically. Caller commits once.

    PRECONDITION: this function is only called when the collected issue list is empty,
    so ``resolved_sources`` and ``snapshots`` contain no ``None`` entries and every
    one of ``entries``, ``resolved_sources``, ``snapshots`` is the same length and
    POSITIONALLY ALIGNED by entry index (index i describes entries[i]). The function
    asserts these three invariants on entry (length equality, no ``None``) and raises
    an internal error if violated — it is never a recoverable content path.

    Mirrors create_dataset per index: RawDataset(entries[i]) -> binding_for(
    resolved_sources[i]) -> optional variable init from snapshots[i] -> ... after all
    entries: a single raw.revision bump -> stale_raw_consumers. Returns the created
    datasets in entry order."""

def stale_raw_consumers(session, registry, raw) -> None:
    """Fan-out staleness: Raw artifacts, Raw validation runs, and SDTM via the
    STALENESS capability handler. (Relocated from routes._stale.)"""
```

**Correlation contract (positional, index-aligned).** `entries`, `resolved_sources`, and
`snapshots` are three equal-length lists aligned by entry index: position `i` always
describes `entries[i]`. `resolve_bulk_sources` returns `list[ResolvedSource | None]` with
`None` at every position whose source was missing or foreign-study (and a
`raw_source_file_invalid` issue recorded for that position). The untransacted middle
(§3.6 step 2) then produces `list[RawPhysicalSnapshot | None]` aligned the same way:
`None` at a position that already failed source resolution or whose inspection raised a
typed issue; a snapshot otherwise. `apply_bulk_dataset_import` is reached **only when the
accumulated issue list is empty**, which guarantees every position in both lists is
non-`None`; the function asserts this invariant rather than silently dereferencing. This
eliminates the mis-indexed-binding and `None`/`IndexError` risks.

**Shared source files across entries.** Two entries may legally reference the **same**
`source_file_id` (distinct datasets binding one file). Inspection is **cached by
`source_file_id`**: the middle inspects each distinct resolved object exactly once and
reuses the resulting `RawPhysicalSnapshot` for every entry position that references it
(so N entries sharing one file cost one stream open, honoring NFR1). Each such position
still produces an **independent** `RawDataset` + `RawDatasetFileBinding` row — sharing a
snapshot never collapses or deduplicates dataset rows. A dedicated unit test covers the
"two entries, one shared `source_file_id`" case: two datasets, two bindings, one
inspection.

Both `_source` (as the new `resolve_bulk_sources`, which **returns** typed issues instead
of raising `ProblemException`) and `_stale` (as `stale_raw_consumers`) move from
`routes.py` into `src/app/raw/service.py`. `routes.create_dataset`, `patch_dataset`,
`retire_dataset`, `create_variable`, `patch_variable`, `delete_variable`,
`initialize_variables`, and `patch_raw` are refactored to call `stale_raw_consumers`; the
single-dataset route keeps a thin wrapper that raises `422 raw_source_file_invalid` when
`resolve_bulk_sources` reports a missing source (preserving its current HTTP behavior),
so the single and bulk paths share one implementation. This honors "cross-module access
only via typed service interfaces" and "never import route code into the worker": the
worker imports only `src/app/raw/service.py`, never `routes.py`. The SDTM staleness
consumer is still reached through
`registry.require_handler("sdtm", ModuleCapability.STALENESS)` exactly as today.

- **Retry safety / idempotent terminal transitions.** T1 and T2 both re-read
  `import.status`; if it is `succeeded`/`failed`/`cancelled` the handler `complete(job)`s
  and does nothing (the explicit terminal-state guard added in §3.5). Because T2 is a
  single transaction, a retry after a mid-T2 crash either finds the datasets already
  committed and the run `succeeded` (terminal guard → no-op) or finds none committed and
  re-runs the untransacted inspection safely. Content failures `complete` the job so they
  are never requeued; only transient infra errors `fail` (requeue). Cancellation is
  cooperative at both boundaries.

## 8. Descriptor and capability registration

`src/app/raw/descriptor.py`:

- **No new owned entity type for the operation.** `raw_dataset_import` is an operation row
  (like `artifact_builds`/`reconciliation_runs`/`validation_runs`) and is deliberately
  **not** added to `entity_types`; its status endpoints enforce study ownership directly
  via `StudyService.require_access` (§3.3, §4.2). `RawCapability.resolve_entity` is
  **unchanged** (no `raw_dataset_import` branch), so the import can never be targeted as
  an artifact-build owner.
- **No new artifact type**: the import produces `RawDataset` rows, not artifacts; the
  existing `raw_metadata_json`/`raw_data_dictionary_xlsx` artifacts are still built via the
  unchanged artifact path afterward.
- **No new capability flag**: the import reuses existing capabilities. The new job type is
  a worker/dispatch concern, not a `ModuleCapability`.

**Job-type uniqueness is not a registry concern.** `ModuleRegistry._OWNED_COLLECTIONS`
covers `entity_types`, `relationship_types`, `artifact_types`, `source_plan_types`,
`reconciliation_types`, and `event_types` only — there is **no** `job_types` collection
and no `ModuleDescriptor` job-type field, so startup does **not** validate job types. The
`"raw_dataset_import"` job type is wired by code in three worker locations (the
`claim(job_types=...)` tuple, the `_process_job` dispatch, and the `_record_failure`
branch); a duplicate job-type string is prevented by code review, not by startup. (If
startup enforcement of job types is ever wanted, adding `job_types` to `ModuleDescriptor`
and `_OWNED_COLLECTIONS` is a separate, explicit kernel change and is out of scope here —
see Finding 2 in §12.)

The only registry-guaranteed startup check that still applies is the ordinary one: the
Raw descriptor's existing owned collections stay duplicate-free, and the new table/model/
routes do not introduce a duplicate owned entity type.

## 9. Testing strategy

- **Unit (`tests/unit`)**: `RawDatasetImportRequest` validation (empty array, over-limit,
  intra-batch duplicate code, bad code pattern, extra fields rejected); canonical
  `fingerprint(command.model_dump(mode="json"))` stability; `resolve_bulk_sources` and
  `apply_bulk_dataset_import` happy path and each per-entry issue branch with a fake
  storage/session; the worker handler's job-vs-business rule (a content rejection calls
  `JobService.complete`, not `fail`); the terminal-state guard makes a redelivered
  terminal run a no-op; the cancel handler transitions a `queued` import to `cancelled`.
- **Property (`tests/unit`)**: a batch of unique codes always yields one dataset per entry
  and exactly one revision bump; any batch containing a duplicate/invalid entry yields
  zero datasets (all-or-nothing invariant) — Hypothesis over entry lists.
- **Repository integration (`tests/integration`)**: migration applies up/down from an
  empty DB; a committed import is a single transaction (count rows before/after); late
  `IntegrityError` path rolls back fully and the job ends `succeeded` with a `failed` run;
  idempotency replay returns the same run and reuse returns `409`; a deterministic content
  failure is **not** requeued (attempt_count stays 1); lease/claim of the new job type via
  `FOR UPDATE SKIP LOCKED`.
- **Storage integration**: `:bulk` upload of several files produces distinct `SourceFile`
  rows with correct checksums; a mid-batch oversize file rejects the whole request and
  commits no rows; the `:bulk` upload pass holds **at most one temp file at a time** (a
  temp-dir spy asserts no two temp files coexist, mirroring the worker's one-stream
  assertion); worker inspection releases each file stream before opening the next
  (asserted via a storage spy that fails if two streams are open at once).
- **Contract (`tests/contract`)**: `202 + Location`, `problem+json` shapes for 400/409/
  413/415/422, status `GET`, cancel transition, and OpenAPI includes the three new
  operations with `snake_case` schemas and a closed `status` enum.
- **E2E (`tests/e2e`)**: upload many files, import a JSON array referencing them, poll the
  status to `succeeded`, confirm datasets + bindings exist, the workbench revision bumped
  once, and a dependent SDTM input is staled.

## 10. Documentation and client updates

- `docs/api-contract.md`: add the two Raw endpoints and the `raw-dataset-imports` status
  resource to the route inventory and the async-operation table (new
  `Location: /api/v1/raw-dataset-imports/{import_id}` row); note the `:bulk` upload under
  the bulk-imports section.
- `docs/artifact-catalog.md`: no new artifact type; add a sentence that bulk import
  creates the same `raw_dataset`/binding records and provenance as single create.
- OpenAPI is regenerated and the typed-client fixture + `frontend/src/api/generated`
  Raw/artifacts clients are refreshed (same step performed for `importReferences`); add
  contract tests before considering the schema change complete.
- `docs/local-development.md`: no new commands; the existing `uv run python -m
workers.job_worker` already processes the new job type once registered in the
  `claim(job_types=...)` tuple and the dispatch.

## 11. Verification commands (from `docs/local-development.md`)

```
ruff format --check .
mypy src workers
pytest tests/unit tests/contract
pytest tests/integration        # requires the Postgres/MinIO compose profile
```

Migrations are verified from a clean database (`alembic upgrade head` against a fresh
`clinical_test`) because persistence changed, and OpenAPI/contract tests are run because
routes and schemas changed.

## 12. Responses to design-review findings

### 12.1 First-round findings (resolved in revision 2)

Each finding from the first-round review is listed with how revision 2 resolved it.

- **Finding 1 (HIGH) — worker retry requeues a deterministic failure.** _Addressed._
  §3.5 is new and makes the job-success-vs-business-failure rule explicit: every content
  rejection calls `JobService().complete(job)` (never `fail()`), and `fail()` is reserved
  for transient infra errors. §5.3 adds a `Job call` column showing `complete` for every
  business outcome and `fail` only for the transient-infra row. §3.6 and §7 add the
  explicit T1/T2 terminal-state guard (`status in {succeeded,failed,cancelled}` →
  `complete` + return), which the cited template did not have. A unit and an integration
  test assert `attempt_count` stays 1 for a content failure.

- **Finding 2 (HIGH) — startup does not validate job types.** _Addressed._ FR8 (§1.2) and
  AC8 (§1.4) now claim startup-duplicate protection only for the new **entity type**
  situation, and in fact the operation is **not** an owned entity type at all (Finding 5),
  so the real startup guarantee is just that Raw's existing owned collections stay
  duplicate-free. §8 states plainly that the registry has no `job_types` collection, that
  the job type is wired in three worker locations, and that its uniqueness is a
  code-review guarantee; a registry `job_types` collection is called out as a separate
  out-of-scope kernel change.

- **Finding 3 (MEDIUM) — cancel-endpoint transition unspecified.** _Addressed._ §4.2
  "Cancel handler" now specifies the exact behavior mirroring `cancel_artifact_build`:
  reject `409 invalid_lifecycle_transition` unless `status in {queued,running}`; else set
  `status="cancelled"`, `completed_at`, and the job's `cancellation_requested_at`; commit.
  AC7 (§1.4) now states that a `queued` import is transitioned synchronously by the
  handler. Worker guards `complete(job)`.

- **Finding 4 (MEDIUM) — whole-batch inspection memory.** _Addressed._ NFR1 (§1.3) is
  rewritten: it cites that `read_rows` materializes a whole file's rows, states that the
  worker inspects files **one at a time** retaining only the small `RawPhysicalSnapshot`
  and issues, bounds memory by the single largest file, and adds a new
  `raw_bulk_import_max_total_bytes` setting (checked before inspection in §3.6 step 2 and
  §5.3/§5.4). A storage-spy test asserts streams are not held open concurrently.

- **Finding 5 (MEDIUM) — operation registered as `entity_type`.** _Addressed._ §3.3 and
  §8 now explicitly do **not** add `raw_dataset_import` to `entity_types` and leave
  `RawCapability.resolve_entity` unchanged; ownership for the status resource is enforced
  directly via `StudyService.require_access` in the GET/cancel handlers, following the
  `ArtifactBuild`/`ReconciliationRun`/`ValidationRun` operation-row precedent.

- **Finding 6 (MEDIUM) — idempotency fingerprint/study_id unpinned.** _Addressed._ §4.2
  and §6 pin `IdempotencyRecord.study_id = raw.study_id`,
  `route="raw-dataset-import"`, `resource_type="raw_dataset_import"`, and
  `request_fingerprint = fingerprint(command.model_dump(mode="json"))` (the canonical
  `RawDatasetImportRequest`: `schema_version` + entries + `expected_raw_revision`), making
  replay/reuse deterministic.

- **Finding 7 (MEDIUM) — all-or-nothing/orphan rule imprecise.** _Addressed._ §4.1 now
  specifies the explicit two-pass `create_source_files_bulk`: validate every part's
  filename + media type **before** streaming any bytes, then stream+upload each (reusing
  `_safe_display_filename`, the allow-list, the byte cap, and the `finally`-unlink), then
  one commit. §5.1 states the crisp rule that only a mid-stream `413` or an object-store
  error can orphan a blob and that no metadata rows are ever partially committed.

- **Finding 8 (MEDIUM) — `_source`/`_stale` worker boundary.** _Addressed._ §7 moves
  **both** helpers into `src/app/raw/service.py`: `_source` becomes `resolve_bulk_sources`
  which **returns** typed `ValidationIssue`s instead of raising `ProblemException`, and
  `_stale` becomes `stale_raw_consumers`. `create_dataset` and the other mutating routes
  are refactored onto these; the worker imports only `service.py`, never `routes.py`.

- **Finding 9 (MEDIUM) — `expected_raw_revision` 409 vs run-state.** _Addressed._ §4.2 now
  says the worker terminates the run `failed` with issue code `stale_raw_revision` (no
  HTTP 409 from the worker), consistent with §3.4/§5.3. The pin is documented as optional,
  defaulting to `None`, and the prose notes that nearly any concurrent Raw edit bumps the
  revision and thus invalidates the pin, so callers pin only for strict isolation.

- **Finding 10 (NIT) — `status: str`.** _Addressed._ §4.3 types the response `status` as
  `ImportStatus = Literal["queued","running","succeeded","failed","cancelled"]`; the
  persisted column stays `String(32)`.

- **Finding 11 (NIT) — untyped `issues` dicts.** _Addressed._ §4.3 types the transport
  field as `list[ValidationIssue]`; JSONB storage still holds dicts, validated back into
  `ValidationIssue` on read.

- **Finding 12 (NIT) — invented issue codes.** _Addressed._ §5.3 confirms the real codes
  raised by `inspect_file`/`read_rows` in `src/app/raw/files.py` —
  `raw_file_format_unsupported`, `raw_physical_schema_invalid`, and `raw_json_shape_invalid`
  — and forwards them verbatim (as `validate_raw` does) instead of inventing codes. Only
  the two genuinely new codes (`raw_bulk_import_too_large`, `stale_raw_revision`) and the
  request-level `raw_bulk_import_duplicate_code`/`raw_bulk_upload_*` codes are introduced
  by this feature.

### 12.2 Second-round findings (resolved in revision 3)

Each finding from the second-round `design-review.json` (3 MEDIUM + 2 NIT) is listed with
how revision 3 resolves it.

- **Finding 1 (MEDIUM) — replay response status contradicts the declared `202`.**
  _Addressed._ I took the template-matching choice: a same-key+same-body replay returns
  the prior resource with **`202 Accepted`**, not `200`. Verified against
  `create_artifact_build` in `src/app/artifacts/builds.py`: it is decorated
  `status_code=status.HTTP_202_ACCEPTED` and its replay branch is a bare
  `return ArtifactBuildResponse.model_validate(prior)` with no `response.status_code`
  override, so FastAPI emits `202` on replay. §5.2's "Key replay, same body" cell now
  reads `(202)`; §4.2's replay bullet now states the handler does not override
  `response.status_code` (matching the template byte-for-byte) and sets no new `Location`;
  AC3 (§1.4) now says replay "returns the original run with `202 Accepted`." All three
  sections agree, so the contract test written to this will pass.

- **Finding 2 (MEDIUM) — `files_inspected` never persisted while `running`.** _Addressed_
  via option (a) (honest terminal counter). The worker skeleton (verified in
  `workers/job_worker.py`: `_handle_artifact_build`/`_handle_reconciliation`/
  `_handle_validation` all use exactly T1 → untransacted middle → T2, with **no** middle
  transaction) has no session in the middle to commit an intermediate counter. Rather than
  add a middle transaction across object-store I/O (which the no-held-transaction rule
  discourages), §3.4 now states plainly that `files_inspected` is a **terminal-only**
  counter: `0` while `running`, written once in T2 (equal to `entry_count` on success, or
  the count inspected before the first short-circuiting issue on failure). The only live
  progress signal is the lifecycle `status`. §4.3 annotates the field accordingly and §3.6
  step 3 sets it in T2. The live-progress framing is removed.

- **Finding 3 (MEDIUM) — entry→snapshot correlation unspecified.** _Addressed._ §7 now
  defines a **positional, index-aligned** correlation contract: `resolve_bulk_sources`
  returns `list[ResolvedSource | None]` aligned to `entries` (`None` where
  `raw_source_file_invalid` was collected); the middle produces a
  `list[RawPhysicalSnapshot | None]` aligned the same way; and `apply_bulk_dataset_import`
  runs **only when the collected issue list is empty**, so every position is non-`None`
  (the function asserts length-equality and no-`None` rather than dereferencing blindly).
  §7 also specifies that a `source_file_id` shared by two entries is **inspected once**
  (cached by `source_file_id`) but yields two independent `RawDataset`+binding rows, and
  §3.6 steps 2–3 and NFR1 are updated to match. §9 adds the "two entries, one shared
  source file" unit test (two datasets, two bindings, one inspection).

- **Finding 4 (NIT) — `expected_raw_revision` `ge=1` rationale.** _Addressed._ §5.4 now
  states the bound deliberately mirrors `RawReconcileRequest` (also `ge=1`) and that the
  pin is compared for **equality** against the live `raw.revision` in T2, with `None`
  disabling it. The contract stays internally consistent with the reconcile request.

- **Finding 5 (NIT) — sequential temp-file release not asserted.** _Addressed._ §4.1 step
  2 now guarantees each part's temp file is streamed, uploaded, and `unlink`ed **before
  the next part is streamed** (at most one temp file at a time, bounding local disk to one
  `source_file_max_bytes` regardless of `raw_bulk_upload_max_files`). §9 adds a
  storage-integration temp-dir spy test asserting no two temp files coexist, mirroring the
  worker's one-stream assertion.
