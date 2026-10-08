# SDTM Derivation Plan bootstrap — final report

## The bug

The SDTM Derivation Plan tab showed "No derivation plan yet" with no way to
author a first plan. `GET /sdtms/{id}/derivation-plan` returning
`404 sdtm_derivation_plan_required` was handled by rendering only an
`EmptyState` and returning early; the `DerivationPlanGraph` editor only mounted
in a later branch guarded by a loaded `plan` object. Result: the editor could
only appear once a plan existed, but a plan could only be created through the
editor (chicken-and-egg).

## The change (frontend only)

File: `frontend/src/components/workbench/derivation-plan-panel.tsx`

A new fully-interactive "new-plan mode" was added. No backend, OpenAPI, or
generated client code was touched.

### How new-plan mode decides to render the editor

- `planRequired` = plan GET returned `404` with code
  `sdtm_derivation_plan_required`.
- Prerequisites are read from the already-present `useGetSpecification` /
  `useGetInputSelection` queries:
  - `currentSpecRevision = specQuery.data?.revision` (a current Specification is
    one that exists, i.e. GET 200).
  - `currentInputRevision = inputQuery.data?.state === 'current' ?
    inputQuery.data.revision : undefined` (matches the backend's
    `selection.state != "current"` gate in `put_plan`).
- `prerequisitesReady` = both revisions defined.
- `newPlanMode = planRequired && prerequisitesReady`.

When `planRequired && !newPlanMode`, the existing guidance empty state is kept
("Save a current Specification and Input Selection, then author the plan here").
When `newPlanMode` is true, the panel falls through to the same editor markup
used by the loaded-plan path, seeded with an empty canvas (`nodes`/`edges`
start empty; the re-seed effect's `if (!plan) return` leaves the canvas empty).
The editor is NOT read-only in new-plan mode (`misaligned` is false because
there is no misaligned loaded plan).

### How revisions are pinned on first save

`handleSave` was generalized to pin against either source:

- `pinnedSpecRevision  = plan?.specification_revision  ?? currentSpecRevision`
- `pinnedInputRevision = plan?.input_selection_revision ?? currentInputRevision`

so a loaded plan uses its own pinned revisions and a new plan pins against the
current Specification / Input Selection revisions. The save still calls the
existing `usePutPlan` with `If-Match` from `useWorkbench().ifMatch()` (the
aggregate ETag) and `graphToPlan(nodes, edges, { specificationRevision,
inputSelectionRevision, schemaVersion: '1.0.0' })`. The `describeStaleInput`
helper was updated to take a `{ specificationRevision, inputSelectionRevision }`
pair instead of a `PlanResponse`, so 409 attribution works in both modes.

### Preserved behavior

- Header/description, alignment pill, and all notices render in new-plan mode.
  The description shows a "New plan (unsaved)" line with the pinned current
  revisions instead of crashing on a missing `plan`.
- The nested `DerivationPreviewLineagePanel` (preview/validate/lineage) now
  renders only when a saved `plan` exists, since those endpoints operate on a
  saved plan.
- Loaded-plan behavior is unchanged: alignment gating (misaligned => read-only),
  409 `stale_input_fingerprint` (retain on-canvas edits), 412 concurrency notice
  + reload.
- After a successful first save, `onSuccess` invalidates the plan sub-resource;
  the refetch returns revision 1 and the re-seed effect (`seededRevision` ref,
  still `null` in new-plan mode) seeds the canvas from the saved plan,
  transitioning cleanly to the loaded-plan path.
- A backend 422 on save (e.g. zero nodes) surfaces via the existing
  `toast.error(parseProblem(err).detail ...)` path.

The component JSDoc was updated to document new-plan mode.

## Tests added/updated

File: `frontend/src/components/workbench/plan-graph/-derivation-plan-graph.test.tsx`

- Updated the `sdtmApi.input` stub type to carry an optional `state`, and the
  `beforeEach` default to `{ revision: 2, state: 'current' }`.
- Added a `DerivationPlanPanel new-plan mode` describe block:
  - 404 + current spec/input renders the interactive editor (palette + canvas
    present, no "No derivation plan yet", Save enabled).
  - 404 + input selection not current keeps the guidance empty state.
  - 404 + missing specification keeps the guidance empty state.
  - first save (after dropping one node) issues PUT pinned to the CURRENT
    spec/input revisions (5 / 9) with the aggregate `If-Match`.
  - backend 422 on save surfaces a toast.
- Existing loaded-plan, 409, and misaligned panel tests remain and pass.

## Commands run and results

From `frontend/`:

- `npm run typecheck` (tsc -b) — PASS (exit 0).
- `npm run test` (vitest run) — PASS: 26 test files, 283 tests passed.
- Targeted `npm run test -- src/components/workbench/plan-graph/-derivation-plan-graph.test.tsx`
  — PASS: 11 tests (including the 5 new new-plan-mode tests).
