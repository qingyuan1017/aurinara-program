# Validation module

Status: implemented declarative rules and study rule packs, immutable validation runs,
Documents validation, and artifact-integrity validation.

## Rules and rule packs

```powershell
$rules = Invoke-RestMethod -Uri "$base/validation-rules" -Headers $headers
$packBody = @{
  code = "STUDY-DOCS"
  name = "Study document checks"
  selections = @(
    @{ validation_rule_id = $rules[0].id; parameters = @{}; severity = "warning" }
  )
} | ConvertTo-Json -Depth 6
$pack = Invoke-RestMethod -Method Post `
  -Uri "$base/studies/$studyId/validation-rule-packs" -Headers $headers `
  -ContentType "application/json" -Body $packBody
```

Study packs select exact registered rule versions and typed parameters. They cannot contain
executable code or disable mandatory rules. Replace a study pack with
`PUT /validation-rule-packs/{id}` and its current `If-Match` value.

## Run validation

For Documents, use `POST /documents/{document_id}/validate`; it snapshots exact document,
content, USDM, evidence, relationship, and dependency revisions and completes synchronously
inside the request. For an immutable artifact, use `POST /artifacts/{artifact_id}/validate`;
it returns a queued run for the worker. Neither current endpoint requires an idempotency
key. Poll queued runs at `GET /validation-runs/{id}` and inspect `issues`, counts, and report
artifact IDs. Cancellation is available while a run is queued or running.

Issue consumers should branch on stable `code` and `severity`, not parse the human message.
Errors block dependent generation; warnings remain visible in evidence and manifests.
