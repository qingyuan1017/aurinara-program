# Review module

Status: implemented human review questions, workflow fields, and append-only comments.
This is collaborative review evidence, not an electronic signature or formal audit trail.

## Create a review item

The target must be an entity type advertised by a module with entity-resolution support.
Documents are currently the richest target surface:

```powershell
$body = @{
  target_module = "documents"
  target_entity_type = "document"
  target_entity_id = $documentId
  field_path = "sections[0].paragraphs[0]"
  question = "Please confirm this wording."
  assignee = "clinical-reviewer"
  priority = "normal"
} | ConvertTo-Json
$item = Invoke-RestMethod -Method Post -Uri "$base/studies/$studyId/review-items" `
  -Headers $headers -ContentType "application/json" -Body $body
```

Use `PATCH /review-items/{id}` with the current `ETag` to change assignment, priority,
status, disposition, or resolution. Add comments with
`POST /review-items/{id}/comments`; comments cannot be edited or deleted. List comments in
creation order with `GET /review-items/{id}/comments`.
