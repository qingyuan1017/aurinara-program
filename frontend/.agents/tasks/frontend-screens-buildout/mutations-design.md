# Technical Design — Frontend Mutations (Create / Edit) Buildout

Aurinara Clinical Artifact Platform — frontend (`e:\Work\EDETEK\Python\aurinara\frontend`)

## Overview

The read/list/detail pass (see `design.md` in this folder) wired twelve module screens on top of the generated Orval hooks, a `ResourceTable`, a `PageHeader`, shared loading/error/empty state components, a `StatusBadge`, and a current-study context (`useCurrentStudy()`). This pass adds the write side: create and edit flows, plus the few immutable "trigger" actions that fit cleanly onto an existing screen. It introduces **one** reusable form/dialog pattern reused by every covered module, four new shadcn/ui primitives (`dialog`, `textarea`, `form` helpers, and a `sonner` toaster), and a single, carefully justified mechanism for the concurrency/idempotency headers the contract requires. No per-module bespoke form is written, no read-only screen is broken, and nothing under `src/api/generated/**` or the backend is touched.

The hard part here is not the forms — it is three contract facts that the generated client does not surface and that must be handled by hand:

1. The generated mutation hooks forward their `options` argument as the `request` config, which becomes the **second** positional argument to `customInstance` and is spread into the axios request. That is the only channel for injecting `If-Match` and `Idempotency-Key`, because those headers are absent from every OpenAPI operation definition.
2. `If-Match` is required on `PATCH`/`PUT`/`DELETE` (and on `POST` actions that mutate an existing aggregate). The ETag is **deterministic** — the backend computes `"revision-{revision}"` and compares the header with `hmac.compare_digest` — so the UI constructs the header from the `revision` field a GET already returns. This was verified against the real backend, not assumed (see §3).
3. `Idempotency-Key` is required on exactly the operation-creating endpoints the contract enumerates (build / execute / reconcile / redeliver / bulk import / submission-package). A plain collection POST that creates a new resource requires neither header.

Everything below is grounded in the generated sources and the backend, both read for this design.

## Technology stack (locked)

Unchanged from the read pass and locked for this pass:

- Vite 5, React 18, TypeScript strict.
- TanStack Router 1.69 (file-based, `autoCodeSplitting`, pathless `_app` guard — not weakened).
- TanStack Query 5.59 — all data access and all mutations go through the generated `useXxx` hooks. No direct axios calls in screens or forms.
- Orval 7.21 generated client under `src/api/generated` (read-only); axios mutator at `src/api/axios-instance.ts`.
- Tailwind v4, shadcn/ui new-york style, zinc base color, `data-slot` attributes, `cn()` from `@/lib/utils`, `cva` where the upstream component uses it.
- Icons: `lucide-react`.

**One new runtime dependency: `sonner`** (the toast library shadcn's `sonner` wrapper is built on). Pinned to `^1.5.0` (current 1.x line), added to `package.json` `dependencies`. Every other primitive this pass needs is built on Radix packages **already present**: `@radix-ui/react-dialog` (`^1.1.2`) and `@radix-ui/react-label` (`^2.1.0`) are already in `dependencies`; `textarea` is a plain `<textarea>` with no Radix dep. So the dependency delta is exactly one package. After editing `package.json` the implementer runs `npm install` so the lockfile updates before `npm run build`.

Rejected alternative for forms: `react-hook-form` + `zod` + `@hookform/resolvers`. shadcn's canonical `form` is built on react-hook-form, and it is genuinely nice, but it is three new dependencies and a second validation model layered over the generated model types. The forms in scope are small (2–6 fields, flat), and the generated models already encode the required/optional and length/pattern constraints. A dependency-free controlled-form approach (see §1) keeps the surface minimal and consistent with the read pass's "no new library unless it earns its place" stance. If a later task needs complex nested field arrays (e.g. full SDTM authoring, explicitly deferred here), that task can add react-hook-form then.

## 3. Concurrency + idempotency — verified mechanism (decide first, it shapes everything)

This section is first because the form component's API depends on it.

### 3a. How the generated hook forwards headers to axios — VERIFIED

Read from `src/api/generated/studies/studies.ts`, `reference/reference.ts`, `integrations/integrations.ts`. The pattern is identical in every tag file. The operation function places the body and its own `Content-Type` into the axios **config** (first arg) and forwards the hook's `options`/`request` as the **second** arg:

```ts
export const patchStudy = (
  studyId: string,
  studyPatch: BodyType<StudyPatch>,
  options?: SecondParameter<typeof customInstance>,
) =>
  customInstance<StudyResponse>(
    {
      url: `/api/v1/studies/${studyId}`,
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      data: studyPatch,
    },
    options, // ← SecondParameter<typeof customInstance>
  );
```

The mutation hook threads `options.request` into that `options` slot via `getXxxMutationOptions`:

```ts
const { mutation, request: requestOptions } = options ?? {};
// mutationFn calls: patchStudy(studyId, data, requestOptions)
```

So the injection point is the hook's **`request`** field (NOT `mutation`). `request` is typed `SecondParameter<typeof customInstance>` = the second parameter of `customInstance` = `AxiosRequestConfig | undefined`. There is **no** `{ request: { headers } }` wrapper layer — the thing you pass as `request` _is_ the axios config, so headers go at `request.headers`:

```ts
usePatchStudy({ request: { headers: { "If-Match": ifMatch } } });
```

### 3b. The mutator header-merge hazard — VERIFIED, and the fix

`src/api/axios-instance.ts`:

```ts
export const customInstance = <T>(config: AxiosRequestConfig, options?: AxiosRequestConfig) =>
  AXIOS_INSTANCE({ ...config, ...options, signal: options?.signal ?? controller.signal }) ...
```

The merge is a **shallow spread**: `{ ...config, ...options }`. The operation function already set `config.headers = { 'Content-Type': 'application/json' }`. If our injected `options.headers` is present, the spread **replaces the entire `headers` object**, so `Content-Type` would be dropped on PATCH/POST-with-body. The axios request interceptor still re-adds `Authorization`, so auth is unaffected, but a dropped `Content-Type` on a JSON body is a real risk.

Two ways to make this safe:

- **(Chosen) Always include `Content-Type: application/json` in the injected headers for any request that carries a JSON body.** The header helper (§3d) emits `{ 'Content-Type': 'application/json', ...conditionalHeaders }`. For the DELETE/retire case (no body) `Content-Type` is harmless. This keeps `axios-instance.ts` untouched, which is desirable: that file is shared with every read query and changing its merge semantics is higher blast radius than owning the merge at the one call site that needs it.
- (Rejected) Deep-merge `headers` inside `customInstance`. It is a one-line change (`headers: { ...config.headers, ...options?.headers }`) and arguably "more correct," but it mutates behavior for all 100+ generated calls to fix a problem only mutations have, and the read pass's error-handling and cancellation tests implicitly depend on the current shape. The chosen approach is strictly local and provably sufficient.

The implementer MUST NOT rely on the generated `Content-Type` surviving when `request.headers` is set. The header helper owning `Content-Type` is a locked invariant (§3d).

### 3c. ETag source — VERIFIED against the backend, decision made

The task flagged the ETag SOURCE PROBLEM and listed two options. The backend was read to decide, not assumed.

`src/app/common/etag.py`:

```python
def etag_for_revision(revision: int) -> str:
    return f'"revision-{revision}"'          # literal double-quotes included

def require_matching_etag(if_match: str | None, revision: int) -> None:
    if if_match is None:
        raise ProblemException(status_code=428, code="precondition_required", ...)
    expected = etag_for_revision(revision)
    if not hmac.compare_digest(if_match, expected):
        raise ProblemException(status_code=412, code="precondition_failed", ...)
```

Every module route uses exactly this pair. Verified call sites: `studies/service.py:100`, `reference/routes.py:233,287`, `review/routes.py:182`, `integration/routes.py:283,302,582,609,650`, `terminology/routes.py:345,455,509,545`, `validation/routes.py:227`, `documents/routes.py` (many), `kernel/dependencies.py:238`, `api/clinical_aggregates.py`. The ETag is **always** `"revision-{N}"` and acceptance is an exact string compare against the current `revision`.

**Decision: construct `If-Match` from the `revision` field — option (b).** Every GET/response model that is editable exposes a numeric `revision` (confirmed in the read pass's response-field inventory: studies, references, review items, integrations, extensions, aggregates, documents, rule packs all carry `revision`). The If-Match value is:

```ts
export const ifMatchFromRevision = (revision: number) =>
  `"revision-${revision}"`;
```

Note the embedded double-quotes — they are part of the opaque tag the backend compares, so the string literal must include them. This matches the backend byte-for-byte.

Why not option (a) — capture the ETag response header? It would require either changing the mutator to stop discarding `response.headers` (high blast radius, breaks the `Promise<T>` → `response.data` contract every read query depends on) or a parallel raw fetch purely to read a header. Both are strictly more complex than reading a field the edit form already has in hand, and the backend proves the field is sufficient. Option (a) would only be necessary if the ETag were non-derivable (e.g. a random nonce or a content hash); it is not. The design records this so a future backend change that makes the ETag opaque/non-derivable is a known trigger to revisit — if `etag.py` ever stops deriving from `revision`, option (a) becomes mandatory. (Mitigation note: the stale-reload UX in §3e already handles the case where our constructed tag is wrong, degrading to a correct "reload and retry" rather than silent data loss.)

The edit form therefore takes the full current entity (which includes `revision`) as its initial value and derives `If-Match` at submit time. For DELETE/retire (no entity body in the form) the row still carries `revision` from the list response, so the row action passes `revision` to the retire call.

### 3d. Idempotency-Key — scope and construction, VERIFIED

Backend requires `Idempotency-Key` (missing → 428-style `idempotency_key_required`; reused with a different request → 409 `idempotency_key_reused`) on exactly: artifact builds (`artifacts/builds.py:163`), reconciliation-run create (`reconciliation/routes.py:145`), integration redelivery (`integration/routes.py:700`), reference bulk import (`reference/routes.py:343`), document import (`documents/routes.py:1120`), and submission-package create (per contract §3.4/§3.7). These are the only endpoints that read the header.

Key construction: `crypto.randomUUID()`, generated **once per user-initiated action attempt** and held stable across React re-renders of that attempt. The invariant that matters is "reusing the same key with a _different_ body → 409," so the key must NOT be regenerated on every render (that would make retries create duplicate operations) and must NOT be reused across distinct user actions (that would 409 or silently return the prior operation). Concretely, the trigger button component generates the key inside the `onClick` handler and passes it to a single `mutate` call; it is not stored in component state, so a fresh click yields a fresh key. This is the simplest correct policy: one click = one key = one operation.

### 3e. Header helper + the three header-injection shapes

New file `src/api/request-headers.ts` (NOT under `generated/`; it is hand-authored app code that imports nothing from generated):

```ts
import { type AxiosRequestConfig } from "axios";

const JSON_CT = { "Content-Type": "application/json" } as const;

/** If-Match for a conditional write, derived from the entity revision. */
export function ifMatchRequest(revision: number): AxiosRequestConfig {
  return { headers: { ...JSON_CT, "If-Match": `"revision-${revision}"` } };
}

/** Idempotency-Key for an operation-creating POST. Caller generates the key once per attempt. */
export function idempotencyRequest(key: string): AxiosRequestConfig {
  return { headers: { ...JSON_CT, "Idempotency-Key": key } };
}

/** Plain JSON create: no conditional/idempotency header, but keep Content-Type (see §3b). */
export function jsonRequest(): AxiosRequestConfig {
  return { headers: { ...JSON_CT } };
}
```

These three functions are the ONLY place header strings are built. Each returns an `AxiosRequestConfig` that is passed verbatim as the hook's `request`:

| Operation kind                                                                                                   | Hook invocation                                                             | Header source                  |
| ---------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------- | ------------------------------ |
| Plain collection create (studies, references, review items, extensions, integrations, aggregates, subscriptions) | `useCreateX({ request: jsonRequest() })`                                    | Content-Type only              |
| Edit (PATCH/PUT) and retire (DELETE)                                                                             | `usePatchX({ request: ifMatchRequest(revision) })`                          | Content-Type + If-Match        |
| Operation-creating action (reconcile/build/redeliver/import)                                                     | `useX({ request: idempotencyRequest(crypto.randomUUID()) })` within onClick | Content-Type + Idempotency-Key |

Because the hook's `request` must be known when the hook is _called_ (not when `mutate` runs), and `If-Match`/`Idempotency-Key` are per-attempt values, the form/trigger passes `request` through at call time via a thin wrapper: the shared form (see §1) accepts a `buildRequest?: () => AxiosRequestConfig` and the component calls the generated hook with `{ request: buildRequest?.() }`. For edit this is `() => ifMatchRequest(entity.revision)`; for create it is `() => jsonRequest()`; for the trigger buttons it is `() => idempotencyRequest(crypto.randomUUID())`. This keeps the header value lazy and attempt-scoped. (TanStack Query re-reads `mutationFn` from the options object on each `mutate`, and `request` is baked into the options at hook-call time; passing a fresh `request` requires re-invoking the hook with new options, which React does on each render — so `buildRequest` is evaluated on the render that precedes the submit, giving the current `revision`. For the idempotency trigger, which must be stable across the single in-flight attempt, the key is generated in `onClick` and passed to a dedicated single-shot mutation created with `useMutation`-style stability; see §4 trigger note.)

### 3f. Surfacing 412 / 428 / 409

Mapped in the shared error handler (§1, error handling), keyed off `error.response.status` and the problem `code`:

- **428 `precondition_required`**: a bug (we always send If-Match on conditional writes). Surfaced as a top-level form error "A required precondition header was missing — please retry." and the condition is logged to the console because it indicates a client defect, not user error.
- **412 `precondition_failed`**: the record changed since the form opened (our constructed `If-Match` no longer matches the current revision). Top-level form error: **"This record changed since you opened it. Reload and try again."** plus a "Reload" affordance that invalidates the entity's query and closes the dialog so the user reopens with fresh data. Recoverable; not logged as an error.
- **409 `idempotency_key_reused`**: only reachable on operation-creating actions if a key were reused with a different body (our policy prevents this). Surfaced on the trigger as "This action was already submitted with different inputs." Recoverable by retrying (fresh key); logged to console.
- **409 other codes** (`duplicate` natural key, invalid lifecycle transition, `dependency_refresh_required`, etc.): rendered as a top-level error using the problem `detail`, since the `code` is specific to the backend state and not form-field mappable.

## 1. The one reusable form pattern — `ResourceFormDialog`

New file `src/components/data/resource-form-dialog.tsx`. ONE component reused by every create and edit form in scope. It is a controlled dialog that renders a declarative field list, runs client-side validation before submit, calls a caller-supplied submit function (which wraps the generated mutation), and handles loading/success/error uniformly.

### Why a field-descriptor dialog, not "render fields from the model type"

TypeScript interfaces are erased at runtime, so there is no way to iterate a generated model's fields reflectively. "Render fields from a generated model type" is therefore realized as: the caller supplies a typed `fields` descriptor array **whose keys are constrained to `keyof TBody`**, so the field list is checked against the generated model at compile time and cannot drift (a renamed/removed model field fails the build). This gives the model-driven guarantee the task asks for while staying strict-TS-safe. The field constraints (required, maxLength, pattern) are copied from the model's JSDoc into the descriptor as validation metadata — they are not reflectively available, so they are declared once per form next to the field. This duplication is intentional and small; the compile-time `keyof` check is what prevents the forms from going stale.

### Props / API

```ts
import { type AxiosRequestConfig } from "axios";

type FieldType = "text" | "textarea" | "select" | "number" | "tags"; // 'tags' = comma/enter list → string[]

interface FieldDescriptor<TBody> {
  name: keyof TBody & string;
  label: string;
  type: FieldType;
  required?: boolean;
  placeholder?: string;
  description?: string;
  options?: { value: string; label: string }[]; // for 'select'
  maxLength?: number;
  pattern?: { re: RegExp; message: string }; // mirrors the model @pattern
  min?: number;
  max?: number; // for 'number'
}

interface ResourceFormDialogProps<TBody extends Record<string, unknown>> {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  submitLabel?: string; // default 'Save'
  fields: FieldDescriptor<TBody>[];
  initialValues: Partial<TBody>; // edit prefill; {} for create
  /** Runs the generated mutation. Resolves with the created/updated entity, rejects with the AxiosError. */
  onSubmit: (body: TBody) => Promise<unknown>;
  isSubmitting: boolean; // the hook's isPending, passed in so the button disables
  submitError: AxiosError | null; // the hook's error, passed in for problem-detail mapping
  successMessage: string; // toast text on success
}
```

The dialog is **controlled** (`open`/`onOpenChange` owned by the screen). The screen owns the mutation hook (so cache invalidation and `request` header injection live where the entity's query keys are known) and passes `isSubmitting`, `submitError`, and an `onSubmit` that calls `mutate`/`mutateAsync`. Keeping the hook in the screen (not inside the dialog) is deliberate: the dialog stays generic over `TBody` and never imports a generated hook, so it is unit-testable with a stub `onSubmit`.

### Field rendering

Built on the new `form` helpers (§2) + existing `input`, `label`, `select`, and the new `textarea`. Each field renders a `FormItem` with `Label`, the control, an optional `description` line, and a per-field error slot (`FormMessage`). Field value state is a single `useState<Partial<TBody>>(initialValues)` record updated per control. `type` maps to control:

- `text` → `Input`
- `textarea` → `Textarea`
- `number` → `Input type="number"`, value coerced to `number` on change
- `select` → `Select` with `options`
- `tags` → `Input` whose comma-separated value is split/trimmed into `string[]` on submit (used for `allowed_modules`, `event_types`, `synonyms`)

### Client-side validation (before submit)

Pure function `validate(fields, values): Record<string, string>` run on submit (and re-run on change for a field already showing an error, so the message clears as the user fixes it). Rules, all derived from the generated model constraints:

- **required**: `required` field whose trimmed value is empty / empty array → "`{label}` is required."
- **maxLength**: string longer than `maxLength` → "`{label}` must be at most {n} characters."
- **pattern**: string failing `pattern.re` → `pattern.message` (e.g. study `code` → `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`).
- **number range**: outside `[min,max]` → "`{label}` must be between {min} and {max}."

If `validate` returns any entries, submit is blocked, errors render under their fields, and no request is made. This enforces "required present, correct shapes before submit." The submit button is also `disabled` while `isSubmitting`.

### Submit flow

1. Run `validate`; if errors, show them and stop.
2. Build `TBody` from `values` (drop empty optionals so PATCH stays sparse — `exclude_unset` semantics on the backend side mean omitted keys are not touched; the design sends only populated fields for PATCH, and all required + populated optionals for create).
3. `await onSubmit(body)`.
4. On resolve: `toast.success(successMessage)`, `onOpenChange(false)`, reset local field state. Cache invalidation happens in the screen's mutation `onSuccess` (see below), not in the dialog.
5. On reject: do NOT close. The screen has already set `submitError`; the dialog's error-mapping effect (below) distributes it.

### Error handling — RFC 9457 problem-detail aware

The backend problem shape was read from `src/app/common/problems.py`. The relevant fields:

```jsonc
{ "detail": "string", "code": "string", "status": 422,
  "issues": [ { "code, severity, message, field_path, module, entity_type, ... } ],
  "errors": [ { "location": ["body","name"], "message": "...", "type": "..." } ] }
```

Two distinct arrays, both must be handled:

- **`issues[]`** — application/clinical validation. Each has `field_path` (dot path, nullable). The dialog maps an issue to a form field when `field_path`'s **last segment** (or its full value) matches a `fields[].name`; matched issues render as that field's `FormMessage`. Unmatched issues (null `field_path`, or a path with no matching field, e.g. `graph.edges`) accumulate into a top-level alert listing each `message`.
- **`errors[]`** — transport/request validation (FastAPI `RequestValidationError`). `location` is a path array typically `["body", <field>]`. The dialog takes the segment after `"body"` and matches it to a `fields[].name`; matched → that field's message; unmatched → top-level.
- **No `issues`/`errors` (e.g. 500, network error, 401)** — a single top-level alert using `detail` (or `error.message` when there is no problem body).
- **412 / 428 / 409** — handled per §3f (the stale-record copy, the reload affordance, etc.), checked before the generic mapping because their `code` is specific.

A small pure helper `mapProblemToFieldErrors(error: AxiosError, fieldNames: string[]): { fieldErrors: Record<string,string>; formErrors: string[] }` encapsulates all of the above and is independently unit-testable. The `error` prop is typed `AxiosError | null` (imported from `axios`) for the same reason the read pass typed it that way: `AxiosError<HTTPValidationError>` from the hooks assigns to `AxiosError<unknown, any>` with no cast, and the problem body is read defensively off `error.response?.data`. The problem body is typed locally as `interface ProblemDetails { detail?: string; code?: string; issues?: ProblemIssue[]; errors?: ProblemTransportError[] }` in `src/api/problem.ts` (hand-authored, NOT generated — the generated `HTTPValidationError` only models FastAPI's `{ detail: [...] }` and does not describe the platform's richer `issues[]`/`code`/RFC9457 fields).

### Loading / disabled state

The submit button renders `isSubmitting ? <Loader2 className="animate-spin" /> Saving… : submitLabel` and is `disabled` when `isSubmitting` or when validation currently has errors. The cancel button is disabled while submitting so a close mid-flight cannot orphan the toast.

### Cache invalidation (owned by the screen, listed here for the contract)

Each screen's mutation hook sets `onSuccess` to `queryClient.invalidateQueries({ queryKey })` for the affected list (and detail, for edit). Query keys come from the generated `getListXxxQueryKey(...)` / `getGetXxxQueryKey(...)` helpers (they exist in every tag file, verified in `studies.ts`), so no key strings are hand-written. The `queryClient` is obtained via `useQueryClient()`. Example (studies create):

```ts
const qc = useQueryClient();
const create = useCreateStudy({
  mutation: {
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: getListStudiesQueryKey() }),
  },
  request: jsonRequest(),
});
```

## 2. New shadcn/ui primitives

Authored by hand in the exact new-york/zinc style of the existing files (`data-slot`, `cn()`, `cva` only where upstream uses it — `button.tsx` and `badge.tsx` are the style references).

| Component      | File                             | Dep to add                                             | Notes                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| -------------- | -------------------------------- | ------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Dialog         | `src/components/ui/dialog.tsx`   | none (`@radix-ui/react-dialog@^1.1.2` already present) | Exports `Dialog, DialogTrigger, DialogContent, DialogHeader, DialogFooter, DialogTitle, DialogDescription, DialogClose`. Overlay + content with `data-slot`, zinc styling, close button with an `X` lucide icon.                                                                                                                                                                                                                                                                                                                                                            |
| Textarea       | `src/components/ui/textarea.tsx` | none (plain `<textarea>`)                              | Single `Textarea` export mirroring `input.tsx`'s classes + `data-slot="textarea"`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| Form helpers   | `src/components/ui/form.tsx`     | none (`@radix-ui/react-label@^2.1.0` already present)  | **Dependency-free** helpers matching the chosen controlled-form approach: `FormItem`, `FormLabel` (wraps the existing `Label`), `FormControl` (passthrough wrapper applying `data-slot` + aria wiring), `FormDescription`, `FormMessage` (renders a `text-destructive` message when passed one). These are presentational and take `error`/`id` via props — they do NOT pull in react-hook-form context (that is the rejected alternative). This keeps `form.tsx` consistent with the no-new-dependency decision while still giving the dialog the standard field scaffold. |
| Sonner toaster | `src/components/ui/sonner.tsx`   | `sonner@^1.5.0`                                        | The shadcn `sonner` wrapper: a `Toaster` component that reads the current theme from the existing `theme-provider` and renders `<Sonner theme=... className="toaster group" ... />`. Exports `Toaster` and re-exports `toast` from `sonner`.                                                                                                                                                                                                                                                                                                                                |

Dialog uses `cva` only if the upstream new-york dialog does (it uses plain class strings for overlay/content, no variants) — so no `cva` in `dialog.tsx`, matching upstream. `textarea.tsx` and `form.tsx` are plain class strings like `input.tsx`/`label.tsx`.

### Toaster mount point

`<Toaster />` mounts once in `src/main.tsx`, inside `ThemeProvider` (so it reads the theme) and alongside `RouterProvider` — app-wide, outside the router tree, so any screen's `toast.success(...)` works. `main.tsx` currently renders `ThemeProvider > AuthProvider > RouterProvider`; add `<Toaster />` as a sibling of `RouterProvider` inside `AuthProvider` (or directly inside `ThemeProvider`). This is the only edit to `main.tsx`.

## 4. Scope map — modules, hooks, body models

Each row names the exact generated hook and the exact body model (read from `src/api/generated/model`). The implementer reads each model file for the precise field list before building its form; the fields noted here were read for this design. Priority order preserved.

### Studies — create + edit (route `_app/studies.tsx`)

- **Create**: `useCreateStudy` + `StudyCreate` `{ code (required, @pattern ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$), name (required, 1–255) }`. Request: `jsonRequest()`. New button in `PageHeader.actions`.
- **Edit**: `usePatchStudy({ request: ifMatchRequest(revision) })` + `StudyPatch` `{ name?, status? }` (both optional; `StudyPatchName`/`StudyPatchStatus` are nullable string aliases). Per-row edit action.
- Invalidate `getListStudiesQueryKey()` on both; `getGetStudyQueryKey(id)` on edit.

### Reference — create / edit / retire (route `_app/reference.tsx`)

- **Create**: `useCreateReference` + `ReferenceCreate` `{ reference_type (required; enum ReferenceType: organization|country|site|vendor|language|unit|role|milestone → a `select`), natural_key (required, 1–128), display_name (required, 1–255), value: ReferenceValue }`. `ReferenceValue = { schema_version?, fields: ReferenceField[] }`, `ReferenceField = { name (@pattern ^[a-z][a-z0-9_]{0,63}$), value }`. The nested `value.fields` array is the one non-flat body in the "clearest high-value" set — scope the create form to a **single starter field pair** (one name + one value row) submitted as `value: { fields: [{ name, value }] }`, which is enough to create a valid reference; multi-row field editing is DEFERRED (noted below). This keeps the reference create form within the flat-field pattern plus one repeatable row handled as two `tags`-style inputs.
- **Edit**: `usePatchReference({ request: ifMatchRequest(revision) })` + `ReferencePatch` `{ display_name?, value? }` (read `referencePatch.ts` for exact optional set; `display_name` + `value` confirmed by the patch sub-models present).
- **Retire**: `useRetireReference({ request: ifMatchRequest(revision) })` (DELETE, body-less; If-Match required — verified `reference/routes.py:287`). Per-row "Retire" action with a confirm (see §5). Invalidate the references list.

### Review — create + edit + add comment (route `_app/review.tsx`)

- **Create item**: `useCreateReviewItem` + `ReviewItemCreate` `{ target_module (req), target_entity_type (req), target_entity_id (req), field_path?, question (req, 1–4000 → textarea), assignee?, priority? }`. Request: `jsonRequest()`.
- **Edit item**: `usePatchReviewItem({ request: ifMatchRequest(revision) })` + `ReviewItemPatch` (optional: status, priority, assignee, disposition, resolution — per the `reviewItemPatch*` sub-models). Per-row edit.
- **Add comment**: `useCreateComment` + `CommentCreate` `{ body (req, 1–8000 → textarea) }`. Request: `jsonRequest()` — verified the comment POST requires **neither** header (`review/routes.py` `create_comment` has no `if_match`/idempotency param). Surfaced as a small "Add comment" dialog from the review item row (comments list drill-down itself is out of scope; the add action is in).

### Integrations — create + edit + subscription create (route `_app/integrations.tsx`)

- **Create integration**: `useCreateIntegration` + `IntegrationWrite` `{ integration_code (req, @pattern), display_name (req), direction (req; enum IntegrationWriteDirection → select), external_subject?, allowed_modules (req, string[] → `tags`) }`. Request: `jsonRequest()`.
- **Edit integration**: `usePatchIntegration({ request: ifMatchRequest(revision) })` + `IntegrationPatch` (optional display_name/status/external_subject/allowed_modules per sub-models). Per-row edit.
- **Create subscription**: `useCreateSubscription` + `SubscriptionWrite` `{ callback_url (req), event_types (req, string[] → tags), headers?, timeout_seconds? (1–30, number) }`. Request: `jsonRequest()`. Surfaced from the integration row ("Add subscription"). Verified subscription create requires neither header (`integration/routes.py` create_subscription has no if_match/idempotency param); subscription PATCH/DELETE do require If-Match but are out of scope this pass.

### Terminology extensions — create extension + add/edit term (route `_app/terminology.tsx`, Study extensions tab)

- **Create extension**: `useCreateExtension` + `ExtensionCreate` `{ code (req, @pattern), name (req, 1–255), base_release_id (req), codelist_code (req, 1–64) }`. Request: `jsonRequest()`. New button on the Study extensions tab.
- **Add term**: `useCreateExtensionTerm` (`POST /terminology-extensions/{extension_id}/terms`) + `ExtensionTermWrite` `{ code (req, 1–128), submission_value (req, 1–255), decode (req, 1–1000 → textarea), definition?, preferred_term?, synonyms? (string[] → tags) }`. **If-Match REQUIRED** against the **extension's** revision (verified `terminology/routes.py:455`), so request is `ifMatchRequest(extension.revision)` — the add-term dialog is opened from an extension row and receives that extension's `revision`.
- **Edit term**: `usePatchExtensionTerm({ request: ifMatchRequest(extension.revision) })` + `ExtensionTermPatch` (all optional). Also keyed to the extension's revision (verified `terminology/routes.py:509`). Term edit is reachable from an extension drill-down; if the term list drill-down is not built this pass, defer edit-term and keep **create extension + add term** as the committed terminology scope. (Add-term is the high-value one and only needs the extension row's revision.)

### Clinical aggregates raw / sdtm / adam / tlf — minimal create only (routes `_app/raw.tsx`, `sdtm.tsx`, `adam.tsx`, `tlf.tsx`)

- **Create**: the four create hooks (`useCreateRawAggregate`/`useCreateSdtmAggregate`/`useCreateAdamAggregate`/`useCreateTlfAggregate` — confirm exact names in each tag file) + `AggregateCreate` `{ code (req), name (req), document_type? (AggregateCreateDocumentType, nullable → optional text/select) }`. Request: `jsonRequest()` (plain collection POST, no headers). New button in each screen's `PageHeader.actions`, scoped to `currentStudyId` (disabled when no study selected, matching the read-pass empty-state rule). No edit/patch for aggregates this pass.

### Action triggers (immutable operation creates) — Idempotency-Key

Added **only where they fit an existing screen cleanly**:

- **Reconciliation run create** — on `_app/reconciliation.tsx`: a "Start reconciliation run" trigger is DEFERRED unless the screen can supply the full `ReconciliationCreate` body (`study_id`, reconciliation type, exact entity revisions, input fingerprint, options — read `reconciliationCreate.ts`). That body requires selecting exact upstream revisions the current read-only screen does not surface, so a bare trigger would 422. **Deferred** (listed below). The reconciliation screen stays lookup-only this pass.
- **Integration redelivery** — `POST /integration-deliveries/{delivery_id}/redeliver`, requires `Idempotency-Key`, body-less. This fits a delivery row cleanly IF the deliveries drill-down exists; the deliveries list is not built this pass, so redelivery is **deferred** with it.

Net: the only idempotency-bearing action that could land cleanly is redelivery, and it depends on a deliveries list that is out of scope. So **no idempotency trigger ships this pass**, but the `idempotencyRequest()` helper and the per-click key policy (§3d) are specified and in place so the follow-up that adds the deliveries/builds screens can wire triggers with one line. The trigger pattern (for that follow-up) is: a `Button` whose `onClick` generates `const key = crypto.randomUUID()` and calls a mutation created with `useXxx({ request: idempotencyRequest(key) })`; because `request` must be fixed at hook-call time, the trigger component is a tiny wrapper that re-mounts per target id so the key is attempt-scoped, or uses the `request`-at-call-time passthrough noted in §3e.

## 5. Attaching New / Edit / Retire affordances without breaking read-only screens

### New buttons via `PageHeader.actions`

`PageHeader` already exposes an `actions` slot (read pass). Each covered screen passes a `New …` `Button` (with a `Plus` lucide icon) that sets a local `open` state for its `ResourceFormDialog`. Study-scoped create buttons are `disabled` when `!currentStudyId` (consistent with the read-pass empty-state rule) with a tooltip "Select or create a study first." Screens not getting create (documents, standards, validation, packaging) pass no `actions`, so their headers are unchanged — zero impact.

### Per-row edit / retire via an OPTIONAL `ResourceTable` actions column

`ResourceTable` is extended with **optional** props so every read-only screen keeps compiling and rendering unchanged:

```ts
interface ResourceRowAction<T> {
  label: string
  icon?: React.ComponentType<{ className?: string }>
  onSelect: (row: T) => void
  variant?: 'default' | 'destructive' // 'destructive' for Retire/Delete
}

// added to ResourceTableProps<T>:
rowActions?: (row: T) => ResourceRowAction<T>[] // omitted → no actions column
```

Behavior:

- When `rowActions` is `undefined` (all current read screens), **no extra column is rendered** — the table markup is byte-identical to today. This is the invariant that keeps read-only screens unbroken; it is enforced by making the actions column render conditional on `rowActions != null`.
- When provided, `ResourceTable` appends ONE trailing column (header empty, `className="w-[1%] text-right"`). Each row renders a `DropdownMenu` (existing `dropdown-menu` primitive) triggered by a ghost icon button (`MoreHorizontal`), listing the row's actions; a `destructive` action renders in the destructive text color. Using the existing dropdown avoids adding a new primitive and keeps rows compact.
- `rowActions` is a function of the row so actions can be conditional (e.g. hide "Retire" on an already-retired row by returning a shorter array).

**Retire/Delete confirmation**: destructive actions route through a small shared `ConfirmDialog` (built on the new `dialog` primitive — a title, a body message, Cancel + a `destructive` Confirm button that shows a spinner while the delete mutation is pending). This satisfies the "hard-to-reverse action needs confirmation" guardrail; retire is a logical retire (not a hard delete) per the contract, but a confirm is still warranted because it changes resource lifecycle. `ConfirmDialog` lives at `src/components/data/confirm-dialog.tsx` and takes `{ open, onOpenChange, title, description, confirmLabel, onConfirm, isPending, destructive? }`.

Edit actions open the same `ResourceFormDialog` the New button uses, pre-filled via `initialValues={row}` (the row carries `revision` for If-Match). One dialog instance per screen, with `mode`/`initialValues` swapped by the row action — the screen holds `const [editing, setEditing] = useState<T | null>(null)` and `const [creating, setCreating] = useState(false)`.

## Edge cases

- **Create button with no study selected** (study-scoped creates): button disabled + tooltip; the dialog never opens, so no request fires without a `studyId`.
- **Stale revision on edit (412)**: handled per §3f — top-level "record changed, reload" message + reload affordance; the user is never silently overwritten.
- **Missing If-Match (428)**: should be impossible (helper always sends it on conditional writes); surfaced as a retry message and console-logged as a client defect.
- **Idempotency key reuse (409)**: prevented by the per-click key policy; if it still occurs, surfaced on the trigger. (No trigger ships this pass, so this is latent until the follow-up.)
- **Duplicate natural key / invalid lifecycle (409 other)**: top-level error using problem `detail`.
- **Validation issue with unmappable `field_path`** (e.g. `graph.edges`, or `null`): accumulated into the top-level alert, never dropped.
- **Transport 422 (`errors[]` with `location: ["body", x]`)**: `x` mapped to the field; `["body"]`-only or `["query", ...]` → top-level.
- **Empty optional fields on PATCH**: omitted from the body so the backend's `exclude_unset` leaves them untouched (verified `patch_review_item` uses `model_dump(exclude_unset=True)`).
- **`tags` input empties**: an empty `tags` string yields `[]`; for a required array field (`allowed_modules`, `event_types`) that fails the required check before submit.
- **Dialog closed mid-submit**: cancel disabled while `isSubmitting`; `onSubmit` resolution still fires the toast, but close is driven by success, so no orphaned open dialog.
- **Toast after unmount**: `toast.*` is global (sonner), unaffected by the dialog unmounting.
- **Nested reference `value.fields`**: create form supplies exactly one `{name,value}` row; submitting with an empty name fails required validation. Multi-row editing deferred.

## Input validation (per external input)

All validation rules are copied from the generated model constraints into each field descriptor (declared once per form; see §1 for why reflection is not possible).

| Field (model)                          | Required | Type        | Limits / rules                                                                                                                      | On failure                        |
| -------------------------------------- | -------- | ----------- | ----------------------------------------------------------------------------------------------------------------------------------- | --------------------------------- |
| `StudyCreate.code`                     | yes      | text        | `@pattern ^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`                                                                                        | field message "Code must match …" |
| `StudyCreate.name`                     | yes      | text        | 1–255                                                                                                                               | required / maxLength message      |
| `StudyPatch.name/status`               | no       | text/select | nullable                                                                                                                            | omitted when empty                |
| `ReferenceCreate.reference_type`       | yes      | select      | enum (8 values)                                                                                                                     | required                          |
| `ReferenceCreate.natural_key`          | yes      | text        | 1–128                                                                                                                               | required / maxLength              |
| `ReferenceCreate.display_name`         | yes      | text        | 1–255                                                                                                                               | required / maxLength              |
| `ReferenceCreate.value.fields[0].name` | yes      | text        | `@pattern ^[a-z][a-z0-9_]{0,63}$`                                                                                                   | field message                     |
| `ReviewItemCreate.question`            | yes      | textarea    | 1–4000                                                                                                                              | required / maxLength              |
| `ReviewItemCreate.target_*`            | yes      | text        | non-empty                                                                                                                           | required                          |
| `CommentCreate.body`                   | yes      | textarea    | 1–8000                                                                                                                              | required / maxLength              |
| `IntegrationWrite.integration_code`    | yes      | text        | `@pattern`                                                                                                                          | field message                     |
| `IntegrationWrite.direction`           | yes      | select      | enum                                                                                                                                | required                          |
| `IntegrationWrite.allowed_modules`     | yes      | tags        | non-empty `string[]`                                                                                                                | required                          |
| `SubscriptionWrite.callback_url`       | yes      | text        | non-empty (backend enforces HTTPS/SSRF rules; client does basic non-empty + `https://` prefix hint, does not duplicate SSRF checks) | required / prefix hint            |
| `SubscriptionWrite.event_types`        | yes      | tags        | non-empty                                                                                                                           | required                          |
| `SubscriptionWrite.timeout_seconds`    | no       | number      | 1–30                                                                                                                                | range message                     |
| `ExtensionCreate.code`                 | yes      | text        | `@pattern`                                                                                                                          | field message                     |
| `ExtensionCreate.name`                 | yes      | text        | 1–255                                                                                                                               | required / maxLength              |
| `ExtensionCreate.base_release_id`      | yes      | text        | non-empty UUID (format owned by backend)                                                                                            | required                          |
| `ExtensionCreate.codelist_code`        | yes      | text        | 1–64                                                                                                                                | required / maxLength              |
| `ExtensionTermWrite.code`              | yes      | text        | 1–128                                                                                                                               | required / maxLength              |
| `ExtensionTermWrite.submission_value`  | yes      | text        | 1–255                                                                                                                               | required / maxLength              |
| `ExtensionTermWrite.decode`            | yes      | textarea    | 1–1000                                                                                                                              | required / maxLength              |
| `AggregateCreate.code/name`            | yes      | text        | non-empty                                                                                                                           | required                          |

The client does format/length/required validation only. Clinical/content validity, SSRF/callback-URL safety, UUID resolution, and natural-key uniqueness remain backend-owned and surface via the problem-detail mapping — the frontend never duplicates those authorities.

## Error handling (per operation)

| Operation                  | Failure condition               | Recoverable?      | Caller sees                                                                                | Logged?                     |
| -------------------------- | ------------------------------- | ----------------- | ------------------------------------------------------------------------------------------ | --------------------------- |
| Any create (POST)          | 422 content/transport invalid   | yes               | field + top-level errors via problem mapping; dialog stays open                            | no (user error)             |
| Any create (POST)          | 409 duplicate/lifecycle         | yes               | top-level error from `detail`                                                              | no                          |
| Any edit (PATCH/PUT)       | 412 precondition failed (stale) | yes               | "record changed, reload" + reload affordance                                               | no                          |
| Any edit (PATCH/PUT)       | 428 precondition required       | should-not-happen | "required header missing, retry"                                                           | yes (client defect)         |
| Retire (DELETE)            | 412 / 409                       | yes               | confirm dialog shows the error; stays open                                                 | no                          |
| Any mutation               | 401                             | yes (re-login)    | interceptor clears token → guard redirects; if render first, top-level "not authenticated" | interceptor only (existing) |
| Any mutation               | network / 5xx                   | yes (retry)       | top-level `detail`/`error.message`; dialog stays open                                      | no                          |
| Operation trigger (future) | 428/409 idempotency             | yes               | per §3f on the trigger                                                                     | 409-reuse logged            |

No mutation performs client-side optimistic updates, so there is no rollback concern: the server response (or its error) is authoritative, and success triggers an `invalidateQueries` refetch. This is the simplest correct policy for forms that already close on success.

## Invariant ownership

- **"If-Match is sent on exactly the conditional writes, derived correctly"** — owned by `src/api/request-headers.ts` (`ifMatchRequest`) + the edit/retire call sites that pass `revision`. Centralized so the `"revision-{n}"` format lives in one place; if the backend ETag derivation changes, one function changes.
- **"Idempotency-Key is unique per attempt, stable within an attempt"** — owned by the trigger component's `onClick` (one `crypto.randomUUID()` per click). Not stored in render state.
- **"Content-Type survives header injection"** — owned by the header helpers (every helper emits `Content-Type`), because the mutator's shallow spread would otherwise drop it (§3b). Enforced at the helper layer, not the mutator, to keep `axios-instance.ts` (shared with all reads) untouched.
- **"Read-only screens are not broken"** — owned by `ResourceTable`: the actions column renders only when `rowActions` is provided, so omitting it is byte-identical to today.
- **"The generated client stays read-only"** — unchanged convention; forms import generated hooks and model types only.
- **"One form/validation/error contract"** — owned by `ResourceFormDialog` + `mapProblemToFieldErrors`; no screen hand-rolls a form, validation, or problem-mapping.
- **"Cache stays fresh after a write"** — owned by each screen's mutation `onSuccess` using generated query-key helpers; the dialog never invalidates (it does not know the keys), keeping it generic.

## Testability

- **Unit (pure, no network)**:
  - `ifMatchRequest` / `idempotencyRequest` / `jsonRequest` — exact header output (table-driven), including the embedded-quote `"revision-{n}"` format.
  - `mapProblemToFieldErrors` — the highest-value test: `issues[]` with matching/null/unmatchable `field_path`; `errors[]` with `["body",x]` vs `["body"]`; 412/428/409 code branches; empty/absent problem body. Covers the whole error-mapping surface against a stub `AxiosError`.
  - `validate(fields, values)` — required/maxLength/pattern/number-range per rule.
  - `ResourceFormDialog` — rendered with React Testing Library against a stub `onSubmit`: validation blocks submit; success calls `onSubmit` then closes; a rejecting `onSubmit` keeps it open and renders mapped errors. Generic over `TBody`, no hooks, so fully unit-testable.
  - `ResourceTable` actions column — present only when `rowActions` provided (regression guard for the read-only-unbroken invariant).
- **Integration (hooks + MSW)**: a create flow (studies) asserting POST body + `jsonRequest` headers + list invalidation; an edit flow (reference) asserting the `If-Match: "revision-N"` header is on the PATCH and a 412 renders the stale-record message. These two cover the header-injection path end-to-end — the part most likely to regress.
- **Not currently set up**: still no test runner in `package.json`. As in the read pass, the recommended stack is **Vitest + React Testing Library + MSW**; adding it remains a separate optional task. Flagged, not assumed. The gate for this pass is `npm run build` + `npm run lint`.

## DEFERRED / out of scope (explicit)

- Documents full content / USDM authoring.
- TLF ARS authoring; full SDTM/ADaM Specification + Derivation-Plan authoring (the nested typed-AST bodies).
- Reference multi-row `value.fields` editing (create ships a single starter field pair; full field-array editing deferred).
- Edit-term under terminology if the extension term drill-down list is not built this pass (create-extension + add-term remain in scope).
- Integration subscription PATCH/DELETE, external-identifier bindings, secret rotation.
- Reconciliation-run create trigger (requires exact upstream revision selection the current screen does not surface — would 422).
- Integration redelivery and artifact-build triggers (depend on deliveries/builds drill-down lists that are out of scope); the `idempotencyRequest` helper + per-click key policy are specified so these are a one-line add later.
- Submission-package create (no package screen; depends on packaging buildout).
- Validation rule-pack `PUT` (study rule packs) — read-only this pass.

## Files summary

New:

- `src/api/request-headers.ts` (header helpers)
- `src/api/problem.ts` (`ProblemDetails` type + `mapProblemToFieldErrors`)
- `src/components/data/resource-form-dialog.tsx`
- `src/components/data/confirm-dialog.tsx`
- `src/components/ui/dialog.tsx`
- `src/components/ui/textarea.tsx`
- `src/components/ui/form.tsx`
- `src/components/ui/sonner.tsx`

Modified:

- `src/main.tsx` (mount `<Toaster />`)
- `src/components/data/resource-table.tsx` (add OPTIONAL `rowActions` prop + conditional actions column)
- `package.json` (add `sonner`)
- Covered routes: `studies.tsx`, `reference.tsx`, `review.tsx`, `integrations.tsx`, `terminology.tsx`, `raw.tsx`, `sdtm.tsx`, `adam.tsx`, `tlf.tsx` (add New buttons, row actions, dialog wiring).

Not touched: `src/api/axios-instance.ts` (the mutator is deliberately left alone — §3b), anything under `src/api/generated/**`, `src/routeTree.gen.ts`, the `_app` guard, the backend.

## Verification plan for the implementer

`npm install` (for `sonner`), then `npm run build` (`tsc -b && vite build`, zero type errors) and `npm run lint` (zero errors; the 3 pre-existing react-refresh warnings remain acceptable). `study-provider.tsx` already carries the `react-refresh/only-export-components` disable; any new file that exports both a component and a non-component (e.g. `sonner.tsx` re-exporting `toast`) needs the same disable comment to avoid a new warning. The field-descriptor `keyof TBody` typing is the main compile-time guard — a drifted model field name fails `tsc`.

## Responses to design review findings

(No review exists yet for this document; this is the initial design. This section will record responses when a review is returned.)
