# Reconciliation module

Status: implemented immutable, asynchronous reconciliation runs over exact entity revisions
and artifact IDs/checksums. Successful runs publish a `reconciliation_report_json` artifact.

## Use it

Build the request from exact current inputs, not mutable aliases:

```json
{
  "study_id": "<study-uuid>",
  "reconciliation_type": "exact_input_comparison",
  "reconciliation_version": "1.0.0",
  "inputs": [
    {"entity_type":"document","entity_id":"<document-uuid>","revision":2},
    {"artifact_id":"<artifact-uuid>","checksum":"<sha256>"}
  ],
  "expected_input_fingerprint": "<sha256-of-canonical-resolved-input>",
  "options": {}
}
```

POST the body to `/reconciliation-runs` with `Idempotency-Key`. The service verifies study
ownership, exact revisions, artifact availability, and checksums before queueing. Poll
`GET /reconciliation-runs/{id}` and read stable issues at
`GET /reconciliation-runs/{id}/issues`. Cancellation is cooperative and only valid while
queued or running.

The current API does not expose fingerprint preview, so creating a run is intended for a
trusted client that implements the canonical input contract. Reusing an idempotency key for
different input returns `409`.
