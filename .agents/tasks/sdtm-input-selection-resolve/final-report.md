# SDTM input-selection resolve — final report

## Status: COMPLETE

Both opaque internal values the SDTM Input-selection panel previously forced users to
type by hand are now **auto-resolved from the selected Raw workbench** and shown
read-only. Neither value is unresolved:

- `validation_run_id` — resolved from the new Raw route
  `GET /api/v1/raw/{raw_id}/latest-validation-run`.
- `raw_dependency_fingerprint` — resolved from the pre-existing Raw route
  `GET /api/v1/raw/{raw_id}/dependencies` (`input_fingerprint`).

## Path taken: BACKEND-EXTENDED (plus frontend wiring)

This follows the user's instruction for option A: resolve from the aggregate / raw-context
/ dependencies response, and **fall back to resolving from the backend when a field was
not already available**.

### Evidence that drove the decision (which response fields did / didn't exist)

- `raw_dependency_fingerprint` **already existed**: `GET /raw/{raw_id}/dependencies`
  returns `input_fingerprint`, so the frontend consumes it directly — no new endpoint
  needed.
- `validation_run_id` **did not exist** on any Raw/aggregate/context/dependencies
  response. There was no list or lookup that exposed the newest succeeded Raw validation
  run's internal id. Per the "also consider resolve from backend" instruction, a new
  additive Raw route was added rather than keeping the free-text input.

### Endpoints / fields / migrations added or extended

Backend (additive only — **no persistence change, no Alembic migration**):

- New route `GET /api/v1/raw/{raw_id}/latest-validation-run` (owned by the Raw module,
  study-scoped via `_raw(...)`). Returns `RawLatestValidationRunResponse`:
  - `validation_run_id` (UUID)
  - `raw_revision` (advisory int, nullable; coerced via `_manifest_raw_revision` — bools
    and non-ints map to `None`)
  - `completed_at` (RFC 3339 UTC, nullable)
  - `input_fingerprint` (str)
  - `404 raw_validation_run_not_found` when no succeeded Raw validation run exists.
- Pure helpers `_latest_validation_run_response` / `_manifest_raw_revision`.
- Raw `ModuleDescriptor` `module_version` bumped `0.3.0 -> 0.4.0`.
- Route documented in `docs/api-contract.md`; added to `PHASE3_RAW_SDTM_OPERATIONS`.

Frontend:

- `input-selection-panel.tsx`: the two free-text inputs replaced with a read-only,
  copyable `ResolvedField` ("Resolved from <raw>"). `useGetRawDependencies` feeds
  `raw_dependency_fingerprint`; `useGetLatestValidationRun` feeds `validation_run_id`,
  gated on study scope + a chosen `raw_id`. 404/empty shows "Run and pass validation on
  this Raw workbench first". Submitted `SdtmInputSelectionWrite` body shape, aggregate
  ETag `If-Match`, 422 detail+issues, `input_refresh_required` banner, and 412 reload are
  unchanged.
- Precursor commit converted `raw_id`, `dataset_code`, and `artifact_id` to list-backed
  dropdowns.

Typed client note (carried from the approved review, out of scope here): the
`useGetLatestValidationRun` hook + helpers in `raw/raw.ts` and the
`RawLatestValidationRunResponse` model files were **hand-added** mirroring orval's
`getRawDependencies` output. Root cause is a pre-existing orval duplicate-schema blocker
from uncommitted ADaM/SDTM-Define work; `src/api/generated` was not regenerated. The
hand-added artifacts are additive and shaped to reconcile with a future regen. `api:export`
confirms the backend emits the new path.

## Commit state

- `9e5bd5b feat: auto-resolve SDTM input-selection validation run and fingerprint` (HEAD)
- `27abf7f feat: pick SDTM input-selection IDs from dropdowns`

All task-owned files (`src/app/raw/routes.py`, `src/app/raw/descriptor.py`,
`frontend/src/components/workbench/input-selection-panel.tsx`,
`frontend/src/api/generated/raw/raw.ts` + model files, `tests/unit/test_raw.py`,
`tests/integration/test_phase3_raw_sdtm.py`, `tests/contract/typed_client_fixture.py`,
`docs/api-contract.md`) are committed with no pending modifications. No new task changes
were needed — every confirmation check passed.

The remaining uncommitted working-tree changes (ADaM / Phase 4 / workbench components) are
unrelated in-flight work and were intentionally left untouched, consistent with the review
finding that ADaM edits should travel with the ADaM change.

No worktree was used; work is on `master`.

## Confirmation check output

### Frontend — `npm run typecheck` (cwd frontend) — PASS

```
> aurinara-frontend@0.1.0 typecheck
> tsc -b
(exit code 0)
```

### Frontend — `npm run lint` (cwd frontend) — PASS (0 errors)

```
> aurinara-frontend@0.1.0 lint
> eslint .
... 10 problems (0 errors, 10 warnings)
(exit code 0)
```

All 10 are pre-existing `react-refresh/only-export-components` warnings in ui/workbench
components unrelated to this task (badge.tsx, button.tsx, sidebar.tsx, acrf-panel.tsx,
alignment-banner.tsx, derivation-preview-lineage-panel.tsx, preview-panel.tsx,
staleness-banner.tsx). No errors.

### Frontend — `npm run test` (cwd frontend) — PASS

```
> aurinara-frontend@0.1.0 test
> vitest run
 Test Files  26 passed (26)
      Tests  278 passed (278)
   Duration  11.70s
(exit code 0)
```

Includes `-input-selection-specification.test.tsx` (14 tests passed), which covers the
read-only resolved fields and the no-successful-run prompt. The stderr lines are React
`forwardRef` warnings and jsdom "navigation not implemented" stubs from unrelated panels,
not failures.

### Backend (src/app changed) — touched suites, ruff, mypy — PASS

`ruff check src/app/raw/routes.py src/app/raw/descriptor.py`:

```
All checks passed!
(exit code 0)
```

`mypy src/app/raw/routes.py src/app/raw/descriptor.py`:

```
Success: no issues found in 2 source files
(exit code 0)
```

`pytest tests/unit/test_raw.py -q`:

```
...........
11 passed in 0.26s
(exit code 0)
```

`AURINARA_INTEGRATION=1 pytest tests/integration/test_phase3_raw_sdtm.py -k latest_validation_run -q`
(aurinara Postgres on :55432 and MinIO running):

```
.
1 passed, 2 deselected in 1.44s
(exit code 0)
```

`test_raw_latest_validation_run_resolution` exercises all four behaviors in one test:
newest-succeeded resolved, failed run ignored, 404 when none, and unknown-raw access 404.

`AURINARA_INTEGRATION=1 pytest tests/contract -q`:

```
..................
18 passed in 5.77s
(exit code 0)
```

### OpenAPI export — `npm run api:export` (cwd frontend) — PASS

```
> aurinara-frontend@0.1.0 api:export
> node scripts/export-openapi.mjs
Wrote .../frontend/openapi.json (169 paths, 217 schemas).
(exit code 0)
```

The exported document includes `"/api/v1/raw/{raw_id}/latest-validation-run"`. This
task's contribution to the schema is purely additive (one new GET path). The generated
typed client under `frontend/src/api/generated` was not regenerated (pre-existing orval
blocker, out of scope); the task's committed hand-added client files already cover the new
route. The export-run modification to `frontend/openapi.json` was reverted so the working
tree is not left carrying unrelated ADaM routes mixed into the committed file.

## Unresolved values

None. Both `validation_run_id` and `raw_dependency_fingerprint` resolve from the backend
for a Raw workbench with a succeeded validation run.
