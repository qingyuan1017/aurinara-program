# Final Handoff — Pinned provider asset content served from S3 object storage

Branch: `master` (no worktree). Status: implemented, reviewed **APPROVED**, committed locally.
**Nothing was pushed.**

## 1. Files / functions changed

Functional change committed as `ff31574` — *"feat: serve pinned provider asset content from S3 object storage"* (19 files, +1159/-62).

| File | What changed |
| --- | --- |
| `src/app/artifacts/storage.py` | Added `ObjectNotFoundError(ObjectStorageError)`. `S3ObjectStorage.open` now splits boto3 errors: NoSuchKey/404 → `ObjectNotFoundError`, other `ClientError`/`BotoCoreError` → `ObjectStorageError`. Added `exists()` (via `head_object`) and the read-only `local_fallback_enabled` policy flag. `ObjectStorage` Protocol extended with `exists()` and `local_fallback_enabled`. |
| `src/app/common/asset_content.py` | **New.** Verified reader/publisher primitive: `AssetContentError` (+ `reason`), `read_verified_asset_bytes`, `read_verified_asset_json_object`, `publish_verified_asset`. Locked branch order — object store first, local fallback consulted **only** on a genuinely missing object, every other storage error fails immediately, and bytes are re-hashed against the DB checksum before return for both branches. |
| `src/app/api/catalogs.py` | Added `_asset_content_problem` and storage dependency on both content routes. Maps `AssetContentError.reason` → Decision 6 problem codes. Success `response_model=dict[str, object]` and route paths unchanged. |
| `src/app/documents/service.py` | Phase split: `build_artifact_payload` resolves the `TemplateVersion` row and emits a `presentation_template_ref` payload key (replacing `presentation_template`), preserving the exact `RuntimeError("validated Template version is missing")`. `render_artifact` reads bytes through the verified reader; `load_presentation_template(storage, ref)` drives the renderer check off `ref["renderer_versions"]` and keeps the presentation-only 409 boundary checks. Frozen capability signatures unchanged. |
| `src/app/config.py` | Added `pinned_asset_local_fallback: bool = True`; `reject_unsafe_production_configuration` rejects it when `app_env == "production"`. |
| `src/app/catalog_seed.py` | `seed(session, storage)` now publishes its four pinned JSON files **before** the exists-guards; `_checksum` stays pure; single terminal commit. `main()` builds `S3ObjectStorage(get_settings())`. |
| `src/app/cdisc_library_registry.py` | Publish-before-txn split: `load_and_publish_library_snapshot` publishes only per-resource real files; `register_library_snapshot_rows` does inserts only; `register_library_snapshot` kept as a thin wrapper. **No group-digest object is ever published.** |
| `src/app/standards/importer.py`, `src/app/terminology/importer.py` | Manifest/asset publish helpers (standards publishes manifest + assets; terminology publishes manifest file only). |
| `src/app/cdisc_registry.py` | Storage wiring for register-snapshot / register-manifests, plus the new `publish-assets` backfill subcommand with keyset streaming, `exists()` skip, and group-digest skip detection. |
| `tests/unit/test_asset_content.py`, `tests/unit/test_config.py`, `tests/contract/test_catalog_asset_content.py`, `tests/integration/test_asset_storage.py`, `tests/integration/test_phase1_core.py`, `tests/integration/test_phase2_documents.py` | Coverage (see §4). |
| `docs/architecture.md`, `docs/local-development.md` | Setting + CLI documentation. |

No Alembic migration and no `object_key` column were added — the object key is derived from the existing DB `checksum` via `checksum_object_key(sha256)` (Decision 1).

## 2. Group-digest HIGH finding handling

`standard_versions` / `terminology_releases` rows whose stored `checksum` is a synthetic
`_group_checksum(resources)` inventory digest have **no own publishable file object**. These
are never published:

- During registration, `load_and_publish_library_snapshot` publishes only per-resource
  real files (`manifest.resources` entries), never an object keyed by a group digest.
- In `publish-assets`, group-digest rows are detected and **skipped without error**:
  the CLI computes the actual on-disk file sha256
  (`verify_repository_asset(..., expected_sha256=None, ...)`) and compares it to the row's
  stored `checksum`. When `actual_file_sha256 != stored_checksum` the row is a group digest
  → skipped. Hand-maintained manifest paths (where actual == stored) are published normally,
  as are all `StandardAsset`/`TerminologyAsset` rows (always real file sha256).

Confirmed in the approved review (`review.md`, Decision 3/3b, HIGH) and exercised by the
25,689-row `publish-assets --dry-run` that skipped 270 group-digest rows with no error.

## 3. publish-assets usage

```
python -m app.cdisc_registry publish-assets [--batch-size N] [--dry-run] [--verify-existing] [--force]
```

- `--batch-size N` — keyset batch size (default 500; rejects `<= 0`).
- `--dry-run` — streams rows, reports present / would-upload via `exists()`, writes nothing.
- `--verify-existing` — re-reads and re-hashes already-present objects; re-publishes on corruption.
- `--force` — re-uploads unconditionally.

Streams `standard_assets` / `terminology_assets` plus the hand-maintained manifest files on
`standard_versions` / `terminology_releases` in short read-only sessions. No DB mutation.
Run after `alembic upgrade head` and `catalog_seed` (documented in `docs/local-development.md`).

## 4. Gate suites run (from `verification.md`)

| Suite | Result |
| --- | --- |
| `uv run ruff check .` | PASS — all checks passed |
| `uv run ruff format --check .` | PASS — 194 files already formatted |
| `uv run mypy src workers` | PASS — no issues in 118 source files |
| `uv run pytest tests/unit` | PASS — 53 passed |
| `uv run pytest tests/contract` | PASS — 16 passed |
| `uv run pytest tests/integration/test_asset_storage.py` | PASS — 5 passed (publish→verified read, missing→object_missing, local fallback served, tampered→checksum_mismatch, re-upload idempotent) |
| `uv run pytest tests/integration/test_phase1_core.py tests/integration/test_phase2_documents.py` | PASS — 8 passed (new `seed(session, storage)` signature; worker reads templates from object storage) |
| `python -m app.cdisc_registry publish-assets --dry-run` | PASS — streamed 25,689 rows; skipped 270 group-digest rows without error |

Storage/integration suites ran against local MinIO (`http://localhost:9000`, bucket
`clinical-artifacts`) and the default local PostgreSQL with `AURINARA_INTEGRATION=1`.

## 5. Deferred / blocked

- A full real upload of the ~25k-object corpus was not performed (heavy); upload + idempotency
  are covered by `tests/integration/test_asset_storage.py` and the `--dry-run` run.
- No gate suite was blocked by an environment constraint in the recorded run — MinIO and
  PostgreSQL were reachable locally, so all storage/integration suites executed. (Where Docker/
  MinIO is unavailable in a different environment, the storage and documents integration suites
  would be the ones blocked; unit and contract suites require neither.)

## 6. Finalization

- The approved functional work was already committed as `ff31574`; no further functional code
  changes were made.
- Task artifacts under `.agents/tasks/s3-asset-storage-master/` (plan, design, reviews, and
  this report) were committed as a `docs:` commit.
- Pre-existing unrelated working-tree changes under `frontend/` and `frontend/.agents/`
  (auth/cognito, study switcher, button styling, routing) were **left untouched and not
  committed**, consistent with `verification.md`.
- **Nothing was pushed.** `master` is ahead of its upstream only locally.
