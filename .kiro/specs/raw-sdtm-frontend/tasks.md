# Implementation Plan: Raw and SDTM Frontend

## Overview

This plan converts the Raw and SDTM frontend design into incremental, test-driven coding steps for the React 18 + TypeScript + Vite app in `frontend/`. It starts by regenerating the stale Orval typed client (every screen depends on the typed hooks), adds the two new browser-only dependencies, then builds the shared cross-cutting transport layer before any screen. Raw screens come next, then the SDTM screens (including the React Flow Derivation Plan graph editor), and each screen's tests are co-located with its implementation so there is no orphaned, un-wired code.

The design document declares property-based testing is not appropriate for this UI/transport feature and intentionally omits a Correctness Properties section. Accordingly this plan uses Vitest + React Testing Library + MSW example/boundary tests and a build-time typed-hook contract check instead of property tests. All test-related sub-tasks are marked optional with `*`. This is frontend-only work against the fixed Phase 3 backend contract; no backend route, OpenAPI shape, or migration is touched.

## Tasks

- [x] 1. Regenerate the typed Orval client and add new client dependencies
  - [x] 1.1 Regenerate the Orval client for the Phase 3 Raw/SDTM surface
    - Run `npm run api:export` (`scripts/export-openapi.mjs`) to boot FastAPI and write `frontend/openapi.json`; confirm it exits without error (precondition for regeneration)
    - Run `npm run api:generate` (`orval --config orval.config.ts`, `tags-split` + `clean: true`) to regenerate `src/api/generated/**`, producing per-tag hooks for Raw (dataset, variable, initialize, preview, validate, reconcile, artifacts) and SDTM (input-selection, raw-context, specification, derivation-plan, lineage, validate, compile, execute, define, acrf, csdrg) plus shared `model/` types
    - Verify `src/api/generated/raw/raw.ts` and `src/api/generated/sdtm/sdtm.ts` expose the full typed hook set and `getXQueryKey` helpers
    - _Requirements: 1.1, 1.2, 1.3, 1.5_
  - [x] 1.2 Add and pin the new browser-only dependencies
    - Add `@xyflow/react` (React Flow) pinned to an exact version to `frontend/package.json` and import its stylesheet `@xyflow/react/dist/style.css` once at the app entry
    - Add `@dnd-kit/core` and `@dnd-kit/sortable` pinned to exact versions
    - Confirm no backend/OpenAPI/Orval change results from these additions
    - _Requirements: 1.3_
  - [x] 1.3 Build-time typed-hook contract check
    - Run `npm run typecheck` (`tsc --noEmit`) after `npm run api:sync`; confirm it passes and that referencing a non-existent operation would fail compilation (demonstrating a build-time type error rather than an untyped runtime call)
    - _Requirements: 1.5_

- [x] 2. Extend the shared transport helpers (requests + problems)
  - [x] 2.1 Wire `lib/requests.ts` idempotency/If-Match helpers to real triggers
    - Confirm/extend `ifMatchRequest(revision)` (emits `If-Match: "revision-{N}"`, retains `Content-Type`) and `idempotentRequest()` (emits a UUID `Idempotency-Key`, retains `Content-Type`); ensure the key is generated once per operation attempt (via a ref) and held stable across automatic retries
    - _Requirements: 21.1, 21.2_
  - [x] 2.2 Write unit tests for request header helpers
    - `ifMatchRequest(n)` emits the exact header and retains `Content-Type`; `idempotentRequest()` emits a syntactically valid UUID; the key is identical across simulated retries of one attempt and differs across distinct attempts
    - _Requirements: 21.1, 21.2_
  - [x] 2.3 Write unit tests for problem mapping (reuse `lib/problems.ts`)
    - `stalenessAlert` returns the right sentence for 412/428/409-by-code; `mapProblemToFieldErrors` splits `issues[]`/`errors[]` into field vs form buckets
    - _Requirements: 21.3, 21.4, 21.5_

- [x] 3. Build the shared cross-cutting hooks
  - [x] 3.1 Implement `useOperationPoll` (`src/hooks/use-operation-poll.ts`)
    - Wrap a generated "get operation" query with `refetchInterval` and a wall-clock deadline; return the configured interval while non-terminal and within timeout, `false` once terminal/timed-out; expose `phase` (`idle`/`polling`/`terminal`/`timed-out`/`error`), final resource, and `problem`
    - Support per-call config: 1-5s interval with 120s cap (Raw reconcile/artifacts, SDTM validate/compile/execute) and fixed 2s with 300s cap (aCRF/Define/cSDRG builds, Define reconcile); stop and surface `title`/`detail` on a `problem+json`
    - _Requirements: 7.2, 8.3, 14.1, 16.2, 17.7, 18.6, 18.7, 19.5_
  - [x] 3.2 Implement `useDownload` (`src/hooks/use-download.ts`)
    - Call `AXIOS_INSTANCE` directly with `responseType: 'blob'` (inheriting base URL + bearer) for Specification `export?format=json|xlsx`, Define `render?version=2.0|2.1` XML, and artifact `/download`; trigger a browser save via object-URL anchor for binary, return text for the XML preview
    - _Requirements: 1.4, 8.4, 11.6, 18.5_
  - [x] 3.3 Implement `useCursorList` helper
    - Hold the current `after` cursor in state, request `limit` clamped to 1-50 (default 50), accumulate `items`, expose `loadMore()` enabled while `has_more`
    - _Requirements: 2.1, 9.1_
  - [x] 3.4 Write unit tests for `useOperationPoll` and `useCursorList`
    - Fake-timers test: polls at the configured interval, stops on terminal, enters `timed-out` at the deadline, stops and surfaces a problem body; cursor list clamps limit and paginates with `next_cursor` while `has_more`
    - _Requirements: 7.2, 8.3, 2.1_

- [x] 4. Build the shared reusable components
  - [x] 4.1 Implement `WorkbenchDetailShell` and study-scope gating
    - Fetch the aggregate, render `DetailHeader` (code, name, status, revision) + shadcn `Tabs`, expose the aggregate `revision`/ETag to child panels via context; gate every list/detail query on `enabled: !!currentStudyId`, render the shared `EmptyState` and issue no request when no study is selected; guard that the loaded aggregate's `study_id` matches the selected study
    - _Requirements: 2.2, 9.3, 9.4, 21.1_
  - [x] 4.2 Implement `IssueList`
    - Render the common issue model (code, severity, message, suggestion, entity type/id, field path, dataset, variable) with a per-severity count summary and an empty state
    - _Requirements: 6.2, 14.3_
  - [x] 4.3 Implement `OperationRunner`, `ArtifactList`, and `DownloadButton`
    - `OperationRunner`: generic trigger + `useOperationPoll` + render-result widget; distinguish `failed` terminal (render typed failure, present no artifact/output) from client `timed-out` (notice naming the run/build); `ArtifactList` + `DownloadButton` list produced artifacts and download via `useDownload`
    - _Requirements: 8.4, 8.5, 14.1_
  - [x] 4.4 Implement `StalenessBanner` and `AlignmentBanner`
    - Persistent notices for `dependency_refresh_required`, `input_refresh_required`, and plan `misaligned` states, with the ability to disable the operation controls they guard
    - _Requirements: 10.5, 12.4, 20.5_
  - [x] 4.5 Implement `FileDropzone` and the dnd-kit wrappers
    - `FileDropzone`: reusable drop-target wrapping a click-to-browse `<input type="file">` (native HTML5 file-drop); `SortableList`/`DraggableItem`/`DropTarget`: thin dnd-kit wrappers giving list reordering and source-to-target transfer a consistent, accessible shape with keyboard-sensor + numeric/explicit-control fallbacks; every DnD action produces the identical typed request as its fallback and never introduces a free-text code path
    - _Requirements: 3.2, 21.1_
  - [x] 4.6 Implement `lib/invalidate.ts` query-key invalidation helpers
    - Group per-aggregate invalidation so each mutation `onSuccess` invalidates the affected aggregate key and its dependent collection keys (Raw workbench/dataset/variable; SDTM sub-resource + aggregate + lineage/raw-context)
    - _Requirements: 21.6_
  - [x] 4.7 Write component tests for shared components
    - Study-scope gating renders empty state and issues no request when `currentStudyId` is null; `IssueList` renders fields + per-severity counts + empty state; `OperationRunner` renders terminal/failed/timeout states; banners disable guarded controls; jsdom harness installs `ResizeObserver` + element-dimension mocks and dnd-kit pointer/keyboard sensors
    - _Requirements: 2.2, 9.4, 6.2, 14.3, 10.5, 12.4, 20.5_

- [x] 5. Raw workbench list, create, and detail
  - [x] 5.1 Convert `_app/raw.tsx` to `raw/index.tsx` list + create
    - Cursor list via `useListRawAggregates` + `useCursorList`; create via `ResourceFormDialog` + `jsonRequest()` through `useCreateRawAggregate`, refresh list on `201`; on a `problem+json` show `title`/`detail`, retain form values, do not refresh
    - _Requirements: 2.1, 2.2, 2.3, 2.4_
  - [x] 5.2 Add `raw/$rawId.tsx` workbench detail (tabbed)
    - `WorkbenchDetailShell` over `useGetRawAggregate`; name/status edit via `usePatchRawAggregate` with `ifMatchRequest(revision)`; 412 concurrency message + discard stale edit + reload current revision before retry; 428 reload for fresh ETag before resubmit; tabs Datasets/Dependencies/Validation/Reconciliation/Artifacts
    - _Requirements: 2.5, 2.6, 2.7, 2.8_
  - [x] 5.3 Write component tests for Raw list/create/detail
    - Cursor pagination requests limit 1-50 and follows `next_cursor` while `has_more`; create success refreshes, problem retains form; conditional edit sends `If-Match`, 412 shows concurrency + reload, 428 refreshes before retry
    - _Requirements: 2.1, 2.3, 2.4, 2.5, 2.6, 2.7_

- [x] 6. Raw datasets and source-file bindings
  - [x] 6.1 Implement the Datasets panel
    - List via `useListRawDatasets` ordered by dataset code; source-file upload via `useCreateSourceFile` (multipart) through a `FileDropzone` (drag or browse), then bind; create via `useCreateRawDataset` with code/label/source-file id; rebind via `usePatchRawDataset` with `ifMatchRequest`; retire via `useRetireRawDataset` behind a `ConfirmDialog` naming the dataset
    - 409 `duplicate_raw_dataset_code` uniqueness message + retain values; 413/415 upload size/media-type message + retain dataset form (on both drop and browse); 412 rebind/retire concurrency + reload before retry
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8_
  - [x] 6.2 Write component tests for the Datasets panel
    - Dropped and browsed file issue identical multipart `POST` with the same 413/415 handling; duplicate-code retains form; rebind/retire send `If-Match` and surface the 412 reload path; retire requires confirmation naming the dataset
    - _Requirements: 3.2, 3.3, 3.5, 3.6, 3.7, 3.8_

- [x] 7. Raw variables, initialization, and preview
  - [x] 7.1 Implement the Variables panel
    - List via `useListRawVariables` ordered by ordinal; full metadata create (`useCreateRawVariable`) and edit (`usePatchRawVariable` with `ifMatchRequest`); delete (`useDeleteRawVariable`) behind a `ConfirmDialog` naming the variable; ordinal reorder via `SortableList` (dnd-kit) with numeric/keyboard fallback, each reorder persisting through `usePatchRawVariable` with `ifMatchRequest`; initialize via `useInitializeRawVariables` with the dataset ETag, show created/filled counts and refresh the list
    - 409 `duplicate_raw_variable` uniqueness message + retain values; initialize 412/428 reload dataset revision for fresh ETag before retry
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7_
  - [x] 7.2 Implement the Preview panel
    - `usePreviewRawDataset` with optional column selection; client clamps limit to 1-200 and offset to >= 0 before sending; render columns/rows + offset/limit/total; zero-row message with counts still shown; do not persist/cache rows beyond the view lifetime
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_
  - [x] 7.3 Write unit tests for clamping helpers
    - `clampLimit(n)`: below 1 -> 1, above 200 -> 200, in-range unchanged (0, 1, 200, 201); `clampOffset(n)`: negative -> 0 (-1, 0)
    - _Requirements: 5.2, 5.3, 13.2_
  - [x] 7.4 Write component tests for Variables and Preview
    - Reorder drop and keyboard/numeric fallback issue identical `PATCH` with `If-Match`; duplicate-variable retains form; initialize shows created/filled and refreshes, 412/428 reload path; preview sends clamped params, renders rows + offset/limit/total, zero-row message, no persistence after unmount
    - _Requirements: 4.3, 4.4, 4.6, 4.7, 5.1, 5.4, 5.5, 5.6_

- [x] 8. Raw validation, reconciliation, artifacts, and dependencies
  - [x] 8.1 Implement the Raw Validation panel
    - `useValidateRaw` returns a synchronous `200` ValidationRun -> render status + per-severity counts + `IssueList` (empty state when none); `failed` shows a persistent block notice; open-by-id via `useGetValidationRun`, 404 shows a not-found notice without stale content
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5_
  - [x] 8.2 Implement the Raw Reconciliation panel
    - `useReconcileRaw` with expected current revision + `Idempotency-Key`; on `202` poll `useGetReconciliationRun` at 1-5s to terminal with a 120s cap + timeout notice; 409 `stale_raw_reconciliation_input` message + reload action re-fetching current revision; render per-severity counts + full issue list; a poll `problem+json` surfaces `title`/`detail` and stops polling
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_
  - [x] 8.3 Implement the Raw Artifacts panel
    - Fixed client type constant `['raw_dependency_manifest','raw_metadata_json','raw_data_dictionary_xlsx','raw_validation_report_json']`; submit disabled while none selected; `useCreateRawArtifacts` with expected input fingerprint + `Idempotency-Key`; on `202` poll `useGetArtifactBuild` at 1-5s/120s via `OperationRunner`; on `completed` list artifacts with `DownloadButton`; `failed` shows typed failure, no download
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5_
  - [x] 8.4 Implement the Raw Dependencies panel
    - Selection view via `useGetRawDependencies`; replace via `useReplaceRawDependencies` `PUT` with the aggregate ETag; 422 `dependency_selection_invalid`/`dependency_selection_incomplete` render each incompatibility (message + suggestion); 412 concurrency + refresh before retry; `dependency_refresh_required` banner disables start-operation controls
    - _Requirements: 20.1, 20.2, 20.3, 20.4, 20.5_
  - [x] 8.5 Write component tests for Raw validation/reconcile/artifacts/dependencies
    - Synchronous validation renders counts/issues/empty/failed-notice and 404-by-id; reconcile polls to terminal/timeout, 409 stale reload; artifacts restrict to four types, disable submit when none, poll to terminal, failed shows no download; dependencies 422 issue list, 412 refresh, refresh-required disables controls
    - _Requirements: 6.1, 6.3, 6.5, 7.2, 7.3, 8.2, 8.3, 8.5, 20.3, 20.4, 20.5_

- [x] 9. Checkpoint - Raw screens
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. SDTM workbench list, create, and detail shell
  - [x] 10.1 Convert `_app/sdtm.tsx` to `sdtm/index.tsx` list + create
    - Cursor list via `useListSdtmAggregates` + `useCursorList`; create via `useCreateSdtmAggregate`, refresh on success; on a `problem+json` show `title`/`detail` and retain form input; empty-state when no study and no request
    - _Requirements: 9.1, 9.2, 9.4, 9.5_
  - [x] 10.2 Add `sdtm/$sdtmId.tsx` tabbed workbench detail shell
    - `WorkbenchDetailShell` over `useGetSdtmAggregate`; single aggregate ETag source for all conditional writes; tabs individually reachable via a `?tab=` search param (Input selection, Specification, Derivation plan, aCRF, Define, cSDRG, Validation, Compile & artifacts, Execution, Dependencies)
    - _Requirements: 9.3_
  - [x] 10.3 Write component tests for SDTM list/create/detail shell
    - Cursor list, create refresh/problem retain, study-scope empty state; each tab reachable by `?tab=` so refresh/links land on the right section
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5_

- [x] 11. SDTM input selection and Specification
  - [x] 11.1 Implement the Input selection panel
    - `useReplaceSdtmInputSelection` `PUT` with raw_id, Raw revision, successful validation-run id, source-file artifact ids+checksums, dependency fingerprint, aggregate ETag; display current selection (`useGetSdtmInputSelection`) with revision/state and resolved context (`useGetSdtmRawContext`); 422 `sdtm_raw_artifact_invalid`/`sdtm_raw_validation_invalid` render `detail` + `issues[]`; `input_refresh_required` persistent notice; 412 concurrency + reload action re-fetching current aggregate revision
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6_
  - [x] 11.2 Implement the Specification panel
    - View current via `useGetSdtmSpecification` (revision + schema version); 404 `sdtm_specification_required` unsaved empty state; save via `useReplaceSdtmSpecification` with aggregate ETag; import via `FileDropzone` through `useImportSdtmSpecification` with ETag + `Idempotency-Key`; variable ordering via `SortableList` persisting through the save `PUT`; 422 `sdtm_specification_import_invalid` renders `detail` + `issues[]`; export via `useDownload` with `format=json|xlsx`; 412 reload current Specification revision before retry
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7_
  - [x] 11.3 Write component tests for input selection and Specification
    - Input-selection save sends the full pinned body + aggregate ETag, 422 variants render detail + issues, input_refresh_required banner, 412 reload; Specification 404 empty state, save ETag, import dropzone+browse parity with ETag+Idempotency-Key, 422 import issues, export calls the download bypass with base URL+bearer+responseType, 412 reload
    - _Requirements: 10.1, 10.4, 10.5, 10.6, 11.2, 11.4, 11.6, 11.7_

- [x] 12. SDTM Derivation Plan graph editor
  - [x] 12.1 Implement `planToGraph`/`graphToPlan` pure adapters
    - Map the typed Derivation Plan body to React Flow `nodes`/`edges` and back; round-trip node layout from the backend when stored, otherwise deterministic auto-layout kept as client-only view state (never invented into the typed body); node `data` is always a typed operator-parameter object from `api/generated/model`
    - _Requirements: 12.1_
  - [x] 12.2 Implement the `DerivationPlanGraph` React Flow editor
    - Custom node types per typed Dataflow operator (`PLAN_OPERATOR_TYPES`) with typed ports + compact parameter summary; node inspector binds typed operator params from `api/generated/model`; the `derivation` node uses a structured typed-expression builder (never a free-text Python/R/SAS/SQL field); palette drag-to-create and port-to-port edge creation via React Flow built-in drag
    - `isValidConnection` enforces typed-model-permitted edges and rejects any edge that would introduce a cycle, refused at drop time with an inline reason and no request
    - _Requirements: 12.1, 12.2_
  - [x] 12.3 Wire plan save, alignment gating, and conflict handling
    - Save serializes graph via `graphToPlan` through `useReplaceSdtmDerivationPlan` with `ifMatchRequest(aggregate.revision)` and pinned `specification_revision` + `input_selection_revision`; display revision + pinned revisions + Alignment_State; 409 `stale_input_fingerprint` identifies the stale input (spec vs input-selection) and retains unsaved graph edits; `misaligned` renders the graph read-only (no palette/connect/reposition-save/inspector-write) with `AlignmentBanner` and disables validate/preview/compile/execute; 412 concurrency + reload
    - _Requirements: 12.1, 12.2, 12.3, 12.4_
  - [x] 12.4 Write tests for the graph editor
    - `isValidConnection` permits only typed-model-allowed edges and rejects cycle-creating edges (DAG preserved); palette drop adds a typed node; node inspector edits typed params and reflects them; `planToGraph`/`graphToPlan` round-trip an equivalent plan (positions view-only when no backend layout); save issues the `PUT` with aggregate `If-Match` + pinned revisions; 409 stale identifies the input and keeps on-canvas edits; misaligned renders read-only with banner; harness installs `ResizeObserver` + dimension mocks
    - _Requirements: 12.1, 12.2, 12.3, 12.4_

- [x] 13. SDTM derivation preview, lineage, and validation
  - [x] 13.1 Implement derivation preview and lineage
    - Preview via `usePreviewSdtmDerivationPlan` with optional domain selection, limit constrained to 1-200; render produced domain outputs + specification/plan/input-selection revisions; per-domain empty-result indication; 422 `sdtm_preview_domain_unknown` shows which domains were not produced; no caching beyond the view; inline plan validation via `useValidateSdtmDerivationPlan` showing status + IR fingerprint, problem leaves the displayed plan unchanged; lineage via `useGetSdtmLineage` rendered as a read-only React Flow graph (no palette/connect/inspector writes)
    - _Requirements: 12.5, 12.6, 12.7, 13.1, 13.2, 13.3, 13.4, 13.5, 13.6_
  - [x] 13.2 Implement the SDTM Validation panel
    - `useValidateSdtm` returns `202`; poll the returned validation-run via `useGetValidationRun` to a terminal status (`passed`/`failed`); render status + per-severity counts + full `IssueList` (code, severity, message, suggestion, entity type/id, field path, dataset, variable) + validator name/version; a request `problem+json` renders `title`/`detail` + `issues[]`
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5_
  - [x] 13.3 Write component tests for preview, lineage, and validation
    - Preview sends constrained limit, renders outputs + revisions + per-domain empty, 422 unknown-domain list, no persistence; lineage renders read-only graph; validation polls to terminal, renders counts/issues/validator version, problem surfacing
    - _Requirements: 13.1, 13.3, 13.4, 13.5, 14.1, 14.2, 14.3, 14.4, 14.5_

- [x] 14. SDTM compile, artifacts, and execution
  - [x] 14.1 Implement the Compile & artifacts panel
    - `useCompileSdtm` with backend `python`/`r`/`sas` + expected input fingerprint + `Idempotency-Key`; on `202` poll `useGetArtifactBuild` to terminal via `OperationRunner`, list produced program artifacts on success; `failed` shows the typed failure object and no partial artifacts; 409 `backend_capability_missing` message; extra metadata/report artifact types via `useCreateSdtmArtifacts` with fingerprint + `Idempotency-Key`
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.5_
  - [x] 14.2 Implement the Execution panel
    - `useExecuteSdtm` with language, program artifact id, input artifact ids, validation-run id, pinned input-selection/specification/plan revisions, compiler fingerprint, expected input fingerprint, accepted limits, `Idempotency-Key`; on `202` poll `useGetExecutionRun` to terminal; render status/timing/resource metrics + logs (`useGetExecutionRunLogs`) + outputs (`useGetExecutionRunOutputs`); `runner_not_configured` keeps the generated program available; other failure shows the typed failure + any captured logs
    - _Requirements: 16.1, 16.2, 16.3, 16.4, 16.5_
  - [x] 14.3 Write component tests for compile and execution
    - Compile sends backend+fingerprint+Idempotency-Key, polls to terminal, failed shows typed failure + no partial artifacts, 409 backend_capability_missing; execution sends the full pinned body + limits, polls to terminal, renders metrics/logs/outputs, runner_not_configured keeps program available, other failure shows failure + logs
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 16.1, 16.2, 16.3, 16.4, 16.5_

- [x] 15. SDTM aCRF annotations, links, and coverage
  - [x] 15.1 Implement the aCRF panel
    - List via `useListAcrfAnnotations`; create via `useCreateAcrfAnnotation` with source PDF artifact id, page >= 1, normalized rect, aggregate ETag; client rect-bounds validation blocks submit and names the out-of-range field without issuing the request; edit/soft-delete via `usePatchAcrfAnnotation`/`useDeleteAcrfAnnotation` with the annotation ETag (delete behind explicit confirmation); link building via dnd-kit drag of a source SDTM variable onto a target annotation with an explicit "add link" fallback, issuing `useWriteAcrfLinks` with the annotation ETag; coverage via `useGetAcrfCoverage` showing total, unlinked annotations (count+list), unlinked SDTM variables (count+list), and non-current-revision links (count+list); build via `useCreateAcrfArtifacts` + `Idempotency-Key`, poll at 2s to terminal or 300s with a build-failure/timeout indication naming the build and no artifact presented
    - _Requirements: 17.1, 17.2, 17.3, 17.4, 17.5, 17.6, 17.7, 17.8_
  - [x] 15.2 Write unit tests for rectangle-bounds validation
    - Accept in-range rects; reject each out-of-range field and the `x+width > 1` / `y+height > 1` overflow cases returning the offending field; reject page < 1
    - _Requirements: 17.3_
  - [x] 15.3 Write component tests for the aCRF panel
    - Out-of-range rect blocks submit + field message + no request; valid create sends aggregate ETag; edit/delete/link send the annotation ETag; delete requires confirmation; link drag and the add-link fallback issue identical `useWriteAcrfLinks` with the annotation ETag; coverage renders the four count/list groups; 2s build poll to terminal/timeout naming the build
    - _Requirements: 17.2, 17.3, 17.4, 17.5, 17.6, 17.7, 17.8_

- [x] 16. SDTM Define lifecycle
  - [x] 16.1 Implement the Define panel
    - View model via `useGetDefine`; initialize via `useInitializeDefine` with aggregate ETag + expected Define revision + selected XPT artifact ids (selectable via dnd-kit drag-to-select with a checkbox fallback); save via `useReplaceDefine` with aggregate ETag; validate via `useValidateDefine` -> ValidationRun status/error+warning counts/full issue list; render via `useDownload` with `version=2.0|2.1` as a non-persisting XML preview; reconcile via `useReconcileDefine` with revision + fingerprint + `Idempotency-Key`, poll at 2s to terminal/300s; build via `useCreateDefineArtifacts` with version(s) + canonical fingerprint + `Idempotency-Key`, poll at 2s to terminal/300s; a failed/timeout run or build is identified with no artifact presented; 409 staleness refreshes the current Define model before retry
    - _Requirements: 18.1, 18.2, 18.3, 18.4, 18.5, 18.6, 18.7, 18.8, 18.9_
  - [x] 16.2 Write component tests for the Define panel
    - View/save/initialize/validate; render requests `version=2.0|2.1` via the download bypass and shows the XML preview; reconcile and build poll at 2s to terminal/timeout naming the run/build with no artifact on failure; 409 staleness refreshes the model; XPT drag-select and checkbox fallback issue identical initialize body
    - _Requirements: 18.1, 18.2, 18.4, 18.5, 18.6, 18.7, 18.8, 18.9_

- [x] 17. SDTM cSDRG lifecycle and SDTM dependencies
  - [x] 17.1 Implement the cSDRG panel
    - View via `useGetCsdrg`; initialize via `useInitializeCsdrg` with aggregate ETag + expected cSDRG revision + current Define revision + successful reconciliation run id; save via `useReplaceCsdrg` with aggregate ETag presenting the nine required narrative sections (`CSDRG_SECTIONS`) as editable text fields preserving user content without inferring/auto-populating narrative; validate via `useValidateCsdrg` treating any of the nine sections that is absent/whitespace-only as an error-severity issue; build via `useCreateCsdrgArtifacts` + `Idempotency-Key`, poll at 2s to terminal/300s with a build-failure/timeout indication naming the build and no artifact presented
    - _Requirements: 19.1, 19.2, 19.3, 19.4, 19.5, 19.6_
  - [x] 17.2 Implement the SDTM Dependencies panel
    - Mirror the Raw dependencies pattern: `useGetSdtmDependencies` selection view with revision/state; replace via `useReplaceSdtmDependencies` `PUT` with aggregate ETag; 422 issue list (message + suggestion); 412 refresh before retry; `dependency_refresh_required` banner disables start-operation controls
    - _Requirements: 20.1, 20.2, 20.3, 20.4, 20.5_
  - [x] 17.3 Write component tests for cSDRG and SDTM dependencies
    - Nine sections preserve typed content and never auto-populate; validate surfaces whitespace-only sections as error issues; build polls at 2s; dependencies 422 issue list, 412 refresh, refresh-required disables controls
    - _Requirements: 19.3, 19.4, 19.5, 20.3, 20.4, 20.5_

- [x] 18. Cross-cutting wiring, invalidation, and DnD parity
  - [x] 18.1 Wire query-key invalidation across all mutations
    - Apply `lib/invalidate.ts` to each mutation `onSuccess` so the affected aggregate key and its dependent collections (and SDTM lineage/raw-context when inputs change, and artifact/validation collections after completed `202` operations) reload current data; apply the uniform error handling (412/428/409-by-code, 413/415, 404, operation failure vs timeout) consistently across all screens
    - _Requirements: 21.3, 21.4, 21.5, 21.6_
  - [x] 18.2 Write component tests for invalidation and DnD-vs-fallback parity
    - Each successful mutation invalidates the aggregate key + dependent collection keys so dependent views refetch; for every DnD surface (source-file dropzone, Specification import dropzone, Define XPT drag-select, Raw/Specification variable reorder, aCRF link drag) the pointer drop and its keyboard/non-pointer fallback issue the identical typed request carrying the same `If-Match`/`Idempotency-Key` and surfacing the same `problem+json`; accessibility assertions verify every DnD action is operable without a pointer
    - _Requirements: 21.1, 21.2, 21.5, 21.6_
  - [x] 18.3 Finalize the build-time contract check in CI
    - Confirm CI runs `api:sync` + `typecheck` (`tsc --noEmit`) + `lint` + the Vitest suite; a screen referencing a non-existent operation fails compilation
    - _Requirements: 1.5_

- [x] 19. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional test tasks and can be skipped for a faster MVP; the design declares property-based testing is not appropriate here, so these are Vitest + RTL + MSW example/boundary/component tests plus the build-time typed-hook contract check.
- Every task references specific requirement sub-clauses for traceability.
- The first task regenerates the stale Orval client and adds the new pinned dependencies, since every screen depends on the typed hooks and the graph/DnD libraries.
- The shared cross-cutting layer (hooks + components) is built before any screen so screens stay declarative and no code is orphaned.
- Checkpoints after the Raw screens and at the end provide incremental validation.
- Component tests mock the generated hooks or the axios layer via MSW; poll-timing tests use fake timers; the harness installs the jsdom shims React Flow needs (`ResizeObserver`, element-dimension mocks) and dnd-kit pointer/keyboard sensors.
- This is frontend-only work against the fixed Phase 3 contract; no backend route, OpenAPI shape, or migration changes.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.3", "2.1", "2.3"] },
    { "id": 2, "tasks": ["2.2", "3.1", "3.2", "3.3"] },
    { "id": 3, "tasks": ["3.4", "4.1", "4.2", "4.4", "4.5", "4.6"] },
    { "id": 4, "tasks": ["4.3", "4.7", "5.1", "10.1"] },
    { "id": 5, "tasks": ["5.2", "5.3", "10.2", "10.3"] },
    { "id": 6, "tasks": ["6.1", "7.2", "7.3", "11.1", "11.2", "12.1"] },
    { "id": 7, "tasks": ["6.2", "7.1", "11.3", "12.2"] },
    {
      "id": 8,
      "tasks": ["7.4", "8.1", "8.2", "8.3", "8.4", "12.3", "13.1", "13.2"]
    },
    {
      "id": 9,
      "tasks": [
        "8.5",
        "12.4",
        "13.3",
        "14.1",
        "14.2",
        "15.1",
        "16.1",
        "17.1",
        "17.2"
      ]
    },
    { "id": 10, "tasks": ["14.3", "15.2", "15.3", "16.2", "17.3", "18.1"] },
    { "id": 11, "tasks": ["18.2", "18.3"] }
  ]
}
```
