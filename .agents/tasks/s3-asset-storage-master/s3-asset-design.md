# Technical Design: Pinned Provider Assets in S3-Compatible Object Storage

## Overview

Today the Aurinara Clinical Artifact Platform keeps the bytes of all pinned provider
assets (CDISC standards snapshots under `schemas/`, controlled terminology under
`terminology/`, presentation templates under `templates/`) on the local filesystem of
the repository/deployment. The database stores only a pointer (`asset_path`, a
repo-relative POSIX path) plus a `checksum` (sha256) that is the integrity source of
truth. Three runtime read paths depend on local disk:

- `GET /api/v1/standard-assets/{asset_id}/content` (`src/app/api/catalogs.py`),
- `GET /api/v1/terminology-assets/{asset_id}/content` (`src/app/api/catalogs.py`),
- Document rendering reads a Template version asset in
  `load_presentation_template(...)` (`src/app/documents/service.py`).

All three call `verify_repository_asset(...)` (`src/app/common/repository_assets.py`),
which resolves a safe path under an allowed root, reads the bytes, computes sha256, and
raises on mismatch. This couples the API to a local disk that must carry a large and
growing (~25k standard assets + 215 terminology assets, growing) corpus, which blocks
stateless, horizontally-scaled cloud deployment.

This design moves pinned asset **content** into the existing S3-compatible object
storage, keyed by checksum, while the DB keeps the pointer + checksum unchanged as the
integrity source of truth. The API becomes stateless with respect to asset content. The
checksum integrity guarantee is preserved end to end: no byte is ever served whose
sha256 differs from the DB checksum, regardless of source.

The design makes six decisions concrete (storage key scheme, derive-vs-column, runtime
reader primitive, upload insertion point, dev fallback policy, migration/publish command)
and specifies the exact files/functions to change, error mapping, test plan, and docs.

### Revision note

This document has been through two review passes. The first pass's structural
corrections (typed `ObjectNotFoundError` + `exists` at the storage boundary; the
`load_presentation_template` phase split; `catalog_seed` as a fourth inline-publish site)
are folded into Decisions 0, 2b, and 3 and are stable.

The **current** review pass
(`.agents/tasks/s3-asset-storage-master/s3-asset-design-review.md`,
verdict `CHANGES_REQUESTED`) raised one HIGH, three MEDIUM, and two NIT findings against
precision gaps in those decisions. All six are resolved in this document; see "Review
findings — resolutions" at the end for the point-by-point response. The one HIGH
correction — the render-phase documents fallback flag had no concrete delivery channel —
is resolved by carrying a read-only `local_fallback_enabled` policy flag on the
`ObjectStorage` object (set from settings where the worker constructs `S3ObjectStorage`),
which is the only policy signal the render phase receives and requires no
capability-protocol change.

## Technology stack (locked by this design)

Python 3.13, FastAPI, Pydantic 2, SQLAlchemy 2, boto3 (via the existing
`S3ObjectStorage`), PostgreSQL 16, S3-compatible object storage (MinIO locally). No new
third-party dependencies. The existing `ObjectStorage` Protocol
(`src/app/artifacts/storage.py`) and `checksum_object_key(sha256)` are reused, with a
small, additive extension to the storage boundary (a typed `ObjectNotFoundError` and an
`exists` probe; Decision 0). No Alembic schema change is introduced (see Decision 1b /
Decision 7).

## Decision 0 — Extend the storage boundary: typed missing-object error + existence probe

**Decision:** Before anything else is built on top of it, extend
`src/app/artifacts/storage.py` so the `ObjectStorage` boundary can (a) signal a missing
object distinctly from a connectivity/credential failure, and (b) answer a cheap
existence question without downloading the body.

Add a typed subclass and raise it from `S3ObjectStorage.open` on an S3 `NoSuchKey`/`404`;
add an `exists` method backed by `head_object`; add a read-only
`local_fallback_enabled` policy flag (constructed from settings) exposed on the Protocol;
extend the `ObjectStorage` Protocol with `exists` and `local_fallback_enabled`.

```python
# src/app/artifacts/storage.py
class ObjectNotFoundError(ObjectStorageError):
    """Raised when a specific object key does not exist."""


class ObjectStorage(Protocol):
    local_fallback_enabled: bool  # NEW (Finding 1)

    def put_file(self, object_key: str, path: Path, media_type: str) -> None: ...
    @contextmanager
    def open(self, object_key: str) -> Iterator[BinaryIO]: ...
    def exists(self, object_key: str) -> bool: ...  # NEW
    def check(self) -> None: ...


class S3ObjectStorage:
    def __init__(self, settings: Settings) -> None:
        # ... existing bucket/client wiring unchanged ...
        self.local_fallback_enabled = settings.pinned_asset_local_fallback  # NEW

    @contextmanager
    def open(self, object_key: str) -> Iterator[BinaryIO]:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=object_key)
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") in {"NoSuchKey", "NoSuchObject", "404"}:
                raise ObjectNotFoundError("object not found") from error
            raise ObjectStorageError("object download failed") from error
        except BotoCoreError as error:
            raise ObjectStorageError("object download failed") from error
        body = cast(BinaryIO, response["Body"])
        try:
            yield body
        finally:
            body.close()

    def exists(self, object_key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=object_key)
            return True
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") in {
                "NoSuchKey",
                "NoSuchObject",
                "404",
                "NotFound",
            }:
                return False
            raise ObjectStorageError("object existence check failed") from error
        except BotoCoreError as error:
            raise ObjectStorageError("object existence check failed") from error
```

The `local_fallback_enabled` flag is placed on the storage object (not on a capability
signature) because the one read site that lacks any `Settings` in scope — the documents
render phase (Decision 2b, Finding 1) — already receives the `ObjectStorage` instance and
nothing else. The worker constructs `S3ObjectStorage(settings)` once at
`workers/job_worker.py` (`main()`), where `settings` is in scope, so the flag is resolved
there and travels with the only object the render phase has. This is the single clean
channel for the render-phase fallback decision; see Decision 2b / Decision 4.

**Justification:** Decisions 2, 4, and 6 depend on telling `object_missing` apart from
`storage_error`, because the dev fallback (Decision 4) triggers **only** on absence and
never on a connectivity fault, and the HTTP mapping (Decision 6) distinguishes the two.
Today `S3ObjectStorage.open` collapses `NoSuchKey` and `BotoCoreError`/`ClientError`
connectivity failures into a single `ObjectStorageError` with the same message, and
AGENTS.md plus this design forbid parsing human-readable messages to recover the
distinction. A typed `ObjectNotFoundError` is the only clean way to recover it. The
`exists` probe makes the backfill command's default skip-check cheap (Decision 5)
instead of re-downloading each object body.

**Test-fake parity:** every in-memory/stub `ObjectStorage` used in tests must match the
real contract. `MemoryStorage.open` in `tests/integration/test_phase1_core.py` currently
does `io.BytesIO(self.objects[object_key])`, which raises a bare `KeyError` on a miss;
update it to raise `ObjectNotFoundError`, to implement `exists`, and to expose a
`local_fallback_enabled` attribute (default `False`, settable per test) so render-phase
fallback tests can exercise both branches. Any other fake that implements the Protocol is
updated the same way. This is required so the fallback and
missing-object tests exercise the real branch rather than an uncaught `KeyError`.

## Decision 1a — Storage key scheme: shared bucket, checksum-addressed key

**Decision:** Store each pinned asset's bytes in object storage under the key produced by
the existing `checksum_object_key(sha256)` -> `sha256/<aa>/<bb>/<sha256>`, in the **same
bucket** already configured for generated artifacts (`object_store_bucket`, default
`clinical-artifacts`). No dedicated bucket; no extra prefix.

**Justification:**

- The key is content-addressed by sha256 only. Collision across "artifact" bytes and
  "pinned asset" bytes is a sha256 collision, i.e. not a practical concern, and if two
  logically distinct records legitimately have identical bytes they _should_ resolve to
  one object — that is the point of content addressing and makes re-upload a no-op.
- A single bucket keeps readiness (`storage.check()` on one bucket), IAM, lifecycle, and
  the local `minio-init` bootstrap unchanged. A dedicated bucket would add a second
  readiness probe, a second bootstrap step, and new config without integrity benefit.
- Reusing `checksum_object_key` keeps one key-derivation primitive for the whole platform
  and matches how `artifacts/service.py` already uploads source files and generated
  artifacts. Consistency here is a safety property: one function owns the mapping from a
  verified checksum to a key.

A dedicated `pinned/` prefix was considered for operational clarity (lifecycle rules that
never expire pinned assets). It is rejected for Release 1 because pinned assets and
generated artifacts are both immutable and audit-retained (AGENTS.md: "Retain stale
artifacts for audit and comparison"), so no divergent lifecycle policy is needed, and
introducing a second key shape would fork `checksum_object_key`. If a future lifecycle
divergence appears, it is a localized follow-up (a prefix parameter on a new key helper),
not a reason to split now.

## Decision 1b — Derive the object key from the checksum; do NOT add a column

**Decision:** Derive the object key at read/upload time from the DB `checksum` via
`checksum_object_key(asset.checksum)`. Do **not** add an `object_key` column to
`standard_assets`, `terminology_assets`, `standard_versions`, `terminology_releases`, or
`template_versions`.

**Justification:**

- The checksum is already persisted and is the integrity source of truth. The key is a
  pure function of it, so a stored key would be redundant denormalized state that can only
  drift. Deriving avoids an Alembic migration entirely (Decision 7) and keeps the DB
  schema untouched, which reduces blast radius for a safety-sensitive change.
- Re-verification after download (Decision 2) already recomputes sha256 and compares to
  the DB checksum, so a stored key would add no integrity value.
- Tradeoff considered: a stored key would let the key scheme evolve per-row. That
  flexibility is unnecessary while `checksum_object_key` is the single scheme, and the
  function already supplies versioning in its prefix (`sha256/...`) if the hash algorithm
  ever changes. Decision: derive now; a column remains an available, reviewed migration if
  a future multi-scheme need is proven.

## Decision 2 — Runtime read: an object-storage asset reader with a re-verify guard

**Decision:** Introduce one technical read primitive that fetches an asset's bytes from
object storage by its checksum-derived key, streams the body, **re-verifies sha256 against
the expected (DB) checksum before returning**, and (for the JSON content endpoints) is
wrapped by a small helper that parses the verified bytes as a JSON object. This primitive
is a storage technical primitive (no clinical logic), so it lives next to
`verify_repository_asset` in `src/app/common/`, in a new module to avoid overloading the
local-disk file.

**Location & new module:** `src/app/common/asset_content.py`.

**Signatures:**

```python
# src/app/common/asset_content.py
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from app.artifacts.storage import (
    ObjectNotFoundError,
    ObjectStorage,
    ObjectStorageError,
    checksum_object_key,
)
from app.common.canonical import sha256_hex

AssetContentReason = Literal[
    "object_missing", "checksum_mismatch", "storage_error", "not_json_object"
]


class AssetContentError(RuntimeError):
    """Raised when verified asset bytes/content cannot be produced from any source."""

    def __init__(self, reason: AssetContentReason, *, checksum: str) -> None:
        super().__init__(reason)
        self.reason: AssetContentReason = reason
        self.checksum = checksum


def read_verified_asset_bytes(
    storage: ObjectStorage,
    expected_sha256: str,
    *,
    local_fallback: Callable[[], Path] | None = None,
) -> bytes:
    """Return bytes whose sha256 == expected_sha256, fetched from object storage.

    Control flow (branch order is a locked safety invariant):

    1. object_key = checksum_object_key(expected_sha256).
    2. Open the object through ObjectStorage and read the body fully.
       - ObjectNotFoundError  -> treat as the "object_missing" case (go to step 3).
       - any other ObjectStorageError -> raise AssetContentError("storage_error")
         IMMEDIATELY. The fallback is NOT consulted on a storage error.
    3. If (and only if) the object was missing:
         - if local_fallback is provided: read bytes from that path (dev fallback,
           Decision 4) and continue to step 4;
         - else: raise AssetContentError("object_missing").
    4. Re-compute sha256_hex(bytes). If it != expected_sha256 ->
       raise AssetContentError("checksum_mismatch") IMMEDIATELY. This runs for BOTH the
       object-storage branch and the fallback branch, so neither source can serve
       mismatched bytes, and a present-but-corrupt object is a hard error that is NEVER
       retried against local disk.
    5. Return the verified bytes.
    """


def read_verified_asset_json_object(
    storage: ObjectStorage,
    expected_sha256: str,
    *,
    local_fallback: Callable[[], Path] | None = None,
) -> dict[str, object]:
    """read_verified_asset_bytes + json.loads.

    If the verified bytes do not parse to a top-level JSON object (dict), raise
    AssetContentError("not_json_object", checksum=expected_sha256). The bytes verified
    against the checksum but violate the registered content contract; see Decision 6 for
    the HTTP mapping. This replaces today's bare RuntimeError in catalogs.py.
    """


def publish_verified_asset(
    storage: ObjectStorage,
    local_path: Path,
    expected_sha256: str,
    media_type: str,
) -> str:
    """Verify local_path's sha256 == expected_sha256, then upload to its checksum key.

    Returns the object_key. Verify-before-publish: raises
    AssetContentError("checksum_mismatch") before any upload if bytes don't match, so
    partial/garbage bytes are never published. Upload is idempotent (content-addressed);
    re-upload of identical bytes to the same key via storage.put_file is a harmless no-op
    because the object is immutable by content.
    """
```

**Branch-order invariant (fallback-only-on-absence):** the fallback is reachable **only** from the
`object_missing` path. `checksum_mismatch` and `storage_error` short-circuit before the
fallback is ever considered. This is stated in the docstring above and is pinned by a
named unit test (`test_reader_corrupt_object_never_falls_back`, see Testability) that
feeds a fake storage returning present-but-wrong bytes with a `local_fallback` that would
return valid bytes, and asserts the result is `checksum_mismatch` and that the fallback
callable was never invoked.

**Why `common/` is correct here:** `read_verified_asset_bytes` manipulates only
checksums, keys, and bytes through the `ObjectStorage` Protocol. It contains no standard,
terminology, or template semantics — those stay in the owning modules/routes that decide
_which_ asset to read and interpret the result. This mirrors `verify_repository_asset`,
which already lives in `common/` as the local-disk analogue. AGENTS.md permits technical
primitives (hashing, canonical JSON, storage helpers) in `common`; it forbids only
clinical business rules. The parse-as-JSON-object helper is a thin technical convenience
and carries no clinical judgment.

**Module ownership is preserved:** standards still owns deciding to read a
`StandardAsset` (the `catalogs.py` standards route), terminology still owns reading a
`TerminologyAsset`, and documents still owns reading its `TemplateVersion` and enforcing
the presentation-only boundary. Each simply swaps its byte-source primitive from
`verify_repository_asset(...local disk...)` to `read_verified_asset_*(storage, checksum)`.

## Decision 2b — Documents template read moves to the render phase (phase split)

**Problem the review surfaced:** `load_presentation_template(session, template_version_id)`
is called **only** from `DocumentsCapability.build_artifact_payload(self, session,
aggregate_id, study_id, artifact_type)`, which has a `Session` but **no** `ObjectStorage`.
The method that owns `storage` is a different one, `render_artifact(self, payload,
storage)`. Both are capability-protocol methods whose signatures are declared in
`src/app/artifacts/builds.py` and `src/app/kernel/dependencies.py` and dispatched
generically by `build_artifact_payloads(...)` / `render_artifact(...)` in the worker.
Changing either protocol signature to carry both `session` and `storage` would ripple
across every implementing module and violate the modular-monolith rule that shared
dispatch must not be special-cased. So "just pass storage to the caller" is not viable.

**Decision:** Split the template handling across the two phases that already exist, with
**no capability-protocol signature change**:

- In `build_artifact_payload` (has `session`, no `storage`): resolve the exact
  `TemplateVersion` row by id and place into the payload only the small, serializable
  **boundary metadata** needed to read+verify later: the template's `checksum` and its
  `renderer_versions`. Do **not** read the template bytes here. Concretely the payload key
  `presentation_template` is replaced by a `presentation_template_ref`:
  `{"checksum": version.checksum, "renderer_versions": version.renderer_versions}` (or
  `None` when no template is selected). Raise the existing `template version is missing`
  error here if the row is absent (unchanged, session-only check).
- In `render_artifact` (has `storage`, no `session`): **stop reading the old
  `presentation_template` payload key** and instead read the new
  `presentation_template_ref` key. When the ref is present, call the reworked
  `load_presentation_template(storage, ref)` to fetch the bytes from object storage,
  re-verify the checksum, and enforce the presentation-only boundary; the resulting dict
  is bound to the local `presentation_template` variable and passed to `render_pdf` /
  `render_docx` / `render_xlsx` exactly as the loaded dict is today (those ~3–8 call
  sites are **unchanged**). When the ref is `None`, `presentation_template` is `None` as
  today. The `documents_dependency_manifest` early-return branch uses no template and is
  unaffected.

The exact render-phase edit (current review Finding 2) is: replace

```python
presentation_template = cast(dict[str, object] | None, payload.get("presentation_template"))
```

with

```python
ref = cast(dict[str, object] | None, payload.get("presentation_template_ref"))
presentation_template = load_presentation_template(storage, ref) if ref is not None else None
```

Leaving the old `payload.get("presentation_template")` line in place would make it always
`None` (the build side no longer emits that key) and silently drop all template styling,
so the rename must be threaded through both phases together.

**Render-phase fallback channel (Finding 1):** `load_presentation_template` reads the
fallback decision from `storage.local_fallback_enabled` (Decision 0) — the only policy
signal the render phase has, resolved from settings when the worker built the storage
object. When that flag is `True` **and** the ref carries `asset_path`,
`load_presentation_template` passes a local-fallback closure to
`read_verified_asset_json_object`; when it is `False` (production), no closure is passed
and the template is read only from object storage. No capability-protocol signature
changes, no settings threaded into `build_artifact_payload`, and no storage injected into
the frozen `DocumentsCapability` descriptor.

**Reworked signature:**

```python
# src/app/documents/service.py
def load_presentation_template(
    storage: ObjectStorage,
    ref: dict[str, object],  # {"checksum": str, "renderer_versions": list[str], "asset_path": str}
) -> dict[str, object]:
    """Load and enforce the presentation-only boundary of one exact Template asset.

    Reads bytes from object storage by ref["checksum"] via
    read_verified_asset_json_object, then applies the EXISTING boundary checks verbatim:
    allowed_keys subset, styles/blank_structure types, and the renderer compatibility
    check using ref["renderer_versions"]. All existing ProblemException raises (status
    409 template_content_boundary_violation / template_renderer_incompatible) are kept.

    The local_fallback closure is passed to read_verified_asset_json_object ONLY when
    storage.local_fallback_enabled is True (dev); it resolves the local path via
    verify_repository_asset(REPOSITORY_ROOT, ref["asset_path"], ref["checksum"],
    allowed_root="templates"). In production the flag is False and no closure is passed.
    AssetContentError is translated to the Decision 6 problems at the API boundary.
    """
```

**Justification:** this keeps the session-only concern (does the exact `TemplateVersion`
row exist, what is its checksum and renderer set) in the phase that has the session, and
the storage-only concern (fetch + verify bytes) in the phase that has storage, each using
only what it already receives. No new parameter is threaded through
`build_artifact_payloads`/`render_artifact`, so the capability protocols in
`artifacts/builds.py` and `kernel/dependencies.py` are untouched. The payload stays
JSON-serializable (checksum + renderer list are strings/lists), which the durable job
queue requires. The presentation-only boundary stays owned by the documents module.

A rejected alternative was giving `DocumentsCapability` an `ObjectStorage` at
construction. `DocumentsCapability` is a frozen, `slots=True` dataclass instantiated once
as a module-level `HANDLER` in `src/app/documents/descriptor.py` at import/composition
time, where no request-scoped or app-state `ObjectStorage` exists; wiring storage into a
static descriptor is awkward and couples descriptor construction to runtime storage. The
phase-split above avoids that entirely.

## Decision 3 — Upload path: publish during registration/import/seed, after local checksum verify

**Decision:** Publish bytes to object storage **inside the existing offline
acquisition/registration/seed functions**, immediately after each asset's on-disk
checksum is verified, rather than as a separate standalone command. Concretely, add an
upload step to the four sites that create asset rows:

- `cdisc_library_registry` bulk path (the ~25k + 215 corpus): the verify pass
  `load_library_snapshot` already calls `verify_repository_asset` on the manifest and
  every resource; publish each there (Transaction boundary below),
- `standards/importer.import_standard_manifest` (hand-maintained standard packages),
- `terminology/importer.import_terminology_manifest` (hand-maintained CT packages),
- **`catalog_seed.seed(...)`** — the site that creates the Phase 1 `TemplateVersion`,
  `StandardVersion`, and `TerminologyRelease` rows. Templates are
  registered **only** here, by no other inline site, so without this templates would never
  be published inline and the first production document render would `503`.

The upload is checksum-addressed, so re-upload of identical bytes is an idempotent no-op,
and it runs **after** the bytes have been confirmed to match the checksum — i.e.
verify-before-publish.

**What the publish pass must cover (Finding 4):** the content endpoints
`GET /standard-assets/{id}/content` and `/terminology-assets/{id}/content` operate on
`StandardAsset` / `TerminologyAsset` rows and derive their key from the **per-asset**
`StandardAsset.checksum` / `TerminologyAsset.checksum` (not the manifest/version
checksum). So each importer's verify+publish pass must publish **one object per distinct
checksum among {the manifest file} ∪ {every referenced asset that becomes a
`StandardAsset`/`TerminologyAsset` row}** — i.e. every row the content endpoints can
address, plus the version/release manifest file. The importers already create those
per-asset rows with `checksum=asset.sha256`, so the data exists; the pass simply iterates
`manifest.assets` and publishes each in addition to the manifest file. Content addressing
dedupes identical bytes automatically, so publishing a shared checksum twice is a no-op.
Without this, individual-asset content endpoints would `503` after a fresh import even
though the manifest/version object was published.

The migration of a corpus registered **before** this change (DB rows exist but objects
may not) is handled by the dedicated repeatable admin command (Decision 5). These
mechanisms share the one `publish_verified_asset` primitive. With all four inline sites
publishing, the claim "new registrations publish inline and never need the backfill" is
now true for standards, terminology, **and** templates.

**`catalog_seed` storage wiring:** `catalog_seed.seed(session)` is called from
`catalog_seed.main()` (its own `__main__`) and wherever the app bootstraps the catalog.
Add an `ObjectStorage` parameter to `seed(session, storage)` and construct
`S3ObjectStorage(get_settings())` in `main()`; every caller of `seed(...)` must pass a
storage instance (DI at the boundary). `seed()` creates **four** pinned asset files, all
JSON, each published with `media_type="application/json"` (Finding 5):

- `schemas/platform/dependency-selection-1.0.0.json` (one `StandardVersion`),
- `terminology/platform/issue-severity-1.0.0.json` (one `TerminologyRelease`),
- `templates/platform/report-layout-1.0.0.json` (first `TemplateVersion`),
- `templates/platform/document-layout-2.0.0.json` (second `TemplateVersion` — the one the
  documents render path depends on; omitting it would reproduce the Finding-3 render
  `503`).

Publish each asset at its `session.add` site (see Finding 6 below), using the local path
and checksum already in scope there.

**`_checksum` stays pure (Finding 6):** do **not** thread `ObjectStorage` into
`catalog_seed._checksum(path)` — it verifies the path is under `ROOT` and returns the hex
digest, and AGENTS.md keeps pure domain/hashing logic separate from I/O. Instead publish
at each `session.add(...)` site, where both the resolved `*_path` and its
`_checksum(*_path)` value are already in scope:
`publish_verified_asset(storage, <*_path>, _checksum(<*_path>), "application/json")`
before (or alongside) that asset's `session.add`. The single `session.commit()` stays at
the end; because the asset set is tiny and publishing precedes the row adds, no DB
transaction is held across object-store I/O.

**Transaction boundary (publish before the write txn):** AGENTS.md says a command should normally commit
once and that a DB transaction must not stay open across object-store I/O ("Do not hold a
database transaction open while ... accessing object storage"). The current CLI
`_register_snapshot` opens `factory.begin()` and calls `register_library_snapshot`
**inside** it; `register_library_snapshot` currently both verifies (via
`load_library_snapshot`) and inserts. To satisfy both rules the publish happens with **no
DB transaction held**, in a verify+publish pass that runs **before** `factory.begin()`:

```python
# src/app/cdisc_registry.py  (publish-then-insert ordering, no object-store I/O in the txn)
manifest = load_and_publish_library_snapshot(
    storage, manifest_path, REPOSITORY_ROOT
)  # verify + publish; NO txn
with factory.begin() as session:
    register_library_snapshot_rows(
        session, manifest, REPOSITORY_ROOT
    )  # inserts only; NO object-store I/O
```

Specifics the implementer must honor:

- `load_library_snapshot(manifest_path, repository_root)` keeps its current job (parse
  manifest, `verify_repository_asset` the manifest and every resource) and is wrapped by
  (or extended into) `load_and_publish_library_snapshot(storage, manifest_path,
repository_root)` that additionally calls `publish_verified_asset(...)` for each
  already-verified asset — the manifest file with `media_type="application/json"`
  (Finding 3) and each resource with its own `media_type` (fixed
  `Literal["application/json"]` for library resources). It publishes one object per
  distinct checksum among {manifest file} ∪ {every resource} and performs **no DB
  writes**.
- `register_library_snapshot` is refactored so the DB-insert portion
  (`register_library_snapshot_rows`) runs under `factory.begin()` and performs **no
  object-store I/O and no `verify_repository_asset` second pass**. Row insertion
  **trusts** the manifest already validated by the publish pass; it does not re-hash the
  ~25k assets a second time. This avoids a hidden double pass over the corpus. (The
  checksum written to the row is the manifest's declared `sha256`, which the publish pass
  already proved matches the on-disk bytes, so trusting it in the insert phase introduces
  no integrity gap: a committed row's checksum has been verified and its bytes have been
  published.)
- `import_standard_manifest` / `import_terminology_manifest` get the same shape: their
  `load_*` returns the manifest plus the asset checksums it already computes
  (`load_standard_manifest` -> `(manifest, standard_checksum, group_checksum)` and the
  terminology equivalent); the verify+publish pass runs before the transaction with the
  full set of asset `path + checksum + media_type`, then an inserts-only call runs under
  `factory.begin()`. These importers accept an `ObjectStorage`.
- **Manifest-file media type (Finding 3):** each importer must also publish the
  _manifest file itself_, whose checksum (`standard_checksum` / the terminology
  equivalent) is persisted on `StandardVersion.checksum` / `TerminologyRelease.checksum`
  as the integrity source of truth and is read back by the content endpoints. The
  manifest file is JSON, so publish it with `media_type="application/json"`
  (`load_standard_manifest`/`load_terminology_manifest` return no media type for the
  manifest file, so the importer supplies this constant). The per-asset rows keep using
  their own `asset.media_type`. Likewise, the library snapshot _manifest_ file published
  by `load_and_publish_library_snapshot` uses `media_type="application/json"` (its
  resource rows already carry `media_type: Literal["application/json"]`). Getting the
  manifest media type wrong does not affect integrity (the checksum still governs) but is
  fixed for correctness and to match the `application/json` the content endpoints assume.
- `catalog_seed.seed` publishes each of its four assets at that asset's `session.add`
  site using the already-resolved `*_path` and the value returned by the **pure**
  `_checksum(*_path)` (Finding 6 — `_checksum` is not given storage); it currently does a
  single `session.commit()` at the end. Because its asset set is tiny (four platform JSON
  files) the publish calls precede the row adds within the same function without a
  meaningful transaction-held-across-I/O concern, and the single `commit()` stays at the
  end.

Because objects are content-addressed and immutable, publishing before the DB commit is
safe: if a later DB insert fails, orphaned objects are harmless (same bytes, same key,
reused on retry), and every committed asset row is guaranteed to already have its bytes in
object storage.

## Decision 4 — Dev/compat fallback: object-storage-first with an explicit, verified local fallback

**Decision:** Read object-storage-first, and when the object is **absent** (only on the
`object_missing` path, never on `checksum_mismatch` or `storage_error`), fall back to
reading the local repository file via the existing `verify_repository_asset` path — but
**only when explicitly enabled** by a setting that is off in production.

**New setting:** `pinned_asset_local_fallback: bool = True` in `Settings`
(`src/app/config.py`), added to `reject_unsafe_production_configuration` so that
`app_env == "production"` with the fallback enabled is rejected at startup (same pattern
as the other production safety checks, which append a label to `unsafe`). Default `True`
for development ergonomics; must be set `False` in production. The settings env name is
`PINNED_ASSET_LOCAL_FALLBACK`.

**How the fallback stays integrity-safe:** the content endpoints and the documents reader
supply a `local_fallback` callable to `read_verified_asset_*`. For the content endpoints
that callable returns the safe local path by calling
`verify_repository_asset(REPOSITORY_ROOT, asset.asset_path, asset.checksum,
allowed_root=<"schemas"|"terminology">)`, which itself re-checks sha256 on disk. The
reader then re-verifies the returned bytes against the same expected checksum (step 4). So
the dev fallback passes through **two** checksum gates and cannot serve mismatched bytes.
The fallback triggers **only** on object absence (per the branch-order invariant in
Decision 2), so a tampered object yields `checksum_mismatch` (a hard error), never a
silent disk read.

For the documents template read the fallback also needs (a) a path and (b) a channel for
the enabled/disabled flag, because `load_presentation_template` runs in the render phase
without a `session` and without a `Settings`. Both are supplied without any
capability-protocol change:

- **Path:** `build_artifact_payload` (which has the session) carries `asset_path`
  alongside `checksum` and `renderer_versions` in the `presentation_template_ref`.
- **Flag:** the render phase reads `storage.local_fallback_enabled` (Decision 0). The
  worker set it when it constructed `S3ObjectStorage(settings)` in
  `workers/job_worker.py` `main()`, which is the one site with `settings` in scope; the
  flag then travels with the `ObjectStorage` instance that `render_artifact` already
  receives. This is the resolved answer to the review's Finding 1 — the earlier
  "the worker reads settings when constructing the fallback policy" wording named no
  realizable seam; the storage-carried flag is that seam.

So `load_presentation_template` passes a local-fallback closure that calls
`verify_repository_asset(REPOSITORY_ROOT, ref["asset_path"], ref["checksum"],
allowed_root="templates")` **iff** `storage.local_fallback_enabled` is `True`. In
production the flag is off and no fallback closure is passed, so the render path reads
only from object storage.

A rejected alternative (review Option A) was threading `Settings` into
`build_artifact_payload` so the resolved bool rides in the payload. It works but requires
adding a settings parameter to the artifact-build pipeline (`artifacts/builds.py`
`resolve_build_input` → `build_artifact_payload`), touching more call sites than the
storage-flag approach, which changes nothing beyond the storage boundary that already
flows into the render phase. Option B (storage-carried flag) is chosen for the smaller
blast radius and because the flag is a storage-read policy, not build-input state.

**Justification:**

- Dev ergonomics: a developer who has registered assets (DB rows + on-disk files) but has
  not yet run the publish/backfill command can still exercise the content endpoints and
  document renders without a mandatory extra step. This matches the current single-step
  local workflow.
- It is non-silent and bounded: it only covers absence, is gated by an explicit setting,
  and is refused in production, so it cannot mask a missing-publish in a real deployment.
- Readiness: because production disables the fallback, `storage.check()` plus a documented
  "publish step must have run" requirement (Decision 6) correctly reflect that production
  reads come only from object storage.

`verify_repository_asset` is retained unchanged for the offline
verification/acquisition path regardless of this decision; the fallback simply reuses it.

## Decision 5 — Migration/publish admin command for the already-registered corpus

**Decision:** Add a new, repeatable, idempotent, resumable subcommand to the existing
offline CLI `src/app/cdisc_registry.py`:

```
python -m app.cdisc_registry publish-assets [--batch-size N] [--dry-run] [--force] [--verify-existing]
```

**Behavior:**

- Streams all `standard_assets`, `terminology_assets`, and the manifest/release assets on
  `standard_versions` / `terminology_releases`, plus `template_versions`, from the DB in
  batches (`--batch-size`, default 500), ordered by primary key for deterministic
  resumption.
- For each row: derive `object_key = checksum_object_key(asset.checksum)`.
  - **Default skip-check uses `storage.exists(object_key)` (cheap existence probe).** If the object
    exists, skip the upload — a cheap `head_object`, no body download. This is the default
    because content addressing already guarantees a present object with this key has the
    right bytes.
  - If the object is absent, resolve the local path with
    `verify_repository_asset(REPOSITORY_ROOT, asset.asset_path, asset.checksum,
allowed_root=<schemas|terminology|templates>)` (re-verifies on-disk sha256), then
    `publish_verified_asset(storage, path, asset.checksum, asset.media_type)`.
  - `--verify-existing` opt-in: instead of trusting existence, download each present
    object and re-verify its sha256; a present-but-corrupt object is detected and
    re-published from the verified local file. This is the expensive full-read path and is
    **not** the default (the default is the cheap existence probe).
  - `--force`: re-upload unconditionally, bypassing both the existence probe and
    `--verify-existing`.
- **Resumable:** every step is independently idempotent and ordered, so a crashed run is
  restarted by re-invoking the command; already-published objects are skipped by the
  existence probe.
- `--dry-run`: verifies every on-disk checksum and reports what would be uploaded (uses
  the existence probe to report "already present" vs "would upload") without writing to
  object storage.
- No DB writes. The command never mutates DB rows (there is no new column), so it holds no
  long DB transaction; it uses short read-only sessions per batch.
- Structured progress logging mirroring `snapshot-all`'s progress callback (count +
  current logical id). Object keys and checksums are not secrets but are logged at debug
  level only to keep logs clean (per Decision 6 / AGENTS.md). Never log asset bytes.

**No Alembic data migration performs byte movement.** Per AGENTS.md and the task, all byte
movement lives in this admin command (and the inline publish of Decision 3). Because
Decision 1b adds no column, there is **no Alembic migration at all** for this feature
(Decision 7).

**Why extend the CLI rather than a brand-new entrypoint:** `cdisc_registry.py` is already
the single offline admin surface for asset acquisition/registration, already constructs
the session factory and settings, and `docs/local-development.md` already documents it.
Adding `publish-assets` keeps one discoverable admin tool and one place to document the
workflow. The command constructs `object_storage = S3ObjectStorage(settings)` (DI at the
boundary), consistent with how `main.py` wires it into app state.

## Decision 6 — Config / readiness / typed-error -> HTTP problem mapping

Object storage is already a hard dependency wired into `app.state.object_storage` and
probed by `_storage_readiness` in `src/app/api/health.py`. This design adds
**content-level** error mapping so a missing/corrupt/non-contract object returns a clean
problem, not a generic 500 stack trace.

**Error -> HTTP problem mapping** (translated at the API boundary — the two `catalogs.py`
handlers and, for template reads, where `AssetContentError` surfaces from the render
path — by catching `AssetContentError` and raising `ProblemException`):

| `AssetContentError.reason`                                     | HTTP    | problem `code`                     | title / detail                                                                                                                             |
| -------------------------------------------------------------- | ------- | ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `object_missing` (fallback disabled or local file also absent) | **503** | `asset_content_unavailable`        | "Asset content is not published" / "The pinned asset has not been published to object storage. Run the publish-assets admin step."         |
| `storage_error` (BotoCore/other ClientError failure)           | **503** | `asset_content_unavailable`        | "Asset content store is unavailable" / "Object storage could not be reached."                                                              |
| `checksum_mismatch`                                            | **500** | `asset_content_integrity_error`    | "Asset content failed integrity verification" / "Stored bytes do not match the registered checksum." (never serve the bytes; log at error) |
| `not_json_object` (Finding 4)                                  | **500** | `asset_content_contract_violation` | "Asset content is not a JSON object" / "The verified asset bytes do not form a JSON object."                                               |

Rationale for status codes:

- `object_missing` and `storage_error` are **operational/transient or deployment-state**
  conditions, not client errors — `503 Service Unavailable` with a typed `problem+json` is
  correct and signals "retry after the publish/backfill or when storage recovers". In
  production (fallback off) an unpublished corpus makes content endpoints `503`, matching
  the operational expectation that `publish-assets` must have run.
- `checksum_mismatch` is a server-side integrity fault; `500` with a stable code and an
  error-level log (no bytes, no key at info) is correct. It must never return `200`.
- `not_json_object` (Finding 4): the bytes verified against the checksum but violate the
  registered content contract. **Chosen status: 500** with the dedicated code
  `asset_content_contract_violation`, replacing today's bare
  `RuntimeError("registered standard asset is not a JSON object")` that fell through to
  the generic `unexpected_exception_handler` as an untyped `500 internal_error`. 500
  (not 422) is correct because the input is not client-supplied — a registered,
  checksum-verified server-side asset is malformed, which is a server fault, and the HTTP
  contract (unchanged `dict[str, object]` response model) assumes a JSON object. This
  satisfies Decision 6's "never a raw 500" goal: the condition now returns a typed
  `problem+json`, not the generic handler.

The route still returns `404 standard_asset_not_found` / `terminology_asset_not_found`
when the DB row is absent (unchanged `_require(...)`), so "unknown asset" and "known
asset, unpublished/corrupt/non-contract content" are distinct.

**Logging:** keep structured logging. Do not log JWTs/secrets; object keys and checksums
are not secrets but are logged only at debug level to avoid noise. Never log asset bytes.
Because every content-level condition now raises a typed `ProblemException`, none reaches
`unexpected_exception_handler` as an unhandled 500 (the integrity and contract 500s are
deliberate typed problems, not the generic handler).

**Config/readiness summary:** no new hard dependency; one new boolean setting
(`pinned_asset_local_fallback`) with a production-safety check. Readiness is unchanged
(bucket reachability). The "content is published" precondition is documented and surfaced
as `503 asset_content_unavailable` at request time rather than as a readiness gate,
because readiness cannot cheaply assert that all ~25k objects exist.

## Decision 7 — Alembic migration plan

**None.** Decision 1b adds no column; Decision 4 adds only an in-memory setting. There is
no persistent schema change, therefore no Alembic migration is created. The AGENTS.md rule
"Create an Alembic migration for every persistent schema change" is satisfied vacuously —
there is no schema change.

If a future reviewer insists on persisting `object_key`, that would be a normal reviewed
nullable-column migration that must upgrade a clean DB in tests; it is explicitly **out of
scope** here and not required for correctness.

## Exact files and functions to change

1. **`src/app/artifacts/storage.py`** (Decision 0)
   - Add `class ObjectNotFoundError(ObjectStorageError)`.
   - In `S3ObjectStorage.open`, split the `except`: raise `ObjectNotFoundError` on S3
     `NoSuchKey`/`404`, `ObjectStorageError` on all other BotoCore/Client failures.
   - Add `S3ObjectStorage.exists(object_key) -> bool` backed by `head_object`.
   - In `S3ObjectStorage.__init__`, set
     `self.local_fallback_enabled = settings.pinned_asset_local_fallback` (current review
     Finding 1 — the render-phase fallback channel).
   - Add `exists` and the `local_fallback_enabled: bool` attribute to the `ObjectStorage`
     Protocol.

2. **New** `src/app/common/asset_content.py` (Decision 2)
   - `AssetContentReason` literal (`object_missing | checksum_mismatch | storage_error |
not_json_object`).
   - `AssetContentError(RuntimeError)` with `.reason`, `.checksum`.
   - `read_verified_asset_bytes(storage, expected_sha256, *, local_fallback=None) -> bytes`
     with the locked branch order (missing -> fallback; storage_error/mismatch
     short-circuit).
   - `read_verified_asset_json_object(...) -> dict[str, object]` raising
     `not_json_object`.
   - `publish_verified_asset(storage, local_path, expected_sha256, media_type) -> str`.
   - Depends only on `app.artifacts.storage` and `app.common.canonical`; no clinical
     logic.

3. **`src/app/api/catalogs.py`** (Decisions 2, 4, 6)
   - Import `get_object_storage` (from `app.api.dependencies`), the new helpers, and
     `AssetContentError`.
   - `get_standard_asset_content`: add `request: Request` and
     `storage: Annotated[ObjectStorage, Depends(get_object_storage)]`; read
     `settings = request.app.state.settings` (the established sibling-route pattern, no new
     `get_settings` dependency); replace the `verify_repository_asset` + `json.loads` +
     bare `RuntimeError` block with `read_verified_asset_json_object(storage,
asset.checksum, local_fallback=<closure calling verify_repository_asset(...,
allowed_root="schemas")> if settings.pinned_asset_local_fallback else None)`;
     translate `AssetContentError` to the mapped `ProblemException`. **Response
     model/shape unchanged** (`dict[str, object]`).
   - `get_terminology_asset_content`: same, `allowed_root="terminology"`.
   - Keep handlers thin: no inline validation beyond the existing `_require`.

4. **`src/app/documents/service.py`** (Decision 2b, 4)
   - Rework `load_presentation_template` to the new signature
     `load_presentation_template(storage, ref)` reading bytes via
     `read_verified_asset_json_object`, preserving every existing presentation-only
     boundary `ProblemException` (409) verbatim and using `ref["renderer_versions"]` for
     the renderer compatibility check.
   - In `build_artifact_payload`: resolve the `TemplateVersion` row (session), keep the
     "validated Template version is missing" check, and place
     `presentation_template_ref = {"checksum": version.checksum, "renderer_versions":
version.renderer_versions, "asset_path": version.asset_path}` (or `None`) into the
     payload instead of the loaded dict.
   - In `render_artifact` (has `storage`): **replace**
     `presentation_template = cast(..., payload.get("presentation_template"))` **with**
     `ref = cast(dict[str, object] | None, payload.get("presentation_template_ref"))`
     then `presentation_template = load_presentation_template(storage, ref) if ref is not
None else None`. The downstream
     `render_pdf/render_docx/render_xlsx(..., presentation_template)` calls are
     **unchanged**. Do not leave the old `payload.get("presentation_template")` line in
     place (it would always be `None` and silently drop template styling — Finding 2).
   - `load_presentation_template` passes a local-fallback closure to
     `read_verified_asset_json_object` **iff** `storage.local_fallback_enabled` is `True`
     (Decision 0 / Finding 1); the closure calls `verify_repository_asset(REPOSITORY_ROOT,
ref["asset_path"], ref["checksum"], allowed_root="templates")`. No settings are read
     in this phase; the flag arrives on the `storage` object.
   - **No change** to the `build_artifact_payload` / `render_artifact` capability
     signatures in `src/app/artifacts/builds.py` or `src/app/kernel/dependencies.py`.

5. **`src/app/catalog_seed.py`** (Decision 3, Findings 5, 6)
   - `seed(session, storage)`: thread `ObjectStorage` in. At each of the **four**
     `session.add` sites, publish that asset with
     `publish_verified_asset(storage, <*_path>, _checksum(<*_path>), "application/json")`:
     `schemas/platform/dependency-selection-1.0.0.json` (`StandardVersion`),
     `terminology/platform/issue-severity-1.0.0.json` (`TerminologyRelease`),
     `templates/platform/report-layout-1.0.0.json` and
     `templates/platform/document-layout-2.0.0.json` (both `TemplateVersion` rows).
   - **Leave `_checksum(path)` pure** — do not pass it `ObjectStorage` (Finding 6);
     publish at the `session.add` site where both the path and checksum are in scope.
   - `main()`: construct `S3ObjectStorage(get_settings())` and pass it to `seed`.
   - Update every other caller of `seed(...)` to pass a storage instance.

6. **`src/app/cdisc_library_registry.py`** (Decision 3, transaction boundary)
   - Add `load_and_publish_library_snapshot(storage, manifest_path, repository_root)`:
     run the existing verify pass and `publish_verified_asset(...)` each verified asset,
     **no DB txn held**; return the validated manifest.
   - Refactor `register_library_snapshot` so its insert portion
     (`register_library_snapshot_rows(session, manifest, repository_root)`) runs under
     `factory.begin()` with **no object-store I/O and no second full verify pass** (trusts
     the manifest already validated/published).

7. **`src/app/standards/importer.py`** and **`src/app/terminology/importer.py`**
   (Decision 3, Findings 3 and 4)
   - `import_standard_manifest` / `import_terminology_manifest` accept `storage`; run the
     verify+publish pass with no DB txn held, then an inserts-only step under
     `factory.begin()`. The pass publishes **one object per distinct checksum among the
     manifest file plus every `manifest.assets` entry that becomes a
     `StandardAsset`/`TerminologyAsset` row** (Finding 4) — not just the manifest/version
     checksum — so every content-endpoint-addressable row is backed. Publish the manifest
     file with `media_type="application/json"` (Finding 3); publish each per-asset row
     with its own `asset.media_type`. The `load_*` return already provides the per-asset
     `path`/`sha256`/`media_type`; the manifest file's media type is the one constant the
     importer supplies.

8. **`src/app/cdisc_registry.py`** (Decisions 3, 5)
   - Construct `S3ObjectStorage(settings)` in each command and pass it to the registration
     functions (`register-snapshot`, `register-manifests`) using the
     publish-then-insert ordering.
   - Add the `publish-assets` subcommand (Decision 5): argparse parser, batched read-only
     iteration over the asset-bearing tables, `storage.exists` skip-check default,
     `verify_repository_asset` + `publish_verified_asset` on absence, `--batch-size`,
     `--dry-run`, `--force`, `--verify-existing`, structured progress.

9. **`src/app/config.py`** (Decision 4)
   - Add `pinned_asset_local_fallback: bool = True` (env `PINNED_ASSET_LOCAL_FALLBACK`).
   - Extend `reject_unsafe_production_configuration`: in production with the flag `True`,
     append "pinned asset local fallback" to `unsafe`.

10. **`tests/integration/test_phase1_core.py`** and any other `ObjectStorage` fake
    (Decision 0 parity)
    - `MemoryStorage.open` raises `ObjectNotFoundError` on a missing key (not `KeyError`);
      add `MemoryStorage.exists`.

11. **`src/app/api/dependencies.py`** — already exposes `get_object_storage`; no change
    beyond import usage. (Confirmed present and correct.)

## Edge cases

- **Object present but corrupted/tampered:** `read_verified_asset_bytes` returns
  `checksum_mismatch` (step 4, short-circuit) -> 500 `asset_content_integrity_error`;
  bytes never served; fallback never consulted (absence-only).
- **Object absent, fallback enabled, local file present and valid:** served from disk
  after double checksum verification; dev-only.
- **Object absent, fallback disabled (production) or local file also absent:**
  `object_missing` -> 503 `asset_content_unavailable`.
- **Storage unreachable (network/credentials):** non-`NoSuchKey` `ObjectStorageError`
  from `storage.open` -> `storage_error` -> 503; fallback never consulted. Readiness probe
  flips to not-ready independently.
- **Verified bytes are not a JSON object:** `read_verified_asset_json_object` ->
  `not_json_object` -> 500 `asset_content_contract_violation` (typed, not the generic
  handler). Document template boundary violations stay `409` as today.
- **Template read in production with unpublished template object:** inline publish at
  `catalog_seed`/registration (Decision 3) means a freshly bootstrapped
  deployment has template objects; if a corpus predates this change, `publish-assets`
  publishes them. If neither ran, the render path returns `object_missing` -> 503 (not a
  crash).
- **Idempotent re-publish:** re-running `publish-assets` or re-registering identical bytes
  is a no-op by content key; `storage.exists` skips the PUT; no duplicate objects.
- **Resume after crash mid-publish:** safe; ordered, per-row idempotent, existence-probed.
- **Unsafe `asset_path`:** still blocked by `verify_repository_asset` on the
  fallback/publish paths (path traversal, backslashes, escaping the allowed root).

## External input validation

- `asset_id` path params: unchanged UUID parsing by FastAPI (422 on malformed).
- DB `checksum`: trusted internal value; `checksum_object_key` requires the `sha256` form;
  the registration path only writes 64-hex checksums (enforced by the snapshot resource
  contract `pattern=r"^[0-9a-f]{64}$"` in `src/app/standards/library_snapshot.py`). The
  reader treats the DB checksum as the expected value and never trusts object bytes
  without re-verification.
- `publish-assets --batch-size`: positive int (argparse `type=int`); reject <= 0 with a
  CLI error. `--dry-run`, `--force`, `--verify-existing`: boolean flags.
- Object bytes from storage: untrusted until the sha256 re-verify passes.
- `presentation_template_ref` payload: produced internally by `build_artifact_payload`
  from a validated `TemplateVersion` row; `checksum` is a 64-hex string, `asset_path` is a
  repo-relative path re-validated by `verify_repository_asset` on the fallback branch.

## Invariant ownership

- **Checksum integrity (never serve mismatched bytes):** owned by
  `read_verified_asset_bytes` (the single re-verify gate, step 4), reinforced on the
  dev-fallback branch by `verify_repository_asset`. Centralizing the gate in one primitive
  is why this invariant cannot be bypassed by any of the three read sites.
- **Fallback-only-on-absence:** owned by the branch order in `read_verified_asset_bytes`
  (Decision 2); pinned by `test_reader_corrupt_object_never_falls_back`.
- **Verify-before-publish:** owned by `publish_verified_asset` (checks before any
  `put_file`).
- **Missing-vs-connectivity distinction:** owned by `S3ObjectStorage.open`
  (`ObjectNotFoundError` vs `ObjectStorageError`) and mirrored by every test fake.
- **Module ownership (which asset to read, how to interpret it):** owned by the standards/
  terminology routes and the documents service (presentation-only boundary), not by
  `common`.
- **Production never silently reads local disk:** owned by `config.py`
  `reject_unsafe_production_configuration`.
- **Capability-protocol stability:** owned by Decision 2b's phase split; no protocol
  signature changes.

## Testability

- **Unit (fast, no infra):**
  - `read_verified_asset_bytes` re-verify guard: fake `ObjectStorage` returning bytes
    whose sha256 != expected -> `AssetContentError("checksum_mismatch")`, no bytes
    returned.
  - **`test_reader_corrupt_object_never_falls_back`** (branch-order invariant): object present with
    wrong bytes + a `local_fallback` that would return valid bytes -> result is
    `checksum_mismatch` and the fallback callable is asserted never called.
  - `test_reader_storage_error_never_falls_back`: `storage.open` raises a non-missing
    `ObjectStorageError` + a `local_fallback` -> `storage_error`, fallback not called.
  - Fallback branch: object missing (`ObjectNotFoundError`) + `local_fallback`
    returning a valid/invalid path -> correct served/raised behavior.
  - `not_json_object`: verified bytes that are a JSON array/scalar ->
    `AssetContentError("not_json_object")`.
  - `publish_verified_asset` refuses to upload when local bytes mismatch
    (verify-before-publish): assert `put_file` never called.
  - `config` production safety: `app_env="production"` + `pinned_asset_local_fallback=True`
    raises.
  - Error mapping: each `AssetContentError.reason` maps to the specified status/code.
  - Storage boundary: `S3ObjectStorage.open` raises `ObjectNotFoundError` on a mocked
    `NoSuchKey` and `ObjectStorageError` on a mocked connectivity error; `exists` returns
    `False`/`True`/raises per mocked `head_object`.

- **Storage integration (Testcontainers/Compose MinIO):**
  - `publish_verified_asset` then `read_verified_asset_bytes` returns identical,
    checksum-verified bytes.
  - Missing-object read -> `object_missing` (fallback disabled) and -> served from disk
    (fallback enabled).
  - `exists` true/false against a real bucket; re-upload idempotency (same key, no error).

- **Contract tests (`tests/contract`):**
  - `GET /standard-assets/{id}/content` and `/terminology-assets/{id}/content` still
    return the same JSON object shape (OpenAPI unchanged). New cases: published asset ->
    200 with expected payload; unpublished asset (fallback off) -> `503 problem+json`
    `asset_content_unavailable`; non-object asset -> `500 problem+json`
    `asset_content_contract_violation`. **The OpenAPI response-model shape
    (`dict[str, object]`) and routes are unchanged**; only error-response assertions are
    added.

- **Migrations-from-clean-DB:** unchanged suite still passes because no migration is
  added; tests continue to apply migrations from zero.

- **Document rendering integration:** template content now read from object storage via
  the render-phase `load_presentation_template(storage, ref)`; assert a render using a
  published template produces the same output and that presentation-only boundary
  violations still raise `409`.
  - **Render-phase fallback channel (Finding 1):** with a fake `ObjectStorage` whose
    object is absent, assert `load_presentation_template` consults the local fallback
    **iff** `storage.local_fallback_enabled` is `True`: flag `True` + valid local file ->
    served; flag `False` -> `object_missing` (no disk read). This pins that the flag
    reaches the render phase through the storage object and nowhere else.
  - **Build/render key rename (Finding 2):** assert `build_artifact_payload` emits
    `presentation_template_ref` (checksum + renderer_versions + asset_path) and no longer
    emits `presentation_template`, and that `render_artifact` loads the template from the
    ref; a payload with the ref absent yields `presentation_template = None`.

The design is testable without wide refactors because the integrity gate, upload, and
existence probe are isolated primitives with an injectable `ObjectStorage` (the existing
fakes in `tests/integration/test_phase1_core.py` implement the Protocol and are updated
for `ObjectNotFoundError`/`exists`), the routes remain thin, and the capability protocol
signatures are untouched.

## Documentation to update

- **`docs/local-development.md`:**
  - §6 "Object storage workflow": note that pinned provider assets (standards,
    terminology, templates) now also live in object storage under checksum-addressed keys,
    uploaded by the registration/import/seed steps and backfilled by `publish-assets`.
  - §"Snapshotting and registering CDISC Library" / "Registering approved CDISC packages":
    state that registration now publishes verified bytes to object storage, and document
    the new `python -m app.cdisc_registry publish-assets [--batch-size N] [--dry-run]
[--force] [--verify-existing]` backfill for a corpus registered before this change.
    Document that it is idempotent and resumable, that it skips already-published objects
    with a cheap existence probe by default, that `--verify-existing` re-reads and
    re-verifies present objects, and that `--force` re-uploads unconditionally.
  - Note that `catalog_seed` now publishes template/platform assets inline so a fresh
    bootstrap needs no separate publish step for them.
  - Document `PINNED_ASSET_LOCAL_FALLBACK` (default `true` in dev, must be `false` in
    production) and that production rejects startup if it is enabled.

- **`docs/architecture.md`:**
  - Record the decision: pinned asset content lives in S3-compatible object storage keyed
    by `checksum_object_key(sha256)` in the artifact bucket; the DB keeps pointer +
    checksum as the integrity source of truth; the API is stateless w.r.t. asset content.
    Note the `common/asset_content.py` technical primitive, the re-verify-before-serve
    guarantee, the storage-boundary `ObjectNotFoundError`/`exists` extension, and that
    `verify_repository_asset` remains the offline verification/acquisition primitive.

- **`docs/artifact-catalog.md`:** **no change required (confirmed).** The catalog's
  storage-location column (`support/standards/`, `support/terminology/`, `support/reference/`
  "when selected") describes **submission-package placement** of generated manifests, not
  the runtime storage location of pinned provider-asset content. It records no per-asset
  "pinned assets live on the local filesystem" statement that this change would make
  stale. No edit needed.

## Open ambiguities, resolved

1. **Shared vs dedicated bucket/prefix** -> shared artifact bucket, no extra prefix
   (Decision 1a).
2. **Store vs derive object key** -> derive from checksum, no column, no migration
   (Decision 1b / 7).
3. **Where the reader lives** -> `src/app/common/asset_content.py`, technical primitive,
   no clinical logic (Decision 2).
4. **Missing-vs-connectivity distinction** -> typed `ObjectNotFoundError` at the storage
   boundary (Decision 0).
5. **Documents template read seam** -> phase split: boundary metadata in
   `build_artifact_payload`, byte read in `render_artifact`; no capability-protocol change
   (Decision 2b).
6. **Upload insertion point** -> inline in registration/import/seed (four sites, including
   `catalog_seed`) after local verify and before the DB txn; backfill via `publish-assets`
   (Decisions 3, 5).
7. **Dev fallback** -> object-first with explicit, production-disabled, absence-only,
   double-verified local fallback (Decision 4).
8. **Content-level error behavior** -> typed `AssetContentError` ->
   `503 asset_content_unavailable` (`object_missing`/`storage_error`),
   `500 asset_content_integrity_error` (`checksum_mismatch`),
   `500 asset_content_contract_violation` (`not_json_object`); never a raw generic 500
   (Decision 6).
9. **Transaction/object-store ordering** -> publish with no DB transaction held, then an
   inserts-only write transaction that trusts the already-validated manifest (Decision 3).
10. **OpenAPI** -> unchanged routes/params/response models; contract/typed-client fixtures
    change only to add new error-response assertions, not schema shape.

## Review findings — resolutions (current pass)

- **Finding 1 (HIGH, render-phase documents fallback flag has no delivery channel) —
  RESOLVED (review Option B).** The render phase (`load_presentation_template` inside
  `render_artifact`) has no `Settings` and the design forbids changing the
  `render_artifact`/`build_artifact_payload` capability signatures or injecting storage
  into the frozen `DocumentsCapability` descriptor. The fix adds a read-only
  `local_fallback_enabled: bool` attribute to the `ObjectStorage` Protocol and sets it in
  `S3ObjectStorage.__init__` from `settings.pinned_asset_local_fallback` (Decision 0).
  The worker constructs `S3ObjectStorage(settings)` once in `workers/job_worker.py`
  `main()` — the one site with `settings` in scope — so the flag travels with the
  `ObjectStorage` instance that `render_artifact` already receives.
  `load_presentation_template(storage, ref)` passes a local-fallback closure **iff**
  `storage.local_fallback_enabled` is `True` (Decision 2b / Decision 4 / "Exact files"
  item 4). The content-endpoint path keeps its existing channel
  (`request.app.state.settings`). Review Option A (threading `Settings` into
  `build_artifact_payload`) is explicitly considered and rejected for larger blast radius
  (Decision 4). No capability-protocol signature changes.

- **Finding 2 (MEDIUM, `render_artifact` still reads old `presentation_template` key) —
  RESOLVED.** Decision 2b and "Exact files" item 4 now state the exact edit: replace
  `presentation_template = payload.get("presentation_template")` with
  `ref = payload.get("presentation_template_ref")` then
  `presentation_template = load_presentation_template(storage, ref) if ref is not None
else None`; the downstream `render_pdf/docx/xlsx(..., presentation_template)` calls are
  unchanged, and the `documents_dependency_manifest` early-return branch is unaffected.
  The design explicitly warns that leaving the old key in place silently drops styling.

- **Finding 3 (MEDIUM, manifest-file publish media type unspecified) — RESOLVED.**
  Decision 3 and "Exact files" item 7 pin `media_type="application/json"` for the
  manifest-file publish in both `import_standard_manifest` and
  `import_terminology_manifest`, and for the library snapshot manifest file published by
  `load_and_publish_library_snapshot` (item 6). Per-asset rows keep their own
  `asset.media_type`.

- **Finding 4 (MEDIUM, inline publish not stated to cover every per-asset row) —
  RESOLVED.** Decision 3 now states the verify+publish pass publishes **one object per
  distinct checksum among {manifest file} ∪ {every referenced asset becoming a
  `StandardAsset`/`TerminologyAsset` row}** — the per-asset `checksum` the content
  endpoints actually derive their key from — not only the manifest/version checksum.
  "Exact files" item 7 repeats this. Content addressing dedupes identical bytes, so this
  cannot double-store.

- **Finding 5 (NIT, `catalog_seed` template-row count undercounted) — RESOLVED.**
  Decision 3 and "Exact files" item 5 enumerate all four seeded JSON assets explicitly
  (`dependency-selection-1.0.0.json`, `issue-severity-1.0.0.json`,
  `report-layout-1.0.0.json`, `document-layout-2.0.0.json`), each published with
  `application/json`, and call out that `document-layout` is the row the documents render
  path depends on.

- **Finding 6 (NIT, threading storage into `_checksum` mixes I/O into a pure primitive) —
  RESOLVED.** Decision 3 and "Exact files" item 5 now publish at each `session.add` site
  using the already-resolved `*_path` and the value returned by the **pure**
  `_checksum(*_path)`; `_checksum` is left as a pure hash helper and is not given
  `ObjectStorage`, matching the AGENTS.md "keep pure domain logic separate from I/O" rule.
