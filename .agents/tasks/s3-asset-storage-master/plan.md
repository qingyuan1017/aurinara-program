# Implementation Plan: Pinned Provider Assets in S3-Compatible Object Storage

This plan pins the exact per-file contract for moving pinned provider-asset **content**
(CDISC standards under `schemas/`, controlled terminology under `terminology/`,
presentation templates under `templates/`) from local disk into the existing S3-compatible
object store, keyed by `checksum_object_key(sha256)`, with the DB `checksum` kept as the
integrity source of truth and a single sha256 re-verify gate before any byte is served.

It implements the design (`.agents/tasks/s3-asset-storage-master/s3-asset-design.md`) as
amended by the brief's FIXED DECISIONS 0–7, which resolve the review findings in
`s3-asset-design-review.md`. The FIXED DECISIONS are final; where source differed from the
original design text, this plan follows the decision (discrepancies noted inline).

## Source confirmation (read before implementing)

Every seam below was read in the live source and matches the brief:

- `src/app/artifacts/storage.py` — `ObjectStorageError`, `ObjectStorage` Protocol
  (`put_file`/`open`/`check` only), `S3ObjectStorage` (boto3, path-style via
  `object_store_path_style`), `checksum_object_key(sha256) -> "sha256/<aa>/<bb>/<sha256>"`.
  `S3ObjectStorage.open` collapses `BotoCoreError`/`ClientError` (incl. `NoSuchKey`) into
  one `ObjectStorageError("object download failed")` — confirmed; must be split (Decision 0).
- `src/app/common/repository_assets.py` — `verify_repository_asset(repository_root,
  relative_path, expected_sha256=None, *, allowed_root) -> tuple[Path, str]`; rejects
  absolute/`..`/backslash paths, enforces `allowed_root`, re-reads bytes, recomputes sha256,
  raises `ValueError` on mismatch. Confirmed.
- `src/app/common/canonical.py` — `sha256_hex(value: bytes) -> str`, plus `canonical_json`.
  Confirmed (reader/publisher depend only on `storage` + `sha256_hex`).
- `src/app/api/catalogs.py` — `get_standard_asset_content` (allowed_root `"schemas"`) and
  `get_terminology_asset_content` (allowed_root `"terminology"`); both
  `response_model=dict[str, object]`, call `verify_repository_asset` + `json.loads` + bare
  `RuntimeError` on non-dict. Neither takes `Request` or a storage dep today. Confirmed.
- `src/app/documents/service.py` — `load_presentation_template(session, template_version_id)`
  called only from `build_artifact_payload` (writes payload key `presentation_template`);
  `render_artifact(self, payload, storage)` reads
  `cast(dict|None, payload.get("presentation_template"))`. The missing-row raise is exactly
  `RuntimeError("validated Template version is missing")`. Confirmed.
- Capability signatures `build_artifact_payload(session, aggregate_id, study_id,
  artifact_type)` and `render_artifact(payload, storage)` are FROZEN (dispatched generically
  in `src/app/artifacts/builds.py` / `src/app/kernel/dependencies.py`). Confirmed.
- `src/app/catalog_seed.py` — `seed(session)` (no storage), `_checksum(path)` pure
  (hash + ROOT check), four pinned JSON assets, each `session.add` nested inside
  `if session.get(...) is None:`, single terminal `session.commit()`. `main()` opens
  `with factory() as session: seed(session)`. Confirmed. Callers of `seed(`:
  `catalog_seed.main`, `tests/integration/test_phase1_core.py`,
  `tests/integration/test_phase2_documents.py`.
- `src/app/cdisc_library_registry.py` — `_register_standard_group`/`_register_terminology_group`
  set `checksum=_group_checksum(resources)` (synthetic inventory digest, NOT a file sha256);
  `StandardAsset`/`TerminologyAsset` rows use per-item `checksum=item.sha256` (real files).
  `load_library_snapshot` verifies manifest + every resource; `register_library_snapshot`
  verifies + inserts. Confirmed — Decision 3 HIGH fix applies.
- `src/app/standards/importer.py` — `load_standard_manifest -> (manifest, relative_path,
  manifest_checksum)`; `StandardVersion.checksum = manifest_checksum` (real manifest file
  sha256 on THIS path); per-asset `StandardAsset.checksum = asset.sha256`. Confirmed.
- `src/app/terminology/importer.py` — `load_terminology_manifest -> (manifest, relative_path,
  checksum)`; `TerminologyRelease.checksum = checksum` (real manifest file sha256);
  creates `TerminologyCodelist`/`TerminologyTerm` rows ONLY — **no `TerminologyAsset` rows**,
  manifest has no `assets` collection (confirmed in `terminology/contracts.py`). Decision 3(c).
- `src/app/cdisc_registry.py` — `register-snapshot` / `register-manifests` call registration
  functions inside `with factory.begin() as session:`. `REPOSITORY_ROOT = parents[2]`.
  `_snapshot_all` has a `progress(count, href)` callback to mirror. Confirmed.
- `src/app/config.py` — `Settings` with `object_store_*`; `reject_unsafe_production_configuration`
  appends labels to `unsafe` and raises when non-empty and `app_env == "production"`. Confirmed.
- `workers/job_worker.py` `main()` builds `storage = S3ObjectStorage(settings)` (settings in
  scope). `src/app/main.py` `create_app(..., object_storage=...)` builds/accepts it into
  `app.state.object_storage`. `src/app/api/dependencies.py` exposes `get_object_storage`.
  `src/app/api/health.py` readiness probes `storage.check()` only. Confirmed.
- `tests/integration/test_phase1_core.py` `MemoryStorage(ObjectStorage)` — `open` yields
  `io.BytesIO(self.objects[object_key])` (bare `KeyError` on miss), no `exists`, no
  `local_fallback_enabled`. Confirmed — Decision 0 fake parity required.
- `StandardAsset`, `TerminologyAsset` both have `media_type`, `asset_path`, `checksum`
  columns. Confirmed (publish-assets uses `asset.media_type`).

No source contradicted a FIXED DECISION; all decisions are implemented as written.

## Verification contract (gate commands, from repo root)

Per `docs/local-development.md` and `pyproject.toml`. The brief specifies the `uv run`
form; docs show the bare form — both run the same tools. Use:

- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run mypy src workers`
- `uv run pytest tests/unit`
- `uv run pytest tests/contract`
- Storage/integration suites requiring MinIO+Postgres (Testcontainers or Compose test
  profile), with `AURINARA_INTEGRATION=1` where the suite requires it (e.g.
  `$env:AURINARA_INTEGRATION = "1"; uv run pytest tests/integration/test_phase2_documents.py`).

"Verify" lines below name the narrowest relevant command first; run the broader gate set
before handoff. Grep is never verification.

## Decision 6 error-code table (pin exactly; implement at the content routes)

`AssetContentError.reason` → HTTP problem (`application/problem+json`):

| `reason`           | HTTP | problem `code`                     | when                                                              |
| ------------------ | ---- | ---------------------------------- | ----------------------------------------------------------------- |
| `object_missing`   | 503  | `asset_content_unpublished`        | object absent AND (fallback disabled OR local file also absent)   |
| `storage_error`    | 503  | `asset_content_store_unavailable`  | non-NoSuchKey BotoCore/ClientError from `open`/`exists`           |
| `checksum_mismatch`| 500  | `asset_content_integrity_error`    | fetched bytes' sha256 ≠ DB checksum (object OR fallback branch)   |
| `not_json_object`  | 500  | `asset_content_contract_violation` | verified bytes do not parse to a top-level JSON object (dict)     |

(Note: the design's original table used `asset_content_unavailable` for both 503s; FIXED
Decision 6 splits them into `asset_content_unpublished` / `asset_content_store_unavailable`.
This plan uses the split codes.) The route still returns `404 standard_asset_not_found` /
`terminology_asset_not_found` for a missing DB row (unchanged `_require`). No raw/generic
500 may leave the content read path.

## Key derivation (single scheme, platform-wide)

`object_key = checksum_object_key(asset.checksum)` → `sha256/<aa>/<bb>/<sha256>`, in the
existing `object_store_bucket` (default `clinical-artifacts`). No `object_key` column, no
Alembic migration (Decisions 1a/1b/7).

## Group-digest skip detection (Decision 3 HIGH / Decision 4)

A `standard_versions` / `terminology_releases` row whose stored `checksum` is a
`_group_checksum(resources)` has **no own publishable file object**. Detect by computing the
actual on-disk file sha256 of the row's `asset_path` (via `verify_repository_asset(... ,
expected_sha256=None, ...)`, which returns `actual_sha256`) and comparing to the stored
`checksum`: if `actual_file_sha256 != stored_checksum`, the row is a group digest → **skip**
(treat as "no own file object"), do NOT error, do NOT publish a version/release object.
When they are equal (hand-maintained importer paths), the row's file (the manifest) IS
publishable. `StandardAsset`/`TerminologyAsset` rows always use real file sha256 and are
always publishable.

---

# Implementation Plan

- [ ] 1. Extend the storage boundary with a typed missing-object error, an `exists` probe,
      and a read-only `local_fallback_enabled` policy flag (Decision 0).
      In `src/app/artifacts/storage.py`: add `class ObjectNotFoundError(ObjectStorageError)`.
      In `S3ObjectStorage.open`, split the `except`: on `ClientError` whose
      `error.response["Error"]["Code"]` is in `{"NoSuchKey","NoSuchObject","404"}` raise
      `ObjectNotFoundError("object not found")`, else `ObjectStorageError("object download
      failed")`; keep `BotoCoreError -> ObjectStorageError`. Add
      `S3ObjectStorage.exists(object_key) -> bool` backed by `head_object` (True on success;
      False on `ClientError` code in `{"NoSuchKey","NoSuchObject","404","NotFound"}`; else
      raise `ObjectStorageError("object existence check failed")`; `BotoCoreError ->
      ObjectStorageError`). In `__init__` set
      `self.local_fallback_enabled = settings.pinned_asset_local_fallback` (added in item 9;
      sequence item 9 or add the setting first — see note). Add to the `ObjectStorage`
      Protocol: attribute `local_fallback_enabled: bool` and method
      `exists(self, object_key: str) -> bool`.
      Files: src/app/artifacts/storage.py
      Verify: `uv run mypy src workers` passes; `uv run pytest tests/unit` passes (new unit
      tests from item 11 cover the `open`/`exists` branch mapping).
      Note: item 1 reads `settings.pinned_asset_local_fallback`; do item 9 first OR add the
      setting in the same change set so `S3ObjectStorage.__init__` compiles.

- [ ] 2. Add the config setting and production safety check (Decision 4/7).
      In `src/app/config.py` add `pinned_asset_local_fallback: bool = True` (env
      `PINNED_ASSET_LOCAL_FALLBACK`). In `reject_unsafe_production_configuration`, when
      `app_env == "production"` and `self.pinned_asset_local_fallback` is True, append
      `"pinned asset local fallback"` to `unsafe`.
      Files: src/app/config.py
      Verify: `uv run pytest tests/unit` — new config test asserts
      `Settings(_env_file=None, app_env="production", pinned_asset_local_fallback=True, ...)`
      raises `ValueError`, and that `False` in production is accepted (with other prod-safe
      values). `uv run mypy src workers` passes.

- [ ] 3. Create the runtime reader/publisher primitive (Decision 2).
      New file `src/app/common/asset_content.py`. Define:
      `AssetContentReason = Literal["object_missing","checksum_mismatch","storage_error","not_json_object"]`;
      `class AssetContentError(RuntimeError)` with `__init__(self, reason, *, checksum)`
      storing `.reason` and `.checksum`;
      `read_verified_asset_bytes(storage, expected_sha256, *, local_fallback: Callable[[], Path] | None = None) -> bytes`
      with the LOCKED branch order: (1) `key = checksum_object_key(expected_sha256)`;
      (2) open+read via `storage.open(key)` — on `ObjectNotFoundError` go to step 3; on any
      other `ObjectStorageError` raise `AssetContentError("storage_error", checksum=...)`
      immediately (fallback NOT consulted); (3) only-if-missing: if `local_fallback` is not
      None read bytes from `local_fallback()` path, else raise
      `AssetContentError("object_missing", ...)`; (4) recompute `sha256_hex(data)`, if
      `!= expected_sha256` raise `AssetContentError("checksum_mismatch", ...)` immediately —
      runs for BOTH branches; (5) return bytes.
      `read_verified_asset_json_object(...) -> dict[str, object]` = bytes + `json.loads`;
      raise `AssetContentError("not_json_object", ...)` if the parsed value is not a dict.
      `publish_verified_asset(storage, local_path, expected_sha256, media_type) -> str`:
      recompute `sha256_hex(local_path.read_bytes())`; if `!= expected_sha256` raise
      `AssetContentError("checksum_mismatch", ...)` BEFORE any upload; else
      `storage.put_file(checksum_object_key(expected_sha256), local_path, media_type)` and
      return the key (content-addressed re-upload is a no-op).
      Depends only on `app.artifacts.storage` and `app.common.canonical`; no clinical logic.
      Files: src/app/common/asset_content.py
      Verify: `uv run mypy src workers` passes; `uv run pytest tests/unit` passes (item 11
      exercises every branch).

- [ ] 4. Add the Decision 6 error translation at the two content routes (Decisions 2, 4, 6).
      In `src/app/api/catalogs.py`: import `Request` from fastapi, `get_object_storage` from
      `app.api.dependencies`, `ObjectStorage` from `app.artifacts.storage`, and
      `AssetContentError`/`read_verified_asset_json_object` from `app.common.asset_content`.
      Add a module-level helper `_asset_content_problem(error: AssetContentError) ->
      ProblemException` mapping each `error.reason` per the Decision 6 table above (503
      `asset_content_unpublished` / 503 `asset_content_store_unavailable` / 500
      `asset_content_integrity_error` / 500 `asset_content_contract_violation`).
      In `get_standard_asset_content`: add params `request: Request` and
      `storage: Annotated[ObjectStorage, Depends(get_object_storage)]`; read
      `settings = request.app.state.settings`; replace the `verify_repository_asset` +
      `json.loads` + bare `RuntimeError` block with
      `return read_verified_asset_json_object(storage, asset.checksum,
      local_fallback=(lambda: verify_repository_asset(REPOSITORY_ROOT, asset.asset_path,
      asset.checksum, allowed_root="schemas")[0]) if settings.pinned_asset_local_fallback
      else None)` wrapped in `try/except AssetContentError as error: raise
      _asset_content_problem(error)`. Keep `response_model=dict[str, object]` unchanged.
      Do the same for `get_terminology_asset_content` with `allowed_root="terminology"`.
      Keep handlers thin (no logic beyond `_require` + the read). Do NOT change OpenAPI
      routes or response models.
      Files: src/app/api/catalogs.py
      Verify: `uv run pytest tests/contract` passes (item 12 updates/adds error-code cases);
      `uv run mypy src workers` passes.

- [ ] 5. Documents phase split: carry a template ref in the payload and read bytes in the
      render phase (Decisions 2b, 4). NO capability-protocol signature change.
      In `src/app/documents/service.py`:
      (a) Rework `load_presentation_template` to signature
      `load_presentation_template(storage: ObjectStorage, ref: dict[str, object]) ->
      dict[str, object]`. Read bytes via `read_verified_asset_json_object(storage,
      str(ref["checksum"]), local_fallback=(lambda: verify_repository_asset(
      Path(__file__).resolve().parents[3], str(ref["asset_path"]), str(ref["checksum"]),
      allowed_root="templates")[0]) if storage.local_fallback_enabled else None)`. Keep the
      EXISTING presentation-only boundary checks verbatim (allowed_keys subset, styles/
      blank_structure typing, renderer check), but drive the renderer check from
      `ref["renderer_versions"]` instead of a `TemplateVersion` row (i.e.
      `"document-1" not in ref["renderer_versions"] or value.get("renderer") != "document-1"`).
      Keep all `ProblemException` 409 raises (`template_content_boundary_violation`,
      `template_renderer_incompatible`). Import `AssetContentError`/
      `read_verified_asset_json_object`.
      (b) In `build_artifact_payload` (session phase): resolve the `TemplateVersion` row by
      `selected_templates[0].template_version_id`; if the row is absent keep raising the
      EXACT `RuntimeError("validated Template version is missing")` (worker-phase error, NOT
      part of Decision 6 mapping). Build
      `presentation_template_ref = {"checksum": version.checksum, "renderer_versions":
      version.renderer_versions, "asset_path": version.asset_path}` (or `None` when no
      template selected). Replace the payload key: emit `"presentation_template_ref": ...`
      instead of `"presentation_template": presentation_template`. Do NOT read bytes here.
      (c) In `render_artifact`: replace
      `presentation_template = cast(dict[str, object] | None,
      payload.get("presentation_template"))` with
      `ref = cast(dict[str, object] | None, payload.get("presentation_template_ref"))` then
      `presentation_template = load_presentation_template(storage, ref) if ref is not None
      else None`. The downstream `render_pdf/render_docx/render_xlsx(..., presentation_template)`
      call sites are UNCHANGED. Remove the now-unused session-based template load in build.
      Files: src/app/documents/service.py
      Verify: `uv run mypy src workers` passes; `uv run pytest tests/unit` passes; documents
      render integration (item 13) passes under MinIO.

- [ ] 6. Make `catalog_seed.seed` publish its four assets unconditionally and thread storage
      through all callers (Decisions 3, 3b).
      In `src/app/catalog_seed.py`: change signature to `seed(session: Session, storage:
      ObjectStorage) -> None`. Keep `_checksum(path)` PURE (no storage). For each of the four
      pinned assets, call `publish_verified_asset(storage, <*_path>, _checksum(<*_path>),
      "application/json")` BEFORE/OUTSIDE each `if session.get(...) is None:` guard (so seed
      self-heals a DB-exists/object-missing state and stays an idempotent content-addressed
      no-op): `standard_path`, `terminology_path`, `template_path`,
      `document_template_path`. Keep the single terminal `session.commit()`. In `main()`
      build `storage = S3ObjectStorage(get_settings())` and call `seed(session, storage)`.
      Import `publish_verified_asset` and `S3ObjectStorage`/`ObjectStorage`.
      Files: src/app/catalog_seed.py
      Verify: `uv run mypy src workers` passes; `uv run pytest tests/unit` passes (callers in
      items 10/13 updated in lockstep so integration suites still import cleanly).

- [ ] 7. Publish objects during library-snapshot registration with a publish-before-txn
      split (Decision 3a, 5-shape). Publish ONLY real file objects; do NOT publish a
      version/release manifest object here.
      In `src/app/cdisc_library_registry.py`: add
      `load_and_publish_library_snapshot(storage: ObjectStorage, manifest_path: Path,
      repository_root: Path) -> CdiscLibrarySnapshotManifest` that calls the existing
      `load_library_snapshot` (verify pass) and then, with NO DB txn held, calls
      `publish_verified_asset(storage, repository_root / item.asset_path, item.sha256,
      item.media_type)` once per `StandardAsset`/`TerminologyAsset` resource (every
      `manifest.resources` entry; `item.media_type` is `application/json`). Do NOT publish an
      object keyed by any group digest. Refactor `register_library_snapshot` into
      `register_library_snapshot_rows(session, manifest, repository_root)` that performs
      inserts ONLY (no object-store I/O, no second full verify pass — trusts the manifest the
      publish pass validated). Keep `register_library_snapshot(session, manifest_path,
      repository_root)` as a thin wrapper that calls `load_library_snapshot` +
      `register_library_snapshot_rows` for any caller not doing the publish split (preserves
      current behavior/tests). Import `publish_verified_asset`, `ObjectStorage`.
      Files: src/app/cdisc_library_registry.py
      Verify: `uv run mypy src workers` passes; `uv run pytest tests/unit` and existing
      registry tests pass.

- [ ] 8. Publish objects during the hand-maintained importers with the same publish-before-txn
      split (Decision 3b/3c, 5-shape).
      In `src/app/standards/importer.py`: add an importer-level verify+publish step (new
      function e.g. `publish_standard_manifest(storage, manifest_path, repository_root)` that
      calls `load_standard_manifest` then publishes, with NO DB txn held: the manifest file
      with `media_type="application/json"` keyed by `manifest_checksum` (== stored
      `StandardVersion.checksum` on this path), plus each `asset` in `manifest.assets` keyed
      by `asset.sha256` with `asset.media_type`). Keep `import_standard_manifest` as the
      inserts-only step. In `src/app/terminology/importer.py`: add
      `publish_terminology_manifest(storage, manifest_path, repository_root)` that publishes
      the MANIFEST FILE ONLY (`media_type="application/json"`, keyed by `checksum` == stored
      `TerminologyRelease.checksum`); this path creates NO `TerminologyAsset` rows and the CT
      manifest has NO `assets` collection — do NOT iterate `manifest.assets`. Keep
      `import_terminology_manifest` inserts-only.
      Files: src/app/standards/importer.py, src/app/terminology/importer.py
      Verify: `uv run mypy src workers` passes; `uv run pytest tests/unit` and existing
      importer tests pass.

- [ ] 9. Wire storage + publish-before-txn ordering into the CLI and add the `publish-assets`
      backfill subcommand (Decisions 3, 4, 5).
      In `src/app/cdisc_registry.py`:
      (a) Import `S3ObjectStorage`, `checksum_object_key`, the new publish helpers, and
      `verify_repository_asset`, `publish_verified_asset`, `AssetContentError`, plus
      `StandardAsset`/`TerminologyAsset`/`StandardVersion`/`TerminologyRelease` models and
      `select`.
      (b) `_register_snapshot`: build `storage = S3ObjectStorage(settings)`; call
      `manifest = load_and_publish_library_snapshot(storage, manifest_path.resolve(),
      REPOSITORY_ROOT)` BEFORE `factory.begin()`; inside `with factory.begin() as session:`
      call `register_library_snapshot_rows(session, manifest, REPOSITORY_ROOT)`.
      (c) `_register_manifests`: build storage; for each standard/terminology manifest call
      the item-8 publish helper BEFORE the txn, then run the inserts-only importer inside
      `with factory.begin() as session:`.
      (d) Add subcommand `publish-assets` with args `--batch-size` (int, default 500, reject
      `<= 0`), `--dry-run`, `--verify-existing`, `--force` (all store_true). Behavior: build
      `storage = S3ObjectStorage(settings)` and a read-only session factory; stream
      `standard_assets`, `terminology_assets` ordered by PK in `--batch-size` batches, plus
      the hand-maintained manifest files on `standard_versions`/`terminology_releases`
      (apply the GROUP-DIGEST SKIP: compute actual file sha256 via
      `verify_repository_asset(REPOSITORY_ROOT, row.asset_path, None, allowed_root=...)` and
      skip rows whose `actual != stored checksum`, without error). For each publishable row:
      derive `key = checksum_object_key(row.checksum)`; default skip when
      `storage.exists(key)`; `--verify-existing` re-reads+re-hashes present objects and
      re-publishes on corruption; `--force` re-uploads unconditionally; otherwise
      `verify_repository_asset(REPOSITORY_ROOT, row.asset_path, row.checksum,
      allowed_root=<"schemas"|"terminology">)` then `publish_verified_asset(storage, path,
      row.checksum, row.media_type)`. `--dry-run` reports present/would-upload using
      `exists`, writes nothing. No DB mutation; short read-only sessions per batch; structured
      progress mirroring `_snapshot_all`'s `progress(count, id)`; log keys/checksums at debug
      only, never bytes. Add the parser in `_arguments` and dispatch in `main`.
      Files: src/app/cdisc_registry.py
      Verify: `uv run mypy src workers` passes; `uv run pytest tests/unit` passes;
      `uv run python -m app.cdisc_registry publish-assets --dry-run` runs without error
      against a seeded local DB+MinIO (manual/integration check in item 13).

- [ ] 10. Update every `ObjectStorage` test fake and `seed(...)` call site for Decision 0
      parity and the new `seed` signature.
      In `tests/integration/test_phase1_core.py` `MemoryStorage`: `open` raises
      `ObjectNotFoundError` on a missing key (not bare `KeyError`); add
      `exists(self, object_key) -> bool`; add attribute `local_fallback_enabled: bool`
      (default False, settable per test). Update both `seed(session)` call sites
      (`test_phase1_core.py`, `test_phase2_documents.py`) to `seed(session, storage)` passing
      the fake. Apply the same `open`/`exists`/`local_fallback_enabled` update to any other
      `ObjectStorage` fake found in `tests/`.
      Files: tests/integration/test_phase1_core.py, tests/integration/test_phase2_documents.py
      (and any other fake)
      Verify: `uv run mypy src workers` passes; the integration suites import and the storage
      fakes satisfy the Protocol (`uv run pytest tests/integration/test_phase1_core.py` with
      MinIO/Postgres available, or the suite's required `AURINARA_INTEGRATION` flag).

- [ ] 11. Add unit tests for the storage boundary, reader/publisher, and config (Decision 0,
      2, 4).
      New `tests/unit/test_asset_content.py` (or module-appropriate location): re-verify gate
      — fake storage returns wrong bytes → `checksum_mismatch`, no bytes returned;
      `test_reader_corrupt_object_never_falls_back` — present-but-wrong bytes + a
      `local_fallback` that would return valid bytes → `checksum_mismatch` AND fallback never
      invoked; `test_reader_storage_error_never_falls_back` — `open` raises non-missing
      `ObjectStorageError` + a fallback → `storage_error`, fallback not called; fallback
      branch — `ObjectNotFoundError` + fallback returning a valid path → served; `not_json_object`
      — verified bytes that are a JSON array/scalar → `not_json_object`;
      `publish_verified_asset` refuses to upload on local mismatch (assert `put_file` never
      called). Storage boundary unit tests (mock boto3 client): `open` raises
      `ObjectNotFoundError` on `NoSuchKey` and `ObjectStorageError` on a connectivity error;
      `exists` returns True/False/raises per mocked `head_object`. Config test from item 2.
      Files: tests/unit/test_asset_content.py (+ storage/config unit test files)
      Verify: `uv run pytest tests/unit` — all new tests pass; `uv run mypy src workers` passes.

- [ ] 12. Update contract tests for the new content error codes (Decision 6).
      In the relevant file under `tests/contract/`: keep the success-shape assertions
      (`dict[str, object]`, OpenAPI unchanged); add cases — published asset → 200 with the
      expected payload; unpublished asset with fallback OFF → 503 `problem+json` code
      `asset_content_unpublished`; non-object asset bytes → 500 `problem+json` code
      `asset_content_contract_violation`. Assert routes/response model are unchanged
      (no OpenAPI diff).
      Files: tests/contract/<catalog content test>.py
      Verify: `uv run pytest tests/contract` passes.

- [ ] 13. Add storage/documents integration tests (Decision 2, 2b, 4, 5).
      Storage-integration (Testcontainers/Compose MinIO): `publish_verified_asset` then
      `read_verified_asset_bytes` returns identical checksum-verified bytes; missing-object
      read → `object_missing` (fallback off) and served-from-disk (fallback on, valid local
      file); tampered/corrupt present object → `checksum_mismatch`; `exists` true/false; and
      re-upload idempotency (same key, no error). Documents render integration: a render
      using a published template produces the same output; with a fake storage whose object
      is absent, `load_presentation_template` consults the local fallback IFF
      `storage.local_fallback_enabled` is True; presentation-only boundary violations still
      raise 409. Add a `publish-assets` resumability/idempotency check (second run skips via
      `exists`).
      Files: tests/integration/<storage + documents content tests>.py
      Verify: with MinIO+Postgres up, `$env:AURINARA_INTEGRATION = "1"; uv run pytest
      tests/integration` (and `tests/integration/test_phase2_documents.py`) passes.

- [ ] 14. Full gate pass and docs sync.
      Run the whole verification contract. Update `docs/local-development.md` to document the
      `pinned_asset_local_fallback` setting (default True local, must be False in production)
      and the `python -m app.cdisc_registry publish-assets [--batch-size N] [--dry-run]
      [--verify-existing] [--force]` backfill step after `alembic upgrade head` /
      `catalog_seed`. No Alembic migration is added (Decision 1b/7); confirm no new migration
      files were created.
      Files: docs/local-development.md
      Verify: `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src workers`,
      `uv run pytest tests/unit`, `uv run pytest tests/contract` all pass; integration/storage
      suites pass under MinIO+Postgres with `AURINARA_INTEGRATION=1` where required.

## Notes / assumptions

- Ordering: items 1–3 are the foundation (storage boundary, config, reader). Items 4–9 are
  consumers and the CLI; each leaves the tree buildable. Item 10 updates fakes/call sites in
  lockstep with the `seed` and Protocol changes (do item 10 together with items 1/6 if a
  suite would otherwise fail to import mid-sequence). Items 11–13 add tests; item 14 is the
  final gate + docs.
- Decision 3 HIGH is honored throughout: NO version/release group-digest object is ever
  published or re-verified as a file; only per-asset rows and hand-maintained manifest files
  are published.
- No OpenAPI `/api/v1` content-route change: both content handlers keep
  `response_model=dict[str, object]` and their paths; only new error responses are asserted.
- No Alembic migration: Decision 1b derives the key from the existing `checksum`.
