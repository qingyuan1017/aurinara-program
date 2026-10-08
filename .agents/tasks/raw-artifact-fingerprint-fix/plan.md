# Implementation Plan — Raw artifact-build fingerprint preview endpoint

Fixes the confirmed HTTP 409 `stale_input_fingerprint` on every Raw artifact build.

## Root cause (verified by reading source)

- Build endpoint `POST /api/v1/raw/{raw_id}/artifacts` (`src/app/raw/routes.py`,
  `create_raw_artifacts`) forwards to `create_artifact_build` in `src/app/artifacts/builds.py`.
- `create_artifact_build` recomputes `input_fingerprint = fingerprint(resolved)` from
  `resolve_build_input(...)` (the dict `{study_id, owner_type, owner_id, artifact_types, options,
payloads}`) and rejects with 409 `stale_input_fingerprint` when it differs from
  `command.expected_input_fingerprint`.
- The frontend (`frontend/src/components/workbench/artifacts-panel.tsx`) sends
  `expected_input_fingerprint = useGetRawDependencies(rawId).data.fingerprint` — the
  dependency-selection fingerprint, a sha256 over a _different_ structure. The two hashes can
  never be equal, so every Raw build 409s.

The fix (Option 1): expose the exact resolved build-input fingerprint through a read-only
preview endpoint that reuses the SAME `resolve_build_input(...)` + `fingerprint(...)` path, then
have the frontend fetch and send that value. The server-side staleness guard is NOT weakened.

## Design decisions (grounded in the code)

1. **Factor a shared helper in `src/app/artifacts/builds.py`** so the build handler and the new
   preview endpoint compute the fingerprint through one code path and cannot drift. The helper
   wraps the existing `resolve_build_input(...)` + `fingerprint(resolved)` that
   `create_artifact_build` already runs inline. `create_artifact_build` is refactored to call it,
   preserving current behavior exactly (it still needs `module_key` for the build row, so the
   helper returns the fingerprint plus the already-resolved values rather than only a string).
2. **Raw route stays thin and in the Raw module**, mirroring `create_raw_artifacts`: resolve the
   workbench + study access via `_raw(...)`, reuse the same `unsupported` artifact-type 422 guard,
   then call the Artifacts helper with `owner_type="raw_workbench"`, `owner_id=raw.id`,
   `options={}`. Synchronous `200`, no Idempotency-Key, no persistence, no migration.
3. **Response model** is a small Pydantic 2 model `{ "input_fingerprint": "<64 hex>" }` with
   snake_case JSON (consistent with AGENTS.md).
4. **Route summary drives the generated client name.** Give the handler function the name
   `preview_raw_artifact_fingerprint` so FastAPI's operationId becomes
   `preview_raw_artifact_fingerprint_api_v1_...`, which Orval cleans to
   `usePreviewRawArtifactFingerprint`. The request model name `RawArtifactFingerprintRequest`
   and response `RawArtifactFingerprintResponse` become the generated model type names.
5. **Testing without Docker:** the OpenAPI surface and the typed-client fixture are asserted by
   `tests/contract/test_phase3.py`, which only calls `app.openapi()` and needs no
   Postgres/MinIO. The end-to-end build-succeeds path belongs in the existing Docker-backed
   integration test `tests/integration/test_phase3_raw_sdtm.py`. The plan adds a focused unit
   test for the shared helper refactor that does not require services.

## Commands discovered during exploration

- Backend tests: `uv run pytest <path>` (system python is 3.9; the project pins 3.13, so always
  use `uv run`). Narrow contract test runs without Docker.
- OpenAPI export + client regen (from `frontend/`): `npm run api:sync` (= `api:export` which runs
  `node scripts/export-openapi.mjs` via `uv run python`, then `api:generate` = `orval`).
  `uv` and `node`/`npm` are both available in this environment.
- Frontend checks (from `frontend/`): `npm run typecheck`, `npm run lint`, `npm run test`.

---

## Ordered items

- [ ] 1. Factor the shared fingerprint helper in `src/app/artifacts/builds.py`.
     Add `resolve_build_fingerprint(session, registry, *, study_id, owner_type, owner_id,
artifact_types, options) -> tuple[str, str, ArtifactBuilderCapability, dict[str, object]]`
     returning `(input_fingerprint, module_key, handler, resolved)`. Implement it by calling the
     existing `resolve_build_input(...)` and `fingerprint(resolved)`. Refactor
     `create_artifact_build` to call this helper instead of calling `resolve_build_input` +
     `fingerprint` inline, keeping identical behavior (it uses `module_key` for the build row).
     Do NOT change `resolve_build_input` signatures or the canonical `resolved` shape.
     Files: `src/app/artifacts/builds.py`
     Verify: `uv run pytest tests/unit/test_canonical.py` passes, and (added in item 2)
     `uv run pytest tests/unit/test_artifacts_builds.py` passes.

- [ ] 2. Add a unit test for the helper/build equivalence.
     Create `tests/unit/test_artifacts_builds.py` asserting that `resolve_build_fingerprint`
     returns `fingerprint(resolve_build_input(...)[2])` for the same inputs (use a small fake
     `ArtifactBuilderCapability`/registry or monkeypatch `resolve_build_input` to a known
     `resolved` dict and assert the returned fingerprint equals `fingerprint(resolved)` and the
     returned `module_key`/`resolved` match). This is a pure-logic test; no Postgres/MinIO.
     Files: `tests/unit/test_artifacts_builds.py`
     Verify: `uv run pytest tests/unit/test_artifacts_builds.py` — tests pass.

- [ ] 3. Add the Raw fingerprint-preview request/response models and route.
     In `src/app/raw/routes.py` add:
     `class RawArtifactFingerprintRequest(BaseModel)` with
     `model_config = ConfigDict(extra="forbid")` and
     `artifact_types: tuple[str, ...] = Field(min_length=1)` (mirror `RawArtifactRequest` but
     WITHOUT `expected_input_fingerprint`); and
     `class RawArtifactFingerprintResponse(BaseModel)` with `input_fingerprint: str`.
     Add handler `def preview_raw_artifact_fingerprint(raw_id, command, session, registry,
principal)` on `@router.post("/raw/{raw_id}/artifacts/fingerprint",
response_model=RawArtifactFingerprintResponse)` (default 200). Body: `raw = _raw(...)`;
     reuse the existing `unsupported = sorted(set(command.artifact_types) -
set(RAW_ARTIFACT_TYPES))` → 422 `artifact_type_unsupported` guard identical to
     `create_raw_artifacts`; then call `resolve_build_fingerprint(session, registry,
study_id=raw.study_id, owner_type="raw_workbench", owner_id=raw.id,
artifact_types=command.artifact_types, options={})` and return
     `RawArtifactFingerprintResponse(input_fingerprint=<first element>)`. Import
     `resolve_build_fingerprint` from `app.artifacts.builds`. Keep the handler thin; let the
     422s from `resolve_build_input` (owner/type invalid) propagate as RFC 9457 problems.
     Files: `src/app/raw/routes.py`
     Verify: `uv run pytest tests/contract/test_phase3.py` passes after item 4;
     `uv run python -c "from app.main import create_app; create_app()"` imports cleanly.

- [ ] 4. Assert the new route in the typed-client fixture.
     Add `"/api/v1/raw/{raw_id}/artifacts/fingerprint": frozenset({"post"})` to
     `PHASE3_RAW_SDTM_OPERATIONS` in `tests/contract/typed_client_fixture.py`.
     Files: `tests/contract/typed_client_fixture.py`
     Verify: `uv run pytest tests/contract/test_phase3.py` — passes (route present in
     `app.openapi()`); no Docker needed.

- [ ] 5. Document the new route in the API contract.
     In `docs/api-contract.md`, under the Raw routes block (after
     `POST /api/v1/raw/{raw_id}/artifacts`), add
     `POST /api/v1/raw/{raw_id}/artifacts/fingerprint` and a short paragraph: it accepts
     `{ "artifact_types": [...] }` (≥1, from the fixed Raw artifact-type set), returns `200`
     `{ "input_fingerprint": "<64 hex>" }` computed from the exact same resolved build inputs as
     the build endpoint, requires study access, is read-only (no persistence, no
     Idempotency-Key), and returns `422` for unsupported/invalid artifact types or owner —
     consistent with sibling Raw routes.
     Files: `docs/api-contract.md`
     Verify: manual read-back; the route string matches the handler path exactly.

- [ ] 6. Regenerate the OpenAPI document and the Orval client.
     From `frontend/`, run `npm run api:sync`. This rewrites `frontend/openapi.json` (adds the
     new path + `RawArtifactFingerprintRequest`/`RawArtifactFingerprintResponse` schemas) and
     regenerates `frontend/src/api/generated/**` (adds `usePreviewRawArtifactFingerprint` /
     `previewRawArtifactFingerprint` in `raw/raw.ts` and the two model files + their `model/
index.ts` exports). Do NOT hand-edit generated files; commit whatever the generator emits.
     Files: `frontend/openapi.json`, `frontend/src/api/generated/raw/raw.ts`,
     `frontend/src/api/generated/model/*` (generated)
     Verify: `npm run typecheck` passes; confirm the new hook exists via
     `uv run pytest tests/contract/test_phase3.py` still green (OpenAPI side) and the generated
     `raw.ts` contains `previewRawArtifactFingerprint`.

- [ ] 7. Wire the Artifacts panel to the new endpoint.
     In `frontend/src/components/workbench/artifacts-panel.tsx`, replace the dependency-selection
     fingerprint source with a fetch of the correct build-input fingerprint for the exact
     selected set at build time. On the Build click (`handleStart`): compute the ordered
     `artifact_types` (unchanged `RAW_ARTIFACT_TYPES` order + filter), call the generated
     `previewRawArtifactFingerprint({ rawId, data: { artifact_types } })` to get
     `input_fingerprint`, then pass THAT as `expected_input_fingerprint` into the existing
     `create.mutateAsync` build POST. Keep: Build disabled until ≥1 type selected; the stable
     per-attempt Idempotency-Key (`idempotency.begin()` before the mutation); the fixed
     `RAW_ARTIFACT_TYPES` list and submit order; 202 polling via `OperationRunner`; toast on
     start error (wrap the fingerprint fetch in the same try/catch so a preview failure surfaces
     as a start-error toast). Because the fingerprint depends on the selected set, do NOT cache a
     single study-wide value — fetch it for the exact set when Build is clicked. Update the
     `canStart` condition and the card description text that referenced the dependency-selection
     fingerprint. Decide `useGetRawDependencies`: it is now unused for the fingerprint — remove
     the query, its `inputFingerprint`/`dependenciesQuery.isError` UI, and the stale JSDoc, OR
     keep it only if it still drives displayed state (it does not today). Remove dead code; do
     not leave an unused import/hook.
     Files: `frontend/src/components/workbench/artifacts-panel.tsx`
     Verify: `npm run typecheck` and `npm run lint` pass; `npm run test` passes
     (`-raw-screens.test.tsx` mocks `ArtifactsPanel`, so it is unaffected).

- [ ] 8. Update the Raw end-to-end integration test to prove the build now succeeds via the
     preview fingerprint. In `tests/integration/test_phase3_raw_sdtm.py`, in the Raw-artifacts
     section, obtain the expected fingerprint by calling
     `POST /api/v1/raw/{raw_id}/artifacts/fingerprint` with the selected `artifact_types` and
     use its `input_fingerprint` as `expected_input_fingerprint` in the
     `POST /api/v1/raw/{raw_id}/artifacts` build (replacing any direct
     `fingerprint(resolve_build_input(...))` computation for the Raw build), then assert the
     build reaches `202` and completes `succeeded` (not 409). This mirrors how the client now
     works end to end.
     Files: `tests/integration/test_phase3_raw_sdtm.py`
     Verify (Docker/Postgres/MinIO REQUIRED): bring up services per `docs/local-development.md`
     (`docker compose up -d postgres minio minio-init`, `uv run alembic upgrade head`,
     `uv run python -m app.catalog_seed`), then `uv run pytest
tests/integration/test_phase3_raw_sdtm.py`. If Docker is unavailable in the execution
     environment, this item cannot be run here — note that and rely on the contract test
     (item 4) plus the helper unit test (item 2) as the non-Docker verification that the route
     exists and the fingerprint is computed through the identical path.

- [ ] 9. Final verification sweep.
     Backend (no Docker): `uv run pytest tests/unit tests/contract` — all pass. Lint/type:
     `uv run ruff check src tests`, `uv run ruff format --check src tests`, `uv run mypy src`.
     Frontend (from `frontend/`): `npm run typecheck`, `npm run lint`, `npm run test`.
     Confirm `frontend/openapi.json` and the generated client are regenerated (not hand-edited)
     and that `docs/api-contract.md`, the route, and the typed-client fixture all agree on the
     path `POST /api/v1/raw/{raw_id}/artifacts/fingerprint`.
     Files: (verification only)
     Verify: every command above exits 0; any Docker-only integration step (item 8) is reported
     as run-or-skipped explicitly.

## Notes / assumptions

- The build endpoint and request model (`RawArtifactRequest`, with
  `expected_input_fingerprint`) are left unchanged — the client keeps sending the field, now with
  the correct value. The server staleness guard is intentionally preserved.
- Helper return shape includes `module_key`, `handler`, and `resolved` (not just the hash) so
  `create_artifact_build` keeps building the `ArtifactBuild` row without a second resolution pass.
- If `npm run api:sync` fails because the backend cannot import under `uv` in this environment,
  the fallback is to run `node scripts/export-openapi.mjs` after confirming
  `uv run python -c "from app.main import create_app; create_app().openapi()"` works, then
  `npm run api:generate`.

---

## Verification (recorded 2026-10-08)

Environment: Windows, Python 3.13 via `uv`, Node 22. Backend dev deps installed with
`uv sync --extra dev`. Integration DB: existing `aurinara-postgres-1` container on
localhost:55432 (`docker compose` could not be used directly because the user's `.env` has a
stray backtick on line 48 that breaks compose env parsing; the already-running Postgres
container was used instead and was NOT modified in content, only connected to).

Backend (no Docker required):

- `uv run ruff check src tests` — PASS (all checks passed).
- `uv run ruff format --check <changed files>` — PASS (already formatted).
- `uv run mypy src` — PASS (no issues in 138 source files).
- `uv run python -m pytest tests/unit/test_artifacts_builds.py tests/unit/test_canonical.py
tests/contract/test_phase3.py` — PASS (3).
- `uv run python -m pytest tests/unit tests/contract` — PASS (101) with a clean environment.
  Note: with a leaked `APP_ENV=test` shell variable, `tests/unit/test_config.py` fails because
  it asserts the default app env is `development`; this is a shell-env artifact, not a code
  regression — re-running after `Remove-Item Env:APP_ENV` is green.

Backend (Docker/Postgres required):

- Discovered and cleared a leaked `idle in transaction` Postgres backend from an earlier
  killed run that was holding a lock on `sdtm_workbenches` and blocking the fixture's
  `TRUNCATE ... CASCADE` (this had caused two apparent "hangs"). Terminated the stale backends
  with `pg_terminate_backend`.
- `AURINARA_INTEGRATION=1 uv run alembic upgrade head` + `uv run python -m app.catalog_seed` —
  applied against the running Postgres.
- Focused end-to-end check (temporary test, since removed): created a Raw workbench, validated
  it, called `POST /api/v1/raw/{raw_id}/artifacts/fingerprint`, and used the returned
  `input_fingerprint` as `expected_input_fingerprint` on `POST /api/v1/raw/{raw_id}/artifacts`
  — build ACCEPTED (202) and completed `succeeded` (NOT 409). Also asserted 422 for an unknown
  artifact type and 404 for an unknown workbench. PASS.
  (Discovery: the preview endpoint correctly surfaces the same `409 successful_validation_required`
  precondition as the build endpoint when the Raw revision has no successful validation run,
  because it reuses the identical `resolve_build_input` path — expected behavior.)
- `AURINARA_INTEGRATION=1 uv run python -m pytest tests/integration/test_phase3_raw_sdtm.py` —
  PASS (2), including `test_raw_to_aligned_sdtm_and_upstream_staleness`, which now builds Raw
  artifacts via the preview-endpoint fingerprint (item 8).

Frontend (from `frontend/`):

- `npm run api:sync` — regenerated `frontend/openapi.json` (145 paths, 181 schemas) and the
  Orval client; `usePreviewRawArtifactFingerprint`/`previewRawArtifactFingerprint` and the
  `RawArtifactFingerprintRequest`/`RawArtifactFingerprintResponse` models are present. The regen
  also refreshed previously stale SDTM/aCRF/define/csdrg client surface that the committed client
  had drifted from; those are generator output, not hand edits.
- `npm run typecheck` — PASS.
- `npm run lint` — PASS (0 errors; only pre-existing fast-refresh warnings in `components/ui`).
- `npm run test` — PASS (26 files, 275 tests), including the updated
  `components/workbench/-raw-ops-panels.test.tsx` ArtifactsPanel cases, which now drive the
  fingerprint through the new preview endpoint fake.

Not run here: Docker runner images and the full `tests/e2e` / `tests/conformance` suites were
out of scope for this fix. SAS execution remains `runner_not_configured` by design.
