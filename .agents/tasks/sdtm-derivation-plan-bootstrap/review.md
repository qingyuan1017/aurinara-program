# Author the first SDTM Derivation Plan from an empty canvas

The SDTM Derivation Plan tab was stuck in a chicken-and-egg: a `404 sdtm_derivation_plan_required` was rendered as a dead-end "No derivation plan yet" empty state with an early return, while the interactive `DerivationPlanGraph` editor only mounted behind a loaded `plan` object. A first plan could only be authored in the editor, but the editor only appeared once a plan existed. This change adds a "new-plan mode": when the plan GET 404s *and* a current Specification and current Input Selection both exist, the full interactive editor mounts over an empty canvas, and the first save pins the plan against the current spec/input revisions. The save path was generalized (not duplicated) so a loaded plan and a brand-new plan share one `handleSave`. The commit introduces `derivation-plan-panel.tsx` and its component tests as new files; it is frontend-only.

Watch for: nothing blocking. The implementation matches every acceptance criterion, reuses existing adapters/components/hooks, and the component tests cover cases (a)-(d). One cosmetic transient (header shows "New plan (unsaved)" for the brief window between a successful first save and the refetch landing) — `possible`, non-blocking.

**Verdict**: APPROVED

## High-level view

New-plan mode is gated conservatively. `newPlanMode = planRequired && prerequisitesReady`, where `prerequisitesReady` requires a current Specification (`specQuery.data?.revision` defined) and a current Input Selection (`inputQuery.data?.state === 'current'`). The latter mirrors the backend's `put_plan` gate that rejects a non-current selection, so the UI never enters interactive mode in a state the backend would reject. When prerequisites are not yet current, the existing guidance empty state is preserved via the `planRequired && !newPlanMode` early return.

The save path is unified rather than branched. `pinnedSpecRevision = plan?.specification_revision ?? currentSpecRevision` and the input equivalent let one `handleSave` serve both modes: a loaded plan uses its own pinned revisions, a new plan pins the current ones. `graphToPlan(nodes, edges, { specificationRevision, inputSelectionRevision, schemaVersion: '1.0.0' })` and the aggregate `If-Match` from `useWorkbench().ifMatch()` are identical across modes. The `describeStaleInput` helper was reshaped to take a `{ specificationRevision, inputSelectionRevision }` pair instead of a `PlanResponse`, so 409 attribution works in both modes.

New-plan mode tolerates the absent `plan` object everywhere it renders. Revision display, the alignment pill, both notice components, and the misaligned gate all read through `plan?.…` or state derived independently of `plan`. `misaligned` is `false` in new-plan mode because `plan?.state` is undefined, so the editor is interactive, not read-only. The nested preview/validate/lineage panel is correctly withheld (`{plan && …}`) since those endpoints operate on a saved plan.

The transition back to the loaded-plan path after the first save is clean. `onSuccess` invalidates the derivation-plan sub-resource key; the refetch returns revision 1; the re-seed effect — whose `seededRevision` ref is still `null` because it never ran in new-plan mode (`if (!plan) return`) — seeds the canvas from the saved plan. Since `planToGraph` reconstructs exactly what was just serialized, the just-authored nodes are not disturbed.

All loaded-plan behavior is present in this new file: misaligned ⇒ read-only (Save disabled, palette hidden, banner shown), 409 `stale_input_fingerprint` retains on-canvas edits and names the drifted input, 412 raises a persistent concurrency notice with a reload action that resets `seededRevision` and invalidates the plan key.

<details>
<summary>Issues (1)</summary>

1. **Transient "unsaved" header after first save** (`possible`, non-blocking) — between the first save resolving and the invalidated plan query refetching, `plan` is still `undefined`, so the header momentarily reads "New plan (unsaved)" despite the success toast. Purely cosmetic; no action required unless the flash is observed to be noticeable.

</details>

<details>
<summary>Details</summary>

### New-plan gating mirrors the backend PUT gate

The decision to enter interactive mode is `newPlanMode = planRequired && prerequisitesReady`, and `prerequisitesReady` is `currentSpecRevision !== undefined && currentInputRevision !== undefined`. `currentInputRevision` is only defined when `inputQuery.data?.state === 'current'`. This is the important detail: a non-current input selection (e.g. `input_refresh_required`) leaves `currentInputRevision` undefined, so `newPlanMode` stays false and the guidance empty state is kept. That matches the server contract — the backend's `put_plan` rejects a save when the selection is not current — so the client never offers an interactive canvas for a state the server would bounce. The two "keeps the guidance empty state" tests exercise exactly these branches (not-current input, and absent specification).

```
planRequired (404 sdtm_derivation_plan_required)
        │
        ├── prerequisitesReady?  ── no ──▶ guidance EmptyState (+ early return)
        │        (spec rev defined AND
        │         input state === 'current')
        │
        └── yes ──▶ newPlanMode ──▶ interactive editor, empty canvas, Save enabled
```

### Unified save path and 409 attribution across modes

`handleSave` guards on `pinnedSpecRevision === undefined || pinnedInputRevision === undefined` and returns early if neither a loaded plan nor current prerequisites supply revisions — so a save can never fire without something to pin. The pinned values resolve through `plan?.specification_revision ?? currentSpecRevision`, giving a loaded plan its own pinned revisions and a new plan the current ones. The `first save issues PUT pinned to the CURRENT spec/input revisions` test confirms a new plan pins 5/9 (the current values) with the aggregate `If-Match`, and the loaded-plan `save` test confirms a loaded plan pins 3/2 (its own). The `describeStaleInput` signature change to a `PinnedRevisions` pair is what lets 409 attribution name the drifted input in either mode without reading a `PlanResponse` that may not exist.

### Absent-plan tolerance

Every render site that could dereference `plan` is guarded. The header branches on `plan ?` for the revision line versus the "New plan (unsaved)" line; `alignmentState = plan?.state` and `misaligned = isMisaligned(alignmentState)` are both safe on undefined (`isMisaligned` returns false for null/undefined); the preview/lineage panel is gated behind `{plan && …}`. The three new-plan render guards (`planRequired && !newPlanMode`, `query.isError && !newPlanMode`, `!plan && !newPlanMode`) each exclude new-plan mode so the fall-through to the editor is reached only when intended. No unguarded `plan.` access remains in the new-plan path.

### Clean transition after first save

The re-seed effect short-circuits on `if (!plan) return`, so in new-plan mode `seededRevision.current` is never written and stays `null`. After the first save, `onSuccess` → `invalidateSdtmSubResource(qc, 'derivation-plan', sdtmId)` invalidates the plan key (verified against `invalidate.ts`, which maps `'derivation-plan'` to `getGetPlanQueryKey`). The refetch returns revision 1; the effect sees `seededRevision.current (null) !== plan.revision (1)` and seeds from `planToGraph(planBodyFromResponse(plan))`. Because `planBodyFromResponse` reads the same `nodes`/`edges` payload that was just serialized by `graphToPlan`, the seeded canvas equals what the user authored — no lost work, no duplicate state. The only observable artifact is a brief window where `plan` is undefined before the refetch resolves, during which the header shows "New plan (unsaved)" even though the save succeeded. Cosmetic, flagged as `possible`.

### Preserved loaded-plan behavior

The new file carries the full loaded-plan contract, and the tests prove it:
- misaligned ⇒ read-only: `DerivationPlanGraph` receives `readOnly={misaligned}`; Save is `disabled={put.isPending || misaligned}`; the `AlignmentBanner` renders; the palette is hidden (`!readOnly &&`). The misaligned test asserts the banner, the disabled Save, and the absent `operator palette` landmark.
- 409 `stale_input_fingerprint`: caught, sets the stale-input notice via `describeStaleInput`, and `return`s *without* re-seeding, so on-canvas edits survive. The 409 test asserts the Specification is named as drifted and the loaded nodes `read1`/`write1` remain on canvas.
- 412: sets a persistent `concurrency` notice; `reloadCurrentRevision` resets `seededRevision.current = null` and invalidates the plan key so the editor re-seeds from the refetched revision.

### Reuse and scope

The panel reuses `DerivationPlanGraph`, `DerivationPreviewLineagePanel`, `AlignmentBanner`/`isMisaligned`, `graphToPlan`/`planToGraph`, `usePutPlan`, `useGetSpecification`/`useGetInputSelection`/`useGetPlan`, `useWorkbench().ifMatch()`, `invalidateSdtmSubResource`, and `parseProblem`/`stalenessAlert` — no reinvention. The component JSDoc documents new-plan mode explicitly (the "New-plan mode:" paragraph). The commit touches only `derivation-plan-panel.tsx`, its test file, and the task report; no backend route, no OpenAPI, no `frontend/src/api/generated/` file is modified. All field accesses (`SpecificationResponse.revision`, `InputSelectionResponse.revision/state`, `PlanResponse.specification_revision/input_selection_revision/state/schema_version`) are backed by the generated model types.

### Verification evidence

Per the task I did not re-run the suites. `final-report.md` records, from `frontend/`: `npm run typecheck` (tsc -b) PASS; `npm run test` (vitest run) PASS with 26 files / 283 tests; and the targeted `-derivation-plan-graph.test.tsx` PASS with 11 tests including the 5 new new-plan-mode cases. The test file I read contains those 5 new cases plus the retained loaded-plan/409/misaligned cases, consistent with the recorded counts. The evidence is present and specific, leaving no articulable doubt that would justify a spot-check.

</details>

<details>
<summary>File map</summary>

- `frontend/src/components/workbench/derivation-plan-panel.tsx` — new panel; adds new-plan mode, generalized `handleSave`, `describeStaleInput` pair-based signature, absent-plan-tolerant render.
- `frontend/src/components/workbench/plan-graph/-derivation-plan-graph.test.tsx` — new/updated component tests; adds the `new-plan mode` describe block (cases a-d) and the `state` field on the input stub.
- `.agents/tasks/sdtm-derivation-plan-bootstrap/final-report.md` — coder's report with verification commands/results.

Full change: `git show b1a597d`.

</details>
