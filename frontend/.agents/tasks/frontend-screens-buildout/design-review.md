# Design Review — Frontend Screens Buildout

Reviewed document: `.agents/tasks/frontend-screens-buildout/design.md`
Frontend app: `e:\Work\EDETEK\Python\aurinara\frontend`
Review mode: fresh read, every API claim independently verified against the generated sources under `src/api/generated` and against the existing hand-written source.

## Verdict

**APPROVED** — zero HIGH, zero MEDIUM findings. Three NITs are recorded below; none gate implementation.

This design has already been through one review cycle (see its "Responses to design review findings" section). I re-verified the disputed items from that cycle (aggregate hook arity, `ErrorType` definition and location, the array-vs-collection split, the reconciliation column derivation) directly against the generated files, and they are all now correct. The remaining work was to confirm the design did not merely _assert_ those fixes but that they match reality. They do.

---

## Findings

### 1. (NIT) Reconciliation screen does not specify how its two independent queries coordinate their loading/error states

**Where:** "Per-screen design" §9 Reconciliation, and "Error handling" row for 404.

**Problem:** The screen runs two independent queries off the same `runId` — `useGetReconciliation` (drives the summary `Card`) and `useListReconciliationIssues` (drives the issues `ResourceTable`). The design specifies each query's hook call and the generic `ErrorState` behavior, but it does not say what the screen renders when the two queries disagree: e.g. the run GET succeeds (200) while the issues list 404s, or the summary is still loading while issues have resolved. As written an implementer could reasonably render a populated summary card above an errored issues table, or vice versa, with no stated preference.

**Concrete fix:** State a rule, e.g.: "The summary `Card` is gated on `getReconciliation` (`isLoading`/`isError` of that query only); the issues `ResourceTable` is gated independently on `listReconciliationIssues` via its own `isLoading`/`isError`/`error` props. The two render independently — a failed issues query shows the issues `ErrorState` beneath a successful summary card, and a failed run GET replaces the whole body (card + table) with a single `ErrorState`." That removes the only interpretation gap.

### 2. (NIT) `document_type` is `string | null`, not merely optional — the "render `—` when undefined" wording is slightly off

**Where:** "Generated API — verified facts" row-shape note and §1 Raw datasets ("document_type (render `—` when undefined)").

**Problem:** `AggregateResponse.document_type` is typed `document_type?: AggregateResponseDocumentType` where `AggregateResponseDocumentType = string | null` (verified). So the field can be `undefined` (key absent) OR `null` (present but null). The prose says "undefined"; a careless implementer might null-check only `=== undefined`.

**Concrete fix:** No code change needed — the design's own default cell renderer `String((row as any)[column.key] ?? '—')` already catches both `undefined` and `null` via `??`. Just correct the wording to "render `—` when null or undefined" so the spec and the renderer agree. Cosmetic only.

### 3. (NIT) Standards/Terminology/Validation tabs mount all tab queries eagerly, which fires global catalog requests the user may never view

**Where:** §6 Standards ("Queries for inactive tabs still mount ... acceptable at this scale"), applies equally to §7 and §8.

**Problem:** The design acknowledges this and accepts it, which is fine. The NIT is that it is accepted only for Standards and not restated for the study-scoped tabs in Terminology/Validation, where an inactive tab mounting a _study-scoped_ query is still correctly gated by `enabled: !!currentStudyId` but an inactive _global_ tab (Releases, Rules, Platform rule packs) will fetch on mount regardless of which tab is active.

**Concrete fix:** None required — the behavior is correct and the cost is trivial (cached, `staleTime` 30s). Optionally add one sentence to §7/§8 noting the same eager-mount tradeoff accepted in §6 applies, so the implementer does not "optimize" it with `TabsContent forceMount`-style conditional hook calls (which would violate the rules-of-hooks). Documentation-only.

---

## Verified Assumptions

Every item below was confirmed by reading the cited generated file(s). The design's claims are accurate.

- **`ErrorType<Error> = AxiosError<Error>`** is defined and exported from `src/api/axios-instance.ts` (NOT under `generated/**`). Confirmed. The design's import guidance (`import type { ErrorType } from '@/api/axios-instance'`) is correct.
- **Aggregate hooks are 3-positional** `(studyId, params?, options?)`: `useListRawAggregates` (`raw/raw.ts`), `useListSdtmAggregates` (`sdtm/sdtm.ts`), `useListAdamAggregates` (`adam/adam.ts`), `useListTlfAggregates` (`tlf/tlf.ts`), and `useListArtifacts` (`artifacts/artifacts.ts`). All require `studyId: string`. The design's mandate to pass `undefined` for `params` to reach the options slot is correct and necessary.
- **`useListArtifacts` requires `studyId: string`** (not optional). Confirmed in `artifacts/artifacts.ts` overloads. The task hint `studyId?` is indeed inaccurate; the design's correction is right.
- **Study-scoped array hooks are 2-positional** `(studyId, options?)`: `useListDocuments` (`documents/documents.ts`), `useListReviewItems` (`review/review.ts`), `useListIntegrations` (`integrations/integrations.ts`), `useListExtensions` (`terminology/terminology.ts`), `useListStudyRulePacks` (`validation/validation.ts`), `useListReferences` (`reference/reference.ts`). Confirmed.
- **Global catalog hook arities:** `useListStandards(params?, options?)`, `useListReleases(params?, options?)`, `useListTemplates(options?)`, `useListCodelists(releaseId, params?, options?)` — all confirmed in `provider-catalogs/provider-catalogs.ts`. `useListRules(options?)`, `useListPlatformRulePacks(options?)` in `validation/validation.ts`. `useListModules(options?)` in `modules/modules.ts`.
- **Reconciliation:** no list-runs endpoint exists; only `useGetReconciliation(runId, options?)` and `useListReconciliationIssues(runId, options?)` are exported (`reconciliation/reconciliation.ts`). The lookup-by-id framing is honest — no endpoint is invented.
- **`ListReconciliationIssues200Item = { [key: string]: unknown }`** (untyped record). Confirmed. The union-of-keys column derivation and the `v == null ? '—' : typeof v === 'object' ? JSON.stringify(v) : String(v)` cell contract are the correct way to render ragged records.
- **Collection shapes** wrap rows in `{ items: T[] }`: `AggregateCollection` (`items: AggregateResponse[]`), `StudyCollection`, `ReferenceCollection` (`items` + optional `schema_version`), `ModuleCollection`, `ArtifactCollection`. Confirmed. The `data?.items ?? []` normalization is correct.
- **Array-shaped responses** return `T[]`: `DocumentResponse[]`, `IntegrationResponse[]`, `ExtensionResponse[]`, `ReviewItemResponse[]`, `RulePackResponse[]`, `StandardProductResponse[]`, `TerminologyReleaseResponse[]`, `CatalogIdentity[]`, `RuleResponse[]`. The `data ?? []` normalization is correct.
- **Row-shape field names** all match the generated models exactly:
  - `AggregateResponse`: id, study_id, code, name, status, revision, `document_type?` (`string | null`). ✓
  - `DocumentResponse`: document_code, name, document_type (`string`), status, revision, updated_at. ✓
  - `ExtensionResponse`: code, name, codelist_code, status, revision. ✓
  - `IntegrationResponse`: integration_code, display_name, direction, status, revision, updated_at. ✓
  - `ReviewItemResponse`: target_module, target_entity_type, question, priority, status, revision, updated_at. ✓
  - `ArtifactResponse`: module, artifact_type, filename, media_type, size (`number`), status, created_at. ✓
  - `StandardProductResponse`: code, name, provider, family, product_type, scope. ✓
  - `TerminologyReleaseResponse`: code, version, provider, product, lifecycle, content_schema_version. ✓
  - `CatalogIdentity`: id, code, name (only). ✓
  - `RuleResponse`: rule_id, version, module_key, default_severity, mandatory (`boolean`). ✓
  - `RulePackResponse`: code, name, lifecycle, revision, updated_at. ✓
  - `ReconciliationResponse`: reconciliation_type, reconciliation_version, status, error_count, warning_count, info_count, started_at, completed_at. ✓
- **Nullable date types** `ReconciliationResponseStartedAt`/`CompletedAt` resolve to `string | null`. The `formatDate(iso?: string | null)` signature handles them. ✓
- **Param model shapes:** `ListStandardsParams` = `{ provider?, family?, product_type?, scope? }` all `string | null`; `ListRawAggregatesParams` etc. are the pagination params. Confirmed; the design wires none of them to UI, which is consistent with its stated scope.
- **Current-study context is complete:** localStorage key `aurinara.currentStudy`, try/catch degrade-to-memory (mirrors the verified pattern in `src/lib/auth.ts`), default-to-first with stale-id validation against `data.items`, mounted inside `_app` layout (verified `_app.tsx` structure matches the proposed wrap), `useCurrentStudy()` throw-outside-provider mirrors the verified `useAuth()` pattern in `auth-provider.tsx`, and the zero-studies empty state is specified for both the switcher and each scoped screen. All four aspects the task asked about are covered.
- **Reusable components are concrete enough to build 11+ screens without copy-paste:** `ResourceTable` carries the full prop interface and a strict 4-state rendering contract (loading → error → empty → rows); `PageHeader` has its exact JSX; `states.tsx` (`TableLoadingState`/`ErrorState`/`EmptyState`) and `StatusBadge` are specified with props and behavior. Each per-screen section lists the exact hook call, normalization, and column set. This is sufficient to implement declaratively.
- **Existing-source claims:** `query-client.ts` has `staleTime: 30_000`, `retry: 1` (✓); `studies.tsx` has the inline `statusVariant` and 401 error copy the design extracts/reuses (✓); `Badge` exposes exactly `default | secondary | destructive | outline` variants, matching `StatusBadge`'s mapping (✓); `header.tsx` has the `ml-auto` cluster the switcher anchors before, and the search box is `hidden ... md:block` as the design states (✓); `module-placeholder.tsx` exists and is safe to delete after migration (✓).
- **Build tooling:** `package.json` has `typecheck` (`tsc --noEmit`), `build` (`tsc -b && vite build`), and `lint` (`eslint .`) scripts; existing Radix deps are on the 1.x/2.x line, so `@radix-ui/react-select ^2.1.2` and `@radix-ui/react-tabs ^1.1.1` are consistent, and `@radix-ui/react-dialog` is indeed already present. The verification plan is runnable.

## Unverified / Wrong Assumptions

- **`AxiosError<HTTPValidationError>` is assignable to `AxiosError` (i.e. `AxiosError<unknown, any>`) under strict TS** — the design's locked error-prop decision. I did not compile this (no build was run, per instructions), so I did not mechanically confirm the assignability. However, it is strongly corroborated: the existing `studies.tsx` already reads `error?.response?.status` and `error?.message` off a hook error typed `ErrorType<HTTPValidationError>` and the project compiles today, which exercises the same `AxiosError<HTTPValidationError>` surface the design relies on. The design's reasoning (second config type param is `any`, so the payload-narrowing contravariance is bypassed) is sound. Treated as a reasoned, low-risk decision rather than a verified fact; if it ever fails to compile, a single-line `as AxiosError` cast at the prop boundary is the trivial fallback.
- **Extended `StatusBadge` literals** (`approved`, `retired`, `pending`, `failed`, `error`) are not constrained by any backend enum — the `status`/`lifecycle`/`default_severity` fields are free-form `string` (verified: no enum in the models). The design already acknowledges this and makes the mapping a cosmetic, case-insensitive, `secondary`-default lookup. Correctly handled, not a gap.
- **`ModuleDescriptor` field names** (`module_key`, `module_version`, `api_prefix`) were not independently reopened. The design explicitly marks `useListModules` as catalogued-for-completeness and not surfaced on any screen, so no screen depends on those fields. Acceptable — no screen correctness rides on it.
