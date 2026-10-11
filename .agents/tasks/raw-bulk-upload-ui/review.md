# Raw bulk-upload UI — two-phase dataset import on the Raw workbench

The change adds a frontend-only bulk-import flow to the Raw workbench's Datasets panel. A new "Bulk upload" header button opens a modal that walks the user through a two-phase flow: upload many source files at once via the existing `createSourceFilesBulk` endpoint, then author one dataset per uploaded file in an editable table and submit a single all-or-nothing import via `createDatasetImport`. The import is polled to a terminal status (`getDatasetImport`) through the shared `useOperationPoll` hook, with a cancel control (`cancelDatasetImport`) available while non-terminal. All four generated hooks are consumed unchanged; no file under `frontend/src/api/generated/` was touched. The work is split into pure helpers (`raw-bulk-import.ts`), three presentational/container components, and two test files, mirroring existing workbench conventions.

Watch for: nothing blocking. The `issue.id` key used in the failure issue list is read off `ValidationIssue` but is not declared in the generated `ValidationIssue` model surfaced in the design note — worth a glance, but the test fixtures supply `id` and typecheck passed, so this is **possible** at most and not a defect in the diff.

**Verdict**: APPROVED

## High-level view

The flow is a single stateful dialog (`raw-bulk-import-dialog.tsx`) driving a discriminated phase machine (`select → uploading → author → submitting → polling → terminal`), with the editable table and the status/polling panel as controlled presentational children. State resets on open, mirroring `DatasetCreateDialog`. The structure keeps the one stateful unit testable and leans entirely on existing primitives — `FileDropzone`, `useOperationPoll`, `useIdempotencyKey`, `parseProblem`/`stalenessAlert`, `StatusBadge`, `invalidateRawDataset` — rather than introducing anything new.

The generated client is consumed exactly as the plan prescribes: `useCreateSourceFilesBulk` (artifacts), `useCreateDatasetImport`/`useGetDatasetImport`/`useCancelDatasetImport` (raw), with model types imported from the barrel. The `File[] as unknown as string[]` cast matches the body-type/FormData mismatch already handled by the single-file upload path. The generated directory diff is empty.

Client-side validation lives in a pure, well-tested module: the code pattern `^[A-Za-z][A-Za-z0-9_]{0,63}$` is reproduced verbatim from the generated `RawDatasetImportEntry` contract, intra-batch duplicate detection is exact/case-sensitive and flags every member of a duplicate group, and submit is gated until the batch is clean. The request builder trims, omits blank descriptions, defaults `initialize_variables`, and omits `expected_raw_revision` per the R1 decision.

Error surfacing distinguishes 413/415 upload failures, 409/428 staleness, and 422 per-row issue mapping, all via the shared problem helpers; edits are retained on every submit error. The all-or-nothing contract is honored — only a terminal `succeeded` invalidates the dataset list and the success copy reports a count, while `failed`/`cancelled` state explicitly that no datasets were created. No object-store key or internal path is ever rendered; source files are shown by `filename`/`media_type` only, and the import response exposes no such field.

Test coverage mirrors the existing `-*.test.tsx` convention: a pure-helper unit suite plus a component/integration suite that mocks the generated hook modules and drives the real dialog through all phases, including a scripted poll under fake timers. Verification evidence is present and specific.

<details>
<summary>Issues (1)</summary>

1. **`ValidationIssue.id` key** — the failure issue list keys on `issue.id`; confirm `id` is a declared field on the generated `ValidationIssue` model (test fixtures supply it and typecheck passed, so likely a non-issue). Non-blocking.

</details>

<details>
<summary>Details</summary>

## Generated-client consumption

The diff touches no file under `frontend/src/api/generated/` — confirmed by an empty `git diff master --stat` on that path. The four hooks are imported from their generated module paths (`@/api/generated/raw/raw`, `@/api/generated/artifacts/artifacts`) and all model types from the `@/api/generated/model` barrel. The hook signatures line up with what the components call: `useCreateSourceFilesBulk` mutates `{ studyId, data }`, `useCreateDatasetImport({ request })` mutates `{ rawId, data }`, `useGetDatasetImport(id, { query })` and `useCancelDatasetImport` mutating `{ importId }` all exist as used.

The `files: picked as unknown as string[]` cast in `handleUpload` is the sanctioned workaround for orval typing the multipart body as `{ files: string[] }` while the mutator appends real `File` objects to `FormData`; it matches the existing single-file `useCreateSourceFile` call in `datasets-panel.tsx`. Not a hand-edit of generated code — a cast at the call site.

## Two-phase flow and phase machine

The dialog holds a `Phase` union and resets every piece of state in a `useEffect` keyed on `open`, matching `DatasetCreateDialog`. Phase 1 renders `FileDropzone multiple` and lists picked files by name and size. On upload success it seeds one authoring row per returned `SourceFileResponse` in order (`seedRowsFromUpload`), each row defaulting its bound source file to its own upload. Phase 2 renders the controlled `RawBulkImportTable`; submit is gated by `canSubmit = phase === 'author' && rows.length > 0 && rowsAreValid(validation)`. On 202 the response id drives phase 3's `RawBulkImportStatus`, which owns the poll and reports status/terminal back up through `onStatus`/`onTerminal` callbacks — keeping `useOperationPoll` as the single polling mechanism as the design required.

The status panel's terminal callback is latched on `terminalId` (the settled import id) so `onTerminal` — and therefore `invalidateRawDataset` — fires once per settled import, the same latching `ExecutionPanel` uses.

## Client-side validation

`CODE_PATTERN` is `^[A-Za-z][A-Za-z0-9_]{0,63}$`, identical to the `@pattern` annotation on the generated `RawDatasetImportEntry.code`. `validateRows` groups rows by exact trimmed code, flags every member of any group with more than one row (case-sensitive, so `AB`/`ab` are distinct), checks the code pattern, the 1–255 label bound, and that the bound source file is one of this session's uploads; it emits a top-level error for an empty or >500 batch. The unit suite covers the regex boundaries (leading digit, single char, 64 vs 65), all three duplicate shapes, label 0/255/256, the count bounds, and the request-builder shape (envelope `1.0.0`, order preserved, `initialize_variables` default, description trim/omit).

`buildImportRequest` trims code/label, omits `description` when blank, defaults `initialize_variables`, and omits `expected_raw_revision` — consistent with the R1 out-of-scope note.

## Error surfacing

Upload failures map 413/415 to specific copy and fall back through `parseProblem().detail → axiosError.message`, retaining the picked files and returning to `select`. Submit errors keep the dialog in `author` and retain all edits: 409/428 route through `stalenessAlert`, and 422 runs `mapIssuesToRows`, which keys issues to rows by `dataset` (the dataset code) and drops unplaceable issues into a top-level list with all-or-nothing copy. The 422 path builds its row lookup from the current (trimmed) row codes, which is the right join key since the backend reports the offending dataset by code.

One nuance worth noting (not a defect): the status panel renders a `pollProblem` notice whenever `poll.problem` is set, independent of `poll.phase`. Because the poll adapter sets `retry: false`, a poll `problem+json` sets `poll.problem` and flips the phase to `error`, so the notice shows and polling halts — the intended behavior.

## All-or-nothing and no-leak invariants

Only `response.status === 'succeeded'` triggers `invalidateRawDataset`; `failed` and `cancelled` render notices that explicitly state no datasets were created, and success copy reports a count from `result_dataset_ids.length` rather than listing ids. The table and status panel reference source files by `filename`/`media_type` only. The `RawDatasetImportResponse` and `SourceFileResponse` models expose no object-store key or path field, so there is nothing to leak; the components never attempt to construct one. The failure branch renders only `failure.code`/`failure.detail` and the typed `issues[]` (code, severity, message, suggestion, dataset/variable/field_path) — no raw payloads.

## Test coverage

The component suite follows the repo's `-*.test.tsx` convention: it mocks the generated hook modules and toast, stubs `invalidateRawDataset`, imports the real dialog after the mocks, and drives a scripted get-operation hook under fake timers for the poll. It covers upload-seeds-rows, 413 retention, code-pattern gating, intra-batch duplicate gating (asserting no request is sent), submit carrying a UUID `Idempotency-Key` and entries in order, 422→row mapping with edit retention, 409 staleness banner with edit retention, queued→running→succeeded with a single `invalidateRawDataset`, failed terminal rendering the typed failure plus issues with no invalidation, and the cancel control calling `cancelDatasetImport` while non-terminal. The `-datasets-panel.test.tsx` change stubs the newly mounted dialog so that file's own flow tests don't pull in the bulk hooks it doesn't mock — an additive, correct adjustment.

Not tested: the >500-entry top-level form error at the component level (covered at the unit level only, and effectively unreachable through the UI since the file picker is the gate), and the client-timeout `timed-out` notice. Neither gap is material.

## Idempotency-key timing (pre-existing pattern, not a regression)

`useIdempotencyKey()` mints a key lazily on first render and stores it in a ref; `useCreateDatasetImport({ request: idempotency.requestConfig })` captures the config at render time, and `handleSubmit` calls `idempotency.begin()` to mint a fresh key for the attempt. Because `requestConfig` is captured at the prior render, `begin()`'s new key takes effect on the next render rather than for the in-flight call — but a valid UUID is always present and sent (the backend's actual requirement). This timing is identical to the cited `ExecutionPanel` pattern, so it is accepted existing behavior, not something this diff introduced. Called out for completeness only.

## Verification evidence

`verification.md` and the commit message both report lint (0 errors, 10 pre-existing warnings in unrelated files), typecheck (0 errors), build (success), and the full vitest run (29 files, 321/321). The evidence names the exact commands, explains the local-binary vitest invocation, and confirms the generated directory is unchanged — which I independently reconfirmed. No articulable doubt remained that would justify re-running a suite, so per the review mandate I did not.

</details>

<details>
<summary>File map</summary>

- `frontend/src/components/workbench/raw-bulk-import.ts` — new pure helpers: code pattern, `validateRows`, `rowsAreValid`, `seedRowsFromUpload`, `buildImportRequest`.
- `frontend/src/components/workbench/raw-bulk-import-table.tsx` — new editable entry table (phase 2), controlled.
- `frontend/src/components/workbench/raw-bulk-import-status.tsx` — new inline polling/status panel (phase 3) over `useOperationPoll`.
- `frontend/src/components/workbench/raw-bulk-import-dialog.tsx` — new two-phase dialog state machine (public export).
- `frontend/src/components/workbench/raw-bulk-import.test.ts` — new pure-helper unit suite.
- `frontend/src/components/workbench/-raw-bulk-import.test.tsx` — new dialog component/integration suite.
- `frontend/src/components/workbench/datasets-panel.tsx` — added "Bulk upload" header button + mounted the dialog.
- `frontend/src/components/workbench/index.ts` — barrel export of `RawBulkImportDialog` + props type.
- `frontend/src/components/workbench/-datasets-panel.test.tsx` — stubbed the newly mounted dialog.

Full diff: `git -C e:\Work\EDETEK\Python\aurinara\.worktrees\raw-bulk-upload-ui diff master`

</details>
