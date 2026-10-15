# ADaM module

Status: Phase 4 Define and ADRG slice. The current API supports exact SDTM input selection, immutable
ADaM Specification revisions, aligned immutable Derivation Plan revisions, plan validation,
dependency compatibility checks, atomic JSON/XLSX Specification exchange, bounded preview,
lineage, immutable validation snapshots, deterministic metadata/report/program artifacts, and
exact-provenance Python/R execution that publishes CSV and XPT v5 datasets, version-neutral
ADaM Define authoring, XPT reconciliation, Define-XML 2.0/2.1 publication, and versioned ADRG
authoring and DOCX/PDF publication.

The runner conformance suite lowers one manually authored ADaM Specification/Derivation Plan pair
to the same internal IR fingerprint, executes its generated Python and R programs in isolated
containers, and compares the ADSL schema, declared column order, and discrete values exactly.
Supported typed value-level equality and ordering conditions render as formal machine-readable
Define structures. Typed Protocol/SAP trace targets are verified and replaced as normalized trace
links in the same transaction as each Specification revision.

## Create a workbench and select dependencies

```powershell
$adam = Invoke-WebRequest -Method Post -Uri "$base/studies/$studyId/adams" -Headers $headers `
  -ContentType "application/json" -Body '{"code":"ADAM-01","name":"ADaM workbench"}'
$adamBody = $adam.Content | ConvertFrom-Json
$etag = $adam.Headers.ETag
```

Use `PUT /adams/{adam_id}/dependencies` with the current `ETag` to replace the complete
dependency selection. If ADaM and the chosen SDTM context both select the same Standard
purpose or Terminology scope, their exact version IDs must match.

## Select exact validated SDTM inputs

First obtain the current SDTM workbench, dependency fingerprint, successful validation run,
and available XPT artifact IDs/checksums. Then pin them atomically:

```powershell
$body = @{
  sdtm_id = $sdtmId
  sdtm_revision = 7
  validation_run_id = $sdtmValidationRunId
  sdtm_dependency_fingerprint = $sdtmDependencyFingerprint
  xpt_artifacts = @(
    @{ dataset_code = "DM"; artifact_id = $dmXptId; checksum = $dmChecksum }
  )
} | ConvertTo-Json -Depth 5

$selection = Invoke-WebRequest -Method Put -Uri "$base/adams/$($adamBody.id)/input-selection" `
  -Headers ($headers + @{ "If-Match" = $etag }) -ContentType "application/json" -Body $body
$etag = $selection.Headers.ETag
```

The API accepts only available `sdtm_dataset_xpt` artifacts from the current aligned SDTM
Specification, input selection, and Derivation Plan. The validation run must be successful,
error-free, and bind those same exact revisions. `GET /adams/{id}/sdtm-context` returns only
the XPT artifacts selected by this ADaM workbench, plus the SDTM metadata snapshot.

## Save an ADaM Specification

`PUT /adams/{id}/specification` creates a new immutable revision and requires `If-Match`.
The request is one atomic document containing:

- datasets with stable UUIDs, natural codes, class, structure, keys, and sort order;
- variables with stable UUIDs, roles, exact origins, output node IDs, and optional terminology;
- parameters and value-level metadata with stable UUIDs;
- reviewer-readable methods linked to Derivation Plan node IDs.
- typed trace targets from exact Protocol/SAP entities to exact ADaM entities.

Example skeleton:

```json
{
  "schema_version": "1.0.0",
  "datasets": [{
    "id": "10000000-0000-0000-0000-000000000001",
    "code": "ADSL",
    "label": "Subject-Level Analysis Dataset",
    "dataset_class": "SUBJECT LEVEL ANALYSIS DATASET",
    "structure": "One record per subject",
    "keys": ["USUBJID"],
    "sort_order": ["USUBJID"],
    "expected_output_name": "adsl.xpt",
    "variables": [{
      "id": "20000000-0000-0000-0000-000000000001",
      "name": "USUBJID",
      "label": "Unique Subject Identifier",
      "data_type": "character",
      "length": 40,
      "role": "Identifier",
      "origin": {
        "origin_type": "Predecessor",
        "source_kind": "sdtm",
        "source_dataset": "DM",
        "source_variable": "USUBJID"
      },
      "output_node_id": "read_dm"
    }]
  }],
  "methods": [],
  "trace_targets": [{
    "relationship_type": "analyzes",
    "source": {
      "module": "documents",
      "entity_type": "sap_method",
      "entity_id": "60000000-0000-0000-0000-000000000001"
    },
    "target": {
      "module": "adam",
      "entity_type": "adam_dataset",
      "entity_id": "10000000-0000-0000-0000-000000000001"
    }
  }]
}
```

`Assigned` and `Derived` origins may include a description but cannot claim an exact source.
`Predecessor` origins require `source_kind`, `source_dataset`, and `source_variable`.

### Import and export

`GET /adams/{id}/specification/export?format=json|xlsx` returns a non-persisting export of
the current revision. The versioned workbook contains `Metadata`, `Datasets`, `Variables`,
`Parameters`, `ValueLevel`, `Methods`, and `TraceTargets` sheets and preserves typed expressions,
origins, terminology bindings, stable UUIDs, method-to-node links, and exact trace endpoints.

Trace sources are registered Protocol objectives/endpoints or SAP objectives/endpoints, estimands,
populations, or methods. Destinations are Specification datasets, variables, parameters, or
value-level items. The save fails with
`422` before commit when an endpoint does not exist in the same study or the relationship type is
not registered. Replacing a Specification revision removes only its superseded declared links;
the normalized `trace_links` table remains the single relationship store.

`POST /adams/{id}/specification/import` accepts JSON or that XLSX contract. It requires the
current `If-Match` value and an `Idempotency-Key`. The complete workbook is validated before
one immutable revision is committed. Replaying the same key and bytes returns the original
revision; reusing the key for different bytes returns a conflict.

## Save and validate a Derivation Plan

`PUT /adams/{id}/derivation-plan` also requires the current `ETag`. Its
`specification_revision` and `input_selection_revision` must match the current records.

```json
{
  "schema_version": "1.0.0",
  "specification_revision": 1,
  "input_selection_revision": 1,
  "nodes": [
    {"node_type": "sdtm_read", "id": "read_dm", "dataset": "DM"},
    {"node_type": "dataset_write", "id": "write_adsl", "dataset": "ADSL"}
  ],
  "edges": [{"source_node": "read_dm", "target_node": "write_adsl"}]
}
```

The initial node vocabulary is `sdtm_read`, `adam_read`, `filter`, `derive`, `select`,
`assert`, and `dataset_write`. Expressions are typed expression objects; raw code in ordinary
nodes and arbitrary expression strings are rejected. A plan may declare typed named
`custom_functions` with fixed signatures and explicit Python, R, and/or SAS bodies, then invoke
them through `custom_function` expressions. `POST /adams/{id}/derivation-plan/validate`
checks current alignment and returns the deterministic internal IR fingerprint.

`POST /adams/{id}/derivation-plan/preview` accepts optional target `datasets` and a row
`limit` from 1 through 200. The SDTM module verifies and reads the exact selected XPT bytes,
including their SHA-256 checksums; ADaM receives only typed rows through the context interface.
The same lowered IR used by later compilation evaluates the bounded preview. Results are
transient and are not artifacts. `GET /adams/{id}/lineage` returns the normalized ancestor
node IDs for each declared dataset write.

Saving a new Specification or input selection marks the current plan `misaligned`. Until a
new plan revision pins the current revisions, plan validation and later dependent operations
return `409 adam_plan_misaligned`. If SDTM changes, resolving the context fails as stale; the
ADaM metadata itself is not rewritten or silently rebound.

## Validate, build, compile, and execute

`POST /adams/{id}/validate` creates an immutable, zero-error validation snapshot over the exact
ADaM dependency selection, selected SDTM context and XPT checksums, Specification revision,
Derivation Plan revision, and normalized IR. Compilation and artifact generation require a
current successful snapshot; a later authoring or input change makes it unusable.

`POST /adams/{id}/artifacts` accepts one or more of:

- `adam_dependency_manifest`
- `adam_specification` (XLSX) and `adam_specification_json`
- `adam_derivation_plan_json`
- `adam_derivation_report` and `adam_traceability_report` (JSON)
- `adam_validation_report` (JSON)
- `adam_program_python`, `adam_program_r`, or `adam_program_sas`

`POST /adams/{id}/compile` is the single-backend convenience route. Both routes require an
`Idempotency-Key` and the expected canonical build-input fingerprint. The resulting immutable
artifact records freeze dependency, input-selection, Specification, plan, validation, IR, and
compiler provenance.

Custom implementations are backend-specific. If the selected language has a body, its generated
program is executable. If it does not, the compiler still creates a reviewable TODO program with
`compiler.executable=false` and `compiler.todo_functions`; only execution of that artifact is
rejected with `execution_custom_function_incomplete`.

Use `POST /adams/{id}/execute` with the exact generated program, selected SDTM XPT artifact IDs,
validation run, authoring revisions, compiler fingerprint, program input fingerprint, limits,
and an `Idempotency-Key`. Python and R use the shared isolated runner boundary. The dispatcher
stages each checksum-bound XPT as deterministic CSV in a fresh workspace, validates that the
program emits exactly the declared datasets, and publishes `adam_dataset_csv`,
`adam_dataset_xpt`, and `adam_execution_log` artifacts. XPT v5 generation enforces the saved
ADaM variable order, types, labels, and character widths and independently reads the file back
before publication. SAS programs are generated; without an external SAS adapter execution ends
with the typed `runner_not_configured` result.

## Maintain version-neutral Define metadata

The current Define foundation provides `GET` and `PUT /adams/{id}/define`,
`POST /adams/{id}/define/initialize`, and `POST /adams/{id}/define/validate`.
Every immutable revision pins the current Specification and input-selection revisions plus exact
available `adam_dataset_xpt` artifact IDs, filenames, and checksums. Its datasets retain classes,
roles, parameters, value-level metadata, origins, terminology bindings, and reviewer-readable
methods from the ADaM Specification.

Initialization requires the workbench `ETag` and `expected_define_revision`. It adds missing
datasets, variables, and methods from current metadata and refreshes exact leaf facts, while
preserving maintained labels and other existing metadata. Replacing an existing output selection
requires an explicit complete `PUT`; initialization will not silently rebind it. Preserved edits to
factual dataset metadata remain visible but must reconcile with the current Specification before
publication; top-level descriptive fields remain independently maintained. Define validation
creates an immutable common-model issue snapshot and compares dataset metadata, variables,
parameters, value-level metadata, origins, method bindings and definitions, and terminology
bindings with the current Specification. Predecessor origins must resolve in the exact selected
SDTM datasets or maintained ADaM metadata. It also checks complete dataset output coverage, exact
leaf identity/checksums, and both repository-pinned XSD suites. `GET
/adams/{id}/define/render?version=2.0|2.1` provides a non-persisting preview only after that
validation succeeds.
Exact terminology bindings render as ODM aliases. Parameters and complete typed value-level
contracts are preserved deterministically in referenced Define comments. Conditions composed of
same-dataset column-to-literal equality or ordering comparisons, including conjunctions, also
render as machine-readable `ValueListDef`/`WhereClauseDef` structures. Conditions that cannot be
represented faithfully by Define range checks remain comment-only; the renderer never substitutes
or simplifies their semantics.

`POST /adams/{id}/define/reconcile` creates a durable immutable comparison between one exact
Define revision and every selected ADaM XPT checksum. The capability-dispatched evaluator checks
dataset coverage, filenames and labels; exact variable order, names, labels, types, lengths,
origins, and methods; undefined XPT variables; and leaf identities, filenames, and checksums.
After a zero-error reconciliation, `POST /adams/{id}/define/artifacts` can publish one or both
immutable `adam_define_xml_20` and `adam_define_xml_21` artifacts. Publication records the Define
validation run, reconciliation run, local XSD fingerprint, dependencies, authoring revisions, and
exact output checksums. A superseded SDTM context stales Define and ADRG validations and blocks
Define publication until the ADaM input selection and dependent evidence are refreshed.

## Author, validate, and publish the ADRG

Before producing ADaM evidence, select one exact compatible Template for each requested format
with `PUT /adams/{id}/dependencies`. Use purpose `presentation`, artifact types
`adam_adrg_docx` and `adam_adrg_pdf`, and the same approved template version when it supports both
formats. Changing that selection later correctly stales dependent evidence.

ADRG initialization is available only after current Define validation and a successful zero-error
`adam_define_outputs` reconciliation. Call `POST /adams/{id}/adrg/initialize` with the current
workbench `If-Match`, expected ADRG revision, exact current Define revision, and exact
reconciliation run ID:

```json
{
  "expected_adrg_revision": null,
  "title": "Analysis Data Reviewer's Guide",
  "version": "1.0",
  "define_revision": 3,
  "reconciliation_run_id": "10000000-0000-0000-0000-000000000001"
}
```

Initialization derives immutable factual tables from the exact Define-selected XPT artifacts and
their successful execution/program evidence. It creates the required narrative section shells but
does not invent clinical conclusions. Populate every section's `paragraphs` with manually authored
content and save the complete payload using `PUT /adams/{id}/adrg` plus the current `If-Match`.
Reinitializing with `expected_adrg_revision` set to the current ADRG revision refreshes factual
evidence and preserves those paragraphs, headings, title, and version.

`POST /adams/{id}/adrg/validate` creates an immutable validation snapshot. Missing manual content
in any required section is an error. After zero-error validation, resolve the canonical build-input
fingerprint and call `POST /adams/{id}/adrg/artifacts` with an `Idempotency-Key`:

```json
{
  "artifact_types": ["adam_adrg_docx", "adam_adrg_pdf"],
  "expected_input_fingerprint": "<64-character canonical fingerprint>"
}
```

The asynchronous build freezes the ADRG revision, exact input/Specification/plan/Define revisions,
XPT and program checksums, reconciliation and validation runs, and Template ID/version/checksum.
Both formats are rendered from the same shared `Document` representation; regeneration creates new
immutable artifacts.

## Verify Python/R conformance

Build both pinned local runner images and enable the runner integration profile:

```powershell
docker compose --profile runners build python-runner r-runner
$env:AURINARA_RUNNER_INTEGRATION = "1"
uv run pytest tests/integration/test_execution_runners.py -q
```

The ADaM fixture uses `lower_plan` rather than constructing IR directly. It therefore proves that
the module-owned Specification and Derivation Plan adapter, shared IR canonicalization, both
compilers, and both isolated runners produce the same exact structural and discrete result. The
test also requires the Python and R compiler manifests to carry the same IR fingerprint.
