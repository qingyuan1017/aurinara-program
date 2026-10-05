# SDTM module

Status: Phase 1 foundation only. You can create an SDTM aggregate, select exact dependencies,
and build a deterministic `sdtm_dependency_manifest`.

## Use the current surface

```powershell
$sdtm = Invoke-RestMethod -Method Post -Uri "$base/studies/$studyId/sdtms" -Headers $headers `
  -ContentType "application/json" -Body '{"code":"SDTM-01","name":"SDTM workbench"}'
Invoke-RestMethod -Uri "$base/sdtms/$($sdtm.id)/dependencies" -Headers $headers
```

Replace the complete exact selection with `PUT /sdtms/{id}/dependencies`, the current
aggregate `ETag`, and the contract in [dependency-consuming modules](dependency-consumers.md).

Specifications, Derivation Plans, input selection, compilation, execution, XPT, aCRF,
Define-XML, and cSDRG routes in the target API contract are not implemented yet. The current
member route is read-only and does not provide `PATCH`.
