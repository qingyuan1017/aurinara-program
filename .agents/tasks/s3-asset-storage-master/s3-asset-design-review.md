# Design Review: Pinned Provider Assets in S3-Compatible Object Storage

Reviewed document: `.agents/tasks/s3-asset-storage-master/s3-asset-design.md`
Reviewed against: `AGENTS.md`, `docs/architecture.md`, `docs/artifact-catalog.md`, and the
actual source at the named seams.

This is a fresh, independent review. Every claim the design makes about existing code was
re-checked against the source rather than taken on the design's word. The design is
careful, internally consistent, and gets the module-ownership, checksum-gate,
OpenAPI-stability, upload-path, admin-command, typed-error, and dev-fallback shape right.
One HIGH defect was found that would crash the primary migration path for the ~25k corpus,
plus a few MEDIUM precision gaps and some NITs.

Verdict is mechanical: HIGH + MEDIUM > 0 → **CHANGES_REQUESTED**.

---

## Findings

### 1. HIGH — Version/release "manifest object" publish and backfill will crash on the ~25k library-snapshot corpus because `StandardVersion.checksum` / `TerminologyRelease.checksum` is a synthetic group digest, not a file sha256

Where: Decision 3 ("Manifest-file media type (Finding 3)" and the library-snapshot bullet),
Decision 5 (`publish-assets` streaming `standard_versions` / `terminology_releases` and
calling `verify_repository_asset(..., asset.asset_path, asset.checksum, ...)`), and "Exact
files" items 6 and 7.

The design repeatedly assumes the version/release checksum is the sha256 of a real on-disk
file (the "manifest/version object") that can be published and later re-verified via
`verify_repository_asset(..., version.asset_path, version.checksum)`. I verified this is
true only for the hand-maintained importers and **false for the bulk corpus**:

- `src/app/standards/importer.py` → `StandardVersion.checksum = manifest_checksum`
  (= sha256 of the real manifest file). OK.
- `src/app/terminology/importer.py` → `TerminologyRelease.checksum = checksum`
  (= sha256 of the real manifest file). OK — but this path creates **no** `TerminologyAsset`
  rows at all (see Finding 3).
- `src/app/cdisc_library_registry.py` → `_register_standard_group` sets
  `checksum=_group_checksum(resources)` with `asset_path=manifest_path...`, and
  `_register_terminology_group` sets `checksum=_group_checksum(resources)` with
  `asset_path=root_resource.asset_path`. `_group_checksum` is
  `sha256_hex(canonical_json([{href, sha256} ...]))` — a **synthetic digest over the group
  inventory**, not the sha256 of the file named by `asset_path`.

Consequence: for every library-snapshot `StandardVersion` / `TerminologyRelease` row (the
entire ~25k + 215 corpus), `checksum_object_key(version.checksum)` points at a key whose
bytes do not and cannot exist as a file, and `verify_repository_asset(REPOSITORY_ROOT,
version.asset_path, version.checksum, allowed_root=...)` will raise
`repository asset checksum mismatch` because the file's real sha256 ≠ the stored group
digest. So:

- the Decision 3 inline publish of the "version/release object" cannot succeed for the
  bulk path, and
- `publish-assets` (Decision 5) will raise on the first library-snapshot version/release
  row it tries to back-fill, defeating the resumable migration this whole task exists for.

This is not merely cosmetic: the content endpoints (`/standard-assets/{id}/content`,
`/terminology-assets/{id}/content`, verified in `src/app/api/catalogs.py`) only ever derive
their key from the **per-asset** `StandardAsset.checksum` / `TerminologyAsset.checksum`
(= `item.sha256`, real files). No read path ever fetches bytes keyed by the
version/release checksum. So the version/release "object" is both impossible to produce for
the bulk path and unnecessary for every reader.

Concrete fix (choose one, state it in the design):

- Preferred: **do not treat the version/release checksum as a publishable file object.**
  Publish only objects whose checksum is a real file sha256 — i.e. the per-asset
  `StandardAsset` / `TerminologyAsset` rows (whose `checksum == item.sha256`) plus, for the
  hand-maintained importers only, the manifest file (whose checksum equals the stored
  `StandardVersion.checksum` / `TerminologyRelease.checksum` on _those_ paths). For
  `publish-assets`, skip `standard_versions` / `terminology_releases` rows whose stored
  checksum is a group digest; or detect the mismatch (`actual != stored`) and treat the
  version/release row as "no own file object" rather than erroring.
- Alternative: publish the manifest file under `checksum_object_key(sha256_of_manifest_file)`
  (a _recomputed_ file digest), and keep the stored group-digest column purely as the
  integrity/identity value it already is. But since no reader keys off it, this adds an
  object nothing reads.

Either way the design must stop asserting "the manifest-file checksum is persisted on
`StandardVersion.checksum` / `TerminologyRelease.checksum`" as a universal truth; that holds
only for the hand-maintained importer paths, not for `register_library_snapshot`.

### 2. MEDIUM — Terminology importer publish instruction references `manifest.assets` and per-asset `TerminologyAsset` rows that this path never creates

Where: Decision 3 "What the publish pass must cover (Finding 4)" and "Exact files" item 7:
"publish one object per distinct checksum among {manifest file} ∪ {every `manifest.assets`
entry that becomes a `StandardAsset`/`TerminologyAsset` row}".

Verified against `src/app/terminology/importer.py`: `import_terminology_manifest` creates
`TerminologyRelease`, `TerminologyCodelist`, and `TerminologyTerm` rows only — it creates
**no `TerminologyAsset` rows**, and the terminology manifest contract has no `assets`
collection to iterate. So the "publish every per-asset terminology row" instruction is
inapplicable on the hand-maintained CT path and will mislead the implementer into looking
for a `manifest.assets` that does not exist there. (`TerminologyAsset` rows exist only on
the library-snapshot path, created by `_register_terminology_group`, where `item.sha256`
is a real file.)

Concrete fix: scope the Finding-4 rule per path. State explicitly:

- hand-maintained standards importer: publish each `StandardAsset` (`asset.sha256`) + the
  manifest file;
- hand-maintained terminology importer: publish the manifest file only (no per-asset rows
  exist);
- library snapshot: publish each `StandardAsset` / `TerminologyAsset` (`item.sha256`); the
  version/release row has no own file object (see Finding 1).

### 3. MEDIUM — "catalog_seed publishes at each session.add site" is ambiguous about the idempotency guard, which determines whether a DB-exists/object-missing state ever self-heals

Where: Decision 3 "`_checksum` stays pure (Finding 6)" and "Exact files" item 5: "publish
at each `session.add(...)` site ... before (or alongside) that asset's `session.add`".

Verified against `src/app/catalog_seed.py`: every `session.add(...)` for the four pinned
assets is nested inside an `if session.get(...) is None:` guard. If the publish call is
placed _inside_ that guard (the natural reading of "at the `session.add` site"), then on a
DB that already has the rows but is missing the objects (exactly the pre-existing-corpus
case this feature targets), `seed()` will **skip publishing** and silently leave the
objects absent — relying entirely on `publish-assets` to recover. If placed _outside_ the
guard, re-seeding re-publishes (a harmless content-addressed no-op). The design does not say
which, and the two behaviors differ in whether a fresh `seed()` on a half-migrated DB
self-heals.

Concrete fix: state the placement explicitly. Recommended: publish **outside / before** the
`if session.get(...) is None:` guard (unconditionally, using the resolved `*_path` and
`_checksum(*_path)`), so `seed()` is self-healing for the DB-exists/object-missing case and
remains an idempotent no-op otherwise. Keep the single terminal `session.commit()`.

### 4. MEDIUM — `object_missing` and `storage_error` collapse to the same `503` code `asset_content_unavailable`, which the design elsewhere insists must be distinguishable

Where: Decision 6 error-mapping table — both `object_missing` and `storage_error` map to
`503 asset_content_unavailable`.

Decision 0's whole justification is that the two conditions "must be told apart" and that
parsing human-readable messages to recover the distinction is forbidden by AGENTS.md.
The design preserves the distinction all the way to `AssetContentError.reason` and then
discards it at the HTTP boundary by emitting the same `code`. A client or operator seeing
`asset_content_unavailable` cannot tell "run the publish step" (deployment state) from
"object storage is down" (transient infra) — which is precisely the operational signal
Decision 6's own rationale says each status should carry. The AGENTS.md validation/issue
guidance ("issue codes are stable machine-readable identifiers ... do not encode control
flow by parsing messages") applies in spirit to problem `code`s too.

Concrete fix: give them distinct stable codes while keeping both `503`, e.g.
`object_missing` → `asset_content_unpublished` ("run the publish-assets admin step") and
`storage_error` → `asset_content_store_unavailable` ("object storage could not be
reached"). Update the Decision 6 table, the contract-test assertions, and the "Open
ambiguities, resolved" item 8 accordingly.

### 5. NIT — "established sibling-route pattern" for `request.app.state.settings` is slightly overstated for `catalogs.py`

Where: Decision 6 / "Exact files" item 3: "read `settings = request.app.state.settings`
(the established sibling-route pattern, no new `get_settings` dependency)".

Verified: `request.app.state.settings` is a real, established platform pattern
(`src/app/artifacts/routes.py`, `src/app/integration/routes.py`), and `app.state.settings`
is set in `create_app`. But it is **not** currently used anywhere in `src/app/api/catalogs.py`
— the content handlers today take neither `Request` nor a settings/storage dependency. The
mechanism is sound; the "sibling-route" wording implies a precedent inside this file that
does not exist. Minor, no behavior impact.

Concrete fix: reword to "the established platform pattern (used in artifacts/integration
routes)"; and note that both content handlers must newly add `request: Request` and the
`get_object_storage` dependency.

### 6. NIT — `load_presentation_template` missing-row error is a bare `RuntimeError`, and the design describes it as both unchanged and as surfacing through the Decision 6 problem mapping

Where: Decision 2b ("Raise the existing `template version is missing` error here if the row
is absent (unchanged, session-only check)").

Verified against `src/app/documents/service.py`: the current raise is
`raise RuntimeError("validated Template version is missing")` (note: "validated Template
version is missing", not "template version is missing"). It is a bare `RuntimeError`, not a
`ProblemException`, so if it ever reaches the API boundary it becomes a generic 500 via
`unexpected_exception_handler` — the same anti-pattern Decision 6 is otherwise eliminating
for `not_json_object`. In the phase split this raise moves to `build_artifact_payload`
(session phase), which runs in the worker, so it is not directly a request-path 500; but
the design should not imply it participates in the typed Decision 6 mapping.

Concrete fix: quote the error text accurately and state plainly that this missing-row raise
stays a worker-phase `RuntimeError` (unchanged, not part of the content-error HTTP mapping);
the Decision 6 mapping covers only `AssetContentError` surfacing from the byte read.

---

## Verified Assumptions (checked against source)

- `verify_repository_asset(repository_root, relative_path, expected_sha256, *, allowed_root)`
  exists in `src/app/common/repository_assets.py`, resolves a safe path under
  `allowed_root`, re-reads bytes, recomputes sha256, and raises on mismatch — exactly as the
  design relies on for the dev-fallback double-gate.
- `src/app/artifacts/storage.py` `S3ObjectStorage.open` **does** collapse `NoSuchKey` and
  `BotoCoreError`/`ClientError` into one `ObjectStorageError("object download failed")`;
  the `ObjectStorage` Protocol has only `put_file`/`open`/`check`; `checksum_object_key`
  returns `sha256/<aa>/<bb>/<sha256>`. Decision 0's typed-error + `exists` extension is
  necessary and correctly scoped.
- `src/app/api/catalogs.py` content endpoints `GET /standard-assets/{id}/content` and
  `/terminology-assets/{id}/content` are declared `response_model=dict[str, object]`, call
  `verify_repository_asset(... allowed_root="schemas"|"terminology")`, `json.loads`, and
  raise a bare `RuntimeError` when the payload is not a dict — matching the design's "replace
  this exact block" and the OpenAPI-unchanged claim. The handlers do **not** currently take
  `Request`/storage (relevant to Finding 5).
- Content endpoints key only off the **per-asset** `StandardAsset.checksum` /
  `TerminologyAsset.checksum`; no read path uses the version/release checksum (central to
  Finding 1).
- `src/app/documents/service.py`: `load_presentation_template(session, template_version_id)`
  is called only from `build_artifact_payload` (has `session`, no `storage`);
  `render_artifact(self, payload, storage)` has `storage`, no `session`; the render phase
  reads `payload.get("presentation_template")`. The capability signatures in
  `src/app/artifacts/builds.py` (`build_artifact_payload(session, aggregate_id, study_id,
artifact_type)`, `render_artifact(payload, storage)`) match. The phase split is feasible
  with no protocol change, as claimed.
- `workers/job_worker.py` `main()` constructs `storage = S3ObjectStorage(settings)` with
  `settings` in scope — the exact seam Decision 0/4 use to carry `local_fallback_enabled`
  into the render phase. `src/app/main.py` constructs it for the API and accepts an injected
  `object_storage` (so test fakes carrying `local_fallback_enabled` work).
- `src/app/config.py` `reject_unsafe_production_configuration` appends labels to an `unsafe`
  list and raises when non-empty in production — Decision 4's new check fits the pattern
  exactly.
- `src/app/cdisc_registry.py` `_register_snapshot` / `_register_manifests` call the
  registration functions **inside** `with factory.begin() as session:`; the importers and
  `register_library_snapshot` perform `verify_repository_asset` + inserts under that
  caller-owned transaction. The design's publish-before-txn / inserts-only refactor is
  feasible and aligns with the AGENTS.md "no object-store I/O inside a DB transaction" rule.
- `src/app/catalog_seed.py` creates exactly four pinned JSON assets
  (`dependency-selection-1.0.0.json`, `issue-severity-1.0.0.json`, `report-layout-1.0.0.json`,
  `document-layout-2.0.0.json`) and commits once; `_checksum(path)` is pure (hash + root
  check, no I/O injection). Findings 5/6 of the prior pass are consistent with the source.
- `tests/integration/test_phase1_core.py` `MemoryStorage.open` does
  `io.BytesIO(self.objects[object_key])`, raising a bare `KeyError` on a miss, and has no
  `exists`/`local_fallback_enabled` — so Decision 0's test-fake-parity update is required
  and correctly described.
- `src/app/api/health.py` readiness probes storage via `storage.check()` (bucket
  reachability) only; `get_object_storage` resolves `app.state.object_storage`. The
  "readiness unchanged; content availability surfaced per-request as 503" claim holds.
- `src/app/common/problems.py` registers `unexpected_exception_handler` for `Exception`, so
  today's bare `RuntimeError` non-JSON-object case does fall through to a generic 500 — the
  design's motivation for the typed `not_json_object` mapping is accurate.
- `docs/artifact-catalog.md`: `support/standards/` / `support/terminology/` are
  submission-package placements for generated manifest artifacts, not runtime storage of
  pinned provider-asset content; no per-asset "pinned assets live on local disk" statement
  exists. The "no artifact-catalog change" claim is correct.
- `src/app/standards/library_snapshot.py` resource `sha256` field is
  `Field(pattern=r"^[0-9a-f]{64}$")` and `media_type` is `Literal["application/json"]` —
  the design's external-input-validation and media-type claims are accurate.

## Unverified / Wrong Assumptions

- **WRONG:** "the manifest-file checksum ... is persisted on `StandardVersion.checksum` /
  `TerminologyRelease.checksum` as the integrity source of truth and is read back by the
  content endpoints." For the ~25k library-snapshot corpus these columns hold
  `_group_checksum(resources)` (a synthetic inventory digest, not a file sha256), and **no**
  content endpoint reads bytes by the version/release checksum. (Finding 1.)
- **WRONG / inapplicable:** `import_terminology_manifest` iterating `manifest.assets` to
  publish per-asset `TerminologyAsset` rows — this path creates no `TerminologyAsset` rows
  and the CT manifest has no `assets` collection. (Finding 2.)
- **IMPRECISE:** `request.app.state.settings` as "the established sibling-route pattern" in
  `catalogs.py` — it is a valid platform pattern but is not currently used in that file.
  (Finding 5.)
- **IMPRECISE:** the template-missing raise described as "the existing `template version is
missing` error"; the actual text is `RuntimeError("validated Template version is missing")`
  and it is a bare `RuntimeError`, not a typed problem. (Finding 6.)
- **NOT VERIFIED (out of review scope):** the exact `--batch-size` / resumability wording of
  `snapshot-all`'s progress callback that `publish-assets` says it "mirrors" was not
  line-checked beyond confirming `_snapshot_all` has a `progress(count, href)` callback; the
  claim is plausible and not load-bearing for correctness.

---

## Verdict

HIGH: 1 (Finding 1). MEDIUM: 3 (Findings 2, 3, 4). NIT: 2 (Findings 5, 6).

HIGH + MEDIUM = 4 > 0 → **CHANGES_REQUESTED**.
