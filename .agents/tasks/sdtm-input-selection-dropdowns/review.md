# SDTM input-selection: free-text IDs replaced with list-backed dropdowns

The SDTM "Pin Raw inputs" form now sources its ID fields from dropdowns backed by real generated LIST hooks instead of free-text entry. `raw_id` comes from `useListRawAggregates` (and auto-fills `raw_revision` from the chosen aggregate's current revision), each source-artifact row's `dataset_code` comes from `useListDatasets(raw_id)`, and `artifact_id` comes from `useListSourceFiles` (auto-filling that row's `checksum` from the file's `sha256`). `validation_run_id` and `raw_dependency_fingerprint` stay free-text because no list endpoint / typed source exists for them. The submitted `SdtmInputSelectionWrite` body and the aggregate-ETag `If-Match` are unchanged, and the 422/412/staleness/raw-context/add-remove behavior is preserved. The change is scoped to two files: the panel and its test; no backend, OpenAPI, or generated-client edits.

Watch for: nothing blocking. One minor accessibility note on the read-only checksum input (possible) and a cosmetic point on the "(not in current list)" synthetic item (confirmed, by design). Both are non-blocking.

**Verdict**: APPROVED

## High-level view

Only two files changed, both new in commit `27abf7f`: `input-selection-panel.tsx` and `-input-selection-specification.test.tsx`. Verified that the generated client under `src/api/generated` has no working-tree changes and the commit touched no backend/OpenAPI assets, so the "frontend-only, no fabricated endpoints" constraint holds.

The three dropdowns are each backed by a hook that genuinely exists in the generated client with the fields the panel reads (`AggregateResponse.{id,code,name,revision}`, `RawDatasetResponse.{id,code,label}`, `SourceFileResponse.{id,artifact_id,filename,sha256}`). The two fields left as text — `validation_run_id` and `raw_dependency_fingerprint` — have no list hook in the generated client (confirmed: no `useListValidation*`/`ValidationRunCollection`), so leaving them free-text is the correct call rather than a gap.

The body contract is untouched: `toWriteBody` still trims each string, casts `raw_revision` with `Number(...)`, and emits the same five keys plus `source_artifacts[].{dataset_code,artifact_id,checksum}`. Dropdowns only change how values enter the form state. The mutation is still wired with `request: ifMatch()`, so the aggregate ETag rides as `If-Match` on every save.

Query gating matches the plan: raw-aggregate and source-file lists gate on `enabled: !!studyId`, datasets gate on `enabled: !!form.raw_id`. Disabled/placeholder states are present (the dataset select is disabled until a Raw workbench is chosen).

Seeded-value preservation is handled on all three dropdowns via a synthetic `SelectItem` when the saved value is absent from the loaded options, plus an empty-value guard in the `onValueChange` handlers so Radix reconciliation never blanks a seeded id. Each dropdown has a `Label` associated to its trigger id, and the add/remove row controls and Save button label are intact.

Tests drive the dropdowns through faithful hook fakes and keep the required assertions: full pinned body + `If-Match`, 422 detail+issues, the `input_refresh_required` banner, and the 412 reload path. A new case covers the retired-workbench (seeded value absent from the list) scenario.

<details>
<summary>Issues (2)</summary>

1. **Read-only checksum lacks a disabled/aria affordance** (possible, non-blocking) — the checksum `Input` is `readOnly required`; it is correctly derived from the chosen source file, but a screen reader gets no "read only" cue beyond the native `readonly` attribute. Optional: add `aria-readonly` or helper text. Not required for this change.
2. **Synthetic "(not in current list)" item shows the raw id, not a human label** (confirmed, by design) — when a seeded `raw_id`/`dataset_code`/`artifact_id` is not in the loaded options, the fallback `SelectItem` label is the opaque id. This is the documented trade-off (no label is available for a retired/absent record) and preserves the value rather than dropping it. No action needed.

</details>

<details>
<summary>Details</summary>

### Dropdowns are backed by real hooks, text fields are not faked

Each dropdown resolves to a generated LIST hook that exists with the exact fields read: `useListRawAggregates(studyId, {limit}, {query:{enabled}})` → `AggregateCollection.items` of `AggregateResponse` (`id`, `code`, `name`, `revision`, `status`); `useListDatasets(rawId, {query:{enabled}})` → `RawDatasetResponse[]` (array, matching `datasetsQuery.data ?? []`); `useListSourceFiles(studyId, {limit}, {query:{enabled}})` → `SourceFileCollection.items` of `SourceFileResponse` (`artifact_id`, `filename`, `sha256`, `id`). All confirmed against `src/api/generated`.

`validation_run_id` and `raw_dependency_fingerprint` remain free-text `Input`s with explanatory comments. A search of the generated validation client finds no `useListValidation*` / `listValidationRuns` / `ValidationRunCollection`, so there is no endpoint to enumerate validation runs; and the raw-context payload is an untyped `{ [key: string]: unknown }` dictionary with no fingerprint field. Keeping both as text — rather than inventing a client-side list — is the correct, constraint-respecting decision.

### Body shape and If-Match are unchanged

`toWriteBody` still emits `raw_id` (trimmed), `raw_revision` (`Number(...)`), `validation_run_id` (trimmed), `raw_dependency_fingerprint` (trimmed), and `source_artifacts[].{dataset_code,artifact_id,checksum}` (each trimmed). Dropdown values are plain strings, so the trim/cast path is identical to the previous free-text path. The mutation is created with `request: ifMatch()`, which rebinds to the current aggregate revision on each render, so a post-412 retry carries the fresh ETag. The 10.1 test asserts the exact body and `ifMatchRequest(AGGREGATE_REVISION)`, and it still passes per the recorded verification.

### Gating, disabled, and empty states

`enabled: !!studyId` gates the raw-aggregate and source-file queries; `enabled: !!form.raw_id` gates the dataset query. The dataset `Select` is `disabled={!form.raw_id}` with a "Select a Raw workbench first" placeholder until a workbench is chosen, then "Select a dataset". Raw-workbench and artifact selects carry their own placeholders.

### Seeded-value preservation

For all three dropdowns, when the current form value is non-empty but not present among loaded items, a synthetic `SelectItem value={form.raw_id}` (or dataset code / artifact id) is rendered labeled "<id> (not in current list)" so Radix renders the saved selection instead of blanking it. The `onValueChange` handlers (`selectRawAggregate`, `selectArtifact`, and the inline dataset handler) all early-return on an empty value, guarding against Radix emitting a transient empty value during reconciliation of a controlled value with no matching item. The retired-workbench test (`rawApi.rawAggregates = []`) confirms the seeded `raw_id: 'raw-1'` still submits unchanged.

### Accessibility and controls preserved

`raw_id` → `Label htmlFor="is-raw-id"` → `SelectTrigger id="is-raw-id"`; each row's dataset and artifact selects carry `htmlFor`/`id` pairs (`is-artifact-dataset-${index}`, `is-artifact-id-${index}`), and the checksum keeps `is-artifact-checksum-${index}`. The add button ("Add artifact"), the per-row remove button (`aria-label="Remove source artifact N"`, disabled when only one row), and the "Save input selection" submit label are all unchanged.

### Test coverage

The suite mocks `@/api/generated/raw/raw` and `@/api/generated/artifacts/artifacts` with faithful fakes driven by a mutable `rawApi` seeded in `beforeEach` so the seeded `makeSelection()` ids resolve to real options. Preserved assertions: full pinned body + `If-Match` (10.1), 422 `sdtm_raw_artifact_invalid`/`sdtm_raw_validation_invalid` detail+issues (10.4), `input_refresh_required` → "Input selection needs a refresh" banner (10.5), 412 concurrency message + reload invalidating `getGetSdtmAggregateQueryKey` (10.6). Added: a dropdown-label assertion (`RAW1 — Raw one`, `DM — Demographics`, `dm.xpt`) that still submits the unchanged body, and the retired-workbench preservation case. The sibling `SpecificationPanel` tests in the same file are untouched and share the unchanged SDTM mock.

Not tested: whether `useListDatasets` actually re-queries when `form.raw_id` changes at runtime (the fake ignores the arg and returns a static array), and the auto-fill of `raw_revision`/`checksum` on a live user selection (the tests drive seeded values, not an open-and-click). These are acceptable given the plan's note that Radix under jsdom renders trigger text without opening the listbox; the behavior is covered by code inspection.

Verification evidence is present in the commit message: `npm run typecheck` pass, input-selection suite 13 pass, `npm run lint` 0 errors, `npm run test` 277 pass. No articulable doubt remained that warranted re-running the suites; spot-checks were limited to confirming the generated hooks/models and client cleanliness.

</details>

<details>
<summary>File map</summary>

- `frontend/src/components/workbench/input-selection-panel.tsx` — new panel: three list-backed Selects (raw workbench, dataset code, artifact id), auto-fill of `raw_revision` and `checksum`, seeded-value preservation, `validation_run_id`/`raw_dependency_fingerprint` kept as text; body/If-Match/422/412/staleness/raw-context behavior unchanged.
- `frontend/src/components/workbench/-input-selection-specification.test.tsx` — new test: adds raw/artifacts list-hook fakes, dropdown-label and retired-workbench assertions; preserves 10.1/10.4/10.5/10.6 and the SpecificationPanel suite.

Full diff: `git show 27abf7f`.

</details>
