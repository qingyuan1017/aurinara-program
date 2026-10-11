# SDTM Derivation Plan — "cannot edit node in inspector" — findings

Read-only diagnosis. No code was changed.

## Summary answer

The inspector itself is wired correctly: when a node is selected its typed data is passed into `NodeInspector`, every field has a real `onChange`, and edits are written back to the controlled graph state. There is no missing-handler or by-value-only bug in the inspector.

The reason the inspector refuses input is almost certainly the **intentional alignment guard**. `DerivationPlanPanel` passes `readOnly={misaligned}` down through `DerivationPlanGraph` into `NodeInspector`, and `NodeInspector` disables every field when `readOnly` is true. `misaligned` is server-authoritative: it is true whenever the loaded plan's `state === 'misaligned'`. The backend flips a plan to `misaligned` as soon as the SDTM **Specification** or **Input Selection** is re-saved (see routes cited below). So a user who edited the spec/input after authoring the plan will find the whole plan editor — palette, edge creation, node dragging, delete, **and the inspector** — locked until a new validated, re-aligned plan revision is saved.

Ranked conclusions:

1. **Most likely (intended behavior, not a defect):** the plan is in `misaligned` state, so `readOnly` is true end-to-end and the inspector is disabled by design. The fix is a product/UX one (make the reason obvious at the inspector), not a code bug.
2. **Less likely (would be a real defect):** the node never actually becomes "selected," so `selectedNode` stays `null` and the inspector shows its empty placeholder rather than editable fields. This is a different symptom ("no fields at all" vs "fields are greyed out") and the wiring looks correct, but it is the only plausible code-level failure mode and is listed with what to check.

The two symptoms are distinguishable: misalignment → fields render but are **greyed/disabled** and a "read-only while misaligned" note + the AlignmentBanner are visible; selection failure → the inspector shows the **"Select a node on the canvas…" placeholder** with no fields.

## Evidence

### 1. Where selection state lives and how it reaches the inspector

`DerivationPlanGraphInner` owns the selection:

- `frontend/src/components/workbench/plan-graph/derivation-plan-graph.tsx`
  - `const [selectedId, setSelectedId] = React.useState<string | null>(null)`
  - `const selectedNode = nodes.find((node) => node.id === selectedId)?.data ?? null`
  - It is passed in: `<NodeInspector node={selectedNode} onChange={handleInspectorChange} readOnly={readOnly} />`

So the selected node's **typed `data`** is passed into the inspector. Answer to brief Q1: yes, selection state exists and is passed in.

`selectedId` is set from React Flow `select` node changes in `handleNodesChange`:

```
const sel = effective.find(change => change.type === 'select')
if (sel) setSelectedId(sel.selected ? sel.id : null)
```

### 2. Fields are controlled WITH onChange; they are gated only by `readOnly`

`frontend/src/components/workbench/plan-graph/node-inspector.tsx`:

- `NodeInspectorProps` has `node`, `onChange`, and `readOnly?: boolean` whose doc comment states: "Read-only mode (e.g. when the plan is misaligned) disables every field."
- Every reusable field passes `disabled={readOnly}` to the underlying control:
  - `TextField` → `<Input … disabled={readOnly} />`
  - `StringListField` → inputs and add/remove buttons all `disabled={readOnly}`
  - `JoinFields` / `CastFields` / `TerminologyFields` / `AggregateFields` → `Select … disabled={readOnly}`, inputs `disabled={readOnly}`
  - `FilterFields` / `AssertFields` / `DeriveFields` → `ExpressionBuilder`/`AssignmentList` receive `disabled={readOnly}`
  - `SequenceFields` numeric input → `disabled={readOnly}`
  - `EnumSelect` → `Select … disabled={readOnly}`

Answer to brief Q2: fields are **not** permanently disabled and are **not** missing onChange. They are controlled with a real `onChange` and are disabled **only** when `readOnly` is true. The unit test confirms both the editable path and the disabled path:

- `frontend/src/components/workbench/plan-graph/-derivation-plan-graph.test.tsx`
  - "edits a typed operator param and emits an updated typed node object" — typing into the raw-dataset field calls `onChange` once with the updated typed node.
  - "disables every field in read-only mode" — with `readOnly`, the input's `.disabled` is `true`.

### 3. The view/edit gate: `readOnly` traces to server-driven `misaligned`

`frontend/src/components/workbench/derivation-plan-panel.tsx`:

```
const alignmentState = plan?.state as AlignmentState | undefined
const misaligned = isMisaligned(alignmentState)
…
<DerivationPlanGraph … readOnly={misaligned} />
```

`frontend/src/components/workbench/alignment-banner.tsx`:

```
export function isMisaligned(state) { return state === 'misaligned' }
```

And `DerivationPlanGraph` forwards the same `readOnly` straight into `NodeInspector` (see §1). So:

`plan.state === 'misaligned'` → `misaligned === true` → `readOnly === true` → every inspector field `disabled`.

The panel's own doc comment states the design explicitly: "A `misaligned` Alignment_State renders the graph read-only (no palette, edge creation, reposition-to-save, or **inspector writes**)…". The panel also renders a visible hint next to Save: "The plan is read-only while misaligned." plus the `AlignmentBanner`.

Answer to brief Q3: **yes**, there is an edit gate, and it is the misalignment guard. It disables the inspector by design. Whether it is "a bug" depends on whether the plan is legitimately misaligned (see server evidence).

### 4. Server makes misalignment easy to trigger (why users hit this)

The backend flips the latest plan to `misaligned` whenever the Specification or Input Selection is re-saved, independent of the plan's own content:

- `src/app/sdtm/routes.py`
  - Input Selection save path: `plan = _handler(registry).latest_plan(session, workbench.id); if plan is not None: plan.state = "misaligned"` (around line 299-300).
  - `_save_specification(...)`: same `plan.state = "misaligned"` (around line 355-356).
- `src/app/sdtm/service.py`
  - `plan.state = "misaligned"` on input-selection changes (around line 518), and a `409 sdtm_plan_misaligned` is raised for downstream ops (around line 403) with detail "Save a validated plan revision against the current Specification…".

This matches the platform rule in `AGENTS.md`: a Specification or input-selection change marks the plan misaligned and must block edits/preview/validation/compilation/execution until an explicit validated plan revision restores alignment. So the locked inspector after a spec/input edit is **expected**, not a defect.

### 5. ETag / If-Match is NOT a cause

Answer to brief Q4: no. The `If-Match` ETag (`useWorkbench().ifMatch()`) is attached only to the **save mutation** (`usePutPlan({ … request: ifMatch() })`). It plays no part in whether inspector fields are enabled. A missing/absent ETag would surface as a `412` on save, not a disabled inspector.

### 6. Edits ARE written back (not pass-by-value only)

Answer to brief Q5: edits are wired back. `handleInspectorChange` in `derivation-plan-graph.tsx` maps the changed node into the controlled array and calls `onNodesChange`, which the panel binds to `setNodes`:

```
const handleInspectorChange = (next) => {
  if (readOnly) return
  onNodesChange(flow.getNodes().map(node =>
    node.id === next.id ? { ...node, data: next, type: next.node_type } : node))
}
```

Note the leading `if (readOnly) return` — a second place the misalignment gate blocks writes even if a field somehow fired.

## Secondary code-level risk (only if the symptom is "no fields," not "greyed fields")

If the real symptom is that selecting a node shows the **placeholder** ("Select a node on the canvas to edit its typed parameters.") instead of greyed fields, then selection is not landing. Things to verify against a running build:

- `selectedNode` depends on `selectedId` being set by a React Flow `select` change in `handleNodesChange`. The handler reads `applyNodeChanges(effective, flow.getNodes())` and emits upward, then sets `selectedId`. If `flow.getNodes()` and the controlled `nodes` prop ever diverge (e.g. the panel does not feed the applied array straight back), the `select` flag could be dropped. In the current code the panel binds `onNodesChange={setNodes}`, so this should hold — but it is the one place worth a live check.
- `elementsSelectable` is set on `<ReactFlow>` and `nodesDraggable={!readOnly}`; selection is independent of `readOnly`, so a selected-but-locked node is the expected misaligned experience.

This path is **not** supported by the current code reading as a defect; it is listed for completeness because it is the only alternative that produces "can't edit."

## Recommendations (propose only; nothing implemented)

1. **Confirm which symptom the user sees.** If the inspector fields are visible but greyed, this is the misalignment guard working as designed (cause #1). If the inspector shows the placeholder text and no fields, pursue the selection check in the secondary-risk section.

2. **If misaligned (expected):** improve discoverability rather than changing the gate. Options:
   - Add a short read-only banner inside the inspector panel itself (it currently has no misalignment note of its own; the explanation lives only at the top of the page in `AlignmentBanner` and next to Save). File: `frontend/src/components/workbench/plan-graph/node-inspector.tsx` — render a one-line "Read-only: plan is misaligned with its pinned Specification/Input Selection" when `readOnly` is true.
   - Make the re-alignment path obvious (a "Create aligned plan revision" affordance), consistent with the server message in `src/app/sdtm/service.py`.
   These are user-visible/behavioral changes — confirm intent before implementing.

3. **If selection is genuinely failing (defect):** add a focused component test that mounts `DerivationPlanGraph` with `readOnly={false}`, fires a React Flow `select` change for a node, and asserts the inspector renders that node's editable fields (extends `-derivation-plan-graph.test.tsx`). Then trace `handleNodesChange` → `setSelectedId` → `selectedNode` to find where the `select` flag is lost.

## Verification performed

- Read the four brief-named files plus `plan-graph-adapters.ts`, `operator-node.tsx`, and `alignment-banner.tsx`.
- Traced the `readOnly` prop from `DerivationPlanPanel` → `DerivationPlanGraph` → `NodeInspector` and confirmed every field binds `disabled={readOnly}`.
- Confirmed `onChange` is present on all inspector fields and that `handleInspectorChange` writes edits back to controlled state.
- Confirmed server-side that Specification / Input Selection saves set `plan.state = "misaligned"` (`src/app/sdtm/routes.py`, `src/app/sdtm/service.py`), which drives the frontend read-only gate.
- Reviewed the component tests, which assert both the editable and the read-only (disabled) inspector behavior.
