# Shared platform control plane

Aurinara remains independently deployable and keeps its artifact, specification,
validation, execution, and packaging data in its own database. The shared
`aurinara-platform` service owns OIDC identity mappings, canonical study identity,
memberships, authorization decisions, and the opaque object catalog.

## Runtime integration

- `PLATFORM_AUTHORIZATION_MODE=disabled` uses existing local memberships.
- `shadow` calls the platform, logs decision mismatches, and preserves local behavior.
- In shadow mode, a projected canonical study with no legacy local membership becomes
  visible only after an explicit positive `artifact.study.read` decision. Legacy studies
  continue to use their local memberships until cutover.
- `enforced` treats the platform decision as authoritative and fails closed with `503`
  when neither the platform nor an unexpired positive cache entry is available.
- Positive decisions are cached for at most 60 seconds. Membership and user events
  invalidate matching cache entries immediately.
- Canonical study events update only `code`, `name`, `sponsor`, and platform projection fields.
  They never change Aurinara's own study/workbench lifecycle state.
- Artifact and source-file rows with `platform_object_id` download through a short-lived
  gateway URL. Shadow mode can dual-read legacy bytes; enforced mode cannot fall back.

The API service uses an OIDC client-credentials identity with the
`platform.authorization.decide` permission plus the applicable
`aurinara.object.download`, `aurinara.object.upload`, and
`aurinara.object.reference` permissions. Browser clients never receive these
credentials or object-store keys.

## Migration

Run the reviewed membership exporter from the repository root:

```powershell
python scripts/export_platform_memberships.py `
  --mapping .\migration\reviewed-aurinara-map.json `
  --output .\migration\aurinara-platform-snapshot.json
```

The mapping must explicitly identify every local study and OIDC subject. Missing or
ambiguous mappings stop the export. Import the result into `aurinara-platform`, run in
shadow mode until mismatches are resolved, run `alembic upgrade head` through the
`20261010_0015` object-reference reconciliation, and then enable the event consumer
for the product's SQS subscription.

For local Compose development, start that supervised consumer with
`docker compose up -d platform-projection-worker`. The Studies queries refresh every
30 seconds while the page is active, so a newly authorized projection appears without a
full browser reload.

Do not remove legacy object keys during dual-read. Populate `platform_object_id` only
after checksum, metadata, reference, backup, and retention reconciliation succeeds.
