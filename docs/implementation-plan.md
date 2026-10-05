# Implementation Plan

## 1. Delivery strategy

Build Release 1 as a sequence of usable vertical slices. Each phase ends with running migrations, documented APIs, automated tests, and artifacts that can be inspected outside the platform. Shared services are introduced when a real module needs them and then hardened for later modules.

The release is accepted only when a complete study can register and validate raw data, author the required Documents (including Protocol and SAP), then move through SDTM, ADaM, TLF, and immutable submission packaging without manual database or object-store intervention.

## 2. Engineering guardrails

- Preserve module ownership: cross-module calls use service interfaces and context DTOs.
- Treat Pydantic schemas, database migrations, OpenAPI, object manifests, and standards assets as versioned contracts.
- Use deterministic canonical JSON and SHA-256 dependency fingerprints from the first artifact builder onward.
- Keep long work out of API processes; use leased PostgreSQL jobs.
- Publish bytes only after successful build and checksum verification.
- Build PDF and DOCX from one shared `Document` representation and XLSX from typed, versioned workbook contracts.
- Bind validation, compilation, execution, and packaging to exact immutable inputs.
- Record warnings; block only on errors or specifically documented material assumptions.
- Keep runner images minimal, pinned, non-root, network-disabled, and replaceable through an executor adapter.

## 3. Phase 1: Project foundation

### 3.1 Repository and runtime

- Create the repository layout described in [architecture.md](architecture.md).
- Configure Python 3.13, `pyproject.toml`, dependency locking, linting, formatting, type checking, pytest, and pre-commit hooks.
- Add FastAPI application startup, versioned routing, Pydantic settings, structured logging, request IDs, and liveness/readiness endpoints.
- Add API, job-worker, integration-dispatcher, Python runner, and R runner images with reproducible builds.
- Add Docker Compose for PostgreSQL 16, MinIO, API, workers, an integration test receiver, and runners.

### 3.2 Persistence and identity

- Configure SQLAlchemy 2 sessions and explicit transaction boundaries.
- Establish Alembic migrations and naming conventions.
- Implement `studies`, membership boundary, external JWT validation, and study-scoped service helpers.
- Implement source-file streaming, checksums, metadata, and S3/MinIO storage abstraction.
- Add base UUID/time/version mixins without creating a shared business-domain superclass.

### 3.3 Shared platform services

- Implement the `kernel` module descriptor, typed capability protocols, startup registry, conflict validation, router composition, and read-only module discovery API. Register every core module through the same path.
- Implement jobs with leases, attempts, cancellation, retry policy, and `FOR UPDATE SKIP LOCKED` claiming.
- Implement outbox events and idempotent consumers.
- Implement study-scoped integrations, external identifier bindings, registered public-event schemas/projectors, payload validation and size limits, event subscriptions, secret rotation/fingerprints, signed delivery attempts, retry/dead-letter/redelivery behavior, callback SSRF controls, and event schema versioning.
- Keep inbound connectors on existing typed APIs/imports and require service identities, study membership, module scopes, ETags, and idempotency keys; do not create a generic arbitrary JSON write path.
- Implement artifacts, canonical dependency fingerprints, checksum-addressed keys, and staleness propagation.
- Implement immutable validation runs and common issues.
- Implement the Standards registry over pinned repository assets, including product/version identity, asset provenance and checksums, lifecycle, module purpose, and compatibility links.
- Implement immutable Terminology releases and revisioned, manually maintained study sponsor extensions bound to exact base releases and codelists.
- Implement typed study Reference identities and immutable revisions with atomic import/export, optional exact code bindings, retirement, refresh-required events, and dependency invalidation.
- Implement the Templates registry with immutable assets, artifact-type applicability, content-schema and renderer compatibility, and an enforced presentation-only boundary.
- Implement the shared `DependencySelection` contract and provider resolvers, with module-owned persistence and consistent `GET/PUT .../dependencies` endpoints for Raw, Documents, SDTM, ADaM, TLF, and any registered dependency-consuming module.
- Implement Review items and append-only comments linked through typed entity resolvers.
- Implement the declarative validation rule registry and study-scoped rule packs without executable user code.
- Implement immutable Reconciliation runs, leased execution, cancellation, common issues, and JSON/PDF reports.
- Implement trace-link endpoint registry, link validation, and graph queries.
- Implement RFC 9457 errors, cursor pagination, idempotency keys, and optimistic concurrency.
- Publish OpenAPI and generate a typed client fixture in CI.

### 3.4 Phase exit criteria

- A caller with a valid test JWT can create a study and upload/download a source file.
- A worker can claim, complete, retry, and recover a leased job.
- An artifact can be built, downloaded, marked stale by an upstream change, and retained.
- Pinned standards, terminology, and template assets and historical Reference or extension revisions can be queried by exact version without runtime downloads.
- Every clinical aggregate can atomically bind exact compatible dependencies; `latest` aliases, incompatible sets, cross-study revisions, and unavailable versions are rejected.
- Publishing a new immutable registry version leaves existing selections current, while superseding a selected Reference or extension revision requires explicit refresh and stales dependent evidence without rewriting clinical content.
- A caller can maintain study reference data and review items, select an exact rule pack, and run an idempotent reconciliation against exact inputs.
- Invalid cross-study references are rejected at the service and database boundaries.
- Duplicate or incomplete module descriptors fail startup; a synthetic module can register a router, resolver, validator, artifact type, event type, and package contributor without changing shared-service dispatch code.
- A committed outbox event can be delivered to the local integration receiver with a verifiable signature, retried without duplicating the event, and redelivered from immutable attempt history; unsafe callback targets are rejected.
- PostgreSQL and MinIO integration tests run through Testcontainers or the Compose test profile.

## 4. Phase 2: Documents

Implementation status: complete in the repository as of 2026-10-05, with unit, contract,
renderer-equivalence, migration, and PostgreSQL-backed Protocol/SAP/quality-workbook
workflow coverage.

### 4.1 Shared document and workbook system

- Implement the renderer-neutral `Document` model.
- Implement style-controlled DOCX and PDF renderers.
- Implement typed workbook models and style-controlled XLSX rendering with `openpyxl`.
- Implement Documents dependency selections for applicable content/schema standards, terminology scopes, exact Reference revisions, and one Template version per generated artifact type.
- Resolve all dependency records through typed service interfaces and record the complete selection, checksums, and compatibility decision in manifests.
- Enforce that Templates supply only section order, blank structures, placeholders, and styles; clinical narrative and decisions come only from the Documents aggregate.
- Link human Review items to document entities and fields without embedding review workflow in document aggregates.
- Add normalized-content equivalence tests and golden visual fixtures for PDF, DOCX, and XLSX outputs.

### 4.2 Protocol document type

- Implement the Protocol document type, source PDF association, and lifecycle within the Documents aggregate.
- Add versioned USDM JSON storage, import/export, pinned schema validation, and relationship checks.
- Add evidence regions, multi-entity links, evidence questions, resolution state, coordinate validation, and coverage rules.
- Add annotated evidence PDF and evidence manifest builders.
- Add protocol summary and validation report builders.

### 4.3 Statistical Analysis Plan document type

- Implement the Statistical Analysis Plan document type and all structured content groups within the Documents aggregate.
- Expose immutable protocol context DTOs and manual link selection.
- Implement estimand completeness, reference, assumption, required-section, and citation checks.
- Build structured JSON, DOCX/PDF, citation reports, and validation reports.

### 4.4 Operational and quality document types

- Implement typed content contracts and PDF builders for Protocol Amendment Summary of Change, Protocol Deviation Document, Aggregate Study Risk Profile, Data Management Plan, Centralized Monitoring Platform Set-up Documentation, Aggregate Study Brief, and Study Data Summary.
- Implement typed workbook contracts, atomic XLSX/JSON imports, validation, and XLSX builders for the PD Dataset, three Standard Quality Dashboard workbooks, Signals Report, and Actions Report.
- Validate required sections, sheets, columns, stable row identifiers, controlled values, dates, owners, statuses, duplicate keys, and cross-document references without inferring clinical or quality decisions.
- Record exact source document IDs and revisions, dependency-selection revision and fingerprint, imported source-file IDs and checksums, validation runs, and warnings in artifact manifests.

### 4.5 Phase exit criteria

- End-to-end scenario 1 passes: protocol PDF, USDM, evidence, validation, and all protocol artifacts.
- End-to-end scenario 2 passes: linked Statistical Analysis Plan plus every operational and quality document type can be manually authored or atomically imported, validated, and generated in its required PDF or XLSX format.
- DOCX and PDF normalized content matches for the same document revision.
- A Protocol change makes dependent Statistical Analysis Plan and other linked Documents artifacts stale without changing their manually maintained content.

## 5. Phase 3: Raw and SDTM

### 5.1 Raw module

- Implement the Raw workbench, dataset records, variable metadata, and aggregate-scoped natural-key constraints.
- Bind each dataset to an exact immutable, study-owned source-file artifact and preserve prior bindings across replacements.
- Support manually authored metadata plus non-destructive initialization of missing factual physical metadata from supported files.
- Implement bounded row preview without persisting or logging raw rows.
- Validate file availability and checksums, supported formats, physical-schema agreement, metadata completeness, and trace-link integrity.
- Implement separate Raw and SDTM dependency selections. Bind exact applicable Standards, Terminology releases and extension revisions, Reference revisions, Templates, and validation rule-pack versions to validation and artifact inputs.
- Use immutable Reconciliation runs for source-file/schema, XPT/Define, and aCRF/Define comparisons.
- Build JSON metadata, XLSX data dictionary, and validation-report artifacts with full dependency fingerprints.
- Expose an immutable Raw context interface to SDTM; do not permit SDTM to query Raw repositories directly.

### 5.2 Shared Transformation framework

- Implement the one-word internal `transformation` package with typed Dataflow IR and Analysis IR DTOs, operator/procedure registries, canonicalization, lineage propagation, and compiler interfaces. Do not expose or persist a universal public Transformation Plan.
- Implement Dataflow IR operators for reads, selections, filters, joins, unions, casts, projections, typed derivations, reshaping, controlled-term mappings, grouping, aggregation, window operations, sequencing, sorting, assertions, and writes.
- Implement Analysis IR procedures for explicitly declared statistical methods, options, grouping, estimators, and normalized result schemas; reuse Dataflow IR for preparation and post-processing.
- Implement a typed expression AST and prohibit raw Python, R, SAS, SQL, or arbitrary expression strings in plan data.
- Implement module-owned adapters from validated, revision-aligned SDTM and ADaM Specification/Derivation Plan pairs and from TLF ProgramPlans; Transformation must not import clinical repositories or validate clinical conformance.
- Record input-selection, Specification, source-plan, normalized IR, operator/procedure, library, and compiler revisions or versions in fingerprints and manifests.
- Add IR contract, graph property, typed-expression, adapter isolation, canonicalization, lineage, and cross-language conformance tests.

### 5.3 SDTM Specification and Derivation Plan

- Implement an exact Raw input selection and one versioned SDTM Specification containing domains, variables, value-level metadata where applicable, shared-Terminology bindings, keys, sort order, sequencing metadata, expected outputs, and typed trace targets.
- Keep relational tables and constraints where needed internally, but expose one aggregate Specification contract so partial domain, variable, or binding edits cannot leave metadata inconsistent.
- Validate SDTM IG, Define-XML, terminology, Reference, and Template compatibility as one dependency set; never upgrade one selection to make another compatible.
- Implement one atomic SDTM-owned Derivation Plan in SDTM vocabulary for raw-to-domain reads, filters, joins, reshaping, derivations, terminology application, sequencing, assertions, and declared target writes, then lower it internally to Dataflow IR.
- Align every Derivation Plan to exact Specification and input-selection revisions. A change to either marks the plan misaligned and stales dependent evidence without rewriting it; block validation, preview, compilation, and execution until an explicit plan revision restores alignment.
- Validate acyclicity, port/schema compatibility, required target variables, terminology, sequencing, sorting, output coverage, and natural-key uniqueness.
- Add atomic XLSX/JSON Specification import/export and bounded Derivation Plan preview against exact Raw inputs using the same lowering path as compilation.
- Implement lineage traversal from Raw variables through stable plan nodes to SDTM variables.

### 5.4 Compiler and runners

- Implement deterministic Python, R, and SAS source generators from the shared normalized IR.
- Fail before publication with typed `backend_capability_missing` when a backend cannot implement a valid node.
- Implement Python and R local container adapters and the production executor interface.
- Implement manifest staging, network isolation, resource limits, cancellation, log capture, output validation, and cleanup.
- Write and read back XPT v5 datasets; validate labels, names, types, lengths, and row counts.
- Implement the SAS adapter contract and `runner_not_configured` behavior.

### 5.5 aCRF, Define, and cSDRG

- Implement aCRF annotations and multi-target links, coverage, reconciliation, and rendered PDF.
- Implement version-neutral Define metadata and non-destructive initialization.
- Bundle pinned Define-XML 2.0 and 2.1 schemas and build both renderers.
- Reconcile Define with exact XPT artifacts and aCRF references.
- Implement cSDRG factual initialization, manual narratives, validation, and DOCX/PDF rendering.
- Build specifications, programs, derivation/lineage/validation reports, logs, and the full SDTM artifact set.

### 5.6 Phase exit criteria

- A caller can register raw datasets, maintain dataset and variable metadata, validate physical-schema agreement, preview bounded rows, and build Raw artifacts.
- Rebinding a raw dataset to a corrected immutable file makes every dependent SDTM input selection and Derivation Plan alignment stale and stales each validation run, artifact, preview, and execution.
- End-to-end scenario 3 passes independently with Python and R.
- Generated SAS is deterministic and produces a valid manifest; unconfigured execution returns the typed expected result.
- XPT round trips preserve required metadata within format constraints.
- Define 2.0 and 2.1 pass their bundled XSDs and reconcile with selected datasets.
- aCRF references and Define leaf/document references reconcile.
- The complete SDTM package can be assembled and checked without database inspection.
- A canonical SDTM Specification and Derivation Plan produce equivalent normalized results in Python and R; SAS generation uses the same IR and manifest.
- Contract tests prove the SDTM and ADaM envelopes are structurally consistent, module-only fields cannot cross their discriminated contracts, stale alignment blocks operations, and no module plan accepts raw backend code.

## 6. Phase 4: ADaM

### 6.1 Workbench and exact SDTM input selection

- Implement ADaM dependency selections and validate their exact Standards and Terminology compatibility with the selected immutable SDTM context.
- Implement an optimistic-concurrency-controlled input selection containing exact SDTM workbench/revision, successful validation run, XPT artifact IDs/checksums, and upstream dependency fingerprint.
- Expose a read-only resolved SDTM context through the SDTM service interface; never query its repositories or substitute newer artifacts.
- Propagate input-selection changes to all ADaM previews, validations, programs, executions, datasets, Define/ADRG artifacts, and downstream TLF contexts.

### 6.2 ADaM Specification and traceability

- Implement one versioned ADaM Specification using the same outer envelope as SDTM and containing datasets, variables, parameters, value-level metadata, reviewer-readable methods, terminology bindings, and typed trace targets.
- Keep relational tables and constraints where needed internally, but expose one aggregate contract so partial resource edits cannot leave metadata inconsistent.
- Verify Protocol/SAP trace targets and write normalized trace links through the traceability service in the same transaction; do not create a second analysis-binding store.
- Implement atomic versioned JSON/XLSX specification import and non-persisting export; keep Derivation Plan replacement separate.
- Resolve Reference revisions for study/sponsor/role/unit metadata and Templates for specifications, ADRG, derivation, and validation reports without moving analysis content into those providers.
- Validate origin, predecessor, method, parameter, value-level, terminology, and traceability completeness independently from derivation execution.

### 6.3 ADaM Derivation Plan and execution

- Implement one atomic ADaM-owned Derivation Plan using the same outer envelope and alignment lifecycle as SDTM, aligned to exact ADaM Specification and SDTM input-selection revisions; do not create overlapping separately mutable graph-step or variable-rule resources.
- Express nodes in ADaM vocabulary with stable dataset, variable, and parameter references, then lower the validated plan internally to Dataflow IR.
- Permit reads only from the exact SDTM input selection and explicitly declared upstream ADaM outputs; validate dataset-to-dataset acyclicity and complete output coverage.
- Use one lowering pipeline for bounded previews, compilation, and execution; record exact input-selection, Specification, Derivation Plan, IR/operator/compiler versions.
- Generate and execute Python/R, generate SAS, validate declared output schemas and assertions, and reconcile XPT v5 outputs with metadata.
- Produce canonical ADaM Specification and Derivation Plan JSON, XPT datasets, XLSX specifications, derivation reports, traceability reports, logs, and validation reports.

### 6.4 Define and ADRG

- Implement ADaM Define metadata for dataset classes, roles, parameters, value-level metadata, origins, methods, terminology, and SDTM traceability.
- Implement Define 2.0/2.1 rendering, XSD validation, and reconciliation with exact ADaM XPT outputs and SDTM origins.
- Implement ADRG factual initialization from the exact ADaM Specification, input selection, Derivation Plan, programs, executions, and outputs while preserving manual narrative.
- Render ADRG DOCX/PDF from one `Document` representation and exact Template version.

### 6.5 Phase exit criteria

- End-to-end scenario 4 passes independently with Python and R from the same ADaM Specification and Derivation Plan.
- Every ADaM output variable resolves to a Derivation Plan output; every declared origin resolves to the exact selected SDTM or predecessor ADaM artifact, dataset, and variable.
- Parameters, value-level metadata, methods, terminology bindings, and trace links are complete and reconcile with datasets and Define metadata.
- Changing the SDTM input selection stales every dependent ADaM and TLF evidence without modifying maintained ADaM metadata.
- ADaM Define matches generated datasets and passes both applicable XSD suites.
- ADRG factual tables derive from the same input selection, ADaM Specification revision, Derivation Plan revision, execution, and artifact manifest as its narrative context.

## 7. Phase 5: TLF and submission packaging

### 7.1 TLF workflow

- Implement shell, ADaM bindings, assumptions, ARS, and ProgramPlan editing.
- Implement TLF dependency selections for an optional exact ARS version, explicitly used terminology, Reference revisions, and per-output Template versions.
- Enforce that Templates control presentation only and cannot create analysis steps, titles, interpretations, populations, parameters, or statistics.
- Validate leaf-row coverage, analysis steps, population/parameter/statistic references, ordering, and output intent.
- Lower the validated ARS and ProgramPlan directly to internal Analysis IR, using Dataflow IR for ADaM preparation and post-processing; do not expose a second generated plan.
- Keep shell hierarchy, titles, footnotes, pagination, styles, and output rendering outside compiler IR.
- Generate deterministic Python/R/SAS programs and record the source ProgramPlan plus normalized IR fingerprint.
- Execute Python/R against exact ADaM artifacts and produce CSV/Parquet results.
- Render table/listing RTF/PDF and figure PNG/SVG/PDF.
- Build output indexes and enforce program/run/result/output lineage.

### 7.2 Submission packaging

- Implement package requests with explicit registered-module and artifact selections.
- Define required-artifact and trusted-path policies through each module's typed package-contribution capability rather than central module-name switches.
- Apply Documents completeness rules per explicitly selected `document_types` value.
- Recalculate checksums and validate current dependency fingerprints.
- Verify that every selected artifact's frozen dependency snapshot is available, study-correct, internally compatible, and compatible with related upstream/downstream artifacts; packaging never upgrades or re-renders it.
- Implement Define/dataset, aCRF/Define, ADaM/SDTM, and TLF run reconciliation.
- Require package reconciliation inputs to reference completed immutable Reconciliation runs or create new runs against the exact package selection.
- Normalize and validate archive paths; detect duplicates on case-insensitive and Unicode-normalized forms.
- Build deterministic ZIPs, `manifest.json`, `checksums.sha256`, and package validation reports.
- Store the ZIP and report as immutable artifacts.

### 7.3 Phase exit criteria

- End-to-end scenario 5 passes for at least one table/listing and one figure using both supported internal languages across the suite.
- End-to-end scenario 6 produces a complete study ZIP whose checksums verify independently.
- End-to-end scenario 7 proves upstream edits stale every transitive dependent artifact.
- End-to-end scenario 8 proves stale, invalid, failed, incomplete, cross-study, duplicate-path, and mixed-run selections are rejected.
- End-to-end scenario 9 proves authenticated inbound API use and signed, retryable outbound event delivery.
- End-to-end scenario 10 proves a synthetic deployment-added module composes through registered capabilities without shared dispatch changes.

## 8. Test strategy

### 8.1 Test layers

| Layer                  | Focus                                                                                   |
| ---------------------- | --------------------------------------------------------------------------------------- |
| Unit                   | Domain invariants, module descriptors/capability conflicts, event envelopes/signatures, ADaM specification/traceability, dependency selection/resolution, compatibility, module-plan adapters, IR operators/procedures/lowering, fingerprints, registries, validators, path rules |
| Property               | Filenames, archive paths, module keys, callback URLs/IP resolution, event canonicalization, PDF coordinates, typed expressions, graph ports/edges/DAGs, rule parameters, reference keys, canonical JSON |
| Repository integration | PostgreSQL constraints, immutable provider revisions, module selections, integration subscriptions/delivery attempts, refresh/staleness outbox behavior, JSONB queries, transactions, and job leases |
| Storage integration    | Multipart/streaming I/O, checksum verification, immutable keys, MinIO behavior          |
| Contract               | REST status/headers/problems, module discovery, import/event schema compatibility, OpenAPI snapshot, typed client compatibility |
| Conformance            | USDM/Define schemas, XPT round trips, controlled metadata checks                        |
| Golden file            | XML, DOCX, PDF, RTF, XLSX, canonical Specification/Derivation/Program contracts, normalized IR, and generated programs |
| Execution security     | No network, non-root, resource ceilings, timeouts, cancellation, cleanup                |
| Integration security   | Service scopes, webhook signatures, secret redaction, SSRF/DNS-rebinding/redirect defenses, retry bounds |
| End to end             | The ten release scenarios on real PostgreSQL, MinIO, integration receiver, and runner containers |

Golden tests compare stable normalized representations where binary formats contain volatile metadata. A separate visual or rendered comparison catches layout regressions in PDF, DOCX, XLSX, and RTF.

### 8.2 Required automated scenarios

1. Register exact compatible Standards, Terminology, Reference revisions, and Templates; bind them explicitly to Documents; manually create a Protocol, USDM, and evidence set; review it and generate all Protocol artifacts.
2. Link Protocol to the Statistical Analysis Plan; author or atomically import all remaining Documents types; generate the required PDF and XLSX artifacts.
3. Bind separate Raw and SDTM dependencies and an exact Raw input selection; maintain one SDTM Specification and one aligned Derivation Plan; execute it in Python/R through shared Dataflow IR; reconcile outputs; and produce XPT, aCRF, Define, and cSDRG.
4. Bind an ADaM dependency and exact SDTM input selection; maintain one ADaM Specification and one aligned Derivation Plan; execute through shared Dataflow IR in Python/R; and produce reconciled XPT, Define, and ADRG.
5. Bind TLF dependencies; author the shell, bindings, ARS, and ProgramPlan; execute through shared Analysis/Dataflow IR and render outputs while proving presentation is outside compiler IR and templates supply no analysis content.
6. Assemble a complete study package and independently verify checksums.
7. Publish a new immutable provider version and verify pinned work is unchanged; then supersede a selected Reference or extension revision, verify refresh-required state and transitive staleness, explicitly accept it, and verify deterministic regeneration.
8. Confirm stale or invalid artifacts cannot enter a submission package.
9. Use an external-system service identity to perform an idempotent typed import, subscribe to registered lifecycle events, verify the signed minimal event at the test receiver, force a retry, and confirm redelivery retains the same event ID without exposing clinical payloads or secrets.
10. Enable a synthetic `labs` module through one descriptor and its own package/migrations; discover it through `/api/v1/modules`; exercise its study-scoped route, entity resolver, validation, artifact, event, trace, and package contribution; and prove duplicate registrations or undeclared capabilities fail startup.

## 9. CI and release controls

Pull-request CI runs formatting, linting, type checks, unit/property tests, migration checks, OpenAPI compatibility, and focused integration tests. Main-branch CI adds container builds, full integration/conformance tests, golden files, vulnerability/license scanning, and end-to-end workflows.

A release candidate records:

- source commit and image digests;
- database migration head;
- Python and R runner image digests;
- enabled module descriptor versions and capability catalog;
- import and event schema versions plus integration-dispatcher image digest;
- generator and validator versions;
- USDM and Define schema versions;
- controlled terminology snapshot identifiers;
- dependency-selection revisions and fingerprints for each clinical aggregate;
- selected Reference and sponsor-extension revision identifiers;
- document template versions;
- passed test-suite identifiers and golden baseline version.

Production deployment runs database migrations as a controlled step, deploys API/workers, verifies readiness, then enables new job claiming. Rollback must account for migration compatibility and never delete already generated artifacts.

## 10. Major risks and mitigations

| Risk                                                    | Mitigation                                                                           |
| ------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| Standards assets are incomplete or ambiguously licensed | Pin approved local assets, record provenance, and fail clearly when unavailable      |
| Registry versions are combined incompatibly             | Persist compatibility links and validate exact version selections before use          |
| New registry versions silently alter existing work       | Require exact module-owned selections; never resolve `latest` or auto-upgrade           |
| Reference or extension corrections overwrite evidence   | Create immutable revisions, require explicit refresh, and stale dependent evidence      |
| Templates smuggle in clinical content or decisions       | Restrict and validate template schemas to layout, blank structure, and style             |
| Shared compiler becomes a lowest-common-denominator domain model | Share consistent SDTM/ADaM envelopes and internal IR/operators/backends, while keeping module-specific Specification, Derivation Plan, ProgramPlan, and validators in owning modules |
| Language backends implement nodes differently             | Define language-neutral node semantics and normalized cross-language conformance fixtures |
| Sponsor rule packs introduce unsafe behavior             | Allow typed parameters over registered rules only; prohibit executable user code       |
| Review or reconciliation links cross study boundaries    | Resolve every endpoint through study-scoped typed interfaces before committing         |
| DOCX/PDF content drifts                                 | Use one document model and normalized equivalence tests                              |
| Workbook columns or controlled values drift             | Use versioned workbook contracts, atomic imports, and normalized XLSX golden tests    |
| Python/R compiler behavior diverges                     | Compile from one typed intermediate representation and share conformance fixtures    |
| XPT v5 limitations cause silent loss                    | Validate before write, read back, compare metadata, and report constraints           |
| Source-file schema and maintained metadata diverge      | Bind exact checksums, validate physical schemas, and stale downstream dependencies    |
| Staleness misses transitive dependencies                | Persist dependency edges and test multi-hop invalidation                             |
| Long database transactions block workers                | Claim with short leased transactions and perform work outside locks                  |
| Runner escapes or exhausts resources                    | Non-root ephemeral containers, disabled network, read-only filesystem, strict limits |
| Package contains mismatched outputs                     | Require exact IDs and reconcile lineage/checksums immediately before ZIP assembly    |
| New modules require edits throughout shared services    | Dispatch through typed capability registries and test a synthetic module in CI       |
| A module descriptor overclaims or collides              | Fail startup on duplicate ownership, missing handlers, or routes outside its prefix  |
| Outbound callbacks leak data or enable SSRF             | Emit minimal events, sign deliveries, isolate the dispatcher, and enforce destination policy |
| Event retries duplicate downstream effects              | Use immutable event IDs, at-least-once semantics, receiver deduplication, and bounded attempt history |

## 11. Release 1 definition of done

Release 1 is done when all five clinical workflows, the shared registries, review, reconciliation, internal Transformation compiler, packaging, module-extension kernel, and controlled integration boundary are available through documented `/api/v1` contracts; every enabled module registers a conflict-free typed descriptor and capabilities; every clinical aggregate owns an exact compatible dependency selection with no implicit upgrades; Reference and extension revisions refresh safely; SDTM and ADaM each expose a consistent Specification/Derivation Plan lifecycle with module-specific semantics and exact revision alignment, while TLF retains ARS/ProgramPlan; all executable plans lower through shared internal IR and backends; Python and R execute equivalent source plans in isolated environments; SAS programs and adapter manifests are generated; Define-XML 2.0/2.1 validates against pinned local schemas; all artifacts carry immutable dependency and compiler provenance with correct staleness; signed outbound events remain minimal and retryable; the ten end-to-end scenarios pass; and a complete package can be independently verified without direct database or object-store manipulation.
