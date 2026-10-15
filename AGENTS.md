# Repository Conventions for Agents

## Scope and authority

This file applies to the entire repository. More specific `AGENTS.md` files may be added inside subdirectories when a module needs additional rules; a nested file may refine these conventions for its subtree but must not weaken platform-wide safety, traceability, immutability, or manual-authoring requirements.

Before changing implementation or contracts, read the relevant documents:

- `docs/architecture.md` for system boundaries and technical decisions;
- `docs/artifact-catalog.md` for artifact types, prerequisites, lineage, and package placement;
- `docs/api-contract.md` for HTTP behavior and resource contracts;
- `docs/implementation-plan.md` for delivery order and acceptance criteria;
- `docs/local-development.md` for the intended local environment and verification workflow.

If implementation and documentation disagree, do not silently choose one. Preserve existing behavior when required for safety, identify the mismatch, and update the authoritative contract as part of the same change when the requested work authorizes it.

## Product boundaries

This is a standalone Clinical Artifact Platform for manually managing raw data and authoring, validating, reviewing, reconciling, generating, executing, and packaging Documents, SDTM, ADaM, and TLF deliverables. Shared first-class modules own standards, terminology, reference data, templates, review, and reconciliation. The Documents module owns Protocol, SAP, and study operational and quality deliverables.

The following are non-negotiable Release 1 boundaries:

- Clinical content, mappings, rules, assumptions, annotations, and review decisions are authored by users.
- Do not add AI generation, proposal workflows, automated mapping, recommendations, or confidence scoring.
- Do not claim regulatory certification or parity with a commercial validator.
- Python and R execution are first-party capabilities.
- SAS programs are generated, while SAS execution uses an optional external runner adapter.
- Define-XML 2.0 and 2.1 are both supported from one version-neutral metadata model.
- There is no legacy-backend compatibility layer or legacy migration requirement.
- Fine-grained RBAC, electronic signatures, formal audit trails, document comparison, regulatory-gateway submission, and built-in SAS execution remain deferred unless the project scope is explicitly changed.

## Architecture

Use Python 3.13, FastAPI, Pydantic 2, SQLAlchemy 2, Alembic, PostgreSQL 16, and S3-compatible object storage. MinIO is the local object store.

Build a modular monolith with these primary packages:

```text
src/app/
  api/
  common/
  kernel/
  integration/
  standards/
  terminology/
  reference/
  templates/
  review/
  reconciliation/
  raw/
  documents/
  sdtm/
  adam/
  tlf/
  transformation/
  artifacts/
  execution/
  validation/
  packaging/
```

Each clinical module, including Raw, owns its routes, domain models, persistence repositories, services, validators, and artifact builders. Cross-module access must use explicit typed service interfaces or immutable context DTOs. Never import or query another clinical module's repository implementation directly.

Keep `common` limited to technical primitives such as UUIDs, clocks, database sessions, hashing, canonical JSON, pagination, problem details, and transaction helpers. Do not move clinical business rules into `common` merely to avoid a dependency decision.

`kernel` owns the typed module-extension contracts, module descriptor, capability protocols, and startup registry. `integration` owns external-system registrations, external identifier bindings, event subscriptions, delivery attempts, signing, and connector boundaries. Neither package owns clinical content. Do not implement runtime loading of arbitrary Python packages or let integrations bypass an owning module's application service.

`standards`, `terminology`, and `templates` own versioned registries over pinned repository assets. `reference` owns manually maintained study reference data. `review` owns human questions, comments, assignments, and dispositions without claiming electronic signatures. `reconciliation` owns immutable comparisons between exact revisions and artifacts. These packages expose typed interfaces and must not become generic bypasses around module ownership.

`transformation` is an internal compilation package. It owns typed dataflow and analysis intermediate representations, core operators, canonicalization, lineage propagation, and deterministic compiler interfaces shared by SDTM, ADaM, and TLF. It does not define a public or persisted universal `TransformationPlan`, and it owns no study mapping, derivation, analysis choice, target metadata, or presentation rule. SDTM owns one Specification (all domains) plus one Derivation Plan per domain; ADaM owns one Specification (all datasets) plus one Derivation Plan per dataset; TLF owns ARS plus ProgramPlan. These remain module-owned authoring contracts even where their outer envelopes are consistent. TLF rendering remains outside the framework.

Each clinical aggregate—including Raw, Documents, SDTM, ADaM, TLF, and any deployment-added module declaring dependency consumption—owns an explicit, versioned dependency selection for the exact Standards, Terminology, Reference revisions, and Templates it consumes. Provider modules validate and resolve selections but never choose a version on behalf of a clinical module. Do not use `latest`, silently inherit a new registry version, or resolve mutable current values during validation, generation, execution, reconciliation, or packaging.

- Publishing a new immutable standard, terminology release, or template does not stale existing work. Changing an aggregate's explicit selection does.
- A Reference or sponsor-terminology-extension edit creates an immutable revision. It marks consumers of the superseded logical record as requiring refresh and stales dependent evidence without automatically rebinding or rewriting clinical content.
- Clinical modules own terminology bindings and usage context, not copies of shared codelists or terms. SDTM and ADaM variable/value-level bindings must resolve into the exact Terminology release and extension revisions selected by their aggregate.
- Templates may control layout, section order, blank structures, and styling. They must not provide clinical narrative, mappings, derivations, risk decisions, signals, actions, or conclusions.
- Reference data represents study-instance facts. It may point to a pinned standard or terminology code, but it must not duplicate a controlled code system or absorb module-owned clinical content.
- Artifacts and operation manifests record the complete resolved dependency selection, compatibility decision, and provider checksums used for the operation.

Use dependency injection at application boundaries. Keep domain and service code independent of FastAPI request objects, Docker APIs, and concrete S3 clients.

### Module extension conventions

Every capability-participating first-party or deployment-added module registers one immutable `ModuleDescriptor` at application composition time. The descriptor uses a stable lowercase one-word `module_key` and declares its API prefix, module version, supported content schema versions, dependency purposes, owned entity and relationship types, artifact types, source-plan types, event types, authorization scopes, and implemented capabilities. Supported capabilities include dependency selection and staleness edges, validation, artifacts, typed entity resolution, review targets, reconciliation inputs, context export, packaging, compilation, execution, and outbound events. A module registers only capabilities it actually implements.

Shared services dispatch through typed capability registries; do not add module-name `if`/`match` chains to Artifacts, Validation, Review, Reconciliation, Traceability, Packaging, or Integration. Startup must fail on duplicate module keys, route prefixes, owned entity or relationship types, artifact types, source-plan types, event types, or missing handlers for declared capabilities. Registration never grants cross-module persistence access.

A new module owns its package, migrations, API schemas and router, services, repositories, validators, artifact builders, context DTOs, trace resolvers, events, and tests. Alembic remains the single ordered migration history. Modules are added at code/deployment time and reviewed like the core application; Release 1 does not support hot installation or execution of untrusted plugin code.

### External integration conventions

External systems use `/api/v1`, OAuth/JWT service identities, explicit study membership and module scopes, ETags, idempotency keys, and the same validation/application services as interactive clients. They never access module tables, outbox tables, object-store keys, or runner endpoints directly. Bulk inbound data must use typed versioned imports and is validated completely before commit.

Outbound integration uses transactional outbox events and study-scoped subscriptions. A module with outbound events must register a versioned public event schema and projector; never serialize an internal outbox payload generically. Events have a stable event ID, event type, schema version, time, study, module key, typed subject, subject revision, correlation ID, and a minimal data object. Validate projected bytes against the registered schema and size limit. Do not include source rows, full clinical payloads, credentials, or object-store locations; subscribers fetch authorized resources through the API. Delivery is at least once, signed, retryable, bounded, and idempotent by event ID. Validate callback destinations against SSRF policy, require TLS outside local development, do not follow unsafe redirects, and never log signing secrets or authorization headers.

## Repository layout

Follow the target structure in `docs/architecture.md`:

```text
src/app/                 API and domain application
workers/                 durable build and execution workers
runners/                 isolated Python/R runners and SAS adapter
migrations/              Alembic migrations
schemas/                 pinned standards schemas
terminology/             pinned controlled terminology releases
templates/               versioned presentation templates
tests/unit/              fast domain and validator tests
tests/integration/       PostgreSQL and object-store tests
tests/contract/          REST and OpenAPI tests
tests/conformance/       standards and file-format tests
tests/e2e/               complete study workflows
docs/                    architecture and operating contracts
```

Prefer one clear responsibility per module. Use descriptive filenames and avoid generic `utils.py` or `helpers.py` modules; place a primitive in the package that owns its meaning.

## Domain and persistence conventions

- Use UUIDs for all primary identifiers.
- Store user-facing identifiers such as `DM`, `ADSL`, and `T-14-1` as separate natural keys with aggregate-scoped uniqueness constraints.
- Store identity, ownership, lifecycle status, stable references, timestamps, and searchable fields in relational columns.
- Use JSONB for versioned, standards-heavy structures. Every JSONB payload requires a Pydantic contract and an explicit schema version.
- Use UTC-aware timestamps at every boundary.
- Put transaction boundaries in application services. A command should normally commit once.
- Write state changes and their outbox events in the same database transaction.
- Validate an entire XLSX or JSON bulk import before committing any of it.
- Enforce study ownership in services and database relationships where practical.

Do not expose SQLAlchemy models as API schemas. Translate between persistence, domain, and transport models explicitly.

Create an Alembic migration for every persistent schema change. Review autogenerated migrations for constraint names, JSONB defaults, enum behavior, indexes, foreign-key deletion rules, and reversibility. Tests must apply migrations from an empty database rather than relying on `metadata.create_all()` as a substitute.

## API conventions

All public application routes use `/api/v1`. Follow `docs/api-contract.md` for the complete route inventory.

- Use Pydantic 2 request and response models.
- Use `snake_case` JSON fields, UUIDs, and RFC 3339 UTC timestamps.
- Return RFC 9457 `application/problem+json` errors.
- Return `422` for invalid clinical or standards content.
- Return `409` for duplicate natural keys, idempotency conflicts, stale build inputs, and invalid lifecycle transitions.
- Use opaque cursor pagination for collections.
- Require `If-Match` with the current `ETag` for direct edits to mutable aggregates.
- Require idempotency keys for bulk import, build, execution, reconciliation, integration redelivery, and submission-package creation.
- Return `202 Accepted` and a status resource for long-running work.
- Never return object-store keys, credentials, internal filesystem paths, or runner secrets through the public API.

Keep route handlers thin: authenticate, parse, call one application service, and translate the result. Domain validation belongs in validators and services, not inline in route functions.

Treat OpenAPI as a versioned contract. Update contract tests and the generated typed-client fixture when a public schema changes. Avoid breaking `/api/v1` behavior without an explicit versioning decision.

## Validation conventions

All module validators emit the common issue model:

```text
id
code
severity: error | warning | info
message
suggestion
module
entity_type
entity_id
field_path
dataset
variable
artifact_id
```

Issue codes are stable machine-readable identifiers. Messages explain the observed problem, and suggestions state a concrete correction when one is available. Do not encode control flow by parsing human-readable messages.

Validation runs are immutable snapshots. Record validator name and version, canonical input fingerprint, start and completion times, issue counts, full issues, and report artifact IDs. Revalidation creates a new run.

The validation package owns a declarative rule registry with stable rule IDs, versions, applicability, parameters, default severity, and rule-pack membership. Module packages own their clinical rule implementations. Sponsor-defined rule packs are manually authored data, never executable user code.

Errors block dependent generation, execution, or packaging. Warnings remain visible in reports and package manifests. Keep schema validation, platform conformance checks, and external-validator findings distinguishable.

Reconciliation runs are immutable snapshots over exact entity revisions and artifact IDs/checksums. They use the common issue model but remain distinguishable from ordinary validation runs. Review items must resolve typed targets through owning-module interfaces, enforce study ownership, and keep comments append-only. Review workflow is not an electronic-signature or formal audit-trail capability.

## Traceability conventions

Create cross-module relationships through the traceability service and normalized `trace_links` records. The service must verify both endpoints exist, belong to the same study, and support the requested relationship before inserting an edge.

Preserve these required chains:

```text
Protocol objective
  -> Protocol endpoint
  -> SAP estimand or method
  -> ADaM dataset or variable
  -> TLF output

CRF annotation
  -> Raw variable
  -> SDTM Derivation Plan node
  -> SDTM variable
  -> ADaM Derivation Plan node and derived variable
```

Never create an unverified polymorphic link by inserting directly into `trace_links` from a clinical module repository.

## Artifact conventions

Generated files are immutable. Regeneration creates a new artifact record and never overwrites an existing object.

Every artifact must record the fields and provenance defined in `docs/artifact-catalog.md`, including SHA-256, byte size, canonical input fingerprint, generator name/version, validation run, reconciliation run or execution run when applicable, creator, and creation time.

- Use checksum-addressed object keys.
- Treat user filenames as display metadata only.
- Calculate dependency fingerprints from canonical inputs, upstream artifact IDs/checksums, relevant settings, and standards/terminology/schema/template/rule-pack/generator versions.
- Retain stale artifacts for audit and comparison.
- Reject stale or invalid artifacts from new submission packages.
- Require packages to select exact artifact IDs; never silently substitute a newer artifact.
- Upload or publish bytes only after successful generation and checksum verification.
- On failure, retain structured failure metadata but do not publish partial files as available artifacts.

Narrative PDF and DOCX artifacts for the Documents module, cSDRG, ADRG, validation reports, review reports, and reconciliation reports must use the shared renderer-neutral `Document` representation. Uploaded original PDFs and annotated evidence overlays retain their source/evidence-specific builders. Clinical content comes only from persisted, manually maintained records. Templates control presentation and section order. Documents workbooks use typed, versioned row contracts and `openpyxl`; they must not infer clinical judgments or silently alter user-maintained values.

## Jobs and workers

Use PostgreSQL as the durable queue. Claim jobs in a short transaction with `FOR UPDATE SKIP LOCKED`, record a lease owner and expiry, commit, and perform expensive work outside the lock.

Workers must be safe to retry. Use stable operation IDs and idempotent terminal transitions. Recover expired leases, bound retry attempts, record typed failures, and implement cooperative cancellation.

Do not hold a database transaction open while rendering documents, accessing object storage, running programs, or assembling ZIP files.

## Compilation and execution

Keep the module semantics distinct while making the SDTM and ADaM authoring lifecycle consistent:

- SDTM owns one versioned Specification for all domains (variables, value-level metadata where applicable, terminology bindings, keys, sort order, sequencing metadata, and trace targets) plus one Derivation Plan per domain, each expressed as a typed raw-to-domain DAG that produces only its own domain. A plan reads other produced SDTM domains through an `sdtm_read` node resolved against the single Specification (no new external input pin); the Raw input selection stays the only external pin.
- ADaM owns one versioned Specification for all datasets (variables, parameters, value-level metadata, terminology bindings, origins, methods, and trace targets) plus one Derivation Plan per dataset, each expressed as a typed SDTM/predecessor-to-analysis-dataset DAG that produces only its own dataset. A plan reads predecessor ADaM datasets through an `adam_read` node resolved against the single Specification.
- TLF owns shells, ADaM bindings, assumptions, ARS, and ProgramPlan. ProgramPlan analysis steps are a structured analysis model, not an exposed generic DAG.

SDTM and ADaM Specifications and Derivation Plans use consistent outer envelopes, endpoint shapes, optimistic concurrency, atomic import/export, validation/preview behavior, and provenance. Each per-domain/per-dataset Derivation Plan is keyed by `(aggregate, domain/dataset, revision)`, pins the exact `specification_revision` and `input_selection_revision`, and additionally pins server-resolved `upstream_plan_pins` (the exact sibling plan revisions it reads via `sdtm_read`/`adam_read`); a read may only pin a sibling that is already authored and aligned. A Specification or input-selection change marks every affected per-domain/per-dataset plan misaligned, and a sibling-plan change transitively misaligns the plans that read it (reason `upstream_plan_changed`); staleness never rewrites a plan or silently rebinds identifiers. Block preview, validation, compilation, and execution until an explicit validated plan revision restores alignment. Every plan output resolves to its Specification; each per-domain/per-dataset plan declares exactly one write for its own target, and the build/packaging orchestration enforces that the union of per-domain/per-dataset plans covers every derived domain/dataset in the Specification.

The owning module validates and lowers its aligned authoring model into internal typed Dataflow IR and, for TLF statistical procedures, Analysis IR. Shared operators cover reads, selections, filters, joins, unions, projections, casts, reshaping, typed-expression derivations, controlled-terminology mappings, grouping, aggregation, window operations, sequencing, sorting, assertions, and declared writes. Raw Python, R, SAS, SQL, or arbitrary expression strings are invalid in ordinary nodes and expressions. A Derivation Plan or TLF ProgramPlan may instead declare a typed, named custom function with a fixed signature and explicit per-language bodies. Custom bodies are immutable plan inputs, are never evaluated by API or preview processes, and run only through the existing isolated runner boundary. A missing language body generates a visible TODO program artifact that is marked non-executable for that language without blocking languages whose bodies are present.

Compile Python, R, and SAS deterministically from the normalized IR. TLF layout and rendering never enter either IR. Generated programs and manifests must be reproducible for the same input selection, Specification when applicable, canonical module-owned plan, exact input artifacts, IR/operator/compiler versions, and generator version.

Cross-language conformance compares structural and discrete results exactly and floating-point statistical results only with node-declared tolerances and pinned algorithm/library versions. Never substitute a different statistical method to make a backend pass; return `backend_capability_missing` before publishing the program when equivalent declared semantics are unavailable.

Python and R execute in disposable containers. Every run must:

1. bind a successful validation run and exact immutable inputs;
2. stage inputs in a new temporary workspace;
3. run as a non-root user;
4. disable external network access;
5. enforce CPU, memory, process, runtime, and output-size limits;
6. capture stdout, stderr, exit code, timing, and resource metrics;
7. validate declared output names, types, and checksums;
8. upload valid outputs as immutable artifacts;
9. destroy the temporary workspace.

Do not run user programs in the API or worker process. Do not weaken isolation for local convenience. SAS execution must return the typed result `runner_not_configured` when no external runner is configured; that result does not invalidate a successfully generated SAS program.

## Standards and file generation

Pin USDM, Define-XML, controlled terminology, and template assets in the repository with provenance and version metadata. Tests must not download standards, terminology, or template assets at runtime.

- Validate Define-XML 2.0 and 2.1 against their locally bundled XSDs.
- Reconcile Define metadata with the exact selected XPT datasets.
- Reconcile SDTM Define references with the selected aCRF.
- Reconcile ADaM origins and lineage with the selected SDTM datasets.
- Write XPT v5, read it back, and verify values and supported metadata.
- Build DOCX with `python-docx`, PDF with `reportlab`, XLSX with `openpyxl`, and XML/XSD operations with `lxml` unless an architecture change is documented.
- Normalize unstable binary metadata before comparing golden files.

Initialization endpoints may fill missing factual structures from saved metadata. They must preserve manual edits and must not generate narrative clinical content.

## Submission packaging

Before creating a ZIP, verify study ownership, required selections, artifact availability, current fingerprints, validation status, execution completion, recalculated checksums, cross-module reconciliation, and TLF run cohesion.

Reject absolute paths, traversal segments, reserved names, unsafe Unicode forms, duplicate normalized paths, and case-insensitive filename collisions. Construct package paths from trusted artifact-type rules, not user input.

Create deterministic `manifest.json` and `checksums.sha256` entries. Store the final ZIP and package validation report as new immutable artifacts.

## Security and privacy

- Validate external JWT signature, issuer, audience, expiry, and required claims.
- Enforce study membership at service boundaries.
- Stream uploads and apply size, media-type, checksum, and path controls.
- Keep credentials in environment-backed secret configuration; never commit them.
- Do not log JWTs, secrets, full clinical payloads, review-comment bodies, licensed terminology payloads, or raw dataset rows.
- Use synthetic data in fixtures; never commit real patient information.
- Keep execution images minimal, pinned, and non-root.
- Treat filenames, archive entries, uploaded content, generated programs, and external runner responses as untrusted input.

Operational logs and immutable snapshots are useful evidence, but do not describe them as a formal regulatory audit trail or electronic-signature system.

## Testing conventions

Use pytest for all suites, Hypothesis where input spaces matter, and Testcontainers or the Compose test profile for PostgreSQL and MinIO integration.

Add tests in proportion to the change:

- unit tests for domain invariants, module descriptor/capability conflicts, event envelopes and signatures, ADaM specification and traceability, validators, fingerprints, rule applicability, registry compatibility, module-plan adapters, IR operators/lowering, reconciliation behavior, and compiler behavior;
- property tests for filenames, archive paths, module keys, callback URLs/IP resolution, event canonicalization, coordinates, typed expressions, graph ports/edges/DAGs, filters, mappings, reference keys, rule parameters, and canonicalization;
- repository integration tests for transactions, registry immutability, reference constraints, review comments, reconciliation inputs, integration subscriptions and delivery attempts, leases, JSONB, and outbox behavior;
- storage integration tests for checksums and immutable object handling;
- contract tests for routes, headers, problem responses, and OpenAPI;
- conformance tests for USDM/Define schemas, XPT round trips, and normalized Python/R results from the same canonical module-owned source plan;
- golden tests for normalized XML, DOCX, PDF, RTF, XLSX, and generated programs;
- isolation tests for network denial, non-root execution, timeouts, cancellation, cleanup, and resource ceilings;
- integration-security tests for service scopes, signing/secret redaction, SSRF and redirect defenses, delivery retry bounds, and event-ID deduplication;
- end-to-end tests for the ten scenarios in `docs/implementation-plan.md`.

Test behavior and meaningful invariants. Avoid tests that merely repeat implementation structure. Keep fixtures small, deterministic, synthetic, and rich enough to cover missing values, non-ASCII text, long labels, value-level metadata, annotations, and cross-module traceability.

Until `pyproject.toml`, Compose files, and package entry points exist, do not claim that repository commands have run. Once created, use the commands declared by those files and keep `docs/local-development.md` synchronized.

## Code style

- Add type annotations to public functions, service interfaces, repository interfaces, and non-obvious local structures.
- Prefer small typed value objects and explicit schemas over unstructured dictionaries.
- Use enums or literals for stable finite states, artifact types, issue severities, node types, and languages.
- Keep pure domain logic separate from I/O.
- Pass clocks and identifier generators into code that needs deterministic tests.
- Use structured logging with correlation identifiers.
- Write docstrings for public interfaces and behavior whose constraints are not clear from types. Avoid comments that merely restate code.
- Raise typed domain/application errors and translate them to HTTP problems at the API boundary.
- Avoid hidden global state, import-time network/database access, and environment reads outside the settings layer.

## Change workflow

Before editing:

1. Identify the owning module and applicable contracts.
2. Inspect existing code and tests in that module.
3. Check whether the change affects persistence, API compatibility, artifact provenance, traceability, staleness, or execution safety.

While editing:

1. Keep the change inside the owning module or add an explicit interface.
2. Add or update migrations and tests with the implementation.
3. Update relevant documentation when behavior, settings, schemas, templates, or operational steps change.
4. Preserve unrelated user changes and avoid broad mechanical rewrites.

Before handing off:

1. Run the narrowest relevant checks, then the appropriate broader suite.
2. Verify migrations from a clean database when persistence changed.
3. Verify OpenAPI/contract compatibility when routes or schemas changed.
4. Inspect generated files or normalized golden output when builders changed.
5. State what changed, why, what was tested, and any remaining limitation.

## Definition of done

A change is complete when it respects module boundaries, preserves study isolation and manual authoring, records required provenance, handles staleness and retries correctly, registers accurate module capabilities, preserves import/event compatibility, includes meaningful verification, and keeps implementation, OpenAPI, module descriptors, migrations, standards assets, artifact catalog, and operating documentation consistent.

Release 1 as a whole is complete only when all ten end-to-end scenarios in `docs/implementation-plan.md` pass without manual database or object-store intervention.
