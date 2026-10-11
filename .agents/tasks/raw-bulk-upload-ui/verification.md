# Verification — Raw bulk-upload UI (frontend-only)

Scope: FRONTEND ONLY. No backend/python suites were run. All work is inside the
worktree `e:\Work\EDETEK\Python\aurinara\.worktrees\raw-bulk-upload-ui` under
`frontend/`. The orval-generated client under `frontend/src/api/generated/` was
NOT regenerated or hand-edited (`git status --short frontend/src/api/generated`
reports no changes).

## Commands run (from `frontend/`)

Script names were read from `frontend/package.json` (`lint`, `typecheck`,
`build`, `test`). `node_modules` was absent in the worktree, so dependencies
were installed first (`npm install`). The test runner was invoked via the local
binary (`node node_modules/vitest/vitest.mjs run`) because the pinned
`vitest@2.1.9` is the `test` script's resolver; this is equivalent to
`npm run test` (`vitest run`).

| Step | Command | Result |
| --- | --- | --- |
| Install deps | `npm install --no-audit --no-fund` | 741 packages added |
| Lint | `npm run lint` (`eslint .`) | PASS — 0 errors, 10 warnings (all pre-existing `react-refresh/only-export-components` in unrelated `ui/*` and other `workbench/*` files; none in the new files) |
| Typecheck | `npm run typecheck` (`tsc --noEmit`) | PASS — 0 errors |
| Build | `npm run build` (`tsc -b && vite build`) | PASS — built in ~18s |
| Tests (new helper unit) | `node node_modules/vitest/vitest.mjs run src/components/workbench/raw-bulk-import.test.ts` | PASS — 18/18 |
| Tests (new dialog component) | `node node_modules/vitest/vitest.mjs run src/components/workbench/-raw-bulk-import.test.tsx` | PASS — 10/10 |
| Tests (full suite) | `node node_modules/vitest/vitest.mjs run` (== `npm run test`) | PASS — 29 files, 321/321 tests, exit 0 |

## New / changed files

New (all under `frontend/src/components/workbench/`):

- `raw-bulk-import.ts` — pure helpers: `CODE_PATTERN`, `validateRows`,
  `rowsAreValid`, `seedRowsFromUpload`, `buildImportRequest`.
- `raw-bulk-import-table.tsx` — editable entry table (phase 2).
- `raw-bulk-import-status.tsx` — inline status/polling panel (phase 3).
- `raw-bulk-import-dialog.tsx` — two-phase dialog state machine (public export).
- `raw-bulk-import.test.ts` — pure-helper unit tests (18 cases).
- `-raw-bulk-import.test.tsx` — dialog component/integration tests (10 cases).

Changed:

- `datasets-panel.tsx` — added a "Bulk upload" header button + mounted
  `RawBulkImportDialog` next to the existing "New dataset" dialog.
- `index.ts` — barrel export of `RawBulkImportDialog` + its props type.
- `-datasets-panel.test.tsx` — stubbed the newly mounted bulk-import dialog
  (mirroring the existing variables/preview panel stubs) so the panel's own
  flow tests do not pull in the bulk hooks this file's mocks omit. The header
  button is additive and the existing `/new dataset/i` lookups are unaffected.

## Behavior coverage (per the test suite)

- Phase 1 → 2: `createSourceFilesBulk` happy path uploads the picked files and
  seeds one authoring row per returned file in order; a 413 upload failure
  surfaces a top-level alert and retains the picker.
- Phase 2: client-side code-pattern validation (`^[A-Za-z][A-Za-z0-9_]{0,63}$`)
  and intra-batch duplicate-code detection gate the Submit button before any
  request is sent.
- Submit: `createDatasetImport` sends the `{ schema_version:'1.0.0', entries }`
  envelope in row order with a syntactically valid `Idempotency-Key`; a 422 maps
  issues onto the matching rows and a 409 shows the staleness banner, both
  retaining edits.
- Phase 3: `getDatasetImport` polling transitions queued → running → succeeded,
  reports the created-dataset count, and fires `invalidateRawDataset` once on
  success; a `failed` terminal renders the typed `failure` object plus per-entry
  `ValidationIssue`s and does NOT invalidate; the cancel control is shown while
  non-terminal and calls `cancelDatasetImport`.

## Constraints honored

- Generated client consumed as-is (no regen/hand-edit; generated dir unchanged).
- Import is all-or-nothing — no partial-success copy; only `succeeded`
  invalidates the dataset list.
- No object-store keys or internal paths are rendered (source files are shown by
  `filename`/`media_type` only; the import response exposes none).
- No new npm dependencies; reused existing UI primitives, `FileDropzone`,
  `useOperationPoll`, `useIdempotencyKey`, `parseProblem`/`stalenessAlert`, and
  the `StatusBadge`/`Notice` patterns.
