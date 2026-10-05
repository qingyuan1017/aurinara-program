# Reference module

Status: implemented revisioned study facts for organizations, countries, sites, vendors,
languages, units, roles, and milestones.

## Create and revise a record

```powershell
$body = @{
  reference_type = "site"
  natural_key = "SITE-001"
  display_name = "Example Site"
  value = @{
    schema_version = "1.0.0"
    fields = @(
      @{ name = "country"; value = "US" },
      @{ name = "active"; value = $true }
    )
  }
} | ConvertTo-Json -Depth 6
$reference = Invoke-RestMethod -Method Post -Uri "$base/studies/$studyId/references" `
  -Headers $headers -ContentType "application/json" -Body $body
```

Retrieve `/references/{id}` with `Invoke-WebRequest` when you need its `ETag`; send that
value as `If-Match` on `PATCH`. A patch creates a new immutable revision. `DELETE` retires
the logical record while retaining revision history.

`POST /studies/{study_id}/references/import` accepts one complete versioned collection,
requires `Idempotency-Key`, validates all rows, and commits none if any row is invalid.
`GET /studies/{study_id}/references/export` returns the same portable contract. When a
revision changes, dependent aggregates are marked for explicit refresh; their content is
never rebound automatically.
