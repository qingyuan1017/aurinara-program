# ADaM module

Status: Phase 1 foundation only. You can create an ADaM aggregate, select exact dependencies,
and build a deterministic `adam_dependency_manifest`.

## Use the current surface

```powershell
$adam = Invoke-RestMethod -Method Post -Uri "$base/studies/$studyId/adams" -Headers $headers `
  -ContentType "application/json" -Body '{"code":"ADAM-01","name":"ADaM workbench"}'
Invoke-RestMethod -Uri "$base/adams/$($adam.id)/dependencies" -Headers $headers
```

Replace the complete exact selection with `PUT /adams/{id}/dependencies`, the current
aggregate `ETag`, and the contract in [dependency-consuming modules](dependency-consumers.md).

Specifications, Derivation Plans, SDTM input selection/context, compilation, execution,
XPT, Define-XML, and ADRG routes in the target API contract are not implemented yet. The
current member route is read-only and does not provide `PATCH`.
