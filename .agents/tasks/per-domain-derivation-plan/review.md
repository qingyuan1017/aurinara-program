# Per-domain SDTM / per-dataset ADaM Derivation Plans — review (pass 2)

This change splits the single SDTM Derivation Plan (one DAG spanning every domain) into one plan per domain, and the single ADaM plan into one plan per dataset, while the Specification stays a single all-domains/all-datasets aggregate. SDTM gains an `sdtm_read` node that lowers to an IR `read`; ADaM reworks `adam_read` from an in-plan predecessor edge to a cross-plan read. Cross-plan reads are made correct by server-resolved `upstream_plan_pins` plus a transitive `upstream_plan_changed` staleness edge, serialized by an aggregate-row `FOR UPDATE` lock. The collective output-coverage invariant is enforced in the all-domain/all-dataset deliverables, the migration splits legacy plans and backfills annotations/pins, and AGENTS.md plus the docs are corrected to the per-domain/per-dataset model.

This is the second review pass. The first pass returned `CHANGES_REQUESTED` with four findings (missing verification evidence, missing collective coverage gate, uncorrected AGENTS.md/docs, and a migration alignment-reasons invariant break). All four are addressed on branch `per-domain-derivation-plan` (single commit `d7cf6c3`), and no new blocking concern surfaced.

Watch for: nothing blocking. Two non-blocking observations are noted below (local `import re` in a route helper; the coverage test uses a sentinel dict rather than real plan rows). Both are confirmed and cosmetic.

**Verdict**: APPROVED

## High-level view

The four prior-pass findings are all resolved. Verification evidence now exists: the branch carries a commit and `verification.md` records `ruff check`, `ruff format --check`, `mypy src workers`, a clean-DB `alembic upgrade head` to `20261009_0012`, and pytest runs (213 unit+contract; 243 passed / 5 skipped with integration+conformance). Per the mandate I did not re-run the suites; the evidence is specific and internally consistent, and the one spot-checkable risk (migration constraint ordering) is both described in the evidence and visible in the migration source.

The collective coverage gate is implemented as `require_output_coverage` on both `SdtmCapability` and `AdamCapability`. It computes the derived-target set from the current Specification and compares against authored plan heads, raising `409 sdtm_output_coverage_incomplete {missing_domains}` / `409 adam_output_coverage_incomplete {missing_datasets}`. It is invoked from every all-domain/all-dataset deliverable (SDTM aCRF, Define, cSDRG; ADaM Define, ADRG), so a never-authored derived target can no longer slip through `aligned_domain_plans`/`aligned_dataset_plans`, which only gate targets that already have a plan row.

AGENTS.md, `docs/api-contract.md` (§4.7, §9.3, §10.3), `docs/architecture.md`, `docs/artifact-catalog.md`, and `docs/implementation-plan.md` are rewritten to the per-domain/per-dataset model. §4.7 now describes the real stored/response envelope, states the SDTM rule as dataset-level, defers `module`/`outputs`/`assertions`, and removes the never-implemented `derivation_plan_alignment_required` code. The route inventory and the typed-client contract fixture carry the new per-domain/per-dataset paths plus the collection and per-target validate routes.

The migration (`0012`) sets `alignment_reasons = ["specification_changed"]` for sub-rows split from a legacy misaligned row (and `NULL` for aligned rows), restoring the "empty iff aligned" invariant. It also drops the old `(aggregate_id, revision)` unique constraint before the split and adds the per-target constraint after — fixing a constraint-ordering defect the coder found and recorded during verification.

The staleness model is correct end to end: write-time pin resolution rejects reads of absent or misaligned siblings (`upstream_state: "absent"` vs the sibling state), `mark_sibling_plan_change` propagates transitively on any transition into misaligned, `require_domain_aligned`/`require_dataset_aligned` re-check pinned revisions at operation time, and a workbench-row `FOR UPDATE` lock serializes concurrent plan writes within an aggregate. Spec/input writes misalign every head and keep the workbench ETag; plan writes use the per-target plan-revision ETag and stop bumping the workbench revision.

<details>
<summary>Issues (2)</summary>

1. **Local `import re` in `_require_domain`** — `src/app/sdtm/routes.py` imports `re` inside the route helper to pattern-check the path domain. Non-blocking; a module-level import or reuse of the contract pattern would be cleaner.
2. **Coverage test uses sentinel dict** — `tests/integration/test_phase5_output_coverage.py` passes `{"DM": object()}` to `require_output_coverage` rather than real plan-head rows. It validates the Specification-derived-set-minus-covered-keys computation (the actual gate logic) but not the `aligned_domain_plans` resolution path feeding it; that path is covered by the deliverable-build integration tests. Non-blocking.

</details>

<details>
<summary>Details</summary>

### Prior finding 1 — verification evidence now present

The first pass rejected because the branch had no commits (HEAD == master) and no `verification.md`. Both are fixed: commit `d7cf6c3` carries the change and `verification.md` records the repo's declared tooling (`uv run ruff check .`, `ruff format --check .`, `mypy src workers`, clean-DB `alembic upgrade head` confirming head `20261009_0012`, `pytest tests/unit tests/contract` → 213 passed, and `AURINARA_INTEGRATION=1` across unit/contract/integration/conformance → 243 passed, 5 skipped). The 5 skips are the runner-image execution tests, which are environment-gated and unchanged by this work. The evidence also documents two defects the coder found and fixed during verification (the migration constraint-ordering bug and a Phase 3 SAS-execute provenance mismatch), both of which are consistent with the committed code. Confidence: confirmed (commit and file read directly; suites not re-run per mandate).

### Prior finding 2 — collective output-coverage gate implemented

`require_output_coverage` exists on both capabilities and is wired into every all-domain/all-dataset deliverable. On SDTM it is called from the `sdtm_acrf` branch of `build_artifact_payload`, `_build_define_xml_payload`, and `_build_csdrg_payload`; on ADaM from `_build_define_xml_payload` and `_build_adrg_payload` (verified by grep — five call sites plus the two definitions). Each computes the derived set directly from the Specification (`any(variable.derived ...)` for SDTM, `any(origin.origin_type == "Derived" ...)` for ADaM) and reports `derived - covered`, so a derived target with no authored plan is named in `missing_domains`/`missing_datasets` with `409`. This closes the exact gap the first pass flagged: `aligned_domain_plans`/`aligned_dataset_plans` gate only targets that already have a plan row, so without this gate a never-authored derived target would have been silently skipped. Confidence: confirmed.

### Prior finding 3 — AGENTS.md and docs corrected

AGENTS.md "Architecture" and "Compilation and execution" now state SDTM owns one Specification (all domains) plus one plan per domain and ADaM one plan per dataset, keyed by `(aggregate, target, revision)`, with `sdtm_read`/`adam_read` resolved through the Specification, server-resolved `upstream_plan_pins`, transitive `upstream_plan_changed` staleness, and the union-coverage invariant enforced in build/packaging. `docs/api-contract.md` §4.7 is rewritten to the real stored payload (`schema_version 1.1.0`, `domain`/`dataset`, `nodes`, `edges`) and response-only fields (`alignment_state`, `alignment_reasons`, read-only `upstream_plan_pins`), states the SDTM single-producer rule at the dataset level, defers `module`/`outputs`/`assertions`, replaces the three-value `alignment_reasons` enumeration, and removes `derivation_plan_alignment_required` in favor of the implemented `*_plan_misaligned`/`*_plan_upstream_misaligned` codes. §9.3/§10.3 and the route inventory are repathed to the per-domain/per-dataset routes plus the `derivation-plans` collection and per-target `validate` routes, preserving `/api/v1`, cursor pagination, If-Match/ETag, and the problem codes. `architecture.md`, `artifact-catalog.md`, and `implementation-plan.md` are updated consistently, and the typed-client contract fixture lists the new operations. Confidence: confirmed.

### Prior finding 4 — migration alignment-reasons invariant

The `0012` split now emits `alignment_reasons = ["specification_changed"]` for sub-rows carried over from a misaligned legacy row and `NULL` for aligned rows, satisfying "empty iff aligned". `test_phase5_migration_reason.py` seeds a pre-split misaligned two-domain plan, runs the real `0012` upgrade through Alembic on a dedicated disposable DB, and asserts every emitted per-domain row is `misaligned` with a non-empty `alignment_reasons`. Confidence: confirmed.

### Migration split and downgrade guard

`split_plan` is a pure dict-to-dict helper (no app-service import). It maps writes to codes, computes per-node reachable code sets, assigns a node reaching ≥2 codes to the lexicographically-smallest consumer, injects a read node (`__read_<owner>_<n>`, scanned for non-collision) with an edge into the first owned consumer for every other consumer, and asserts per-plan id uniqueness before emit. Both the relational `schema_version` column and `payload["schema_version"]` are set to `1.1.0`; `created_by`/`created_at` are preserved; `ValidationRun`/`ExecutionRun` rows for affected aggregates are marked `stale`. The old `(aggregate_id, revision)` unique constraint is dropped before the split and the per-target constraint added after — the ordering fix recorded in the evidence. The downgrade guard raises if any aggregate spans more than one distinct code or any row carries injected read pins (JSONB non-empty or a `sdtm_read`/`adam_read` node in the payload), matching the design's distinct-natural-key predicate. Confidence: confirmed by reading the migration module.

### Read binding, lowering, and the no-new-external-pin constraint

`SdtmReadNode{dataset}` lowers to IR `{node_type: "read", dataset}` and the read binding resolves from the single Specification (`specification_slice` / membership in the Specification domain set), introducing no new external input pin — the Raw/SDTM input selection stays the only external pin. `sdtm_read` rejects self-reads (`sdtm_read_self`) and unknown targets (`sdtm_read_target_unknown`); `domain_write`/`derive.target_domain` are restricted to the plan's own domain (`sdtm_plan_output_scope`), exactly one write is allowed (`sdtm_plan_output_duplicate`), and a derived domain must declare its write (`sdtm_plan_output_coverage_missing`). ADaM `adam_read` lowers to a `select` over the predecessor dataset's Specification variables, the former in-plan `adam_plan_predecessor_output_missing`/`adam_plan_predecessor_edge_missing` checks are removed, and acyclicity moves to the cross-plan write-time cycle check. Confidence: confirmed.

### Cross-plan staleness and concurrency

`resolve_upstream_plan_pins` resolves each read target's current sibling head, rejecting an absent sibling (`upstream_state: "absent"`) or a non-aligned/wrong-spec sibling (`sdtm_plan_upstream_misaligned`) at write time, and records sorted de-duplicated `{code, plan_revision}` pins. `mark_sibling_plan_change` flips every aligned head that pins the changed code to misaligned with reason `upstream_plan_changed` and recurses, terminating on the acyclic pin graph (the write-time cycle check forbids closing a cycle). `require_domain_aligned`/`require_dataset_aligned` re-verify each pinned sibling still exists at the pinned revision and is aligned, so `GET` alignment state and operation-time gating agree. `put_plan` acquires `SELECT ... FROM {sdtm,adam}_workbenches WHERE id = :id FOR UPDATE` before resolving pins and inserting, serializing concurrent plan writes within an aggregate; it uses the per-target plan-revision ETag (first write accepts absent/`*`) and no longer bumps `workbench.revision`. Spec/input writes misalign all heads via `_misalign_all_domain_plans`/`_misalign_all_dataset_plans` (reason `specification_changed`/`input_changed`), keep the workbench revision, and retain `_stale_adam_consumers` on all three SDTM write paths. Confidence: confirmed.

### aCRF plan-node resolution and traceability

`AcrfPlanNodeLink` gains optional `domain`, and `sdtm/acrf.py` keys both link validation and coverage on `(aggregate_id, domain_code, revision)`; a link with `domain is None` is reported `acrf_plan_node_unresolved` rather than silently matched, and coverage counts links not pointing at their domain's head as `noncurrent`. The migration backfills `AcrfPlanNodeLink.domain` from the split's node→code map. The documented traceability chain still resolves through these two aCRF paths (no new trace service), and `architecture.md` records that plan-node endpoints now resolve inside the owning per-target plan. Confidence: confirmed.

### Module boundaries and Release 1 non-negotiables

No `transformation` contract change (the IR `read` already represents a named-dataset read). Kernel `source_plan_types` and route prefixes are unchanged — plan multiplicity is per target, not a new source-plan type — so startup conflict checks stay valid. No AI/proposal/automation surface is added; Python/R stay first-party and SAS stays the external-runner adapter; Define-XML stays version-neutral. The `define.py` and `kernel/traceability.py` diffs are line-length reformats only (pre-existing drift noted in the evidence), with no behavioral change. Confidence: confirmed.

</details>

<details>
<summary>File map</summary>

- `AGENTS.md` — per-domain/per-dataset ownership and compilation/execution bullets.
- `docs/api-contract.md` — §4.7 envelope rewrite; §9.3/§10.3 route repath + per-target validate + collection.
- `docs/architecture.md` — three-part workbench, §12.2 authoring contracts, traceability-chain note.
- `docs/artifact-catalog.md` — per-domain/per-dataset plan and program rows; split-staleness note.
- `docs/implementation-plan.md` — §5.3/§6.3 per-target wording; E2E scenarios updated.
- `migrations/versions/20261009_0012_per_domain_derivation_plans.py` — split-backfill, pins, annotation domain backfill, run staleness, guarded downgrade.
- `src/app/sdtm/contracts.py`, `src/app/adam/contracts.py` — `SdtmReadNode`, required `domain`/`dataset`, `schema_version 1.1.0`, `AcrfPlanNodeLink.domain`.
- `src/app/sdtm/models.py`, `src/app/adam/models.py` — `domain_code`/`dataset_code`, `upstream_plan_pins`, `alignment_reasons`, new unique constraint + index.
- `src/app/sdtm/service.py`, `src/app/adam/service.py` — per-target accessors, coverage gate, pins/cycle/staleness, lower_plan rewrite, deliverable gates.
- `src/app/sdtm/routes.py`, `src/app/adam/routes.py` — per-target routes, workbench lock, per-target ETag, misalign-all helpers, manifest shape.
- `src/app/sdtm/acrf.py` — plan-node resolution keyed on `(aggregate, domain, revision)`.
- `src/app/artifacts/builds.py` — thread `domain_code` option through the build path.
- `src/app/adam/define.py`, `src/app/kernel/traceability.py` — cosmetic reformat only.
- `tests/contract/typed_client_fixture.py` — new route inventory.
- `tests/integration/test_phase3_raw_sdtm.py`, `tests/integration/test_phase4_adam.py` — per-target routes, `plan_set_fingerprint` manifest, per-target validation runs.
- `tests/integration/test_phase5_migration_reason.py`, `tests/integration/test_phase5_output_coverage.py` — new tests for finding 4 and finding 2.
- `tests/unit/test_sdtm.py`, `tests/unit/test_adam.py` — read nodes, coverage, `schema_version`, response mapping.

Full diff: `git -C e:\Work\EDETEK\Python\aurinara\.worktrees\per-domain-derivation-plan diff master...per-domain-derivation-plan`

</details>
