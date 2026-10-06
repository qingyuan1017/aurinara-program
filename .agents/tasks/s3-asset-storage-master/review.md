# Pinned provider asset content served from S3 object storage

The change moves pinned provider-asset *content* (CDISC standards, controlled terminology, presentation templates) off local disk and into the existing checksum-addressed object store, keyed by `checksum_object_key(sha256)` in the existing `clinical-artifacts` bucket. The DB `checksum` stays the integrity source of truth: a single sha256 re-verify gate runs before any byte is served, for both the object-storage read and the local-file fallback. No `object_key` column and no Alembic migration were added. A new `publish-assets` CLI backfills the store from registered rows; registration/seed now publish real file objects before the DB transaction. Content routes gain four typed error codes without changing their success shape or OpenAPI paths.

Watch for: nothing blocking. The group-digest HIGH (Decision 3) is honored — only real per-asset files and hand-maintained manifest files are published, never a synthetic version/release digest object (confirmed). Verification evidence (ruff/format/mypy/unit 53✓/contract 16✓ and the storage+documents integration suites + a 25,689-row `publish-assets --dry-run`) is present in `verification.md` and matches the committed code.

**Verdict**: APPROVED

## High-level view

The storage boundary now distinguishes a genuinely missing object from any other storage failure. `S3ObjectStorage.open` raises `ObjectNotFoundError` on NoSuchKey/404 and `ObjectStorageError` otherwise; `exists()` probes via `head_object`; `local_fallback_enabled` is a read-only policy flag. The `ObjectStorage` Protocol and both test fakes (`MemoryStorage`, the contract stub) carry the same surface (Decision 0).

The reader/publisher primitive in `common/asset_content.py` locks the branch order: object storage first, fallback consulted only for a genuinely missing object, every other storage error fails immediately without touching the fallback, and fetched bytes are always re-hashed against the expected checksum before return — for both branches (Decision 2). Publishing re-verifies the local file before upload and is an idempotent content-addressed no-op.

The two content routes translate `AssetContentError.reason` to exactly the Decision 6 table: `object_missing`→503 `asset_content_unpublished`, `storage_error`→503 `asset_content_store_unavailable`, `checksum_mismatch`→500 `asset_content_integrity_error`, `not_json_object`→500 `asset_content_contract_violation`. The 404 for a missing DB row and the `dict[str, object]` success model are unchanged.

The Documents phase split keeps the frozen capability signatures. The build phase resolves the `TemplateVersion` row and emits a `presentation_template_ref` payload key (replacing `presentation_template`), still raising the exact `RuntimeError("validated Template version is missing")` when the row is absent. The render phase reads bytes through the verified reader, driving the renderer check off `ref["renderer_versions"]` while preserving the presentation-only 409 boundary checks (Decision 2b).

Publishing is split before the DB transaction everywhere: library-snapshot registration publishes only per-resource real files (never a group digest), the hand-maintained importers publish the manifest file (+ standard assets), and `catalog_seed` publishes its four JSON files unconditionally before the exists-guards with a pure `_checksum` and a single terminal commit (Decisions 3/3b/5). The `publish-assets` CLI streams rows in keyset batches, skips present objects via `exists()`, skips group-digest version/release rows without error, and performs no DB mutation (Decision 4). The `pinned_asset_local_fallback` setting defaults True locally and is rejected in production (Decision 7).

<details>
<summary>Issues (0)</summary>

No blocking or non-blocking findings. Every FIXED DECISION (0–7) is satisfied as written and the required test coverage is present.

</details>

<details>
<summary>Details</summary>

### Decision 0 — storage boundary split (confirmed)

`src/app/artifacts/storage.py`: `ObjectNotFoundError(ObjectStorageError)` added. `open` (lines ~73-87) catches `ClientError`, routes NoSuchKey/404 to `ObjectNotFoundError` via `_is_missing_object` (which checks both the error code set `{NoSuchKey,NoSuchObject,404,NotFound}` and `HTTPStatusCode == 404`), and routes other `ClientError`/`BotoCoreError` to `ObjectStorageError("object download failed")`. `exists()` (lines ~89-100) returns True on `head_object` success, False on a missing-object code, and raises `ObjectStorageError` otherwise. The `ObjectStorage` Protocol declares `local_fallback_enabled: bool` and `exists(...)`. `MemoryStorage` (phase1) and the contract `_ContentStorage`/`_FakeStorage` fakes all raise `ObjectNotFoundError` on miss and expose `exists`/`local_fallback_enabled`.

### Decision 1 — checksum key, no column, no migration (confirmed)

Content is keyed via `checksum_object_key(asset.checksum)` into the existing bucket. `git show ff31574 --name-only` lists no file under `migrations/` and no `object_key` addition; `read_verified_asset_bytes`/`publish_verified_asset` derive the key purely from the sha256. (The `_source_object_key` in `documents/service.py` is the pre-existing `SourceFile.object_key`, unrelated to this scheme.)

### Decision 2 / 2b — verified reader and documents phase split (confirmed)

`common/asset_content.py` `read_verified_asset_bytes` enforces the locked order: open object; on `ObjectNotFoundError` fall back only if `local_fallback` is provided else raise `object_missing`; on any other `ObjectStorageError` raise `storage_error` immediately (fallback never consulted); then `sha256_hex(data) != expected` → `checksum_mismatch` for both branches; return bytes. `read_verified_asset_json_object` adds the `not_json_object` check. `publish_verified_asset` re-hashes the local file and raises `checksum_mismatch` before any `put_file`.

Documents (`documents/service.py`): `build_artifact_payload` resolves `TemplateVersion`, keeps the exact `RuntimeError("validated Template version is missing")`, and emits `presentation_template_ref = {checksum, renderer_versions, asset_path}` (or None). `render_artifact` reads `payload.get("presentation_template_ref")` and calls `load_presentation_template(storage, ref)`. `load_presentation_template(storage, ref)` reads bytes via the verified reader, builds the local fallback only when `storage.local_fallback_enabled`, drives the renderer check off `ref["renderer_versions"]`, and preserves the allowed-keys / styles / blank_structure / renderer 409 `ProblemException` boundary checks. The frozen `build_artifact_payload`/`render_artifact(payload, storage)` signatures are unchanged.

### Decision 3 / 3b — publish only real files; group digest never published (confirmed, HIGH)

`cdisc_library_registry.py` `load_and_publish_library_snapshot` verifies then publishes `publish_verified_asset(storage, root/item.asset_path, item.sha256, item.media_type)` once per `manifest.resources` entry and never publishes an object keyed by `_group_checksum`. `register_library_snapshot_rows` performs inserts only; `register_library_snapshot` remains a thin verify+insert wrapper for non-split callers. The standard importer publishes the manifest file (`application/json`, keyed by `manifest_checksum`) plus each `manifest.assets` entry; the terminology importer publishes the manifest file only and does not iterate `manifest.assets` (the CT manifest has none and creates no `TerminologyAsset` rows). `catalog_seed.seed` publishes the four pinned JSON files with `media_type="application/json"`.

`catalog_seed.py`: the four `publish_verified_asset` calls run in a loop *before* the `if session.get(...) is None:` guards, `_checksum(path)` stays pure (hash + ROOT check, no storage), and a single terminal `session.commit()` remains. `main()` builds `S3ObjectStorage(get_settings())` and calls `seed(session, storage)`.

### Decision 4 — publish-assets CLI (confirmed)

`cdisc_registry.py` `publish-assets` subcommand exposes `--batch-size` (default 500, rejects `<= 0`), `--dry-run`, `--verify-existing`, `--force`. `_publish_asset_row` skips when `storage.exists(key)` and not `--force`; `--verify-existing` re-reads+re-hashes and re-publishes on corruption; `--dry-run` reports present/would-upload and writes nothing. `_is_group_digest` computes the on-disk file sha256 (`verify_repository_asset(..., None, ...)`) and returns True when it differs from the stored checksum, so version/release group-digest rows are skipped without error. Rows are streamed by keyset (`_stream_rows`) in short read-only sessions; no commit and no DB mutation occur.

### Decision 5 — publish before/outside the DB txn (confirmed)

`_register_snapshot` calls `load_and_publish_library_snapshot(...)` before `factory.begin()`, then only `register_library_snapshot_rows` inside the `with` block. `_register_manifests` publishes every standard/terminology manifest before `factory.begin()`, then runs the inserts-only importers inside it.

### Decision 6 — content-route error mapping (confirmed)

`api/catalogs.py` `_ASSET_CONTENT_PROBLEMS` maps the four reasons to exactly (503 `asset_content_unpublished`), (503 `asset_content_store_unavailable`), (500 `asset_content_integrity_error`), (500 `asset_content_contract_violation`). Both `get_standard_asset_content` and `get_terminology_asset_content` wrap the reader in `try/except AssetContentError` → `_asset_content_problem`, so no raw 500 escapes. The 404 `*_asset_not_found` path (`_require`) and `response_model=dict[str, object]` are unchanged; the contract test asserts the OpenAPI 200 schema is still a free-form object.

### Decision 7 — fallback setting and production rejection (confirmed)

`config.py` adds `pinned_asset_local_fallback: bool = True`; `reject_unsafe_production_configuration` appends `"pinned asset local fallback"` to `unsafe` when `app_env == "production"` and the flag is True. `S3ObjectStorage.__init__` reads it into `local_fallback_enabled`.

### Test coverage

Present and aligned with the plan: `tests/unit/test_asset_content.py` covers the re-verify gate (object + fallback), never-fall-back-on-corrupt, never-fall-back-on-storage-error, object_missing, not_json_object, publish-refuses-on-mismatch, S3 `open`/`exists` boto3 branch mapping, group-digest skip, and `load_presentation_template` fallback on/off. `tests/contract/test_catalog_asset_content.py` asserts 200 object shape, 503 `asset_content_unpublished`, 500 `asset_content_contract_violation`, 404 missing row, and unchanged OpenAPI response model. `tests/integration/test_asset_storage.py` covers publish→verified read, missing→object_missing, local fallback served, tampered→checksum_mismatch, and re-upload idempotency. `tests/unit/test_config.py` covers the production rejection and the `False`-accepted case. Phase1/Phase2 integration tests use the updated `seed(session, storage)` signature and the Decision-0-parity `MemoryStorage`.

Not independently re-run per the brief's verification discipline; `verification.md` records ruff/format/mypy, unit (53), contract (16), the storage/documents integration suites, and a 25,689-row `publish-assets --dry-run` that skipped 270 group-digest rows without error. The evidence is specific and consistent with the committed code, so no spot-check was warranted.

</details>

<details>
<summary>File map</summary>

- `src/app/artifacts/storage.py` — `ObjectNotFoundError`, `exists()`, `local_fallback_enabled`, split `open` error mapping.
- `src/app/common/asset_content.py` — new verified reader/publisher primitive with locked branch order.
- `src/app/api/catalogs.py` — Decision 6 error mapping + storage dependency on both content routes.
- `src/app/documents/service.py` — phase split: `presentation_template_ref` payload key, render-phase byte read via reader.
- `src/app/config.py` — `pinned_asset_local_fallback` setting + production rejection.
- `src/app/catalog_seed.py` — publish four pinned assets before the exists-guards; `seed(session, storage)`.
- `src/app/cdisc_library_registry.py` — publish-before-txn split; only per-resource files published.
- `src/app/standards/importer.py`, `src/app/terminology/importer.py` — manifest/asset publish helpers.
- `src/app/cdisc_registry.py` — storage wiring + `publish-assets` backfill subcommand with group-digest skip.
- `tests/unit/test_asset_content.py`, `tests/unit/test_config.py`, `tests/contract/test_catalog_asset_content.py`, `tests/integration/test_asset_storage.py`, `tests/integration/test_phase1_core.py`, `tests/integration/test_phase2_documents.py` — coverage.
- `docs/architecture.md`, `docs/local-development.md` — settings/CLI documentation.

Full diff: `git show ff31574` on branch `master`.

</details>
