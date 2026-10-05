# Implementation Plan — Frontend Screens Buildout

Source of truth: `./design.md` (APPROVED). This plan sequences that design. Every generated hook signature and model field below was verified against `src/api/generated` before writing.

Global constraints (apply to EVERY item):

- No edits to anything under `src/api/generated/**` or to `src/routeTree.gen.ts` (TanStack Router regenerates the route tree automatically on dev/build via `autoCodeSplitting`).
- The `_app` `beforeLoad` auth guard in `src/routes/_app.tsx` must not be weakened — `StudyProvider` is mounted strictly INSIDE the guarded layout component.
- Existing dashboard (`index.tsx`), auth pages, and studies list must keep working.
- Final gate (run from `frontend/`): `npm run build` (`tsc -b && vite build`) passes with ZERO type errors AND `npm run lint` reports ZERO errors (3 pre-existing `react-refresh/only-export-components` WARNINGS in `badge.tsx`/`button.tsx`/`sidebar.tsx` are acceptable and must not increase to errors).

Verified facts used throughout:

- Collection-shaped hooks return `{ items: T[] }`: `useListRawAggregates`/`useListSdtmAggregates`/`useListAdamAggregates`/`useListTlfAggregates` → `AggregateCollection`; `useListArtifacts` → `ArtifactCollection`; `useListStudies` → `StudyCollection`. Normalize with `data?.items ?? []`.
- Array-shaped hooks return `T[]` directly: `useListDocuments`→`DocumentResponse[]`, `useListReviewItems`→`ReviewItemResponse[]`, `useListIntegrations`→`IntegrationResponse[]`, `useListExtensions`→`ExtensionResponse[]`, `useListStudyRulePacks`/`useListPlatformRulePacks`→`RulePackResponse[]`, `useListRules`→`RuleResponse[]`, `useListStandards`→`StandardProductResponse[]`, `useListReleases`→`TerminologyReleaseResponse[]`, `useListTemplates`→`CatalogIdentity[]`, `useListReconciliationIssues`→`ListReconciliationIssues200Item[]`. Normalize with `data ?? []`.
- Hook arity (query options object is ALWAYS the last positional arg):
  - 3-positional `(studyId, params?, options?)`: `useListRawAggregates`, `useListSdtmAggregates`, `useListAdamAggregates`, `useListTlfAggregates`, `useListArtifacts` — MUST pass `undefined` for `params` to reach the options slot.
  - 2-positional `(studyId, options?)`: `useListDocuments`, `useListReviewItems`, `useListIntegrations`, `useListExtensions`, `useListStudyRulePacks`.
  - params/options-only (NO studyId): `useListStandards(params?, options?)`, `useListReleases(params?, options?)`, `useListTemplates(options?)`, `useListRules(options?)`, `useListPlatformRulePacks(options?)`.
  - lookup-by-id: `useGetReconciliation(runId, options?)`, `useListReconciliationIssues(runId, options?)`.
- `ErrorType<E> = AxiosError<E>` is exported from `src/api/axios-instance.ts` (NOT the generated tree). Shared error prop is typed `AxiosError | null` (imported from `axios`); hook errors (`ErrorType<HTTPValidationError>`) pass through with no cast.

---

- [ ] 1. Add shared formatting helpers to `src/lib/utils.ts`: `formatDate(iso?: string | null): string` (returns `—` for null/undefined, else a locale date-time string via `new Date(iso).toLocaleString()`) and `formatBytes(n?: number): string` (returns `—` for null/undefined, formats bytes to B/KB/MB/GB). Keep existing `cn`.
      Files: src/lib/utils.ts
      Verify: `npm run build` passes (no type errors introduced).

- [ ] 2. Add shadcn `table` primitive at `src/components/ui/table.tsx` — plain `<table>` elements in new-york style with `data-slot` attributes and `cn()`. Export `Table, TableHeader, TableBody, TableFooter, TableRow, TableHead, TableCell, TableCaption`. No new dependency.
      Files: src/components/ui/table.tsx
      Verify: `npm run build` passes; `npm run lint` zero errors.

- [ ] 3. Add shadcn `select` and `tabs` primitives, and register their Radix deps. Add `@radix-ui/react-select` (`^2.1.2`) and `@radix-ui/react-tabs` (`^1.1.1`) to `package.json` dependencies (caret ranges consistent with existing Radix 1.x entries), then run `npm install` so the lockfile updates. Author `src/components/ui/select.tsx` (export `Select, SelectGroup, SelectValue, SelectTrigger, SelectContent, SelectLabel, SelectItem, SelectSeparator`) and `src/components/ui/tabs.tsx` (export `Tabs, TabsList, TabsTrigger, TabsContent`) in new-york style with `data-slot` + `cn()` + `cva` only where upstream uses it.
      Files: package.json, src/components/ui/select.tsx, src/components/ui/tabs.tsx
      Verify: `npm install` succeeds; `npm run build` passes; `npm run lint` zero errors.

- [ ] 4. Add shared data-state components at `src/components/data/states.tsx`: `TableLoadingState({ columns, rows=5 })` (skeleton `<TableRow>`s), `ErrorState({ error, resourceLabel })` (Card with `text-destructive` title "Could not load {resourceLabel}", 401-specific copy via `error?.response?.status === 401` else `error?.message ?? 'Request failed.'`; prop typed `error: AxiosError | null` imported from `axios`), and `EmptyState({ title, description, icon? })` (Card with optional lucide icon). Depends on items 2.
      Files: src/components/data/states.tsx
      Verify: `npm run build` passes; `npm run lint` zero errors.

- [ ] 5. Add `StatusBadge` at `src/components/data/status-badge.tsx`: `StatusBadge({ status }: { status: string })` mapping (case-insensitive) active/approved→`default`, archived/retired→`secondary`, draft/pending→`outline`, failed/error→`destructive`, else `secondary`, rendering `<Badge>`. Depends on existing `badge.tsx`.
      Files: src/components/data/status-badge.tsx
      Verify: `npm run build` passes; `npm run lint` zero errors.

- [ ] 6. Add the generic `ResourceTable` at `src/components/data/resource-table.tsx` with `ResourceColumn<T>` ({ key, header, cell?, className? }) and `ResourceTableProps<T>` ({ columns, rows, getRowId, isLoading, isError, error: AxiosError | null, resourceLabel, emptyState?, onRowClick? }). Implements the four-way switch: loading→header+`TableLoadingState`; error→`ErrorState`; empty→`emptyState ?? EmptyState`; rows→`table` wrapped in `rounded-md border`, each cell `column.cell?.(row) ?? String((row as any)[column.key] ?? '—')`. Depends on items 2, 4.
      Files: src/components/data/resource-table.tsx
      Verify: `npm run build` passes; `npm run lint` zero errors.

- [ ] 7. Add the current-study context at `src/components/study-provider.tsx`: `STUDY_KEY = 'aurinara.currentStudy'`, calls `useListStudies()`, tracks selected id in state + `localStorage` (try/catch, degrade to in-memory per `auth.ts` pattern), auto-selects persisted-id-if-still-present else `items[0]`, rewrites storage on stale id. Exposes `useCurrentStudy()` returning `{ studies, currentStudy, currentStudyId, setCurrentStudyId, isLoading, isError }`; throws if used outside provider. Add `// eslint-disable-next-line react-refresh/only-export-components` above `useCurrentStudy` (mirrors `auth-provider.tsx`). Depends on item 1 (none actually; uses generated `useListStudies`).
      Files: src/components/study-provider.tsx
      Verify: `npm run build` passes; `npm run lint` zero errors.

- [ ] 8. Add the header `StudySwitcher` at `src/components/layout/study-switcher.tsx` built on the `select` primitive: options are `studies` mapped to `{ value: study.id, label: `${study.code} — ${study.name}` }`; `onValueChange` calls `setCurrentStudyId`. States: `isLoading`→`Skeleton h-9 w-48`; zero studies→disabled trigger "No studies"; selected→code+name truncated. Depends on items 3, 7.
      Files: src/components/layout/study-switcher.tsx
      Verify: `npm run build` passes; `npm run lint` zero errors.

- [ ] 9. Add `PageHeader` at `src/components/layout/page-header.tsx` ({ title, description?, actions? }) rendering the title/description block used across pages. Pure presentational.
      Files: src/components/layout/page-header.tsx
      Verify: `npm run build` passes; `npm run lint` zero errors.

- [ ] 10. Wire the foundation into the shell: in `src/routes/_app.tsx` wrap the existing shell (SidebarProvider → SidebarInset → Header → Outlet) in `<StudyProvider>` INSIDE `AppLayout` (keep `beforeLoad` guard untouched); in `src/components/layout/header.tsx` render `<StudySwitcher />` immediately before the `ml-auto` cluster (always visible, not under the search box's `md:` gating). Depends on items 7, 8.
      Files: src/routes/_app.tsx, src/components/layout/header.tsx
      Verify: `npm run build` passes; `npm run lint` zero errors; dashboard and studies pages still render.

- [ ] 11. Build the four aggregate study-scoped screens (same pattern, one item): replace placeholders in `raw.tsx`, `sdtm.tsx`, `adam.tsx`, `tlf.tsx`. Each reads `useCurrentStudy()`, calls the 3-positional hook `useListXxxAggregates(currentStudyId ?? '', undefined, { query: { enabled: !!currentStudyId } })`, normalizes `data?.items ?? []`, renders `PageHeader` + `ResourceTable`. Columns: Raw = code,name,document_type (`—` when undefined),status(`StatusBadge`),revision; SDTM/ADaM/TLF = code,name,status(`StatusBadge`),revision. No-study case uses `ResourceTable` `emptyState` = `EmptyState` "No study selected" / "Create a study first...". Depends on items 5, 6, 9, 10.
      Files: src/routes/_app/raw.tsx, src/routes/_app/sdtm.tsx, src/routes/_app/adam.tsx, src/routes/_app/tlf.tsx
      Verify: `npm run build` passes; `npm run lint` zero errors.

- [ ] 12. Build the array study-scoped screens: `documents.tsx` (`useListDocuments(id, { query:{ enabled }})`, rows `data ?? []`, cols document_code,name,document_type,status(`StatusBadge`),revision,updated_at via `formatDate`), `review.tsx` (`useListReviewItems(id,{query:{enabled}})`, cols target_module,target_entity_type,question(truncated),priority(`StatusBadge`),status(`StatusBadge`),updated_at), `integrations.tsx` (`useListIntegrations(id,{query:{enabled}})`, cols integration_code,display_name,direction,status(`StatusBadge`),revision,updated_at). Each uses the no-study `emptyState`. Depends on items 5, 6, 9, 10.
      Files: src/routes/_app/documents.tsx, src/routes/_app/review.tsx, src/routes/_app/integrations.tsx
      Verify: `npm run build` passes; `npm run lint` zero errors.

- [ ] 13. Build the three tabbed global/mixed screens using the `tabs` primitive, one `ResourceTable` per tab: `standards.tsx` — Products (`useListStandards()`: code,name,provider,family,product_type,scope), Terminology releases (`useListReleases()`: code,version,provider,product,lifecycle(`StatusBadge`),content_schema_version), Templates (`useListTemplates()`: code,name). `terminology.tsx` — Releases (`useListReleases()`, same cols) + Study extensions (`useListExtensions(id,{query:{enabled}})`, rows `data ?? []`: code,name,codelist_code,status(`StatusBadge`),revision; no-study emptyState). `validation.tsx` — Rules (`useListRules()`: rule_id,version,module_key,default_severity(`StatusBadge`),mandatory Yes/No), Platform rule packs (`useListPlatformRulePacks()`: code,name,lifecycle(`StatusBadge`),revision,updated_at), Study rule packs (`useListStudyRulePacks(id,{query:{enabled}})`: same cols; no-study emptyState). All array-shaped → `data ?? []`. `useListCodelists` intentionally NOT wired. Depends on items 3, 5, 6, 9, 10.
      Files: src/routes/_app/standards.tsx, src/routes/_app/terminology.tsx, src/routes/_app/validation.tsx
      Verify: `npm run build` passes; `npm run lint` zero errors.

- [ ] 14. Build the packaging screen `packaging.tsx` (artifacts framing, no package-list API): `useListArtifacts(currentStudyId ?? '', undefined, { query: { enabled: !!currentStudyId } })`, rows `data?.items ?? []`, cols module,artifact_type,filename,media_type,size (right-aligned via `className`, `formatBytes`),status(`StatusBadge`),created_at(`formatDate`). Header "Submission artifacts" with description noting no package-list API yet. No-study emptyState. Depends on items 5, 6, 9, 10.
      Files: src/routes/_app/packaging.tsx
      Verify: `npm run build` passes; `npm run lint` zero errors.

- [ ] 15. Build the reconciliation lookup-by-id screen `reconciliation.tsx`: controlled `Input` + "Look up" `Button`; on submit set `runId` state (trimmed; button disabled when empty). `useGetReconciliation(runId, { query: { enabled: !!runId } })` and `useListReconciliationIssues(runId, { query: { enabled: !!runId } })`. Before lookup: `EmptyState` prompt. On loaded run: summary `Card` (reconciliation_type, reconciliation_version, status `StatusBadge`, error_count/warning_count/info_count, started_at/completed_at via `formatDate`) + issues `ResourceTable`. Issue columns = union of keys `Array.from(new Set(issues.flatMap((i) => Object.keys(i))))`; cell `v == null ? '—' : typeof v === 'object' ? JSON.stringify(v) : String(v)`; single synthetic `raw` column (`JSON.stringify(issue)`) ONLY when union is empty; `getRowId` = `String(index)`. Depends on items 5, 6, 9, 10.
      Files: src/routes/_app/reconciliation.tsx
      Verify: `npm run build` passes; `npm run lint` zero errors.

- [ ] 16. Refactor `src/routes/_app/studies.tsx` to use `PageHeader` + `StatusBadge` (remove the inline `statusVariant`), keeping its card-grid layout and behavior otherwise unchanged. Then delete `src/components/layout/module-placeholder.tsx` (now unused — confirm no remaining imports first). Depends on items 5, 9, and all route items 11–15 (so no route still imports the placeholder).
      Files: src/routes/_app/studies.tsx, (delete) src/components/layout/module-placeholder.tsx
      Verify: `npm run build` passes with ZERO type errors; `npm run lint` ZERO errors; grep confirms no import of `module-placeholder` remains.

- [ ] 17. Final full verification from `frontend/`: `npm run build` (`tsc -b && vite build`) completes with zero type errors; `npm run lint` reports zero errors; manually confirm dashboard, studies, login/signup still render and the auth guard still redirects when unauthenticated.
      Files: (none)
      Verify: `npm run build` and `npm run lint` both succeed with the stated outcomes.
