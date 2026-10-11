# Per-domain / per-dataset Derivation Plan frontend migration

The frontend plan consumers move off the single aggregate-wide plan contract onto the new per-domain (SDTM) / per-dataset (ADaM) Derivation Plan API. The orval client and committed `openapi.json` were regenerated against the new routes (`.../domains/{domain_code}/derivation-plan`, `.../datasets/{dataset_code}/derivation-plan`), the SDTM workbench now scopes every plan read/write/preview/validate/compile by a selected `domain_code`, the graph editor gains the `sdtm_read` source node, the four new 409 codes are surfaced beside the existing stale-input handling, and the per-domain plan revision drives `If-Match`. The change is confined to `frontend/`, additive, and keeps the existing TanStack Query / @xyflow/react / radix-shadcn / sonner patterns.

Watch for: the plan-error problem bodies (`upstream_state`, `missing_domains`) are read through the `ProblemIssue` index signature as `unknown` with runtime guards (confirmed), not typed OpenAPI members — this is deliberate and matches the existing `stale_input_fingerprint` handling, but it means a backend rename of those fields won't surface as a type error. No ADaM plan-editing UI exists in the frontend, so "ADaM per-dataset" lands only as the regenerated client; there is nothing to re-wire there (confirmed).

**Verdict**: APPROVED

## High-level view

Client regeneration is deterministic and committed: the plan response type became `AppSdtmRoutesPlanResponse` carrying `domain`, `revision`, `alignment_state`, and `upstream_plan_pins`; `SdtmDerivationPlan` now requires `domain` + `schema_version: '1.1.0'`; the SDTM/ADaM list routes were disambiguated in `orval.config.ts` because both auto-generated a colliding `ListPlansParams`. The fix is a single targeted name prefix on the `list_plans` operation and leaves every other hook name untouched.

The SDTM workbench detail route grew a `DerivationPlanTab` that resolves the available domains from the plan head list (`useListSdtmPlans`), binds the selection to a `?domain=` search param for stable deep links, and remounts `DerivationPlanPanel` per domain so query state, canvas state, and the per-plan ETag reset cleanly. The panel itself is scoped to one `domainCode` and drives the per-domain GET/PUT/validate/preview routes; the compile panel independently picks a domain and sends `domain_code` in the compile body.

The graph editor adds `sdtm_read` as a source operator (`hasOutput: true`, no input ports), so the pure connection rules automatically allow it as an edge source and reject it as a target. The node inspector renders a typed `dataset` field for it. No free-text code field is introduced, honoring the platform boundary.

Error handling extends the existing conflict path: `sdtm_plan_upstream_misaligned` (including `upstream_state: "absent"`) and `sdtm_output_coverage_incomplete` get their own inline notices that name the offending domains and preserve on-canvas edits, sitting alongside the existing `stale_input_fingerprint` and 412 notices. The per-domain plan revision is used as `If-Match` for a loaded plan, with the aggregate ETag retained only for a brand-new plan's first save.

ADaM symmetry lands at the API layer only. The regenerated ADaM client exposes the per-dataset shape, but the frontend has no ADaM workbench detail route or plan panel (only an aggregate list/create screen), so there is no ADaM plan consumer to migrate.

<details>
<summary>Issues (0)</summary>

No blocking or non-blocking findings. The notes under "Watch for" are deliberate, pre-existing patterns, not action items.

</details>

<details>
<summary>Details</summary>

### Client regeneration and the list-route name collision

Both `GET /sdtms/{sdtm_id}/derivation-plans` and `GET /adams/{adam_id}/derivation-plans` auto-generate the operationId `list_plans_...`; after the existing `_api_v1_...` suffix strip they both cleaned to `listPlans` and each emitted a global `ListPlansParams` query-param model (`limit`/`after`), which orval refuses as a duplicate. The `orval.config.ts` change disambiguates only the `list_plans` operation by prefixing its tag (`list_sdtm_plans` / `list_adam_plans`), so the sole renamed hooks are the brand-new `useListSdtmPlans` / `useListAdamPlans`. Other cross-tag name shares (`getPlan`, `getSpecification`) are untouched because orval splits hooks per tag into separate files and only the list endpoints carry a named query-param model. The verification doc records a second `api:sync` reproducing identical output, consistent with the committed `openapi.json` + `src/api/generated/**`.

### Per-domain scoping through the workbench

`DerivationPlanTab` in `$sdtmId.tsx` resolves domains from `useListSdtmPlans(sdtmId)`, drives the active domain off a validated `?domain=` search param (falling back to the first head when the deep link is stale), and remounts `DerivationPlanPanel` with `key={activeDomain}` so the per-domain plan query, local canvas state, and ETag reset on domain switch. `?domain=` is preserved across `?tab=` changes so returning to the tab lands on the same plan. The compile panel resolves its own domain selection from the plan head list and sends `domain_code` in the compile body, matching the per-domain compile contract.

### `sdtm_read` as a typed source operator

The operator catalog adds `sdtm_read` with `category: 'source'`, `inputs: []`, `inputArity: 'none'`, `hasOutput: true`, and a factory producing `{ node_type: 'sdtm_read', id, dataset: '' }`. Because the pure `evaluateConnection` rules key off `hasOutput` and `inputs.length`, `sdtm_read` is admissible as an edge source and refused as a target ("does not accept an input") with no rule-specific branching. The inspector renders a single typed `dataset` text field. The catalog is typed as a total map over `PlanNodeType`, so the new union member is a compile-time requirement rather than an optional add — the right way to keep the palette in lockstep with the generated union.

### New 409 codes and the per-plan ETag

`derivation-plan-panel.tsx` adds two conflict branches next to the existing `stale_input_fingerprint` (409) and 412 handling. `sdtm_plan_upstream_misaligned` reads `issues[].upstream_code` / `upstream_state`, rendering `"<code> (no plan authored yet)"` when `upstream_state === 'absent'` and `"<code> (<state>)"` otherwise, falling back to `problem.detail`. `sdtm_output_coverage_incomplete` flattens `issues[].missing_domains` into the notice. Both keep the on-canvas edits (no re-seed) so no work is lost while re-aligning. These fields are read through the `ProblemIssue` `[key: string]: unknown` index signature with `typeof`/`Array.isArray` guards — the same defensive runtime-body pattern used for `stale_input_fingerprint` and `sdtm_preview_domain_unknown`, and the reason they do not appear as generated types. For a loaded plan the PUT sends `If-Match` for the plan's own `revision` via `ifMatchRequest(plan.revision)`; only a brand-new plan (no revision yet) falls back to the aggregate `ifMatch()`. The test suite pins both: a loaded save asserts `If-Match: "revision-4"` (the plan revision) and a first save asserts the aggregate revision.

### ADaM symmetry is API-only

The regenerated ADaM client carries the per-dataset plan shape (`datasetCode` hooks, `AppAdamRoutesPlanResponse`, `adamArtifactRequestDatasetCode`), but the frontend has no ADaM workbench detail route (`$adamId.tsx` does not exist) and no ADaM derivation-plan panel — only `routes/_app/adam.tsx`, which lists and creates aggregates and does not touch plans. So "ADaM goes per-dataset at the same time" is satisfied at the generated contract without any consumer to re-wire, and nothing in the ADaM UI needed to change.

### Test coverage

Updated/added tests (per the verification evidence, not re-run here): the graph test exercises the per-domain hook shape, the plan-revision `If-Match`, the two new 409 notices (including `upstream_state: "absent"` and `missing_domains`), and a `sdtm_read` create/edit round-trip proving its `dataset` field persists; the adapters-connection test adds `sdtm_read` as a valid source and rejected target and requires `domain` on `graphToPlan` meta; the preview/lineage test threads `domainCode` through preview/validate; the SDTM screens and compile tests add the `useListSdtmPlans` mock and assert the compile request carries `domain_code`. 27 files / 291 tests pass. Not separately verified here: the ADaM list route generation beyond the recorded `api:sync` reproduction (acceptable — no ADaM consumer depends on it yet).

</details>

<details>
<summary>File map</summary>

- `frontend/orval.config.ts` — disambiguate the colliding `list_plans` operation name per tag
- `frontend/openapi.json`, `frontend/src/api/generated/**` — regenerated per-domain/per-dataset client (new plan response types, `sdtm_read`/`domain_code`, list params)
- `frontend/src/components/workbench/derivation-plan-panel.tsx` — per-domain scoping, per-plan ETag, two new 409 notices
- `frontend/src/components/workbench/plan-graph/operator-catalog.ts` — `sdtm_read` source operator entry
- `frontend/src/components/workbench/plan-graph/node-inspector.tsx` — typed `sdtm_read` dataset field
- `frontend/src/components/workbench/plan-graph-adapters.ts` — `domain` on `GraphToPlanMeta`, schema version `1.1.0`
- `frontend/src/components/workbench/derivation-preview-lineage-panel.tsx` — `domainCode` threaded through preview/validate
- `frontend/src/components/workbench/compile-panel.tsx` — per-domain compile with `domain_code`
- `frontend/src/lib/invalidate.ts` — per-domain plan key invalidation
- `frontend/src/routes/_app/sdtm/$sdtmId.tsx` — `DerivationPlanTab` domain picker + `?domain=` deep link
- test files — `-derivation-plan-graph.test.tsx`, `-adapters-connection.test.ts`, `-derivation-preview-lineage-panel.test.tsx`, `-sdtm-screens.test.tsx`, `-compile-execution-panels.test.tsx`

Full diff: `git -C e:\Work\EDETEK\Python\aurinara\.worktrees\frontend-per-domain-plan diff master...frontend-per-domain-plan`

</details>
