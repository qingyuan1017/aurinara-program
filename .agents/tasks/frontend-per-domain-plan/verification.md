# Verification — Frontend per-domain / per-dataset Derivation Plans

Iteration: first implementation (no `review.json` present).

All commands run with the working directory
`e:\Work\EDETEK\Python\aurinara\.worktrees\frontend-per-domain-plan\frontend`
(the worktree frontend dir), using the declared npm scripts. Node 22, orval 7.21.0.

Note on first setup: the worktree had no `node_modules`, so `npm install` was run
once (741 packages added) before the client could be regenerated. The backend
app factory booted in-process through `uv run python` for the OpenAPI export (no
running server needed), exactly as `scripts/export-openapi.mjs` does.

## 1. Client regeneration — `npm run api:sync` → PASS (exit 0)

`api:export` wrote `frontend/openapi.json`:

```
Wrote E:\...\frontend\openapi.json (173 paths, 230 schemas).
```

`api:generate` (orval):

```
🍻 orval v7.21.0 ...
aurinara: Cleaning output folder
🎉 aurinara - Your OpenAPI spec has been converted into ready to use orval!
```

Orval initially failed with `Duplicate schema names detected: 2x ListPlansParams`.
Root cause: the backend's two list routes (`GET /sdtms/{sdtm_id}/derivation-plans`
and `GET /adams/{adam_id}/derivation-plans`) both auto-generate the operationId
`list_plans_...`; after the config strips the `_api_v1_...` suffix both became
`listPlans`, and each emits a global `ListPlansParams` query-param model
(`limit`/`after`) that collided. Fixed in `orval.config.ts` with a single,
targeted disambiguation: when the cleaned name is `list_plans`, prefix the tag
(`list_sdtm_plans` / `list_adam_plans`). This renames only the brand-new list
hooks (`useListSdtmPlans` / `useListAdamPlans`) and leaves every other hook name
unchanged. (Many other operations share hook names across tags, e.g. `getPlan`,
`getSpecification`; those are fine because hooks are split per-tag into separate
files and only the list endpoints carry a named query-param model.)

Regenerated `openapi.json` was grepped to confirm the new contract is present:

```
OK   domains/{domain_code}/derivation-plan
OK   datasets/{dataset_code}/derivation-plan
OK   upstream_plan_pins
```

(`upstream_plan_changed`, the 409 codes `sdtm_plan_upstream_misaligned` /
`sdtm_output_coverage_incomplete`, and `upstream_state` / `missing_domains` are
runtime `problem+json` body values, not OpenAPI schema members, so they are read
defensively via `parseProblem()` and do not appear in the generated types — same
pattern the existing `stale_input_fingerprint` / `sdtm_preview_domain_unknown`
handling uses.)

Confirmed regenerated hook signatures (SDTM; ADaM mirrors with `datasetCode`):
- `useGetPlan(sdtmId, domainCode)`, `getGetPlanQueryKey(sdtmId?, domainCode?)`
- `usePutPlan` vars `{ sdtmId, domainCode, data }`
- `useValidatePlan` vars `{ sdtmId, domainCode }`
- `usePreviewPlan` vars `{ sdtmId, domainCode, data }`
- `useGetLineage(sdtmId)` — still aggregate-level (`GET /sdtms/{sdtm_id}/lineage`)
- `useListSdtmPlans(sdtmId, params?)`, `getListSdtmPlansQueryKey(sdtmId?, params?)`
- Plan response type is now `AppSdtmRoutesPlanResponse` (was `PlanResponse`);
  it carries `domain`, `revision`, `alignment_state`, `alignment_reasons`,
  `upstream_plan_pins`.
- `SdtmDerivationPlan` now requires `domain` and `schema_version: '1.1.0'`.
- `AppSdtmRoutesCompileRequest` now requires `domain_code`.
- `SdtmDerivationPlanNodesItem` union now includes `SdtmReadNode`
  (`{ node_type: 'sdtm_read', id, dataset }`).

A second `api:sync` reproduced identical generated output (orval `clean: true`
is deterministic), so the committed `openapi.json` + `src/api/generated/**` are
in sync with the backend — matching the CI contract check.

## 2. `npm run typecheck` (tsc --noEmit) and `tsc -b` → PASS (exit 0)

The build-time gate is `tsc -b` (project references). It initially surfaced the
expected consumer breaks after regen (operator-catalog exhaustiveness for the new
`sdtm_read` union member; the `domainCode` arity change on the plan hooks; the
new required `domain` / `schema_version` '1.1.0' / `domain_code`). After the
consumer edits:

```
> aurinara-frontend@0.1.0 typecheck
> tsc --noEmit
(exit 0)

$ npx tsc -b
(exit 0)
```

## 3. `npm run lint` (eslint) → PASS (exit 0)

```
> eslint .
✖ 11 problems (0 errors, 11 warnings)
(exit 0)
```

All 11 are pre-existing `react-refresh/only-export-components` warnings in files
unrelated to this change (badge, button, sidebar, acrf-panel, alignment-banner,
preview-panel, staleness-banner, and two pre-existing ones in
derivation-preview-lineage-panel). No new warnings were introduced (an initial
`react-hooks/exhaustive-deps` warning from the new `DerivationPlanTab` was
resolved by memoizing `heads`). 0 errors.

## 4. `npm run test` (vitest run) → PASS (exit 0)

```
 Test Files  27 passed (27)
      Tests  291 passed (291)
```

Updated/added tests:
- `plan-graph/-derivation-plan-graph.test.tsx`: per-domain hook shape
  (`useGetPlan(sdtmId, domainCode)`, `usePutPlan` vars `{sdtmId, domainCode, data}`,
  `getGetPlanQueryKey(sdtmId, domainCode)`); render `<DerivationPlanPanel
  sdtmId="sdtm-1" domainCode="DM" />`; save `If-Match` asserted as the loaded
  **plan revision** (`ifMatchRequest(4)` → `"revision-4"`) instead of the
  aggregate revision; new cases for `409 sdtm_plan_upstream_misaligned`
  (`upstream_state: "absent"` → upstream notice, on-canvas edits kept) and
  `409 sdtm_output_coverage_incomplete` (`missing_domains` → coverage notice);
  a NodeInspector case proving `sdtm_read` is creatable and its `dataset` field
  round-trips a typed `SdtmReadNode`. New-plan first-save still pins the current
  spec/input and the aggregate `If-Match` (no plan revision exists yet) and now
  carries `domain: 'DM'` / `schema_version: '1.1.0'`.
- `-derivation-preview-lineage-panel.test.tsx`: `domainCode` threaded through the
  mocked preview/validate hooks and the render; asserts preview and validate
  mutate vars carry `domainCode`.
- `plan-graph/-adapters-connection.test.ts`: `graphToPlan` meta now requires
  `domain`; added cases that `sdtm_read` is a valid connection SOURCE and
  rejected as a TARGET (no inputs).
- `routes/_app/sdtm/-sdtm-screens.test.tsx`: added `useListSdtmPlans` to the
  SDTM hook mock (the Derivation plan tab resolves domains from the plan head
  list) and a `?domain=` search param; routing assertions unchanged.
- `-compile-execution-panels.test.tsx`: added `useListSdtmPlans` to the mock and
  asserted the compile request now carries `domain_code: 'DM'` (compile is
  per-domain).

## 5. `npm run build` (tsc -b && vite build) → PASS

```
✓ built in 20.18s
```

## Git scope

`git status --porcelain` shows 633 changed paths, **all under `frontend/`**
(0 outside). `src/app/config.py` and everything outside `frontend/` are
untouched. The bulk are regenerated `src/api/generated/**` + `openapi.json`;
the rest are the hand-written consumer edits and tests listed above.
