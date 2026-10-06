# Verification — S3 pinned provider asset storage (first iteration)

Branch: `master` (no worktree). Changes committed locally; not pushed.

## Gate commands (run from repo root with `uv`)

| Command | Result |
| --- | --- |
| `uv run ruff check .` | PASS — "All checks passed!" |
| `uv run ruff format --check .` | PASS — 194 files already formatted |
| `uv run mypy src workers` | PASS — no issues found in 118 source files |
| `uv run pytest tests/unit` | PASS — 53 passed |
| `uv run pytest tests/contract` | PASS — 16 passed |

## Storage / integration suites (MinIO + PostgreSQL reachable locally)

Both services were reachable on their default local endpoints
(`http://localhost:9000` MinIO with the `clinical-artifacts` bucket, and the default
PostgreSQL URL). Ran with `AURINARA_INTEGRATION=1`.

| Command | Result |
| --- | --- |
| `uv run pytest tests/integration/test_asset_storage.py` | PASS — 5 passed (publish→verified read, missing→object_missing, local fallback served, tampered→checksum_mismatch, re-upload idempotent) |
| `uv run pytest tests/integration/test_phase1_core.py tests/integration/test_phase2_documents.py` | PASS — 8 passed (new `seed(session, storage)` signature; worker reads presentation templates from object storage) |
| `python -m app.cdisc_registry publish-assets --dry-run` | PASS — streamed 25,689 asset rows; correctly skipped 270 group-digest version/release rows with no error |

Notes:
- `publish-assets --dry-run` exercised real streaming, keyset batching, `exists()`
  probing, and the group-digest skip against the live registered CDISC Library corpus.
  A full real upload of ~25k objects was not performed (heavy); upload + idempotency are
  covered by `tests/integration/test_asset_storage.py`.

## Scope / contract checks

- No Alembic migration added (`git status -- migrations` is empty); the content key is
  derived from the existing DB `checksum` per Decision 1.
- OpenAPI `/api/v1` content routes unchanged: same paths, params, and
  `response_model=dict[str, object]`. A contract test asserts the 200 object schema is
  unchanged and asserts the new Decision 6 error codes
  (`asset_content_unpublished`, `asset_content_store_unavailable`,
  `asset_content_integrity_error`, `asset_content_contract_violation`).
- Only this task's files were staged for commit; unrelated pre-existing working-tree
  changes under `frontend/` and `frontend/.agents/` were left untouched and not committed.

## Added tests

- `tests/unit/test_asset_content.py` — reader re-verify gate (object + fallback paths),
  "never fall back on corrupt object", "never fall back on storage error", `object_missing`,
  `not_json_object`, publisher refuses upload on local mismatch, S3 `open`/`exists`
  boto3 branch mapping, group-digest skip detection, and `load_presentation_template`
  fallback behavior.
- `tests/contract/test_catalog_asset_content.py` — content-route success shape and the
  new typed error codes via FastAPI dependency overrides (no DB/MinIO required).
- `tests/integration/test_asset_storage.py` — MinIO round-trip, missing/fallback,
  tampered integrity, and re-upload idempotency.
- Updated `tests/unit/test_config.py` for the `pinned_asset_local_fallback` production
  rejection, and the `MemoryStorage` fake in `tests/integration/test_phase1_core.py`.
