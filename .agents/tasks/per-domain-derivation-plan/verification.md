# Verification — Per-Domain SDTM / Per-Dataset ADaM Derivation Plans

Iteration: review follow-up (addresses the four findings in `review.json` /
`review.md`, verdict `CHANGES_REQUESTED`). All work on branch
`per-domain-derivation-plan` in the worktree
`e:\Work\EDETEK\Python\aurinara\.worktrees\per-domain-derivation-plan`.

## Findings addressed

1. **Verification evidence missing (blocking)** — produced this record and ran the
   repo's declared tooling (see Commands below). Work is committed on the branch.

2. **Collective output-coverage gate not implemented (blocking)** — added
   `SdtmCapability.require_output_coverage` (`src/app/sdtm/service.py`) and
   `AdamCapability.require_output_coverage` (`src/app/adam/service.py`). Each computes
   the derived target set from the current Specification
   (`any(variable.derived ...)` for SDTM; `any(origin_type == "Derived" ...)` for ADaM)
   and compares it against the authored, aligned plan heads, raising
   `409 sdtm_output_coverage_incomplete {missing_domains}` /
   `409 adam_output_coverage_incomplete {missing_datasets}` for any derived target that
   was never authored. The gate is invoked from every all-domain/all-dataset deliverable
   that resolves `aligned_domain_plans`/`aligned_dataset_plans`:
   - SDTM: `sdtm_acrf` branch of `build_artifact_payload`, `_build_define_xml_payload`,
     `_build_csdrg_payload`.
   - ADaM: `_build_define_xml_payload` (all-dataset Define), `_build_adrg_payload`.
   New tests: `tests/integration/test_phase5_output_coverage.py` (SDTM + ADaM: a derived
   target with no plan row is reported as missing; the gate passes once both are
   authored).

3. **AGENTS.md and docs not corrected (blocking)** — updated:
   - `AGENTS.md`: product-boundaries/architecture ownership and the
     "Compilation and execution" bullets now say SDTM owns one plan per domain and ADaM
     one per dataset, keyed by `(aggregate, target, revision)`, with `sdtm_read`/`adam_read`
     resolved through the Specification, server-resolved `upstream_plan_pins`, transitive
     `upstream_plan_changed` staleness, and the collective coverage invariant.
   - `docs/api-contract.md`: §4.7 rewritten to the real stored/response envelope
     (`domain`/`dataset`, `state`/`alignment_state`/`alignment_reasons`, `nodes`/`edges`,
     read-only `upstream_plan_pins`; `module`/`outputs`/`assertions` explicitly deferred;
     dataset-level single-producer rule). §9.3/§10.3 and route lists repathed to the
     per-domain/per-dataset routes plus the `derivation-plans` collection and per-target
     validate routes, preserving `/api/v1`, cursor pagination, If-Match/ETag, idempotency,
     problem+json, 409 stale/alignment/upstream/coverage, 422 invalid clinical content.
   - `docs/architecture.md`: three-part workbench prose, §12.2 authoring-contract prose,
     and the traceability-chain note (plan nodes resolve inside per-target plans with an
     aCRF `domain`).
   - `docs/artifact-catalog.md`: derivation-plan and program rows are per-domain/per-dataset
     with `manifest.domain_code`/`dataset_code` and per-target `source_plan_revision`; split
     recomputes fingerprints (stale artifacts retained, rejected from new packages).
   - `docs/implementation-plan.md`: §5.3/§6.3 per-target wording and E2E scenarios 3/4/7
     updated with per-target authoring, the coverage gate, and an upstream-staleness
     assertion (no scenario removed).
   - `docs/local-development.md`: no curl examples referenced the single-plan routes;
     verification commands are unchanged.

4. **Migration writes `[]` reasons for legacy misaligned rows (minor)** — in
   `migrations/versions/20261009_0012_per_domain_derivation_plans.py` the split now emits
   `alignment_reasons = ["specification_changed"]` (not `[]`) for sub-rows carried over
   from a `misaligned` legacy row, preserving the design 2.3 invariant
   "`alignment_reasons` empty iff `state == aligned`". New test:
   `tests/integration/test_phase5_migration_reason.py`.

## Additional defect found and fixed during verification

- **Migration unique-constraint ordering bug** — the `0012` upgrade split a legacy
  multi-domain/multi-dataset plan into N rows all at `revision = 1` *before* dropping the
  old `(aggregate_id, revision)` unique constraint, so a real multi-target legacy row
  would fail the split with a unique-violation. (It passed earlier only because the test
  DB had no plan rows.) Fixed by dropping `uq_sdtm_plan_aggregate_revision` /
  `uq_adam_plan_aggregate_revision` *before* `_split_table` and adding the per-target
  unique constraint after. Caught by `test_phase5_migration_reason.py`.

- **Phase 3 integration test wiring** — the per-domain rewrite left the SAS `/execute`
  call bound to the aggregate validation run while the per-domain SAS program binds the
  per-domain run, causing `409 execution_provenance_mismatch`. Updated the SAS execute to
  use `domain_validation` (consistent with the already-updated Python execute).

## Commands run (worktree root; tooling from pyproject.toml / docs/local-development.md)

Environment: `uv` (0.11.29) managed venv, Python 3.13. Compose Postgres on
`localhost:55432` and MinIO on `localhost:9000` already running.

- `uv run ruff check .` → All checks passed.
- `uv run ruff format --check .` → 287 files already formatted (green).
- `uv run mypy src workers` → Success: no issues found in 154 source files.
- Clean-DB migration: dropped/recreated `clinical_test`, `uv run alembic upgrade head`
  with `DATABASE_URL` → `clinical_test`; head confirmed `20261009_0012`.
- `uv run pytest tests/unit tests/contract` → 213 passed.
- `AURINARA_INTEGRATION=1 uv run pytest tests/unit tests/contract tests/integration tests/conformance`
  → 243 passed, 5 skipped (the 5 skips are `tests/integration/test_execution_runners.py`,
  which require `AURINARA_RUNNER_INTEGRATION=1` and built runner images).
- `tests/e2e` contains no collected tests (the ten scenarios live in the phase
  integration tests); `uv run pytest tests/e2e` → no tests ran.

## Notes / out-of-scope items

- `ruff format` also reformatted three files that carried pre-existing drift from the
  base merge commit (`441ec49`), unrelated to this change:
  `src/app/adam/define.py`, `src/app/kernel/traceability.py`, and the other task's
  `.agents/tasks/typed-expression-expansion/design.md`. These were already failing
  `ruff format --check` at the base commit; they were reformatted (cosmetic only, no
  behavioral change) so the project-wide quality gate passes.
- Runner-isolation tests (network denial, non-root, timeouts, cleanup) remain skipped
  here because they require building both runner images; they are unchanged by this work.
