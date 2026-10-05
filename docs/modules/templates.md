# Templates module

Status: implemented as a read-only catalog of immutable presentation-template versions.
Templates control layout, styles, section order, and blank structures only.

## Use it

```powershell
$templates = Invoke-RestMethod -Uri "$base/templates?module=documents" -Headers $headers
$versions = Invoke-RestMethod -Uri "$base/templates/$($templates[0].id)/versions" -Headers $headers
$templateVersion = Invoke-RestMethod -Uri "$base/template-versions/$($versions[0].id)" -Headers $headers
```

Choose an exact version whose `applicable_modules`, `artifact_types`, content schema
versions, and renderer versions match the intended build. Add one dependency-selection
entry per artifact type, for example:

```json
{
  "purpose": "presentation",
  "artifact_type": "document_pdf",
  "template_version_id": "<template-version-uuid>"
}
```

The seeded `REPORT_LAYOUT` version `2.0.0` supports current Documents formatting. Templates
must not contain clinical narrative or decisions. There are no runtime template mutation
routes; changes are reviewed repository assets and seed-data changes.
