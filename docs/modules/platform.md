# Shared platform usage

The shared platform supplies authentication, study isolation, module discovery, source
files, immutable artifacts, queued jobs, and typed trace links.

## Authenticate and create a study

Use the development issuer described in [local development](../local-development.md#7-authentication-in-development),
then create a study:

```powershell
$study = Invoke-RestMethod -Method Post -Uri "$base/studies" -Headers $headers `
  -ContentType "application/json" -Body '{"code":"STUDY-001","name":"Example study"}'
$studyId = $study.id
```

The creating subject becomes a study member. Every study-scoped operation verifies this
membership. `GET /studies` returns only visible studies. To edit a study, first capture the
`ETag` from `GET /studies/{id}`, then send it as `If-Match` on `PATCH`.

## Discover enabled modules

```powershell
Invoke-RestMethod -Uri "$base/modules" -Headers $headers
Invoke-RestMethod -Uri "$base/modules/documents" -Headers $headers
Invoke-RestMethod -Uri "$base/modules/documents/event-types" -Headers $headers
```

Descriptors are the runtime source of truth for owned entity types, artifact types,
capabilities, event types, and authorization scopes.

## Upload a source file

`POST /studies/{study_id}/source-files` accepts multipart form data. The service streams the
file, verifies its size and media type, calculates SHA-256, and creates both a source-file
record and immutable artifact. Never address MinIO keys directly.

```powershell
curl.exe -X POST "$base/studies/$studyId/source-files" `
  -H "Authorization: Bearer $($tokenResponse.access_token)" `
  -F "file=@C:\data\protocol.pdf;type=application/pdf"
```

List and download through `/studies/{study_id}/source-files`, `/source-files/{id}`, and
`/source-files/{id}/download`. Corrected bytes are uploaded as a new source file.

## Work with artifacts and builds

Artifacts are immutable and downloadable only through authorized API routes:

```powershell
Invoke-RestMethod -Uri "$base/studies/$studyId/artifacts" -Headers $headers
Invoke-WebRequest -Uri "$base/artifacts/$artifactId/download" -Headers $headers `
  -OutFile ".\downloaded-artifact.bin"
```

Asynchronous builds return `202 Accepted`. Poll `GET /artifact-builds/{id}` until `status`
is `succeeded`, `failed`, or `cancelled`. Build creation requires `Idempotency-Key` and the
exact 64-character SHA-256 fingerprint of the server-resolved input. The current API does
not expose a fingerprint-preview endpoint, so generic build submission is intended for a
trusted client that implements the canonical input contract. A mismatch returns
`409 stale_input_fingerprint` rather than building from changed inputs.

## Create trace links

Use `/studies/{study_id}/trace-links` to create relationships only between registered,
resolvable entity types. The traceability service verifies both endpoints and study
ownership. Never create polymorphic links by writing module tables directly.

## Common request rules

- Send `Authorization: Bearer <JWT>` on protected routes.
- Send the current `ETag` as `If-Match` for direct mutable edits.
- Send a unique `Idempotency-Key` for imports, builds, validation/reconciliation operations,
  redelivery, and other retryable commands.
- Treat `202` responses as operation resources to poll, not completed output.
- Parse errors as RFC 9457 `application/problem+json`; use the stable `code` field for logic.
- Follow `next_cursor` with `?after=...` on cursor-paginated collections.
