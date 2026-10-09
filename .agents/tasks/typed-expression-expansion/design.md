# Typed Expression Expansion — Conditional + Function Catalog

Status: Draft for review
Scope: `src/app/transformation` (contract, evaluator, codegen), `src/app/sdtm`/ADaM/TLF (consumers), `src/app/validation`, conformance tests, and the frontend `expression-builder.tsx`.
Authoring boundary: everything stays inside the **typed** expression model. No free-text Python/R/SAS/SQL/arbitrary expression strings, per AGENTS.md "Compilation and execution".

---

## 1. Problem and goal

The shared typed expression model is a discriminated union of four kinds — `literal`, `column`, `unary`, `binary` — defined in `src/app/transformation/contracts.py:35-39`:

```python
Expression = Annotated[
    LiteralExpression | ColumnExpression | UnaryExpression | BinaryExpression,
    Field(discriminator="kind"),
]
```

Operators are only comparison (`eq ne lt le gt ge`), logic (`and or not`), null tests (`is_null is_not_null`), and arithmetic (`add sub mul div negate`) (`contracts.py:24-33`). This vocabulary cannot:

- Produce a **conditional value**: an ADaM-style flag `ITTFL = "Y" when (SAFFL=="Y" and RANDFL=="Y") else null` is impossible — `and` yields a boolean, and there is no construct that maps a condition to a value.
- Call any **function**: no string ops (concat, substr, upper), no null-handling (coalesce), no rounding, no date math — all of which SDTM/ADaM derivations routinely need.

Goal: broaden the typed vocabulary with two new expression kinds — a **multi-branch conditional** and an **allowlisted typed function call** — that compile deterministically and identically to Python, R, and SAS, with validation and cross-language conformance coverage, plus the frontend builder additions. No free-text escape hatch.

This document specifies both. Delivery is phased (§9): **Phase 1 = conditional** (directly unblocks ITTFL), **Phase 2 = function catalog**.

---

## 2. Where the change lands (grounding, with file:line)

| Concern                            | File                                                                  | Current state                                                                                                                                          |
| ---------------------------------- | --------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Typed `Expression` union           | `src/app/transformation/contracts.py:35-39`                           | 4 kinds; new kinds join this union                                                                                                                     |
| IR version fields                  | `src/app/transformation/contracts.py:207-209`                         | `schema_version="1.0.0"`, `operator_version="1.1.0"` — bump required                                                                                   |
| SDTM authoring embeds `Expression` | `src/app/sdtm/contracts.py`                                           | `DeriveNode.assignments`, `FilterNode.predicate`, `AssertNode.predicate`, `SdtmValueLevelMetadata.condition`; imports `Expression` from transformation |
| Preview interpreter                | `src/app/transformation/evaluator.py:24-82` (`_value`)                | dispatches on `expression.kind`; raises `preview_expression_type_invalid` etc.                                                                         |
| Python codegen                     | `src/app/transformation/codegen.py` `_py_expr`                        | string-emitting recursive lowerer                                                                                                                      |
| R codegen                          | `src/app/transformation/codegen.py` `_r_expr`                         | string-emitting recursive lowerer                                                                                                                      |
| SAS codegen                        | `src/app/transformation/codegen.py` `_sas_expr`                       | string-emitting recursive lowerer; `GENERATORS` map at end                                                                                             |
| Frontend builder                   | `frontend/src/components/workbench/plan-graph/expression-builder.tsx` | recursive `ExpressionBuilder`, `KIND_OPTIONS`, `defaultExpression`, per-kind field editors; types come from `@/api/generated/model` (orval)            |

Because SDTM, ADaM, and TLF all consume the **shared** `Expression`, enriching it flows through to every module that embeds it. The design treats `Expression` as the single source of truth; module authoring contracts are unchanged structurally.

**Hard constraint discovered in SAS codegen:** `_sas_expr` emits raw DATA-step expressions and some operators (`join`, `aggregate`) already raise `UnsupportedOperator`. New expression kinds must either lower cleanly to a SAS DATA-step expression or raise `backend_capability_missing` before publishing — never silently substitute (AGENTS.md).

---

## 3. New expression kind: conditional (case/when)

### 3.1 Contract

```python
class ConditionalBranch(StrictModel):
    when: "Expression"    # must evaluate to boolean
    then: "Expression"    # the value produced when `when` is truthy

class ConditionalExpression(StrictModel):
    kind: Literal["conditional"]
    branches: tuple[ConditionalBranch, ...] = Field(min_length=1)
    otherwise: "Expression"   # mandatory else; use a literal null for "no match -> null"
```

Added to the union:

```python
Expression = Annotated[
    LiteralExpression | ColumnExpression | UnaryExpression | BinaryExpression
    | ConditionalExpression | FunctionCallExpression,
    Field(discriminator="kind"),
]
```

### 3.2 Semantics (the normative contract all four surfaces must honor)

- **Evaluation order**: branches are evaluated top-to-bottom; the first branch whose `when` is **truthy** returns its `then`. If none match, return `otherwise`.
- **Short-circuit**: once a branch matches, later `when`/`then` are not evaluated (so a later divide-by-zero in an unmatched branch never fires). This matters for cross-backend identity — see §3.4.
- **Null `when`**: a `when` that evaluates to null is treated as **not matched** (same as false). This mirrors SQL `CASE` and R `dplyr::case_when`.
- **Mandatory `otherwise`**: making else required removes the "implicit null vs explicit null" ambiguity across backends. "No match → null" is written explicitly as `otherwise = literal null`.
- **Result type**: the conditional's result type is the common type of all `then` values and `otherwise`. The design does **not** require every branch to be the same declared type at the contract level (Pydantic cannot see runtime column types), but validation (§6) emits a warning when branch result types are statically incompatible (e.g. one branch literal is a number, another a string). Mixed character/numeric results are the author's responsibility; the evaluator and codegen do not coerce.

### 3.3 ITTFL expressed under this design

```json
{
  "kind": "conditional",
  "branches": [
    {
      "when": {
        "kind": "binary",
        "operator": "and",
        "left": {
          "kind": "binary",
          "operator": "eq",
          "left": { "kind": "column", "dataset": "dm", "column": "SAFFL" },
          "right": { "kind": "literal", "value": "Y" }
        },
        "right": {
          "kind": "binary",
          "operator": "eq",
          "left": { "kind": "column", "dataset": "dm", "column": "RANDFL" },
          "right": { "kind": "literal", "value": "Y" }
        }
      },
      "then": { "kind": "literal", "value": "Y" }
    }
  ],
  "otherwise": { "kind": "literal", "value": null }
}
```

### 3.4 Lowering

| Backend             | Lowering strategy                                                                                                                                                                                                                                                                                                                                                                                                             | Notes                                                                                                                                                                                                                         |
| ------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Python (`_py_expr`) | Nested ternary, innermost = `otherwise`: `((then1) if (bool(when1) and when1 is not None) else ((then2) if ... else (otherwise)))`                                                                                                                                                                                                                                                                                            | Build right-fold over branches. Null-`when` guarded by `when is not None` to match "null = not matched". Ternary is naturally short-circuit.                                                                                  |
| R (`_r_expr`)       | `dplyr::case_when(...)` **is not** used (adds a dependency and NA-handling differs); instead nested `if (...) ... else ...` is wrong for vectorized frames. Use **`ifelse` nesting with explicit NA guard**, or generate a per-row evaluation. **Recommended**: emit a right-folded `ifelse(cond & !is.na(cond), then, inner)` where `cond` is the `when`. `ifelse` is vectorized and evaluates both arms — see hazard below. | **HAZARD**: `ifelse` is NOT short-circuit; both arms are computed for all rows. If an unmatched branch's `then` can error (e.g. `1/0`), R will warn/err where Python won't. Mitigation options in §3.5.                       |
| SAS (`_sas_expr`)   | DATA-step requires a statement, not an expression, for `IF/THEN`. The conditional appears **inside** a `derive` assignment (`name = <expr>;`). Lower to **nested `CASE` is not an expression in base SAS DATA step**. Use the `IFC`/`IFN` functions for scalar conditional expressions: `IFC(cond, then_char, else_char)` for character, `IFN(cond, then_num, else_num)` for numeric.                                         | **HAZARD**: `IFC`/`IFN` evaluate **all three** arguments (not short-circuit), AND they are type-split (char vs numeric). The generator must know whether the result is character or numeric to pick `IFC` vs `IFN`. See §3.5. |

### 3.5 Cross-backend hazards for the conditional (must be resolved before implementation)

1. **Short-circuit divergence** (Python ternary short-circuits; R `ifelse` and SAS `IFC/IFN` do not). → **Decision needed.** Recommended resolution: **forbid side-effecting/partial expressions inside branches** by construction — the expression language has no side effects, and the only "error" is type/arithmetic (e.g. div-by-zero). Define div-by-zero and type-invalid inside an _unmatched_ branch as **implementation-defined to produce null, not an error**, and make all three backends swallow per-branch arithmetic errors to null. This keeps results identical. This is a semantic choice that MUST be ratified (it slightly changes arithmetic error behavior inside conditionals vs. a bare `derive`).
2. **SAS char/numeric split** (`IFC` vs `IFN`). → The SDTM/ADaM target variable has a declared `data_type` (`character`/`numeric`, see `SdtmVariable.data_type` in `src/app/sdtm/contracts.py:48`). The codegen for a `derive` assignment already knows the target column but **not** its declared type (the IR `DeriveNode` carries only expressions, not types). → **Decision needed**: thread the target variable's declared type into the IR `derive` node (new optional field, e.g. `result_types: dict[str, Literal["character","numeric"]]`), so the SAS generator picks `IFC`/`IFN` deterministically. Without this, SAS lowering of a conditional cannot be done safely and must raise `backend_capability_missing`.
3. **R NA propagation in `ifelse`**: `ifelse(NA, a, b)` returns NA, not `b`. The explicit `cond & !is.na(cond)` guard fixes "null when = not matched".

---

## 4. New expression kind: typed function call

### 4.1 Contract

```python
class FunctionCallExpression(StrictModel):
    kind: Literal["function"]
    function: FunctionName          # a Literal[...] enum of allowlisted names
    arguments: tuple["Expression", ...]  # positional; arity validated per function
```

`FunctionName` is a closed `Literal` of the catalog in §4.3 — there is no arbitrary-callable path. Arity and argument types are validated in §6; the contract only enforces the name is in the allowlist and arguments are themselves valid `Expression`s.

### 4.2 Catalog design principles

- **Allowlist only.** Every function is a named entry with a fixed signature. Adding a function is a code+version change, reviewed like any contract change.
- **Null-in → null-out by default** unless the function's job is null-handling (`coalesce`, `nullif`, `is_null`-style). Documented per function.
- **Result type is static per function** (not value-dependent), so validation and the SAS char/numeric split are decidable.
- **Exact vs tolerance**: string/int/boolean/date results compare **exactly** across backends; float results compare only within node-declared tolerance (AGENTS.md conformance rule). Marked per function below.

### 4.3 Initial function catalog

Legend — Result: `str`/`int`/`float`/`bool`/`date`. Compare: `exact` or `tol` (tolerance-bound float).

**String** (all `exact`):

| Function     | Signature                                      | Null behavior                      | Py                          | R                                  | SAS                         | Hazard                                                                                                                        |
| ------------ | ---------------------------------------------- | ---------------------------------- | --------------------------- | ---------------------------------- | --------------------------- | ----------------------------------------------------------------------------------------------------------------------------- | ------------ | ----- | --- | --------------------------------------------------------------------------- |
| `concat`     | `concat(str...) -> str`                        | null arg → treated as empty string | `"".join(...)`              | `paste0(...)`                      | `cats(...)` or `            |                                                                                                                               | `with`strip` | SAS ` |     | `keeps trailing blanks; use`cats`. Empty-vs-null: concat defines null=`""`. |
| `substring`  | `substring(str, start:int, length:int) -> str` | null str → null                    | `s[start-1:start-1+length]` | `substr(s, start, start+length-1)` | `substr(s, start, length)`  | **1-based** indexing is the contract (SAS/R native); Python generator subtracts 1. Out-of-range → empty string, all backends. |
| `upper`      | `upper(str) -> str`                            | null → null                        | `.upper()`                  | `toupper`                          | `upcase`                    | Locale: define as ASCII/invariant upper; document non-ASCII handling (see §7).                                                |
| `lower`      | `lower(str) -> str`                            | null → null                        | `.lower()`                  | `tolower`                          | `lowcase`                   | same locale note                                                                                                              |
| `trim`       | `trim(str) -> str`                             | null → null                        | `.strip()`                  | `trimws`                           | `strip`                     | trims leading+trailing whitespace                                                                                             |
| `length`     | `length(str) -> int`                           | null → null (not 0)                | `len`                       | `nchar`                            | `lengthn`                   | SAS `length()` counts to trailing blanks; use `lengthn`. null→null requires guard.                                            |
| `contains`   | `contains(str, substr) -> bool`                | null arg → null                    | `b in a`                    | `grepl(fixed=TRUE)`                | `index(a,b) > 0`            | fixed (non-regex) match is the contract                                                                                       |
| `startswith` | `startswith(str, prefix) -> bool`              | null → null                        | `.startswith`               | `startsWith`                       | `=: ` operator / `index==1` |                                                                                                                               |
| `endswith`   | `endswith(str, suffix) -> bool`                | null → null                        | `.endswith`                 | `endsWith`                         | reverse+index               |                                                                                                                               |

**Null-handling**:

| Function   | Signature                                        | Behavior                             | Py                  | R                             | SAS                                       |
| ---------- | ------------------------------------------------ | ------------------------------------ | ------------------- | ----------------------------- | ----------------------------------------- |
| `coalesce` | `coalesce(a...) -> same` (exact/tol by arg type) | first non-null arg, else null        | first `is not None` | `dplyr::coalesce` or `Reduce` | `coalesce()` (SAS 9.4+) char: `coalescec` |
| `nullif`   | `nullif(a, b) -> same`                           | null if `a==b` else `a`              | ternary             | `ifelse(a==b, NA, a)`         | `IFN/IFC(a=b, ., a)`                      |
| `is_in`    | `is_in(a, list_literal) -> bool`                 | true if `a` ∈ list; null `a` → false | `a in {...}`        | `a %in% c(...)`               | `a in (...)`                              |

`is_in` needs a **list literal** — see §4.5.

**Numeric** (`round`/`abs` exact for int inputs, `tol` for float):

| Function | Signature                             | Behavior                           | Py                                   | R                       | SAS                           | Hazard                                                                                                                                                                   |
| -------- | ------------------------------------- | ---------------------------------- | ------------------------------------ | ----------------------- | ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `round`  | `round(x:float, digits:int) -> float` | half-away-from-zero (NOT banker's) | custom (Python `round` is banker's!) | `round` is banker's too | `round(x, 10**-d)` is half-up | **HAZARD**: Python/R default to banker's rounding, SAS to half-up. Must standardize on **half-away-from-zero** and implement it explicitly in all three to match. `tol`. |
| `floor`  | `floor(x) -> int`                     | toward −∞                          | `math.floor`                         | `floor`                 | `floor`                       | exact                                                                                                                                                                    |
| `ceil`   | `ceil(x) -> int`                      | toward +∞                          | `math.ceil`                          | `ceiling`               | `ceil`                        | exact                                                                                                                                                                    |
| `abs`    | `abs(x) -> same`                      |                                    | `abs`                                | `abs`                   | `abs`                         | exact(int)/tol(float)                                                                                                                                                    |
| `modulo` | `modulo(a:int, b:int) -> int`         | sign follows dividend; b=0 → null  | `a - b*int(a/b)`                     | `%%` differs on sign!   | `mod`                         | **HAZARD**: R `%%` and Python `%` differ for negative operands. Standardize on truncated (dividend-sign) modulo and implement explicitly.                                |

**Date/datetime** (`exact` — all integer/string results; the hardest group):

| Function         | Signature                                     | Behavior                                    | Py                   | R                         | SAS                                | Hazard                                                                                                                                                                                                                                                         |
| ---------------- | --------------------------------------------- | ------------------------------------------- | -------------------- | ------------------------- | ---------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `parse_date`     | `parse_date(str) -> date`                     | parse ISO 8601 `YYYY-MM-DD`; invalid → null | `date.fromisoformat` | `as.Date(fmt="%Y-%m-%d")` | `input(x, yymmdd10.)`              | **HAZARD**: partial dates (`2021-03`, `2021`) are common in SDTM `--DTC`. Contract: only full `YYYY-MM-DD` parses; partials → null (documented). SAS date origin is 1960-01-01, R/Python differ — never expose the integer, only use via other date functions. |
| `year`           | `year(date) -> int`                           |                                             | `.year`              | `format(d,"%Y")`          | `year()`                           | works on parsed date only                                                                                                                                                                                                                                      |
| `month`          | `month(date) -> int`                          |                                             | `.month`             |                           | `month()`                          |                                                                                                                                                                                                                                                                |
| `day`            | `day(date) -> int`                            |                                             | `.day`               |                           | `day()`                            |                                                                                                                                                                                                                                                                |
| `date_diff_days` | `date_diff_days(end:date, start:date) -> int` | integer day difference; null if either null | `(e-s).days`         | `as.integer(e-s)`         | `e - s` (SAS dates are day counts) | sign and inclusivity defined as `end - start`, exclusive.                                                                                                                                                                                                      |

### 4.4 Why these and not raw mutate

Every entry has a single defined semantic and three concrete lowerings that are verified by conformance tests (§8). This is the point: an author gets "more expressions" with the guarantee that Python, R, and SAS agree — which a free-text R `mutate` string can never provide (it would not compile to Python or SAS at all).

### 4.5 Supporting addition: list literal (for `is_in`)

`is_in` needs a set of constants. Rather than overload `LiteralExpression`, add:

```python
class ListLiteralExpression(StrictModel):
    kind: Literal["list_literal"]
    values: tuple[str | int | float | bool | None, ...] = Field(min_length=1)
```

Only valid as the second argument of `is_in` (validation enforces). Not a general-purpose value elsewhere.

---

## 5. Evaluator changes (`evaluator.py`)

`_value` (`evaluator.py:24-82`) gains branches:

- `kind == "conditional"`: iterate `branches`; for each, `cond = _value(branch.when, row)`; if `cond is not None and bool(cond)` return `_value(branch.then, row)`; after loop return `_value(expression.otherwise, row)`. Honors null-when=not-matched and short-circuit.
- `kind == "function"`: dispatch on `expression.function` through a **registry dict** `{name: python_callable}`, each callable implementing the catalog semantics on evaluated scalar args, with the documented null rules. Unknown name → `AssertionError` (contract already restricts the Literal, so this is a guard).
- `kind == "list_literal"`: return a tuple of the values (only consumed by `is_in`).

New preview problem codes: `preview_function_argument_invalid`, `preview_date_parse_invalid` (both 422), reusing `preview_expression_type_invalid` where it already fits.

---

## 6. Validation (`src/app/validation` + Pydantic contract)

Two layers, consistent with AGENTS.md "Validation conventions" (stable codes, common issue model):

**Contract-level (Pydantic, structural):**

- `ConditionalExpression`: `branches` min_length ≥ 1 (enforced by Field); `otherwise` required.
- `FunctionCallExpression`: name ∈ allowlist (Literal); per-function **arity** validated in a `model_validator` keyed by `function`.
- `ListLiteralExpression`: only accepted as `is_in` arg 2 — enforced in `FunctionCallExpression` validator.

**Rule-registry-level (declarative rules with stable IDs):** emit the common issue model with these new stable codes:

| Code                                  | Severity | When                                                                                                    |
| ------------------------------------- | -------- | ------------------------------------------------------------------------------------------------------- |
| `expr_function_unknown`               | error    | function name not in catalog (defense-in-depth beyond the Literal)                                      |
| `expr_function_arity`                 | error    | wrong number of arguments for the function                                                              |
| `expr_function_arg_type`              | error    | an argument's static type is incompatible with the signature (e.g. `substring` start not integer-typed) |
| `expr_conditional_empty`              | error    | zero branches (also caught structurally)                                                                |
| `expr_conditional_result_type_mixed`  | warning  | `then`/`otherwise` static types disagree (character vs numeric)                                         |
| `expr_conditional_branch_unreachable` | warning  | a later branch whose `when` is a constant-true duplicate of an earlier guard                            |
| `expr_list_literal_misplaced`         | error    | list literal used outside `is_in`                                                                       |
| `expr_date_function_on_nondate`       | warning  | date function applied to an expression not produced by `parse_date`                                     |

Field paths point at the offending sub-expression so the UI can highlight it (`field_path` in the common issue model).

---

## 7. Codegen changes (`codegen.py`) — per backend

Each of `_py_expr`, `_r_expr`, `_sas_expr` gains `conditional`, `function`, `list_literal` handling. Key decisions already identified:

- **Conditional**: right-fold as in §3.4 with the agreed error-to-null semantics (§3.5 decision 1) and the SAS char/numeric type threading (§3.5 decision 2).
- **Functions**: a per-backend lowering table keyed by `function`. Where a backend cannot preserve a function's exact semantics, raise `UnsupportedOperator`/`backend_capability_missing` (e.g. if a future function has no faithful SAS form) rather than approximate.
- **Rounding/modulo**: emit explicit half-away-from-zero and truncated-modulo implementations in all three; never rely on the language default (§4.3 hazards).
- **Locale/encoding** (`upper`/`lower`): define as invariant/ASCII-casing; document that non-ASCII casing is out of scope for Phase 2 and, if needed, is a later per-function decision. Conformance fixtures include non-ASCII to prove the three backends agree on the defined behavior.
- **Dates**: never expose the raw integer date; date functions compose only through `parse_date`'s output. SAS date origin (1960) is internal to the generator.

The compiler banner currently reads `compiler=1.4.0`; bump to reflect the new operator set (see §9).

---

## 8. Conformance tests (`tests/conformance`, plus unit/property)

Per AGENTS.md "Testing conventions":

- **Conformance (the core gate):** for a fixture plan exercising every new expression kind and every catalog function, generate Python and R programs, execute both (SAS when a runner is configured; otherwise assert the SAS program is generated and `runner_not_configured` is the only reason it did not run), and compare normalized outputs: **exact** for string/int/bool/date results, **tolerance** for float results (`round`, float `abs`), with the tolerance declared on the node.
- **Property tests:** typed expressions (round-trip serialize/deserialize), conditional branch evaluation vs a reference oracle, function null-propagation, 1-based substring boundaries, modulo/round on negative and boundary inputs, date parsing of valid/partial/invalid strings.
- **Unit tests:** evaluator branches, each codegen lowerer snapshot (golden), validation codes fire on the right malformed inputs.
- **Fixtures** must include missing values, empty-string-vs-null, non-ASCII text, partial dates, and the ITTFL conditional end to end.

---

## 9. Versioning, saved plans, OpenAPI compatibility

- The expression vocabulary is part of the Dataflow IR operator set. Bump **`operator_version`** `"1.1.0" → "1.2.0"` (`contracts.py:208`) and the codegen `compiler=` banner. `schema_version` of the IR stays `"1.0.0"` unless the envelope shape changes (it does not).
- **Already-saved Derivation Plans** pinned to the old operator set remain valid — the new kinds are **additive** to the union, so old plans (which never contain the new kinds) still parse and lower unchanged. No rewrite, no forced staleness of existing plans (consistent with AGENTS.md: publishing new capability does not stale existing work; only changing an aggregate's selection does).
- **OpenAPI** is a versioned contract (AGENTS.md "API conventions"). The new `kind`s widen the `Expression` schema. This is an additive, backward-compatible schema change for readers, but it DOES change the generated frontend client. Update contract tests and regenerate the typed client (`npm run api:sync`). Confirm whether the platform treats a widened request schema as needing a version bump — flag as an open decision if the team's policy is strict.
- **ADaM/TLF**: confirm during implementation that both reuse the shared `Expression` (SDTM does, via import). If so they inherit the capability for free; if ADaM/TLF pin their own operator version, bump those too.

---

## 10. Frontend builder changes (`expression-builder.tsx`)

The component's invariant — "NEVER exposes a free-text Python/R/SAS/SQL field" — is preserved. Changes:

- **`KIND_OPTIONS`**: add `{ value: 'conditional', label: 'Conditional (case/when)' }` and `{ value: 'function', label: 'Function' }`.
- **`defaultExpression`**: add defaults — conditional with one empty branch + `otherwise` = empty literal null; function defaulting to a safe no-arg-ish entry (e.g. `upper` with one column arg).
- **Conditional editor (`ConditionalFields`)**: a branch list (reuse the `AssignmentList` pattern) where each row has a `when` `ExpressionBuilder` (labeled "When") and a `then` `ExpressionBuilder` (labeled "Then"), add/remove branch buttons, and a single `otherwise` `ExpressionBuilder` ("Otherwise"). Recursion via the existing `ExpressionBuilder` with `depth+1`.
- **Function editor (`FunctionFields`)**: a `Select` populated from a generated function catalog (names + arities come from `@/api/generated/model` enums), and one child `ExpressionBuilder` per positional argument. Changing the function resets arguments to the new arity's defaults. The list-literal argument for `is_in` renders a small typed value-list editor (no free text beyond individual literal values), gated to that argument slot.
- Types regenerate from the backend OpenAPI via orval (`npm run api:sync`), so the union, function-name enum, and arities are not hand-maintained in the frontend.
- Keep the existing `depth` guard so deep nesting stays readable; consider a soft depth cap warning.

---

## 11. Open decisions requiring human ratification (gating implementation)

1. **D1 — Arithmetic error semantics inside conditionals** (§3.5-1): adopt "per-branch arithmetic/type error → null" uniformly so Python/R/SAS agree despite short-circuit differences? Recommended: **yes**. Changes error behavior slightly vs a bare `derive`.
2. **D2 — Thread target `data_type` into the IR `derive` node** (§3.5-2) so SAS can pick `IFC`/`IFN`. Recommended: **yes** (small additive IR field). Alternative: SAS raises `backend_capability_missing` for conditionals, which is a worse user outcome.
3. **D3 — Rounding/modulo standard**: half-away-from-zero and truncated modulo implemented explicitly in all three backends. Recommended: **yes**.
4. **D4 — Partial-date policy**: `parse_date` accepts only full `YYYY-MM-DD`; partials → null. Confirm this matches the clinical intent, or whether partial-date components are needed (bigger scope).
5. **D5 — Non-ASCII casing** for `upper`/`lower`: invariant/ASCII only in Phase 2. Confirm acceptable.
6. **D6 — OpenAPI widening policy**: does an additive request-schema widening need an API version decision under the team's rules?

---

## 12. Phased delivery (recommendation)

- **Phase 1 — Conditional.** Smallest change that unblocks the motivating ITTFL case. Delivers: `ConditionalExpression` contract + union/version bump, evaluator branch, three codegen lowerings (with D1/D2 resolved), validation codes `expr_conditional_*`, conformance + unit + property tests, frontend conditional editor. No function catalog yet.
- **Phase 2 — Function catalog.** `FunctionCallExpression` + `ListLiteralExpression`, the §4.3 catalog, evaluator function registry, per-backend lowering tables, validation `expr_function_*`/`expr_list_literal_*`, the full conformance matrix, frontend function editor. Can ship function groups incrementally (string → null-handling → numeric → date) behind the same kind.

Each phase is independently shippable, independently conformance-gated, and additive to the saved-plan compatibility story.

---

## 4.6 Expanded catalog (second wave) — clinically-driven additions

These extend §4.3. Each is a permanent three-backend + conformance obligation, so the recommendation is to ship them in Phase 2 groups by demand (study-day/datetime first — they are the most-requested ADaM derivations). Same legend: Result `str`/`int`/`float`/`bool`/`date`/`datetime`; Compare `exact` or `tol`.

### String (second wave) — all `exact`

| Function     | Signature                                      | Behavior                                                                            | Py                      | R                                    | SAS                      | Hazard                                                                                                                                                                                                                                                                                            |
| ------------ | ---------------------------------------------- | ----------------------------------------------------------------------------------- | ----------------------- | ------------------------------------ | ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------- | ------------------------------------------------------------------------------- |
| `replace`    | `replace(str, find, with) -> str`              | replace **all** non-overlapping literal (non-regex) occurrences; null str → null    | `s.replace(find, with)` | `gsub(find, with, s, fixed=TRUE)`    | `tranwrd(s, find, with)` | **HAZARD**: `tranwrd` ignores a zero-length `find` and trims trailing blanks differently; contract forbids empty `find` (validation error). Literal, not regex.                                                                                                                                   |
| `index_of`   | `index_of(str, substr) -> int`                 | 1-based position of first occurrence, 0 if absent; null → null                      | `s.find(sub)+1`         | `regexpr(fixed=TRUE)` clamped to 0   | `index(s, sub)`          | **1-based**, 0 = not found (SAS-native). Python generator adds 1 to its 0-based `find` and maps −1→0.                                                                                                                                                                                             |
| `scan_token` | `scan_token(str, n:int, delimiter:str) -> str` | the n-th token (1-based) split on `delimiter`; out-of-range → null; null str → null | split + guard           | `strsplit` + index                   | `scan(s, n, delim)`      | **HAZARD**: SAS `scan` treats **multiple consecutive delimiters as one** and has a default delimiter set; contract pins a single explicit delimiter and "collapse consecutive delimiters" must be matched in Py/R (or chosen as a documented behavior). Needs a ratified delimiter-collapse rule. |
| `pad_left`   | `pad_left(str, width:int, fill:str) -> str`    | left-pad to `width` with single-char `fill`; longer strings unchanged; null → null  | `s.rjust(width, fill)`  | `formatC(width=, flag=)` / `sprintf` | `right(repeat(fill)      |                                                                                                                                                                                                                                                                                                   | s)`or`putn` | `fill` must be exactly one character (validation). Common for zero-padding IDs. |
| `pad_right`  | `pad_right(str, width:int, fill:str) -> str`   | right-pad to `width`; null → null                                                   | `s.ljust(width, fill)`  | `formatC(flag='-')`                  | `left(...)` composition  | same one-char `fill` rule                                                                                                                                                                                                                                                                         |

### Numeric (second wave)

| Function      | Signature                                | Behavior                                                      | Py              | R                       | SAS                                     | Compare               | Hazard                                                                                        |
| ------------- | ---------------------------------------- | ------------------------------------------------------------- | --------------- | ----------------------- | --------------------------------------- | --------------------- | --------------------------------------------------------------------------------------------- |
| `min_of`      | `min_of(x...) -> same`                   | row-wise min across args, **ignoring nulls**; all null → null | `min(non-null)` | `pmin(..., na.rm=TRUE)` | `min(of ...)` (SAS min ignores missing) | exact(int)/tol(float) | SAS `min()` already skips missing — matches contract. Py/R need explicit null-skip.           |
| `max_of`      | `max_of(x...) -> same`                   | row-wise max, ignoring nulls                                  | `max(non-null)` | `pmax(na.rm=TRUE)`      | `max(of ...)`                           | exact/tol             | same                                                                                          |
| `truncate`    | `truncate(x:float) -> int`               | toward zero (NOT floor)                                       | `math.trunc`    | `trunc`                 | `int(x)`                                | exact                 | **HAZARD**: distinct from `floor` for negatives (`truncate(-1.5)=-1`, `floor=-2`). Keep both. |
| `safe_divide` | `safe_divide(a:float, b:float) -> float` | `a/b`, but `b==0` or either null → null (never errors)        | guarded ternary | guarded `ifelse`        | `IFN(b=0 or missing, ., a/b)`           | tol                   | The null-safe counterpart to the `div` operator; avoids the div-by-zero error path entirely.  |

### Logical / null (second wave)

| Function    | Signature                | Behavior                   | Py                      | R                    | SAS                     | Hazard                                                                                                                                |
| ----------- | ------------------------ | -------------------------- | ----------------------- | -------------------- | ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| `n_missing` | `n_missing(x...) -> int` | count of null/missing args | `sum(a is None)`        | `sum(is.na(c(...)))` | `nmiss(of ...)`         | SAS `nmiss` is numeric-only; for character args use `cmiss`. Generator picks by static arg type, or restrict to numeric (validation). |
| `n_present` | `n_present(x...) -> int` | count of non-null args     | `len(args) - n_missing` | `sum(!is.na(...))`   | `n(of ...)` for numeric | same char/numeric split note                                                                                                          |

### Date / datetime (second wave) — the clinically critical group

| Function                     | Signature                                       | Behavior                                                                                                                                | Py                       | R                      | SAS                                                      | Compare | Hazard                                                                                                                                                                                                               |
| ---------------------------- | ----------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- | ------------------------ | ---------------------- | -------------------------------------------------------- | ------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `parse_datetime`             | `parse_datetime(str) -> datetime`               | parse ISO 8601 `YYYY-MM-DDThh:mm:ss` (optionally without seconds); invalid/partial → null                                               | `datetime.fromisoformat` | `as.POSIXct(tz="UTC")` | `input(x, e8601dt.)`                                     | exact   | **HAZARD**: timezone handling — contract pins **naive/UTC, no offset parsing** in Phase 2; offsets → null. SAS datetime origin differs from date origin; keep internal.                                              |
| `hour` / `minute` / `second` | `hour(datetime) -> int` (etc.)                  | component extraction; null → null                                                                                                       | `.hour` etc.             | `format(dt, "%H")`     | `hour(timepart(dt))`                                     | exact   | only on `parse_datetime` output                                                                                                                                                                                      |
| `study_day`                  | `study_day(event:date, reference:date) -> int`  | **SDTM/ADaM `--DY`**: if `event >= reference` then `event - reference + 1`, else `event - reference`. **No day 0.** null if either null | explicit formula         | explicit formula       | explicit formula                                         | exact   | **HAZARD**: the +1/no-zero rule is the whole point and is NOT a plain date diff — must be implemented identically and conformance-tested on the boundary (event == reference → 1; event == reference-1 → −1).        |
| `date_add_days`              | `date_add_days(date, n:int) -> date`            | add `n` days (negative allowed); null → null                                                                                            | `d + timedelta(n)`       | `d + n`                | `d + n` (SAS dates are day counts)                       | exact   | SAS/R date arithmetic is integer days; Python via timedelta. No DST since these are dates not datetimes.                                                                                                             |
| `date_diff_months`           | `date_diff_months(end:date, start:date) -> int` | whole-month difference (calendar months, day-of-month aware); null → null                                                               | explicit                 | explicit               | `intck('month', start, end, 'C')` with continuous option | exact   | **HAZARD**: "whole month" is ambiguous — SAS `intck` default counts boundary crossings, `'C'` counts continuous. Pin the **continuous** definition and implement explicitly in Py/R to match; ratify the exact rule. |

### 4.6.1 New supporting hazards and decisions (extend §11)

- **D7 — `scan_token` delimiter-collapse rule**: match SAS `scan` (consecutive delimiters collapse) in Py/R, or define non-collapsing and document the SAS deviation? Recommended: **collapse**, to match the SAS-native idiom clinical programmers expect. Must be ratified before implementing `scan_token`.
- **D8 — `study_day` is the flagship**: confirm the no-day-zero `--DY` convention is the required one (it is the CDISC standard; included because it is the single most common derivation that today forces free-text code — directly relevant to the "custom expression" ask).
- **D9 — `date_diff_months` definition**: continuous (true elapsed months) vs boundary-crossing count. Recommended: **continuous**; ratify.
- **D10 — datetime timezone/offset**: Phase 2 is naive/UTC only; offset-bearing `--DTC` values → null. Confirm acceptable, or defer datetime entirely to a later phase.
- **D11 — char/numeric split for `n_missing`/`min_of`/`max_of`**: restrict to a single static arg type per call (validation `expr_function_arg_type`), so the SAS generator picks the right native function. Recommended: **yes, homogeneous args only**.

### 4.6.2 Deliberately still excluded (needs scope decision, not in this feature)

- **Partial-date imputation** (`--DTC` → imputed full date with imputation flags): a policy-heavy, study-specific decision surface. Belongs in a dedicated imputation feature with its own flags, not a general expression function.
- **Regex** string ops: regex semantics differ across Py/R/SAS (PCRE vs POSIX vs SAS PRX) and are a conformance nightmare; keep `contains`/`replace`/`scan_token` literal-only.
- **Free-text / arbitrary expression**: rejected — see the new §13. Violates AGENTS.md's non-negotiable "no arbitrary expression strings" boundary; cannot compile identically to three backends; breaks determinism, provenance, isolation, and static validation.

---

## 13. Rejected alternative — free-text custom expression

A free-text code field (e.g. an author typing an R `mutate` snippet or a raw SAS expression) was requested and is **rejected for this feature**. It is recorded here so the decision is explicit, not silently dropped.

**Why it is out of scope:**

- AGENTS.md, "Compilation and execution": _"Raw Python, R, SAS, SQL, or arbitrary expression strings are invalid in every authoring model."_ This is a stated Release-1 boundary, not a style choice.
- **Breaks one-source → three-backend identity.** A snippet in one language cannot be compiled to the other two; every plan using it loses the cross-language conformance guarantee that is the core of the compilation design.
- **Breaks determinism and provenance.** Opaque expressions can reference state the canonical input fingerprint does not capture, so "reproducible for the same inputs" no longer holds.
- **Breaks isolation/security.** Free-text code is an injection vector into generated programs; the platform treats authored content as untrusted data and does not execute untrusted plugin code (AGENTS.md module-extension section).
- **Breaks static validation.** None of the §6 issue codes (arity, type, null-reasoning) apply to an opaque string.

**Sanctioned ways to get the same expressive power without the escape hatch:**

1. Grow the typed catalog on demand (this section).
2. A **named reusable typed sub-expression** ("typed macro"): compose a tree from existing kinds, name it, reuse it. Fully typed and compilable. Candidate for a follow-up feature.
3. A **reviewed extension path**: a genuinely novel operation is added as a new catalog function via a reviewed code change (modules/operators are added at code/deployment time and reviewed, per AGENTS.md) — "custom" becomes a PR, not a runtime text box.

**If arbitrary code is truly required** (a derivation that can never be typified), that is a **project-owner scope change** that reopens the Release-1 boundaries and must be decided outside this feature. The flagship driver behind most "I need custom code" requests — study-day `--DY` math — is handled by the typed `study_day` function above, which is the recommended path to satisfy the underlying need.

---

## 14. Ratified decisions (D1–D11)

All open decisions are resolved as follows and are now **binding** for implementation. This section supersedes the "needs ratification" framing in §11 and §4.6.1; those lists remain as rationale.

| ID  | Decision                                                       | Resolution (RATIFIED)                                                                                                                                                                                                                                                                                                                                                                        |
| --- | -------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| D1  | Arithmetic/type error inside a conditional branch              | **Error → null, uniformly.** All three backends swallow per-branch arithmetic/type errors (e.g. div-by-zero, bad cast) to null so results are identical despite short-circuit differences. This applies only _inside_ a `conditional`; a bare `derive` keeps its existing error behavior.                                                                                                    |
| D2  | SAS char/numeric split for conditionals                        | **Thread declared result type into the IR.** Add an optional `result_types: dict[str, Literal["character","numeric"]]` to the IR `derive` node, populated from the target variable's `data_type`. SAS codegen uses it to pick `IFC` (character) vs `IFN` (numeric). If a conditional's result type is unknown at generation time, SAS raises `backend_capability_missing` rather than guess. |
| D3  | Rounding and modulo standard                                   | **Half-away-from-zero rounding** and **truncated (dividend-sign) modulo**, implemented explicitly in Python, R, and SAS — never the language default.                                                                                                                                                                                                                                        |
| D4  | `parse_date` partial-date policy                               | **Full `YYYY-MM-DD` only; partials (`2021`, `2021-03`) → null.** Partial-date imputation is explicitly a separate future feature (§4.6.2), not this one.                                                                                                                                                                                                                                     |
| D5  | `upper`/`lower` casing                                         | **ASCII/invariant casing only** in this feature. Non-ASCII casing is out of scope; conformance fixtures still include non-ASCII input to prove the three backends agree on the defined (invariant) behavior.                                                                                                                                                                                 |
| D6  | OpenAPI widening policy                                        | **Additive, backward-compatible schema widening; no `/api/v1` version bump.** New `kind`s and function names widen the `Expression` schema without breaking existing readers. Regenerate the typed client (`npm run api:sync`) and update contract tests. (If the team later adopts a stricter request-schema policy, revisit — but the default here is additive-is-safe.)                   |
| D7  | `scan_token` delimiter handling                                | **Collapse consecutive delimiters** (SAS `scan`-native behavior). Python/R generators implement collapse explicitly to match.                                                                                                                                                                                                                                                                |
| D8  | `study_day` convention                                         | **CDISC `--DY` no-day-zero rule** confirmed: `event >= reference ? event-reference+1 : event-reference`. This is the flagship typed answer to the "custom code" need.                                                                                                                                                                                                                        |
| D9  | `date_diff_months` definition                                  | **Continuous elapsed whole months** (day-of-month aware), implemented explicitly in all three backends; do not rely on SAS `intck` default (boundary-crossing).                                                                                                                                                                                                                              |
| D10 | datetime timezone/offset                                       | **Naive/UTC only; offset-bearing values → null** in this feature. Full offset handling deferred.                                                                                                                                                                                                                                                                                             |
| D11 | Homogeneous args for `n_missing`/`n_present`/`min_of`/`max_of` | **Arguments must share one static type (all numeric or all character)** per call, enforced by validation (`expr_function_arg_type`), so the SAS generator selects the correct native function (`nmiss`/`cmiss`, `min`/`max`).                                                                                                                                                                |

### Consequence for the contract (D2)

The IR `derive` node gains:

```python
class DeriveNode(StrictModel):
    node_type: Literal["derive"]
    id: str
    assignments: dict[str, Expression] = Field(min_length=1)
    result_types: dict[str, Literal["character", "numeric"]] = Field(default_factory=dict)
```

`result_types` is keyed by assignment target name and is **optional/additive** — existing saved plans without it still parse (keeping the §9 backward-compatibility story intact). It is populated during lowering from the owning module's Specification (SDTM `SdtmVariable.data_type`), not authored by hand. When a conditional-valued assignment lacks a `result_types` entry, SAS codegen raises `backend_capability_missing` for that program (Python/R are unaffected).

### Net scope after ratification

- **Phase 1**: `ConditionalExpression` (multi-branch + mandatory else), D1/D2/D3 semantics, evaluator + three-backend codegen, `expr_conditional_*` validation, conformance/unit/property tests, frontend conditional editor, `operator_version` 1.1.0 → 1.2.0.
- **Phase 2**: `FunctionCallExpression` + `ListLiteralExpression`, the full §4.3 + §4.6 catalog under D4–D11, evaluator function registry, per-backend lowering tables, `expr_function_*`/`expr_list_literal_*` validation, full conformance matrix, frontend function editor. Shippable in groups: date/study-day first (highest demand), then string, numeric, null-handling.
- **Rejected**: free-text/arbitrary expression (§13) — unchanged; needs a project-owner scope change if ever revisited.
