# Integration module

Status: implemented study-scoped external-system registration, external identifier
bindings, signed outbound subscriptions, delivery evidence, secret rotation, and manual
redelivery.

## Register an external system

```powershell
$body = @{
  integration_code = "EDC-01"
  display_name = "Example EDC"
  direction = "bidirectional"
  external_subject = "service-account-subject"
  allowed_modules = @("documents", "reference")
} | ConvertTo-Json
$created = Invoke-RestMethod -Method Post -Uri "$base/studies/$studyId/integrations" `
  -Headers $headers -ContentType "application/json" -Body $body
$integrationId = $created.integration.id
```

Store `created.secret.signing_secret` immediately; plaintext is returned only at creation
or `POST /integrations/{id}/secrets/rotate`. Subsequent resources expose only a fingerprint.

## Subscribe and bind identifiers

Create a subscription at `/integrations/{id}/subscriptions` with a validated callback URL,
registered event types, allowlisted non-secret headers, and a 1–30 second timeout. Production
callbacks require safe HTTPS destinations; private, loopback, link-local, credential-bearing,
and unsafe redirect targets are rejected. A local loopback exception exists only when the
development setting enables it.

Use `/integrations/{id}/external-identifiers` to bind an external tuple to a typed platform
entity. The target is resolved through its owning module and must belong to the same study.

List deliveries at `/integrations/{id}/deliveries`. Manual redelivery uses
`POST /integration-deliveries/{id}/redeliver` with `Idempotency-Key`; receivers must
deduplicate at-least-once deliveries by event ID. Never put credentials or clinical payloads
in subscription headers or events.
