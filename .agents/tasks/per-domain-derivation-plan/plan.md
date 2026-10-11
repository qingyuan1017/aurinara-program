# Implementation Plan — Per-Domain SDTM / Per-Dataset ADaM Derivation Plans

Source design: `.agents/tasks/per-domain-derivation-plan/design.md` (authoritative; decisions settled).
All paths below are relative to the worktree root
`e:\Work\EDETEK\Python\aurinara\.worktrees\per-domain-derivation-plan`.
Use `git -C e:\Work\EDETEK\Python\aurinara\.worktrees\per-domain-derivation-plan` for any git op.

## Verification tooling (discovered in repo — use ONLY these)

- Quality gate (from `docs/local-development.md` §13 and `pyproject.toml`):
  `ruff check .`, `ruff format --check .`, `mypy src workers`, `pytest`.
- Fast suites (no DB): `pytest tests/unit`, `pytest tests/contract`.
- DB/integration + conformance suites require a migrated `clinical_test` DB and
  `AURINARA_INTEGRATION=1` (fixtures `skipif` otherwise) with Compose Postgres/MinIO up:
  `docker compose up -d postgres minio minio-init`, then against the test DB
  `uv run alembic upgrade head` (DATABASE_URL pointed at `clinical_test`), then
  `$env:AURINARA_INTEGRATION="1"; pytest tests/integration tests/conformance`.
- Migrations: author under `migrations/versions/`; `alembic upgrade head` / `alembic downgrade`
  must run on a clean DB. Tests apply migrations from an empty DB (never `metadata.create_all`).
- Alembic head today is `20261008_0011` (`adam_adrg`); new migration is `20261009_0012`,
  `down_revision = "20261008_0011"`.

Run order within a task: narrowest unit tests → `ruff`/`mypy` → broader suites. Keep the tree
buildable (imports resolve, `mypy` clean) after every numbered item.

Note on cross-plan coupling: SDTM and ADaM are structurally symmetric. Where an item says
"mirror on ADaM", apply the same shape (`domain`→`dataset`, `domain_write`→`dataset_write`,
`sdtm_read`→`adam_read`, `SdtmWorkbench`→`AdamWorkbench`, `aligned_domain_plans`→
`aligned_dataset_plans`, `require_domain_aligned`→`require_dataset_aligned`).

---

## Phase A — Contracts (pure, no DB) — SDTM then ADaM

- [ ] 1. Add the SDTM read node and per-domain envelope fields to the SDTM authoring contracts.
      Add `SdtmReadNode(StrictModel)` with `node_type: Literal["sdtm_read"]`,
      `id: str = Field(min_length=1, max_length=128)`,
      `dataset: str = Field(pattern=r"^[A-Z][A-Z0-9]{1,7}$")` and add it to the `SdtmPlanNode`
      discriminated union (design §2.4). On `SdtmDerivationPlan`: add required
      `domain: str = Field(pattern=r"^[A-Z][A-Z0-9]{1,7}$")` and change
      `schema_version` from `Literal["1.0.0"]` to `Literal["1.1.0"] = "1.1.0"` (design §2.3).
      On `AcrfPlanNodeLink`: add optional `domain: str | None = None` (design §2.5, Finding 7).
      Do NOT add `module`/`outputs`/`assertions` (explicitly deferred, §2.3).
      Files: `src/app/sdtm/contracts.py`
      Verify: `pytest tests/unit/test_sdtm.py` — existing contract tests still import/parse
      (expect some assertions about `schema_version=="1.0.0"` and plan shape to fail; they are
      fixed in Phase F). Also `ruff check src/app/sdtm/contracts.py` and
      `mypy src` (contracts module type-clean).

- [ ] 2. Add the per-dataset envelope field to the ADaM plan contract.
      On `AdamDerivationPlan`: add required `dataset: str = Field(pattern=r"^[A-Z][A-Z0-9]{1,7}$")`
      and change `schema_version` to `Literal["1.1.0"] = "1.1.0"` (design §2.3, §3.2). No new node
      type — `SdtmReadNode`/`AdamReadNode` already exist in `adam/contracts.py`.
      Files: `src/app/adam/contracts.py`
      Verify: `pytest tests/unit/test_adam.py` (import/parse OK; schema_version assertions fail
      pending Phase F); `mypy src`.

## Phase B — Persistence models + Alembic migration 0012 (SDTM + ADaM together)

- [ ] 3. Extend the SDTM and ADaM plan-revision ORM models for per-domain/per-dataset keying.
      SDTM `SdtmDerivationPlanRevision`: add non-null `domain_code: Mapped[str]` (`String(8)`),
      `upstream_plan_pins: Mapped[list[dict[str,object]]]` (`JSONB`, non-null, default `list`),
      `alignment_reasons: Mapped[list[str] | None]` (`JSONB`, nullable); replace
      `UniqueConstraint("aggregate_id","revision", name="uq_sdtm_plan_aggregate_revision")` with
      `UniqueConstraint("aggregate_id","domain_code","revision",
      name="uq_sdtm_plan_aggregate_domain_revision")` and add
      `Index("ix_sdtm_plan_aggregate_domain","aggregate_id","domain_code")` (design §2.1).
      Mirror on ADaM `AdamDerivationPlanRevision` with `dataset_code`,
      `uq_adam_plan_aggregate_dataset_revision`, `ix_adam_plan_aggregate_dataset` (§2.2).
      Add a CHECK on `domain_code`/`dataset_code` matching `^[A-Z][A-Z0-9]{1,7}$` where the
      project expresses CHECKs (if not used elsewhere, enforce the pattern in services/contracts
      and skip the DB CHECK — match existing convention).
      Files: `src/app/sdtm/models.py`, `src/app/adam/models.py`
      Verify: `mypy src` clean; `python -c "import app.sdtm.models, app.adam.models"` imports.
      (DB behavior verified in item 4.)

- [ ] 4. Author Alembic migration `20261009_0012_per_domain_derivation_plans`
      (`down_revision="20261008_0011"`) implementing the full split-backfill (design §2.6).
      Steps, SDTM then ADaM mirrored:
      (1) add nullable `domain_code`/`dataset_code`, non-null `upstream_plan_pins JSONB DEFAULT '[]'`,
      nullable `alignment_reasons JSONB`;
      (2) a pure dict→dict split helper **inside the migration module** (no app-service import):
      compute `domain_write`→domain map, assign each node to the single domain whose
      `domain_write` it reaches; a node reaching ≥2 domains is owned by the
      lexicographically-smallest consuming domain, and every other consumer gets an injected
      `sdtm_read{dataset=<owner>}` (`adam_read` for ADaM) plus an edge; keep original node ids
      stable, generate injected read ids by scanning the target sub-plan's existing ids for the
      first non-colliding `__read_<owner>_<n>`; assert per-plan id uniqueness before emit (abort
      with context otherwise); for each produced domain/dataset emit `revision=1`,
      set BOTH the relational `schema_version` column AND `payload["schema_version"]` to `"1.1.0"`,
      inject `payload["domain"]`/`payload["dataset"]`, recompute fingerprint, set
      `upstream_plan_pins`, preserve `created_by`/`created_at` (do NOT regenerate — §2.6 note);
      build an in-memory `node_id → owning domain_code` map;
      (3) backfill `sdtm_acrf_annotations.links` entries with
      `target_type=="derivation_plan_node"` setting `domain` from that map (links whose node did
      not survive keep `domain=null`);
      (4) `SET NOT NULL` on `domain_code`, drop old unique constraint, add new unique constraint +
      index;
      (5) mirror (1)–(4) for ADaM;
      (6) mark affected aggregate `ValidationRun`/`ExecutionRun` rows `stale` (do not delete
      artifacts);
      (7) `downgrade()` guard: raise if any `aggregate_id` spans >1 distinct
      `domain_code`/`dataset_code`, or any row carries injected read pins (`upstream_plan_pins`
      non-empty or payload contains `sdtm_read`/`adam_read`); otherwise drop new
      columns/constraints/index and restore the old unique constraint. Legacy row with no
      `domain_write` → abort with context.
      Files: `migrations/versions/20261009_0012_per_domain_derivation_plans.py`
      Verify (empty-DB migration + split helper): add the repo integration migration test from
      item 20 and run it; also `alembic upgrade head` then `alembic downgrade -1` on the
      `clinical_test` DB succeeds for a single-domain seed and the guard raises for a multi-domain
      seed. Minimum here: `mypy` excludes `migrations`, so run
      `ruff check migrations/versions/20261009_0012_per_domain_derivation_plans.py`.

## Phase C — SDTM service layer

- [ ] 5. Add per-domain plan accessors and the all-domain gate to the SDTM service.
      Add `latest_plan(session, aggregate_id, domain_code)` (max-revision for the pair; change the
      existing single-arg `latest_plan` signature and update its one caller set),
      `list_plan_heads(session, aggregate_id) -> tuple[SdtmDerivationPlanRevision, ...]`
      (one head row per `domain_code`, ordered newest-first by `(created_at, id)`),
      `aligned_domain_plans(session, aggregate_id) -> dict[str, SdtmDerivationPlanRevision]`
      (requires every domain with a plan to be aligned with satisfied pins; raises
      `409 sdtm_plan_misaligned`/`sdtm_plan_upstream_misaligned` naming the first offender),
      `require_domain_aligned(session, aggregate_id, domain_code) -> (spec, selection, domain_plan)`
      (self state/spec/input + each pin's sibling head still at pinned revision and aligned —
      §6 step 4), and `specification_slice(specification, code)` returning the owned
      `SdtmDomain` plus `{sibling_code: variables}` (§5). Keep `require_aligned` temporarily or
      remove once all callers migrated (prefer remove; §3.4 says it is replaced).
      Files: `src/app/sdtm/service.py`
      Verify: `pytest tests/unit/test_sdtm.py -k "slice or coverage or plan"` (new/adjusted unit
      tests land in Phase F; for now `mypy src` clean and module imports).

- [ ] 6. Rewrite SDTM `lower_plan` for per-domain exact coverage and `sdtm_read` lowering (§4).
      Lower `sdtm_read → {"node_type":"read","id":...,"dataset":<domain code>}` (IR `read`; no
      transformation change). Enforce: exactly one `domain_write` and its `domain == plan.domain`
      (`422 sdtm_plan_output_duplicate` / `422 sdtm_plan_output_scope`); `plan.domain` required iff
      its spec slice has any derived variable (`422 sdtm_plan_output_coverage_missing`); restrict
      `domain_write`/`derive.target_domain` to `plan.domain`; validate `sdtm_read.dataset` is a
      declared sibling domain and `!= plan.domain` (`422 sdtm_read_target_unknown` /
      `422 sdtm_read_self`). Replace the current global subset coverage check. Accept a
      non-derived domain plan with zero writes.
      Files: `src/app/sdtm/service.py` (`lower_plan`)
      Verify: `pytest tests/unit/test_sdtm.py -k "lower or coverage or read"` after Phase F adds
      the cases; immediately `ruff`/`mypy` clean.

- [ ] 7. Implement SDTM cross-plan staleness primitives and the write-time pin model (§6).
      Add `mark_sibling_plan_change(session, aggregate_id, changed_code, reason)` — flips every
      aligned head whose `upstream_plan_pins` reference `changed_code` to `misaligned`, appends
      reason `upstream_plan_changed`, and recurses on each newly-flipped head (terminates on the
      acyclic pin DAG; idempotent on already-misaligned). Add pin resolution used at write time:
      from a plan's `sdtm_read` nodes resolve sorted/deduped
      `[{"domain_code","plan_revision"}]`, each referenced sibling must have a plan row and be
      `aligned` against the same `specification_revision` else `409 sdtm_plan_upstream_misaligned`
      (carry `upstream_state:"absent"` when no row exists — §6 step 2 + fourth-iter Finding 1).
      Add the write-time cross-plan cycle check `422 sdtm_plan_dataset_cycle` over this plan's
      `sdtm_read` targets plus the transitive closure of aligned siblings' pins (§4.1).
      Files: `src/app/sdtm/service.py`
      Verify: `mypy src`; staleness/pin unit + repo tests land in Phase F/G.

- [ ] 8. Rewrite SDTM refresh/staleness fan-out and `context_snapshot`/`read_context_dataset`
      for per-domain resolution (§3.4).
      `mark_raw_refresh`: for each affected selection loop `list_plan_heads(...)` and set each head
      `misaligned` with reason `input_changed` (not just one row), then call
      `mark_sibling_plan_change` for each flipped head. `context_snapshot`: resolve
      `aligned_domain_plans`, keep each `sdtm_dataset_xpt` artifact only if its
      `manifest["dataset"]` is a produced domain `D` and `source_plan_revision == plans[D].revision`;
      replace scalar `plan_revision`/`plan_fingerprint` with a `plan_revisions`
      `{domain_code:{plan_revision,plan_fingerprint}}` map plus a scalar `plan_set_fingerprint`
      (ordered hash of per-domain fingerprints); bump the return dict literal
      `"schema_version"` from `"1.0.0"` to `"1.1.0"` (line ~439 only; leave other `"1.0.0"`
      literals untouched — fourth-iter Finding 4). `read_context_dataset`: look up
      `latest_plan(session, sdtm_id, dataset_code)`, require that domain aligned, and change ONLY
      the plan-revision match to the per-domain revision — preserve all existing `study_id`,
      `owner_type`, `owner_id`, `artifact_type`, `status`, checksum, `input_selection_revision`
      predicates (§3.4). Keep `read_context_dataset` signature.
      Files: `src/app/sdtm/service.py`
      Verify: `mypy src`; integration coverage in Phase G (item 22).

- [ ] 9. Make SDTM `build_artifact_payload` domain-scoped and update study-level deliverable gates
      (§3.3).
      Add required keyword `domain_code` to `build_artifact_payload` for per-domain artifacts
      (XPT, programs): call `require_domain_aligned(session, aggregate_id, domain_code)`, lower only
      that domain's plan, and match the per-domain `ValidationRun` whose
      `input_manifest["domain_code"] == domain_code` and
      `input_manifest["plan_revision"] == domain_plan.revision`; set per-domain
      `source_plan_revision`. All-domain artifact builds (aCRF/Define/cSDRG) assert the aggregate
      `ValidationRun` manifest's `plan_revisions`/`plan_set_fingerprint` matches the freshly
      resolved set instead of a scalar `plan_revision`. Replace `require_aligned` with
      `aligned_domain_plans` in `_build_define_xml_payload` (~L686) and `_build_csdrg_payload`
      (~L804), iterating the returned `{domain_code: head}` map (§3.3, third-iter Finding 5).
      Files: `src/app/sdtm/service.py`
      Verify: `mypy src`; Phase G items 22/24 exercise the gates.

## Phase D — SDTM routes, aCRF, ETag/concurrency

- [ ] 10. Repath SDTM plan routes to per-domain and switch concurrency to the per-domain plan ETag
      (§3.1, Finding 9).
      Replace single-plan routes with:
      `GET/PUT /sdtms/{sdtm_id}/domains/{domain_code}/derivation-plan`,
      `POST .../domains/{domain_code}/derivation-plan/validate`,
      `POST .../domains/{domain_code}/derivation-plan/preview`,
      `GET /sdtms/{sdtm_id}/derivation-plans` (cursor-paginated head collection),
      `POST /sdtms/{sdtm_id}/domains/{domain_code}/validate` (per-domain run). Validate
      `{domain_code}` against the pattern and that it exists in the current Specification
      (`404 sdtm_domain_unknown`) and equals the body `domain` (`422 sdtm_plan_domain_mismatch`).
      `put_plan`: acquire `SELECT ... FROM sdtm_workbenches WHERE id=:aggregate_id FOR UPDATE`
      first (§6 isolation note), use `etag_for_revision(domain_plan.revision)` for ETag/If-Match
      (first write accepts absent/`*`), resolve+gate `upstream_plan_pins`, run the cycle check,
      insert the new per-`(aggregate,domain)` revision (per-domain revision counter), set
      `state="aligned"` + `alignment_reasons=[]`, call `mark_sibling_plan_change(...,
      plan.domain, "upstream_plan_changed")` for downstream readers, and STOP bumping
      `workbench.revision`. Keep `_stale_adam_consumers` on this path. Extend `PlanResponse` with
      `domain`, `alignment_state` (`aligned→current`, `misaligned→alignment_required`),
      `alignment_reasons` (echo persisted column), and read-only `upstream_plan_pins`.
      `GET .../derivation-plans` uses `common/pagination.paginate` over
      `list_plan_heads(...)` head rows (summary projected after paging).
      Files: `src/app/sdtm/routes.py`
      Verify: `pytest tests/contract/test_phase4.py` fails until the fixture is updated (item 25);
      run `mypy src` and `ruff check src/app/sdtm/routes.py` now.

- [ ] 11. Make SDTM spec/input writes misalign all domain plans and keep the workbench ETag;
      rewrite `get_lineage` and `validate_sdtm` manifests (§3.1, §3.3, §3.4).
      `_save_specification` and `put_input_selection`: keep `workbench.revision` as their own
      concurrency token (unchanged), but loop every domain head plan → `misaligned` with reason
      `specification_changed`/`input_changed` (and call `mark_sibling_plan_change` per flipped
      head), keep `_stale_adam_consumers`. `get_lineage`: resolve `aligned_domain_plans` (fail-fast
      `409` naming first misaligned domain), lower each plan, return
      `{plan_set_fingerprint, domains: {domain_code: {ir_fingerprint, outputs}}}`. Aggregate
      `validate_sdtm` (path unchanged): resolve `aligned_domain_plans`, lower every plan, write one
      aggregate `ValidationRun` whose manifest replaces scalar `plan_revision`/`plan_fingerprint`
      with `plan_revisions` map + `plan_set_fingerprint`, and `normalized_ir` as a
      `{domain_code: canonical_ir}` map. Add a per-domain `validate` route writing a run with
      `domain_code`/`plan_revision`/`plan_fingerprint`. Add the new problem codes to responses:
      `409 sdtm_plan_upstream_misaligned`, `409 sdtm_output_coverage_incomplete`,
      `422 sdtm_plan_output_scope`/`sdtm_plan_output_duplicate`/`sdtm_read_target_unknown`/
      `sdtm_read_self`/`sdtm_plan_dataset_cycle`/`sdtm_plan_domain_mismatch`,
      `404 sdtm_domain_unknown`.
      Files: `src/app/sdtm/routes.py`
      Verify: `mypy src`; contract behavior in item 25.

- [ ] 12. Make SDTM compile/artifacts/execute domain-scoped and add the whole-set orchestration
      coverage gate (§3.3).
      Thread `domain_code` through `/compile`, `/artifacts`, `/execute` and into
      `build_artifact_payload(..., domain_code=...)`; `sdtm_program_*` and XPT artifacts carry
      `manifest.domain_code` and per-domain `source_plan_revision`. The "build whole SDTM set"
      orchestration loops `aligned_domain_plans` and fails fast
      `409 sdtm_plan_misaligned`/`sdtm_plan_upstream_misaligned`; the collective coverage check
      computes `derived_domains` from the Specification and fails
      `409 sdtm_output_coverage_incomplete {missing_domains}` for any never-authored derived domain.
      Record resolved upstream artifacts for `sdtm_read` in the execution manifest (§6 step 4).
      Files: `src/app/sdtm/routes.py` (and the artifact-build worker path it calls, if the loop
      lives there — follow existing `create_artifact_build` flow)
      Verify: `mypy src`; Phase G item 24 exercises per-domain build + whole-set failure.

- [ ] 13. Key SDTM aCRF plan-node resolution on `(aggregate_id, domain_code, revision)` (§2.5, §7).
      In `acrf.py` link validation (~L230): look up the plan by
      `(aggregate_id, domain_code == link.domain, revision == link.plan_revision)`; a link with
      `domain is None` after backfill → `acrf_plan_node_unresolved`. In aCRF coverage (~L457):
      resolve each domain's head plan via `latest_plan(..., link.domain)` and count links not
      pointing at their domain's head as `noncurrent` (replace the single aggregate max-revision
      plan comparison). Update `AcrfCoverageResponse.plan_revision` handling as needed (it now has
      no single plan — report per-domain or drop the scalar; follow the design's "links not pointing
      at their domain's current head" semantics).
      Files: `src/app/sdtm/acrf.py`
      Verify: `pytest tests/unit/test_sdtm.py -k acrf` after item 23; `mypy src` now.

## Phase E — ADaM service + routes (mirror SDTM)

- [ ] 14. Add per-dataset accessors/gate/slice to the ADaM service (mirror of items 5 + 7).
      Add `latest_plan(session, aggregate_id, dataset_code)`, `list_plan_heads`,
      `aligned_dataset_plans`, `require_dataset_aligned`, `specification_slice`,
      `mark_sibling_plan_change`, per-dataset `upstream_plan_pins` resolution with the write-time
      sibling-alignment gate (`409 adam_plan_upstream_misaligned`, including
      `upstream_state:"absent"`), and the cross-plan cycle check (`adam_plan_dataset_cycle`).
      Files: `src/app/adam/service.py`
      Verify: `mypy src`; unit/repo coverage in Phases F/G.

- [ ] 15. Rework ADaM `lower_plan` cross-dataset reads and remove the in-plan predecessor rule
      (§4.1).
      `adam_read.dataset` must be a declared sibling dataset `!= plan.dataset`
      (`422 adam_read_target_unknown` / `adam_read_self`), resolving to that dataset's variables
      from the spec sub-slice (as `source_kind="adam"` origins already do); lowering stays
      `adam_read → select(predecessor variables)`. Remove the in-plan
      `adam_plan_predecessor_output_missing`/`adam_plan_predecessor_edge_missing` checks in
      `_validate_dataset_dependencies` and move acyclicity to the cross-plan write-time check from
      item 14. Keep per-dataset coverage: exactly one `dataset_write` of `plan.dataset`
      (`adam_plan_output_duplicate`) and `output_node_id` lineage scoped to that dataset's variables
      (`adam_plan_variable_lineage_missing`).
      Files: `src/app/adam/service.py` (`lower_plan`, `_validate_dataset_dependencies`)
      Verify: `pytest tests/unit/test_adam.py -k "lower or read or dependency"` after Phase F;
      `mypy src` now.

- [ ] 16. Rewrite ADaM refresh fan-out and per-dataset build (mirror items 8 + 9).
      `mark_sdtm_refresh`: loop all dataset head plans → `misaligned` reason `input_changed` and
      recurse via `mark_sibling_plan_change`. Add `build_artifact_payload(..., dataset_code=...)`
      with per-dataset validation lookup; `adam_program_*` become per-dataset with
      `manifest.dataset_code`. Replace `require_aligned` with `aligned_dataset_plans` in
      `_build_adrg_payload` (~L585) and iterate the returned map.
      Files: `src/app/adam/service.py`
      Verify: `mypy src`; Phase G.

- [ ] 17. Repath ADaM routes to per-dataset with the per-dataset ETag and update the SDTM input
      binding + lineage (§3.2, §3.4 third-iter Finding 10).
      Replace single-plan routes with
      `GET/PUT /adams/{adam_id}/datasets/{dataset_code}/derivation-plan`,
      `.../derivation-plan/validate`, `.../derivation-plan/preview`,
      `GET /adams/{adam_id}/derivation-plans`, and `GET /adams/{adam_id}/lineage` (map shape).
      `put_plan`: `AdamWorkbench ... FOR UPDATE` first, per-dataset ETag, pin resolve+gate+cycle,
      per-`(aggregate,dataset)` revision, `alignment_reasons` handling, stop bumping
      `workbench.revision`. Spec/input writes misalign all dataset heads. Thread `dataset_code`
      through validate/compile/artifacts/execute. Aggregate `validate_adam` manifest carries
      `plan_revisions` + `plan_set_fingerprint`. Update the SDTM-input binding at `routes.py` ~L269
      from `manifest.get("plan_revision") != context["plan_revision"]` to
      `manifest.get("plan_set_fingerprint") != context["plan_set_fingerprint"]`. Extend the ADaM
      plan response with `dataset`/`alignment_state`/`alignment_reasons`/`upstream_plan_pins`. Add
      `409 adam_plan_upstream_misaligned`, `409 adam_output_coverage_incomplete`, matching `422`/
      `404` codes.
      Files: `src/app/adam/routes.py`
      Verify: `pytest tests/contract/test_phase4.py` fails until item 25; `mypy src`,
      `ruff check src/app/adam/routes.py` now.

## Phase F — Unit + property tests (no DB)

- [ ] 18. Add/adjust SDTM unit tests (design §10 Unit + Property).
      Cover: `SdtmReadNode` acceptance; `sdtm_read_self`/`sdtm_read_target_unknown`;
      per-domain exact coverage (`sdtm_plan_output_scope`, `sdtm_plan_output_duplicate`,
      `sdtm_plan_output_coverage_missing`, non-derived zero-write acceptance);
      lowering `sdtm_read → read` and `domain_write → write` restricted to the plan's domain;
      `specification_slice` returns target + sibling variable map; `schema_version == "1.1.0"` and
      required `domain`; response `alignment_state`/`alignment_reasons` mapping incl.
      `upstream_plan_changed`. Property: `domain_code` pattern, DAG/ports/edges for plans with
      `sdtm_read`, `upstream_plan_pins` canonical ordering/dedup, and migration split determinism
      over randomized legacy DAGs including a seeded legacy `__read_`-prefixed node (injected read
      gets a non-colliding id). Update existing assertions that expected `"1.0.0"`/old coverage.
      Do not add unrelated tests.
      Files: `tests/unit/test_sdtm.py`
      Verify: `pytest tests/unit/test_sdtm.py` passes; `ruff check tests/unit/test_sdtm.py`.

- [ ] 19. Add/adjust ADaM unit tests (mirror item 18).
      Cover: `adam_read` cross-dataset resolution against the spec sub-slice; removal of the
      in-plan predecessor-edge requirement; cross-plan cycle via pins; per-dataset coverage +
      `output_node_id` lineage scoped to the dataset; `schema_version == "1.1.0"` + required
      `dataset`. Also the never-authored-sibling unit case: a `PUT` whose `adam_read.dataset` names
      a Specification-declared sibling with no plan row is rejected
      `409 adam_plan_upstream_misaligned` `upstream_state:"absent"`, then succeeds after the sibling
      is authored and aligned (place in unit if pure, else the repo test item 21). Update the
      `tests/unit/test_adam.py` ~L421 fixture that asserted scalar `plan_revision` to
      `plan_set_fingerprint`.
      Files: `tests/unit/test_adam.py`
      Verify: `pytest tests/unit/test_adam.py` passes; `ruff check tests/unit/test_adam.py`.

## Phase G — Repository / integration / conformance / traceability tests (DB)

Prereq for every item below: migrated `clinical_test` DB + `AURINARA_INTEGRATION=1` + Compose
Postgres/MinIO (see "Verification tooling"). These tests MUST apply migrations from an empty DB.

- [ ] 20. Migration `0012` repository test — split-backfill from an empty DB.
      Seed a legacy single-plan SDTM row (spanning ≥2 domains, a shared `raw_read`, and a legacy
      cross-domain edge), apply `alembic upgrade head` from empty, assert: per-domain rows with
      correct `domain_code`/`domain`/`schema_version="1.1.0"` (column AND payload), injected
      `sdtm_read` + `upstream_plan_pins` on the non-owner, preserved node ids + shared
      `created_at`/`created_by`, `AcrfPlanNodeLink.domain` backfilled, affected
      `ValidationRun`/`ExecutionRun` marked `stale`; guarded `downgrade` raises on a multi-domain
      aggregate and succeeds on a single-domain one. Mirror a smaller ADaM assertion.
      Files: `tests/integration/` (new `test_phase5_per_domain_migration.py` or extend an existing
      phase file following its fixture pattern)
      Verify: `$env:AURINARA_INTEGRATION="1"; pytest tests/integration/test_phase5_per_domain_migration.py`.

- [ ] 21. Repository tests for keys, revisions, staleness fan-out, and the alignment invariant.
      Per-`(aggregate,domain)`/`(aggregate,dataset)` uniqueness; per-domain revision counter;
      `upstream_plan_pins`/`alignment_reasons` JSONB round-trip; spec/input/refresh marks EVERY
      head `misaligned` with the correct reason (all five SDTM+ADaM call sites); the invariant
      `alignment_reasons` empty iff `state=="aligned"` after every write path incl. the transitive
      chain A→B→C; transitive staleness: new revision of C flips B then recurses to A
      (`upstream_plan_changed`) in one transaction, `GET A` reports `alignment_required`; diamond
      termination (A pins B and C; both pin D); pin-to-never-authored-sibling `409`
      `upstream_state:"absent"` then success; aggregate-row `FOR UPDATE` serializes two concurrent
      `put_plan`s so A never pins a superseded B revision.
      Files: `tests/integration/` (extend the migration/per-domain phase file)
      Verify: `$env:AURINARA_INTEGRATION="1"; pytest tests/integration -k "per_domain or stale or pin or lock"`.

- [ ] 22. Repository tests for `context_snapshot`/`read_context_dataset` + ADaM-from-SDTM binding.
      `context_snapshot` returns per-domain XPTs matched to each domain's aligned plan revision plus
      `plan_set_fingerprint` and `schema_version=="1.1.0"`; `read_context_dataset` resolves the
      per-domain plan and preserves all ownership predicates. ADaM input-selection acceptance
      matches the SDTM context `plan_set_fingerprint` against the aggregate SDTM `ValidationRun`
      manifest; changing any single SDTM domain's plan changes the fingerprint and invalidates a
      stale ADaM selection with `422 adam_sdtm_validation_invalid`. Update
      `tests/integration/test_phase4_adam.py` ~L236 fixture from scalar `plan_revision` to
      `plan_set_fingerprint`.
      Files: `tests/integration/test_phase4_adam.py` (+ the per-domain phase file)
      Verify: `$env:AURINARA_INTEGRATION="1"; pytest tests/integration/test_phase4_adam.py`.

- [ ] 23. aCRF plan-node resolution + pagination repository tests.
      With per-domain revisions sharing numbers across domains, `acrf.py` link validation and
      coverage resolve by `(aggregate_id, domain_code, revision)`; a legacy null-`domain` link is
      reported `acrf_plan_node_unresolved` (not silently matched). `GET .../derivation-plans`
      cursor stability: head rows sharing a `created_at` are paged without skip/repeat with `id`
      tie-break; paged records are the actual head rows.
      Files: `tests/integration/` (per-domain phase file)
      Verify: `$env:AURINARA_INTEGRATION="1"; pytest tests/integration -k "acrf or pagination or derivation_plans"`.

- [ ] 24. All-domain deliverable gate + per-domain build repository tests.
      Define-XML/cSDRG (and ADaM ADRG) build fails `409` naming the first misaligned domain and
      succeeds only when `aligned_domain_plans` returns every produced domain aligned and the
      aggregate `ValidationRun` manifest `plan_revisions`/`plan_set_fingerprint` matches; a single
      domain builds while a sibling is misaligned; whole-set build fails naming the first offender;
      `sdtm_output_coverage_incomplete` fires for a never-authored derived domain.
      Files: `tests/integration/` (per-domain phase file)
      Verify: `$env:AURINARA_INTEGRATION="1"; pytest tests/integration -k "deliverable or build or coverage"`.

- [ ] 25. Contract/OpenAPI tests + typed-client fixture update.
      Update `tests/contract/typed_client_fixture.py`: replace the SDTM single-plan entries
      (`/sdtms/{sdtm_id}/derivation-plan`, `.../derivation-plan/preview`) with the domain-scoped
      routes, `GET /sdtms/{sdtm_id}/derivation-plans`, and
      `POST /sdtms/{sdtm_id}/domains/{domain_code}/validate`; mirror the ADaM entries under
      `/datasets/{dataset_code}/...` plus `GET /adams/{adam_id}/derivation-plans`. Add contract
      assertions for the new routes, per-domain ETag/If-Match (first-write `*`/absent;
      spec-change-doesn't-change-plan-ETag), `404 sdtm_domain_unknown`,
      `422 sdtm_plan_domain_mismatch`, `409 sdtm_plan_upstream_misaligned`/
      `adam_plan_upstream_misaligned`, `409 sdtm_output_coverage_incomplete`, the three-value
      `alignment_reasons`, and the `GET /lineage` map shape
      `{plan_set_fingerprint, domains:{...}}`.
      Files: `tests/contract/typed_client_fixture.py`, `tests/contract/test_phase4.py`
      Verify: `pytest tests/contract` passes (the fixture-vs-OpenAPI test is authoritative).

- [ ] 26. Conformance + traceability tests.
      Conformance: a canonical per-domain SDTM plan set with a cross-domain `sdtm_read` (e.g. a
      SUPP-style read) produces equivalent normalized Python/R results and a deterministic SAS
      program from the same IR, with the upstream artifact pinned by `upstream_plan_pins`.
      Traceability: `CRF annotation → Raw var → SDTM plan node (per-domain) → SDTM var → ADaM plan
      node (per-dataset) → derived var` resolves end to end with `AcrfPlanNodeLink.domain` present,
      and a legacy null-domain link is flagged, not crashing.
      Files: `tests/conformance/` (extend existing SDTM conformance), `tests/integration/` or
      `tests/e2e/` for the traceability chain following existing patterns.
      Verify: `$env:AURINARA_INTEGRATION="1"; pytest tests/conformance tests/integration -k "conformance or trace"`.

## Phase H — Documentation + AGENTS.md (same change)

- [ ] 27. Correct AGENTS.md and the authoritative docs to per-domain/per-dataset (design §9).
      AGENTS.md "Compilation and execution" + "Architecture" ownership paragraphs: SDTM owns one
      Specification (all domains) plus one Derivation Plan **per domain**; ADaM per **dataset**;
      note `sdtm_read` resolved through the Specification with cross-domain staleness via
      server-resolved upstream-plan pins (no new external input pin, pin requires sibling aligned
      first); the Derivation Plan node now lives in a per-domain/per-dataset plan for the
      traceability chain. `docs/api-contract.md` §4.7: rewrite the plan envelope to the actual
      shape (stored vs response-only fields), state SDTM coverage at the dataset level, resolve the
      "common envelope"/`module` claim with an explicit Deferred note, rewrite the
      concurrency/alignment-parity sentence (per-domain/per-dataset ETag distinct from
      `workbench.revision`), reconcile `derivation_plan_alignment_required` →
      implemented codes + new `sdtm_plan_upstream_misaligned`, and set the `alignment_reasons`
      enumeration to the three values empty-iff-current. §9.3/§10.3: domain-/dataset-scoped routes,
      collection + per-domain validate routes, aggregate-vs-per-domain validation manifests, and
      the `/lineage` map shape. `docs/architecture.md` §7.x/§12.1/§12.2: third workbench part is
      per-domain/dataset; traceability prose. `docs/artifact-catalog.md`:
      `sdtm/adam_derivation_plan_json` and `*_program_*` become per-domain/dataset with
      `source_plan_revision`/`manifest.domain_code`/`dataset_code`, and note split recomputes
      fingerprints (stale artifacts retained, rejected from new packages).
      `docs/implementation-plan.md` §5.3/§6.3 + the ten E2E scenarios (per-domain wording + an
      upstream-staleness assertion; no scenario removed). `docs/local-development.md`: only update
      example curl paths to `/domains/{domain_code}/derivation-plan` (verification commands
      unchanged).
      Files: `AGENTS.md`, `docs/api-contract.md`, `docs/architecture.md`,
      `docs/artifact-catalog.md`, `docs/implementation-plan.md`, `docs/local-development.md`
      Verify: `ruff format --check .` unaffected; re-read each edited section to confirm no residual
      one-plan wording; no code impact.

## Phase I — Full-suite gate

- [ ] 28. Run the whole quality gate and the full test matrix; fix any fallout.
      Files: (fixes as needed across the above)
      Verify: `ruff check .` and `ruff format --check .` clean; `mypy src workers` clean;
      `pytest tests/unit tests/contract` green; with the migrated `clinical_test` DB and
      `AURINARA_INTEGRATION=1`, `pytest tests/integration tests/conformance` green; migrations
      upgrade a clean DB (`alembic upgrade head`) and the guarded downgrade behaves per item 20.
      Review the ten E2E scenarios in `docs/implementation-plan.md` and run `pytest tests/e2e`
      for the scenarios touched, confirming an upstream-domain plan change stales only its
      downstream readers and blocks their compile/package until realigned.

## Notes / assumptions

- No `transformation/` contract change: IR already has `read`/`write`/`select` nodes
  (`src/app/transformation/contracts.py`), so `sdtm_read` lowers to the existing `read` node; add
  only a lowering/compiler code comment documenting that a `read` dataset name may be a Raw code or
  a produced SDTM/ADaM domain/dataset code (design §4, §7).
- Kernel descriptors are unchanged: `source_plan_types` stays `("sdtm_derivation_plan",)` /
  `("adam_derivation_plan",)` and prefixes stay `/api/v1/sdtms` /`/api/v1/adams`; the new
  sub-routes live under the existing prefixes (design §7). If startup conflict checks or a
  descriptor-registry test exist, confirm they still pass — no edit expected beyond that
  confirmation.
- `require_aligned` is replaced, not kept: migrate every caller to `aligned_domain_plans`
  (study-level) or `require_domain_aligned` (domain-scoped) before deleting it, so the tree stays
  importable at each step.
- Integration tests assume a pre-migrated `clinical_test` schema (fixtures only TRUNCATE); the
  `0012` migration test (item 20) is the one that applies migrations from empty — follow its
  existing `create_database_engine`/alembic pattern in `tests/integration`.
