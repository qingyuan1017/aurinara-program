# Shared platform control plane

Aurinara remains independently deployable and keeps its artifact, specification,
validation, execution, and packaging data in its own database. The shared
`aurinara-platform` service owns OIDC identity mappings, canonical study identity,
memberships, authorization decisions, and the opaque object catalog.

## Runtime integration

- `PLATFORM_AUTHORIZATION_MODE=disabled` uses existing local memberships.
- `enforced` treats the platform decision as authoritative and fails closed with `503`
  when neither the platform nor an unexpired positive cache entry is available.
- Positive decisions are cached for at most 60 seconds. Membership and user events
  invalidate matching cache entries immediately.
- Canonical study events update only `code`, `name`, `sponsor`, and platform projection fields.
  They never change Aurinara's own study/workbench lifecycle state.
- Artifact and source-file rows with `platform_object_id` download through a short-lived
  gateway URL in enforced mode. Disabled mode requires an application-owned object key.
  Rows carry exactly one locator, and neither mode falls back to the other provider.

Confirmed human identities receive only the Platform `platform.study.create`
capability. Aurinara publishes its `aurinara.<module>.<action>` permission catalog and
does not define roles. When a person creates a canonical study, Platform assigns its
built-in cross-product Study Administrator role at that study scope. The assignment
does not expose any other study, and direct Aurinara study creation remains disabled
in enforced mode.

The API service uses an OIDC client-credentials identity with the
`platform.authorization.decide` permission plus `aurinara.artifacts.read`,
`aurinara.artifacts.write`, and `aurinara.permission.sync`. Browser clients never
receive these credentials or object-store keys.

## Deployment baseline

This pre-compatibility baseline does not migrate earlier Aurinara memberships, object
references, or database contents. Create a new database from the single baseline migration
and choose `disabled` or `enforced` explicitly for each deployment. Connected deployments
must provision Platform study projections, memberships, service credentials, and object
access before enabling traffic.

For local Compose development, start that supervised consumer with
`docker compose up -d platform-projection-worker`. The Studies queries refresh every
30 seconds while the page is active, so a newly authorized projection appears without a
full browser reload.

There is no dual-read transition. Import or generate data through the storage provider
selected for the deployment mode.
