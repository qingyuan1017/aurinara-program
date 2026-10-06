# Design Review — Frontend Mutations (Create / Edit) Buildout

Reviewed document: `frontend/.agents/tasks/frontend-screens-buildout/mutations-design.md`
Reviewer: design-review subagent (fresh context, sources verified independently)
Date: this pass

## Method

Every load-bearing claim was checked against the actual sources rather than taken on the design's word:

- Generated mutation hook signatures and `request` forwarding: `frontend/src/api/generated/studies/studies.ts`, `reference/reference.ts`, `terminology/terminology.ts`, `raw/sdtm/adam/tlf`.
- Mutator passthrough shape: `frontend/src/api/axios-instance.ts`.
- Body model field types: generated `model/*.ts` files.
- ETag/If-Match/Idempotency-Key rules: `docs/api-contract.md` §3.3/§3.4/§3.7 and backend `src/app/common/etag.py`, `src/app/review/routes.py`, `src/app/terminology/routes.py`, `src/app/common/problems.py`.

The five focus areas the task called out are addressed inline in the findings and summarized in the two assumptions sections at the end.

---

## Findings

### 1. HIGH — `FieldDescriptor<TBody>` with `name: keyof TBody & string` cannot express the Reference create form, which the same section commits to building

Where: §1 ("Props / API", `FieldDescriptor<TBody>`) combined with §4 ("Reference — create") and the §"Input validation" row `ReferenceCreate.value.fields[0].name`.

The field descriptor keys are constrained to `keyof TBody & string`. Verified against `model/referenceCreate.ts`: `ReferenceCreate = { reference_type, natural_key, display_name, value: ReferenceValue }`, and `model/referenceValue.ts`: `ReferenceValue = { schema_version?, fields: ReferenceField[] }`, and `model/referenceField.ts`: `ReferenceField = { name: string (@pattern), value: ReferenceFieldValue }`. There is **no** `keyof ReferenceCreate` key named `value.fields[0].name` or `value`-as-scalar. So the single starter field-pair the design promises ("one name + one value row submitted as `value: { fields: [{ name, value }] }`") cannot be declared through the `FieldDescriptor` array at all — the key `name: keyof TBody & string` only reaches `reference_type | natural_key | display_name | value`, and `value` is an object, not a `text`/`tags` control. The design states this nested body is in scope ("the reference create form within the flat-field pattern plus one repeatable row handled as two `tags`-style inputs") but its own component contract cannot represent it.

Additional type error: `ReferenceFieldValue` is `string | number | boolean | null` (verified `model/referenceFieldValue.ts`), so even the inner `value` is not a string, and the "two tags-style inputs" framing (`tags` → `string[]`) is wrong for both the field `name` (a single `@pattern` string, not a list) and the field `value` (a scalar union, not a list).

Concrete fix (choose one, state it in the design):

- (a) Drop Reference create from this pass's `ResourceFormDialog` scope and defer it with the multi-row field editing already deferred, leaving Reference **edit/retire** in scope (those use flat `ReferencePatch { display_name?, value? }` and a body-less DELETE). Then no module in scope has a non-flat create body, and `keyof TBody` holds for every form; OR
- (b) Extend `FieldDescriptor` with an explicit nested-path escape hatch for exactly this one form, e.g. a `compose?: (values) => TBody` builder on the dialog plus two plain descriptors (`fieldName: text @pattern ^[a-z][a-z0-9_]{0,63}$`, `fieldValue: text`) declared on a side type, and have the Reference screen pass `compose` to assemble `{ value: { fields: [{ name: fieldName, value: fieldValue }] }, reference_type, natural_key, display_name }`. Document that `fieldValue` is submitted as a string (backend coerces) and that `name` is a single string, not `tags`.

Either way the current text is internally contradictory and the implementer cannot build Reference create from it as written.

### 2. HIGH — `onSubmit: (body: TBody) => Promise<unknown>` omits the path/mutate variables every generated mutation requires, so the create/edit flows do not actually type-check as described

Where: §1 ("Props / API", `onSubmit`) and §1 ("Submit flow", step 3 `await onSubmit(body)`).

Verified mutate-variable shapes from the generated hooks:

- `useCreateReference` → `{ studyId: string; data: ReferenceCreate }`
- `usePatchStudy` → `{ studyId: string; data: StudyPatch }`
- `usePatchReference` → `{ referenceId: string; data: ReferencePatch }`
- `useRetireReference` → `{ referenceId: string }` (no `data`)
- `useCreateExtensionTerm` → `{ extensionId: string; data: ExtensionTermWrite }`
- `usePatchExtensionTerm` → `{ termId: string; data: ExtensionTermPatch }`
- `useCreate*Aggregate` → `{ studyId: string; data: AggregateCreate }`

The dialog's `onSubmit(body)` passes only the body. The design says "the screen owns the mutation hook ... and passes ... an `onSubmit` that calls `mutate`/`mutateAsync`," which is the right split — but the written contract never states that the **screen's** `onSubmit` closure is responsible for supplying `studyId`/`referenceId`/`extensionId`/`termId` into the mutate variables. As written, a reader implements `onSubmit = (body) => create.mutateAsync(body)` and gets a type error (missing `studyId`/`data` wrapper).

Concrete fix: specify in §1 that the dialog's `onSubmit` receives only the body and the **screen** wraps it, e.g.:

```ts
onSubmit={(data) => create.mutateAsync({ studyId: currentStudyId!, data })}
onSubmit={(data) => patch.mutateAsync({ referenceId: row.id, data })}
```

and for the body-less retire path, note that retire does not flow through `ResourceFormDialog` at all (it is the `ConfirmDialog` → `retire.mutateAsync({ referenceId: row.id })`), so `onSubmit(body)` never applies to DELETE. State that explicitly so the implementer does not try to route retire through the form dialog.

### 3. MEDIUM — The lazy-`request` passthrough in §3e is described as working through the dialog, but the dialog contract has no `buildRequest` prop and the screen (not the dialog) owns the hook

Where: §3e (final paragraph: "the shared form (see §1) accepts a `buildRequest?: () => AxiosRequestConfig` and the component calls the generated hook with `{ request: buildRequest?.() }`") versus §1 (the dialog's full props list has **no** `buildRequest`, and §1 states "Keeping the hook in the screen (not inside the dialog)").

These two sections conflict. §3e has the dialog calling the generated hook with a `buildRequest` result; §1 is explicit that the dialog never imports a generated hook and the screen owns it. The hook-call site is in the screen, so `request` must be computed in the screen at hook-call time, not passed through a dialog prop that §1 does not define.

Why it matters beyond tidiness: `request` is baked into the hook options when `useXxx({ request })` runs (verified: `getPatchStudyMutationOptions` destructures `request: requestOptions` and closes over it in `mutationFn`). So the correct, verified mechanism is: the screen calls `usePatchReference({ request: ifMatchRequest(editing.revision) })` on the render where `editing` is set, and TanStack Query re-reads the fresh `mutationFn` because React re-invokes the hook with new options each render. The dialog is not in this path.

Concrete fix: delete the `buildRequest` sentence from §3e (or move it to a "screen responsibility" note), and in §1 add a line: "The screen computes `request` at hook-call time from the row/entity it is editing (`usePatchX({ request: ifMatchRequest(editing.revision) })`); the dialog takes no header/request props." Then §1 and §3e agree and match the generated code.

### 4. MEDIUM — 412/428/409 detection is specified on both status and problem `code`, but the FastAPI transport-validation path produces a different `code`, and the design never says status wins

Where: §3f ("keyed off `error.response.status` and the problem `code`") and §1 ("Error handling", bullet "412 / 428 / 409 — ... checked before the generic mapping because their `code` is specific").

Verified `src/app/common/etag.py`: 428 carries `code="precondition_required"`, 412 carries `code="precondition_failed"`. Verified `src/app/common/problems.py`: these flow through `problem_exception_handler`, which sets the body `code` to the exception code — good, the codes exist. But the same file's `validation_exception_handler` (FastAPI `RequestValidationError`, HTTP 422) sets `code="request_validation_failed"` and populates `errors[]`, while `http_exception_handler` sets `code="http_error"`/`resource_not_found`. So a reader who ANDs status with a hard-coded `code` string risks mis-handling (e.g. requiring `code === "precondition_failed"` AND status 412 is fine, but if the backend ever omits the body the status is still authoritative). The design says "keyed off status and code" without a precedence rule.

Concrete fix: state the rule as "detect 412/428 by `error.response?.status` alone (both are unambiguous and body-independent); use `code` only to distinguish the two 409 variants (`idempotency_key_reused` vs duplicate/lifecycle), falling back to `detail` when `code` is absent." This also removes any dependency on a problem body being present for the stale-record path.

### 5. MEDIUM — `mapProblemToFieldErrors` field matching rule is ambiguous for `issues[].field_path` and under-specified for `errors[].location`

Where: §1 ("Error handling — RFC 9457 problem-detail aware"): "maps an issue to a form field when `field_path`'s **last segment** (or its full value) matches a `fields[].name`" and "takes the segment after `"body"` and matches it".

Two ambiguities an implementer cannot resolve from the text:

- "last segment **or** full value" is two rules with no tiebreak. For `field_path: "value.fields.0.name"` the last segment is `name`, which would wrongly match a top-level `name` field on a different form. Verified the backend emits dotted paths like `graph.edges` (api-contract §3.2 example) and nullable `field_path` (model/validation issue in §4.1), so a naive last-segment match will produce false positives.
- `errors[].location` for a JSON body is typically `["body", <field>]`, but for nested bodies FastAPI emits `["body", "value", "fields", 0, "name"]` (array indices are numbers, not strings). The rule "segment after `body`" would pick `value`, not the leaf, and the index segment is an integer. Verified `validation_exception_handler` stringifies every loc item (`[str(item) for item in error["loc"]]`), so the frontend sees `["body","value","fields","0","name"]` — all strings, but still multi-segment.

Concrete fix: pin a single deterministic rule, e.g. "match only when the problem path **exactly equals** a `fields[].name` after stripping a leading `body.` prefix (for `errors[]`) — i.e. join the location after `body` with `.` and compare to the descriptor name; no last-segment fuzzy match. Any issue/error whose joined path is not an exact descriptor name goes to the top-level alert." This matches the flat-form reality (every in-scope descriptor name is a single top-level field) and avoids false positives, at the cost of nested paths always surfacing top-level — which is acceptable because no in-scope form has nested editable fields once Finding 1 is resolved.

### 6. MEDIUM — Idempotency-trigger "re-mount per target id / request-at-call-time" mechanism is left as two alternatives with no decision, and no trigger ships this pass

Where: §3d, §3e (last paragraph), and §4 ("Action triggers") which concludes "no idempotency trigger ships this pass."

The design specifies the idempotency key policy well (one click = one `crypto.randomUUID()` = one operation, not stored in render state) and verifies the scope against the contract. But the actual wiring is left as "a tiny wrapper that re-mounts per target id so the key is attempt-scoped, **or** uses the `request`-at-call-time passthrough" — an unresolved "X or Y." Normally that is a NIT, but it is promoted to MEDIUM because the same section states the mechanism is "specified and in place so the follow-up ... can wire triggers with one line," which is not true: a one-line add is not possible when the hook's `request` must be fixed at hook-call time (verified) and the key must be generated in `onClick` (after the hook has already been called). The follow-up implementer inherits an unsolved ordering problem presented as solved.

Concrete fix: either (a) explicitly defer the trigger mechanism's design to the follow-up and delete the "one-line add" / "in place" claim, or (b) pin the mechanism now: use `mutateAsync` with a per-call `request` by having the trigger component call `useXxx()` with no `request` and instead inject the header via a dedicated per-click path — which the current mutator does NOT support (the mutate variables are `{ ...ids, data }`, there is no per-`mutate` `request` slot). Given (b) is not supported by the generated shape, state (a): "idempotency trigger wiring is deferred with the deliveries/builds screens; the helper is ready but the hook-call-time vs onClick ordering is resolved in that task."

### 7. NIT — "`StudyPatchName`/`StudyPatchStatus` are nullable string aliases" is slightly imprecise

Where: §4 ("Studies — edit").

Verified `model/studyPatch.ts`: `StudyPatch { name?: StudyPatchName; status?: StudyPatchStatus }`. The aliases are separate generated types; the design's characterization is close enough but the implementer should read `studyPatchName.ts`/`studyPatchStatus.ts` for the exact nullable union before wiring the `select` for `status`. No action required beyond the design's existing "read the model file first" instruction.

### 8. NIT — Toaster mount instruction offers two placements ("inside `AuthProvider` ... (or directly inside `ThemeProvider`)")

Where: §2 ("Toaster mount point").

Minor "X or Y." Both work since the only hard requirement is "inside `ThemeProvider` so it reads the theme." Pick one to avoid implementer drift; recommend "as a sibling of `RouterProvider`, inside `ThemeProvider`."

---

## Verified Assumptions (checked against source, correct)

1. **Hook forwards `options` as the second positional arg to `customInstance`, and `request` is the injection slot** — correct. `createStudy`/`patchStudy`/`patchReference`/`retireReference` all call `customInstance(config, options)` and `getXxxMutationOptions` destructures `request: requestOptions` into the `mutationFn`. (`studies.ts`, `reference.ts`.)
2. **Header-injection shape is `{ request: { headers: { ... } } }` with headers at `request.headers`, NOT a `{ request: { headers } }` wrapper layer** — correct. `request` is typed `SecondParameter<typeof customInstance>` = `AxiosRequestConfig | undefined`, so headers sit at `request.headers`.
3. **Mutator does a shallow spread `{ ...config, ...options }` that would drop the generated `Content-Type` if `options.headers` is set** — correct. `axios-instance.ts` `customInstance` spreads config then options with no header deep-merge; the generated op sets `headers: { 'Content-Type': 'application/json' }` in `config`. The design's mitigation (every header helper emits `Content-Type`) is sound and leaves `axios-instance.ts` untouched.
4. **Backend ETag is deterministically `"revision-{N}"` (with embedded double-quotes) and accepted by exact `hmac.compare_digest`** — correct. `etag_for_revision` returns `f'"revision-{revision}"'`; `require_matching_etag` raises 428 when `if_match is None` and 412 on mismatch. So the chosen If-Match source (derive from the `revision` field) is correct, and `ifMatchRequest(revision)` byte-matches the backend. This is the highest-risk decision and it holds.
5. **Every editable response model carries `revision: number`** — correct for `StudyResponse`, `ReferenceResponse`, `IntegrationResponse`, `ExtensionResponse`, `ReviewItemResponse`, `AggregateResponse` (all verified). So deriving If-Match from the in-hand entity/row is feasible everywhere a conditional write is scoped.
6. **Review comment POST requires neither If-Match nor Idempotency-Key** — correct. `create_comment` in `review/routes.py` has no `if_match`/idempotency param; only `patch_review_item` calls `require_matching_etag`.
7. **Terminology add-term and patch-term require If-Match against the extension's revision** — correct. `terminology/routes.py` lines 455 (add term) and 509 (patch term) both call `require_matching_etag(if_match, extension.revision)`; delete-term (545) likewise. `useCreateExtensionTerm` mutate vars `{ extensionId, data }`, `usePatchExtensionTerm` `{ termId, data }`.
8. **`retireReference` is a body-less DELETE taking `(referenceId, options)`; If-Match flows via `request`** — correct. Generated `retireReference` has no `data`; mutate vars `{ referenceId }`.
9. **Body-model field types in the §4 scope map** — correct for `StudyPatch { name?, status? }`, `ReferenceCreate { reference_type, natural_key(1–128), display_name(1–255), value }`, `IntegrationWrite { integration_code(@pattern), display_name, direction, external_subject?, allowed_modules: string[] }`, `SubscriptionWrite { callback_url, event_types: string[], headers?, timeout_seconds?(1–30) }`, `ExtensionTermWrite { code(1–128), submission_value(1–255), decode(1–1000), definition?, preferred_term?, synonyms?: string[] }`. The `tags → string[]` mapping is correct for `allowed_modules`, `event_types`, `synonyms`.
10. **The four aggregate create hooks exist with the stated names and `{ studyId, data: AggregateCreate }` mutate vars** — correct (`raw.ts`/`sdtm.ts`/`adam.ts`/`tlf.ts`).
11. **Idempotency scope (bulk import / build / execution / reconciliation-run / redelivery / submission-package)** — correct per api-contract §3.4 and §3.7.
12. **Problem shape has both `issues[]` (with `field_path`) and `errors[]` (with `location`)** — correct. `ProblemDetails` carries `issues: list[...]` and `errors: list[...]`; transport failures populate `errors[]` with `{ location, message, type }`, application errors populate `issues[]`. The design's two-array handling is the right surface.
13. **`patch_review_item` uses `model_dump(exclude_unset=True)`** — correct (`review/routes.py` line 184), so the "omit empty optionals on PATCH" edge-case handling is valid.
14. **Scoped-vs-collection hook arities** — correct. Collection creates take `(studyId, data, options)` → mutate `{ studyId, data }`; member patches take `(resourceId, data, options)` → mutate `{ resourceId, data }`. (Verified across studies/reference/terminology/aggregates.)

## Unverified / Wrong Assumptions

1. **WRONG (Finding 1): "reference create form within the flat-field pattern plus one repeatable row handled as two `tags`-style inputs."** `ReferenceField.name` is a single `@pattern` string and `ReferenceField.value` is `string | number | boolean | null` — neither is a `tags`/`string[]` control, and neither is reachable through `name: keyof ReferenceCreate & string`. The nested-body create cannot be expressed by the stated `FieldDescriptor` contract.
2. **WRONG (Finding 2): `onSubmit: (body: TBody) => Promise<unknown>` as the complete submit contract.** Every scoped mutation needs path ids (`studyId`/`referenceId`/`extensionId`/`termId`) in its mutate variables; the body alone does not type-check. The split (screen owns the wrap) is right but the responsibility is never stated.
3. **CONFLICTING (Finding 3): dialog `buildRequest` prop.** §3e references a `buildRequest` prop on the shared form that §1's prop list does not contain and that contradicts §1's "hook lives in the screen" rule. Not verifiable because the two sections describe different components owning the hook call.
4. **OVERSTATED (Finding 6): idempotency trigger is "specified and in place" for a "one-line add."** The hook-call-time `request` binding (verified) vs onClick key generation ordering is not actually resolved; the one-line claim is not supported by the generated mutate-variable shape.
5. **UNVERIFIED (not blocking): `ReviewItemPatch` / `ReferencePatch value` / `IntegrationPatch` / `ExtensionTermPatch` exact optional field sets.** The design defers these to "read the sub-models" and I did not open every patch model; the design does not hard-code them, so this is a deferred read, not a wrong claim. `ReferencePatch { display_name?, value? }` was verified; the others were not opened in this review.
6. **UNVERIFIED (not blocking): existence of `getListXxxQueryKey`/`getGetXxxQueryKey` in every tag file.** Verified in `studies.ts` and `reference.ts` (`getListStudiesQueryKey`, `getGetStudyQueryKey`, `getListReferencesQueryKey`, `getGetReferenceQueryKey` all present). Not opened for every module, but the Orval generation pattern is uniform across the files inspected, so the risk is low.

---

## Verdict

HIGH findings: 2 (Findings 1, 2).
MEDIUM findings: 4 (Findings 3, 4, 5, 6).
NIT findings: 2 (Findings 7, 8).

HIGH + MEDIUM = 6 > 0 → **CHANGES_REQUESTED**.

The concurrency/idempotency core (the highest-risk decision — deriving If-Match from `revision`) is correct and verified, as is the header-injection shape and the mutator `Content-Type` hazard mitigation. The blocking issues are in the shared-form contract: it cannot express the Reference create body it commits to (Finding 1), and its submit signature drops the path ids every mutation needs (Finding 2). Resolve those two plus the four MEDIUM clarifications and the design is implementable.
