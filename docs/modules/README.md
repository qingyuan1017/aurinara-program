# Module usage guides

These guides describe the API that is implemented in the current repository. The broader
target contract remains in [the API contract](../api-contract.md); an endpoint listed there
is not available until it also appears in one of these current-state guides or in the
generated OpenAPI document.

## Start here

1. Follow [local development](../local-development.md) to start PostgreSQL, MinIO, the API,
   and workers.
2. Read [shared platform usage](platform.md) for authentication, studies, ETags,
   idempotency, source files, artifacts, and module discovery.
3. Open `http://127.0.0.1:18000/docs` for the generated, executable request schemas.

All examples below assume:

```powershell
$base = "http://127.0.0.1:18000/api/v1"
$headers = @{ Authorization = "Bearer $($tokenResponse.access_token)" }
```

## Current module status

| Module | Current status | Guide |
| --- | --- | --- |
| Documents | Phase 2 authoring, validation, evidence, and generation | [Documents](documents.md) |
| Standards | Read-only pinned catalog | [Standards](standards.md) |
| Terminology | Read-only releases plus study extensions | [Terminology](terminology.md) |
| Templates | Read-only pinned presentation catalog | [Templates](templates.md) |
| Reference | Revisioned study reference data and atomic import/export | [Reference](reference.md) |
| Review | Verified review targets and append-only comments | [Review](review.md) |
| Reconciliation | Immutable queued comparisons and JSON reports | [Reconciliation](reconciliation.md) |
| Validation | Rules, study rule packs, document and artifact validation | [Validation](validation.md) |
| Integration | Study integrations, subscriptions, identifiers, and delivery evidence | [Integration](integration.md) |
| Raw | Phase 3 datasets, variables, preview, validation, and artifacts | [Raw](raw.md) |
| SDTM | Phase 3 Raw inputs, authoring, execution, XPT v5, aCRF, Define, and cSDRG | [SDTM](sdtm.md) |
| ADaM | Phase 1 aggregate, dependency selection, and dependency manifest | [ADaM](adam.md) |
| TLF | Phase 1 aggregate, dependency selection, and dependency manifest | [TLF](tlf.md) |
| Packaging | Registered placeholder; no submission-package API yet | [Packaging](packaging.md) |

The `kernel`, `artifacts`, `execution`, `studies`, and `traceability` packages are shared
platform services rather than registered clinical modules. Their usable public surface is
covered in [shared platform usage](platform.md). The `transformation` package now provides
internal typed Dataflow/Analysis IR, canonicalization, lineage, and deterministic compiler
interfaces; by design it has no public API or persisted universal plan.

## Important product boundary

Aurinara records user-authored clinical content. It does not generate clinical narrative,
mapping decisions, derivations, risk decisions, signals, actions, or conclusions. Current
validation and rendering preserve this boundary.
