# Packaging module

Status: Phase 5 implemented. Packaging assembles exact immutable artifacts through registered
module package-contribution capabilities. It never upgrades, regenerates, or substitutes an
artifact selected by the caller.

## Create a package

Call `POST /api/v1/studies/{study_id}/submission-packages` with an `Idempotency-Key`:

```json
{
  "name": "Study ABC delivery 1",
  "module_selections": [
    {
      "module": "sdtm",
      "artifact_ids": ["00000000-0000-0000-0000-000000000001"],
      "options": {}
    },
    {
      "module": "documents",
      "artifact_ids": ["00000000-0000-0000-0000-000000000002"],
      "options": {
        "schema_version": "1.0.0",
        "document_types": ["protocol"]
      }
    }
  ],
  "artifact_ids": [],
  "reconciliation_run_ids": [],
  "expected_study_fingerprint": "<64-character resolved fingerprint>"
}
```

Each module selection names a registered module that declares the `packaging` capability.
The module validates its own closed options, required artifacts, current dependencies, and
trusted relative paths. Documents requires explicit `document_types` and the complete required
set for every selected document: Protocol requires the original, USDM, both summaries, annotated
evidence, and both evidence manifests; SAP requires structured JSON plus DOCX and PDF; every
operational or quality type requires its primary PDF or XLSX.

Raw requires its metadata JSON and data-dictionary XLSX. Uploaded source files are excluded by
default. To include current source bindings, set `include_original_sources` to `true` in the Raw
selection and list their exact artifact IDs. Superseded or unrelated uploads are rejected. The
top-level `artifact_ids` collection is for exact shared supporting evidence rather than clinical
package modules.

The service rejects duplicate artifact IDs; cross-study, unavailable, stale, failed, or
incomplete evidence; reconciliation mismatches; mixed TLF runs; absolute/traversal/reserved
paths; and Unicode-normalized or case-insensitive path collisions. It recalculates object bytes
and sizes before publication.

A successful request returns `202 Accepted` with a durable `queued` status resource. The build
worker claims it with a bounded lease, resolves the exact selection again, performs object-store
I/O outside database transactions, and publishes a terminal `succeeded` record. Its ZIP includes
selected artifacts, canonical `manifest.json`,
`package-validation-report.json`, and `checksums.sha256`. ZIP entry order, timestamps,
permissions, JSON encoding, and compression settings are deterministic. Both the report and ZIP
are new immutable artifacts. If checksum validation fails, the operation is retained as `failed`,
the report is published, and no ZIP is available.

## Inspect and download

```text
GET /api/v1/studies/{study_id}/submission-packages
GET /api/v1/submission-packages/{package_id}
GET /api/v1/submission-packages/{package_id}/download
```

Download is allowed only for a successful package. Repeating creation with the same
`Idempotency-Key` and exact request returns the original record; using the key for different
inputs returns `409`.
