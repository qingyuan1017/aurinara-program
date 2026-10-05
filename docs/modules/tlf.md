# TLF module

Status: Phase 1 foundation only. You can create a TLF aggregate, select exact dependencies,
and build a deterministic `tlf_dependency_manifest`.

## Use the current surface

```powershell
$tlf = Invoke-RestMethod -Method Post -Uri "$base/studies/$studyId/tlfs" -Headers $headers `
  -ContentType "application/json" -Body '{"code":"TLF-01","name":"TLF workbench"}'
Invoke-RestMethod -Uri "$base/tlfs/$($tlf.id)/dependencies" -Headers $headers
```

Replace the complete exact selection with `PUT /tlfs/{id}/dependencies`, the current
aggregate `ETag`, and the contract in [dependency-consuming modules](dependency-consumers.md).

Shells, bindings, assumptions, ARS, ProgramPlan, compilation, execution, rendering, and
formatted TLF artifact routes in the target API contract are not implemented yet. The
current member route is read-only and does not provide `PATCH`.
