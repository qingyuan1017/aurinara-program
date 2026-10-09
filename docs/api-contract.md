# API Contract

## 1. Contract scope

All public application routes are rooted at `/api/v1`. Operational health routes remain at `/health`, and the interactive API documentation remains at `/docs`. JSON request and response bodies use UTF-8, `snake_case` field names, UUID identifiers, and RFC 3339 UTC timestamps. OpenAPI generated from the FastAPI application is the normative transport contract; this document defines the conventions, resources, and operations it must expose.

The API edits persisted objects directly. There is no proposal, recommendation, confidence-score, or AI-assistance resource.

## 2. Authentication and study scope

Human clients and external-system service identities send an externally issued JWT as a bearer token. The API validates issuer, audience, signature, expiry, subject, and required claims. Module services enforce study membership and registered module/action scopes before reading or changing a study-owned resource. Integration configuration does not create identity-provider credentials or bypass these checks.

Nested create and collection routes include the study ID:

```text
/api/v1/studies/{study_id}/raw
/api/v1/studies/{study_id}/documents
/api/v1/studies/{study_id}/references
/api/v1/studies/{study_id}/review-items
/api/v1/studies/{study_id}/terminology-extensions
/api/v1/studies/{study_id}/validation-rule-packs
/api/v1/studies/{study_id}/integrations
/api/v1/studies/{study_id}/sdtms
/api/v1/studies/{study_id}/adams
/api/v1/studies/{study_id}/tlfs
```

Routes addressed by a globally unique resource ID still resolve the owning study and perform the same membership check. A resource from another study cannot be attached by supplying its UUID.

Collection routes are nested under their owning study or aggregate. Member routes use the shortest unambiguous globally addressable resource path, such as `/api/v1/artifacts/{artifact_id}`. Path parameter names identify the resource type (`{sdtm_id}`, `{dataset_id}`, and so on) rather than using a generic name such as `{solution_id}`.

## 3. HTTP conventions

### 3.1 Methods and statuses

| Operation                    | Success status                                        |
| ---------------------------- | ----------------------------------------------------- |
| Create synchronous resource  | `201 Created` with resource and `Location`            |
| Read resource or collection  | `200 OK`                                              |
| Replace editable document    | `200 OK`                                              |
| Patch resource               | `200 OK`                                              |
| Delete editable child        | `204 No Content`                                      |
| Start asynchronous operation | `202 Accepted` with operation resource and `Location` |

Other common statuses:

- `400` for malformed syntax or unsupported query combinations;
- `401` for missing or invalid authentication;
- `403` for an authenticated caller without study access;
- `404` when a visible resource does not exist;
- `409` for duplicate natural keys, idempotency conflicts, stale inputs, or invalid lifecycle transitions;
- `412` when a supplied `If-Match` value does not match the current `ETag`;
- `413` for upload or request limits;
- `415` for unsupported media types;
- `422` for structurally valid requests containing invalid clinical or standards content;
- `428` when a required `If-Match` header is missing;
- `429` for enforced rate or concurrency limits;
- `503` for unavailable required infrastructure.

### 3.2 Problem details

Errors use `application/problem+json` and RFC 9457 fields:

```json
{
  "type": "https://clinical-artifact-platform.example/problems/clinical-validation",
  "title": "Clinical content is invalid",
  "status": 422,
  "detail": "The SDTM Derivation Plan contains blocking validation issues.",
  "instance": "/api/v1/sdtms/7da4.../compile",
  "code": "clinical_content_invalid",
  "request_id": "01J...",
  "issues": [
    {
      "code": "SDTM_DERIVATION_CYCLE",
      "severity": "error",
      "message": "The derivation graph contains a cycle.",
      "suggestion": "Remove one of the reported graph edges.",
      "module": "sdtm",
      "entity_type": "derivation_plan",
      "entity_id": "f07a...",
      "field_path": "graph.edges",
      "dataset": "DM",
      "variable": null,
      "artifact_id": null
    }
  ]
}
```

Validation issues use the same fields whether returned inline or saved in a validation run.

### 3.3 Optimistic concurrency

Mutable aggregate responses include an opaque `ETag`. `PATCH`, `PUT`, and `DELETE` require `If-Match`. A `POST` action that directly changes an existing editable aggregate, such as `initialize`, also requires `If-Match`; collection creates and actions that create immutable operation resources do not. A missing required header returns `428 Precondition Required`, while a stale value returns `412 Precondition Failed`. This protects direct editing from lost updates. Build, execution, and package services also verify dependency fingerprints at job start and return a terminal stale-input result if content changed after the request was accepted.

### 3.4 Idempotency

Bulk import, build, execution, reconciliation-run, integration redelivery, and submission-package creation require `Idempotency-Key`. The key is scoped to caller, route, and study and retained for a documented period. Repeating the same key and canonical request returns the original result or operation. Reusing the key with a different request returns `409 idempotency_key_reused`.

### 3.5 Cursor pagination

Collections use opaque cursor pagination:

```text
GET /api/v1/studies/{study_id}/artifacts?limit=50&after=<cursor>
```

```json
{
  "items": [],
  "page": {
    "next_cursor": null,
    "has_more": false
  }
}
```

`limit` has a safe default and maximum. Sort order is stable and documented per resource, normally `(created_at DESC, id DESC)`. Filter values are encoded separately from the cursor and a cursor cannot be reused with different filters.

### 3.6 Bulk imports

XLSX and JSON imports are atomic and require `Idempotency-Key` in addition to `If-Match` when replacing an existing aggregate. The response either confirms the committed revision or returns all detected issues; partial row commits are prohibited. Upload endpoints accept multipart form data, while metadata and import options remain typed JSON parts.

### 3.7 Action endpoints and operation resources

Long-running action endpoints use the same result contract in every module:

| Action suffix                                        | Success status and resource                                                                                  |
| ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| `/validate`                                          | `202 Accepted` with a validation run and `Location: /api/v1/validation-runs/{validation_run_id}`             |
| `/reconcile` or reconciliation-run collection `POST` | `202 Accepted` with a reconciliation run and `Location: /api/v1/reconciliation-runs/{reconciliation_run_id}` |
| `/compile` or `/artifacts`                           | `202 Accepted` with an artifact build and `Location: /api/v1/artifact-builds/{build_id}`                     |
| `/execute`                                           | `202 Accepted` with an execution run and `Location: /api/v1/execution-runs/{run_id}`                         |
| `/render` when it creates artifacts                  | `202 Accepted` with an artifact build and `Location: /api/v1/artifact-builds/{build_id}`                     |
| Submission-package collection `POST`                 | `202 Accepted` with a submission package and `Location: /api/v1/submission-packages/{package_id}`            |

Synchronous previews and non-persisting renders return `200 OK` and do not create operation resources. All artifact-producing requests include an expected input fingerprint. Artifact builds, execution runs, reconciliation runs, and submission-package creation require `Idempotency-Key`.

## 4. Common resource contracts

### 4.1 Validation issue

```json
{
  "id": "uuid",
  "code": "string",
  "severity": "error",
  "message": "string",
  "suggestion": "string or null",
  "module": "registered module key",
  "entity_type": "string",
  "entity_id": "uuid or null",
  "field_path": "string or null",
  "dataset": "string or null",
  "variable": "string or null",
  "artifact_id": "uuid or null"
}
```

`module` is a stable lowercase one-word key matching `^[a-z][a-z0-9]{1,31}$` and resolved through the startup module registry. Core keys include `standards`, `terminology`, `reference`, `templates`, `review`, `reconciliation`, `validation`, `integration`, `raw`, `documents`, `sdtm`, `adam`, `tlf`, and `packaging`. Public schemas accept only keys registered by the running deployment; adding a module does not require changing a hard-coded transport enum.

### 4.2 Validation run

```json
{
  "id": "uuid",
  "study_id": "uuid",
  "module": "sdtm",
  "owner_type": "sdtm_solution",
  "owner_id": "uuid",
  "status": "queued|running|completed|failed|cancelled",
  "validator_name": "sdtm_solution",
  "validator_version": "1.0.0",
  "input_fingerprint": "sha256 hex",
  "started_at": "date-time or null",
  "completed_at": "date-time or null",
  "issue_counts": { "error": 0, "warning": 2, "info": 1 },
  "issues": [],
  "report_artifact_ids": ["uuid"]
}
```

### 4.3 Artifact

```json
{
  "id": "uuid",
  "study_id": "uuid",
  "module": "sdtm",
  "artifact_type": "sdtm_dataset_xpt",
  "owner_type": "sdtm_domain",
  "owner_id": "uuid",
  "filename": "dm.xpt",
  "media_type": "application/octet-stream",
  "sha256": "sha256 hex",
  "size": 12345,
  "input_fingerprint": "sha256 hex",
  "dependency_selection_revision": 7,
  "dependency_fingerprint": "sha256 hex",
  "input_selection_revision": 5,
  "source_specification_revision": 9,
  "source_specification_fingerprint": "sha256 hex or null",
  "source_plan_type": "registered source-plan type or null",
  "source_plan_revision": 12,
  "compiler_fingerprint": "sha256 hex or null",
  "generator_name": "sdtm-xpt-builder",
  "generator_version": "1.0.0",
  "status": "available|stale|failed",
  "validation_run_id": "uuid or null",
  "reconciliation_run_id": "uuid or null",
  "execution_run_id": "uuid or null",
  "created_by": "subject identifier",
  "created_at": "date-time"
}
```

`object_key` is internal and is never returned by the public API. Downloads use a short-lived authorized response or redirect from the download endpoint. `dependency_selection_revision` is null only for artifacts, such as an original upload, that have no clinical owner selection. The dependency fingerprint covers the complete resolved Standards, Terminology, Reference, and Templates snapshot; it is also included in `input_fingerprint` with content and other upstream inputs. Source-plan/compiler fields are null for artifacts not produced through compilation; otherwise the manifest also contains the exact normalized IR, operator/procedure versions, and compiler version.

### 4.4 Asynchronous operation

Builds, executions, reconciliations, and packages expose a status resource rather than holding an HTTP request open. Each includes `id`, `status`, timestamps, progress phase, cancellation state, input fingerprint, result artifact IDs, and a typed failure object when terminal.

### 4.5 Reconciliation run

A reconciliation run is an immutable comparison snapshot. It records `id`, `study_id`, reconciliation type and version, exact input entity revisions and artifact IDs/checksums, canonical input fingerprint, lifecycle timestamps, issue counts, full issues, report artifact IDs, and a typed terminal failure when applicable. Re-running a comparison creates a new run.

### 4.6 Dependency selection

Raw, Documents, SDTM, ADaM, TLF, and every registered module with the dependency-consumer capability expose the same versioned dependency-selection shape:

```json
{
  "revision": 7,
  "state": "current|dependency_refresh_required",
  "standards": [
    { "purpose": "module-defined-purpose", "standard_version_id": "uuid" }
  ],
  "terminology": [
    {
      "scope": "module-defined-scope",
      "terminology_release_id": "uuid",
      "terminology_extension_revision_ids": ["uuid"]
    }
  ],
  "references": [
    {
      "purpose": "module-defined-purpose",
      "reference_id": "uuid",
      "reference_revision_id": "uuid"
    }
  ],
  "templates": [
    {
      "purpose": "module-defined-purpose",
      "artifact_type": "registered_artifact_type or null",
      "template_version_id": "uuid"
    }
  ]
}
```

`purpose` and `scope` values are finite enums defined by the consuming module and are unique within their applicable scope. Template purposes cover artifact rendering and, where supported, import, export, or preview layout; `artifact_type` is required only for a purpose that renders a persisted artifact. An aggregate-creation request may include its initial dependency selection. Otherwise the aggregate starts as a draft with an empty selection, and operations that need missing dependencies return `422 dependency_selection_incomplete`; the server never fills defaults.

`PUT .../dependencies` requires `If-Match` and replaces the complete selection atomically. Every ID must be exact; the API rejects aliases such as `latest`. The service resolves all provider records, verifies study ownership for Reference and extension revisions, validates applicability and the complete compatibility set, and returns all actionable incompatibilities as `422 dependency_selection_invalid`. A withdrawn or quarantined required version returns `409 dependency_unavailable`.

Publishing a new Standards, Terminology, or Templates version never changes an existing selection. A superseding Reference or terminology-extension revision moves affected selections to `dependency_refresh_required` and stales dependent validation runs and artifacts, but leaves the bound revision and clinical content unchanged. Content inspection and editing remain available, while new validation, build, execution, reconciliation, and package operations return `409 dependency_refresh_required`. The user clears the state through `PUT .../dependencies` by selecting the superseding revision or, when provider lifecycle policy still permits the historical revision, explicitly reaffirming it with a reason. Every operation manifest records the resolved IDs, versions, checksums, lifecycle states, and compatibility decision used by that operation.

When a clinical aggregate binds an upstream module context, the downstream dependency response also includes that context's aggregate revision, dependency-selection revision, and dependency fingerprint. The downstream service checks compatibility but neither copies nor changes the upstream selection. Shared report builds without a clinical owner selection must provide an exact report `template_version_id` in the build request.

### 4.7 Specifications and compilable plans

There is no public universal Transformation Plan. SDTM and ADaM each expose the same two-resource authoring pattern: a versioned Specification describing target metadata and a versioned Derivation Plan describing how those targets are produced. TLF exposes ARS and ProgramPlan because its analysis and presentation contract is materially different. The SDTM and ADaM resources use consistent envelopes, concurrency rules, revision alignment, import/export behavior, validation, preview, compilation, and provenance, while their module-specific payloads and validation rules remain distinct.

The common Specification envelope contains `schema_version`, `module`, `revision`, `datasets`, `variables`, `value_level_metadata`, `parameters`, `terminology_bindings`, `methods`, and `trace_targets`. SDTM serializes domains as its discriminated `datasets` variant. A module may require, prohibit, or specialize a collection; for example, ADaM owns parameters and reviewer-readable analysis methods, while SDTM prohibits parameters and owns domain structure, keys, sequencing metadata, and submission usage. The common Derivation Plan envelope contains `schema_version`, `module`, `revision`, `specification_revision`, `input_selection_revision`, `alignment_state`, `alignment_reasons`, `nodes`, `edges`, `outputs`, and `assertions`. Module discriminators select closed Pydantic contracts rather than permitting arbitrary dictionaries.

Every Derivation Plan output must resolve to a target in the exact Specification revision, and every target declared as derived must have exactly one valid producing output. `alignment_state` is `current` or `alignment_required`; `alignment_reasons` contains `specification_changed`, `input_changed`, or both. Updating a Specification or input selection never rewrites the Derivation Plan: responses compute the alignment state from its pinned revisions and stale dependent previews, validations, programs, executions, and artifacts. Validation, preview, compile, and execute return `409 derivation_plan_alignment_required` until a `PUT derivation-plan` explicitly targets the current `specification_revision` and `input_selection_revision` and passes module validation.

All Specification and Derivation Plan writes require `If-Match` and replace the complete authoring model atomically. Expressions use a typed AST. The API rejects raw Python, R, SAS, SQL, arbitrary expression strings, unresolved inputs/outputs, and invalid module semantics. SDTM/ADaM additionally reject cycles, dangling ports, incompatible schemas, and incomplete output coverage. Module validation returns its own stable issue codes rather than generic compiler messages.

Preview and compilation use the same internal lowering path to Dataflow IR and, for TLF statistical procedures, Analysis IR. IR is not editable or independently addressable through the public API. Compiler manifests freeze the Specification revision/fingerprint when applicable, source-plan type/revision/fingerprint, input-selection revision, exact input artifacts, normalized IR, operator/procedure versions, and compiler version. A backend that cannot implement the declared semantics returns `409 backend_capability_missing` before publishing a program.

## 5. Shared component routes

### 5.1 Standards and Templates catalogs

```text
GET /api/v1/standards
GET /api/v1/standards/{standard_id}
GET /api/v1/standards/{standard_id}/versions
GET /api/v1/standard-versions/{standard_version_id}
GET /api/v1/standard-versions/{standard_version_id}/assets
GET /api/v1/standard-assets/{asset_id}/content
GET /api/v1/standard-versions/{standard_version_id}/compatibilities

GET /api/v1/templates
GET /api/v1/templates/{template_id}
GET /api/v1/templates/{template_id}/versions
GET /api/v1/template-versions/{template_version_id}
```

These catalogs are read-only at runtime. Standard products identify the provider, family, product type, and clinical/nonclinical/cross-domain scope. Exact version responses include publication date, CDISC Library identity when supplied, manifest schema version, lifecycle, checksum, applicability, and purpose. Asset responses expose role, media type, checksum, canonical CDISC Library href, title, and resource type, but never expose a server filesystem path. The content route reads the immutable repository copy only after rechecking its path and checksum; it never calls CDISC Library. Compatibility responses expose directional exact-version relationships such as `implements`, `based_on`, `requires`, and `supersedes`; a required relationship must be present in an aggregate's dependency selection. List routes support typed filters for product or template family, module, purpose or artifact type, lifecycle, and compatibility with an exact version ID; filters aid selection but never select a version for a clinical aggregate. Releases create registry records from reviewed, repository-pinned assets and record checksums, provenance, lifecycle status, schema or renderer compatibility, and applicable module or artifact types. Template responses describe layout capabilities and blank structures only and cannot contain clinical defaults. No request downloads or silently upgrades an external asset.

### 5.2 Terminology

```text
GET /api/v1/terminology-releases
GET /api/v1/terminology-releases/{terminology_release_id}
GET /api/v1/terminology-releases/{terminology_release_id}/compatibilities
GET /api/v1/terminology-releases/{terminology_release_id}/assets
GET /api/v1/terminology-assets/{asset_id}/content
GET /api/v1/terminology-releases/{terminology_release_id}/codelists
GET /api/v1/terminology-codelists/{codelist_id}
GET /api/v1/terminology-codelists/{codelist_id}/terms

POST  /api/v1/studies/{study_id}/terminology-extensions
GET   /api/v1/studies/{study_id}/terminology-extensions
GET   /api/v1/terminology-extensions/{extension_id}
PATCH /api/v1/terminology-extensions/{extension_id}
GET   /api/v1/terminology-extensions/{extension_id}/revisions
GET   /api/v1/terminology-extension-revisions/{extension_revision_id}
GET   /api/v1/terminology-extension-revisions/{extension_revision_id}/terms
GET   /api/v1/terminology-extensions/{extension_id}/terms
POST  /api/v1/terminology-extensions/{extension_id}/terms
PATCH /api/v1/terminology-extension-terms/{extension_term_id}
DELETE /api/v1/terminology-extension-terms/{extension_term_id}
```

Published terminology releases and their terms are immutable. A release identifies its provider, CDISC terminology product, publication date, exact package version, CDISC Library identity when supplied, manifest schema version, checksum, lifecycle, and module applicability. Its asset routes expose the checked immutable Library package response and the same safe, checksum-verified content behavior as Standard assets. Codelists preserve NCI concept ID, submission value, name, definition, preferred term, synonyms, and extensibility. Terms preserve NCI concept ID, submission value, decode, definition, preferred term, synonyms, and active or retired state. Compatibility records bind an exact terminology release and scope to an exact standard version and dependency purpose.

Sponsor extensions are manually maintained, study-scoped overlays that reference an exact base release and codelist. They may only target a codelist published as extensible. Every accepted extension or term mutation uses `If-Match` and creates an immutable extension revision; historical revision routes remain resolvable. Extensions cannot alter or shadow a published concept identity or submission value, and the API never proposes or automatically codes a value.

### 5.3 Reference data

```text
POST  /api/v1/studies/{study_id}/references
GET   /api/v1/studies/{study_id}/references
POST  /api/v1/studies/{study_id}/references/import
GET   /api/v1/studies/{study_id}/references/export
GET   /api/v1/references/{reference_id}
PATCH /api/v1/references/{reference_id}
DELETE /api/v1/references/{reference_id}
GET   /api/v1/references/{reference_id}/revisions
GET   /api/v1/reference-revisions/{reference_revision_id}
```

Reference records use discriminated, versioned contracts for organizations, countries, sites, vendors, languages, units, roles, and milestones. Natural keys are unique within study and reference type. `PATCH` requires `If-Match` and creates an immutable revision; imports validate and create all revisions atomically. `DELETE` retires the logical identity, preventing new bindings while retaining every historical revision. A Reference value may bind a code from an exact Standards or Terminology version, but it cannot redefine that code. Superseding a revision triggers dependency refresh and staleness without rewriting module-owned content.

### 5.4 Review

```text
POST  /api/v1/studies/{study_id}/review-items
GET   /api/v1/studies/{study_id}/review-items
GET   /api/v1/review-items/{review_item_id}
PATCH /api/v1/review-items/{review_item_id}
GET   /api/v1/review-items/{review_item_id}/comments
POST  /api/v1/review-items/{review_item_id}/comments
```

A review item links to a verified typed entity and optional field path, captures question, assignment, priority, status, disposition, and resolution text, and uses optimistic concurrency for workflow changes. Comments are append-only. This is collaborative review evidence, not an electronic signature or formal regulatory audit trail.

### 5.5 Validation rule registry

```text
GET  /api/v1/validation-rules
GET  /api/v1/validation-rules/{validation_rule_id}
GET  /api/v1/validation-rule-packs
GET  /api/v1/validation-rule-packs/{rule_pack_id}
POST /api/v1/studies/{study_id}/validation-rule-packs
GET  /api/v1/studies/{study_id}/validation-rule-packs
PUT  /api/v1/validation-rule-packs/{rule_pack_id}
```

Platform rule definitions and released rule packs are immutable. Study-scoped sponsor packs select exact registered rule versions and typed parameters. They cannot contain executable code, redefine issue codes, or disable mandatory platform or standards rules.

### 5.6 Reconciliation

```text
POST /api/v1/reconciliation-runs
GET  /api/v1/reconciliation-runs/{reconciliation_run_id}
GET  /api/v1/reconciliation-runs/{reconciliation_run_id}/issues
POST /api/v1/reconciliation-runs/{reconciliation_run_id}/cancel
```

The request supplies `study_id`, a registered reconciliation type, exact entity revisions and artifact IDs, an expected input fingerprint, and typed options. The service resolves every input through its owning module, verifies study ownership and availability, and records checksums before queueing the immutable run.

### 5.7 Module discovery

```text
GET /api/v1/modules
GET /api/v1/modules/{module_key}
GET /api/v1/modules/{module_key}/event-types
```

Module discovery is read-only and returns safe `ModuleDescriptor` fields: stable key and version, API prefix, supported content schema versions, dependency purposes, capabilities, entity and relationship types, artifact types, source-plan types, event types, and authorization scopes. It does not expose Python class paths, database tables, object-store configuration, credentials, or disabled implementation details. Unknown or disabled keys return `404 module_not_registered`.

### 5.8 External integrations

```text
POST   /api/v1/studies/{study_id}/integrations
GET    /api/v1/studies/{study_id}/integrations
GET    /api/v1/integrations/{integration_id}
PATCH  /api/v1/integrations/{integration_id}
DELETE /api/v1/integrations/{integration_id}
POST   /api/v1/integrations/{integration_id}/secrets/rotate

GET    /api/v1/integrations/{integration_id}/external-identifiers
POST   /api/v1/integrations/{integration_id}/external-identifiers
GET    /api/v1/external-identifiers/{external_identifier_id}
DELETE /api/v1/external-identifiers/{external_identifier_id}

GET    /api/v1/integrations/{integration_id}/subscriptions
POST   /api/v1/integrations/{integration_id}/subscriptions
GET    /api/v1/integration-subscriptions/{subscription_id}
PATCH  /api/v1/integration-subscriptions/{subscription_id}
DELETE /api/v1/integration-subscriptions/{subscription_id}

GET  /api/v1/integrations/{integration_id}/deliveries
GET  /api/v1/integration-deliveries/{delivery_id}
POST /api/v1/integration-deliveries/{delivery_id}/redeliver
```

An integration is study-scoped and records a stable `integration_code`, display name, direction (`inbound`, `outbound`, or `bidirectional`), optional external identity subject, allowed registered module keys, lifecycle status, and timestamps. `PATCH`, identifier changes, and subscription changes require `If-Match`. `DELETE` retires an integration, external identifier binding, or subscription rather than erasing history. Retiring an integration prevents new deliveries and identifier bindings while preserving historical attempts. Secret creation or rotation returns plaintext once; subsequent responses expose only secret version and fingerprint.

An external identifier binding supplies `external_entity_type`, `external_id`, and one typed platform target containing `module`, `entity_type`, and `entity_id`. The service resolves the target through the owning module capability and verifies the same study before committing. The external tuple is unique within the integration. Bindings never replace platform UUIDs or module natural keys.

A subscription selects registered event types, a validated HTTPS callback URL, optional non-secret headers from an allowlist, delivery timeout within policy, and active status. Subscription responses never return secret material. Private, loopback, link-local, metadata-service, embedded-credential, disallowed-port, and unsafe-redirect destinations are rejected. Local development may explicitly allow a loopback test receiver through settings; production cannot use that exception.

Outbound events use a versioned envelope containing `id`, `type`, `schema_version`, `occurred_at`, `study_id`, `module_key`, typed subject identity/revision, `correlation_id`, and minimal event-specific `data`. Each delivery carries event ID, timestamp, content digest, and HMAC signature headers. Delivery is at least once; receivers deduplicate by event ID. Attempt history returns status, timings, response code, and a redacted bounded response excerpt. Redelivery creates a new attempt for the same immutable event and current authorized subscription; it never edits the event.

`POST .../redeliver` requires `Idempotency-Key`, returns `202 Accepted`, and creates or returns an immutable redelivery operation. It rejects an inactive integration, missing event, unauthorized study, or event type no longer permitted by the subscription. Automatic and manual deliveries share the same retry ceilings and destination policy.

Inbound systems use existing module routes, imports, uploads, ETags, and idempotency keys. There is no generic arbitrary-payload write endpoint. Connector-specific translation must terminate in one typed module application command and receives the same validation, provenance, and transaction behavior as any other client.

## 6. Study and source-file routes

```text
POST /api/v1/studies
GET  /api/v1/studies
GET  /api/v1/studies/{study_id}
PATCH /api/v1/studies/{study_id}

POST /api/v1/studies/{study_id}/source-files
GET  /api/v1/studies/{study_id}/source-files
GET  /api/v1/source-files/{source_file_id}
GET  /api/v1/source-files/{source_file_id}/download
```

Source-file creation streams the upload, calculates SHA-256, applies size and media checks, and returns an immutable source-file record containing the ID of its corresponding `source_file` artifact. Neither response exposes an object-store key. A corrected file is a new resource and artifact.

## 7. Raw routes

```text
POST  /api/v1/studies/{study_id}/raw
GET   /api/v1/studies/{study_id}/raw
GET   /api/v1/raw/{raw_id}
PATCH /api/v1/raw/{raw_id}
GET   /api/v1/raw/{raw_id}/dependencies
PUT   /api/v1/raw/{raw_id}/dependencies

GET    /api/v1/raw/{raw_id}/datasets
POST   /api/v1/raw/{raw_id}/datasets
GET    /api/v1/raw-datasets/{dataset_id}
PATCH  /api/v1/raw-datasets/{dataset_id}
DELETE /api/v1/raw-datasets/{dataset_id}

GET    /api/v1/raw-datasets/{dataset_id}/variables
POST   /api/v1/raw-datasets/{dataset_id}/variables
POST   /api/v1/raw-datasets/{dataset_id}/variables/initialize
GET    /api/v1/raw-variables/{variable_id}
PATCH  /api/v1/raw-variables/{variable_id}
DELETE /api/v1/raw-variables/{variable_id}

POST /api/v1/raw-datasets/{dataset_id}/preview
POST /api/v1/raw/{raw_id}/validate
GET  /api/v1/raw/{raw_id}/latest-validation-run
POST /api/v1/raw/{raw_id}/reconcile
POST /api/v1/raw/{raw_id}/artifacts/fingerprint
POST /api/v1/raw/{raw_id}/artifacts
```

A raw dataset binds a manually maintained dataset record to an exact, study-owned immutable source-file record and its corresponding artifact. Dataset natural keys are unique within the Raw workbench. Replacing the file binding uses `PATCH` with `If-Match`, creates a new aggregate revision, and makes dependent input selections, Derivation Plans, validation runs, artifacts, and executions stale or alignment-required as applicable; it never overwrites the source file.

Variable metadata includes the source name, label, physical type, length or precision where applicable, ordinal position, role, controlled terminology reference, and user-authored description. `variables/initialize` inspects the selected file and fills only missing factual physical metadata. It preserves manual edits and does not infer clinical meaning, mappings, derivations, annotations, or review decisions. Raw dependencies may select applicable raw-layout or metadata standards, terminology for explicitly bound values, study Reference revisions for source systems, vendors, sites, and units, and templates for dictionary or import/export workbooks; none is inferred from uploaded rows.

Preview accepts a typed column selection and bounded row window, returns `200 OK`, and does not
persist rows or create an artifact. Validation checks file availability and checksum, supported
format, physical-schema agreement, unique dataset and variable names, metadata completeness, and
trace-link integrity. `reconcile` requires the expected current Raw revision and an
`Idempotency-Key`; it snapshots the exact workbench revision and every bound source artifact
ID/checksum, then durably compares names, physical types, ordinals, lengths, and precision. Its
immutable report contains physical schema facts and issue records but no source rows or internal
object-store locations. Raw artifact requests follow the common artifact-build contract.

`artifacts/fingerprint` is a read-only preview. It accepts
`{ "artifact_types": [...] }` (at least one, drawn from the fixed Raw artifact-type set) and
returns `200 OK` with `{ "input_fingerprint": "<64 hex>" }` computed from the exact same resolved
build inputs as `POST /api/v1/raw/{raw_id}/artifacts`. The returned value is the value a client
sends back as `expected_input_fingerprint` on the build request. It requires study access,
persists nothing, needs no `Idempotency-Key`, and returns `422` for unsupported or invalid
artifact types or owner, consistent with the sibling Raw routes.

`latest-validation-run` is a read-only reference to the newest `succeeded` Raw validation run
owned by this workbench. It returns `200 OK` with
`{ "validation_run_id": <uuid>, "raw_revision": <int|null>, "completed_at": <rfc3339|null>,
"input_fingerprint": "<64 hex>" }` so a consumer (the SDTM input selection) can pin
`validation_run_id` without typing it; `raw_revision` is read from the run's input manifest and is
advisory. It requires study access, persists nothing, needs no `Idempotency-Key`, and returns
`404 raw_validation_run_not_found` when the workbench has no successful run yet.

## 8. Documents routes

### 8.1 Document resources

```text
POST  /api/v1/studies/{study_id}/documents
GET   /api/v1/studies/{study_id}/documents
GET   /api/v1/documents/{document_id}
PATCH /api/v1/documents/{document_id}
GET   /api/v1/documents/{document_id}/dependencies
PUT   /api/v1/documents/{document_id}/dependencies

GET  /api/v1/documents/{document_id}/content
PUT  /api/v1/documents/{document_id}/content
POST /api/v1/documents/{document_id}/content/import
GET  /api/v1/documents/{document_id}/content/export

POST /api/v1/documents/{document_id}/validate
POST /api/v1/documents/{document_id}/artifacts
```

Creation requires one of these `document_type` values:

```text
protocol
protocol_amendment_summary_of_change
protocol_deviation_document
aggregate_study_risk_profile
data_management_plan
statistical_analysis_plan
centralized_monitoring_platform_setup_documentation
protocol_deviation_dataset
aggregate_study_brief
study_data_summary
standard_quality_dashboard_qe_details
standard_quality_dashboard_sqe_audit_capa_details
standard_quality_dashboard_audit_observation_detail
signals_report
actions_report
```

Document metadata includes its `document_type`, aggregate-scoped `document_code` natural key, user-facing name, lifecycle status, content schema version, and explicit related document IDs. A relationship never selects a Protocol, SAP, or other document implicitly. Every type has a dedicated versioned Pydantic content contract. Its dependencies bind applicable content/schema standards, controlled-value terminology, exact study Reference revisions, and one presentation template per generated artifact type. PDF document types use structured sections compatible with the shared `Document` renderer. Workbook types use typed sheets, columns, and row contracts. XLSX and JSON content imports are atomic, preserve user-maintained values, and do not infer narrative content, risk decisions, signals, actions, CAPA conclusions, or clinical mappings. Templates may supply headings, styles, and blank structures only. `content/export` accepts a `format` query value of `json` or, for workbook types, `xlsx` and returns a non-persisting `200 OK` response. Immutable deliverables are created through `POST .../artifacts`, which accepts an explicit artifact-type list and expected input fingerprint.

### 8.2 Protocol-specific resources

```text
GET  /api/v1/documents/{document_id}/usdm
PUT  /api/v1/documents/{document_id}/usdm
POST /api/v1/documents/{document_id}/usdm/import
GET  /api/v1/documents/{document_id}/usdm/export

GET    /api/v1/documents/{document_id}/evidence
POST   /api/v1/documents/{document_id}/evidence
GET    /api/v1/document-evidence/{evidence_id}
PATCH  /api/v1/document-evidence/{evidence_id}
DELETE /api/v1/document-evidence/{evidence_id}
```

These routes are valid only when `document_type` is `protocol`; otherwise they return `409 invalid_document_type`. Protocol creation references an existing study-owned PDF source file. The USDM `PUT` replaces the versioned structured document after complete validation. Evidence records contain a source PDF ID, page number, coordinate system and rectangle or polygon, excerpt, linked USDM entity IDs, question and resolution fields, and reviewer status.

### 8.3 Statistical Analysis Plan resources

```text
GET /api/v1/documents/{document_id}/protocol-context
```

This route is valid only when `document_type` is `statistical_analysis_plan`. The SAP content contract includes `protocol_alignment`, `objectives`, `endpoints`, `estimands`, `populations`, `methods`, `multiplicity`, `missing_data`, `sensitivity_analyses`, `output_requirements`, `assumptions`, `qc_items`, `narrative_sections`, and `citations`.

`protocol-context` is read-only and returns stable reference DTOs from the explicitly linked Protocol document. Copying a fact into SAP is an explicit user edit; the API never silently synchronizes narrative content.

## 9. SDTM routes

### 9.1 Workbench, dependencies, and exact Raw inputs

```text
POST  /api/v1/studies/{study_id}/sdtms
GET   /api/v1/studies/{study_id}/sdtms
GET   /api/v1/sdtms/{sdtm_id}
PATCH /api/v1/sdtms/{sdtm_id}

GET /api/v1/sdtms/{sdtm_id}/dependencies
PUT /api/v1/sdtms/{sdtm_id}/dependencies
GET /api/v1/sdtms/{sdtm_id}/input-selection
PUT /api/v1/sdtms/{sdtm_id}/input-selection
GET /api/v1/sdtms/{sdtm_id}/raw-context
```

The input selection is not an implicit link to the current Raw workbench. `PUT input-selection` requires `If-Match` and supplies the exact `raw_id`, Raw aggregate revision, successful validation-run ID, selected source-file artifact IDs and checksums, and expected Raw dependency fingerprint. The service verifies study ownership, artifact availability, validation success, dataset identity, and consistency with the selected Raw revision. Changing the selection creates a new SDTM revision and stales all dependent SDTM, ADaM, TLF, and package evidence without changing maintained specification content.

`raw-context` is a read-only resolved DTO containing the selected Raw datasets and variables, file artifacts and checksums, validation run, dependency fingerprint, and trace endpoints. SDTM never reads Raw repositories directly or substitutes a newer source artifact. The dependency selection binds exact SDTM IG, Define-XML, terminology and extension revisions, study Reference revisions, and artifact templates. Define rendering selects `2.0` or `2.1` explicitly, and the requested version must be present and compatible in the dependency selection.

### 9.2 SDTM Specification

```text
GET  /api/v1/sdtms/{sdtm_id}/specification
PUT  /api/v1/sdtms/{sdtm_id}/specification
POST /api/v1/sdtms/{sdtm_id}/specification/import
GET  /api/v1/sdtms/{sdtm_id}/specification/export
```

The versioned SDTM Specification is one aggregate contract containing domains, variables, value-level metadata where applicable, terminology bindings, domain keys and sort order, sequencing metadata, expected output names, and typed trace targets. Natural keys are unique within the workbench or domain. A terminology binding owns only SDTM usage context—domain/variable, optional value-level condition, and submission behavior—and references a codelist or term resolvable within the exact dependency selection; it never copies shared terminology. The Specification owns target metadata but no executable transformation logic.

`PUT specification` and import require `If-Match`, validate the complete contract, and commit one revision atomically. Import also requires `Idempotency-Key`; replaying the same key and exact bytes returns the originally committed revision, while different bytes conflict. JSON/XLSX import validates every sheet, natural-key uniqueness, cross-references, terminology, metadata constraints, and trace targets before writing anything; it never imports backend code or replaces the Derivation Plan. XLSX uses versioned `Metadata`, `Domains`, `Variables`, and `ValueLevel` sheets and serializes keys, sort order, typed conditions, and terminology bindings explicitly. Export selects non-persisting JSON or XLSX with `?format=json|xlsx`. Immutable metadata deliverables use the artifact endpoint.

### 9.3 Derivation Plan and operations

```text
GET  /api/v1/sdtms/{sdtm_id}/derivation-plan
PUT  /api/v1/sdtms/{sdtm_id}/derivation-plan
POST /api/v1/sdtms/{sdtm_id}/derivation-plan/validate
POST /api/v1/sdtms/{sdtm_id}/derivation-plan/preview
GET  /api/v1/sdtms/{sdtm_id}/lineage

POST /api/v1/sdtms/{sdtm_id}/validate
POST /api/v1/sdtms/{sdtm_id}/compile
POST /api/v1/sdtms/{sdtm_id}/execute
POST /api/v1/sdtms/{sdtm_id}/artifacts
```

The Derivation Plan is an SDTM-owned typed DAG aligned to one SDTM Specification revision and one exact Raw input-selection revision. It owns raw reads, filters, joins, projections, reshaping, derivations, terminology application, sequencing, sorting, assertions, and declared domain writes. Nodes use SDTM vocabulary and stable raw/domain/variable references. Backend-specific code fragments are prohibited. After SDTM validation, the module lowers the plan to internal Dataflow IR; IR is not exposed as an editable API resource.

Workbench validation covers dependency compatibility with the exact Raw context; Specification completeness; domain structure, keys, variables, value-level metadata, terminology, and sequencing; Derivation Plan shape and output coverage; traceability; XPT constraints; and declared output reconciliation. Preview selects target domain codes and bounded rows, then uses the same lowering path as compilation. Preview results are transient and cannot serve as submission artifacts.

The artifact endpoint can publish the canonical XLSX `sdtm_specification`, JSON
`sdtm_derivation_report`, `sdtm_lineage_report`, and `sdtm_validation_report` alongside canonical
plan JSON and generated programs. Every Python/R execution attempt publishes a bounded immutable
`sdtm_execution_log` JSON artifact linked to the execution run; successful declared datasets are
separate CSV/XPT output artifacts.

Compile requests select `python`, `r`, or `sas`, declared target domain codes, expected Specification/input/Derivation Plan fingerprints, and output options. Execute requests select compiled program artifact IDs and the exact immutable source-file artifacts from the input selection. Every program, execution, and output records the input selection, Specification revision, Derivation Plan revision, normalized IR/operator/compiler versions, runner image, and declared output schema.

### 9.4 aCRF

```text
GET    /api/v1/sdtms/{sdtm_id}/acrf/annotations
POST   /api/v1/sdtms/{sdtm_id}/acrf/annotations
GET    /api/v1/acrf-annotations/{annotation_id}
PATCH  /api/v1/acrf-annotations/{annotation_id}
DELETE /api/v1/acrf-annotations/{annotation_id}
POST   /api/v1/acrf-annotations/{annotation_id}/links
GET    /api/v1/sdtms/{sdtm_id}/acrf/coverage
POST   /api/v1/sdtms/{sdtm_id}/acrf/reconcile
POST   /api/v1/sdtms/{sdtm_id}/acrf/artifacts
```

The links operation atomically replaces or amends typed links to SDTM variables, Raw variables, and stable nodes or assertions in an exact Derivation Plan revision. Reconciliation creates an immutable reconciliation run.

Annotation coordinates use the `normalized_top_left` system with `x`, `y`, `width`, and
`height` values bounded by the page. Creation identifies one immutable source PDF artifact and
requires the SDTM workbench `ETag`. Annotation edits, link replacement/amendment, and soft
deletion require the annotation `ETag`. SDTM-variable links include an exact Specification
revision and domain/variable natural key; plan-node links include an exact plan revision and node
ID; Raw-variable links are UUIDs resolved through the Raw module boundary and must belong to the
SDTM workbench's selected Raw context.

### 9.5 Define-XML

```text
GET  /api/v1/sdtms/{sdtm_id}/define
PUT  /api/v1/sdtms/{sdtm_id}/define
POST /api/v1/sdtms/{sdtm_id}/define/initialize
POST /api/v1/sdtms/{sdtm_id}/define/validate
POST /api/v1/sdtms/{sdtm_id}/define/reconcile
GET  /api/v1/sdtms/{sdtm_id}/define/render
POST /api/v1/sdtms/{sdtm_id}/define/artifacts
```

`initialize` accepts an expected revision and fills absent structures from the exact SDTM
Specification and output artifacts without replacing user-edited values. `validate` renders the
same version-neutral model as both 2.0 and 2.1 and validates it offline against the repository's
pinned XSD suites; its immutable input manifest records both schema-suite fingerprints. `render`
requires a `version` query parameter with value `2.0` or `2.1`; it is a non-persisting preview and
requires a current zero-error Define validation. `artifacts` requires `Idempotency-Key`, the
canonical build-input fingerprint, current zero-error validation, and successful exact
Define/XPT/aCRF reconciliation. It creates immutable XML artifacts carrying the validation run,
reconciliation run, exact XPT checksums, dependency selection, and schema fingerprint.

`reconcile` requires an exact Define revision/fingerprint and `Idempotency-Key`. It snapshots the
Define revision, selected XPT IDs/checksums, and active aCRF annotation revisions, then returns
`202 Accepted` with an immutable Reconciliation run. Registered SDTM rules compare XPT metadata,
Define leaves, and aCRF/Define variable references and publish a report artifact.

### 9.6 cSDRG

```text
GET  /api/v1/sdtms/{sdtm_id}/csdrg
PUT  /api/v1/sdtms/{sdtm_id}/csdrg
POST /api/v1/sdtms/{sdtm_id}/csdrg/initialize
POST /api/v1/sdtms/{sdtm_id}/csdrg/validate
POST /api/v1/sdtms/{sdtm_id}/csdrg/artifacts
```

Initialization binds the current exact Specification, Define revision, successful zero-error
reconciliation run, and XPT artifact IDs/checksums. It creates headings and factual tables for
`study_data_overview`, `standards_and_versions`, `trial_design`, `domain_notes`,
`conformance_issues`, `sponsor_defined_domains`, `controlled_terminology`, `data_dependencies`,
and `reviewer_guidance`. It leaves narrative fields for manual authoring and preserves authored
narratives during later factual refreshes. Validation treats missing or empty required narratives
as errors. Artifact creation requires exact compatible Template selections and records both the
validation run and reconciliation run on immutable DOCX/PDF artifacts.

## 10. ADaM routes

### 10.1 Workbench, dependencies, and exact SDTM inputs

```text
POST  /api/v1/studies/{study_id}/adams
GET   /api/v1/studies/{study_id}/adams
GET   /api/v1/adams/{adam_id}
PATCH /api/v1/adams/{adam_id}

GET /api/v1/adams/{adam_id}/dependencies
PUT /api/v1/adams/{adam_id}/dependencies
GET /api/v1/adams/{adam_id}/input-selection
PUT /api/v1/adams/{adam_id}/input-selection
GET /api/v1/adams/{adam_id}/sdtm-context
```

The input selection is not an implicit link to the current SDTM workbench. `PUT input-selection` requires `If-Match` and supplies the exact `sdtm_id`, SDTM aggregate revision, successful validation-run ID, selected SDTM XPT artifact IDs, and expected SDTM dependency fingerprint. The service verifies study ownership, artifact availability and checksums, validation success, dataset uniqueness, and consistency with the selected SDTM revision. Changing the selection creates a new ADaM revision and stales all dependent ADaM and TLF evidence.

`sdtm-context` is a read-only resolved DTO containing the selected SDTM dataset and variable metadata, terminology bindings, trace endpoints, XPT artifacts and checksums, validation run, and dependency fingerprint. ADaM never reads SDTM repositories or substitutes a newer artifact.

### 10.2 ADaM Specification

```text
GET  /api/v1/adams/{adam_id}/specification
PUT  /api/v1/adams/{adam_id}/specification
POST /api/v1/adams/{adam_id}/specification/import
GET  /api/v1/adams/{adam_id}/specification/export
```

The versioned ADaM Specification uses the common Specification envelope and is one aggregate contract containing datasets, variables, parameters, value-level metadata, methods, terminology bindings, and typed trace targets. Dataset entries record natural key, label, selected-standard class, structure, keys, sort order, purpose, and expected output name. Variable entries record physical metadata, role, origin, predecessor, method, terminology binding, and the stable Derivation Plan output that produces the variable. Dataset classes and roles resolve through the selected Standards version rather than a hard-coded global enum.

Parameters have stable UUIDs and codes, labels, target datasets, optional terminology terms, applicability, and expected analysis-value semantics. Value-level metadata binds a typed condition to exact variable metadata, origin, method, terminology, and display attributes. Methods contain reviewer-readable maintained text and links to the exact Derivation Plan nodes and outputs they explain; method text is never executable.

Typed trace targets connect exact Protocol objectives/endpoints or SAP objectives/endpoints/estimands/populations/methods to specification datasets, variables, parameters, or value-level items. The ADaM service verifies registered entity and relationship ownership, resolves both endpoints to the same study, and replaces the revision's relationships through the shared traceability service in the same transaction as the specification revision; it does not maintain a second relationship store or infer bindings from matching names.

`PUT specification` and import require `If-Match`, validate the complete versioned contract, and commit one revision atomically. JSON/XLSX import validates all sheets, natural-key uniqueness, references, terminology, origins, and trace targets before writing anything; it never imports backend code or replaces the Derivation Plan. The XLSX contract uses `Metadata`, `Datasets`, `Variables`, `Parameters`, `ValueLevel`, `Methods`, and `TraceTargets` sheets. Export returns non-persisting JSON or XLSX. Immutable metadata deliverables use the artifact endpoint.

### 10.3 Derivation Plan and operations

```text
GET  /api/v1/adams/{adam_id}/derivation-plan
PUT  /api/v1/adams/{adam_id}/derivation-plan
POST /api/v1/adams/{adam_id}/derivation-plan/validate
POST /api/v1/adams/{adam_id}/derivation-plan/preview
GET  /api/v1/adams/{adam_id}/lineage

POST /api/v1/adams/{adam_id}/validate
POST /api/v1/adams/{adam_id}/compile
POST /api/v1/adams/{adam_id}/execute
POST /api/v1/adams/{adam_id}/artifacts
```

The Derivation Plan uses the common Derivation Plan envelope and is an ADaM-owned typed DAG aligned to one ADaM Specification revision and one exact SDTM input-selection revision. It may read only artifacts in that selection and declared predecessor ADaM outputs. Dataset-to-dataset dependencies must remain acyclic. Nodes use ADaM vocabulary and stable dataset/variable/parameter references. Backend-specific code fragments are prohibited. After ADaM validation, the module lowers the plan to internal Dataflow IR; IR is not exposed as an editable API resource.

Workbench validation covers dependency compatibility with the exact SDTM context; specification completeness; dataset classes, keys, and sort order; variables and roles; parameters and value-level applicability; terminology; origins and predecessor resolution; method-to-node alignment; Derivation Plan shape and output coverage; traceability; XPT constraints; and declared output reconciliation. It reports specification, derivation, standards, traceability, and artifact issues as distinguishable categories.

Preview selects target dataset codes and bounded rows, then uses the same lowering pipeline as compilation. Compile selects `python`, `r`, or `sas` and supplies the expected canonical build-input fingerprint. Execute selects the compiled program, exact SDTM XPT artifacts, validation and authoring revisions, compiler and program-input fingerprints, and bounded resource limits. Every program, execution, and output records the input selection, Specification revision, Derivation Plan revision, normalized IR/operator/compiler versions, and declared output schema. The runner image and execution metrics are recorded on the execution run and log artifact.

### 10.4 Define-XML and ADRG

ADaM Define routes parallel SDTM Define routes:

```text
GET  /api/v1/adams/{adam_id}/define
PUT  /api/v1/adams/{adam_id}/define
POST /api/v1/adams/{adam_id}/define/initialize
POST /api/v1/adams/{adam_id}/define/validate
GET  /api/v1/adams/{adam_id}/define/render
POST /api/v1/adams/{adam_id}/define/reconcile
POST /api/v1/adams/{adam_id}/define/artifacts
```

The non-persisting `render` endpoint requires a `version` query parameter with value `2.0` or `2.1`. The ADaM Define model includes dataset classes, analysis roles, parameters, value-level metadata, origins, methods, terminology references, and SDTM traceability. Initialization may add missing factual structures from the saved ADaM Specification and exact output artifacts but cannot overwrite user-maintained metadata or narrative.

Define validation is an immutable snapshot over the current Specification, exact SDTM selection,
Define revision, output checksums, local XSD fingerprints, renderer version, and validator version.
It reports stable common-model issues for missing, extra, or mismatched dataset, variable,
parameter, value-level, origin, method, and terminology metadata. Every predecessor must resolve
against the selected SDTM metadata or maintained ADaM metadata. Rendering and publication require
the current zero-error validator version; validation from an older rule set cannot satisfy the
gate. XPT reconciliation additionally compares dataset filename/label and exact variable order,
names, labels, types, lengths, origins, and methods.

Typed value-level conditions composed of same-dataset column-to-literal equality or ordering
comparisons and conjunctions render as formal `ValueListDef` and `WhereClauseDef` structures in
both versions. The complete typed contract is also retained in a deterministic referenced comment.
Conditions outside that lossless subset remain comment-only rather than being weakened or rewritten.

ADRG routes are:

```text
GET  /api/v1/adams/{adam_id}/adrg
PUT  /api/v1/adams/{adam_id}/adrg
POST /api/v1/adams/{adam_id}/adrg/initialize
POST /api/v1/adams/{adam_id}/adrg/validate
POST /api/v1/adams/{adam_id}/adrg/artifacts
```

Initialization requires the current Define revision and its successful zero-error
`adam_define_outputs` reconciliation. It fills exact XPT dataset/checksum facts and successful
execution/program facts, binds the current input-selection, Specification, Derivation Plan, and
Define revisions, and does not overwrite user narrative in `study_data_overview`, `standards`,
`analysis_datasets`, `analysis_variables`, `data_dependencies`, `important_derivations`,
`conformance_issues`, `submission_programs`, or `reviewer_guidance`. Validation fails while any
required section lacks manually authored paragraphs. Artifact creation additionally requires
current zero-error ADRG validation and one exact compatible Template selection per requested
DOCX/PDF artifact type.

## 11. TLF routes

```text
POST  /api/v1/studies/{study_id}/tlfs
GET   /api/v1/studies/{study_id}/tlfs
GET   /api/v1/tlfs/{tlf_id}
PATCH /api/v1/tlfs/{tlf_id}
GET   /api/v1/tlfs/{tlf_id}/dependencies
PUT   /api/v1/tlfs/{tlf_id}/dependencies

GET /api/v1/tlfs/{tlf_id}/shell
PUT /api/v1/tlfs/{tlf_id}/shell
GET /api/v1/tlfs/{tlf_id}/bindings
PUT /api/v1/tlfs/{tlf_id}/bindings
GET /api/v1/tlfs/{tlf_id}/assumptions
PUT /api/v1/tlfs/{tlf_id}/assumptions
GET /api/v1/tlfs/{tlf_id}/ars
PUT /api/v1/tlfs/{tlf_id}/ars
GET /api/v1/tlfs/{tlf_id}/program-plan
PUT /api/v1/tlfs/{tlf_id}/program-plan
POST /api/v1/tlfs/{tlf_id}/program-plan/validate
POST /api/v1/tlfs/{tlf_id}/program-plan/preview

POST /api/v1/tlfs/{tlf_id}/validate
POST /api/v1/tlfs/{tlf_id}/compile
POST /api/v1/tlfs/{tlf_id}/execute
POST /api/v1/tlfs/{tlf_id}/render
POST /api/v1/tlfs/{tlf_id}/artifacts
```

Validation requires every leaf shell row to map to an explicit analysis step. The dependency selection may bind an exact ARS version, explicitly used terminology, study Reference revisions, and one presentation template per output artifact type. Templates control layout but never create analysis steps, titles, interpretations, populations, parameters, or statistics.

The ProgramPlan owns explicit ADaM reads, filters, population/parameter selection, statistical procedures, post-processing, and normalized result requirements in TLF vocabulary. After TLF validation, it lowers internally to Analysis IR; data-preparation portions may lower further to shared Dataflow IR. Neither IR is an editable API resource. Shell layout, titles, footnotes, pagination, styles, and rendering remain outside compilation. Preview and compile use the same lowering path. Compile supports `python`, `r`, and `sas`; execution selects exact ADaM artifacts and a compiled program artifact. Render requests select validated result artifacts from the same successful run, the exact shell revision, and the exact Template version.

## 12. Validation, artifact, and build routes

```text
GET  /api/v1/validation-runs/{validation_run_id}
POST /api/v1/validation-runs/{validation_run_id}/cancel

GET  /api/v1/studies/{study_id}/artifacts
GET  /api/v1/artifacts/{artifact_id}
GET  /api/v1/artifacts/{artifact_id}/download
POST /api/v1/artifacts/{artifact_id}/validate

POST /api/v1/artifact-builds
GET  /api/v1/artifact-builds/{build_id}
POST /api/v1/artifact-builds/{build_id}/cancel
```

Validation-run cancellation is available only while the run is queued or running. Artifact validation creates a validation run and follows the common `/validate` action contract.

Artifact filters include module, type, owner, status, source-plan type, validation run, reconciliation run, execution run, and creation range. The generic build route is intended for clients that already know owner and artifact types; module convenience routes submit the same internal command.

Example build request:

```json
{
  "study_id": "uuid",
  "owner_type": "sdtm_solution",
  "owner_id": "uuid",
  "artifact_types": ["sdtm_specification", "sdtm_derivation_report"],
  "expected_input_fingerprint": "sha256 hex",
  "options": {}
}
```

For a clinical owner, the owner resolver supplies the exact dependency selection and rejects a client attempt to override it in `options`. For a shared Review, Reconciliation, or Validation report whose owner has no clinical dependency selection, `options.report_template_version_id` is required and must name one exact compatible Template version.

## 13. Execution routes

```text
POST /api/v1/execution-runs
GET  /api/v1/execution-runs/{run_id}
GET  /api/v1/execution-runs/{run_id}/logs
GET  /api/v1/execution-runs/{run_id}/outputs
POST /api/v1/execution-runs/{run_id}/cancel
```

```json
{
  "study_id": "uuid",
  "module": "adam",
  "owner_type": "adam_workbench",
  "owner_id": "uuid",
  "language": "python",
  "program_artifact_id": "uuid",
  "input_artifact_ids": ["uuid"],
  "validation_run_id": "uuid",
  "input_selection_revision": 5,
  "source_specification_revision": 9,
  "source_plan_type": "adam_derivation",
  "source_plan_revision": 12,
  "compiler_fingerprint": "sha256 hex",
  "expected_input_fingerprint": "sha256 hex",
  "limits": {
    "cpu": 2,
    "memory_mb": 4096,
    "runtime_seconds": 1800,
    "output_bytes": 1073741824
  }
}
```

Clients may request limits only within server policy. The execution service verifies that the requested input-selection, Specification, source-plan identity, and exact input artifacts match the immutable program/compiler manifest; clients cannot execute a program against a different metadata, plan, or input set. SAS returns a run with terminal failure code `runner_not_configured` when no external adapter is configured. Logs are paged or streamed in bounded chunks and never expose executor credentials.

## 14. Traceability routes

```text
POST   /api/v1/studies/{study_id}/trace-links
GET    /api/v1/studies/{study_id}/trace-links
GET    /api/v1/trace-links/{trace_link_id}
DELETE /api/v1/trace-links/{trace_link_id}
GET    /api/v1/studies/{study_id}/traceability
POST   /api/v1/studies/{study_id}/traceability/validate
```

A create request supplies typed source and target references, relationship, and optional metadata. The service verifies both endpoints before committing. The traceability query supports direction, module, relationship, entity, and maximum depth with bounded traversal.

## 15. Submission-package routes

```text
POST /api/v1/studies/{study_id}/submission-packages
GET  /api/v1/studies/{study_id}/submission-packages
GET  /api/v1/submission-packages/{package_id}
GET  /api/v1/submission-packages/{package_id}/download
```

```json
{
  "name": "study-abc-release-1",
  "module_selections": [
    { "module": "raw", "options": {} },
    {
      "module": "documents",
      "options": {
        "document_types": [
          "protocol",
          "statistical_analysis_plan",
          "data_management_plan"
        ]
      }
    },
    { "module": "sdtm", "options": {} },
    { "module": "adam", "options": {} },
    { "module": "tlf", "options": {} }
  ],
  "artifact_ids": ["uuid"],
  "expected_study_fingerprint": "sha256 hex"
}
```

Creation returns `202`. Each entry in `module_selections` names a registered module with the package-contribution capability and uses that module's closed, versioned options schema; unknown keys and arbitrary options are rejected. This lets a deployment-added module contribute required artifacts and trusted package paths without changing the Packaging service's dispatch logic. Selecting `raw` includes Raw metadata and data-dictionary artifacts; original source files are allowed only when package policy explicitly permits them and their exact artifact IDs are selected. The Documents options require `document_types` and apply the required-artifact policy for each listed type. Shared standards, terminology, reference, template, review, rule-pack, and reconciliation artifacts are supporting selections supplied by exact `artifact_ids`; they are not independent package modules. Package validation also verifies ownership, completeness, current fingerprints, validation, reconciliation, and execution status, checksums, module-contributor rules, Define/dataset consistency, aCRF/Define consistency, ADaM lineage, TLF run cohesion, and path safety. A failed package remains as an immutable operation record with issues but has no downloadable ZIP.

## 16. Health and contract publication

```text
GET /health/live
GET /health/ready
GET /api/v1/openapi.json
```

Liveness checks only the process. Readiness verifies required database and object-store connectivity and confirms that module registration completed without capability conflicts. CI snapshots the OpenAPI document and safe module catalog, checks backward compatibility within v1, validates event/import schema compatibility, and generates a typed client fixture used by contract tests.
