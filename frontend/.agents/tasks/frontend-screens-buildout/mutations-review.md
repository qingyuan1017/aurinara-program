# Frontend create/edit/retire mutation buildout

The write side of the Aurinara frontend lands on top of the read/list/detail pass in a single
local commit (`599e29e`) on `master`. It adds one reusable `ResourceFormDialog<TBody>` and one
`ConfirmDialog`, a header-helper lib (`ifMatchRequest`/`idempotentRequest`/`jsonRequest`), a
problem-detail parser (`parseProblem`/`stalenessAlert`/`mapProblemToFieldErrors`), four new
shadcn primitives (dialog/textarea/form/sonner), an additive `rowActions` column on
`ResourceTable`, a new `/reference` route, and create/edit/retire wiring across studies,
reference, review, integrations, terminology, and the four aggregate modules. Optimistic
concurrency (If-Match), problem+json error distribution, and cache invalidation via the
generated query-key getters are all threaded through the screens, with the dialogs kept
hook-agnostic.

Watch for: nothing blocking. Every FIXED DECISION and per-module contract in the plan is
honored as written, the generated client is treated as the source of truth where the plan's
prose and the generator disagree (reference list shape — see below), and the build/lint
evidence is present and clean in the commit message. **confirmed**

**Verdict**: APPROVED

## High-level view

The If-Match contract is exact: `ifMatchRequest(revision)` emits `If-Match: "revision-${revision}"`
with the embedded double-quotes and re-emits `Content-Type: application/json`, derived from the
entity `revision` field rather than a captured response header. The mutator file was not touched.
Every header helper re-emits the content type, matching the shallow-spread behavior of the
generated mutator.

The dialog/screen split is clean. `ResourceFormDialog` and `ConfirmDialog` take no header,
request, or hook props; each screen owns the generated hook, computes `request` at hook-call
time, and wraps path ids into the correct mutate-variable shape. `onSubmit` receives only the
validated body. Retire goes through `ConfirmDialog` with If-Match from the row revision, not the
form dialog.

Error handling follows the pinned precedence: 412/428 are detected by status alone, 409 variants
by `code` then `detail`, and problem+json field distribution matches `issues[].field_path`
exactly and `errors[].location` joined after a leading `"body"` segment. The generated
`HTTPValidationError` 422 shape is not assumed anywhere.

Scope matches the plan exactly: Reference CREATE is deferred (nested body), reference EDIT and
RETIRE are present, no idempotency triggers are shipped (`idempotentRequest` exists unused), and
status/direction select unions are read from the real generated models. The terminology term
writes take If-Match from the parent extension's revision and invalidate the extension detail key
after each write so sequential term writes do not 412.

<details>
<summary>Issues (1)</summary>

1. **Reference list shape — plan prose vs generated client (informational, not a defect)** — the
   plan's "List shapes" note says references are a collection (`data?.items ?? []`), but the
   generated `listReferences` returns `ReferenceResponse[]`; the screen correctly uses
   `data ?? []`, which is what type-checks. No action required; recorded so the plan note isn't
   mistaken for a bug.

</details>

<details>
<summary>Details</summary>

### Decision 1 — If-Match construction and mutator untouched

`src/lib/requests.ts` builds `ifMatchRequest(revision)` as
`{ headers: { ...JSON_CT, 'If-Match': \`"revision-${revision}"\` } }`, so the tag carries the
embedded double-quotes the backend's `etag_for_revision` emits, and `Content-Type: application/json`
is re-emitted alongside it. The value is derived from the entity `revision` passed by each screen
(`editing.revision`, `retiring.revision`, `extension.revision`), never from a response header.
`src/api/axios-instance.ts` is absent from the commit's file list — the mutator was not edited.
**confirmed**

### Decision 2 — headers via each hook's `request`, every helper re-emits Content-Type

Headers are injected through the generated hooks' `request` option on every screen
(`request: ifMatchRequest(...)` / `request: jsonRequest()`). All three helpers
(`ifMatchRequest`, `idempotentRequest`, `jsonRequest`) spread `JSON_CT`, so the content type
survives the mutator's shallow spread that would otherwise replace the generated headers.
**confirmed**

### Decisions 3 & 4 — screen owns the hook, dialog is contract-free, correct mutate shapes

`ResourceFormDialog` and `ConfirmDialog` import no generated hook and expose no
header/request/hook prop; `onSubmit`/`onConfirm` receive only the validated body (or nothing for
retire). Each screen owns the hook, computes `request` at hook-call time, sets `onSuccess`
invalidation, and wraps path ids. Verified per the plan:

- `createStudy` → `{ data }` (no studyId), `patchStudy` → `{ studyId, data }`
- `patchReference` → `{ referenceId, data }`, `retireReference` → `{ referenceId }`
- `createReviewItem` → `{ studyId, data }`, `patchReviewItem` → `{ itemId, data }`,
  `createComment` → `{ itemId, data }`
- `createIntegration` → `{ studyId, data }`, `patchIntegration` → `{ integrationId, data }`,
  `createSubscription` → `{ integrationId, data }`
- `createExtension` → `{ studyId, data }`, `createExtensionTerm` → `{ extensionId, data }`,
  `patchExtensionTerm` → `{ termId, data }`
- `createRaw/Sdtm/Adam/TlfAggregate` → `{ studyId, data }` (all four identical)

**confirmed**

### Decision 5 — retire via ConfirmDialog

Reference retire uses `ConfirmDialog` (not the form dialog) with
`useRetireReference({ request: ifMatchRequest(retiring.revision) })` and
`onConfirm={() => retire.mutateAsync({ referenceId: retiring!.id })}`. The confirm button is
styled `destructive`. **confirmed**

### Decisions 6 & 7 — status precedence and exact problem+json field matching

`stalenessAlert` returns a message for 412 and 428 by status alone, and for 409 reads the problem
`code` (`idempotency_key_reused`) before falling back to `detail`. It is called before field
mapping in both dialogs. `mapProblemToFieldErrors` strips a leading `"body"` from
`errors[].location` and joins the remainder with `.` for an exact `fieldNames.includes` match, and
compares `issues[].field_path` exactly; non-matches go to the top-level `formErrors`. The
generated `HTTPValidationError` shape is not referenced — the `ProblemDetail` type models the
RFC 9457 body directly. **confirmed**

### Decision 8 — Reference scope

Reference CREATE is not built; a comment and the plan's deferred list record why (nested
`value.fields[]` body not expressible by the flat `FieldDescriptor`). Reference EDIT exposes only
`display_name` and RETIRE is present. **confirmed**

### Decision 9 — no idempotency triggers

`idempotentRequest()` ships in `requests.ts` but is not referenced by any screen; no
validate/build/reconcile/redeliver action buttons were added. **confirmed**

### Decision 10 — status unions from real models, Toaster placement

Study status options are `active`/`closed` (matching `StudyPatchStatus = 'active' | 'closed' | null`),
integration status `active`/`retired` (matching `IntegrationPatchStatus`), and direction
`inbound`/`outbound`/`bidirectional` (matching `IntegrationWriteDirection`). `<Toaster />` is
mounted inside `<ThemeProvider>` in `src/main.tsx`, and `ui/sonner.tsx` reads the theme from the
provider. **confirmed**

### Terminology — parent-revision If-Match and sequential-write invalidation

Term writes take If-Match from the parent extension (`ifMatchRequest(extension.revision)`), correct
since `ExtensionTermResponse` carries no revision. After every term write,
`invalidateAfterTermWrite` invalidates the terms list, `getGetExtensionQueryKey(extension.id)`,
and the extensions list; `ExtensionsTab` resolves `selected` from the refetched list by id, so the
next write reads a fresh extension revision and avoids a sequential 412. **confirmed**

### Reference list shape — generated client is the source of truth

The plan's "List shapes" note lists references under the collection group (`data?.items ?? []`),
but the generated `listReferences` returns `customInstance<ReferenceResponse[]>` — a bare array.
The screen uses `rows={data ?? []}`, which is what type-checks against the generated signature; a
`ReferenceCollection` model exists in the generated models but is not this operation's return
type. The coder correctly followed the generated client over the plan prose. Aggregate lists
(`data?.items ?? []`) and the array lists (review items, integrations, extensions, terms via
`data ?? []`) each match their generated return types. Informational only. **confirmed**

### Guardrails — generated/routeTree/auth untouched

The commit touches no file under `src/api/generated/**`, not `axios-instance.ts`, and not the
`_app` auth guard. `routeTree.gen.ts` changed only to register the new `/reference` route
(import, `.update({ id/path })`, and the by-path/by-id/by-fullpath maps) — the mechanical shape
the TanStack Router plugin produces, not a hand edit. The `ResourceTable` `rowActions` column is
guarded by `rowActions &&` on both the header and the cell and widens the loading-state colspan
only when present, so read-only screens render byte-identically. **confirmed**

### Build / lint evidence

The commit message records the gate run from `frontend/`: `npm install` added one package
(sonner); `npm run build` (`tsc -b && vite build`) passed with zero type errors; `npm run lint`
reported zero errors with only the three pre-existing `react-refresh/only-export-components`
warnings (badge.tsx, button.tsx, sidebar.tsx). Evidence is present and clean; per the review
protocol the suites were not re-run. The exact-match problem parsing and status-union typing
depend on the generated models, and the clean `tsc` is the evidence they line up. **confirmed**

</details>

<details>
<summary>File map</summary>

- `src/lib/requests.ts` — header helpers (If-Match, idempotency, plain JSON)
- `src/lib/problems.ts` — RFC 9457 parsing, staleness precedence, exact field mapping
- `src/components/forms/resource-form-dialog.tsx` — reusable hook-agnostic form dialog
- `src/components/forms/confirm-dialog.tsx` — destructive confirm for retire
- `src/components/ui/{dialog,textarea,form,sonner}.tsx` — new shadcn primitives + Toaster
- `src/components/data/resource-table.tsx` — additive `rowActions` column
- `src/components/layout/app-sidebar.tsx` — `/reference` nav entry
- `src/main.tsx` — `<Toaster />` inside ThemeProvider
- `src/routeTree.gen.ts` — auto-registered `/reference` route
- `src/routes/_app/reference.tsx` — new screen (edit display_name + retire)
- `src/routes/_app/{studies,review,integrations,terminology}.tsx` — create/edit/comment/subscription/term flows
- `src/routes/_app/{raw,sdtm,adam,tlf}.tsx` — create-aggregate flow
- `package.json` / `package-lock.json` — add `sonner`

Full diff: `git show 599e29e`
</details>
