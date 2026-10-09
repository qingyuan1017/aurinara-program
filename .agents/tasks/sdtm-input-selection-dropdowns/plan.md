# Implementation Plan — SDTM Input Selection dropdowns

Rework the SDTM "Pin Raw inputs" form in `input-selection-panel.tsx` so ID fields are
chosen from dropdowns populated by real backend LIST endpoints, instead of free-text
entry. **Frontend-only.** No backend, OpenAPI, or Orval-generated client change.

## Scope / files

- Modify: `frontend/src/components/workbench/input-selection-panel.tsx`
- Modify: `frontend/src/components/workbench/-input-selection-specification.test.tsx`
- Reuse (do not edit): `frontend/src/components/ui/select.tsx`, generated hooks under
  `frontend/src/api/generated/**`.

Verification command for the whole task (run from `frontend/`):
`npm run test -- -t "InputSelectionPanel"` for the targeted suite, then the full gate
`npm run typecheck && npm run lint && npm run test`.

---

## Per-field decision (evidence-based)

The submitted `SdtmInputSelectionWrite` body shape is **unchanged**; dropdowns are only
an input affordance. `toWriteBody(form)` must still emit `raw_id`, `raw_revision`
(number), `validation_run_id`, `raw_dependency_fingerprint`, and
`source_artifacts[].{dataset_code, artifact_id, checksum}`.

### 1. `raw_id` → DROPDOWN
- Backing list: `useListRawAggregates(studyId, params)` in `api/generated/raw/raw.ts`.
  Returns `AggregateCollection = { items: AggregateResponse[]; next_cursor? }`
  (`model/aggregateCollection.ts`).
- `AggregateResponse` (`model/aggregateResponse.ts`) has `id`, `code`, `name`, `status`,
  `revision`. Show the human label `code — name` (matching `study-switcher.tsx`), submit
  `aggregate.id` as `raw_id`.
- Gate on `enabled: !!currentStudyId`. `currentStudyId` comes from `useCurrentStudy()`
  (`components/study-provider.tsx`). Note: `useWorkbench()` also exposes `studyId`
  (`workbench-context.tsx`); prefer that since the panel is always inside a
  `WorkbenchDetailShell` and it always equals the selected study. Use `studyId` from
  `useWorkbench()` as the study scope and gate on `!!studyId`.

### 2. `raw_revision` → AUTO-FILLED (not a free dropdown, no longer free-text when a workbench is chosen)
- `AggregateResponse.revision: number` exists, so when a raw workbench is selected,
  auto-fill `raw_revision` from the selected aggregate's `revision`.
- Keep it editable: still render it (as a number input or read-only display) so a user
  can pin an older revision and so a seeded saved value that differs from the current
  aggregate revision is preserved. Simplest correct choice: when the user picks a raw
  workbench from the dropdown, set `raw_revision` to that aggregate's `revision`; leave
  the numeric input present so it round-trips the seeded value otherwise. Record this as
  the decision.

### 3. `validation_run_id` → STAYS TEXT (no list endpoint exists)
- Evidence: grep of `api/generated/**` finds **no** list-validation-runs hook
  (`useListValidation* / listValidationRuns / ValidationRunCollection` → no matches).
  Only `useGetValidationRun(runId)` (`api/generated/validation/validation.ts`, GET by id)
  and `useValidateRaw(rawId)` (`api/generated/raw/raw.ts`, POST create) exist.
- Decision: keep `validation_run_id` as the existing free-text `Input`. There is no way
  to enumerate validation runs for a raw workbench, so it CANNOT be a list-backed
  dropdown. Do not invent a client-side list or fake endpoint.
- Optional (do NOT block save on it): keep as plain text. A read-validation to confirm
  the id resolves via `useGetValidationRun` is explicitly out of scope for this change to
  avoid new failure modes; leave a short code comment noting the absence of a list
  endpoint.

### 4. `raw_dependency_fingerprint` → STAYS TEXT
- It is an opaque server-computed string. `useGetRawContext(sdtmId)` returns
  `GetRawContext200 = { [key: string]: unknown }` (`model/getRawContext200.ts`) — an
  untyped dictionary, so there is no type-safe key to auto-fill from. The raw aggregate
  response has no fingerprint field either.
- Decision: keep it as the existing free-text `Input`. Add a short comment explaining the
  value is opaque/server-computed with no list or typed source to populate from.

### 5. `source_artifacts[].dataset_code` → DROPDOWN (per row, gated on a chosen raw workbench)
- Backing list: `useListDatasets(rawId)` in `api/generated/raw/raw.ts`. Returns a plain
  array `RawDatasetResponse[]` (`model/rawDatasetResponse.ts`), each with `code`, `label`,
  `id`, `revision`, `current_source_file_id`.
- Show label `code — label`, submit `code`. Gate on `enabled: !!form.raw_id` (datasets
  require a selected raw workbench). Render a disabled/empty state until a raw workbench
  is chosen.

### 6. `source_artifacts[].artifact_id` → DROPDOWN, with `checksum` AUTO-FILLED
- Backing list: `useListSourceFiles(studyId, params)` in
  `api/generated/artifacts/artifacts.ts`. Returns `SourceFileCollection = { items:
  SourceFileResponse[]; next_cursor? }`. `SourceFileResponse` (`model/sourceFileResponse.ts`)
  has `artifact_id`, `filename`, `sha256`, `size`, `id`.
- Show label `filename` (optionally with a short sha prefix), submit `artifact_id`, and
  **auto-fill `checksum` from `sha256`** when an artifact is picked. This satisfies the
  `SelectedRawArtifact.checksum` `^[0-9a-f]{64}$` pattern from a real value.
- Why source files, not `useListArtifacts`: `ListArtifactsParams` and `ListSourceFilesParams`
  both only support `{ limit, after }` (no owner/type/raw filter). `ArtifactResponse` is
  generic build-artifact metadata; `SourceFileResponse` directly pairs `artifact_id` with
  `sha256` and `filename`, which is exactly what the row needs (id + checksum auto-fill).
  Decision: use `useListSourceFiles(studyId)` for the Artifact ID dropdown. Gate on
  `enabled: !!studyId`.
- Keep the `checksum` field visible but read-only/derived (it is filled from the chosen
  artifact). It must still submit through `toWriteBody` unchanged.

### Pagination note
These list endpoints are cursor-paginated (`{ limit, after }`). For a dropdown, fetch a
single first page with a high `limit` (e.g. `{ limit: 200 }`, the schema max), mirroring
how `study-switcher.tsx` consumes the full `useListStudies` result. Do not build infinite
scroll into the dropdown for this change. Record this as a deliberate simplification.

### Seeded-value preservation (retired/absent option)
When the form is seeded from an existing saved selection (`formFromSelection`) whose
`raw_id`, `dataset_code`, or `artifact_id` is not present in the freshly loaded options
(e.g. a retired workbench), the dropdown MUST still show/retain the saved value. Implement
by: if the current form value is non-empty and not found among loaded items, inject a
synthetic `SelectItem` for that value (label it with the raw id/code plus a hint like
"(not in current list)") so Radix `Select` renders the saved selection rather than
blanking it. Never silently drop a seeded value.

---

## Ordered implementation steps

- [ ] 1. Add the Select primitive imports and the three list-query hooks to the panel.
      Import `Select, SelectContent, SelectItem, SelectTrigger, SelectValue` from
      `@/components/ui/select`; import `useListRawAggregates, useListDatasets` from
      `@/api/generated/raw/raw` and `useListSourceFiles` from
      `@/api/generated/artifacts/artifacts`. Read `studyId` from the existing
      `useWorkbench()` call. Wire the queries:
      `useListRawAggregates(studyId, { limit: 200 }, { query: { enabled: !!studyId } })`,
      `useListSourceFiles(studyId, { limit: 200 }, { query: { enabled: !!studyId } })`, and
      `useListDatasets(form.raw_id, { query: { enabled: !!form.raw_id } })`.
      Files: `frontend/src/components/workbench/input-selection-panel.tsx`
      Verify: `cd frontend && npm run typecheck` — compiles with no new errors.

- [ ] 2. Replace the `raw_id` free-text Input with a Select over the raw-aggregate items,
      and auto-fill `raw_revision` on selection. On change, set `raw_id` to the chosen
      `aggregate.id` and set `raw_revision` to `String(aggregate.revision)` in the same
      `setForm` update. Keep the `Label htmlFor="is-raw-id"` association (point it at the
      `SelectTrigger id`). Keep the `raw_revision` numeric input rendered (now typically
      auto-filled, still editable) so a seeded value round-trips. Preserve the seeded value
      if the selected `raw_id` is absent from loaded items (inject a synthetic SelectItem).
      Files: `frontend/src/components/workbench/input-selection-panel.tsx`
      Verify: `cd frontend && npm run test -- -t "save sends the full pinned body"` — the
      10.1 save test still asserts the exact body incl. `raw_id: 'raw-1'`,
      `raw_revision: 4`.

- [ ] 3. Convert each source-artifact row's `dataset_code` to a Select over
      `useListDatasets(form.raw_id)` items (label `code — label`, value `code`), gated/
      disabled until a raw workbench is selected; and convert `artifact_id` to a Select over
      `useListSourceFiles` items (label `filename`, value `artifact_id`) that also auto-fills
      that row's `checksum` from the chosen source file's `sha256`. Make `checksum`
      read-only/derived. Preserve per-row seeded values not present in the loaded lists via
      synthetic SelectItems. Keep every `Label htmlFor` association, the `required`
      semantics, and the add/remove artifact buttons (incl. the `aria-label="Remove source
      artifact N"` and the `disabled` when only one row) working unchanged.
      Files: `frontend/src/components/workbench/input-selection-panel.tsx`
      Verify: `cd frontend && npm run test -- -t "InputSelectionPanel"` — all four
      InputSelectionPanel tests still pass once the test fakes from step 6 are in place.

- [ ] 4. Leave `validation_run_id` and `raw_dependency_fingerprint` as free-text Inputs,
      each with a brief explanatory comment (no list endpoint / opaque server value). Do not
      add new queries for them.
      Files: `frontend/src/components/workbench/input-selection-panel.tsx`
      Verify: `cd frontend && npm run lint` — no unused-import/var warnings introduced.

- [ ] 5. Keep `toWriteBody`, `formFromSelection`, the submit flow, the 422
      (`sdtm_raw_artifact_invalid` / `sdtm_raw_validation_invalid`) detail+issues rendering,
      the `input_refresh_required` `StalenessBanner`, the 412 concurrency banner +
      `handleReloadRevision`, the `RawContextView`, and the `invalidateSdtmSubResource`
      onSuccess wiring exactly as they are. Confirm the submitted body still trims and casts
      identically (dropdown values are plain strings; `raw_revision` still `Number(...)`).
      Files: `frontend/src/components/workbench/input-selection-panel.tsx`
      Verify: `cd frontend && npm run test -- -t "InputSelectionPanel"` — the 10.4/10.5/10.6
      behaviors remain green.

- [ ] 6. Update the test file to provide fakes for the newly-used list hooks, following the
      existing `vi.mock` convention. The file already `vi.mock`s `@/api/generated/sdtm/sdtm`;
      add two more module mocks (place them before the panel imports, like the existing one):
      (a) `vi.mock('@/api/generated/raw/raw', ...)` exporting `useListRawAggregates(studyId,
      params, options)` → `{ data: { items: [...] }, isLoading:false, ... }` and
      `useListDatasets(rawId, options)` → `{ data: [...] }`, driven by a mutable `rawApi`
      object seeded in `beforeEach`; (b) `vi.mock('@/api/generated/artifacts/artifacts', ...)`
      exporting `useListSourceFiles(studyId, params, options)` → `{ data: { items: [...] } }`.
      Seed fakes so the existing `makeSelection()` values are present as options:
      a raw aggregate `{ id: 'raw-1', code: 'RAW1', name: 'Raw one', revision: 4, status:
      'draft' }`; a dataset `{ id, raw_id:'raw-1', code: 'DM', label: 'Demographics',
      revision:1, current_source_file_id:'sf-1' }`; a source file `{ id:'sf-1',
      artifact_id: 'art-dm', sha256: 'sha-dm', filename: 'dm.xpt', size: 1 }`. This keeps the
      seeded form submitting `raw_id:'raw-1'`, `raw_revision:4`, `dataset_code:'DM'`,
      `artifact_id:'art-dm'`, `checksum:'sha-dm'` so the 10.1 body assertion is unchanged.
      Files: `frontend/src/components/workbench/-input-selection-specification.test.tsx`
      Verify: `cd frontend && npm run test -- -t "InputSelectionPanel"` — all pass.

- [ ] 7. Add a focused regression test (or extend the 10.1 test) asserting the dropdown
      affordance and seeded-value preservation: with the fakes from step 6, assert the raw
      workbench, dataset, and artifact triggers render the seeded human labels (e.g. a
      `combobox`/trigger showing `RAW1 — Raw one`, `DM — Demographics`), and that submitting
      the seeded form still produces the exact pinned body + aggregate ETag If-Match
      (`ifMatchRequest(AGGREGATE_REVISION)`), i.e. the dropdowns did not alter the body shape.
      Also add a case where the seeded `raw_id` is NOT in the loaded aggregate list and
      assert the trigger still shows the saved value (synthetic item), then save still emits
      `raw_id` unchanged.
      Files: `frontend/src/components/workbench/-input-selection-specification.test.tsx`
      Verify: `cd frontend && npm run test -- -t "InputSelectionPanel"` — new assertions pass.
      Note: Radix `Select` under jsdom renders the trigger's current value text without
      opening the listbox; assert on the trigger/`SelectValue` text and on the submitted body
      rather than driving a full open/click, consistent with how `installJsdomHarness()` is
      used in this suite. If opening the listbox proves necessary, follow the harness pattern
      already present (the file installs `installJsdomHarness()` in `beforeAll`).

- [ ] 8. Preserve the SpecificationPanel tests in the same file (they share the SDTM mock).
      Do not change the `@/api/generated/sdtm/sdtm` mock's spec exports; only add the two new
      module mocks. Confirm the whole file passes.
      Files: `frontend/src/components/workbench/-input-selection-specification.test.tsx`
      Verify: `cd frontend && npm run test -- src/components/workbench/-input-selection-specification.test.tsx`
      — every test in the file passes.

- [ ] 9. Final gate.
      Files: (none)
      Verify: from `frontend/`, run `npm run typecheck && npm run lint && npm run test` — all
      green. Build is not required for this change but may be run as
      `npm run build` if a fuller check is wanted.

---

## Preserved assertions (must stay green)

- Save sends the full pinned body + the aggregate ETag as `If-Match`
  (`ifMatchRequest(AGGREGATE_REVISION)`), body = `{ raw_id, raw_revision, validation_run_id,
  raw_dependency_fingerprint, source_artifacts: [{ dataset_code, artifact_id, checksum }] }`
  (Req 10.1).
- 422 `sdtm_raw_artifact_invalid` / `sdtm_raw_validation_invalid` renders the problem
  `detail` + the `issues[]` list (Req 10.4).
- `input_refresh_required` selection state renders the `StalenessBanner` ("input selection
  needs a refresh") (Req 10.5).
- 412 shows the concurrency message with a "Reload current revision" action that
  invalidates `getGetSdtmAggregateQueryKey(sdtmId)` (Req 10.6).
- "Save input selection" button label and the add/remove artifact controls keep working.
- Each dropdown has an associated `Label` (htmlFor → trigger id) for accessibility.

## Assumptions / limitations recorded

- `validation_run_id` stays free-text: no list endpoint exists in the generated client.
- `raw_dependency_fingerprint` stays free-text: opaque server value, no typed/list source
  (`GetRawContext200` is `{ [key: string]: unknown }`).
- Dropdowns load a single first page (`limit: 200`); no in-dropdown pagination, matching
  `study-switcher`.
- `raw_revision` auto-fills from the selected aggregate's `revision` but remains editable to
  preserve seeded values and allow pinning a specific revision.
- Study scope uses `useWorkbench().studyId` (always equals the selected study for a panel
  inside `WorkbenchDetailShell`); queries gate on `!!studyId`, and per-row dataset queries
  additionally gate on `!!form.raw_id`.
