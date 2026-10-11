# Per-Domain SDTM / Per-Dataset ADaM Derivation Plans — Landing Report

## Outcome

The `per-domain-derivation-plan` work was rebased onto and fast-forwarded into `master`.

- Rebase of `per-domain-derivation-plan` onto `master`: no-op (branch was already based on master's tip `441ec49`).
- Fast-forward: **succeeded** (`441ec49..d7cf6c3`, ff-only, no merge commit).
- Final `master` commit SHA: **`d7cf6c3e1f7fc3d70ede537b31d7b14ce6ee9c84`**.
- The worktree and the `per-domain-derivation-plan` branch were left in place (not deleted), as instructed.

The commit landed as a single feature commit:

> `d7cf6c3 feat: per-domain SDTM / per-dataset ADaM derivation plans`

## What landed on master

### Per-domain / per-dataset model
- SDTM keeps **one Specification for all domains** but now has **one Derivation Plan per domain**, each a typed raw-to-domain DAG that produces only its own domain.
- ADaM keeps **one Specification for all datasets** but now has **one Derivation Plan per dataset**, each a typed SDTM/predecessor-to-analysis DAG that produces only its own dataset.
- Each per-domain/per-dataset plan is keyed by `(aggregate, domain/dataset, revision)`, pins `specification_revision` and `input_selection_revision`, and additionally pins server-resolved `upstream_plan_pins` (the exact sibling plan revisions it reads). A read may only pin a sibling that is already authored and aligned.
- Staleness: a Specification or input-selection change misaligns every affected plan; a sibling-plan change transitively misaligns the plans that read it (reason `upstream_plan_changed`). Staleness never rewrites a plan or silently rebinds identifiers. Per-target ETags were added.

### New read nodes
- **`sdtm_read`** (SDTM): lets a domain plan read other produced SDTM domains, resolved against the single SDTM Specification — no new external input pin; the Raw input selection stays the only external pin. Self-reads are rejected (`sdtm_read_self`: read own domain rows via `raw_read`).
- **`adam_read`** (ADaM): lets a dataset plan read predecessor ADaM datasets, resolved against the single ADaM Specification. Self-reads are rejected (`adam_read_self`); unknown targets rejected (`adam_read_target_unknown`).
- Both node contracts added in `src/app/sdtm/contracts.py` and `src/app/adam/contracts.py` as `Literal` node types.

### Collective output-coverage gate
- `require_output_coverage` added on both modules, invoked from every all-domain/all-dataset deliverable (aCRF / Define / cSDRG / ADRG).
- Raises `409 sdtm_output_coverage_incomplete {missing_domains}` / `409 adam_output_coverage_incomplete {missing_datasets}` when a derived target was never authored.

### Migration 0012
- `migrations/versions/20261009_0012_per_domain_derivation_plans.py` deterministically splits legacy single all-domains/all-datasets plans into per-domain/per-dataset plans.
- Drops the old `(aggregate_id, revision)` unique constraint **before** the split so a real multi-target legacy row does not fail with a unique violation at `revision=1`.
- Emits `alignment_reasons=['specification_changed']` for legacy misaligned rows (design 2.3 invariant: empty iff aligned).

### AGENTS.md and docs corrections
- `AGENTS.md`: rewrote the `transformation`/ownership paragraph and the Compilation/execution bullets to describe one Specification + per-domain/per-dataset plans, the `sdtm_read`/`adam_read` nodes, `upstream_plan_pins`, transitive `upstream_plan_changed` staleness, and the build/packaging coverage enforcement.
- `docs/api-contract.md`: sections 4.7 / 9.3 / 10.3 and route lists updated to per-domain/per-dataset.
- `docs/architecture.md`, `docs/artifact-catalog.md`, `docs/implementation-plan.md` (scenarios 3/4/7) updated for consistency.

### Tests added
- `tests/integration/test_phase5_output_coverage.py` — collective coverage gate (missing-domain/dataset 409s).
- `tests/integration/test_phase5_migration_reason.py` — migration emits `specification_changed` alignment reason for legacy misaligned rows.
- Expanded `tests/unit/test_sdtm.py` and `tests/unit/test_adam.py`, plus updates to `tests/integration/test_phase3_raw_sdtm.py`, `tests/integration/test_phase4_adam.py`, and `tests/contract/typed_client_fixture.py`.

## Verification

Narrowest relevant tests re-run from the worktree after rebase (fast domain/validator suites for the changed modules), using the worktree's `.venv` (Python 3.13):

```
pytest tests/unit/test_sdtm.py tests/unit/test_adam.py  ->  29 passed
```

The authored feature commit additionally records the full pre-merge verification run (uv tooling per `pyproject.toml` / `docs/local-development.md`):
- `ruff check .` clean; `ruff format --check .` clean (287 files)
- `mypy src workers` clean (154 files)
- `alembic upgrade head` on a fresh database → head `20261009_0012`
- `pytest tests/unit tests/contract` → 213 passed
- `AURINARA_INTEGRATION=1` full suite → 243 passed, 5 skipped (runner-image tests requiring `AURINARA_RUNNER_INTEGRATION`)

## Working tree note
The main workspace on `master` had unrelated uncommitted changes before the merge (`src/app/config.py`, `frontend/src/components/workbench/plan-graph/derivation-plan-graph.tsx`, and untracked `.agents/tasks/...` dirs). None overlap the fast-forwarded fileset, so the ff-only merge preserved them intact.
