# Design note — Raw bulk-upload UI (frontend-only)

## Overview

Add a combined two-phase bulk-import flow to the Raw workbench so a user can upload many raw source files at once and then create one dataset per uploaded file in a single all-or-nothing import. The feature is frontend-only inside the `raw-bulk-upload-ui` worktree (`frontend/` subtree). It consumes the EXISTING orval-generated client functions `createSourceFilesBulk` (artifacts), `createDatasetImport` / `getDatasetImport` / `cancelDatasetImport` (raw) — no client regeneration or hand-editing. It reuses the established component, mutation, header, and polling patterns rather than inventing new ones.

Stack is locked to what the frontend already uses: React 18 + TypeScript, TanStack Query 5, TanStack Router, Radix/shadcn UI primitives under `@/components/ui/*`, axios via the shared `customInstance`, `sonner` toasts, `lucide-react` icons, and `vitest` + `@testing-library/react` for tests. No new dependencies.

## Where it mounts

The Raw workbench detail route is `frontend/src/routes/_app/raw/$rawId.tsx`, which renders a `WorkbenchDetailShell` with a tabs array. The current `datasets` tab renders `DatasetsPanel` (`frontend/src/components/workbench/datasets-panel.tsx`), which already owns the dataset list and the single-file create/rebind dialogs.

Decision: add the bulk flow as a modal dialog launched from the Datasets panel header, next to the existing "New dataset" button, rather than as a new tab. Rationale — the flow produces datasets and belongs with dataset management; it reuses `DatasetsPanel`'s `rawId`/`studyId` props and its `invalidateRawDataset` success path; and a tab would fragment "create a dataset" across two places. The new control is a `Button` ("Bulk upload") in the existing `PageHeader actions` of `DatasetsPanel`.

New files (all under `frontend/src/components/workbench/`):

- `raw-bulk-import-dialog.tsx` — the dialog shell and the two-phase state machine (the one stateful container).
- `raw-bulk-import-table.tsx` — the editable entry table (phase 2 authoring).
- `raw-bulk-import-status.tsx` — the inline status/polling panel (phase 3).
- `raw-bulk-import.ts` — pure helpers (code regex, intra-batch duplicate detection, request builder) kept I/O-free for unit testing.

`DatasetsPanel` gets a small edit: import the dialog, add `bulkOpen` state and the header button, and render `<RawBulkImportDialog rawId={rawId} studyId={studyId} open={bulkOpen} onOpenChange={setBulkOpen} />`. Export the new public component from `frontend/src/components/workbench/index.ts` to match the existing barrel convention.

## Reused components, hooks, and patterns (named)

- `FileDropzone` (`components/workbench/file-dropzone.tsx`) with `multiple` enabled for the multi-file picker. Its `onFiles(File[])` funnel already unifies drop and browse.
- `useOperationPoll` + `OPERATION_POLL_PRESETS.fast` (`hooks/use-operation-poll.ts`) for phase-3 polling, exactly as `execution-panel.tsx` uses it. A thin adapter wraps `useGetDatasetImport`.
- Header helpers in `lib/requests.ts`: `useIdempotencyKey()` for the import POST's `Idempotency-Key` (stable across retries; `begin()` on each submit), mirroring `ExecutionPanel`.
- `lib/problems.ts`: `parseProblem` and `stalenessAlert` for 409/412/428 handling and `problem+json` rendering.
- `lib/invalidate.ts`: `invalidateRawDataset(qc, rawId)` on terminal `succeeded` so the dataset list refetches.
- UI primitives already in use by `DatasetsPanel`: `Dialog*`, `Button`, `Input`, `FormItem/FormControl/FormLabel/FormMessage`, `StatusBadge`, `toast`, `Loader2`. The entry table uses `components/data/resource-table` styling conventions or a plain table with the same classes; given inline editing, a lightweight `<table>` with `Input`/`Checkbox`/`Select` cells is used (ResourceTable is read-only), matching the Tailwind classes already present in the panel.
- Status-badge mapping for `queued|running|succeeded|failed|cancelled` via the shared `StatusBadge`.

## Contract facts (verified against the generated client)

- `createSourceFilesBulk(studyId, { files: File[] })` → `SourceFileBulkResponse { items: SourceFileResponse[] }`, multipart field `files`, items in request order. `SourceFileResponse` exposes `id`, `filename`, `media_type`, `sha256`, `size` (no object-store key — nothing to hide, nothing to construct).
- `createDatasetImport(rawId, RawDatasetImportRequest, requestConfig)` → `RawDatasetImportResponse` (202). Request: `{ schema_version: '1.0.0', expected_raw_revision?: number>=1, entries: RawDatasetImportEntry[] }`, `entries` is 1–500. Entry: `{ code, label, description?, source_file_id, initialize_variables? }`, `code` pattern `^[A-Za-z][A-Za-z0-9_]{0,63}$`, `label` 1–255 chars. The generated function sets `Content-Type: application/json`; `useIdempotencyKey().requestConfig` re-emits `Content-Type` and adds `Idempotency-Key`.
- `getDatasetImport(importId)` → `RawDatasetImportResponse` at `/api/v1/raw-dataset-imports/{importId}`; `useGetDatasetImport` and `getGetDatasetImportQueryKey` exist.
- `cancelDatasetImport(importId)` → `RawDatasetImportResponse` at `.../{importId}/cancel`.
- `RawDatasetImportResponse` fields consumed: `id`, `status` (`queued|running|succeeded|failed|cancelled`), `entry_count`, `files_inspected`, `result_dataset_ids`, `issues: ValidationIssue[]`, `failure` (nullable object), `started_at`, `completed_at`. `ValidationIssue`: `code`, `severity` (`IssueSeverity`), `message`, `suggestion?`, `dataset?`, `variable?`, `field_path?`, `entity_type`, `module`.

## State machine (two-phase flow)

The dialog holds a discriminated phase state:

1. `select` — multi-file `FileDropzone`. Shows the pending file list (name, size). "Upload files" calls `createSourceFilesBulk`. While pending → `uploading`.
2. `uploading` — spinner; disable inputs. On success → `author`, seeding one table row per returned `SourceFileResponse` in order. On error → back to `select` with an error alert (files retained for re-pick).
3. `author` — the editable entry table. Each row: `code` (text), `label` (text), `description` (optional text), `source_file` (Select defaulting to the file uploaded for that row, options = all uploaded files this session), `initialize_variables` (Checkbox). Client-side validation runs continuously; "Submit import" is disabled until valid. On submit → `submitting`.
4. `submitting` — `createDatasetImport` with a fresh idempotency key. On 202 → store `importId`, go to `polling`. On 4xx (`problem+json`) → stay in `author`, surface the error (see Error surfacing), retain all edits.
5. `polling` — `RawBulkImportStatus` drives `useOperationPoll`. Terminal `succeeded` → `done-success`; `failed` → `done-failed`; `cancelled` → `done-cancelled`; client timeout → `timed-out` notice.
6. terminal states — show summary; on `succeeded` call `invalidateRawDataset(qc, rawId)` once (keyed on terminal import id, like `ExecutionPanel`'s effect) and offer "Close". A "Cancel import" control is visible whenever `status` is non-terminal (`queued`/`running`), wired to `cancelDatasetImport`.

Re-opening the dialog resets to `select`. Uploaded files from a prior session are discarded on close (the dialog is unmounted or its state reset in a `useEffect` on `open`, matching `DatasetCreateDialog`).

## Polling approach

Mirror `ExecutionPanel`. Define `const IMPORT_TERMINAL = ['succeeded','failed','cancelled'] as const`. Adapter:

```ts
function useDatasetImportOperation(id: string, opts: OperationQueryOpts) {
  const q = useGetDatasetImport(id, { query: { ...opts.query, retry: false } })
  return { data: q.data, error: q.error as AxiosError | null }
}
```

Then `useOperationPoll<RawDatasetImportResponse>({ operationId: importId, useGetOperation: useDatasetImportOperation, intervalMs: fast.intervalMs, timeoutMs: fast.timeoutMs, terminalStatuses: IMPORT_TERMINAL })`. `retry: false` so a `problem+json` surfaces immediately and stops polling. Progress text uses `files_inspected`/`entry_count` while running; the elapsed clock comes from `poll.elapsedMs`.

## Client-side validation rules

Enforced in `raw-bulk-import.ts` before enabling submit (backend remains authoritative):

- `code`: required; must match `^[A-Za-z][A-Za-z0-9_]{0,63}$`. Failure → per-row field message "Code must start with a letter and use only letters, digits, or underscore (max 64)."
- `label`: required; 1–255 chars. Failure → "Label is required (max 255)."
- `description`: optional; no format rule.
- `source_file_id`: required; must reference one of this session's uploaded files (always satisfied since it defaults and the Select is constrained).
- `initialize_variables`: boolean; defaults `false`.
- Intra-batch duplicate `code` (case-sensitivity matching the backend natural key — treat as exact/case-sensitive unless the duplicate rule proves otherwise; surface before submit): flag every row sharing a code with a sibling, message "Duplicate code within this batch." This pre-empts the backend 422.
- Entry count 1–500: block submit above 500 with a top-level message; the dialog cannot exceed 500 unless 500+ files are uploaded, in which case the upload itself is the gate.

`buildImportRequest(rows)` returns `{ schema_version: '1.0.0', entries }` (omit `expected_raw_revision` for R1 — the dialog does not currently read the aggregate revision; note left as a future optimistic-concurrency hook).

## Error surfacing

Each operation that can fail:

- Bulk upload (`createSourceFilesBulk`): 413/415 and generic `problem+json`. Recoverable — show a top-level alert in the `select` phase using `uploadErrorMessage`-style mapping (reuse the local helper pattern from `DatasetsPanel`: 413 → size message, 415 → media-type message, else `parseProblem().detail`). Files retained for re-pick. Not logged (user-facing only; axios surfaces status).
- Import submit (`createDatasetImport`): 422 (invalid clinical/standards content incl. duplicate codes), 409 (idempotency conflict, duplicate natural key, stale input), 428 (missing precondition). Recoverable — stay in `author`, retain edits. 409/428 → `stalenessAlert(error)` top-level banner. 422 → map `problem.issues[]`/`errors[]` onto per-row fields when `field_path`/location identifies a row/field, else a top-level list; reuse the `mapProblemToFieldErrors` approach (field names here are row-scoped, so map by issue `dataset`/`field_path` to the matching row). Copy states the import is all-or-nothing — nothing was created.
- Poll (`getDatasetImport`): a `problem+json` (e.g. 404/403) stops polling via `retry:false`; render a `Notice`-style alert. Client timeout (120s cap) → "still running on the server" notice; no result shown. Terminal `failed` → render the typed `failure` object (`code`/`detail` when present) plus the per-entry `issues[]` list (code, severity, message, suggestion, dataset, variable, field_path). Terminal `cancelled` → neutral notice.
- Cancel (`cancelDatasetImport`): best-effort; on error show a toast and keep polling (the server state remains authoritative). On success the next poll reflects `cancelled`.

Invariant ownership: client validation is a convenience guard only; the backend owns code-pattern, duplicate, and all-or-nothing enforcement. The UI must never claim partial success — on any non-`succeeded` terminal it states no datasets were created, and only `succeeded` triggers `invalidateRawDataset`. Never render object-store keys or internal paths (the API returns none).

## Testability

Unit (pure, no network) in `raw-bulk-import.test.ts`:
- code-regex accept/reject cases (leading digit, length 64 boundary, illegal chars);
- intra-batch duplicate detection (none / one pair / multiple groups);
- `buildImportRequest` shape (schema_version, entries order, `initialize_variables` default, description omitted when empty).

Component/integration in `-raw-bulk-import.test.tsx` with `@testing-library/react` and a `QueryClientProvider`, mocking the generated hooks (as the existing `-raw-ops-panels.test.tsx` / `-compile-execution-panels.test.tsx` do):
- select → upload → author seeds one row per returned file in order, each defaulting to its own source file;
- submit disabled while a row is invalid / has a duplicate code; enabled when valid;
- 422 with issues maps to the right rows and retains edits;
- 409/428 shows the staleness banner and retains edits;
- 202 → polling renders, running progress uses `files_inspected`/`entry_count`;
- terminal `succeeded` shows summary, lists `result_dataset_ids` count, and calls `invalidateRawDataset`;
- terminal `failed` renders `failure` + typed `issues[]`;
- cancel control visible only while non-terminal and calls `cancelDatasetImport`.

The dialog container is the only stateful unit; keeping helpers pure and the status panel driven by the shared `useOperationPoll` keeps everything mockable. Run `npm run typecheck`, `npm run lint`, and `npm run test` (vitest) from `frontend/` before handoff.

## Out of scope

- No backend changes, no OpenAPI/orval regeneration or client hand-edits.
- No new design system or shared primitives beyond the four new files.
- No `expected_raw_revision` optimistic-concurrency UI in R1 (noted as a future hook).
- No partial-success handling (the import is all-or-nothing by contract).
- No persistence of uploaded-file session state beyond the open dialog.
