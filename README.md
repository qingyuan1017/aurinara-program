# Aurinara

A standalone Clinical Artifact Platform for manually authoring, validating, generating,
executing, integrating, and packaging clinical study artifacts.

The Phase 1 platform foundation, Phase 2 Documents vertical slice, and Phase 3 Raw-to-SDTM
vertical slice are implemented. The
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
- a complete Raw dataset/variable workbench, SDTM/ADaM/TLF aggregate shells, and a complete
  Documents module composed
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

Phase 3 work currently includes Raw immutable file bindings, non-destructive physical metadata
initialization, bounded preview, validation, immutable source/schema reconciliation,
JSON/XLSX artifacts, immutable Raw context export,
internal typed Dataflow/Analysis IR, exact SDTM Raw input selection, atomic SDTM Specification and
Derivation Plan revisions, alignment/staleness enforcement, lineage, same-IR bounded plan preview,
validation, deterministic Python/R/SAS program artifacts, and immutable exact-provenance execution
runs. The SDTM plan and Python/R compilers support explicit casts, joins, unions, long reshaping,
controlled-terminology mappings, grouped aggregation, deterministic sequencing, and partitioned
window operations in addition to the foundational operators. Generated Python and R execute over
exact supported tabular inputs in disposable constrained Docker
containers and publish validated immutable CSV and deterministic read-back-verified XPT v5
outputs; unconfigured SAS execution returns its typed expected result. Persisted typed aCRF
annotation/link/coverage workflows, immutable annotated PDFs, version-neutral Define metadata,
and versioned cSDRG authoring are also implemented. Exact XPT/Define and aCRF/Define comparisons
run as immutable capability-dispatched reconciliations with report artifacts. cSDRG factual
initialization consumes that exact reconciliation evidence, preserves manually authored
narratives, validates required sections, and renders template-pinned immutable DOCX/PDF artifacts.
SDTM Specification exchange supports atomic, idempotent JSON/XLSX import and non-persisting
JSON/XLSX export. Execution stages exact CSV, flat JSON, or first-sheet XLSX inputs and supports
empty XPT outputs with preserved declared metadata. The final Phase 3 conformance slice is also
implemented: the same version-neutral model renders deterministic Define-XML
2.0 and 2.1, validates offline against checksum-pinned local XSD suites, and publishes immutable
XML artifacts only after current Define validation and exact XPT/aCRF reconciliation. Assembly of
the complete cross-module submission ZIP remains owned by the later Packaging phase.

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
