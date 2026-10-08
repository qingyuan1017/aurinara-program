# Verification — SDTM Input selection: auto-resolve `validation_run_id` and `raw_dependency_fingerprint`

Path taken: **BACKEND-EXTENDED** (additive Raw route) + frontend wiring. Iteration: FIRST
(no `review.json` present at start).

## What was added / extended

### Backend (additive, backward compatible — no persistence change, no migration)

- `src/app/raw/routes.py`
  - New response model `RawLatestValidationRunResponse`
    (`validation_run_id: UUID`, `raw_revision: int | None`, `completed_at: datetime | None`,
    `input_fingerprint: str`).
  - New read-only route `GET /api/v1/raw/{raw_id}/latest-validation-run`
    (function `get_latest_validation_run`). Study-scoped via `_raw(...)`. Resolves the newest
    `ValidationRun` where `module_key == "raw"`, `owner_type == "raw_workbench"`,
    `owner_id == raw_id`, `status == "succeeded"`, ordered by `completed_at`/`started_at`/`id`
    descending. Returns `404 raw_validation_run_not_found` when none exists.
  - Pure helpers `_latest_validation_run_response` and `_manifest_raw_revision`
    (`raw_revision` read from the run's `input_manifest`; booleans/non-ints coerced to `None`).
- `src/app/raw/descriptor.py` — `module_version` bumped `0.3.0` → `0.4.0` (Raw public surface grew).
- `docs/api-contract.md` — route added to the Raw routes block + a descriptive paragraph.
- `tests/contract/typed_client_fixture.py` — route added to `PHASE3_RAW_SDTM_OPERATIONS`.
- `tests/unit/test_raw.py` — unit tests for `_manifest_raw_revision` (int/0/None/str/float/bool
  cases) and `_latest_validation_run_response` (pins run + revision; tolerates missing revision).
- `tests/integration/test_phase3_raw_sdtm.py` — `test_raw_latest_validation_run_resolution`:
  404 before any run, failed run ignored, newest succeeded run resolved (not the first), advisory
  `raw_revision` matches, unknown `raw_id` → `raw_not_found` (study access).

### Frontend

- Typed client — **HAND-ADDED, NOT produced by orval** (see root-cause note below). Diff is purely
  additive:
  - `frontend/src/api/generated/model/rawLatestValidationRunResponse.ts` (new)
  - `frontend/src/api/generated/model/rawLatestValidationRunResponseRawRevision.ts` (new)
  - `frontend/src/api/generated/model/rawLatestValidationRunResponseCompletedAt.ts` (new)
  - `frontend/src/api/generated/model/index.ts` (3 export lines added)
  - `frontend/src/api/generated/raw/raw.ts` (`useGetLatestValidationRun` +
    `getGetLatestValidationRunQueryKey` + `getGetLatestValidationRunQueryOptions` +
    `getLatestValidationRun`, mirroring the orval output pattern of `getRawDependencies`)
- `frontend/src/components/workbench/input-selection-panel.tsx`
  - Added resolver queries gated on `!!studyId && !!form.raw_id`:
    `useGetRawDependencies` → `raw_dependency_fingerprint`;
    `useGetLatestValidationRun` → `validation_run_id`.
  - Replaced the two free-text inputs with a read-only `ResolvedField` (labeled
    "Resolved from `<raw code — name>`", copyable via a `CopyButton`); 404/empty renders an inline
    prompt ("Run and pass validation on this Raw workbench first") — never a free-text fallback.
  - Resolution effects flow resolved values into `form` only when non-empty (never blank a seeded
    value); seeded persisted values stay visible until resolution replaces them.
  - Preserved: `toWriteBody` body shape + all five fields, aggregate ETag `If-Match`, 422
    `sdtm_raw_artifact_invalid`/`sdtm_raw_validation_invalid` detail+issues, `input_refresh_required`
    banner, 412 reload path, raw-context view, add/remove artifact rows, Save button, `htmlFor`.
- `frontend/src/components/workbench/-input-selection-specification.test.tsx`
  - Extended the raw mock with `useGetRawDependencies` + `useGetLatestValidationRun` fakes driven by
    a mutable `rawApi`; seeded in `beforeEach` so resolved values equal `vr-1` / `raw-dep-fp`.
  - Kept 10.1 (full body + If-Match), 10.4 (422 detail+issues), 10.5 (staleness banner), 10.6 (412
    reload) passing; added a no-successful-run test asserting the inline prompt and the absence of a
    free-text validation-run input.

## Root cause: why the typed client was hand-added (OUT OF SCOPE for this task)

`npm run api:sync` runs `api:export` (boots FastAPI, writes `frontend/openapi.json`) then `orval`.
The export succeeds, but `orval` fails with a **pre-existing** error unrelated to this change:

```
Duplicate schema names detected:
  2x ExportSpecificationParams, 2x ValidatePlan200, 2x PreviewPlan200,
  2x GetLineage200, 2x RenderDefineParams, 2x RenderDefineVersion
```

The committed `frontend/openapi.json` and `frontend/src/api/generated` are pre-existing out of sync
with the backend: the working tree has large uncommitted backend work (the whole ADaM module,
SDTM/ADaM Define, etc.) whose OpenAPI emits colliding schema/operation names that orval rejects.
`orval` runs with `clean: true`, so a failed run also wipes the entire generated tree (observed and
restored from git). This duplicate-schema blocker is **pre-existing and OUT OF SCOPE** for this task
and must be fixed separately (e.g. uniquifying those schema/operation names) before the client can
be regenerated normally. Per the parent decision (Option A), the two additive artifacts for this
route were hand-added mirroring orval's exact `getRawDependencies` pattern so a future real regen
produces an identical diff; `api:sync`/`orval --clean` was **not** re-run after the first failure.

## Commands run and results

Backend (cwd `e:\Work\EDETEK\Python\aurinara`):

- `uv run python -c "import app.main; app.main.create_app()"` → `import-clean` (import clean; the
  export boots the app).
- `uv run ruff check src/app/raw/routes.py src/app/raw/descriptor.py tests/unit/test_raw.py tests/integration/test_phase3_raw_sdtm.py tests/contract/typed_client_fixture.py`
  → `All checks passed!`
- `uv run mypy src/app/raw/routes.py` → `Success: no issues found in 1 source file`
- `uv run pytest tests/unit/test_raw.py tests/contract/test_phase3.py -q` → `12 passed`
  (the integration test in `test_phase3_raw_sdtm.py` requires `AURINARA_INTEGRATION=1` + the Compose
  PostgreSQL/MinIO services and was not run in this environment; it is gated by the module's
  `pytest.mark.skipif`).
- `npm run api:export` → `Wrote ...openapi.json (165 paths, 210 schemas)`, and the exported document
  contains `"/api/v1/raw/{raw_id}/latest-validation-run"`. `openapi.json` was then restored to the
  committed baseline (full regen blocked; see root cause).

Frontend (cwd `e:\Work\EDETEK\Python\aurinara\frontend`):

- `npm run typecheck` (`tsc -b`) → pass (exit 0).
- `npm run test -- src/components/workbench/-input-selection-specification.test.tsx` → 14 passed.
- `npm run test` (full `vitest run`) → 26 files, 278 tests passed. (The `jsdom` "navigation not
  implemented" stderr from the pre-existing download-bypass test is expected noise, not a failure.)
- `npm run lint` (`eslint .`) → 0 errors, 10 warnings; all 10 are pre-existing
  `react-refresh/only-export-components` warnings in files not touched by this change
  (`input-selection-panel.tsx` is not among them).

Generated-client diff scope (confirmed additive only):

```
 frontend/src/api/generated/model/index.ts |   3 +
 frontend/src/api/generated/raw/raw.ts     | 102 +++++++++++++++++++++
 + 3 new model files (rawLatestValidationRunResponse*.ts)
```
`frontend/openapi.json` left at the committed baseline (unchanged).

## Known limitation / follow-up

The orval duplicate-schema blocker (above) is pre-existing and out of scope. Until it is resolved in
a separate change, `npm run api:sync` cannot regenerate the client; the hand-added artifacts here are
shaped to reconcile cleanly when that first successful regen happens.
