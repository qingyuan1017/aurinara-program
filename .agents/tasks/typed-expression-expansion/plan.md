# Implementation Plan — Typed Expression Expansion (Conditional + Function Catalog)

Authoritative design: `.agents/tasks/typed-expression-expansion/design.md` (§3, §4, §4.3, §4.5, §4.6, §5–§10, §14 D1–D11). Implement it EXACTLY. The free-text/arbitrary-expression alternative in §13 is REJECTED and must NOT appear anywhere in contract, evaluator, codegen, validation, or frontend. All work targets the worktree `e:\Work\EDETEK\Python\aurinara\.worktrees\typed-expr`.

## Scope, environment, and migration facts (verified during exploration)

- **No Alembic migration is required.** The IR is a JSONB payload (`DeriveNode` is a Pydantic/JSONB contract, not a table). SDTM Derivation Plans persist their payload in `sdtm_derivation_plan_revisions.payload` (JSONB) and validation runs persist issues in `validation_runs.issues` (JSONB). No new tables or columns. The additive `result_types` field lives inside the JSONB IR only. State this explicitly in the coder's work and add NO migration.
- **OpenAPI widening is additive (D6): no `/api/v1` version bump.** New `kind`s and the `FunctionName` enum widen the `Expression` schema. Contract tests and the generated typed-client fixture MUST be updated and `npm run api:sync` re-run.
- **Toolchain (verified):** `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src` all work in the worktree after `uv sync --extra dev`. `Rscript` (R 4.3.2), `node`, `uv` are on PATH, so conformance can execute BOTH Python (via `sys.executable`/`uv run python`) and R (via `Rscript`) in-process (the existing Docker-runner path in `tests/integration/test_execution_runners.py` is NOT required for conformance here).
- **Compiler banner:** `compile_dataflow` reports version `"1.4.0"` and each codegen banner reads `compiler=1.4.0` (`src/app/transformation/service.py`, `codegen.py` python/r/sas sources). Design §7/§9 says bump the banner with the new operator set. Bump banner + `CompiledProgram.compiler_version` to `"1.5.0"` consistently in Phase 1 (keep stable across Phase 2 unless a further operator bump is warranted — see "needs verification").
- **`operator_version` bump:** `DataflowIR.operator_version` is a `Literal["1.1.0"]` default `"1.1.0"` (`contracts.py`). Change to `Literal["1.2.0"] = "1.2.0"`. `schema_version` stays `Literal["1.0.0"]`.

### IMPORTANT pre-work finding (needs verification during implementation)

`frontend/src/components/workbench/plan-graph/expression-builder.tsx` is **UNTRACKED in the main workspace and ABSENT from the worktree** (confirmed: `git ls-files` lists only `-derivation-plan-graph.test.tsx`; the builder shows as `??` in main). The design and task reference it as if it exists. **The frontend coder MUST first copy the current builder into the worktree** from `e:\Work\EDETEK\Python\aurinara\frontend\src\components\workbench\plan-graph\expression-builder.tsx` (it already implements the recursive `ExpressionBuilder`, `KIND_OPTIONS`, `defaultExpression`, `AssignmentList`, and the free-text-free invariant), confirm it compiles against the worktree's generated model, and only then extend it. Verify in-context whether any component that imports it (e.g. a derive inspector) is also untracked and must be brought over for `tsc --noEmit` to pass.

### Frontend test-runner finding (needs verification during implementation)

The frontend has `.test.tsx` files (e.g. `plan-graph/-derivation-plan-graph.test.tsx`) but **vitest is NOT installed and there is NO `test` script** in `frontend/package.json`, and `vite.config.ts` declares no `test` block. The frontend coder MUST stand up a runnable test setup to satisfy the "frontend component tests" requirement: add `vitest` + `@testing-library/react` + `@testing-library/jsdom`/`jsdom` + `@testing-library/user-event` to devDependencies, add a `test` script (`vitest run`), and add a `test` config to `vite.config.ts` (jsdom environment, globals). Verify the existing `.test.tsx` files run (or are intentionally renamed with the `-` prefix that excludes them). Treat exact versions as pinned-latest-compatible and verify they install.

## Phase 1 — Conditional expression (design §3, §5, §7, §10, §14 D1/D2/D3)

- [ ] 1. Add the conditional contract to the shared typed Expression union and bump the operator set.
      In `src/app/transformation/contracts.py`: add `ConditionalBranch(StrictModel){when: Expression; then: Expression}` and `ConditionalExpression(StrictModel){kind: Literal["conditional"]; branches: tuple[ConditionalBranch, ...] = Field(min_length=1); otherwise: Expression}`; add `ConditionalExpression` to the `Expression = Annotated[... , Field(discriminator="kind")]` union (keep the forward-ref strings; call `model_rebuild()` only if Pydantic requires it — verify). Add optional additive `result_types: dict[str, Literal["character","numeric"]] = Field(default_factory=dict)` to IR `DeriveNode`. Change `DataflowIR.operator_version` to `Literal["1.2.0"] = "1.2.0"`; keep `schema_version` `Literal["1.0.0"]`.
      Files: `src/app/transformation/contracts.py`
      Verify: `uv run pytest tests/unit/test_transformation.py tests/unit/test_transformation_evaluator.py -q` passes; add a contract round-trip assertion in step 7 that an old IR payload WITHOUT `result_types` still validates (backward compat).

- [ ] 2. Evaluator conditional branch (design §5, D1).
      In `src/app/transformation/evaluator.py` `_value`: add `kind == "conditional"` — iterate `branches`, compute `cond = _value(branch.when, row)`; the first branch with `cond is not None and bool(cond)` returns `_value(branch.then, row)`; after the loop return `_value(expression.otherwise, row)` (null-`when` = not matched; short-circuit: do not evaluate later/unmatched `then`). D1: arithmetic/type errors (ZeroDivisionError/TypeError) raised while evaluating `when`/`then`/`otherwise` **inside a conditional** resolve to null instead of raising — scope this swallowing to the conditional branch only; a bare `derive` keeps raising `preview_expression_type_invalid`. Do NOT swallow `preview_column_unknown`.
      Files: `src/app/transformation/evaluator.py`
      Verify: `uv run pytest tests/unit/test_transformation_evaluator.py -q`.

- [ ] 3. Three-backend codegen for conditional (design §3.4, §7, D1/D2).
      In `src/app/transformation/codegen.py`: bump the three banners and `compiler=` to `1.5.0`.
      - `_py_expr`: right-fold nested ternary, innermost = `otherwise`; guard each branch `((then) if (_cond is not None and bool(_cond)) else (inner))`; implement D1 by wrapping branch arithmetic so errors yield None (emit a small `conditional_value`/guarded helper in `python_source` preamble, OR inline a try/except-free null-guard — choose the approach that keeps the generated program deterministic and short; document the choice).
      - `_r_expr`: right-folded `ifelse(cond & !is.na(cond), then, inner)`; implement D1 so per-branch arithmetic errors (e.g. div-by-zero producing `Inf`/`NaN`, bad coercion → `NA`) normalize to `NA` to match Python (emit explicit guards; do NOT rely on `ifelse` short-circuit, which does not exist).
      - `_sas_expr`: lower a conditional via `IFC` (character) / `IFN` (numeric), chosen from the derive node's `result_types[target]` (D2). The conditional is lowered inside a `derive` assignment, so `_sas_expr`/`sas_source` must thread the per-assignment result type to the conditional lowerer. When a conditional-valued assignment has no `result_types` entry, raise `UnsupportedOperator` (which `compile_dataflow` maps to `BackendCapabilityMissing`) — never guess. Right-fold nested `IFC`/`IFN`; implement D1 by guarding arithmetic to missing (`.`).
      Files: `src/app/transformation/codegen.py`
      Verify: `uv run pytest tests/unit/test_transformation.py -q`; golden/snapshot assertions added in step 8.

- [ ] 4. Thread the SAS result type into the IR during SDTM lowering (D2).
      In `src/app/sdtm/service.py` `lower_plan`: when building each `{"node_type":"derive", ...}` IR dict, also build `result_types` by resolving each assignment target variable name against `domains[node.target_domain].variables[*].name -> data_type` (`SdtmVariable.data_type` is `Literal["character","numeric"]`). Only include targets that resolve to a declared variable; leave others absent (SAS then raises `backend_capability_missing` for conditional-valued ones, per D2). Do not change SDTM authoring contracts structurally.
      Files: `src/app/sdtm/service.py`
      Verify: `uv run pytest tests/unit/test_sdtm.py -q` (and any `tests/contract`/`tests/integration` SDTM plan tests that cover `lower_plan`); add a unit test asserting a conditional ADSL/DM derive produces `result_types` and SAS picks `IFC`/`IFN`.

- [ ] 5. Expression validation harness + conditional rules (design §6, AGENTS.md Validation conventions).
      There is NO existing expression-level validator (`sdtm/routes.py::validate_plan` returns `"issues": []`). Create a validator that walks every `Expression` in a plan/IR and emits the common `ValidationIssue` model (`app.validation.contracts.ValidationIssue`, severities `error|warning|info`, with `code`, `message`, `suggestion`, `module`, `entity_type`, `entity_id`, `field_path`). Place it in the transformation package (e.g. `src/app/transformation/expression_validation.py`) so SDTM/ADaM/TLF can call it through a typed function; do NOT put clinical rules in `common`. Conditional codes: `expr_conditional_empty` (error; also structurally caught by `min_length>=1`), `expr_conditional_result_type_mixed` (warning: `then`/`otherwise` static literal types disagree character-vs-numeric), `expr_conditional_branch_unreachable` (warning: a later branch whose `when` is a constant-true duplicate of an earlier guard). Set stable `field_path` pointing at the offending sub-expression. Wire the SDTM `validate_plan` route to run this validator over the lowered/authored expressions and return the issues (preserve the existing response shape, filling `issues`).
      Files: `src/app/transformation/expression_validation.py` (new), `src/app/sdtm/routes.py` (wire issues into `validate_plan`)
      Verify: `uv run pytest tests/unit/ -k "expression_validation or validate_plan" -q`.

- [ ] 6. Phase 1 conformance test — Python + R executed, outputs compared (design §8).
      Add `tests/conformance/test_expression_conformance.py` with a reusable harness that: builds a `DataflowIR` using a conditional derive, writes input CSVs, runs the Python program via `uv run python`/`sys.executable` and the R program via `Rscript` into a tmp workspace (`AURINARA_WORKSPACE`), reads both output CSVs, and compares **exactly** for string/int/bool/date and within a node-declared **tolerance** for float. Include the ITTFL end-to-end case (`SAFFL=="Y" and RANDFL=="Y" -> "Y" else null`) plus null-`when`, short-circuit (unmatched div-by-zero branch → null per D1), and mixed/empty-string/non-ASCII fixtures. Assert the SAS program is generated for a `result_types`-populated conditional, and that a missing `result_types` entry raises `BackendCapabilityMissing` (SAS non-failing when unavailable: assert the typed outcome, do not execute SAS).
      Files: `tests/conformance/test_expression_conformance.py`
      Verify: `uv run pytest tests/conformance/test_expression_conformance.py -q` (skip R-dependent asserts behind a `shutil.which("Rscript")` guard so CI without R still passes the Python+SAS asserts; the guard must NOT hide a real mismatch when R is present).

- [ ] 7. Phase 1 unit + property tests.
      Unit (`tests/unit/test_transformation_conditional.py`): evaluator branch selection/null-when/short-circuit/D1; codegen golden snapshots for `_py_expr`/`_r_expr`/`_sas_expr` on a conditional (assert `IFC` vs `IFN` by `result_types`, and `BackendCapabilityMissing` when absent); contract round-trip (serialize/deserialize a conditional); backward-compat (old IR payload without `result_types` validates and lowers). Property (`tests/unit/test_transformation_conditional_properties.py`, Hypothesis): serialize→deserialize round-trip of conditionals; conditional selection vs a Python oracle; null propagation.
      Files: `tests/unit/test_transformation_conditional.py`, `tests/unit/test_transformation_conditional_properties.py`
      Verify: `uv run pytest tests/unit -k conditional -q`.

- [ ] 8. Phase 1 frontend conditional editor (design §10). SEE the two "needs verification" findings above FIRST (copy builder into worktree; stand up vitest).
      In `expression-builder.tsx`: add `{ value: 'conditional', label: 'Conditional (case/when)' }` to `KIND_OPTIONS`; add a `defaultExpression('conditional')` returning one empty branch + `otherwise` = `{kind:'literal', value:null}`; add a `ConditionalFields` editor — a branch list (reuse the `AssignmentList`/add-remove pattern) where each row has a `when` and a `then` recursive `ExpressionBuilder` (depth+1), add/remove-branch buttons, and a single `otherwise` `ExpressionBuilder`. NEVER render a free-text code field. Regenerate the typed client so the union includes `conditional` (`npm run api:sync`, which runs `api:export` through `uv` then `orval`).
      Files: `frontend/src/components/workbench/plan-graph/expression-builder.tsx`, regenerated `frontend/src/api/generated/**`, `frontend/openapi.json`
      Verify: `npm run api:sync` then `npm run typecheck` (`tsc --noEmit`) and `npm run lint`; `npm run test` (vitest) runs a new `expression-builder.conditional.test.tsx` proving typed controls render and no free-text/code input exists.

### Phase 1 acceptance criteria

- `uv run pytest tests/unit tests/conformance -q`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src` all pass in the worktree.
- A conditional derive compiles to Python/R and produces identical normalized outputs for the ITTFL fixture; SAS compiles via `IFC`/`IFN` when `result_types` is present and raises `BackendCapabilityMissing` when absent.
- `expr_conditional_empty/_result_type_mixed/_branch_unreachable` fire on the right malformed inputs; `operator_version` is `1.2.0`, `schema_version` unchanged; an old IR without `result_types` still validates and lowers.
- Frontend: conditional editor builds the typed union with no free-text code field; `npm run typecheck`/`lint`/`test` and the orval types compile.

## Phase 2 — Typed function catalog + list literal (design §4, §4.3, §4.5, §4.6, §14 D3–D11)

- [ ] 9. Function + list-literal contracts with per-function arity (design §4.1, §4.5).
      In `src/app/transformation/contracts.py`: add `FunctionName` as a closed `Literal[...]` enum containing EVERY function in §4.3 AND §4.6 — string: `concat, substring, upper, lower, trim, length, contains, startswith, endswith, replace, index_of, scan_token, pad_left, pad_right`; null/logical: `coalesce, nullif, is_in, n_missing, n_present`; numeric: `round, floor, ceil, abs, modulo, min_of, max_of, truncate, safe_divide`; date/datetime: `parse_date, year, month, day, date_diff_days, parse_datetime, hour, minute, second, study_day, date_add_days, date_diff_months`. Add `FunctionCallExpression{kind: Literal["function"]; function: FunctionName; arguments: tuple[Expression, ...]}` and `ListLiteralExpression{kind: Literal["list_literal"]; values: tuple[str|int|float|bool|None, ...] = Field(min_length=1)}`. Add both to the `Expression` union. Add a `model_validator(mode="after")` on `FunctionCallExpression` enforcing per-function arity (fixed-arity funcs exact; variadic `concat`/`coalesce`/`min_of`/`max_of`/`n_missing`/`n_present` min counts) AND that a `ListLiteralExpression` appears ONLY as the 2nd argument of `is_in` (and `is_in` requires it there).
      Files: `src/app/transformation/contracts.py`
      Verify: `uv run pytest tests/unit/test_transformation.py -q`; add contract tests in step 13.

- [ ] 10. Evaluator function registry + list literal (design §5, D3/D4/D5/D7/D8/D9/D10/D11).
      In `src/app/transformation/evaluator.py` `_value`: add `kind == "list_literal"` (return the values tuple, consumed only by `is_in`) and `kind == "function"` dispatching through a registry `dict[FunctionName, Callable]`. Implement every catalog semantic on evaluated scalar args: null-in→null-out by default; `coalesce/nullif/is_in` null-handling; D3 half-away-from-zero `round` and truncated (dividend-sign) `modulo`; D4 `parse_date` full `YYYY-MM-DD` only (partials→null); D5 ASCII/invariant `upper`/`lower`; D7 `scan_token` collapses consecutive delimiters; D8 `study_day` CDISC `--DY` no-day-zero (`event>=reference ? event-reference+1 : event-reference`); D9 `date_diff_months` continuous elapsed whole months; D10 `parse_datetime` naive/UTC only, offset-bearing→null; D11 homogeneous arg types for `min_of/max_of/n_missing/n_present`. Preview codes: `preview_function_argument_invalid`, `preview_date_parse_invalid` (both 422). Unknown name → `AssertionError` guard (Literal already restricts).
      Files: `src/app/transformation/evaluator.py`
      Verify: `uv run pytest tests/unit/test_transformation_evaluator.py tests/unit -k function -q`.

- [ ] 11. Three-backend function lowering tables (design §4.3, §4.6, §7, D3/D5/D7/D8/D9/D10/D11).
      In `src/app/transformation/codegen.py`: add per-backend lowering tables keyed by function name in `_py_expr`/`_r_expr`/`_sas_expr`, plus `list_literal` handling (only inside `is_in`). Emit EXPLICIT implementations for the hazard functions — never language defaults: D3 half-away-from-zero `round` and truncated `modulo` in all three; D7 `scan_token` delimiter-collapse in Py/R to match SAS `scan`; D8 `study_day` formula; D9 `date_diff_months` continuous; D10 datetime naive/UTC. SAS char/numeric native selection where it matters (`coalesce`/`coalescec`, `nmiss`/`cmiss`, `min`/`max` from D11 homogeneous type; `IFN`/`IFC` for `nullif`). Where a backend cannot preserve exact semantics, raise `UnsupportedOperator` (→ `BackendCapabilityMissing`) rather than approximate. Date functions compose only through `parse_date`/`parse_datetime`; never expose the raw integer date; SAS 1960 origin stays internal.
      Files: `src/app/transformation/codegen.py`
      Verify: `uv run pytest tests/unit -k "function and (codegen or golden)" -q`.

- [ ] 12. Function/list-literal validation rules (design §6, D11).
      Extend `src/app/transformation/expression_validation.py` with: `expr_function_unknown` (error; defense beyond the Literal), `expr_function_arity` (error), `expr_function_arg_type` (error; e.g. `substring` start/length not integer-typed, D11 heterogeneous args), `expr_list_literal_misplaced` (error; list literal outside `is_in`), `expr_date_function_on_nondate` (warning; date function applied to an expression not produced by `parse_date`/`parse_datetime`). Keep stable codes and `field_path`. Enforce `replace`'s non-empty `find` and `pad_left`/`pad_right` single-char `fill` as `expr_function_arg_type` where statically decidable.
      Files: `src/app/transformation/expression_validation.py`
      Verify: `uv run pytest tests/unit -k expression_validation -q`.

- [ ] 13. Phase 2 conformance + unit + property tests (design §8, every function).
      Extend `tests/conformance/test_expression_conformance.py` with a fixture plan exercising EVERY function and `list_literal`; generate Python+R, execute both, compare exact (string/int/bool/date) and tolerance (float: `round`, float `abs`, `safe_divide`); assert SAS generated (non-failing). Unit (`tests/unit/test_transformation_functions.py`): evaluator per-function, codegen golden per function, each validation code. Property (`tests/unit/test_transformation_functions_properties.py`, Hypothesis): serialize/deserialize round-trip; 1-based `substring`/`index_of` boundaries; `modulo`/`round` on negatives/boundaries; `parse_date` valid/partial/invalid; `study_day` boundaries (event==reference→1; event==reference-1→−1). Fixtures include missing values, empty-string-vs-null, non-ASCII, partial dates.
      Files: `tests/conformance/test_expression_conformance.py`, `tests/unit/test_transformation_functions.py`, `tests/unit/test_transformation_functions_properties.py`
      Verify: `uv run pytest tests/conformance tests/unit -k "function or conformance" -q` (R asserts behind the `Rscript` guard as in step 6).

- [ ] 14. Phase 2 frontend function + list-literal editors (design §10).
      In `expression-builder.tsx`: add `{ value: 'function', label: 'Function' }` to `KIND_OPTIONS`; `defaultExpression('function')` → a safe entry (e.g. `upper` with one column arg); add `FunctionFields` — a `Select` populated from the generated `FunctionName` enum (`@/api/generated/model`), one child `ExpressionBuilder` per positional arg, arity-aware argument reset when the function changes, and a typed value-list editor for the `is_in` list-literal slot (individual typed literal values only, never free text/code). Regenerate the client (`npm run api:sync`) so the function-name enum and widened union are present.
      Files: `frontend/src/components/workbench/plan-graph/expression-builder.tsx`, regenerated `frontend/src/api/generated/**`, `frontend/openapi.json`
      Verify: `npm run api:sync` then `npm run typecheck` and `npm run lint`; `npm run test` runs a new `expression-builder.function.test.tsx` proving the function Select, per-arg builders, arity reset, and the typed `is_in` list editor render with no free-text code field.

### Phase 2 acceptance criteria

- `uv run pytest tests/unit tests/conformance -q`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src` all pass.
- Every §4.3 + §4.6 function and `list_literal` compiles to Python/R with identical normalized outputs (exact or declared tolerance) and generates a SAS program; D3/D4/D5/D7/D8/D9/D10/D11 are honored by explicit implementations, not language defaults.
- `expr_function_unknown/_arity/_arg_type`, `expr_list_literal_misplaced`, `expr_date_function_on_nondate` fire correctly; `is_in` list literal valid only as its 2nd arg.
- Frontend: function + `is_in` list editors are fully typed with no free-text code field; `npm run typecheck`/`lint`/`test` and orval types compile.

## Cross-cutting verification (run before handoff of each phase)

From the worktree root `e:\Work\EDETEK\Python\aurinara\.worktrees\typed-expr`:

```
uv sync --extra dev
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest tests/unit tests/contract tests/conformance -q
```

From `frontend/`:

```
npm run api:sync
npm run typecheck
npm run lint
npm run test
```

Also update `tests/contract` + the generated typed-client fixture for the widened `Expression` schema (D6, no API version bump). Do NOT add an Alembic migration. Keep all changes inside `transformation`, `sdtm`, `validation` packages and the frontend expression builder plus their tests; preserve unrelated code.
