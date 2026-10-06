# Implementation Plan — Standards catalog drill-down

Read-only (GET) hierarchical detail navigation for the Standards catalog screen.
Work directly in `e:\Work\EDETEK\Python\aurinara\frontend` on branch `master`.
Commit locally, DO NOT push. No new dependencies.

## Design decisions (grounded in the codebase)

### D1. Flat param routes keyed on the entity's own id (not deep nesting)
There are currently **no dynamic-param routes** in the repo (all `_app/*` routes are
flat, e.g. `_app/standards.tsx`). Every detail GET hook takes **only that entity's own
id** — `useGetStandardVersion(versionId)`, `useGetStandardVersion`/`useGetCodelist(codelistId)`,
`useGetTemplateVersion(versionId)` — the parent id is never a parameter of the GET.
Therefore nesting a version under a product path (`.../products/$standardId/versions/$versionId`)
would force a route to carry a `$standardId` param it never uses, and `useParams` would
have to track it. Chosen layout: **one level of nesting for the parent→child list screens**
(product, release, template detail), and **flat routes for the leaf detail screens**
(version, codelist). Each route file declares exactly the param(s) it needs. Back links are
built from the data the detail already loads (e.g. a version's `product_id`) or from a
plain `Link to="/standards"`, so flat leaves lose no up-navigation.

TanStack Router file-based routing + `@tanstack/router-plugin` (`autoCodeSplitting: true`,
see `vite.config.ts`) regenerates `src/routeTree.gen.ts` on build and rewrites each file's
`createFileRoute('...')` path arg from the file location. We never edit `routeTree.gen.ts`
by hand. The `createFileRoute` id string in each new file must match its on-disk path under
`src/routes/`; the plugin corrects it on the next build if it drifts.

### D2. Route-file tree to create (under `src/routes/_app/`)
```
src/routes/_app/standards.tsx                      (MODIFY — keep tabbed index, add onRowClick)
src/routes/_app/standards/products/$standardId.tsx (NEW — product header + versions table)
src/routes/_app/standards/versions/$versionId.tsx  (NEW — version header + Assets/Compat tabs)
src/routes/_app/standards/releases/$releaseId.tsx  (NEW — release header + codelists table)
src/routes/_app/standards/codelists/$codelistId.tsx(NEW — codelist header + terms table)
src/routes/_app/standards/templates/$templateId.tsx(NEW — template header + versions table)
```
Note: adding `src/routes/_app/standards/*` sibling to the existing `src/routes/_app/standards.tsx`
is the standard TanStack pattern for a route that is both a page and a path prefix; the plugin
treats `standards.tsx` as `/_app/standards` and `standards/products/$standardId.tsx` as
`/_app/standards/products/$standardId`. This is supported and type-checks.

### D3. Shared DetailHeader component
Create `src/components/data/detail-header.tsx` to avoid copy-paste across the five detail
screens and keep the shadcn (new-york/zinc) look consistent. Shape:
```tsx
export interface DetailField {
  label: string
  value: React.ReactNode   // caller pre-formats (StatusBadge, formatDate, '—', etc.)
}
export interface DetailHeaderProps {
  fields: DetailField[]
}
export function DetailHeader({ fields }: DetailHeaderProps)
```
Renders a `Card` + `CardContent` with a responsive definition-list grid
(`grid grid-cols-2 md:grid-cols-3 gap-x-6 gap-y-3`); each field is a small block with a
`text-muted-foreground text-xs` label over the value. Loading state is handled by the caller
(render `Skeleton` rows while `isLoading`); error via the existing `ErrorState`.
The PageHeader (title = entity name) and a ghost back `Button` wrapped in `Link` sit above it.

### D4. Nullable field handling
All `*Response*` alias types verified as `string | null` (e.g.
`StandardVersionResponsePublicationDate`, `StandardAssetResponseTitle`,
`StandardAssetResponseCanonicalHref`, `TermResponseConceptId`, `CodelistResponseConceptId`).
Use `formatDate(iso)` from `src/lib/utils.ts` for dates (it already returns `'—'` for null/invalid),
and `value ?? '—'` for other nullable strings. `canonical_href`: when non-null render an
external `<a href={href} target="_blank" rel="noreferrer" className="underline">` ; when null
render `'—'`. Never render raw objects: `StandardVersionResponseCompatibility` /
`*Provenance` / `*Evidence` are `{ [key: string]: unknown }` — do NOT put them in a column;
if shown at all, render `JSON.stringify(value)` inside a `<pre>` or simply omit. Default plan omits them.

### D5. Reuse, do not reinvent
- `ResourceTable` already supports `onRowClick` and already applies `cursor-pointer hover:bg-muted/50`
  when `onRowClick` is set (verified in `src/components/data/resource-table.tsx`). Wire navigation
  through it; no new clickable affordance needed.
- `ResourceColumn<T> = { key; header; cell?; className? }`; default cell renders
  `String(row[key] ?? '—')`.
- `error` from the generated hooks is `ErrorType<HTTPValidationError>` (an `AxiosError`) and is
  already passed straight into `ResourceTable` in the existing index — assignable, no cast.
- `ErrorState` shows the standard "Not authenticated…" message on 401 — rely on it; do not add
  auth gating logic. Detail queries run under `_app` (no study gating needed; catalog endpoints
  are global). The id param is always present on a detail route, so queries fire unconditionally;
  pass `enabled` only where a child list depends on an id derived from a prior query (none here —
  all ids come from route params).
- Navigate with the typed router: `const navigate = Route.useNavigate()` (or `useNavigate()` from
  `@tanstack/react-router`) and `navigate({ to: '/standards/versions/$versionId', params: { versionId: row.id } })`.
  Read params with `const { versionId } = Route.useParams()`.
- `Link` from `@tanstack/react-router` + `Button` `variant="ghost"` for back links (pattern already
  used in `app-sidebar.tsx`, `user-nav.tsx`).

## Verified hook signatures (src/api/generated/provider-catalogs/provider-catalogs.ts)
- `useListStandards(params?)` -> `StandardProductResponse[]`
- `useGetStandard(standardId)` -> `StandardProductResponse`
- `useListStandardVersions(standardId, params?)` -> `StandardVersionResponse[]`
- `useGetStandardVersion(versionId)` -> `StandardVersionResponse`
- `useListStandardAssets(versionId)` -> `StandardAssetResponse[]`
- `useListStandardCompatibilities(versionId)` -> `StandardCompatibilityResponse[]`
- `useListReleases(params?)` -> `TerminologyReleaseResponse[]`
- `useGetRelease(releaseId)` -> `TerminologyReleaseResponse`
- `useListCodelists(releaseId, params?)` -> `CodelistResponse[]`
- `useGetCodelist(codelistId)` -> `CodelistResponse`
- `useListTerms(codelistId, params?)` -> `TermResponse[]`
- `useListTerminologyCompatibilities(releaseId)` -> `TerminologyCompatibilityResponse[]`
- `useListTerminologyAssets(releaseId)` -> `TerminologyAssetResponse[]`
- `useListTemplates(params?)` -> `CatalogIdentity[]`
- `useGetTemplate(templateId)` -> `CatalogIdentity`  (NOTE: NOT a template-specific response)
- `useListTemplateVersions(templateId)` -> `TemplateVersionResponse[]`
- `useGetTemplateVersion(versionId)` -> `TemplateVersionResponse`  (not needed by the planned screens)

## Verified model fields (src/api/generated/model)
- `StandardProductResponse`: id, code, name, provider, family, product_type, scope
- `StandardVersionResponse`: id, product_id, version, publication_date(string|null), library_href(string|null),
  content_schema_version, lifecycle, checksum, provenance(obj), applicable_modules(string[]),
  purposes(string[]), compatibility(obj), created_at
- `StandardAssetResponse`: id, version_id, role, media_type, checksum, required(bool),
  canonical_href(string|null), title(string|null), resource_type(string|null), content_schema_version
- `StandardCompatibilityResponse`: id, source_version_id, target_version_id, relationship, required(bool), evidence(obj)
- `TerminologyReleaseResponse`: id, code, version, provider, product, publication_date(string|null),
  library_href(string|null), content_schema_version, lifecycle, checksum, applicable_modules(string[]),
  provenance(obj), created_at
- `CodelistResponse`: id, release_id, code, name, concept_id(string|null), submission_value(string|null),
  definition(string|null), preferred_term(string|null), synonyms(string[]), extensible(bool)
- `TermResponse`: id, codelist_id, code, concept_id(string|null), submission_value, decode,
  definition(string|null), preferred_term(string|null), synonyms(string[]), status
- `TerminologyCompatibilityResponse`: id, release_id, standard_version_id, terminology_scope,
  standard_purpose, relationship, evidence(obj)
- `TerminologyAssetResponse`: id, release_id, role, media_type, checksum, canonical_href(string),
  title(string|null), resource_type(string|null), content_schema_version
- `TemplateVersionResponse`: id, family_id, version, lifecycle, checksum, applicable_modules(string[]),
  artifact_types(string[]), content_schema_versions(string[]), renderer_versions(string[]),
  blank_structure(obj), provenance(obj), created_at
- `CatalogIdentity`: id, code, name

## Gate commands (run from `e:\Work\EDETEK\Python\aurinara\frontend`)
- Build/type-check: `npm run build`  (= `tsc -b && vite build`) MUST pass with zero type errors.
- Lint: `npm run lint`  MUST have zero errors (3 pre-existing `react-refresh/only-export-components`
  warnings on `badge.tsx`, `button.tsx`, `sidebar.tsx` are acceptable).
- Baseline confirmed green before this work (build ok, lint = 0 errors / 3 warnings).
- `npm install` NOT needed (no new deps). Do NOT run a blocking dev server.
- NEVER edit `src/api/generated/**` or `src/routeTree.gen.ts`.

---

## Ordered implementation items

- [ ] 1. Create the shared `DetailHeader` component.
      Card-based definition list per D3: props `{ fields: { label: string; value: React.ReactNode }[] }`,
      responsive grid, muted labels. No data fetching inside; purely presentational.
      Files: src/components/data/detail-header.tsx
      Verify: `npm run build` and `npm run lint` — zero type errors, zero lint errors (3 warnings OK).
      (Component is unused until item 2+, but it must compile; it will be imported next.)

- [ ] 2. Make the Standards index rows navigable (keep tabbed structure).
      In `standards.tsx` add `const navigate = Route.useNavigate()` (import kept) and pass
      `onRowClick` to each tab's `ResourceTable`:
      product -> `navigate({ to: '/standards/products/$standardId', params: { standardId: row.id } })`;
      release -> `/standards/releases/$releaseId`; template -> `/standards/templates/$templateId`.
      Pass `navigate` into the `ProductsTab`/`ReleasesTab`/`TemplatesTab` (via prop or move the hook into
      each tab with `useNavigate()`). Do not change columns or tab labels.
      Files: src/routes/_app/standards.tsx
      Verify: `npm run build` — the new route path strings type-check against the regenerated tree
      (requires items 3,5,7 route files to exist for the typed `to` to resolve; see note). Build the
      route files first OR temporarily rely on the plugin; recommended order is items 3→4 then 5→6 then
      7, then wire 2 last. See item 8 for the final wiring+build.
      NOTE: because typed `navigate({ to })` needs the target routes to exist in the generated tree,
      do item 2's edits together with the detail-route files; sequence below creates routes first.

- [ ] 3. Create the product detail route: header + versions table.
      `useGetStandard(standardId)` for the header (DetailHeader fields: Code, Name, Provider, Family,
      Product type, Scope). `useListStandardVersions(standardId)` for a `ResourceTable` of versions with
      columns: version, lifecycle (StatusBadge), content_schema_version, publication_date (formatDate),
      created_at (formatDate). Row click -> `navigate({ to: '/standards/versions/$versionId', params: { versionId: row.id } })`.
      PageHeader title = `${product.code} — ${product.name}` (guard while loading); ghost back `Button`
      in `Link to="/standards"`. Handle loading (Skeleton header + table loading), error (ErrorState),
      empty (ResourceTable default).
      Files: src/routes/_app/standards/products/$standardId.tsx
      Verify: `npm run build` + `npm run lint` — zero errors.

- [ ] 4. Create the standard version detail route: header + Assets/Compatibilities tabs.
      `useGetStandardVersion(versionId)` header (DetailHeader: Version, Lifecycle (StatusBadge),
      Content schema, Checksum, Publication date (formatDate), Created (formatDate),
      Applicable modules (`applicable_modules.join(', ') || '—'`), Purposes (join)). Two `Tabs`:
      Assets -> `useListStandardAssets(versionId)` table columns: role, media_type, checksum,
      title (`?? '—'`), resource_type (`?? '—'`), required (bool -> 'Yes'/'No'), canonical_href
      (external `<a>` when non-null else '—'); Compatibilities -> `useListStandardCompatibilities(versionId)`
      table columns: relationship, target_version_id, required (bool). Do NOT fetch asset CONTENT
      (`useGetStandardAssetContent` is binary — not used). Back link to the parent product via
      `Link to="/standards/products/$standardId" params={{ standardId: version.product_id }}` (shown once
      version is loaded) with a fallback `Link to="/standards"`.
      Files: src/routes/_app/standards/versions/$versionId.tsx
      Verify: `npm run build` + `npm run lint` — zero errors.

- [ ] 5. Create the terminology release detail route: header + codelists table.
      `useGetRelease(releaseId)` header (DetailHeader: Code, Version, Provider, Product, Lifecycle
      (StatusBadge), Content schema, Publication date (formatDate), Created (formatDate), Applicable
      modules (join)). `useListCodelists(releaseId)` table columns: code, name, submission_value (`?? '—'`),
      concept_id (`?? '—'`), extensible (bool -> 'Yes'/'No'). Row click ->
      `navigate({ to: '/standards/codelists/$codelistId', params: { codelistId: row.id } })`.
      Optionally render Terminology compatibilities (`useListTerminologyCompatibilities(releaseId)`) and
      assets (`useListTerminologyAssets(releaseId)`) in extra tabs/sections (relationship + standard_version_id
      for compat; role/media_type/canonical_href for assets). Back link `Link to="/standards"`.
      Files: src/routes/_app/standards/releases/$releaseId.tsx
      Verify: `npm run build` + `npm run lint` — zero errors.

- [ ] 6. Create the codelist detail route: header + terms table.
      `useGetCodelist(codelistId)` header (DetailHeader: Code, Name, Submission value (`?? '—'`),
      Concept id (`?? '—'`), Preferred term (`?? '—'`), Extensible (bool), Synonyms (join || '—')).
      `useListTerms(codelistId)` table columns: code, submission_value, decode (truncate class
      `max-w-sm truncate`), concept_id (`?? '—'`), preferred_term (`?? '—'`), status (StatusBadge).
      Back link to parent release via `Link to="/standards/releases/$releaseId" params={{ releaseId: codelist.release_id }}`
      once loaded, with `Link to="/standards"` fallback.
      Files: src/routes/_app/standards/codelists/$codelistId.tsx
      Verify: `npm run build` + `npm run lint` — zero errors.

- [ ] 7. Create the template detail route: header + versions table.
      `useGetTemplate(templateId)` returns `CatalogIdentity` -> header DetailHeader: Code, Name
      (only these three fields exist; id optional). `useListTemplateVersions(templateId)` table columns:
      version, lifecycle (StatusBadge), checksum, artifact_types (join || '—'),
      content_schema_versions (join || '—'), created_at (formatDate). No deeper drill required by the
      spec (template version detail route optional; omit unless trivial). Back link `Link to="/standards"`.
      Files: src/routes/_app/standards/templates/$templateId.tsx
      Verify: `npm run build` + `npm run lint` — zero errors.

- [ ] 8. Wire the index navigation (item 2 edits) now that all target routes exist, then full gate.
      Apply the `onRowClick` handlers in `standards.tsx` from item 2 so typed `navigate({ to })`
      resolves against the regenerated tree. Confirm the existing flat tabbed index still renders and
      rows show the pointer/hover affordance (provided automatically by ResourceTable when onRowClick set).
      Files: src/routes/_app/standards.tsx
      Verify: `npm run build` (zero type errors, routeTree.gen.ts regenerated by plugin — do not hand-edit)
      and `npm run lint` (zero errors; only the 3 known warnings). Manually sanity-read the generated
      route ids if the build reports a path mismatch and fix the `createFileRoute('...')` arg to match
      the file location.

- [ ] 9. Final verification + local commit.
      Run the full gate once more from a clean state; ensure no `any`, all nullable fields guarded,
      no edits to generated files. Commit locally on `master` (e.g.
      `git add src/components/data/detail-header.tsx src/routes/_app/standards.tsx "src/routes/_app/standards/*"`
      — stage specific paths, NOT `routeTree.gen.ts` unless the plugin regenerated it as part of the build;
      if routeTree.gen.ts changed from the build, include it as a generated artifact). DO NOT push.
      Files: (commit only)
      Verify: `npm run build` && `npm run lint` both green; `git status` clean after commit.

## Gaps / assumptions
- Template version leaf detail is omitted (spec says the template screen only needs versions; a
  version detail route is optional). Assumption: not required for done.
- Terminology compatibilities/assets sections on the release screen are optional per spec; plan
  includes them as extra tabs but they can be dropped if they complicate typing — the required path
  is release -> codelists -> terms.
- Object-valued fields (provenance/evidence/compatibility/blank_structure) are intentionally not
  surfaced as columns (opaque `{ [key: string]: unknown }`); only scalar/string[]/bool fields are shown.
