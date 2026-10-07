# Raw module

Status: Phase 3 Raw vertical slice implemented for immutable file binding, manually
maintained dataset/variable metadata, non-destructive factual initialization, bounded
preview, validation, immutable source/schema reconciliation, and artifacts.

## Register a dataset

Upload a CSV, flat JSON array, or XLSX source through the shared source-file endpoint, then:

```powershell
$raw = Invoke-RestMethod -Method Post -Uri "$base/studies/$studyId/raw" -Headers $headers `
  -ContentType "application/json" -Body '{"code":"RAW-01","name":"Raw workbench"}'
$body = @{
  code = "DEMOG"
  label = "Demographics"
  source_file_id = $sourceFileId
} | ConvertTo-Json
$dataset = Invoke-RestMethod -Method Post -Uri "$base/raw/$($raw.id)/datasets" `
  -Headers $headers -ContentType "application/json" -Body $body
```

`PATCH /raw-datasets/{id}` requires `If-Match`. Binding a corrected file creates a new
immutable binding-history row, increments the dataset and Raw revisions, and stales prior
Raw evidence; it never overwrites the old source file.

## Maintain variables

Use `/raw-datasets/{id}/variables` and `/raw-variables/{id}` to create, list, read, edit,
or delete metadata. Names and ordinals are unique within a dataset. Metadata includes label,
physical type, length/precision, ordinal, role, description, and an optional exact
terminology binding.

`POST /raw-datasets/{id}/variables/initialize` reads the bound file and creates absent
variables or fills only missing physical type/length/precision. It never overwrites manual
values and never infers clinical meaning, roles, terminology, mappings, or derivations.

## Preview and validate

`POST /raw-datasets/{id}/preview` accepts optional `columns`, zero-based `offset`, and a
`limit` from 1 to 200. Rows are returned only in the response and are not persisted or
logged.

`POST /raw/{id}/validate` recalculates source checksums, verifies supported file shape,
compares maintained and physical variables/types, and records an immutable validation
snapshot. Error issues block artifact generation.

`POST /raw/{id}/reconcile` requires an `Idempotency-Key` and the expected current Raw revision.
It creates a durable immutable `raw_source_schema` reconciliation over the exact workbench
revision and every bound source artifact ID/checksum. The worker compares maintained variable
names, types, ordinals, declared lengths, and precision with observed physical facts, then
publishes a reconciliation report. Reports include schema evidence and stable common-model issues
but never source rows or internal object-store locations.

## Build artifacts

Select exact dependencies at `/raw/{id}/dependencies`, validate, then request one or more:

- `raw_dependency_manifest`
- `raw_metadata_json`
- `raw_data_dictionary_xlsx`
- `raw_validation_report_json`

Use `POST /raw/{id}/artifacts` with `Idempotency-Key` and the expected canonical input
fingerprint. Poll the build and download the immutable result through shared artifact routes.
The registered context-export capability exposes an immutable Raw revision, exact source
artifacts/checksums, variables, and dependency fingerprint to SDTM without repository access.
