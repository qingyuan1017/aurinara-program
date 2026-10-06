# Implementation Plan — Frontend Mutations (Create / Edit) Buildout

Aurinara Clinical Artifact Platform — frontend (`e:\Work\EDETEK\Python\aurinara\frontend`).

This plan pins the exact component contracts for the create/edit buildout. The hard
decisions are already settled in the brief's FIXED DECISIONS and in
`mutations-design.md` as amended by `mutations-design-review.md` (the review fixes win
on every conflict). Everything below was verified against the generated client under
`src/api/generated/**` and the backend under `src/app` — hook names, operation
signatures, mutate-variable shapes, body-model fields, query-key getters, and If-Match /
Idempotency requirements are quoted from the sources, not assumed.

Work directly in the existing frontend on `master`. No worktree. Keep everything local;
do NOT push. NEVER edit `src/api/generated/**`, `src/routeTree.gen.ts`, or
`src/api/axios-instance.ts`. Do NOT modify backend code. Do NOT weaken the `_app`
`beforeLoad` auth guard.

Gate (run from `e:\Work\EDETEK\Python\aurinara\frontend`):
- `npm run build` (= `tsc -b && vite build`) MUST pass with zero type errors.
- `npm run lint` MUST have zero errors (the 3 pre-existing `react-refresh/only-export-components`
  warnings on shadcn ui files are acceptable; add no new error-level issues).
- `npm install` only once, to add `sonner` (the ONLY net-new dependency).

---

## Verified facts this plan is built on (do not re-derive)

Confirmed by reading the sources during planning:

- **Mutator** (`src/api/axios-instance.ts`): `customInstance(config, options)` does a shallow
  spread `{ ...config, ...options }`, so injecting `options.headers` REPLACES the generated
  `headers: { 'Content-Type': 'application/json' }`. Every header helper must re-emit
  `Content-Type: application/json`. The `request` field on a hook IS the axios config
  (`SecondParameter<typeof customInstance>` = `AxiosRequestConfig | undefined`); headers live
  at `request.headers`. There is no wrapper layer.
- **ETag** (`src/app/common/etag.py`): `etag_for_revision(n)` returns the literal string
  `"revision-{n}"` (embedded double-quotes included); `require_matching_etag` raises **428**
  `precondition_required` when `If-Match` is absent and **412** `precondition_failed` on
  mismatch (`hmac.compare_digest`). Derive `If-Match` from the entity's `revision` field.
- **Problem shape** (`src/app/common/problems.py`): `application/problem+json` with
  `type,title,status,detail,instance,code,request_id,issues[],errors[]`. Application errors
  fill `issues[]` (dicts carrying `code,severity,message,field_path,...`; `field_path` nullable).
  Transport 422 (`code="request_validation_failed"`) fills `errors[]` with
  `{ location: string[], message, type }` where every `location` item is stringified (e.g.
  `["body","value","fields","0","name"]`). This is NOT the generated `HTTPValidationError`.
- **Response models carry `revision: number`**: `StudyResponse`, `ReferenceResponse`,
  `ReviewItemResponse`, `IntegrationResponse`, `ExtensionResponse`, `SubscriptionResponse`,
  `AggregateResponse`. **`ExtensionTermResponse` has NO `revision`** — term writes use the
  extension's revision.
- **If-Match requirements** (verified in route handlers): required on `patchStudy`,
  `patchReference`, `retireReference`, `patchReviewItem` (item.revision), `patchIntegration`
  (integration.revision), `createExtensionTerm` / `patchExtensionTerm` / `deleteExtensionTerm`
  (ALL against the EXTENSION's revision). NOT required on `createStudy`, `createReference`,
  `createReviewItem`, `createComment`, `createIntegration`, `createSubscription`,
  `createExtension`, `createExtension`, `createRaw/Sdtm/Adam/TlfAggregate` (plain creates).
- **Mutate-variable shapes** (from `MutationFunction<...>` TVariables in each tag file):
  - `useCreateStudy` → `{ data: StudyCreate }` (NO studyId — collection-root POST)
  - `usePatchStudy` → `{ studyId; data: StudyPatch }`
  - `useCreateReference` → `{ studyId; data: ReferenceCreate }` (DEFERRED — see Decision 8)
  - `usePatchReference` → `{ referenceId; data: ReferencePatch }`
  - `useRetireReference` → `{ referenceId }` (no data; body-less DELETE)
  - `useCreateReviewItem` → `{ studyId; data: ReviewItemCreate }`
  - `usePatchReviewItem` → `{ itemId; data: ReviewItemPatch }`
  - `useCreateComment` → `{ itemId; data: CommentCreate }`
  - `useCreateIntegration` → `{ studyId; data: IntegrationWrite }`
  - `usePatchIntegration` → `{ integrationId; data: IntegrationPatch }`
  - `useCreateSubscription` → `{ integrationId; data: SubscriptionWrite }`
  - `useCreateExtension` → `{ studyId; data: ExtensionCreate }`
  - `useCreateExtensionTerm` → `{ extensionId; data: ExtensionTermWrite }`
  - `usePatchExtensionTerm` → `{ termId; data: ExtensionTermPatch }`
  - `useCreate{Raw,Sdtm,Adam,Tlf}Aggregate` → `{ studyId; data: AggregateCreate }`
- **Query-key getters** (all exist, exact arg signatures verified):
  - `getListStudiesQueryKey(params?)`, `getGetStudyQueryKey(studyId?)`
  - `getListReferencesQueryKey(studyId?)`, `getGetReferenceQueryKey(referenceId?)`
  - `getListReviewItemsQueryKey(studyId?)`, `getGetReviewItemQueryKey(itemId?)`, `getListCommentsQueryKey(itemId?)`
  - `getListIntegrationsQueryKey(studyId?)`, `getGetIntegrationQueryKey(integrationId?)`, `getListSubscriptionsQueryKey(integrationId?)`
  - `getListExtensionsQueryKey(studyId?)`, `getGetExtensionQueryKey(extensionId?)`, `getListExtensionTermsQueryKey(extensionId?)`
  - `getList{Raw,Sdtm,Adam,Tlf}AggregatesQueryKey(studyId?, params?)`
- **Body models** (fields + constraints) are pinned per-module below.
- **List shapes**: studies, references, aggregates = collection (`data?.items ?? []`); review
  items, integrations, extensions = array (`data ?? []`).

---

## Shared contracts to pin before any screen

### A. `src/lib/requests.ts` — header helpers (the ONLY place header strings are built)

```ts
import type { AxiosRequestConfig } from 'axios'

const JSON_CT = { 'Content-Type': 'application/json' } as const

/** If-Match for a conditional write, derived from the entity revision. */
export function ifMatchRequest(revision: number): AxiosRequestConfig {
  return { headers: { ...JSON_CT, 'If-Match': `"revision-${revision}"` } }
}

/** Idempotency-Key for an operation-creating POST (follow-up only; see Deferred). */
export function idempotentRequest(): AxiosRequestConfig {
  return { headers: { ...JSON_CT, 'Idempotency-Key': crypto.randomUUID() } }
}
```

Note the embedded double-quotes in the If-Match value — they are part of the opaque tag.
`idempotentRequest` ships now but is wired to NO trigger this pass (Decision 9).

### B. `src/lib/problems.ts` — problem-detail parsing

```ts
import type { AxiosError } from 'axios'

export interface ProblemIssue {
  code?: string
  severity?: string
  message?: string
  field_path?: string | null
  [key: string]: unknown
}
export interface ProblemTransportError {
  location: (string | number)[] | string[]
  message: string
  type: string
}
export interface ProblemDetail {
  detail?: string
  code?: string
  issues?: ProblemIssue[]
  errors?: ProblemTransportError[]
}

export function parseProblem(error: AxiosError): ProblemDetail {
  const data = error.response?.data
  // defensive: body may be absent (network/500) or a plain string
  return (data && typeof data === 'object' ? (data as ProblemDetail) : {})
}

/**
 * EXACT field matching (Decision 7, review Finding 5):
 * - errors[]: strip a leading "body" segment, join the REMAINDER with "." and compare
 *   the whole joined path to a descriptor field name. No fuzzy last-segment match.
 * - issues[]: compare field_path EXACTLY to a descriptor name.
 * Anything that does not match a field name goes to formErrors (top-level alert).
 */
export function mapProblemToFieldErrors(
  error: AxiosError,
  fieldNames: string[],
): { fieldErrors: Record<string, string>; formErrors: string[] }
```

Matching rule, pinned:
- For each `errors[]` entry: `loc = location.map(String)`; if `loc[0] === 'body'` take
  `loc.slice(1)` else `loc`; `path = joined.join('.')`. If `fieldNames.includes(path)` →
  `fieldErrors[path] = message`, else push `message` to `formErrors`.
- For each `issues[]` entry: if `field_path` is a non-null string and
  `fieldNames.includes(field_path)` → `fieldErrors[field_path] = message ?? code ?? 'Invalid.'`,
  else push `message ?? detail ?? code` to `formErrors`.
- When neither array is present, `formErrors = [detail ?? error.message ?? 'Request failed.']`.

Because every in-scope form is flat top-level fields (Decision 8), the exact match is
correct and nested paths (if any ever appear) land top-level harmlessly.

### C. Status precedence helper (Decision 6) — lives in `problems.ts` or the dialog

```ts
/** 412/428 detected by status ALONE (body-independent). 409 variant by code, then detail. */
export function stalenessAlert(error: AxiosError): string | null {
  const status = error.response?.status
  if (status === 412) return 'This record changed since you opened it. Reload and try again.'
  if (status === 428) return 'A required precondition header was missing — please retry.'
  if (status === 409) {
    const code = parseProblem(error).code
    if (code === 'idempotency_key_reused')
      return 'This action was already submitted with different inputs.'
    return parseProblem(error).detail ?? 'This change conflicts with the current state.'
  }
  return null
}
```

Checked BEFORE the generic field mapping. If it returns non-null, render it as the sole
top-level alert and skip field distribution.

### D. `ResourceFormDialog<TBody>` — the ONE reusable form

`src/components/forms/resource-form-dialog.tsx`.

```ts
import type { AxiosError } from 'axios'

export interface FieldDescriptor<TBody> {
  name: keyof TBody & string
  label: string
  control: 'text' | 'textarea' | 'select' | 'tags' | 'number'
  required?: boolean
  placeholder?: string
  options?: { label: string; value: string }[] // for 'select'
  helpText?: string
  maxLength?: number
  pattern?: { re: RegExp; message: string }
  min?: number
  max?: number // for 'number'
}

export interface ResourceFormDialogProps<TBody extends Record<string, unknown>> {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description?: string
  fields: FieldDescriptor<TBody>[]
  initialValues: Partial<TBody>
  submitLabel?: string // default 'Save'
  onSubmit: (body: TBody) => Promise<unknown> // receives ONLY the validated body
  isSubmitting: boolean // hook isPending, passed in by the screen
  submitError: AxiosError | null // hook error, passed in by the screen
  successMessage: string // sonner toast text on success
}
```

Contract, pinned (Decisions 2, 3, 4, 7):
- The dialog takes **NO** header/request/hook props. There is no `buildRequest`. The SCREEN
  owns the generated hook and computes `request` at hook-call time.
- `onSubmit` receives **only** the validated `TBody`. The SCREEN wraps path ids into the
  mutate variables (e.g. `onSubmit={(data) => patch.mutateAsync({ referenceId: row.id, data })}`).
- Local state: `useState<Partial<TBody>>(initialValues)`; re-seed on `open` transitioning to
  true (so edit prefills and create resets). Per-field error state cleared as the user edits a
  field that currently shows an error.
- Control mapping: `text`→Input, `textarea`→Textarea, `number`→Input[type=number] coerced to
  number, `select`→Select with `options`, `tags`→Input whose comma/enter-separated value
  splits/trims to `string[]` on submit (used for `allowed_modules`, `event_types`, `synonyms`).
- `validate(fields, values)` runs BEFORE `onSubmit`: required present (non-empty string / non-empty
  array), maxLength, pattern, number range. On any error, block submit, render per-field messages,
  make no request.
- Submit flow: validate → build `TBody` dropping empty optionals (so PATCH stays sparse;
  backend uses `model_dump(exclude_unset=True)`) → `await onSubmit(body)` → on resolve:
  `toast.success(successMessage)`, `onOpenChange(false)`, reset state (screen invalidates caches
  in its hook `onSuccess`) → on reject: stay open; run `stalenessAlert` first, else
  `mapProblemToFieldErrors` to distribute field + top-level errors.
- Submit button: `disabled` while `isSubmitting` or while validation currently has errors;
  shows `<Loader2 className="animate-spin" /> Saving…` when submitting. Cancel disabled while submitting.
- The dialog imports NO generated hook, so it stays generic over `TBody` and unit-testable with a
  stub `onSubmit`.

### E. `ConfirmDialog` — destructive confirm for retire/DELETE (Decision 5)

`src/components/forms/confirm-dialog.tsx`.

```ts
export interface ConfirmDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description?: React.ReactNode
  confirmLabel?: string // default 'Confirm'
  onConfirm: () => Promise<unknown>
  isPending: boolean
  error: AxiosError | null // run stalenessAlert + detail for the top-level message
  destructive?: boolean // style the confirm button variant="destructive"
}
```

Retire does NOT flow through `ResourceFormDialog`. The screen calls
`retire.mutateAsync({ referenceId: row.id })` with `useRetireReference({ request: ifMatchRequest(row.revision) })`.

### F. New shadcn/ui primitives + Toaster

- `src/components/ui/dialog.tsx` — Radix dialog wrapper (`@radix-ui/react-dialog` already present).
  Exports `Dialog, DialogTrigger, DialogContent, DialogHeader, DialogFooter, DialogTitle,
  DialogDescription, DialogClose`. new-york/zinc, `data-slot`, `X` close icon, no `cva`.
- `src/components/ui/textarea.tsx` — plain `<textarea>` mirroring `input.tsx` classes + `data-slot="textarea"`.
- `src/components/ui/form.tsx` — dependency-free presentational helpers `FormItem, FormLabel,
  FormControl, FormDescription, FormMessage` (take `error`/`id` via props; NO react-hook-form).
- `src/components/ui/sonner.tsx` — shadcn `Toaster` reading theme from `@/components/theme-provider`;
  re-export `toast` from `sonner`. `sonner@^1.5.0` added to `package.json`.
- Mount `<Toaster />` in `src/main.tsx` INSIDE `<ThemeProvider>` as a sibling of the provider tree
  (sibling of `AuthProvider`/`RouterProvider`), so it reads the theme (Decision 10 / review Finding 8).

### G. `ResourceTable` additive `rowActions` column

`src/components/data/resource-table.tsx` — ADD an OPTIONAL prop
`rowActions?: (row: T) => React.ReactNode`. When present, render one extra trailing
`<TableHead />` (empty or "Actions", `className="w-[1%] text-right"`) and one trailing
`<TableCell className="text-right">{rowActions(row)}</TableCell>` per row. Strictly additive:
when `rowActions` is undefined, the output is byte-identical to today, so all read-only screens
are untouched. Guard the extra header/cell behind `rowActions &&`.

---

## Ordered implementation plan

- [ ] 1. Add `sonner` dependency and create the four UI primitives.
      Add `"sonner": "^1.5.0"` to `package.json` dependencies; run `npm install`. Create
      `src/components/ui/dialog.tsx`, `src/components/ui/textarea.tsx`, `src/components/ui/form.tsx`,
      `src/components/ui/sonner.tsx` in new-york/zinc style (contract F). Mount `<Toaster />` inside
      `ThemeProvider` in `src/main.tsx`.
      Files: `package.json`, `src/components/ui/dialog.tsx`, `src/components/ui/textarea.tsx`,
      `src/components/ui/form.tsx`, `src/components/ui/sonner.tsx`, `src/main.tsx`.
      Verify: `npm run build` passes (new files type-check, Toaster mounts).

- [ ] 2. Create the request + problem helper libs.
      `src/lib/requests.ts` (`ifMatchRequest`, `idempotentRequest`; contract A) and
      `src/lib/problems.ts` (`ProblemDetail`/`ProblemIssue`/`ProblemTransportError` types,
      `parseProblem`, `mapProblemToFieldErrors`, `stalenessAlert`; contracts B+C).
      Files: `src/lib/requests.ts`, `src/lib/problems.ts`.
      Verify: `npm run build` passes.

- [ ] 3. Add the additive `rowActions` column to `ResourceTable`.
      Extend props with `rowActions?: (row: T) => React.ReactNode` (contract G), guarded so
      read-only screens stay byte-identical.
      Files: `src/components/data/resource-table.tsx`.
      Verify: `npm run build` passes AND `npm run lint` has zero new errors; existing screens
      (review.tsx, integrations.tsx, raw/sdtm/adam/tlf/documents) still render unchanged.

- [ ] 4. Build `ResourceFormDialog<TBody>` and `ConfirmDialog`.
      `src/components/forms/resource-form-dialog.tsx` (contract D — field descriptors, client
      validation, submit flow, problem-detail error distribution via `mapProblemToFieldErrors` +
      `stalenessAlert`, sonner success) and `src/components/forms/confirm-dialog.tsx` (contract E).
      Both import only UI primitives + the helper libs; neither imports a generated hook.
      Files: `src/components/forms/resource-form-dialog.tsx`, `src/components/forms/confirm-dialog.tsx`.
      Verify: `npm run build` passes. (Optional: a stub-`onSubmit` smoke test if a test runner is
      added; none exists today, so build is the gate.)

- [ ] 5. Studies: CREATE + EDIT on `studies.tsx`.
      Add a "New study" button in `PageHeader` `actions` opening `ResourceFormDialog<StudyCreate>`;
      add per-card (or per-row) "Edit" opening `ResourceFormDialog<StudyPatch>`. Hooks owned by the
      screen; see per-module contract below.
      Files: `src/routes/_app/studies.tsx`.
      Verify: `npm run build` + `npm run lint` zero errors; create and edit dialogs submit and the
      list refetches.

- [ ] 6. Reference: new screen with EDIT display_name + RETIRE.
      No reference route exists today (the read pass did not surface references). Create
      `src/routes/_app/reference.tsx` listing `useListReferences(currentStudyId ?? '', { query: { enabled: !!currentStudyId } })`
      (2-positional; collection → `data?.items ?? []`) with columns reference_type, natural_key,
      display_name, status (StatusBadge), revision, and a `rowActions` column with Edit + Retire.
      Add a sidebar nav entry `{ title: 'Reference', to: '/reference', icon: <pick a lucide icon> }`
      in the "Clinical modules" group of the sidebar nav file. Reference CREATE is DEFERRED (Decision 8).
      Files: `src/routes/_app/reference.tsx`, the sidebar nav component
      (`src/components/layout/app-sidebar.tsx` or wherever the nav array lives — grep `to: '/studies'`).
      Verify: `npm run build` (router regenerates the tree) + `npm run lint` zero errors; edit and
      retire work; the new nav link routes correctly.

- [ ] 7. Review: CREATE item + EDIT item + ADD COMMENT on `review.tsx`.
      "New review item" button → `ResourceFormDialog<ReviewItemCreate>`; `rowActions` Edit →
      `ResourceFormDialog<ReviewItemPatch>` (If-Match); "Comment" action → a comment dialog using
      `ResourceFormDialog<CommentCreate>` (no If-Match, no Idempotency).
      Files: `src/routes/_app/review.tsx`.
      Verify: `npm run build` + `npm run lint` zero errors; create/edit/comment all submit and refetch.

- [ ] 8. Integrations: CREATE integration + EDIT integration + CREATE subscription on `integrations.tsx`.
      "New integration" → `ResourceFormDialog<IntegrationWrite>`; `rowActions` Edit →
      `ResourceFormDialog<IntegrationPatch>` (If-Match); "Add subscription" →
      `ResourceFormDialog<SubscriptionWrite>` (no If-Match).
      Files: `src/routes/_app/integrations.tsx`.
      Verify: `npm run build` + `npm run lint` zero errors; all three flows submit and refetch.

- [ ] 9. Terminology: CREATE extension + ADD term + EDIT term on `terminology.tsx`.
      "New extension" → `ResourceFormDialog<ExtensionCreate>`; per-extension "Add term" →
      `ResourceFormDialog<ExtensionTermWrite>` with `useCreateExtensionTerm({ request: ifMatchRequest(extension.revision) })`;
      "Edit term" → `ResourceFormDialog<ExtensionTermPatch>` with
      `usePatchExtensionTerm({ request: ifMatchRequest(extension.revision) })`. After EACH term
      write succeeds, invalidate the extension detail key `getGetExtensionQueryKey(extensionId)` AND
      the list/terms keys so the next write sends a fresh extension revision (prevents sequential 412).
      Files: `src/routes/_app/terminology.tsx` (study-extensions tab).
      Verify: `npm run build` + `npm run lint` zero errors; create extension, then add two terms in a
      row (second must NOT 412), then edit a term — all succeed and refetch.

- [ ] 10. Clinical aggregates: CREATE-only on raw/sdtm/adam/tlf.
      Add a "New dataset/aggregate" button on each of `raw.tsx`, `sdtm.tsx`, `adam.tsx`, `tlf.tsx`
      opening `ResourceFormDialog<AggregateCreate>` wired to the module's create hook. Same pattern
      across all four files (one change pattern, four files).
      Files: `src/routes/_app/raw.tsx`, `src/routes/_app/sdtm.tsx`, `src/routes/_app/adam.tsx`,
      `src/routes/_app/tlf.tsx`.
      Verify: `npm run build` + `npm run lint` zero errors; create works on each and the list refetches.

- [ ] 11. Final gate + local commit.
      Run `npm run build` and `npm run lint` once more. Confirm: no dead buttons; read-only screens
      intact; auth guard intact; no generated/mutator/backend edits; the 3 pre-existing warnings are
      the only lint warnings. Commit locally on `master`. DO NOT push.
      Verify: `npm run build` zero type errors; `npm run lint` zero errors; `git status` clean after
      commit; `git log -1` shows the new local commit.

---

## Per-module contracts (hooks, request binding, fields, mutate variables, invalidation)

For every screen: `const qc = useQueryClient()`. The SCREEN owns the hook, computes `request`
at hook-call time, and sets `onSuccess` to invalidate the listed keys. The dialog's `onSubmit`
receives only the body; the screen wraps path ids.

### 5. Studies — `src/routes/_app/studies.tsx`

CREATE (no If-Match):
```ts
const create = useCreateStudy({
  mutation: { onSuccess: () => qc.invalidateQueries({ queryKey: getListStudiesQueryKey() }) },
  request: { headers: { 'Content-Type': 'application/json' } },
})
// onSubmit={(data) => create.mutateAsync({ data })}   // NOTE: { data } only, no studyId
```
`StudyCreate` fields: `code` (text, required, pattern `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`),
`name` (text, required, maxLength 255).

EDIT (If-Match from the study being edited):
```ts
const patch = usePatchStudy({
  mutation: { onSuccess: () => {
    qc.invalidateQueries({ queryKey: getListStudiesQueryKey() })
    qc.invalidateQueries({ queryKey: getGetStudyQueryKey(editing.id) })
  }},
  request: ifMatchRequest(editing.revision),
})
// onSubmit={(data) => patch.mutateAsync({ studyId: editing.id, data })}
```
`StudyPatch` fields: `name` (text, optional, `StudyPatchName = string | null`),
`status` (select, optional, `StudyPatchStatus = 'active' | 'closed' | null` → options active/closed).

### 6. Reference — `src/routes/_app/reference.tsx` (new)

List: `useListReferences(currentStudyId ?? '', { query: { enabled: !!currentStudyId } })`,
rows `data?.items ?? []` (collection). No-study empty state like other scoped screens.

EDIT display_name (If-Match from row.revision):
```ts
const patch = usePatchReference({
  mutation: { onSuccess: () => {
    qc.invalidateQueries({ queryKey: getListReferencesQueryKey(currentStudyId ?? undefined) })
    qc.invalidateQueries({ queryKey: getGetReferenceQueryKey(editing.id) })
  }},
  request: ifMatchRequest(editing.revision),
})
// onSubmit={(data) => patch.mutateAsync({ referenceId: editing.id, data })}
```
`ReferencePatch` fields IN SCOPE: `display_name` only (text, optional,
`ReferencePatchDisplayName = string | null`). Leave `value` untouched/passthrough (do NOT render
a control for it; `ReferencePatchValue = ReferenceValue | null`).

RETIRE (ConfirmDialog, If-Match from row.revision):
```ts
const retire = useRetireReference({
  mutation: { onSuccess: () => qc.invalidateQueries({ queryKey: getListReferencesQueryKey(currentStudyId ?? undefined) }) },
  request: ifMatchRequest(row.revision),
})
// onConfirm={() => retire.mutateAsync({ referenceId: row.id })}
```
CREATE is DEFERRED (Decision 8 — nested `value.fields[].name/value`, not flat).

### 7. Review — `src/routes/_app/review.tsx`

CREATE item (no If-Match):
```ts
const create = useCreateReviewItem({
  mutation: { onSuccess: () => qc.invalidateQueries({ queryKey: getListReviewItemsQueryKey(currentStudyId ?? undefined) }) },
  request: { headers: { 'Content-Type': 'application/json' } },
})
// onSubmit={(data) => create.mutateAsync({ studyId: currentStudyId!, data })}
```
`ReviewItemCreate` fields: `target_module` (text, required), `target_entity_type` (text, required),
`target_entity_id` (text, required), `field_path` (text, optional, `string | null`),
`question` (textarea, required, maxLength 4000), `assignee` (text, optional, `string | null`),
`priority` (text, optional).

EDIT item (If-Match from item.revision):
```ts
const patch = usePatchReviewItem({
  mutation: { onSuccess: () => {
    qc.invalidateQueries({ queryKey: getListReviewItemsQueryKey(currentStudyId ?? undefined) })
    qc.invalidateQueries({ queryKey: getGetReviewItemQueryKey(editing.id) })
  }},
  request: ifMatchRequest(editing.revision),
})
// onSubmit={(data) => patch.mutateAsync({ itemId: editing.id, data })}
```
`ReviewItemPatch` fields (all optional, each `string | null`): `assignee` (text), `priority` (text),
`status` (text — free-form `string | null`; use text unless the brief later enumerates values),
`disposition` (text), `resolution` (textarea).

ADD COMMENT (no If-Match, no Idempotency):
```ts
const comment = useCreateComment({
  mutation: { onSuccess: () => qc.invalidateQueries({ queryKey: getListCommentsQueryKey(target.id) }) },
  request: { headers: { 'Content-Type': 'application/json' } },
})
// onSubmit={(data) => comment.mutateAsync({ itemId: target.id, data })}
```
`CommentCreate` fields: `body` (textarea, required, maxLength 8000).

### 8. Integrations — `src/routes/_app/integrations.tsx`

CREATE integration (no If-Match):
```ts
const create = useCreateIntegration({
  mutation: { onSuccess: () => qc.invalidateQueries({ queryKey: getListIntegrationsQueryKey(currentStudyId ?? undefined) }) },
  request: { headers: { 'Content-Type': 'application/json' } },
})
// onSubmit={(data) => create.mutateAsync({ studyId: currentStudyId!, data })}
```
`IntegrationWrite` fields: `integration_code` (text, required, pattern
`^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`), `display_name` (text, required), `direction` (select,
required, options `inbound | outbound | bidirectional` from `IntegrationWriteDirection`),
`external_subject` (text, optional, `string | null`), `allowed_modules` (tags → `string[]`, required).

EDIT integration (If-Match from integration.revision):
```ts
const patch = usePatchIntegration({
  mutation: { onSuccess: () => {
    qc.invalidateQueries({ queryKey: getListIntegrationsQueryKey(currentStudyId ?? undefined) })
    qc.invalidateQueries({ queryKey: getGetIntegrationQueryKey(editing.id) })
  }},
  request: ifMatchRequest(editing.revision),
})
// onSubmit={(data) => patch.mutateAsync({ integrationId: editing.id, data })}
```
`IntegrationPatch` fields (all optional): `display_name` (text, `string | null`),
`external_subject` (text, `string | null`), `allowed_modules` (tags → `string[] | null`),
`status` (select, options `active | retired` from `IntegrationPatchStatus = 'active' | 'retired' | null`).

CREATE subscription (no If-Match):
```ts
const sub = useCreateSubscription({
  mutation: { onSuccess: () => qc.invalidateQueries({ queryKey: getListSubscriptionsQueryKey(integration.id) }) },
  request: { headers: { 'Content-Type': 'application/json' } },
})
// onSubmit={(data) => sub.mutateAsync({ integrationId: integration.id, data })}
```
`SubscriptionWrite` fields: `callback_url` (text, required), `event_types` (tags → `string[]`,
required), `timeout_seconds` (number, optional, min 1, max 30). `headers` (`{[k]:string}` map) is
NOT a flat field — OMIT from the form this pass (optional; backend accepts absence).

### 9. Terminology — `src/routes/_app/terminology.tsx` (study-extensions tab)

CREATE extension (no If-Match):
```ts
const createExt = useCreateExtension({
  mutation: { onSuccess: () => qc.invalidateQueries({ queryKey: getListExtensionsQueryKey(currentStudyId ?? undefined) }) },
  request: { headers: { 'Content-Type': 'application/json' } },
})
// onSubmit={(data) => createExt.mutateAsync({ studyId: currentStudyId!, data })}
```
`ExtensionCreate` fields: `code` (text, required, pattern `^[A-Za-z][A-Za-z0-9._-]{0,63}$`),
`name` (text, required, maxLength 255), `base_release_id` (text, required),
`codelist_code` (text, required, maxLength 64).

ADD term — If-Match against the EXTENSION's revision (ExtensionTermResponse has no revision):
```ts
const addTerm = useCreateExtensionTerm({
  mutation: { onSuccess: () => {
    qc.invalidateQueries({ queryKey: getListExtensionTermsQueryKey(extension.id) })
    qc.invalidateQueries({ queryKey: getGetExtensionQueryKey(extension.id) })      // fresh revision
    qc.invalidateQueries({ queryKey: getListExtensionsQueryKey(currentStudyId ?? undefined) })
  }},
  request: ifMatchRequest(extension.revision),
})
// onSubmit={(data) => addTerm.mutateAsync({ extensionId: extension.id, data })}
```
`ExtensionTermWrite` fields: `code` (text, required, maxLength 128), `submission_value` (text,
required, maxLength 255), `decode` (textarea, required, maxLength 1000), `definition` (textarea,
optional, `string | null`), `preferred_term` (text, optional, `string | null`),
`synonyms` (tags → `string[]`, optional).

EDIT term — If-Match against the EXTENSION's revision:
```ts
const patchTerm = usePatchExtensionTerm({
  mutation: { onSuccess: () => {
    qc.invalidateQueries({ queryKey: getListExtensionTermsQueryKey(extension.id) })
    qc.invalidateQueries({ queryKey: getGetExtensionQueryKey(extension.id) })      // fresh revision
  }},
  request: ifMatchRequest(extension.revision),
})
// onSubmit={(data) => patchTerm.mutateAsync({ termId: term.id, data })}
```
`ExtensionTermPatch` fields (all optional): `submission_value` (text, `string | null`),
`decode` (textarea, `string | null`), `definition` (textarea, `string | null`),
`preferred_term` (text, `string | null`), `synonyms` (tags → `string[] | null`).

CRITICAL (sequential-write 412): the extension's `revision` increments on each term write. The
`onSuccess` MUST invalidate `getGetExtensionQueryKey(extension.id)` (and the extensions list) so the
next `ifMatchRequest(extension.revision)` reads a fresh revision from a refetched extension before
the following write.

### 10. Clinical aggregates — `raw.tsx` / `sdtm.tsx` / `adam.tsx` / `tlf.tsx`

CREATE only (no If-Match). Per module, substitute `<Mod>` = Raw/Sdtm/Adam/Tlf:
```ts
const create = useCreate<Mod>Aggregate({
  mutation: { onSuccess: () => qc.invalidateQueries({ queryKey: getList<Mod>AggregatesQueryKey(currentStudyId ?? undefined) }) },
  request: { headers: { 'Content-Type': 'application/json' } },
})
// onSubmit={(data) => create.mutateAsync({ studyId: currentStudyId!, data })}
```
`AggregateCreate` fields: `code` (text, required), `name` (text, required),
`document_type` (text, optional, `AggregateCreateDocumentType = string | null`).
Full Specification/Derivation-Plan authoring is OUT OF SCOPE.

---

## DEFERRED (note in report; do NOT build this pass)

- **Reference CREATE** — nested body `value.fields[].name/value`; `ReferenceField.name` is a single
  `@pattern` string and `ReferenceFieldValue` is `string | number | boolean | null`, not expressible
  by the flat `FieldDescriptor<TBody>` (Decision 8).
- **Idempotency-triggered actions** — validate/build/reconcile/redeliver and all operation-creating
  POSTs. `idempotentRequest()` ships but is wired to NO trigger. The hook-call-time `request` binding
  vs onClick key-generation ordering is a separate concern for the follow-up (Decision 9).
- **Documents** content/USDM/evidence authoring; **TLF** ARS/ProgramPlan authoring; **SDTM/ADaM**
  derivation authoring; dependency-selection edits (`useReplace*Dependencies`).
- **Subscription** `headers` map field (non-flat); **Integration** external-identifier and
  rotate-secret/retire-subscription flows (not in the stated scope).

---

## Gaps / assumptions recorded

- The read pass left references and reference list UNSURFACED (no route, no nav entry). This plan adds
  a minimal `routes/_app/reference.tsx` + a sidebar nav entry so Reference edit/retire have a home,
  because the task scope requires them. If a different placement is preferred (e.g. a tab under an
  existing screen), that is a cosmetic relocation of the same hooks/contracts.
- `ReviewItemPatch.status` is free-form `string | null` in the generated model (no enum). Rendered as
  a text control. If the backend enumerates allowed statuses later, switch to a `select` with those
  options — no contract change otherwise.
- `SubscriptionWrite.headers` (a string map) and any other non-flat optional are omitted from forms
  this pass; the backend accepts their absence.
