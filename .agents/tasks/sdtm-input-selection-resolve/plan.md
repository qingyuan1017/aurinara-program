# Implementation Plan — SDTM Input selection: resolve `validation_run_id` and `raw_dependency_fingerprint`

## Task

Follow-up ("Option A"): stop making the user type the two opaque internal values on the SDTM
"Input selection" panel (`frontend/src/components/workbench/input-selection-panel.tsx`):

- `validation_run_id` — id of a Raw validation run.
- `raw_dependency_fingerprint` — opaque server-computed hash.

Both must be auto-resolved from the Raw workbench the user already picked in the dropdown and
shown read-only, clearly labeled "resolved from `<raw workbench>`", never a blind free-text box.
The submitted body shape (`SdtmInputSelectionWrite` via `toWriteBody`) and all existing behaviors
(ETag `If-Match`, 422 detail+issues, `input_refresh_required` banner, 412 reload, raw-context view,
add/remove artifact rows, accessibility) must be preserved.

---

## Chosen path: BACKEND-EXTENDED (then frontend wiring). NOT regen-free frontend-only.

Per the task's Step 2 rule and the user's message 3 ("if there is not aggregate / raw context /
dependencies response please also consider resolve from backend"), the path is decided by whether
BOTH values are already obtainable from existing endpoint responses. Evidence shows one is and one
is not:

### `raw_dependency_fingerprint` — ALREADY exposed (no backend change needed for it)

- The Raw dependency selection fingerprint is the exact value SDTM pins and validates as
  `raw_dependency_fingerprint`. `src/app/sdtm/routes.py:192` compares
  `context["dependency_fingerprint"] != command.raw_dependency_fingerprint`.
- `context_snapshot` sets `"dependency_fingerprint": selection.fingerprint`
  (`src/app/raw/service.py:335`), where `selection = self.get_selection(...)`.
- The same `selection.fingerprint` is returned by the existing generic dependencies endpoint
  `GET /api/v1/raw/{raw_id}/dependencies` as `DependencySelectionResponse.fingerprint`
  (`src/app/kernel/dependencies.py:66-71`, served by
  `src/app/api/clinical_aggregates.py:_get_dependencies_endpoint`). It is documented at
  `docs/api-contract.md:458`.
- The generated client already has `useGetRawDependencies` returning `.fingerprint`
  (`frontend/src/api/generated/raw/raw.ts:430`). So the fingerprint is resolvable frontend-only.

### `validation_run_id` — NOT exposed by any existing endpoint

- `POST /api/v1/raw/{raw_id}/validate` creates a `ValidationRun` and returns it, but there is NO
  GET that lists a Raw workbench's validation runs or exposes a "latest successful run". The only
  validation GET is `GET /api/v1/validation-runs/{run_id}` (`src/app/validation/routes.py:237`),
  which requires you to already know the id. There is no list endpoint
  (`src/app/validation/routes.py` has only `/validation-rules`, `/validation-rule-packs`,
  `/validation-runs/{run_id}`, `/validation-runs/{run_id}/cancel`).
- The Raw aggregate response (`AggregateResponse`, `src/app/kernel/dependencies.py:84-96`:
  `id, study_id, code, name, status, revision, document_type`) carries no validation-run reference.
- The Raw dependencies response carries no validation-run reference.
- `context_snapshot` / the SDTM `raw-context` DTO (`src/app/raw/service.py:331-338`) returns
  `schema_version, raw_id, raw_revision, dependency_selection_revision, dependency_fingerprint,
  datasets` — **no validation run**.
- Confirmed in the current UI comment: "no list-validation-runs endpoint exists in the generated
  client to back a dropdown" (`input-selection-panel.tsx`, validation-run field).

**Conclusion:** one value (fingerprint) is already available; the other (validation_run_id) is not
exposed anywhere. Therefore the correct path is the smallest additive BACKEND change to expose the
Raw workbench's latest successful validation run, owned by the Raw module, then wire both resolved
values into the frontend. The typed client is regenerated (`npm run api:sync`). No persistence
change, so no Alembic migration.

### Why extend the Raw module (not SDTM, not a reach into validation internals)

AGENTS.md: the Raw module owns Raw validation runs and the raw dependency fingerprint; expose them
through Raw's own routes/services. SDTM must consume Raw only through the existing typed boundary.
The `ValidationRun` model already stores `module_key`, `owner_type`, `owner_id`, `status`,
`completed_at` (`src/app/validation/models.py:23-32`), so Raw can resolve its own latest succeeded
run without any new persistence.

### Shape of the backend addition (additive, backward compatible)

Add ONE new read-only Raw route that returns the latest successful Raw validation run reference:

```
GET /api/v1/raw/{raw_id}/latest-validation-run
```

- Response model `RawLatestValidationRunResponse` with the fields the frontend needs to pin and
  display: `validation_run_id: UUID`, `raw_revision: int` (the `input_manifest["raw_revision"]` of
  that run, so the UI can confirm the run matches the pinned revision), `completed_at: datetime |
  None`, `input_fingerprint: str` (the run's own fingerprint — informational, NOT the dependency
  fingerprint). Keep it minimal and typed.
- Selection logic: newest `ValidationRun` where `module_key == "raw"`,
  `owner_type == "raw_workbench"`, `owner_id == raw_id`, `status == "succeeded"`, ordered by
  `completed_at` desc (tie-break by `started_at`/`id`). Study access enforced via
  `_raw(session, registry, raw_id, principal)`.
- When no successful run exists, return `404` with a typed problem
  (`code="raw_validation_run_not_found"`, detail telling the user to run and pass validation on this
  Raw workbench first). The frontend turns that 404 into the inline "Run and pass validation first"
  message. (This matches how the panel already treats the input-selection 404 as a non-blocking
  "none yet" state.)

Rationale for a new sub-resource vs. extending an existing GET: the Raw aggregate response is the
shared generic `AggregateResponse` produced by `dependency_aggregate_router` for every module
(raw/sdtm/adam/tlf); adding a Raw-only validation-run field there would leak Raw semantics into a
cross-module envelope and change every module's response — a boundary violation. The dependencies
response is likewise the generic `DependencySelectionResponse`. A dedicated Raw sub-resource is the
cleanest additive fit and mirrors the existing Raw-specific sub-resources
(`/raw/{raw_id}/datasets`, `/raw/{raw_id}/artifacts/fingerprint`). The dependency fingerprint is NOT
re-exposed here — the frontend reads it from the already-available `GET /raw/{raw_id}/dependencies`.

> verify during implementation: confirm `ValidationRun.input_manifest` always contains
> `raw_revision` for Raw runs (set in `validate_raw`, `src/app/raw/routes.py` snapshot) before
> relying on it; if a run can lack it, make `raw_revision` optional in the response.

---

## Ordered implementation items

- [ ] 1. Add the backend route + response model for the latest successful Raw validation run.
      Add `RawLatestValidationRunResponse(BaseModel)` and
      `GET /raw/{raw_id}/latest-validation-run` to `src/app/raw/routes.py`, following the existing
      Raw route conventions (uses `_raw(...)` for study-scoped access, `_not_found(...)` for the
      empty case). Query the newest succeeded `ValidationRun` for this `raw_workbench` owner, read
      `raw_revision` from `input_manifest`, and return the typed response; raise
      `_not_found("raw_validation_run_not_found", ...)` (404) when none exists. Keep the handler
      thin; no new service method is required (a single scoped `select(...).order_by(...).limit(1)`
      in the route is consistent with `validate_raw`/`list_datasets`), but if a helper reads
      cleaner, place it in `src/app/raw/service.py` (Raw owns it) — do NOT touch the validation
      module.
      Files: `src/app/raw/routes.py` (and optionally `src/app/raw/service.py`)
      Verify: `python -c "import app.main"` (import-clean, required because the OpenAPI export boots
      the app); `pytest tests/unit/test_raw.py` passes.

- [ ] 2. Add backend tests for the new route.
      In `tests/unit/test_raw.py` (follow the existing fixtures/pattern in that file), cover: (a)
      returns the newest succeeded run with correct `validation_run_id` and `raw_revision` when
      multiple runs exist (including a failed/stale run that must be ignored); (b) 404
      `raw_validation_run_not_found` when the workbench has no succeeded run; (c) study-access
      enforcement / 404 for an unknown `raw_id`.
      Files: `tests/unit/test_raw.py`
      Verify: `pytest tests/unit/test_raw.py` — new tests pass.

- [ ] 3. Document the new route in the API contract and bump the Raw module descriptor version.
      Add `GET /api/v1/raw/{raw_id}/latest-validation-run` to the Raw routes block in
      `docs/api-contract.md` (section ~`### 6.x Raw`, near the `/validate` and
      `/artifacts/fingerprint` lines around `docs/api-contract.md:475-478`) with a one-line
      description: read-only, returns the latest successful Raw validation-run reference, `404` when
      none, requires study access, persists nothing, no Idempotency-Key. Bump
      `module_version` in `src/app/raw/descriptor.py` (e.g. `0.3.0` -> `0.4.0`) since the Raw public
      surface grew (additive). Do NOT add a migration (no persistence change).
      Files: `docs/api-contract.md`, `src/app/raw/descriptor.py`
      Verify: `python -c "import app.main"` still imports clean; re-run `pytest tests/unit/test_raw.py`.

- [ ] 4. Regenerate the typed OpenAPI client.
      From `frontend/`, run the repo's own scripts (confirmed in `frontend/package.json`:
      `api:export` = `node scripts/export-openapi.mjs`, `api:generate` = `orval ...`,
      `api:sync` = both). This must produce a `useGetLatestValidationRun`-style hook under
      `frontend/src/api/generated/raw/raw.ts` and a `RawLatestValidationRunResponse` model under
      `frontend/src/api/generated/model/`. Commit the generated diff; do not hand-edit generated
      files.
      Files: `frontend/src/api/generated/**` (generated), `frontend/openapi.json` (or whatever the
      export writes — confirm from `scripts/export-openapi.mjs`)
      Verify: `cd frontend && npm run api:sync` completes; `npm run typecheck` passes; grep the
      generated raw hooks file for the new hook name to confirm it exists (confirmation only — not
      the verification of correctness, which is item 6's typecheck+tests).

- [ ] 5. Wire the two resolved fields into the InputSelectionPanel (read-only, labeled, copyable).
      In `frontend/src/components/workbench/input-selection-panel.tsx`:
      - Add two resolver queries gated on `!!studyId && !!form.raw_id`:
        `useGetRawDependencies(form.raw_id, { query: { enabled: !!form.raw_id } })` → resolved
        `raw_dependency_fingerprint = data?.fingerprint`; and the new
        `useGetLatestValidationRun(form.raw_id, { query: { enabled: !!form.raw_id } })` → resolved
        `validation_run_id` (and its `raw_revision` for a mismatch hint).
      - Replace the two free-text `<Input>` fields with read-only resolved displays (keep
        `<Label htmlFor=...>` for accessibility; render the value in a read-only input or
        `<code>` with a copy affordance, labeled e.g. "Resolved from `<raw code — name>`").
      - Resolution precedence into `form`: when a resolver returns a value for the currently
        selected `raw_id`, set `form.validation_run_id` / `form.raw_dependency_fingerprint` to it
        (so `toWriteBody` submits the resolved values unchanged). When editing a saved selection,
        keep the persisted seeded value visible until resolution completes, and never blank a
        seeded value if a resolver is still loading or errors (mirror the existing
        `selectRawAggregate`/`selectArtifact` "ignore empty, don't blank seeded" guards).
      - Empty/disabled states: before a Raw workbench is chosen, show a clear "Select a Raw
        workbench first" placeholder, not an input. If the latest-validation-run query 404s (no
        successful run) or the dependencies query returns no fingerprint, show an inline message
        ("Run and pass validation on this Raw workbench first") instead of a free-text fallback.
      - Preserve: `toWriteBody` output shape and all five submitted fields; the aggregate ETag
        `If-Match` via `ifMatch()`; the 422 `sdtm_raw_artifact_invalid`/`sdtm_raw_validation_invalid`
        detail+issues rendering; the `input_refresh_required` `StalenessBanner`; the 412 reload
        path (`handleReloadRevision`); the raw-context `RawContextView`; add/remove artifact rows;
        the "Save input selection" button; dataset/artifact dropdowns and their seeded-value guards.
      Files: `frontend/src/components/workbench/input-selection-panel.tsx`
      Verify: `cd frontend && npm run typecheck` passes (full test run is item 6).

- [ ] 6. Update the InputSelectionPanel component tests so resolved values flow into the body.
      In `frontend/src/components/workbench/-input-selection-specification.test.tsx`: extend the
      existing `vi.mock('@/api/generated/raw/raw', ...)` to also export a fake
      `useGetLatestValidationRun` (returning `{ validation_run_id: 'vr-1', raw_revision: 4 }` seeded
      from a mutable `rawApi` field) and a fake `useGetRawDependencies` (returning
      `{ fingerprint: 'raw-dep-fp', ... }`), following the existing mutable-`rawApi` convention.
      Seed them in `beforeEach` so the resolved values equal the current pinned fixtures
      (`validation_run_id='vr-1'`, `raw_dependency_fingerprint='raw-dep-fp'`). Keep the 10.1
      full-body+If-Match assertion passing (the body must still contain `validation_run_id:'vr-1'`
      and `raw_dependency_fingerprint:'raw-dep-fp'`, now sourced from the resolvers rather than
      typed), and keep 10.4 (422 detail+issues), 10.5 (`input_refresh_required` banner), and 10.6
      (412 reload) passing. Add one test asserting the no-successful-run case (latest-validation-run
      fake 404s) renders the inline "run and pass validation" message and does not render a
      free-text validation-run input.
      Files: `frontend/src/components/workbench/-input-selection-specification.test.tsx`
      Verify: `cd frontend && npm run test -- src/components/workbench/-input-selection-specification.test.tsx`
      passes; then `npm run test` and `npm run lint` for the frontend pass.

- [ ] 7. Full verification sweep.
      Backend: `python -c "import app.main"` import-clean; `pytest tests/unit/test_raw.py` and any
      contract tests touching the Raw OpenAPI (verify during implementation whether a
      `tests/contract` suite asserts the Raw route inventory and update it if so). Frontend:
      `cd frontend && npm run typecheck && npm run lint && npm run test`.
      Files: none (verification only)
      Verify: all commands above pass with no new failures.

---

## Notes / assumptions (resolve during implementation)

- `ValidationRun.input_manifest["raw_revision"]`: assumed present for Raw runs (written by
  `validate_raw`). Verify; if it can be absent, make the response `raw_revision` optional and have
  the UI treat it as advisory only.
- Exact generated hook name (`useGetLatestValidationRun` vs. an operation-id-derived name) depends
  on the `operation_id` chosen for the FastAPI route. Pick a clear `operation_id`
  (e.g. `get_raw_latest_validation_run`) and let orval derive the hook; update item 5/6 to the
  actual generated name after regen.
- The export output filename and any contract-test fixture are governed by
  `frontend/scripts/export-openapi.mjs` and `frontend/orval.config.ts`; confirm both before running
  `api:sync` and include any generated fixture/typed-client file the repo checks in.
- Do NOT fall back to a free-text box in any failure/empty state (explicit task requirement).
- No Alembic migration: this is read/resolve only; no schema change. Confirmed against the
  `ValidationRun` model (all needed columns already exist).
