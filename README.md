# Aurinara

A standalone Clinical Artifact Platform for manually authoring, validating, generating,
executing, integrating, and packaging clinical study artifacts.

The Phase 1 platform foundation and Phase 2 Documents vertical slice are implemented. The
runnable system provides:

- FastAPI application composition;
- typed settings and structured request logging;
- liveness and readiness endpoints;
- a typed, conflict-checked module registry;
- read-only module discovery through `/api/v1/modules`;
- externally issued JWT verification and study membership boundaries;
- PostgreSQL-backed studies, immutable source files, artifacts, jobs, outbox events,
  validation/reconciliation snapshots, and integration records;
- checksum-addressed S3/MinIO storage with authorized streaming downloads;
- callback SSRF validation and deterministic event signing;
- exact Standards, Terminology, Reference, and Templates registries with module-owned
  dependency selections and refresh/staleness propagation;
- Raw, SDTM, ADaM, and TLF aggregate shells plus a complete Documents module composed
  through registered module routers and typed capabilities;
- sponsor terminology extension history, atomic Reference import/export, Review,
  traceability, validation rules and rule packs, and immutable reconciliation runs;
- idempotent asynchronous dependency-manifest builds, checksum validation, retained
  stale artifacts, reconciliation JSON reports, and complete build-worker handlers;
- signed outbound event scheduling, bounded retries, dead-letter evidence, secret
  rotation, and idempotent manual redelivery;
- Alembic migrations verified through upgrade/downgrade/upgrade from an empty database;
- Docker Compose for PostgreSQL, MinIO, API, migration, workers, a bounded integration
  receiver, and isolated runner process boundaries; and
- unit, contract, and service-backed integration tests for those boundaries.

Phase 2 adds immutable type-specific content revisions for all listed document types,
Protocol source-PDF/USDM/evidence workflows, read-only Protocol context for SAP, atomic
JSON/XLSX imports, common validation issues, dependency-aware staleness, and deterministic
DOCX/PDF/XLSX/JSON/CSV artifact generation. Templates remain presentation-only and each
formatted build requires an exact compatible Template selection. Module descriptors
advertise only capabilities backed by registered handlers; deployment-added modules can
contribute their own reviewed router and handlers without shared-service module-name
dispatch.

See the [current module usage guides](docs/modules/README.md) for executable workflows,
[local development](docs/local-development.md) for the intended environment, and
[architecture](docs/architecture.md) for the complete target design.

## Quick start

```powershell
uv sync --extra dev
uv run pytest

docker compose up -d --build api

$tokenResponse = Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:18081/token" `
  -ContentType "application/json" `
  -Body '{"subject":"local-developer","scope":"*","lifetime_seconds":3600}'

$headers = @{ Authorization = "Bearer $($tokenResponse.access_token)" }
Invoke-RestMethod `
  -Uri "http://127.0.0.1:18000/api/v1/standards?provider=CDISC" `
  -Headers $headers
```

The Compose development issuer uses an ephemeral signing key, binds only to host loopback,
and issues tokens for at most one hour. Restarting it invalidates existing tokens. See
[local development](docs/local-development.md#7-authentication-in-development) for host-run
configuration and port overrides.

Run the service-backed integration suite after starting PostgreSQL:

```powershell
docker compose up -d postgres minio minio-init
uv run alembic upgrade head
uv run python -m app.catalog_seed
$env:AURINARA_INTEGRATION = "1"
uv run pytest tests/integration
```
