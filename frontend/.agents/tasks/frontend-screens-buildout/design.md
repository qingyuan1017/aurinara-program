# Technical Design — Frontend Screens Buildout

Aurinara Clinical Artifact Platform — frontend (`e:\Work\EDETEK\Python\aurinara\frontend`)

## Overview

The app already renders a dashboard and a studies list under a pathless `_app` layout route that provides the sidebar + header shell and a `beforeLoad` auth guard. Twelve module routes under `src/routes/_app/` currently render `<ModulePlaceholder/>` (the task's "~11" is approximate; the authoritative list is the twelve enumerated screens in "Per-screen design"). This design replaces those placeholders with real READ/LIST/DETAIL screens, backed by the already-generated Orval hooks, without touching generated files and without duplicating boilerplate twelve times.

The work has three structural pieces plus twelve screen bindings:

1. A **current-study context** mounted inside `_app` that loads studies, tracks a selected study id in `localStorage`, and feeds a **study switcher** in the header.
2. Two reusable building blocks — a **`ResourceTable`** data-table component and a **`PageHeader`** component — plus a small set of shared state components (`LoadingState`, `ErrorState`, `EmptyState`) that enforce one loading/error/empty contract across every data-bound screen.
3. A handful of new shadcn/ui primitives (`table`, `select`, `tabs`) added in the existing new-york/zinc style, with their Radix dependency added to `package.json`.

The scope is list/detail reads plus the study switcher. Create/edit forms are out of scope. The design deliberately uses the generated hooks exactly as they exist; every hook signature and response shape below was read from the generated sources, not guessed.

## Technology stack (locked)

- Vite 5, React 18, TypeScript, strict.
- TanStack Router 1.69 (file-based routing with `autoCodeSplitting`, pathless `_app` layout, URLs omit `_app`).
- TanStack Query 5.59 — all data access goes through the Orval-generated `useListXxx` / `useGetXxx` hooks. No direct axios calls in screens.
- Orval 7.21 generated client under `src/api/generated` (read-only), axios mutator at `src/api/axios-instance.ts` (attaches the bearer token, clears it on 401).
- Tailwind v4, shadcn/ui new-york style, zinc base color. Components use `data-slot` attributes, `cn()` from `@/lib/utils`, and `cva` where variants exist, matching the existing files in `src/components/ui`.
- Icons: `lucide-react`.

No new state-management, data-fetching, or table library is introduced. The table is built on a plain HTML `<table>` wrapped in a shadcn `table` primitive, not TanStack Table — the screens only need render-and-sort-free lists, so a dependency-free table keeps the surface minimal. Column sorting/filtering is out of scope and not designed in.

## Generated API — verified facts

Every item below was confirmed by reading the generated `*.ts` and `model/*.ts` files. Two conventions matter for the shared table:

- **Collection-shaped** responses wrap rows in `{ items: T[] }` (sometimes with `next_cursor`). These are: studies (`StudyCollection`), raw/sdtm/adam/tlf (`AggregateCollection`), references (`ReferenceCollection`), modules (`ModuleCollection`), artifacts (`ArtifactCollection`).
- **Array-shaped** responses return `T[]` directly. These are: documents (`DocumentResponse[]`), integrations (`IntegrationResponse[]`), terminology extensions (`ExtensionResponse[]`), review items (`ReviewItemResponse[]`), study rule packs & platform rule packs (`RulePackResponse[]`), standards (`StandardProductResponse[]`), terminology releases (`TerminologyReleaseResponse[]`), templates (`CatalogIdentity[]`), validation rules (`RuleResponse[]`).

The `ResourceTable` must accept rows as `T[]`, so each screen normalizes a collection with `data?.items ?? []` and an array with `data ?? []` before passing rows in. This is called out again per screen.

**Hook arity rule (locked, enforced per-screen below).** The generated list hooks come in three argument shapes; the query options object is always the LAST positional argument, so getting the arity wrong silently binds `{ query: { enabled } }` to the `params` slot (a type error, and the `enabled` gate is dropped so the query fires with no study). Verified in the tag files:

- **3-positional** `(studyId: string, params?: ListXxxAggregatesParams, options?)` — the aggregate hooks (`useListRawAggregates`, `useListSdtmAggregates`, `useListAdamAggregates`, `useListTlfAggregates`) and `useListArtifacts`. These MUST pass `undefined` for `params` to reach the options slot: `useListSdtmAggregates(studyId, undefined, { query: { enabled } })`.
- **2-positional** `(studyId: string, options?)` — the study-scoped array hooks (`useListDocuments`, `useListReferences`, `useListReviewItems`, `useListIntegrations`, `useListExtensions`, `useListStudyRulePacks`): `useListDocuments(studyId, { query: { enabled } })`.
- **params-or-options-only** — `useListStandards(params?, options?)`, `useListReleases(params?, options?)` (first arg is params, not studyId); `useListTemplates(options?)`, `useListModules(options?)`, `useListRules(options?)`, `useListPlatformRulePacks(options?)`; `useListCodelists(releaseId, params?, options?)`; `useGetReconciliation(runId, options?)`, `useListReconciliationIssues(runId, options?)`.

Every per-screen hook line below spells out the full call with its exact arity; do not abbreviate when implementing.

### Study-scoped hooks (first arg is `studyId: string`, required)

| Hook                                      | Tag file                       | Response                | Row shape fields                                                                        |
| ----------------------------------------- | ------------------------------ | ----------------------- | --------------------------------------------------------------------------------------- |
| `useListRawAggregates(studyId, params?)`  | `raw/raw.ts`                   | `AggregateCollection`   | id, study_id, code, name, status, revision, document_type?                              |
| `useListSdtmAggregates(studyId, params?)` | `sdtm/sdtm.ts`                 | `AggregateCollection`   | same as above                                                                           |
| `useListAdamAggregates(studyId, params?)` | `adam/adam.ts`                 | `AggregateCollection`   | same as above                                                                           |
| `useListTlfAggregates(studyId, params?)`  | `tlf/tlf.ts`                   | `AggregateCollection`   | same as above                                                                           |
| `useListDocuments(studyId)`               | `documents/documents.ts`       | `DocumentResponse[]`    | id, study_id, document_code, name, document_type, status, revision, updated_at          |
| `useListReferences(studyId)` †            | `reference/reference.ts`       | `ReferenceCollection`   | id, reference_type, natural_key, display_name, status, revision                         |
| `useListReviewItems(studyId)`             | `review/review.ts`             | `ReviewItemResponse[]`  | id, target_module, target_entity_type, question, priority, status, revision, updated_at |
| `useListIntegrations(studyId)`            | `integrations/integrations.ts` | `IntegrationResponse[]` | id, integration_code, display_name, direction, status, revision, updated_at             |
| `useListExtensions(studyId)`              | `terminology/terminology.ts`   | `ExtensionResponse[]`   | id, code, name, codelist_code, status, revision                                         |
| `useListStudyRulePacks(studyId)`          | `validation/validation.ts`     | `RulePackResponse[]`    | id, code, name, lifecycle, revision, updated_at                                         |
| `useListArtifacts(studyId, params?)`      | `artifacts/artifacts.ts`       | `ArtifactCollection`    | id, module, artifact_type, filename, media_type, size, status, created_at               |

`useListArtifacts` takes `studyId: string` as a **required** first argument (the task hint "`studyId?`" is inaccurate — verified in `artifacts/artifacts.ts`, overloads require `studyId: string`). The packaging screen therefore uses it only when a study is selected.

### Global catalog hooks (no `studyId`)

| Hook                                   | Tag file                                 | Response                       | Row shape fields                                                                                                                               |
| -------------------------------------- | ---------------------------------------- | ------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| `useListStandards(params?)`            | `provider-catalogs/provider-catalogs.ts` | `StandardProductResponse[]`    | id, code, name, provider, family, product_type, scope                                                                                          |
| `useListReleases(params?)`             | `provider-catalogs/provider-catalogs.ts` | `TerminologyReleaseResponse[]` | id, code, version, provider, product, lifecycle, content_schema_version                                                                        |
| `useListTemplates()`                   | `provider-catalogs/provider-catalogs.ts` | `CatalogIdentity[]`            | id, code, name                                                                                                                                 |
| `useListCodelists(releaseId, params?)` | `provider-catalogs/provider-catalogs.ts` | `CodelistResponse[]`           | needs a `releaseId` — NOT used on a top-level screen (see Terminology)                                                                         |
| `useListRules()`                       | `validation/validation.ts`               | `RuleResponse[]`               | id, rule_id, version, module_key, default_severity, mandatory                                                                                  |
| `useListPlatformRulePacks()`           | `validation/validation.ts`               | `RulePackResponse[]`           | id, code, name, lifecycle, revision, updated_at                                                                                                |
| `useListModules()` †                   | `modules/modules.ts`                     | `ModuleCollection`             | module_key, module_version, api_prefix (`ModuleDescriptor` fields not independently reopened; no screen renders them, so none are depended on) |

† `useListReferences` and `useListModules` are catalogued for completeness only; no per-screen section surfaces references or modules in this scope (mirrors the deferred `useListCodelists`). They are listed so the implementer knows they exist and are intentionally not wired, not so a screen is built for them.

### Special cases

- **Reconciliation**: there is NO `list-reconciliation-runs` endpoint. The only hooks are `useGetReconciliation(runId)` → `ReconciliationResponse` and `useListReconciliationIssues(runId)` → `ListReconciliationIssues200Item[]` (where each item is `{ [key: string]: unknown }`, i.e. an untyped record). The screen is a lookup-by-id, not a list.
- **Packaging**: there is NO submission-package list hook. `useListArtifacts(studyId, params?)` is the closest study-scoped list. The screen lists the study's artifacts (module/type/filename/status) and is framed as an artifacts view, not an invented "packages" list.
- **Standards / Terminology / Validation**: global catalogs with multiple related endpoints; each uses a tabbed layout (see per-screen sections).

### Param model shapes (read, not guessed)

- `ListRawAggregatesParams` / `ListSdtmAggregatesParams` / `ListAdamAggregatesParams` / `ListTlfAggregatesParams`: `{ limit?: number; after?: string | null }`. The screens call these hooks with `studyId` only and omit params (default page size). Cursor pagination is out of scope.
- `ListStandardsParams`: `{ provider?, family?, product_type?, scope? }` — all optional, all `string | null`. Not wired to UI filters in this scope; called with no params.
- `ListReleasesParams`: `{ provider?, product?, module?, lifecycle?, compatible_standard_version_id? }` — same, called with no params.
- `ListArtifactsParams` is passed through untouched (called with `studyId` only).

## Current-study context

New file `src/components/study-provider.tsx`.

### Responsibilities

- Call `useListStudies()` once (cached by TanStack Query; `staleTime` is 30s per `query-client.ts`).
- Track the selected study id, persisted to `localStorage` under key `aurinara.currentStudy`.
- Resolve the selected `StudyResponse` object for consumers.
- Default selection: on load, if a persisted id exists AND still appears in `data.items`, use it; otherwise default to `data.items[0]`. If the persisted id is stale (study no longer visible), fall back to the first study and overwrite storage.
- Expose a setter that updates state and storage together.

### Context value (hook `useCurrentStudy()`)

```ts
interface CurrentStudyContextValue {
  studies: StudyResponse[]; // data?.items ?? []
  currentStudy: StudyResponse | null;
  currentStudyId: string | null;
  setCurrentStudyId: (id: string) => void;
  isLoading: boolean; // studies query loading
  isError: boolean;
}
```

`useCurrentStudy()` throws if used outside the provider (mirrors `useAuth()` in `auth-provider.tsx`).

### Mounting

Provided INSIDE the `_app` layout so it only mounts for authenticated users (the `beforeLoad` guard has already run). Wrap the shell in `src/routes/_app.tsx`:

```tsx
function AppLayout() {
  return (
    <StudyProvider>
      <SidebarProvider>
        <AppSidebar />
        <SidebarInset>
          <Header />
          <div className="flex flex-1 flex-col gap-4 p-4 md:p-6">
            <Outlet />
          </div>
        </SidebarInset>
      </SidebarProvider>
    </StudyProvider>
  );
}
```

### localStorage access rules

Storage reads/writes are wrapped in try/catch and silently degrade to in-memory state on failure, matching the existing pattern in `src/lib/auth.ts` (private-mode safe). The key constant `STUDY_KEY = 'aurinara.currentStudy'` lives in the provider file.

### Study switcher (header)

New file `src/components/layout/study-switcher.tsx`, rendered in `src/components/layout/header.tsx` immediately before the `ml-auto` cluster. The switcher is ALWAYS visible — it carries its own `max-w` + truncation and is not wrapped in any responsive-visibility class, so it does not share the search box's gating. (The existing search box lives inside `<div class="relative hidden w-full max-w-sm md:block">`, i.e. hidden below `md`; so on small screens the switcher, not the search box, is the first visible flex child after the sidebar trigger. "Before the `ml-auto` cluster" is the stable anchor regardless of viewport.)

Built on the new shadcn `select` primitive. It renders a `Select` whose options are `studies` mapped to `{ value: study.id, label: `${study.code} — ${study.name}` }`, with the trigger showing the current study's code and name (truncated). `onValueChange` calls `setCurrentStudyId`.

States:

- `isLoading`: render a `Skeleton` sized like the trigger (`h-9 w-48`).
- Loaded, zero studies: render a disabled trigger reading "No studies" (the scoped pages themselves show the richer empty state).
- Loaded, has studies, none selected yet: should not happen because the provider auto-selects the first; defensively the trigger shows a placeholder "Select study".

## Reusable building blocks

### `PageHeader` — `src/components/layout/page-header.tsx`

Replaces the hand-rolled `<div><h1/><p/></div>` block repeated in `index.tsx`, `studies.tsx`, and `module-placeholder.tsx`. Pure presentational.

```ts
interface PageHeaderProps {
  title: string;
  description?: React.ReactNode; // allows inline <code> like existing pages
  actions?: React.ReactNode; // right-aligned slot (unused in this scope, reserved)
}
```

Renders:

```tsx
<div className="flex items-start justify-between gap-4">
  <div>
    <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
    {description && (
      <p className="text-muted-foreground text-sm">{description}</p>
    )}
  </div>
  {actions && <div className="flex items-center gap-2">{actions}</div>}
</div>
```

### Shared state components — `src/components/data/states.tsx`

Three tiny components encode the loading/error/empty contract so no screen reinvents them.

- `TableLoadingState({ columns, rows = 5 })`: renders `rows` skeleton rows across `columns` cells inside the table body (used by `ResourceTable` internally, see below). Standalone export also available for custom layouts.
- `ErrorState({ error, resourceLabel })`: a `Card` with a `text-destructive` title "Could not load {resourceLabel}" and a description that special-cases a 401 (`error?.response?.status === 401` → "Not authenticated...") exactly like `studies.tsx` does today, otherwise `error?.message ?? 'Request failed.'`. The `error` prop is typed `AxiosError | null` (axios's own default `AxiosError<unknown, any>`), imported from `axios`. This is the widest axios error type and any `ErrorType<HTTPValidationError>` (= `AxiosError<HTTPValidationError>`) assigns to it, so screens pass their hook error through unchanged. `ErrorState` reads `error?.response?.status` and `error?.message` defensively.
- `EmptyState({ title, description, icon? })`: a `Card` with an optional lucide icon, title, and description. Used both for "no rows" and for the "no study selected" case.

### `ResourceTable` — `src/components/data/resource-table.tsx`

ONE generic table that every data-bound screen renders. It owns the loading/error/empty switching so screens stay declarative.

```ts
interface ResourceColumn<T> {
  key: string;
  header: string;
  // Cell renderer. Receives the row; returns a ReactNode. Default renders String(row[key]).
  cell?: (row: T) => React.ReactNode;
  className?: string; // th/td className (e.g. 'text-right' for size)
}

interface ResourceTableProps<T> {
  columns: ResourceColumn<T>[];
  rows: T[] | undefined;
  getRowId: (row: T) => string;
  isLoading: boolean;
  isError: boolean;
  error: AxiosError | null; // widest axios error; see note below
  resourceLabel: string; // e.g. 'documents' — feeds error + empty copy
  emptyState?: React.ReactNode; // overrides the default EmptyState (e.g. "Create a study first")
  onRowClick?: (row: T) => void; // reserved for detail navigation; optional
}
```

**Error-prop typing (locked decision).** The generated hooks default `TError = ErrorType<HTTPValidationError>`, and `ErrorType<E> = AxiosError<E>` is exported from `src/api/axios-instance.ts` (not from `generated/**` — see "Error handling"). An earlier draft typed this prop `ErrorType<unknown>`; that is WRONG under strict TS because `AxiosError<HTTPValidationError>` is not assignable to `AxiosError<unknown>` (the payload parameter appears in a contravariant position via `response.data` and the config/`toJSON` generics, so narrowing the payload to `unknown` is rejected). The prop is therefore typed `AxiosError | null`, imported from `axios`. Axios's own `AxiosError` defaults to `AxiosError<unknown, any>`; because the second (config) type parameter is `any`, any concrete `AxiosError<HTTPValidationError>` assigns to it, so screens pass `error={query.error}` through with no cast. `ResourceTable` stays generic only over the row type `T` — the error payload is intentionally erased at the prop boundary, which is sufficient because `ErrorState` reads only `error?.response?.status` and `error?.message`. (Alternative considered: `ResourceTableProps<T, E = HTTPValidationError>` with `error: ErrorType<E>`. Rejected — it forces each screen to thread or infer a second type argument and buys nothing, since no cell renderer reads the typed payload. The `AxiosError | null` form is simpler and provably assignable.)

Rendering contract (strict order, every screen gets the same behavior):

1. `isLoading` → render the table header plus `TableLoadingState` skeleton rows (`columns.length` wide). Header stays visible so layout does not jump.
2. `isError` → render `<ErrorState error={error} resourceLabel={resourceLabel} />` (no table).
3. loaded, `rows.length === 0` → render `emptyState` if provided, else `<EmptyState title={`No ${resourceLabel} yet`} .../>`.
4. loaded, has rows → render the `table` primitive; each row keyed by `getRowId(row)`; each cell renders `column.cell?.(row) ?? String((row as any)[column.key] ?? '—')`.

The table primitive is wrapped in a `rounded-md border` container (new-york convention). `onRowClick`, when set, adds `cursor-pointer hover:bg-muted/50` to rows; it is reserved and not wired to routes in this scope.

### Status → Badge variant helper — `src/components/data/status-badge.tsx`

The `statusVariant()` function currently lives inline in `studies.tsx` (where it handles only active/archived/draft with a `default` fallback). Extract it into a shared `StatusBadge({ status })` component that maps common statuses (active/approved → `default`, archived/retired → `secondary`, draft/pending → `outline`, failed/error → `destructive`, else `secondary`) and renders a `Badge`. `studies.tsx` is refactored to use it (low-risk, keeps one source of truth). Used by every screen's status/lifecycle/severity column.

Note on the mapping: the `status`/`lifecycle`/`default_severity` fields are free-form `string` in the generated models — there is NO enum constraining them, and the extended literals (`approved`, `retired`, `pending`, `failed`, `error`) were not confirmed against backend data. The map is therefore a best-effort cosmetic lookup with a `secondary` default for any unrecognized value; no screen's correctness depends on a specific badge variant, so an unmapped status renders harmlessly as `secondary`. The lookup is also case-insensitive (`status.toLowerCase()`) so casing variations do not fall through unnecessarily.

## shadcn/ui primitives to add

Added under `src/components/ui`, authored by hand in the exact style of existing files (`data-slot` attributes, `cn()`, `cva` only where the upstream new-york component uses it). Each new Radix dependency is added to `package.json` `dependencies` with a caret range matching the versions already present (Radix 1.x line).

| Component | File                           | Radix dep to add                    | Notes                                                                                                                                           |
| --------- | ------------------------------ | ----------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| Table     | `src/components/ui/table.tsx`  | none (plain `<table>` elements)     | Exports `Table, TableHeader, TableBody, TableFooter, TableRow, TableHead, TableCell, TableCaption`. new-york markup with `data-slot`.           |
| Select    | `src/components/ui/select.tsx` | `@radix-ui/react-select` (`^2.1.2`) | Used by the study switcher. Exports `Select, SelectGroup, SelectValue, SelectTrigger, SelectContent, SelectLabel, SelectItem, SelectSeparator`. |
| Tabs      | `src/components/ui/tabs.tsx`   | `@radix-ui/react-tabs` (`^1.1.1`)   | Used by Standards, Terminology, Validation. Exports `Tabs, TabsList, TabsTrigger, TabsContent`.                                                 |

Not added in this scope: `dialog` (already present as a Radix dep but no shadcn wrapper; no modal is needed for read/list screens), `sonner`/`toast` (no mutations in scope, so nothing to toast). These are intentionally deferred — adding them now would be unused code. If a later create/edit task needs them, that task adds them.

Dependency versions are pinned to caret ranges consistent with the existing Radix entries; after editing `package.json` the implementer runs `npm install` so the lockfile updates before `npm run build`.

## Per-screen design

All twelve screens follow the same skeleton: a `PageHeader`, then either a `ResourceTable` (study-scoped and simple global screens) or a tabbed layout (multi-endpoint globals) or a lookup form (reconciliation).

Study-scoped screens read `const { currentStudyId, currentStudy, isLoading: studiesLoading } = useCurrentStudy()`. The scoped hook is called with `currentStudyId ?? ''` and `{ query: { enabled: !!currentStudyId } }` so it does not fire until a study is selected. When `!studiesLoading && !currentStudyId` (zero studies exist), the screen skips the query and renders a friendly empty state via `ResourceTable`'s `emptyState` prop: an `EmptyState` titled "No study selected" / "Create a study first to view its {resource}." — NOT an error.

### 1. Raw datasets — `routes/_app/raw.tsx`

- Scope: study-scoped. Hook: `useListRawAggregates(currentStudyId ?? '', undefined, { query: { enabled: !!currentStudyId } })`.
- Rows: `data?.items ?? []` (collection).
- Columns: code, name, document_type (render `—` when undefined), status (`StatusBadge`), revision.
- Header: title "Raw datasets", description referencing `/api/v1/studies/{study_id}/raw`.

### 2. SDTM — `routes/_app/sdtm.tsx`

- Scope: study-scoped. Hook (3-positional, pass `undefined` for params): `useListSdtmAggregates(currentStudyId ?? '', undefined, { query: { enabled: !!currentStudyId } })`. Rows: `data?.items ?? []`.
- Columns: code, name, status (`StatusBadge`), revision. (`document_type` omitted; SDTM aggregates are datasets, column adds no signal — code/name/status/revision only.)
- Header: "SDTM datasets".

### 3. ADaM — `routes/_app/adam.tsx`

- Scope: study-scoped. Hook (3-positional, pass `undefined` for params): `useListAdamAggregates(currentStudyId ?? '', undefined, { query: { enabled: !!currentStudyId } })`. Rows: `data?.items ?? []`.
- Columns: code, name, status (`StatusBadge`), revision.
- Header: "ADaM datasets".

### 4. TLF — `routes/_app/tlf.tsx`

- Scope: study-scoped. Hook (3-positional, pass `undefined` for params): `useListTlfAggregates(currentStudyId ?? '', undefined, { query: { enabled: !!currentStudyId } })`. Rows: `data?.items ?? []`.
- Columns: code, name, status (`StatusBadge`), revision.
- Header: "Tables, Listings & Figures".

### 5. Documents — `routes/_app/documents.tsx`

- Scope: study-scoped. Hook (2-positional, options is the second arg): `useListDocuments(currentStudyId ?? '', { query: { enabled: !!currentStudyId } })`.
- Rows: `data ?? []` (ARRAY response).
- Columns: document_code, name, document_type, status (`StatusBadge`), revision, updated_at (formatted date).
- Header: "Documents".

### 6. Standards — `routes/_app/standards.tsx`

- Scope: GLOBAL. Tabbed layout (`tabs` primitive) with three tabs:
  - **Products** — `useListStandards()`, rows `data ?? []`, columns: code, name, provider, family, product_type, scope.
  - **Terminology releases** — `useListReleases()`, rows `data ?? []`, columns: code, version, provider, product, lifecycle (`StatusBadge`), content_schema_version.
  - **Templates** — `useListTemplates()`, rows `data ?? []`, columns: code, name (CatalogIdentity has only id/code/name).
- Each tab is its own `ResourceTable` with its own hook, so a slow/failed tab doesn't block the others. Queries for inactive tabs still mount (TanStack Query caches them); acceptable at this scale.
- Header: "Standards catalog".

### 7. Terminology — `routes/_app/terminology.tsx`

- Tabbed layout mixing a GLOBAL catalog and a study-scoped list:
  - **Releases** (global) — `useListReleases()`, same columns as the Standards "Terminology releases" tab.
  - **Study extensions** (study-scoped, 2-positional hook — options is the second arg) — `useListExtensions(currentStudyId ?? '', { query: { enabled: !!currentStudyId } })`, rows `data ?? []` (array), columns: code, name, codelist_code, status (`StatusBadge`), revision. Same no-study empty state as other scoped screens.
- `useListCodelists(releaseId, ...)` is deliberately NOT surfaced here: it requires a `releaseId` and belongs to a release-detail drill-down that is out of scope (no detail route in this task). Documented so the implementer doesn't try to wire it top-level.
- Header: "Terminology".

### 8. Validation — `routes/_app/validation.tsx`

- Tabbed layout:
  - **Rules** (global) — `useListRules()`, rows `data ?? []`, columns: rule_id, version, module_key, default_severity (`StatusBadge`), mandatory (render Yes/No).
  - **Platform rule packs** (global) — `useListPlatformRulePacks()`, rows `data ?? []`, columns: code, name, lifecycle (`StatusBadge`), revision, updated_at.
  - **Study rule packs** (study-scoped, 2-positional hook — options is the second arg) — `useListStudyRulePacks(currentStudyId ?? '', { query: { enabled: !!currentStudyId } })`, rows `data ?? []`, columns: code, name, lifecycle (`StatusBadge`), revision, updated_at. No-study empty state.
- Header: "Validation".

### 9. Reconciliation — `routes/_app/reconciliation.tsx`

- SPECIAL: no list endpoint. Lookup-by-id screen.
- A controlled `Input` for a reconciliation run id plus a "Look up" `Button`. On submit, set a `runId` state value and enable the two queries:
  - `useGetReconciliation(runId, { query: { enabled: !!runId } })` → `ReconciliationResponse`.
  - `useListReconciliationIssues(runId, { query: { enabled: !!runId } })` → `ListReconciliationIssues200Item[]`.
- Before any lookup: `EmptyState` ("Enter a reconciliation run id to view its result."). This is informative, not an error.
- On loaded run: a summary `Card` showing reconciliation_type, reconciliation_version, status (`StatusBadge`), error_count / warning_count / info_count, started_at/completed_at (formatted). Below it, a `ResourceTable` of issues. Issue items are untyped records (`ListReconciliationIssues200Item` = `{ [key: string]: unknown }`, verified), so the issues table derives its columns dynamically. Column set and cell contract are specified precisely to handle ragged (heterogeneous) records:
  - **Columns** are the UNION of keys across all issues, computed once and stably ordered by first appearance: `const keys = Array.from(new Set(issues.flatMap((i) => Object.keys(i))))`. Deriving from only the first issue is wrong — it drops keys that appear only in later issues.
  - **Cell contract** for each key: `const v = (issue)[key]; return v == null ? '—' : typeof v === 'object' ? JSON.stringify(v) : String(v)`. This covers nulls (em-dash), objects/arrays (JSON string, never the `[object Object]` that bare `String()` would produce), and primitives.
  - **Fallback**: only when the union `keys` is empty (every issue is `{}` or the list is empty) does the table use a single synthetic `raw` column rendering `JSON.stringify(issue)`; with a non-empty union there is no raw column.
  - `getRowId` falls back to the array index (`String(i)`) since no stable id is guaranteed on the record.
- Header: "Reconciliation".

### 10. Review — `routes/_app/review.tsx`

- Scope: study-scoped. Hook (2-positional, options is the second arg): `useListReviewItems(currentStudyId ?? '', { query: { enabled: !!currentStudyId } })`. Rows: `data ?? []` (array).
- Columns: target_module, target_entity_type, question (truncated), priority (`StatusBadge`), status (`StatusBadge`), updated_at.
- Header: "Review items".

### 11. Packaging — `routes/_app/packaging.tsx`

- SPECIAL: no submission-package list hook. Uses `useListArtifacts(currentStudyId ?? '', undefined, { query: { enabled: !!currentStudyId } })`. Rows: `data?.items ?? []` (collection).
- Columns: module, artifact_type, filename, media_type, size (right-aligned, formatted bytes), status (`StatusBadge`), created_at.
- Header text makes the framing explicit: "Submission artifacts" with a description noting these are the generated artifacts available for packaging (there is no package-list API yet). No-study empty state.

### 12. Integrations — `routes/_app/integrations.tsx`

- Scope: study-scoped. Hook (2-positional, options is the second arg): `useListIntegrations(currentStudyId ?? '', { query: { enabled: !!currentStudyId } })`. Rows: `data ?? []` (array).
- Columns: integration_code, display_name, direction, status (`StatusBadge`), revision, updated_at.
- Header: "Integrations".

(That is twelve route files — the authoritative count. The task's "~11 module screens" is approximate; all twelve placeholder routes under `src/routes/_app/` are covered here.)

## Edge cases

- **Zero studies**: the study switcher shows a disabled "No studies" trigger; every study-scoped screen shows the "Create a study first" `EmptyState` (not an error) because its query is disabled while `currentStudyId` is null.
- **Stale persisted study id**: the persisted id is validated against `data.items` on load; if absent, selection falls back to the first study and storage is rewritten. Prevents a scoped page firing a query for a study the principal can no longer see.
- **401 mid-session**: the axios response interceptor clears the token; `onAuthChange` nulls the auth user; the next navigation hits the `_app` guard and redirects to `/login`. Screens additionally render the 401-specific `ErrorState` copy if a request 401s before redirect.
- **Undefined optional fields** (`document_type`, nullable params-derived fields): rendered as an em-dash `—` by the default cell renderer / explicit cell functions.
- **Empty issue list on a valid reconciliation run**: the summary card still renders; the issues `ResourceTable` shows its empty state ("No reconciliation issues").
- **Column derivation from untyped/ragged issues**: columns are the union of keys across all issues (`Array.from(new Set(issues.flatMap(Object.keys)))`), not just the first issue's keys, so keys that appear only in later issues still render. Cell values follow `v == null ? '—' : typeof v === 'object' ? JSON.stringify(v) : String(v)`. The single synthetic "raw" column (`JSON.stringify(issue)`) is used ONLY when that union is empty (all issues are `{}`).
- **Date formatting**: a small `formatDate(iso?: string | null)` helper (in `src/lib/utils.ts` alongside `cn`) returns `—` for null/undefined and a locale date-time string otherwise. Used by `updated_at` / `created_at` / `started_at` columns. No new date library.
- **Byte formatting**: a `formatBytes(n?: number)` helper in `src/lib/utils.ts` for the artifact size column.

## Input validation

The only free-text input in scope is the reconciliation run id.

- **reconciliation run id** (Reconciliation screen): required to run the lookup. Trimmed on submit; the "Look up" button is disabled when the trimmed value is empty, and the query stays disabled (`enabled: !!runId`), so an empty id never hits the API. No format assertion is enforced client-side (the backend owns id validity); if the id is unknown, the backend returns 404 and the screen renders `ErrorState` (see error handling). This is intentional: the frontend does not duplicate the backend's id-format rules.

All other inputs are selections (study switcher, tab triggers) whose values come from server data, so no additional validation applies. List/filter query params exist in the generated models but are not wired to UI inputs in this scope, so there is nothing to validate there.

## Error handling (per operation)

Every data-bound screen delegates to `ResourceTable` / `ErrorState`, giving one consistent policy:

| Operation                                                     | Failure condition               | Recoverable?                                                                                                                                 | What the caller sees                                                                                                                                                                                       | Logging                                                                                                                                                                                   |
| ------------------------------------------------------------- | ------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Any `useListXxx` / `useGetXxx` returns `isError`              | network error, 5xx, 4xx         | Recoverable — TanStack Query retries once (`retry: 1` in `query-client.ts`), then surfaces the error; a later navigation/refetch can succeed | `ErrorState` card: title "Could not load {resource}", description = 401-specific message or `error.message ?? 'Request failed.'`                                                                           | Not logged beyond the browser console; no telemetry sink exists in the app. The axios interceptor already handles the 401 side effect (token clear). No `console.error` added by screens. |
| 401 on any request                                            | expired/absent token            | Recoverable via re-login                                                                                                                     | interceptor clears token → guard redirects to `/login`; if the response renders first, `ErrorState` shows the "Not authenticated" copy                                                                     | Interceptor-level only (existing behavior)                                                                                                                                                |
| 404 on `useGetReconciliation` / `useListReconciliationIssues` | unknown run id                  | Recoverable — user can enter a different id                                                                                                  | `ErrorState` with the generic message (the run id lookup simply failed); the input remains so the user can retry                                                                                           | Console only                                                                                                                                                                              |
| `useCurrentStudy()` studies query error                       | studies list failed to load     | Recoverable                                                                                                                                  | study switcher renders disabled; scoped screens render `ErrorState` for their own query (which will also be in error since it is disabled/won't run) — the switcher's disabled state is the primary signal | Console only                                                                                                                                                                              |
| localStorage read/write throws                                | private mode / disabled storage | Recoverable (degrades)                                                                                                                       | silently falls back to in-memory selection; no user-facing error                                                                                                                                           | Swallowed, matching `auth.ts`                                                                                                                                                             |

Fatal (unrecoverable) conditions: none in this read-only scope. There are no mutations, so there is no partial-write or rollback concern.

Error typing and imports: each generated hook's error is `ErrorType<HTTPValidationError>`, where `ErrorType<E> = AxiosError<E>` is defined and exported from **`src/api/axios-instance.ts`** (import as `import type { ErrorType } from '@/api/axios-instance'`) — it is NOT part of the read-only `src/api/generated/**` tree, so do not look for it there. The payload model `HTTPValidationError` is imported from `@/api/generated/model`. The shared `ErrorState`/`ResourceTable` prop is typed `AxiosError | null` (imported from `axios`) rather than `ErrorType<unknown>`, because `AxiosError<HTTPValidationError>` is not assignable to `AxiosError<unknown>` under strict TS (see the "Error-prop typing" note under `ResourceTable`); the hooks' error passes through to the `AxiosError` prop with no cast. `ErrorState` reads `error?.response?.status` and `error?.message` defensively.

## Invariant ownership

- **"Scoped screens never query without a study"**: owned by each screen via `enabled: !!currentStudyId` on the query options. Enforced at the screen layer (not the provider) because the provider has no knowledge of which screen is mounted; the screen is the only place that pairs a `studyId` with a specific hook. This keeps the provider a pure selection store.
- **"Exactly one selected study, persisted"**: owned by `StudyProvider`. It is the single writer of `localStorage['aurinara.currentStudy']` and the single source of `currentStudyId`. No screen writes the key. Centralized because multiple writers would race.
- **"Generated client is read-only"**: owned by convention + the Orval banner in each file; no screen imports from or edits `src/api/generated/**` except to call exported hooks and import model types.
- **"One loading/error/empty contract"**: owned by `ResourceTable`. Screens may not hand-roll their own skeleton/error/empty markup; they pass `isLoading/isError/error/rows` through. Centralized so the UX stays uniform and a future change (e.g. a shared retry button) lands in one place.

## Testability

- **Unit-testable (pure, no network)**:
  - `StatusBadge` status→variant mapping (table-driven).
  - `formatDate` / `formatBytes` helpers (edge: null, 0, large numbers).
  - `ResourceTable` rendering logic — the four-way loading/error/empty/rows switch — rendered with React Testing Library against static props (no hooks). This is the highest-value unit test because every screen depends on it.
  - `StudyProvider` selection logic — persisted-id-valid, persisted-id-stale, empty-list, storage-throws — by mocking `useListStudies` and `localStorage`. The reducer-like selection resolution is pure enough to test in isolation.
- **Integration-testable (hooks + MSW)**: each screen rendered inside a `QueryClientProvider` + `StudyProvider` with the API mocked via MSW, asserting loading → rows and loading → error transitions. The array-vs-collection normalization (`data?.items ?? []` vs `data ?? []`) is a likely bug source and is worth an integration assertion per response shape (one collection example, one array example suffices).
- **Not currently set up**: the repo has no test runner (`package.json` has no `test` script and no vitest/jest dep). This design does not require adding one for the screens to function, but if tests are desired the standard choice for a Vite + React + TS app is **Vitest + React Testing Library + MSW**; adding it is a separate, optional task. Flagged, not assumed.
- A design note on testability: the array-vs-collection split is the main source of fragility. Keeping the normalization in the screen (one short line) rather than inside `ResourceTable` keeps `ResourceTable` testable with a plain `T[]` and makes each screen's normalization explicit and reviewable.

## Files summary

New:

- `src/components/study-provider.tsx`
- `src/components/layout/study-switcher.tsx`
- `src/components/layout/page-header.tsx`
- `src/components/data/resource-table.tsx`
- `src/components/data/states.tsx`
- `src/components/data/status-badge.tsx`
- `src/components/ui/table.tsx`
- `src/components/ui/select.tsx`
- `src/components/ui/tabs.tsx`

Modified:

- `src/routes/_app.tsx` (wrap shell in `StudyProvider`)
- `src/components/layout/header.tsx` (mount `StudySwitcher`)
- `src/lib/utils.ts` (add `formatDate`, `formatBytes`)
- `src/routes/_app/studies.tsx` (refactor to use `PageHeader` + `StatusBadge`; optional but keeps one source of truth)
- `package.json` (add `@radix-ui/react-select`, `@radix-ui/react-tabs`)
- The 12 placeholder routes: `raw.tsx`, `documents.tsx`, `sdtm.tsx`, `adam.tsx`, `tlf.tsx`, `standards.tsx`, `terminology.tsx`, `validation.tsx`, `reconciliation.tsx`, `review.tsx`, `packaging.tsx`, `integrations.tsx`.

Deleted/retired:

- `src/components/layout/module-placeholder.tsx` becomes unused once all routes are wired; remove it after the last route is migrated to avoid a dangling import.

Not touched: anything under `src/api/generated/**`.

## Verification plan for the implementer

After implementation: `npm install` (for the two new Radix deps), then `npm run typecheck` and `npm run build` (`tsc -b && vite build`). TanStack Router's `autoCodeSplitting` regenerates `routeTree.gen.ts` on dev/build; no manual route registration is needed since the files already exist under `src/routes/_app/`. Run `npm run lint` to catch the project's eslint rules (notably the `react-refresh/only-export-components` rule that `auth-provider.tsx` disables for its hook export — `study-provider.tsx` and `useCurrentStudy` need the same disable comment).

## Responses to design review findings

Review verdict was CHANGES_REQUESTED (2 HIGH, 2 MEDIUM, 5 NIT). Before revising, the disputed hook signatures and the `ErrorType` definition were re-verified against the generated sources: `src/api/generated/sdtm/sdtm.ts` confirms `useListSdtmAggregates(studyId: string, params?: ListSdtmAggregatesParams, options?)` (3-positional) with `TError = ErrorType<HTTPValidationError>`; `src/api/generated/documents/documents.ts` confirms `useListDocuments(studyId: string, options?)` (2-positional); `src/api/axios-instance.ts` confirms `export type ErrorType<Error> = AxiosError<Error>`. Every finding was found accurate and all HIGH/MEDIUM findings are addressed; NITs addressed too.

- **Finding 1 (HIGH) — aggregate hook arity.** ADDRESSED. Added a locked "Hook arity rule" to the "Generated API — verified facts" section distinguishing 3-positional aggregate/artifact hooks from 2-positional array hooks, and spelled out the full `(studyId, undefined, { query })` call for SDTM, ADaM, and TLF (Raw and Packaging already had it).
- **Finding 2 (HIGH) — `ResourceTable` error prop not assignable.** ADDRESSED. Changed the `error` prop on both `ResourceTable` and `ErrorState` from `ErrorType<unknown>` to `AxiosError | null` (imported from `axios`), with a locked decision note explaining the contravariance that makes `AxiosError<HTTPValidationError>` → `AxiosError<unknown>` fail, and why `AxiosError<unknown, any>` (axios's default) accepts the hooks' error unchanged. Recorded the rejected generic-over-`E` alternative with reasoning.
- **Finding 3 (MEDIUM) — scoped array-hook calls underspecified.** ADDRESSED. Annotated the 2-positional call shape inline on Documents, Review, Integrations, Terminology→Study extensions, and Validation→Study rule packs; all now show the concrete `(studyId, { query })` form and reference the arity rule.
- **Finding 4 (MEDIUM) — reconciliation column derivation.** ADDRESSED. Section 9 and the edge-case bullet now specify the union-of-keys column set (`Array.from(new Set(issues.flatMap(Object.keys)))`) and the exact cell contract (`v == null ? '—' : typeof v === 'object' ? JSON.stringify(v) : String(v)`), with the single `raw` JSON column used only when the union is empty.
- **Finding 5 (NIT) — StatusBadge invented statuses.** ADDRESSED. Noted the mapping is a best-effort cosmetic lookup over free-form `string` with a `secondary` default (and case-insensitive); no screen depends on a specific variant.
- **Finding 6 (NIT) — `ErrorType` import location.** ADDRESSED. The error-typing paragraph now states `ErrorType` is imported from `@/api/axios-instance` (not the generated tree) and `HTTPValidationError` from `@/api/generated/model`.
- **Finding 7 (NIT) — screen count 11 vs 12.** ADDRESSED. Overview and the per-screen closing note now say "twelve" consistently and flag the task's "~11" as approximate with the twelve enumerated screens as authoritative.
- **Finding 8 (NIT) — unused `useListReferences`/`useListModules` rows.** ADDRESSED. Both rows are kept but marked (†) as catalogued for completeness and intentionally not surfaced, mirroring the deferred `useListCodelists` note.
- **Finding 9 (NIT) — switcher placement vs search box `md:` gating.** ADDRESSED. The study-switcher section now anchors placement as "immediately before the `ml-auto` cluster," states the switcher is always visible with its own `max-w` + truncation, and explains the search box's `md:block` gating does not apply to it.
