# Implementation Plan — Raw bulk-upload UI (frontend-only)

Derived from `.agents/tasks/raw-bulk-upload-ui/design.md`. All paths are absolute under the worktree
`e:\Work\EDETEK\Python\aurinara\.worktrees\raw-bulk-upload-ui`. Every path begins with
`e:\Work\EDETEK\Python\aurinara\.worktrees\raw-bulk-upload-ui\frontend\` — written below as
`<FE>\` for brevity. Resolve `<FE>` to that absolute prefix; never use relative paths (they would land in
the parent workspace, not the worktree).

## Hard constraints (restated — do not violate)

- Do NOT run `npm run api:generate` / `api:sync` / `api:export`, and do NOT hand-edit anything under
  `<FE>\src\api\generated\`. Consume the EXISTING generated functions/hooks and model types only.
- Consume these exact generated symbols (verified in the generated client):
  - `useCreateSourceFilesBulk` from `@/api/generated/artifacts/artifacts` — mutate vars
    `{ studyId: string; data: { files: string[] } }` (the body type
    `BodyCreateSourceFilesBulkApiV1StudiesStudyIdSourceFilesBulkPost` has field `files: string[]`; orval appends
    each `File` via `FormData`, so pass real `File[]` cast as the DatasetsPanel upload does:
    `files: files as unknown as string[]`). Returns `SourceFileBulkResponse { items: SourceFileResponse[] }`,
    items in request order.
  - `useCreateDatasetImport` from `@/api/generated/raw/raw` — mutate vars
    `{ rawId: string; data: RawDatasetImportRequest }`, returns `RawDatasetImportResponse` (202).
  - `useGetDatasetImport` + `getGetDatasetImportQueryKey` from `@/api/generated/raw/raw` — `GET /api/v1/raw-dataset-imports/{importId}`.
  - `useCancelDatasetImport` from `@/api/generated/raw/raw` — mutate vars `{ importId: string }`,
    returns `RawDatasetImportResponse` (`POST .../{importId}/cancel`).
- Model types to import from `@/api/generated/model` (all barrel-exported): `SourceFileResponse`,
  `SourceFileBulkResponse`, `RawDatasetImportRequest`, `RawDatasetImportEntry`, `RawDatasetImportResponse`,
  `RawDatasetImportResponseStatus`, `ValidationIssue`, `IssueSeverity`.
- NEVER display object-store keys or internal filesystem paths. The API returns none
  (`SourceFileResponse` has only `id`/`filename`/`media_type`/`sha256`/`size`/timestamps); display `filename`
  and human metadata only.
- Import is ALL-OR-NOTHING: never render or imply partial success. Only a terminal `succeeded` triggers
  `invalidateRawDataset`; any other terminal (`failed`/`cancelled`) must state no datasets were created.
- No new npm dependencies. There is NO `Checkbox` UI primitive — use a native
  `<input type="checkbox" className="size-4">` exactly as `<FE>\src\components\workbench\artifacts-panel.tsx`
  does. Use the existing `@/components/ui/select` for the source-file picker and `@/components/ui/textarea`
  (available) or `@/components/ui/input` for text cells.
- `RawDatasetImportEntry.code` pattern is `^[A-Za-z][A-Za-z0-9_]{0,63}$`; `label` is 1–255 chars;
  `entries` is 1–500 items; `schema_version` is the literal `'1.0.0'`. Omit `expected_raw_revision` (R1).

## Patterns to mirror (named, already in the repo)

- Dialog shell / reset-on-open / per-field error state: `DatasetCreateDialog` inside
  `<FE>\src\components\workbench\datasets-panel.tsx` (`React.useEffect(..., [open])` reset).
- Multi-file picker: `FileDropzone` (`<FE>\src\components\workbench\file-dropzone.tsx`) with `multiple`.
- Upload-error mapping (413/415/else): the local `uploadErrorMessage` helper + `parseProblem` in
  `datasets-panel.tsx`.
- Polling: `ExecutionPanel` (`<FE>\src\components\workbench\execution-panel.tsx`) — its
  `useExecutionRunOperation` adapter + `useOperationPoll` + `OPERATION_POLL_PRESETS.fast` +
  terminal-id `useEffect` invalidation. Reuse `useOperationPoll` from `@/hooks/use-operation-poll`.
- Idempotency: `useIdempotencyKey()` from `@/lib/requests` with `begin()` per submit (as `ExecutionPanel`).
- Problem/staleness: `parseProblem`, `stalenessAlert`, `mapProblemToFieldErrors` from `@/lib/problems`.
- Invalidation: `invalidateRawDataset(qc, rawId)` from `@/lib/invalidate`.
- Status rendering: `StatusBadge` from `@/components/data/status-badge`; the `Notice`/`Metric` inline
  helpers in `execution-panel.tsx` as a model for the status/failure surfaces.
- Component-test mocking: `<FE>\src\components\workbench\-raw-ops-panels.test.tsx` and
  `-compile-execution-panels.test.tsx` — mock the generated hook modules with `vi.mock`, drive the real
  component over faithful hook fakes, use `installJsdomHarness`, fake timers for polling.

## Verification commands (run from `<FE>`)

- Typecheck: `npm run typecheck` (expect no errors).
- Lint: `npm run lint` (expect no new errors).
- Tests: `npm run test` (vitest run; expect all green). Scope while iterating with
  `npx vitest run src/components/workbench/raw-bulk-import` and
  `npx vitest run src/components/workbench/-raw-bulk-import`.

---

# Implementation Plan

- [ ] 1. Create the pure helper module with the client-side validation and request builder (I/O-free, no React).
      Export: `CODE_PATTERN = /^[A-Za-z][A-Za-z0-9_]{0,63}$/`; a `BulkImportRow` type
      (`{ id; code; label; description; source_file_id; initialize_variables }` — `id` a stable local key);
      `validateRows(rows): { rowErrors: Record<string, {code?; label?; sourceFile?}>; formError: string | null }`
      enforcing: required `code` matching `CODE_PATTERN` ("Code must start with a letter and use only letters,
      digits, or underscore (max 64)."), required `label` 1–255 ("Label is required (max 255)."),
      `source_file_id` references a known uploaded file, exact/case-sensitive intra-batch duplicate `code`
      detection flagging every row in a duplicate group ("Duplicate code within this batch."), and a top-level
      error when `rows.length` is 0 or > 500; a `seedRowsFromUpload(items: SourceFileResponse[]): BulkImportRow[]`
      that makes one row per uploaded file in order defaulting `source_file_id` to that file and
      `initialize_variables` to `false`; and `buildImportRequest(rows): RawDatasetImportRequest` returning
      `{ schema_version: '1.0.0', entries }` with `entries` in row order, trimming `code`/`label`, OMITTING
      `description` when empty/blank, and defaulting `initialize_variables` to `false`.
      Files: `<FE>\src\components\workbench\raw-bulk-import.ts`
      Verify: `npm run typecheck` passes (module compiles against the generated model types). Full behavior is
      exercised by the unit test in step 2.

- [ ] 2. Add the pure-helper unit test (mirrors `preview-panel.clamp.test.ts` / `acrf-rect.validate.test.ts` — plain
      vitest, no DOM, no network).
      Cover: `CODE_PATTERN` accept/reject (leading digit rejected, 1-char accepted, length-64 boundary accepted /
      65 rejected, illegal chars rejected); `validateRows` duplicate detection (none / one pair / multiple groups,
      all members flagged, case-sensitive so `AB` vs `ab` are distinct); label length 0 and 256 rejected, 255
      accepted; entry-count 0 and 501 produce the top-level error; `buildImportRequest` shape
      (`schema_version === '1.0.0'`, entries order preserved, `initialize_variables` defaults to `false`,
      `description` omitted when blank and included when present).
      Files: `<FE>\src\components\workbench\raw-bulk-import.test.ts`
      Verify: `npx vitest run src/components/workbench/raw-bulk-import.test.ts` — all cases pass.

- [ ] 3. Create the editable entry table (phase-2 authoring, presentational/controlled — receives `rows`, `files`,
      `rowErrors`, and `onChange(id, patch)` from the dialog; holds no network state).
      Render one row per `BulkImportRow`: a `code` text `Input`, a `label` text `Input`, an optional `description`
      `Input`/`Textarea`, a source-file `Select` (from `@/components/ui/select`) whose options are all uploaded
      files this session labeled by `filename` (+ `media_type`) and defaulting to the row's `source_file_id`, and a
      native `<input type="checkbox" className="size-4">` for `initialize_variables` (mirror the checkbox markup in
      `artifacts-panel.tsx`; associate a `<label>`/`id` for the test's `getByLabelText`). Show per-field messages
      from `rowErrors[row.id]` using `FormMessage`/`aria-invalid`. Use a plain `<table>`/`@/components/ui/table`
      with the Tailwind classes already used in the panel (ResourceTable is read-only — do not use it here).
      Never render object-store keys or paths — `filename` only.
      Files: `<FE>\src\components\workbench\raw-bulk-import-table.tsx`
      Verify: `npm run typecheck` passes. Rendering/behavior is covered by step 6's component test.

- [ ] 4. Create the inline status/polling panel (phase-3, presentational — receives the `importId` and renders the
      live `RawDatasetImportResponse`; owns no submit logic).
      Define `IMPORT_TERMINAL = ['succeeded','failed','cancelled'] as const`. Add a
      `useDatasetImportOperation(id, opts)` adapter wrapping `useGetDatasetImport(id, { query: { ...opts.query,
      retry: false } })` and projecting `{ data, error }` (exactly like `useExecutionRunOperation`). Drive
      `useOperationPoll<RawDatasetImportResponse>({ operationId: importId, useGetOperation:
      useDatasetImportOperation, intervalMs: OPERATION_POLL_PRESETS.fast.intervalMs, timeoutMs:
      OPERATION_POLL_PRESETS.fast.timeoutMs, terminalStatuses: IMPORT_TERMINAL })`. Render: while `polling`, a
      spinner + progress text from `files_inspected`/`entry_count` and `poll.elapsedMs` elapsed clock; a
      `StatusBadge` for `status`; on `timed-out`, a "still running on the server" `Notice`; on a poll
      `problem`/`error`, a `Notice` (parsed via `parseProblem`) and polling stops (via `retry:false`). On terminal
      `succeeded`: summary stating N datasets created from `result_dataset_ids.length` (do not list object keys).
      On terminal `failed`: render the typed `failure` object (`code`/`detail` when present) plus the `issues[]`
      list (`code`, `severity`, `message`, `suggestion?`, `dataset?`, `variable?`, `field_path?`) — mirror
      `ExecutionPanel`'s failure Notice. On terminal `cancelled`: a neutral `Notice` stating no datasets were
      created. Expose the current `status` and the terminal state to the parent via props callbacks
      (e.g. `onStatus(status)` / `onTerminal(response)`) so the dialog can gate the cancel control and fire
      invalidation; alternatively lift the poll into the dialog — but keep the shared `useOperationPoll` as the
      single polling mechanism. Never display partial success.
      Files: `<FE>\src\components\workbench\raw-bulk-import-status.tsx`
      Verify: `npm run typecheck` passes. Behavior covered by step 6.

- [ ] 5. Create the dialog container — the single stateful unit implementing the phase state machine.
      Props: `{ rawId: string; studyId: string; open: boolean; onOpenChange: (open: boolean) => void }`. Hold a
      discriminated phase: `select | uploading | author | submitting | polling | <terminal>`. Reset to `select`
      and clear uploaded files/rows/errors in a `React.useEffect(..., [open])` (mirror `DatasetCreateDialog`).
      Phase wiring:
      (a) `select`: `FileDropzone` with `multiple`; list pending files (name, size). "Upload files" calls
      `useCreateSourceFilesBulk().mutateAsync({ studyId, data: { files: picked as unknown as string[] } })`;
      pending → `uploading`. On error → back to `select` with a top-level alert using the `uploadErrorMessage`
      (413/415) → `parseProblem().detail` fallback mapping; retain picked files.
      (b) on upload success → `author`, seeding rows via `seedRowsFromUpload(result.items)` and keeping
      `result.items` as the Select option source.
      (c) `author`: render `RawBulkImportTable`; run `validateRows` continuously; disable "Submit import" unless
      valid. On submit: `idempotency.begin()` then `useCreateDatasetImport({ request: idempotency.requestConfig })`
      `.mutateAsync({ rawId, data: buildImportRequest(rows) })`; → `submitting`.
      (d) on 202 → store `importId`, → `polling`, mount `RawBulkImportStatus`. On submit error: stay in `author`,
      retain all edits — 409/428 → `stalenessAlert(error)` top-level banner; 422 → map issues onto rows via a
      `mapProblemToFieldErrors`-style pass keyed by issue `dataset`/`field_path` to the matching row, else a
      top-level list; copy states the import is all-or-nothing (nothing created).
      (e) terminal `succeeded` → call `invalidateRawDataset(qc, rawId)` ONCE in a `useEffect` keyed on the terminal
      import id (like `ExecutionPanel`), show the success summary, offer "Close".
      (f) a "Cancel import" button is visible whenever the live `status` is non-terminal (`queued`/`running`),
      wired to `useCancelDatasetImport().mutateAsync({ importId })`; best-effort — on error show a `toast` and keep
      polling; on success the next poll reflects `cancelled`.
      Use `useQueryClient`, `useIdempotencyKey`, `toast` from `@/components/ui/sonner`, and `Loader2`.
      Files: `<FE>\src\components\workbench\raw-bulk-import-dialog.tsx`
      Verify: `npm run typecheck` and `npm run lint` pass.

- [ ] 6. Add the component/integration test for the dialog + table + status (mirror `-raw-ops-panels.test.tsx` /
      `-compile-execution-panels.test.tsx`: `installJsdomHarness`, `QueryClientProvider`, `vi.mock` the generated
      hook modules `@/api/generated/artifacts/artifacts` and `@/api/generated/raw/raw`, mock
      `@/components/ui/sonner`, stub `@/lib/invalidate`, and use fake timers for polling as in the reconcile/build
      tests). Import the component AFTER the mocks.
      Cover: select → upload → `author` seeds one row per returned file in order, each defaulting to its own source
      file; submit disabled while a row is invalid or has a duplicate code, enabled when valid; a 422 with `issues`
      maps to the right rows and retains edits; a 409/428 shows the staleness banner and retains edits; a 202 →
      polling renders and running progress uses `files_inspected`/`entry_count`; terminal `succeeded` shows the
      summary, reports `result_dataset_ids` count, and calls `invalidateRawDataset`; terminal `failed` renders the
      `failure` object + typed `issues[]`; the cancel control is visible only while non-terminal and calls
      `cancelDatasetImport`; assert no object-store key/internal path text ever renders.
      Files: `<FE>\src\components\workbench\-raw-bulk-import.test.tsx`
      Verify: `npx vitest run src/components/workbench/-raw-bulk-import.test.tsx` — all cases pass.

- [ ] 7. Wire the dialog into `DatasetsPanel`: import `RawBulkImportDialog`, add `const [bulkOpen, setBulkOpen] =
      React.useState(false)`, add a `Button size="sm" variant="outline"` ("Bulk upload", e.g. with an
      `Upload`/`FileUp` `lucide-react` icon) in the existing `PageHeader actions` next to "New dataset", and render
      `<RawBulkImportDialog rawId={rawId} studyId={studyId} open={bulkOpen} onOpenChange={setBulkOpen} />` beside
      the existing `DatasetCreateDialog`. Do not change the `datasets` tab shape in `$rawId.tsx` (the dialog mounts
      inside the panel, not as a new tab).
      Files: `<FE>\src\components\workbench\datasets-panel.tsx`
      Verify: `npm run typecheck` passes; `npx vitest run src/components/workbench/-datasets-panel.test.tsx` still
      passes (the header button is additive — update that test only if it asserts the exact set of header actions).

- [ ] 8. Export the new public component from the workbench barrel (match the existing convention — export the
      dialog and its props type; the table/status/helpers are internal and need not be exported).
      Add `export { RawBulkImportDialog } from './raw-bulk-import-dialog'` and
      `export type { RawBulkImportDialogProps } from './raw-bulk-import-dialog'`.
      Files: `<FE>\src\components\workbench\index.ts`
      Verify: `npm run typecheck` passes.

- [ ] 9. Full verification pass from `<FE>`: `npm run typecheck`, then `npm run lint`, then `npm run test`.
      All must be clean/green. Confirm no file under `<FE>\src\api\generated\` was modified (`git -C
      e:\Work\EDETEK\Python\aurinara\.worktrees\raw-bulk-upload-ui status --short frontend/src/api/generated`
      shows nothing).
      Files: none (verification only).
      Verify: `npm run typecheck && npm run lint && npm run test` — all succeed; generated dir unchanged.

## Suggested order rationale

1→2 establish and prove the pure helpers (validation + request builder) with no React, so the dialog can rely on
them. 3 and 4 build the presentational pieces the dialog composes. 5 assembles the state machine on top of 1/3/4.
6 tests the composed flow. 7/8 integrate it into the panel and barrel. 9 is the final gate. Each step leaves the
tree buildable: steps 1,3,4 add self-contained modules; the dialog (5) is only imported by the panel in step 7,
so the barrel/panel compile cleanly once 5 exists.

## Notes / assumptions

- The design referenced a `Checkbox` primitive, but none exists in `@/components/ui`. Decision: use the native
  `<input type="checkbox" className="size-4">` pattern already established in `artifacts-panel.tsx` — no new
  dependency, consistent with the repo.
- The bulk-upload body type is `{ files: string[] }` in the generated model, but orval's `createSourceFilesBulk`
  appends real `File` objects to `FormData`. Pass `File[]` cast as `unknown as string[]`, mirroring the existing
  `useCreateSourceFile` call in `datasets-panel.tsx` (`file: file as unknown as string`).
- `expected_raw_revision` is intentionally omitted in R1 (optimistic-concurrency hook left for later), per the
  design's out-of-scope list.
- Poll adapter uses `retry: false` so a `problem+json` surfaces immediately and halts polling, matching
  `ExecutionPanel`.
