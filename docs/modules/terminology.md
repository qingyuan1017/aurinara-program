# Terminology module

> **AI transition:** published terminology snapshots remain exact immutable provider content and
> are never model-generated. AI may propose sponsor-extension terms against an extensible selected
> codelist, with cited rationale and unresolved items; only human acceptance creates an extension
> revision. Current direct extension mutation routes are transitional.

Status: immutable terminology-release browsing plus revisioned, study-scoped sponsor
extensions. Published CDISC releases are imported on demand from one exact Library package
href and retained as checksum-addressed object-store snapshots.

## Browse a pinned release

```powershell
$releases = Invoke-RestMethod -Uri "$base/terminology-releases?module=sdtm" -Headers $headers
$releaseId = $releases[0].id
Invoke-RestMethod -Uri "$base/terminology-releases/$releaseId/codelists" -Headers $headers
Invoke-RestMethod -Uri "$base/terminology-releases/$releaseId/compatibilities" -Headers $headers
```

Release, asset, codelist, and term routes are read-only. Clinical modules store bindings to
the exact release and optional extension revision; they do not copy controlled terms.

## Maintain a sponsor extension

Only an extensible codelist may be extended:

```powershell
$body = @{
  code = "SPONSOR_SEX"
  name = "Sponsor sex extension"
  base_release_id = $releaseId
  codelist_code = "C66731"
} | ConvertTo-Json
$extension = Invoke-RestMethod -Method Post `
  -Uri "$base/studies/$studyId/terminology-extensions" -Headers $headers `
  -ContentType "application/json" -Body $body
```

Add a term with `POST /terminology-extensions/{id}/terms`. Get the extension first, copy its
`ETag`, and use `If-Match` on extension or term mutation routes. Every accepted change
creates an immutable extension revision and marks exact consumers of the superseded
revision as requiring refresh. Extensions cannot shadow published identities or submission
values. The currently implemented API does not yet propose codes; the target sponsor-extension
proposal workflow described above will add reviewable proposals without changing published terms.
