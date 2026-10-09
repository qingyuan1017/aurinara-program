# Raw artifact-build fingerprint preview endpoint

Fixes the confirmed `409 stale_input_fingerprint` that blocked every Raw artifact build. The Artifacts panel was sending the dependency-selection fingerprint as `expected_input_fingerprint`, a hash over a different structure than the server's resolved build input, so the two could never match. The fix exposes a read-only preview endpoint (`POST /api/v1/raw/{raw_id}/artifacts/fingerprint`) that returns the exact resolved build-input fingerprint, factors a shared `resolve_build_fingerprint` helper in Artifacts so the build handler and the preview compute through one path, and rewires the panel to fetch the correct value per build attempt. The server staleness guard is preserved unchanged.

Watch for: one test-coverage gap — the committed negative-path assertions (422 unsupported type, 404/403 access) for the new endpoint live only in a temporary test that was removed; the happy round-trip is covered by the Docker integration test (likely). No correctness or boundary concerns.

**Verdict**: APPROVED

## High-level view

The two fingerprints now share one code path. `resolve_build_fingerprint` wraps the existing `resolve_build_input(...)` + `fingerprint(resolved)` that `create_artifact_build` previously ran inline; both the build handler and the preview endpoint call it, so the value the client is handed and the value the staleness check recomputes are the same by construction. Drift is structurally impossible as long as both pass the same owner tuple — and they do: `owner_type="raw_workbench"`, `owner_id=raw.id`, `options={}` in both the preview route and `create_raw_artifacts`.

Module boundaries hold. Fingerprint computation stays in Artifacts; the Raw route imports the helper through a normal module import and does not touch another module's repository. Nothing clinical leaked into `common`.

The route is a thin, correct sibling of `create_raw_artifacts`: same `_raw(...)` access resolution, same `RAW_ARTIFACT_TYPES` 422 guard, Pydantic 2 models with snake_case JSON, `extra="forbid"` on the request, no `expected_input_fingerprint` in the body, a `{ input_fingerprint }` response, synchronous 200, and no Idempotency-Key. The staleness guard in the build handler is untouched.

The frontend fetches the fingerprint for the exact selected artifact-type set at build click, inside the existing try/catch so a preview failure surfaces as the same start-error toast. Build stays disabled until at least one type is selected, the per-attempt Idempotency-Key is unchanged, submit order follows the fixed `RAW_ARTIFACT_TYPES`, and 202 polling via `OperationRunner` is untouched. The old `useGetRawDependencies` fingerprint source is fully removed with no dead references.

The one gap is in committed tests: the round-trip proof (fingerprint accepted by the build, no 409) is in the Docker-backed integration test, and the contract suite only asserts the route is present in the OpenAPI surface. The negative-path checks the plan describes running were in a throwaway test that is not in the tree.

<details>
<summary>Issues (1)</summary>

1. **No committed negative-path test for the preview endpoint** — the 422 unsupported-type and access-denied cases for `/raw/{raw_id}/artifacts/fingerprint` are only exercised by a temporary test that was removed; the paths are reused from already-tested code, so this is non-blocking, but a dedicated contract/integration case would close the TESTS criterion.

</details>

<details>
<summary>Details</summary>

## Shared helper makes the two fingerprints inseparable

The core of the fix. `resolve_build_fingerprint` in `src/app/artifacts/builds.py` is a thin wrapper that calls the existing `resolve_build_input(...)` and returns `(fingerprint(resolved), module_key, handler, resolved)`. `create_artifact_build` was refactored from

```python
module_key, _, resolved = resolve_build_input(...)
input_fingerprint = fingerprint(resolved)
```

to

```python
input_fingerprint, module_key, _, _ = resolve_build_fingerprint(...)
```

Behavior is identical — same `resolved` shape, same `fingerprint`, `module_key` still available for the build row. The preview endpoint calls the same helper. Because the helper returns the resolved values rather than only the hash, `create_artifact_build` avoids a second resolution pass. The `!= command.expected_input_fingerprint → 409` guard is byte-for-byte unchanged, so the fix hands the client the correct expected value without weakening the check. The endpoint does not re-implement resolution or canonicalization anywhere.

## Owner tuple parity is what guarantees the match

A shared helper only prevents drift if both callers pass the same inputs. They do: `create_raw_artifacts` builds its `ArtifactBuildCreate` with `owner_type="raw_workbench"`, `owner_id=raw.id`, `options={}`, and the preview route passes the identical triple to `resolve_build_fingerprint`. Both resolve the workbench and study access through the same `_raw(session, registry, raw_id, principal)` call, and both apply the same `sorted(set(command.artifact_types) - set(RAW_ARTIFACT_TYPES))` 422 guard before resolving. Given the same selected set, the preview output equals the value `create_artifact_build` recomputes.

## Thin route, correct conventions

The handler authenticates via the shared `get_principal` dependency, parses into `RawArtifactFingerprintRequest`, resolves access, applies the artifact-type guard, calls the one helper, and translates to `RawArtifactFingerprintResponse`. `RawArtifactFingerprintRequest` sets `extra="forbid"` and `artifact_types: tuple[str, ...] = Field(min_length=1)` with no `expected_input_fingerprint` field; the response is `{ input_fingerprint: str }`. Default 200, no `status_code=202`, no Idempotency-Key header. The 422s from the type guard and from `resolve_build_input` (invalid owner/type) propagate as RFC 9457 problems through the existing exception handling.

## Frontend rewired per-attempt, no cached study-wide value

`handleStart` computes the ordered `artifactTypes` from the fixed `RAW_ARTIFACT_TYPES` and the selected set, calls `idempotency.begin()`, then inside a try/catch awaits `previewFingerprint.mutateAsync({ rawId, data: { artifact_types } })` and passes the returned `input_fingerprint` into `create.mutateAsync` as `expected_input_fingerprint`. The fingerprint is fetched for the exact selected set at build time rather than cached, which is correct because the hash depends on the set. `canStart = !noneSelected && !previewFingerprint.isPending && !create.isPending` keeps Build disabled until at least one type is selected and while either request is in flight. The preview fetch shares the build's try/catch, so a preview failure raises the same start-error toast via `parseProblem`. Idempotency key handling, submit order, and the `OperationRunner` 202 polling path are untouched. `useGetRawDependencies` and its `inputFingerprint`/`dependenciesQuery` UI are gone — grep finds no remaining references.

## Contract and client consistency

`docs/api-contract.md` lists the route in the Raw block above `POST /api/v1/raw/{raw_id}/artifacts` and documents it as a read-only preview: accepts `{ artifact_types: [...] }` (≥1 from the fixed set), returns `200` with `{ input_fingerprint: "<64 hex>" }` computed from the same resolved inputs as the build, requires study access, persists nothing, needs no Idempotency-Key, 422 for unsupported/invalid types or owner. The typed-client fixture (`tests/contract/typed_client_fixture.py`) adds `"/api/v1/raw/{raw_id}/artifacts/fingerprint": frozenset({"post"})`. The Orval regen produced `rawArtifactFingerprintRequest.ts`, `rawArtifactFingerprintResponse.ts`, and the `previewRawArtifactFingerprint` / `usePreviewRawArtifactFingerprint` mutation in `raw/raw.ts` with a `{ rawId, data }` signature matching the panel call — standard generator output, not hand-edited. The regen also refreshed previously-drifted SDTM/aCRF/define/csdrg client surface, which explains the large `openapi.json` and model-file churn in the diff; that is generator output, consistent with the plan.

## Test coverage

The helper refactor has a focused unit test (`tests/unit/test_artifacts_builds.py`) that monkeypatches `resolve_build_input` to a known `resolved` dict and asserts `resolve_build_fingerprint` returns exactly `fingerprint(resolved)` along with the propagated `module_key`/`handler`/`resolved` and the forwarded kwargs — directly pinning the no-drift invariant. The Docker-backed integration test (`tests/integration/test_phase3_raw_sdtm.py`) now obtains the expected fingerprint from the preview endpoint and uses it on the build, asserting `200` then `202` then `succeeded` — the end-to-end proof that the round-trip no longer 409s.

Not tested (committed): the endpoint's own negative paths — 422 for an unsupported artifact type and the access-denied case — exist only in a temporary script the author ran during verification and then removed (per the plan's Verification section). Those paths are reused verbatim from `create_raw_artifacts` (the type guard) and the shared `_raw(...)` resolver (access), both exercised elsewhere, so the risk is low; a dedicated case would nonetheless satisfy the stated TESTS criterion cleanly.

## Verification evidence

The plan's Verification section records specific, non-generic evidence: `ruff check`, `ruff format --check`, `mypy src` clean; `pytest tests/unit tests/contract` → 101 passed; the Postgres-backed `tests/integration/test_phase3_raw_sdtm.py` → 2 passed including the Raw build accepted (202) and `succeeded` via the preview fingerprint; frontend `typecheck`/`lint` pass and `vitest` → 275 passed including the updated ArtifactsPanel cases. It also notes an `APP_ENV` shell-leak artifact and a cleared stale Postgres backend, neither a code regression. Nothing in the evidence raises a specific doubt warranting a re-run.

</details>

<details>
<summary>File map</summary>

- `src/app/artifacts/builds.py` — new `resolve_build_fingerprint` helper; `create_artifact_build` refactored to use it; staleness guard unchanged.
- `src/app/raw/routes.py` — new request/response models and thin `preview_raw_artifact_fingerprint` route; imports the helper.
- `tests/unit/test_artifacts_builds.py` — unit test pinning helper/`fingerprint(resolved)` equivalence.
- `tests/contract/typed_client_fixture.py` — asserts the new route in the typed-client surface.
- `tests/integration/test_phase3_raw_sdtm.py` — Raw build now driven by the preview fingerprint; round-trip assertion (Docker).
- `docs/api-contract.md` — documents the new route alongside its Raw siblings.
- `frontend/src/components/workbench/artifacts-panel.tsx` — fetches the fingerprint per attempt; removed `useGetRawDependencies` source.
- `frontend/openapi.json`, `frontend/src/api/generated/**` — Orval regen output (new models/hook plus refreshed drifted surface).

Full diff: `git show b2d0e2d`.

</details>
