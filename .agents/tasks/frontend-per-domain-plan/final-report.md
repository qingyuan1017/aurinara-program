# Final Report — Frontend per-domain / per-dataset Derivation Plans

## What changed

This task delivered the **frontend-only** half of the per-domain SDTM /
per-dataset ADaM derivation-plan work. The backend contract change landed
separately on `master` (`d7cf6c3 feat: per-domain SDTM / per-dataset ADaM
derivation plans`); this branch (`cb3b619 feat(frontend): per-domain SDTM /
per-dataset ADaM derivation plans`) brings the frontend into sync with it.

44 files changed, +2306 / −378. All changes are under `frontend/`. They fall
into two groups:

### Regenerated typed client (`npm run api:sync`)
- `frontend/openapi.json` re-exported from the booted app factory (173 paths,
  230 schemas).
- `frontend/src/api/generated/**` regenerated via orval 7.21.0. New/renamed
  models reflect the per-domain contract:
  - Plan response is now `AppSdtmRoutesPlanResponse` /
    `AppAdamRoutesPlanResponse` (carrying `domain`/`dataset`, `revision`,
    `alignment_state`, `alignment_reasons`, `upstream_plan_pins`).
  - `SdtmDerivationPlan` / `AdamDerivationPlan` require their target
    (`domain` / `dataset`) and `schema_version` `'1.1.0'`.
  - Compile requests are per-target (`AppSdtmRoutesCompileRequest.domain_code`,
    `AppAdamRoutesCompileRequest.dataset_code`).
  - `SdtmDerivationPlanNodesItem` union adds `SdtmReadNode`
    (`{ node_type: 'sdtm_read', id, dataset }`); the ADaM mirror adds the
    `adam_read` node.
  - New per-target list params `ListSdtmPlansParams` / `ListAdamPlansParams`.
  - Hooks: `useGetPlan(id, targetCode)`, `usePutPlan`/`useValidatePlan`/
    `usePreviewPlan` vars now carry the target code, and
    `useListSdtmPlans` / `useListAdamPlans` were added.
- `frontend/orval.config.ts`: single targeted disambiguation so the two
  `list_plans` operations (SDTM + ADaM) do not collide on a shared
  `ListPlansParams` query-param model. This renames only the new list hooks
  (`useListSdtmPlans` / `useListAdamPlans`); every other hook name is unchanged.

### Consumer fixes (hand-written)
- `frontend/src/components/workbench/derivation-plan-panel.tsx` and
  `derivation-preview-lineage-panel.tsx`: thread the target code through the
  per-target plan hooks; save `If-Match` now uses the loaded **plan revision**
  rather than the aggregate revision; handle the new `409`
  `sdtm_plan_upstream_misaligned` (upstream notice) and
  `sdtm_output_coverage_incomplete` (missing-domains notice) problem bodies.
- `frontend/src/components/workbench/compile-panel.tsx`: compile is now
  per-target and sends `domain_code` / `dataset_code`.
- `frontend/src/components/workbench/plan-graph/node-inspector.tsx` and
  `operator-catalog.ts`: support creating/editing the new `sdtm_read` /
  `adam_read` node and its `dataset` field; exhaustiveness over the new union
  member.
- `frontend/src/components/workbench/plan-graph-adapters.ts`: `graphToPlan`
  meta carries `domain`/`dataset`; the read node is a valid connection source
  and rejected as a target.
- `frontend/src/routes/_app/sdtm/$sdtmId.tsx`: Derivation plan tab resolves the
  domain set from the plan-head list and supports a `?domain=` search param.
- `frontend/src/lib/invalidate.ts`: query-key invalidation updated for the
  per-target keys.
- Tests updated/added across the panels, plan-graph adapters/graph, SDTM
  screens, and compile/execution panels.

## Verification

See `.agents/tasks/frontend-per-domain-plan/verification.md` for full command
output. Summary (run in the worktree `frontend/` dir, Node 22, orval 7.21.0):

- `npm run api:sync` → PASS (exit 0); regenerated client is deterministic
  (a second run reproduced identical output), matching the CI contract check.
- `npm run typecheck` (`tsc --noEmit`) and `tsc -b` → PASS (exit 0).
- `npm run lint` (eslint) → PASS (exit 0); 0 errors, 11 pre-existing warnings
  (all `react-refresh/only-export-components`, none introduced here).
- `npm run test` (vitest) → PASS; 27 files, 291 tests.
- `npm run build` (`tsc -b && vite build`) → PASS (built in ~20s).
- `git status --porcelain` on the branch showed all changed paths under
  `frontend/` (0 outside).

## Rebase / fast-forward outcome

- Worktree `frontend-per-domain-plan` working tree: clean, nothing to commit.
- `git rebase master` in the worktree: **no-op** — the branch was already based
  directly on master's tip (`merge-base == master == d7cf6c3`), so git reported
  "Current branch frontend-per-domain-plan is up to date." No conflicts.
- `git merge --ff-only frontend-per-domain-plan` on `master` (main workspace):
  **clean fast-forward** `d7cf6c3..cb3b619` (44 files). No non-ff situation; no
  force needed.

### Final git state
- `master` tip: `cb3b619` (feat(frontend): per-domain SDTM / per-dataset ADaM
  derivation plans)
- `frontend-per-domain-plan` tip: `cb3b619`
- `master...frontend-per-domain-plan`: `0  0` (fully converged; master
  fast-forwarded).
- Worktree and branch left in place (orchestrator will remove them).

## IMPORTANT — unreconciled main-workspace edits

The MAIN-workspace working tree has **separate, uncommitted** edits that were
NOT part of the `frontend-per-domain-plan` branch and were deliberately left
untouched by this step:

- `frontend/src/components/workbench/plan-graph/derivation-plan-graph.tsx`
- `src/app/config.py`

The ff-only merge did not touch either file (the branch changes neither), so
these edits are preserved exactly as they were. **The user must reconcile them
manually.** In particular, `derivation-plan-graph.tsx` has local edits that may
need to be aligned with the regenerated per-domain client / `sdtm_read` node
support that just landed on master; review and integrate (or discard) those
edits deliberately rather than assuming they are consistent with the merged
change.
