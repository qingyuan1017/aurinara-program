# Documents module

Status: Phase 2 vertical slice implemented for manually authored Protocol, SAP, narrative,
operational, quality, signal, action, and workbook deliverables.

## 1. Create the document

For a Protocol, upload its source PDF first. Then create the aggregate:

```powershell
$body = @{
  document_code = "PROT-001"
  name = "Example Protocol"
  document_type = "protocol"
  content_schema_version = "1.0.0"
  source_pdf_file_id = $sourceFileId
  related_document_ids = @()
} | ConvertTo-Json
$document = Invoke-RestMethod -Method Post -Uri "$base/studies/$studyId/documents" `
  -Headers $headers -ContentType "application/json" -Body $body
$documentId = $document.id
```

Supported types are `protocol`, `protocol_amendment_summary_of_change`,
`protocol_deviation_document`, `aggregate_study_risk_profile`, `data_management_plan`,
`statistical_analysis_plan`, `centralized_monitoring_platform_setup_documentation`,
`protocol_deviation_dataset`, `aggregate_study_brief`, `study_data_summary`,
`standard_quality_dashboard_qe_details`,
`standard_quality_dashboard_sqe_audit_capa_details`,
`standard_quality_dashboard_audit_observation_detail`, `signals_report`, and
`actions_report`.

Metadata changes use `PATCH /documents/{id}` with the current `ETag`. Related documents are
explicit IDs; no Protocol or SAP is selected implicitly.

## 2. Author content

Use `PUT /documents/{id}/content` with `If-Match`. A minimal narrative payload is:

```json
{
  "document_type": "protocol",
  "schema_version": "1.0.0",
  "title": "Example Protocol",
  "version": "1.0",
  "sections": [
    {
      "section_id": "objectives",
      "heading": "Objectives",
      "paragraphs": ["Manually authored objective text."]
    }
  ],
  "related_records": []
}
```

Every document type has a strict Pydantic contract. Workbook types use typed `rows` with a
stable `row_id`, description, category, status, owner, dates, and type-specific fields.
`POST /documents/{id}/content/import` supports atomic JSON and, for workbook types, XLSX;
it also requires `Idempotency-Key`. `GET /documents/{id}/content/export?format=json` is a
non-persisting export; workbook types also allow `format=xlsx`.

## 3. Add Protocol USDM and evidence

Protocol-only `PUT /documents/{id}/usdm` accepts the versioned platform USDM subset:

```json
{
  "schema_version":"1.0.0",
  "usdm_version":"4.0",
  "study_version":"1",
  "entities":[
    {"id":"OBJ1","entity_type":"objective","code":"OBJ-1","name":"Primary objective"},
    {"id":"EP1","entity_type":"endpoint","code":"EP-1","name":"Primary endpoint"}
  ],
  "relationships":[
    {"relationship_type":"evaluated_by","source_entity_id":"OBJ1","target_entity_id":"EP1"}
  ]
}
```

The request uses `If-Match`; USDM import also uses `Idempotency-Key`. Add source-PDF evidence
with `POST /documents/{id}/evidence`, a 1-based page, page dimensions, exactly one rectangle
or polygon in `pdf_points_top_left`, and one or more existing USDM entity IDs. Evidence edits
and retirement require `If-Match`.

For a SAP explicitly related to a Protocol, `GET /documents/{sap_id}/protocol-context`
returns read-only objective and endpoint DTOs. Copying or adapting those facts into SAP is
always a user edit; there is no silent synchronization.

## 4. Select dependencies

Use `PUT /documents/{id}/dependencies` with the current document `ETag`. Pin exact standards,
terminology releases/extensions, Reference revisions, and Templates as described in
[dependency-consuming modules](dependency-consumers.md). Every formatted artifact requires
an exact compatible template selection for its own artifact type.

## 5. Validate and build

Call `POST /documents/{id}/validate`; the current implementation completes the immutable
validation snapshot synchronously and returns it in the `202` response. Fix all
error-severity issues before generation. Request artifacts with
`POST /documents/{id}/artifacts`, `Idempotency-Key`, an explicit `artifact_types` list, and
the expected canonical input fingerprint.

Available types depend on the document type and include deterministic DOCX/PDF for narrative
documents, XLSX for workbook documents, JSON snapshots, CSV workbook data, Protocol USDM
JSON, and Protocol evidence overlays. The worker verifies the exact validation snapshot and
dependencies before publishing immutable bytes. List resulting artifacts under the study or
poll the returned build resource.

The current API does not expose a build-fingerprint preview endpoint. Use a trusted client
implementing the canonical input contract; a stale value returns `409` and publishes
nothing.
