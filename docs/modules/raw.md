# Raw module

Status: Phase 1 foundation only. You can create a Raw aggregate, select exact dependencies,
and build a deterministic `raw_dependency_manifest`. Dataset/variable authoring, previews,
and Raw validation in the target API contract are not implemented yet.

## Use the current surface

```powershell
$raw = Invoke-RestMethod -Method Post -Uri "$base/studies/$studyId/raw" -Headers $headers `
  -ContentType "application/json" -Body '{"code":"RAW-01","name":"Raw workbench"}'
Invoke-RestMethod -Uri "$base/raw/$($raw.id)/dependencies" -Headers $headers
```

To replace dependencies, get `/raw/{id}` and capture its `ETag`, then `PUT
/raw/{id}/dependencies` with `If-Match`. The body is the common exact dependency-selection
contract described in [dependency-consuming modules](dependency-consumers.md).

The current collection and member routes do not provide `PATCH`. Uploaded source files are
managed through the shared platform and are not yet bindable as Raw datasets.
