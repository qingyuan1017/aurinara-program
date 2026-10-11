# Implementation Plan — Frontend per-domain / per-dataset Derivation Plans

Scope: FRONTEND ONLY. Backend, OpenAPI source, and docs are already merged to master (commit d7cf6c3). This task regenerates the typed client from the current backend and fixes the hand-written SDTM consumers to the new per-domain contract. Do NOT touch `src/app/config.py` or anything outside `frontend/`.

All paths below are inside the worktree:
`e:\Work\EDETEK\Python\aurinara\.worktrees\frontend-per-domain-plan\frontend\`
(the frontend dir). The run cwd for every `npm` command is that `frontend\` directory.

## Context discovered during exploration (design decisions baked in)

- **The worktree `openapi.json` is STALE.** Its plan routes are still the old single-plan shape (`/api/v1/sdtms/{sdtm_id}/derivation-plan`, `/api/v1/adams/{adam_id}/derivation-plan`) and it lacks `upstream_plan_pins`, the `upstream_plan_changed` alignment reason, and the new 409 codes. It DOES already contain `SdtmReadNode`/`AdamReadNode` schemas and `adam_read`/`sdtm_read` in the ADaM union, but NOT `SdtmReadNode` in the SDTM union — an inconsistent intermediate state. Everything therefore starts from a clean regeneration.
- **The backend on master emits the new routes** (verified in `src/app/sdtm/routes.py` / `src/app/adam/routes.py`): `GET /sdtms/{sdtm_id}/derivation-plans` (list, `PlanHeadPage`), `GET|PUT /sdtms/{sdtm_id}/domains/{domain_code}/derivation-plan`, `POST .../domains/{domain_code}/derivation-plan/validate|preview`; ADaM mirrors with `datasets/{dataset_code}`. Backend models carry `domain_code`/`dataset_code` and `upstream_plan_pins` (verified in `src/app/sdtm/models.py`, `service.py`).
- **The SDTM plan routes have no explicit `operation_id`**, so FastAPI auto-generates ids whose `_api_v1_...` suffix orval strips. Hook names stay the same (`useGetPlan`, `usePutPlan`, `useValidatePlan`, `usePreviewPlan`), but their generated signatures gain a `domainCode` (SDTM) / `datasetCode` (ADaM) argument, `getGetPlanQueryKey` becomes `(sdtmId, domainCode)`, and a new `useListPlans` appears. Confirm the exact regenerated names/arg-order from the regenerated files (step 1) before editing consumers — do not assume.
- **Only SDTM has a hand-written plan UI.** There is NO ADaM detail route or ADaM derivation-plan panel in the frontend (`src/routes/_app/adam.tsx` is a list screen only; no `src/routes/_app/adam/$adamId.tsx`). The ADaM plan hooks are generated but have no hand-written consumer, so the ADaM side is covered by regeneration + typecheck alone and needs no panel edits.
- **The shared plan-graph editor is SDTM-typed.** `operator-catalog.ts` keys an exhaustive map over `SdtmDerivationPlanNodesItem['node_type']` and `node-inspector.tsx` has an exhaustive `switch` with no `default`. When regen adds `sdtm_read` to the SDTM union, BOTH fail `tsc` until a `sdtm_read` entry/case is added. This is the mechanism that forces the node-type work and is why regen must come first.
- **ETag today is the aggregate revision.** `derivation-plan-panel.tsx` sends `If-Match` from `useWorkbench().ifMatch()` (aggregate revision, `"revision-{N}"`). The new contract makes the plan ETag the per-domain plan revision; the panel must send `If-Match` from the loaded plan's `revision`.
- **Verification tooling:** `npm run api:sync` (export + orval), `npm run typecheck` (`tsc -b`, the build-time contract gate), `npm run lint`, `npm run test` (vitest). CI (`.github/workflows/frontend-contract.yml`) runs exactly api:sync → typecheck → lint → test and requires `openapi.json` committed and the client in sync, so the regenerated `openapi.json` and `src/api/generated/**` MUST be committed.
- **MAIN-workspace reconciliation note:** the MAIN workspace copy of `frontend/src/components/workbench/plan-graph/derivation-plan-graph.tsx` has separate UNCOMMITTED edits (confirmed via `git status`). Those are the user's to reconcile later. In THIS worktree make minimal, additive changes to that file for the new API shape only — do not restructure the editor.

---

- [ ] 1. Regenerate the typed client from the current backend and commit the result.
      Run the export+generate pipeline so `openapi.json` reflects master's per-domain routes and the generated hooks/models follow. The exporter boots the FastAPI app in-process (`uv run python`), so no running backend is needed. If `npm run api:export` fails because `uv` can resolve the app but the environment is not synced, run `uv sync --extra dev` at the repo root first (same as CI), then re-run; the fallback for "no running server" is already the default path (`scripts/export-openapi.mjs` runs the app factory directly — do not add a server). Do not hand-edit any generated file.
      Files (regenerated, do not hand-edit): `frontend/openapi.json`, `frontend/src/api/generated/sdtm/sdtm.ts`, `frontend/src/api/generated/adam/adam.ts`, `frontend/src/api/generated/model/**` (new/updated `sdtmReadNode.ts`, `adamReadNode.ts`, `sdtmDerivationPlanNodesItem.ts`, `planResponse.ts` and any `upstream_plan_pins`/`alignmentReasons` additions).
      Verify: `cd frontend; npm run api:sync` exits 0 and writes `openapi.json`; then grep the regenerated `frontend/openapi.json` for `domains/{domain_code}/derivation-plan`, `datasets/{dataset_code}/derivation-plan`, `upstream_plan_pins`, and `upstream_plan_changed` and confirm all are present (this grep validates the regen input, not the app). Expect `npm run typecheck` to now FAIL in `operator-catalog.ts` / `node-inspector.tsx` (SDTM union gained `sdtm_read`) and in the plan consumers (hook arity changed) — those failures are addressed by the steps below and are the signal regen worked.

- [ ] 2. Confirm the regenerated plan hook signatures and record them inline.
      Open the regenerated `frontend/src/api/generated/sdtm/sdtm.ts` and `.../adam/adam.ts` and note the exact exported names and argument order for `getPlan`/`useGetPlan`, `putPlan`/`usePutPlan`, `getGetPlanQueryKey`, `validatePlan`/`useValidatePlan`, `previewPlan`/`usePreviewPlan`, and the new `listPlans`/`useListPlans`. This is a read-only confirmation step so steps 3–8 use the real names/arg-order rather than assumptions; no code changes.
      Files: none (inspection only).
      Verify: the names/signatures are written into this task's working notes or the PR description; nothing to build.

- [ ] 3. Add the `sdtm_read` operator to the shared operator catalog.
      In `operator-catalog.ts`, add an `OperatorDescriptor<SdtmReadNode>` (import `SdtmReadNode` from `@/api/generated/model`): `nodeType: 'sdtm_read'`, a `source` category, no inputs (`inputArity: 'none'`), `hasOutput: true`, a `create` returning `{ node_type: 'sdtm_read', id, dataset: '' }` (matches the generated shape: `dataset` with pattern `^[A-Z][A-Z0-9]{1,7}$`), and a `summary` showing `dataset: {dataset || '—'}`. Register it in `OPERATOR_CATALOG` and in `PALETTE_ORDER` (next to `raw_read`, since both are sources). This restores exhaustiveness so the map compiles.
      Files: `frontend/src/components/workbench/plan-graph/operator-catalog.ts`
      Verify: `cd frontend; npm run typecheck` — the `OPERATOR_CATALOG` exhaustiveness error on the SDTM union is gone (remaining errors are addressed by later steps).

- [ ] 4. Render/edit the `sdtm_read` node in the node inspector.
      In `node-inspector.tsx`, add a `case 'sdtm_read':` to the `NodeFields` switch that renders a single typed `TextField` for `node.dataset` (label e.g. "SDTM domain to read", placeholder `e.g. DM`), emitting `{ ...node, dataset: next }`. Add a small `SdtmReadFields` component mirroring `RawReadFields`. Import `SdtmReadNode` from `@/api/generated/model`. This keeps the inspector exhaustive (no `default`) and binds only the typed field.
      Files: `frontend/src/components/workbench/plan-graph/node-inspector.tsx`
      Verify: `cd frontend; npm run typecheck` — the `NodeFields` switch no longer reports a non-exhaustive/unused-import error for `sdtm_read`.

- [ ] 5. Scope the SDTM Derivation Plan panel to a domain and migrate its hooks + per-plan ETag.
      In `derivation-plan-panel.tsx`: accept a `domainCode: string` prop alongside `sdtmId` (the route supplies it in step 9). Update every plan call to the regenerated signature from step 2 — `useGetPlan(sdtmId, domainCode)`, `usePutPlan` with `{ sdtmId, domainCode, data }` vars, and `getGetPlanQueryKey(sdtmId, domainCode)` for the local `planKey`/reload. Change the save `request` from the aggregate `ifMatch()` to a PER-PLAN ETag: send `If-Match` built from the loaded plan's `revision` using `ifMatchRequest(plan.revision)` from `@/lib/requests` (fall back to the aggregate `ifMatch()` only when no plan is loaded yet, i.e. the first-save/new-plan path, since no plan revision exists then). Keep the existing new-plan/404/409-stale/412/misaligned flows intact; they are per-domain now because the hook is domain-scoped. Keep changes minimal and additive.
      Files: `frontend/src/components/workbench/derivation-plan-panel.tsx`
      Verify: `cd frontend; npm run typecheck` passes for this file; it is covered end-to-end by the test update in step 10.

- [ ] 6. Scope the preview/validation/lineage panel to the same domain.
      In `derivation-preview-lineage-panel.tsx`: accept `domainCode: string` and pass it to `useValidatePlan`/`usePreviewPlan` mutate vars (`{ sdtmId, domainCode, data }`) and to `useGetLineage` per the regenerated signatures. The per-domain preview endpoint still produces that domain's output(s); keep the existing optional-domains input and the `sdtm_preview_domain_unknown` handling as-is. Thread `domainCode` down from `DerivationPlanPanel` where it mounts this panel.
      Files: `frontend/src/components/workbench/derivation-preview-lineage-panel.tsx`
      Verify: `cd frontend; npm run typecheck` passes for this file; covered by its test in step 11.

- [ ] 7. Update the SDTM invalidation helper for the per-domain plan key.
      In `lib/invalidate.ts`, `getGetPlanQueryKey` and `getGetLineageQueryKey` now take `(sdtmId, domainCode)` (confirm lineage arity in step 2 — lineage is still aggregate-level per the backend route `/sdtms/{sdtm_id}/lineage`, so it likely stays `(sdtmId)`; only change what the regenerated signature requires). Add a `domainCode` parameter to `invalidateSdtmSubResource` (and `sdtmSubResourceKeys`) for the `'derivation-plan'` case so the save `onSuccess` invalidates the exact per-domain key. Update the single caller in `derivation-plan-panel.tsx` to pass `domainCode`. Leave the other sub-resources untouched.
      Files: `frontend/src/lib/invalidate.ts`, `frontend/src/components/workbench/derivation-plan-panel.tsx`
      Verify: `cd frontend; npm run typecheck` passes across both files.

- [ ] 8. Surface the new 409 upstream/coverage codes where plan errors are already handled.
      In `derivation-plan-panel.tsx` `handleSave`, extend the existing 409 branch (today only `stale_input_fingerprint`) to also recognize `sdtm_plan_upstream_misaligned` and `sdtm_output_coverage_incomplete` using `parseProblem(err).code`. For `sdtm_plan_upstream_misaligned`, show a notice naming the upstream domain(s) and their `upstream_state` (read from the problem `issues[]`/`detail`; include the "absent" case meaning the referenced sibling domain has no plan yet). For `sdtm_output_coverage_incomplete`, show the `missing_domains` from the problem body. Reuse the existing `StaleInputNotice`/`ConcurrencyNotice` notice pattern (a small additive notice component) and keep on-canvas edits (do not re-seed). These are additive branches; the generic `toast.error` fallback remains for anything else. Do NOT invent new backend fields — read them defensively from `parseProblem` like the existing code does.
      Files: `frontend/src/components/workbench/derivation-plan-panel.tsx`
      Verify: `cd frontend; npm run typecheck` passes; behavior asserted by the new test cases in step 10.

- [ ] 9. Provide `domainCode` from the SDTM route to the panel.
      In `src/routes/_app/sdtm/$sdtmId.tsx`, the Derivation plan tab currently renders `<DerivationPlanPanel sdtmId={sdtmId} />` with no domain. Decide the domain source and wire it: add a domain selector driven by `useListPlans(sdtmId)` (the new `GET /derivation-plans` head list) plus a `?domain=` search param (mirror the existing `?tab=` `validateSearch` pattern already in this file), defaulting to the first plan head (or an explicit "choose a domain" empty state when the workbench has no plan heads yet). Pass the chosen `domainCode` into `<DerivationPlanPanel sdtmId={sdtmId} domainCode={domainCode} />`. Keep the selector small and additive; do not restructure the tab shell. Decision rationale: the backend is one-plan-per-domain with a list endpoint, so the UI must let the user pick which domain's plan to edit; a `?domain=` param keeps deep links/refresh stable exactly like `?tab=`.
      Files: `frontend/src/routes/_app/sdtm/$sdtmId.tsx`
      Verify: `cd frontend; npm run typecheck` passes; the routing test in step 10/`-sdtm-screens.test.tsx` still passes (the panel is mocked there, so update the mock's props if it asserts on them).

- [ ] 10. Update the SDTM Derivation Plan graph/panel component test for per-domain + ETag + new codes.
      In `plan-graph/-derivation-plan-graph.test.tsx`: update the mocked `@/api/generated/sdtm/sdtm` hooks and the `putPlanCalls` assertions to the per-domain shape (`useGetPlan(sdtmId, domainCode)`, `usePutPlan` vars `{ sdtmId, domainCode, data }`, `getGetPlanQueryKey(sdtmId, domainCode)`), render `<DerivationPlanPanel sdtmId="sdtm-1" domainCode="DM" />`, and change the save `If-Match` assertion from the aggregate revision to the loaded PLAN revision (`ifMatchRequest(plan.revision)`). Add two focused cases: (a) a `409 sdtm_plan_upstream_misaligned` (with an `upstream_state` of `"absent"`) renders the upstream notice and keeps on-canvas edits; (b) a `409 sdtm_output_coverage_incomplete` with `missing_domains` renders the coverage notice. Add one palette/drop or inspector case proving a `sdtm_read` node is creatable and editable (dataset field round-trips a typed `SdtmReadNode`). Keep the existing new-plan/stale/misaligned cases, adjusted for the per-domain hook. No unrelated tests.
      Files: `frontend/src/components/workbench/plan-graph/-derivation-plan-graph.test.tsx`
      Verify: `cd frontend; npx vitest run src/components/workbench/plan-graph/-derivation-plan-graph.test.tsx` — all cases pass.

- [ ] 11. Update the preview/lineage panel test and the catalog/connection test for the new domain arg and node type.
      In `-derivation-preview-lineage-panel.test.tsx`: thread `domainCode` through the mocked `usePreviewPlan`/`useValidatePlan`/`useGetLineage` and the render, and assert the mutate vars carry `domainCode`. In `plan-graph/-adapters-connection.test.ts`: add a case that `sdtm_read` is a valid connection SOURCE (it has an output) and is rejected as a target (no inputs), matching the descriptor added in step 3. Keep changes proportionate to the contract change; do not add unrelated coverage.
      Files: `frontend/src/components/workbench/-derivation-preview-lineage-panel.test.tsx`, `frontend/src/components/workbench/plan-graph/-adapters-connection.test.ts`
      Verify: `cd frontend; npx vitest run src/components/workbench/-derivation-preview-lineage-panel.test.tsx src/components/workbench/plan-graph/-adapters-connection.test.ts` — all pass.

- [ ] 12. Full contract + suite gate (mirror CI) and commit the regenerated artifacts.
      Run the same sequence CI enforces so the client stays in sync and nothing else regressed. Ensure `frontend/openapi.json` and `frontend/src/api/generated/**` from step 1 are staged and committed along with the consumer edits (CI fails if `openapi.json` is uncommitted or the client is out of sync). Do NOT commit the MAIN-workspace file; only the worktree branch.
      Files: none new (verification + commit of prior steps).
      Verify: `cd frontend; npm run api:sync; npm run typecheck; npm run lint; npm run test` all exit 0. Then `git -C e:\Work\EDETEK\Python\aurinara\.worktrees\frontend-per-domain-plan status --porcelain` shows `openapi.json` and `src/api/generated/**` as tracked/committed (no unexpected drift from a second `api:sync`).

## Out of scope / explicit non-goals

- No ADaM plan UI changes: there is no ADaM detail route or plan panel; the ADaM client is covered by regeneration + `tsc`. If `tsc` surfaces an ADaM-side break after regen, it would only be in generated code (not hand-written) and indicates a regen issue, not a consumer fix.
- No backend changes, no `src/app/config.py`, nothing outside `frontend/`.
- Do not reconcile or touch the MAIN-workspace uncommitted edits to `derivation-plan-graph.tsx`; the user does that later. Keep worktree edits to that file minimal and additive.
