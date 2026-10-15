# TLF module

Status: Phase 5 implemented. The module owns immutable Shell, exact ADaM Bindings,
Assumptions, ARS, and ProgramPlan revisions; validation and Analysis IR lowering;
deterministic Python/R/SAS programs; isolated Python/R execution; normalized CSV and Parquet
results; and table, listing, and figure rendering.

## Author a TLF

Create a workbench and retain its `ETag` after every write:

```powershell
$tlf = Invoke-WebRequest -Method Post -Uri "$base/studies/$studyId/tlfs" -Headers $headers `
  -ContentType "application/json" -Body '{"code":"T-14-1","name":"Disposition table"}'
$tlfId = ($tlf.Content | ConvertFrom-Json).id
$etag = $tlf.Headers.ETag
```

Replace dependencies through `PUT /tlfs/{tlf_id}/dependencies`. Selections are exact;
publishing a newer Standard, Terminology, Reference, or Template version never changes an
existing workbench. Select one exact presentation Template per rendered artifact type.

Author resources in this order, passing the current workbench `If-Match` value each time:

1. `PUT /tlfs/{tlf_id}/shell`
2. `PUT /tlfs/{tlf_id}/bindings`
3. `PUT /tlfs/{tlf_id}/assumptions`
4. `PUT /tlfs/{tlf_id}/ars`
5. `PUT /tlfs/{tlf_id}/program-plan`

Bindings identify the exact ADaM workbench revision, successful validation run, immutable
CSV or XPT artifact, checksum, dataset code, and dependency fingerprint. ARS must cover every
leaf shell row exactly once. ProgramPlan pins the four current prerequisite revisions and maps
every ARS analysis to one typed `frequency`, `descriptive_statistics`, or `custom` step. A custom
step references a plan-owned function whose fixed parameters are `rows` and `parameters`, whose
return type is `result_rows`, and whose result conforms to the normalized `statistic`, `value`,
and `text` row contract. Saving an upstream
revision makes an older ProgramPlan misaligned; save a deliberate new plan revision to realign it.

Shell title, hierarchy, columns, footnotes, orientation, and Template styling remain outside
Analysis IR. Templates cannot add populations, parameters, statistics, steps, or narrative.

## Validate, preview, compile, and execute

`POST /tlfs/{tlf_id}/program-plan/preview` returns the normalized internal Analysis IR only as a
read-only preview. It is never an editable or persisted public planning resource.

Create an immutable validation snapshot with either:

```text
POST /api/v1/tlfs/{tlf_id}/program-plan/validate
POST /api/v1/tlfs/{tlf_id}/validate
```

Compilation uses `POST /tlfs/{tlf_id}/compile` with `backend` set to `python`, `r`, or `sas`, an
`Idempotency-Key`, and the exact build-input fingerprint. Generated program manifests freeze the
Shell, Bindings, ProgramPlan, dependency selection, ADaM artifacts/checksums, normalized Analysis
IR, and compiler fingerprint.

Each custom function may have Python, R, SAS, or multiple implementations. The program for a
language with a supplied body is executable. Other languages receive deterministic TODO stubs and
manifest fields `compiler.executable=false` plus `compiler.todo_functions`; those artifacts remain
reviewable but execution returns `execution_custom_function_incomplete`. Preview never evaluates
custom bodies in the API process.

Run Python or R with `POST /tlfs/{tlf_id}/execute`. Select exactly the program's frozen ADaM
artifacts and supply the bound validation run, Shell revision, Bindings revision, ProgramPlan
revision, compiler fingerprint, input fingerprint, and bounded execution limits. SAS execution
uses the optional external adapter and reports `runner_not_configured` when none is configured.
Successful runs publish validated `tlf_result_csv` and `tlf_result_parquet` artifacts from the
same normalized result with columns:

```text
analysis_id,row_id,group,statistic,value,text
```

## Render and build artifacts

Use `POST /tlfs/{tlf_id}/render` after a successful current run. Tables and listings support
`rtf` and `pdf`; figures support `png`, `svg`, and `pdf`. Rendering binds the exact result and
execution run to the current Shell. It never recompiles the analysis.

`POST /tlfs/{tlf_id}/artifacts` can build the JSON authoring snapshots, validation report,
programs, dependency manifest, formatted outputs, and `tlf_output_index`. All build and execution
operations require `Idempotency-Key`; regeneration creates a new immutable artifact.
