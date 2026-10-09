# Auto-resolve SDTM input-selection validation run and fingerprint

The SDTM "Input selection" panel no longer asks the user to type the two opaque internal values (`validation_run_id`, `raw_dependency_fingerprint`). After a Raw workbench is picked, the dependency fingerprint is read from the already-exposed `GET /raw/{raw_id}/dependencies` and the validation-run id is resolved from a new additive Raw sub-resource `GET /raw/{raw_id}/latest-validation-run`. Both are shown read-only, labeled "Resolved from `<raw code — name>`", copyable, and flow unchanged into the submitted `SdtmInputSelectionWrite` body. The path chosen was BACKEND-EXTENDED (one additive, read-only Raw route) plus frontend wiring, which matches the user's message 3 ("if there is not aggregate / raw context / dependencies response please also consider resolve from backend"): the fingerprint was already available, the validation-run id was not exposed by any existing endpoint, so the smallest additive Raw-owned route was added for it.

Watch for: the typed client for the new route was **hand-added, not produced by orval** (confirmed) because of a pre-existing orval duplicate-schema blocker; this is out of scope but means the generated tree is not machine-reproducible until that blocker is fixed. Also, commit `9e5bd5b` bundles two unrelated `docs/api-contract.md` edits (ADaM Define `reconcile` route line and ADaM 10.3 prose) that belong to other in-flight ADaM work (likely confirmed).

**Verdict**: APPROVED

## High-level view

The behavioral requirement — stop typing two opaque values, resolve and show them read-only labeled "resolved from `<raw>`", with no free-text fallback — is met. The two free-text inputs are replaced by a `ResolvedField` that renders a read-only copyable input when a value is present and a non-editable `role="status"` prompt when nothing resolved; it never degrades to an editable box. Resolution flows into form state only when non-empty, so a seeded persisted pin is never blanked while a resolver loads or errors.

The backend addition is correctly scoped and placed. The new route lives in the Raw module (`src/app/raw/routes.py`), is study-scoped through the existing `_raw(...)` guard, persists nothing, and resolves the newest `succeeded` Raw validation run directly from the `ValidationRun` model's existing columns — no persistence change, so correctly no migration. SDTM consumes it only through the generated typed client, not Raw repositories. The route is additive to `/api/v1`, documented in `docs/api-contract.md`, added to the contract fixture, and the Raw descriptor version is bumped. A dedicated sub-resource (rather than extending the shared generic `AggregateResponse`/`DependencySelectionResponse`) is the right call: adding Raw-only fields to those cross-module envelopes would leak Raw semantics into every module, which AGENTS.md forbids.

The known gap is the typed client provenance: it was hand-written to mirror orval's output because a pre-existing duplicate-schema collision (from uncommitted ADaM/SDTM-Define work) makes orval fail and wipe the tree. The hand-added files are additive-only and shaped to reconcile with a future regen, and the backend `api:export` was confirmed to include the new path. This is a reasonable interim per Option A, but it is a traceability caveat worth stating plainly.

<details>
<summary>Issues (3)</summary>

1. **Hand-added typed client** (confirmed) — the new hook/model under `frontend/src/api/generated/**` were written by hand, not emitted by orval, because of a pre-existing duplicate-schema blocker. Non-blocking for this task; track the orval fix so the client becomes reproducible.
2. **Unrelated doc edits bundled in the commit** (likely) — `docs/api-contract.md` ADaM Define `reconcile` line and ADaM 10.3 prose changes are unrelated to input-selection resolve and should ideally live with the ADaM work. Non-blocking.
3. **Unknown-raw integration assertion is coarse** (confirmed) — the integration test asserts `404` for an unknown `raw_id` but does not assert the `raw_not_found` code, so it would also pass on an unrelated 404. Minor; tighten if touched again.

</details>

<details>
<summary>Details</summary>

### No free-text fallback: ResolvedField

`ResolvedField` renders three states keyed on whether a value is present: a loading skeleton (only while loading and no value yet), a read-only `<Input readOnly>` plus a `CopyButton` when a value resolved, and a `role="status"` paragraph prompt when nothing resolved. The prompt path reuses the field `id` on a `<p>`, so there is structurally no editable input to type an unresolved value into — this is what the new no-run test asserts (`document.getElementById('is-validation-run').tagName` must not be `INPUT`). The empty messages are context-specific: "Select a Raw workbench first" before a pick, "Run and pass validation on this Raw workbench first" on a 404, "No … resolved yet" otherwise. The provenance line "Resolved from `<raw code — name>`" renders only when a value is present, falling back to the raw id when the aggregate is not in the current list. This satisfies requirement 1 and the explicit "never a free-text fallback" constraint.

### Resolution flow and the "don't blank a seeded value" guard

Two effects push resolved values into form state, each guarded to overwrite only when the resolver returned a non-empty value and it differs from the current field:

```ts
React.useEffect(() => {
  if (!resolvedValidationRunId) return
  setForm((prev) => prev.validation_run_id === resolvedValidationRunId
    ? prev : { ...prev, validation_run_id: resolvedValidationRunId })
}, [resolvedValidationRunId])
```

A still-loading or errored resolver yields `''`, the early return fires, and a seeded persisted value survives. This is the same "ignore empty, don't blank seeded" discipline already used by `selectRawAggregate`/`selectArtifact`. The seed-from-selection effect is keyed on `selection.revision` via a ref so it reseeds after save/reload without clobbering an in-progress edit. Requirement 4 (gated on `!!studyId` and a chosen `raw_id`; seeded values preserved; failed/empty shows an inline message, not a blank or free-text box) holds. The resolver queries are gated `enabled: !!studyId && !!form.raw_id`, and the validation-run query uses `retry: false` so the 404 surfaces immediately as the prompt rather than retrying.

### Body shape preserved

`toWriteBody` is unchanged and still emits all five fields — `raw_id`, `raw_revision` (as `Number`), `validation_run_id`, `raw_dependency_fingerprint`, and `source_artifacts[].{dataset_code, artifact_id, checksum}` — now sourced from the resolvers rather than typed. The 10.1 test asserts the submitted body carries `validation_run_id: 'vr-1'` and `raw_dependency_fingerprint: 'raw-dep-fp'` seeded from the resolver fakes, confirming requirement 2 end to end. Everything else in requirement 3 is intact and visible in the panel: aggregate ETag via `ifMatch()` rebound each render; the 422 `sdtm_raw_artifact_invalid`/`sdtm_raw_validation_invalid` detail+issues block; the `input_refresh_required` `StalenessBanner`; the 412 reload path (`handleReloadRevision` invalidates the aggregate query then `putSelection.reset()`); the `RawContextView`; add/remove artifact rows with the `length <= 1` guard; the "Save input selection" button; and `<Label htmlFor>` on every field including the resolved ones.

### Backend route: ownership, scoping, additivity

The new route is Raw-owned and thin:

```
GET /api/v1/raw/{raw_id}/latest-validation-run
```

It runs `_raw(session, registry, raw_id, principal)` for study-scoped access (an unknown/foreign raw id raises `raw_not_found` → 404), then selects the newest `ValidationRun` filtered by `module_key == "raw"`, `owner_type == "raw_workbench"`, `owner_id == raw.id`, `status == "succeeded"`, ordered by `completed_at`/`started_at`/`id` descending with `limit(1)`. No row ⇒ `404 raw_validation_run_not_found`. All columns referenced already exist on `ValidationRun`, so there is genuinely no persistence change and correctly no migration (requirement 5). The response is a dedicated typed `RawLatestValidationRunResponse` (`extra="forbid"`), not a leaked ORM model.

The `_manifest_raw_revision` helper is a nice correctness detail: `raw_revision` is read from the run's `input_manifest`, and because `bool` is an `int` subclass it is explicitly rejected so a stray `True` never pins revision `1`; any non-int becomes `None`, documented as advisory. This matches the plan's "if a run can lack it, make it optional" note and the response types it `int | None`.

The decision to add a sub-resource rather than extend `AggregateResponse` or `DependencySelectionResponse` is the correct AGENTS.md call — those are shared cross-module envelopes produced for every module, and injecting Raw-only validation semantics would change every module's contract and leak ownership. The dependency fingerprint is deliberately not re-exposed here; the frontend reads it from the existing `GET /raw/{raw_id}/dependencies`. SDTM consumes the new route only through the typed client boundary, never Raw repositories.

### Typed client provenance (the one real caveat)

The verification evidence and commit message both state plainly that `frontend/src/api/generated/raw/raw.ts` (hook + query helpers + fetcher) and the three model files were **hand-authored** mirroring orval's `getRawDependencies` output, not emitted by orval. Reading the committed files confirms they carry the standard orval banner and match the generator's structural pattern (the three overloaded `useGetLatestValidationRun` signatures, `getGetLatestValidationRunQueryKey`, `getGetLatestValidationRunQueryOptions`, `getLatestValidationRun`). The stated reason is a pre-existing orval failure: uncommitted ADaM/SDTM-Define work emits duplicate OpenAPI schema names (`ExportSpecificationParams`, `ValidatePlan200`, etc.) that orval rejects, and orval runs with `clean: true` so a failed run wipes the whole generated tree. The backend `api:export` was confirmed to boot and include `/api/v1/raw/{raw_id}/latest-validation-run`, and `openapi.json` was restored to its committed baseline.

This is the honest and reasonable interim under Option A: the diff is additive-only and shaped so the next successful regen produces an identical result. It is not a blocking defect for this task, but it is a real traceability gap — the generated client is temporarily not machine-reproducible — and it depends on a separate fix landing. Flagging it rather than burying it is the right posture per AGENTS.md's no-silent-divergence rule, and the author did flag it.

### Tests

The component test extends the existing raw mock with `useGetRawDependencies` and `useGetLatestValidationRun` fakes driven by a mutable `rawApi`, seeded in `beforeEach` to `vr-1` / `raw-dep-fp` so the resolved values equal the pinned fixtures. 10.1 (full body + If-Match), 10.4 (422 detail+issues), 10.5 (staleness banner), and 10.6 (412 reload) are retained. A new test seeds a saved selection pinning `raw-1` with an empty `validation_run_id`, drives the latest-validation-run fake to a 404, and asserts both the inline prompt and the absence of an editable input at `is-validation-run` — directly exercising requirement 4's failure state and the no-free-text constraint. The backend integration test `test_raw_latest_validation_run_resolution` covers 404-before-any-run, failed-run-ignored, newest-succeeded-selected (asserting it is the second run, not the first), advisory `raw_revision` matching the aggregate revision, a 64-char `input_fingerprint`, and an unknown-raw 404. The unit tests cover `_manifest_raw_revision` coercion (int/0/None/str/float/bool) and `_latest_validation_run_response` mapping. The unknown-raw integration assertion checks status `404` but not the `raw_not_found` code, so it is slightly coarser than it could be — minor.

Verification evidence is present and specific (tsc, vitest 278 passed, eslint 0 errors, ruff/mypy clean, unit+contract 12 passed, api:export includes the route). The integration test is gated behind `AURINARA_INTEGRATION=1` + Compose services and was not run in this environment, which the evidence states openly; that is consistent with the repo's integration-test gating. No spot-check was warranted — the evidence does not leave a specific articulable doubt.

### Unrelated changes bundled in the commit

Commit `9e5bd5b` also carries two `docs/api-contract.md` edits unrelated to input-selection resolve: a `POST /api/v1/adams/{adam_id}/define/reconcile` route line and a rewrite of the ADaM 10.3 preview/compile/execute prose. These belong to the in-flight ADaM work visible in the broader working tree, not to this task. Not a correctness problem and not blocking, but ideally these would travel with the ADaM change for clean traceability.

</details>

<details>
<summary>File map</summary>

- `src/app/raw/routes.py` — new `RawLatestValidationRunResponse` model, `GET /raw/{raw_id}/latest-validation-run` handler, and pure helpers `_latest_validation_run_response` / `_manifest_raw_revision`.
- `src/app/raw/descriptor.py` — Raw `module_version` 0.3.0 → 0.4.0 (additive surface growth).
- `docs/api-contract.md` — new Raw route documented; two unrelated ADaM Define edits bundled.
- `tests/contract/typed_client_fixture.py` — new route added to `PHASE3_RAW_SDTM_OPERATIONS`.
- `tests/unit/test_raw.py` — unit tests for revision coercion and response mapping.
- `tests/integration/test_phase3_raw_sdtm.py` — `test_raw_latest_validation_run_resolution`.
- `frontend/src/components/workbench/input-selection-panel.tsx` — resolver queries, `ResolvedField`, resolution effects, free-text inputs removed; all preserved behaviors intact.
- `frontend/src/components/workbench/-input-selection-specification.test.tsx` — resolver fakes, resolved-values-into-body coverage, no-successful-run prompt test.
- `frontend/src/api/generated/raw/raw.ts`, `.../model/rawLatestValidationRunResponse*.ts`, `.../model/index.ts` — hand-added typed client mirroring orval output (additive only).

Full diff: `git show 9e5bd5b`.

</details>
