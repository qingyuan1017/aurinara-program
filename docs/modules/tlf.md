# TLF module

Status: Phase 5 AI-first portfolio workflow implemented. One TLF workbench owns a study-wide
output inventory and, for each output, immutable Shell, exact ADaM Bindings, Assumptions, ARS,
and ProgramPlan revisions. The module also owns validation, Analysis IR lowering, deterministic
Python/R/SAS programs, isolated Python/R execution, normalized results, and output rendering.

Clinical TLF content supports direct typed create/edit and AI proposals from exact selected
evidence. The API exposes conditional `PUT` routes for Inventory, Shell, Bindings, Assumptions,
ARS, and ProgramPlan. Direct writes and accepted proposals create the same immutable module-owned
revisions under the same validation and staleness rules. AI proposals still require an authorized
human to accept, reject, or request revision with a rationale before they become active.

## Select exact evidence

Create one workbench for the study portfolio and retain its `ETag` after each accepted change.
Replace dependencies through `PUT /tlf-workbenches/{tlf_id}/dependencies`; all selections are exact.

`PUT /tlf-workbenches/{tlf_id}/input-selection` is an operator evidence-selection command, not
clinical authoring. It pins exact accepted Protocol/SAP document content revisions and exact
available ADaM dataset artifacts, including dataset code, artifact ID, checksum, ADaM workbench,
ADaM revision, validation run, and dependency fingerprint. Updating the selection marks current
authored content misaligned so it cannot be validated, compiled, executed, or packaged until new
proposals are reviewed and accepted.

## Create, edit, or propose the portfolio

Every stage has a manual typed editor and can also use the shared proposal lifecycle:

```text
POST /api/v1/tlf-workbenches/{aggregate_id}/proposals
GET  /api/v1/tlf-workbenches/{aggregate_id}/proposals
GET  /api/v1/tlf-workbenches/{aggregate_id}/proposals/{proposal_id}
POST /api/v1/tlf-workbenches/{aggregate_id}/proposals/{proposal_id}:accept
POST /api/v1/tlf-workbenches/{aggregate_id}/proposals/{proposal_id}:reject
POST /api/v1/tlf-workbenches/{aggregate_id}/proposals/{proposal_id}:request-revision
```

Generation is asynchronous. The assistance worker records the exact immutable context, Platform
agent ID/name/revision and service-contract version, instruction version, generation parameters,
response checksum, typed validation results, and field-level diff. Evidence references are JSON
pointers into that saved context. Invalid output remains evidence but cannot be accepted.

The stages are deliberately ordered:

1. `tlf_output_inventory` proposes the study-wide tables, listings, and figures. It distinguishes
   source-required outputs from conventional suggestions and preserves explicit blockers.
2. `tlf_analysis_shells` proposes each accepted output's Shell, ADaM Bindings, Assumptions, and
   ARS. Output identities must exactly match the accepted inventory and Bindings may use only the
   operator-selected ADaM datasets. ARS must cover every leaf shell row exactly once.
3. `tlf_programming_plan` proposes one typed ProgramPlan per accepted output. Every plan pins its
   current Shell, Bindings, Assumptions, and ARS revisions and lowers successfully to Analysis IR
   before it can be accepted.

Acceptance requires the current workbench `ETag` and an idempotency key. Acceptance, immutable
content revisions, provenance links, staleness changes, and the human decision commit together.
Reject and revision-request commands never modify active content. A revision request creates a
linked generation request that includes the reviewer's guidance without treating that guidance as
accepted clinical content.

The guided UI presents the manual typed editor alongside proposal provenance, structured
output/dataset/analysis-step views, assumptions, unresolved items, evidence references, model
limitations, deterministic issues, and a field-level diff.

## Output-scoped validation and execution

Read the accepted inventory at `GET /tlf-workbenches/{tlf_id}/inventory`. Read per-output content
below `/tlf-workbenches/{tlf_id}/outputs/{output_code}/...` using `shell`, `bindings`,
`assumptions`, `ars`, and `program-plan`.

Validation and preview take an explicit `output_code`; they never infer a mutable current output.
ProgramPlan is the executable authority and its normalized Analysis IR is a read-only preview.
Ordinary steps are language-neutral typed registered analysis procedures. Raw Python, R, SAS, SQL,
and arbitrary expression strings are not ordinary authoring paths.

A plan may declare a typed named custom function with fixed inputs and result schema. Each language
body is immutable accepted plan content and runs only through the isolated runner. A missing body
produces a deterministic non-executable TODO artifact for that language without blocking languages
whose bodies are present.

Compilation, artifact build, rendering, and execution all require `output_code`, an idempotency
key where applicable, a successful current validation, and exact frozen inputs. Generated program
manifests freeze the accepted content revisions, input-selection revision and fingerprint, ADaM
artifacts and checksums, dependency selection, normalized Analysis IR, and compiler fingerprint.

Python and R run through the disposable network-disabled runner boundary. SAS uses the optional
external adapter and returns `runner_not_configured` when absent. Successful executions publish
validated normalized result artifacts. Rendering binds one exact result and execution run to the
accepted Shell and presentation Template; it never recompiles the analysis. Regeneration always
creates new immutable artifacts.
