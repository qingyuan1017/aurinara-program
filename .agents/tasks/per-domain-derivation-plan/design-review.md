# Design Review — Per-Domain SDTM / Per-Dataset ADaM Derivation Plans

Reviewed design: `.agents/tasks/per-domain-derivation-plan/design.md` (fifth iteration — final confirmation pass).
Scope of this pass: confirm the five fixes requested after the fourth-iteration review were applied correctly and introduced no new HIGH/MEDIUM defect. The settled per-domain/per-dataset requirements and the staleness mechanism (server-resolved `upstream_plan_pins` + `upstream_plan_changed` + transitive propagation + aggregate-row `FOR UPDATE` lock) are user-approved and were NOT re-litigated.

## Summary

All five fourth-iteration findings are resolved correctly, and each fix is reflected consistently across every section that must agree (the normative section, the §8 error table, the §10 test plan, and the §15 resolution log). No new HIGH or MEDIUM defect was introduced by the edits. Verdict: **APPROVED**.

---

## Confirmation of the five requested fixes

### MEDIUM #1 — never-authored-sibling read-node pin — CONFIRMED FIXED

- **§6 step 2** now carries a dedicated "Never-authored sibling (fourth-iteration Finding 1)" paragraph: at `PUT`, a `sdtm_read`/`adam_read` referencing a Specification-declared sibling with **no plan row** is rejected with `409 sdtm_plan_upstream_misaligned` (ADaM `409 adam_plan_upstream_misaligned`) carrying `upstream_state: "absent"`. It correctly frames this as a state distinct from "sibling misaligned" (no revision to pin, no `state` to check) and notes that §4 rule 1 validates only Specification membership, not plan existence — the exact gap the prior finding identified. The two upstream states are explicitly distinguished by the `upstream_state` field (`"absent"` vs the step-4 stale states).
- **§8 error table** has the matching row: "a pinned sibling has no plan row (never authored)" → `409 sdtm_plan_upstream_misaligned {domain, upstream_code, upstream_state: "absent"}` (ADaM equivalent noted), recoverable, logged at info. It sits alongside the separate "a pinned sibling is not aligned at pin time" row, so the two states are not conflated.
- **§10 unit test** is called out: "Never-authored sibling (fourth-iteration Finding 1)" asserts the `PUT` is rejected with `upstream_state: "absent"` (distinct from the misaligned case) and then succeeds once the sibling is authored and aligned.

The remediation ("author/align the upstream first") matches the existing upstream-first ordering, so reusing the existing code with a discriminating `upstream_state` is coherent.

### MEDIUM #2 — §4.7 concurrency/alignment-parity rewrite + `derivation_plan_alignment_required` fate — CONFIRMED FIXED

- **§9 §4.7 edit** adds the bullet "Rewrite the concurrency / alignment-parity sentence (fourth-iteration Finding 2)": it states the plan is now a per-domain (SDTM) / per-dataset (ADaM) sub-resource whose `If-Match`/`ETag` is the per-domain/per-dataset plan revision, **distinct** from the aggregate Specification/input (`workbench.revision`) token; that spec/input writes do not change a plan ETag and instead surface staleness via `alignment_state`; and that atomic replacement now applies per plan. It also preserves the "SDTM and ADaM stay symmetric with each other" claim while dropping the invalidated Specification-parity claim — consistent with §3.1/§3.2.
- The "Reconcile the documented alignment code" bullet states the fate of `derivation_plan_alignment_required`: it was never implemented (the code uses `sdtm_plan_misaligned`/`sdtm_plan_alignment`), so this is a **pre-existing divergence**; the rewrite documents the implemented codes plus the new `sdtm_plan_upstream_misaligned`/`adam_plan_upstream_misaligned` and removes the never-implemented placeholder as a deliberate reconciliation (not a silent drop).

### MEDIUM #3 — §4.7 `alignment_reasons` enumeration rewrite — CONFIRMED FIXED

- **§9 §4.7 edit** adds "Replace the `alignment_reasons` enumeration sentence (fourth-iteration Finding 3)" with the exact verbatim replacement: "`alignment_reasons` is a list drawn from `specification_changed`, `input_changed`, and `upstream_plan_changed`, empty iff `alignment_state == current`." It is explicitly part of the enumerated §4.7 edit list (not deferred to the §9.3 route paragraph), closing the residual two-value-vs-three-value contradiction inside the section being reconciled. This matches the persisted-column invariant in §2.3 and the reason set used by the §3.4 refresh sites and §6 step 3.

### NIT #4 — §3.4 `context_snapshot` `schema_version` decision — CONFIRMED FIXED

- **§3.4** adds "`context_snapshot` `schema_version` bump (fourth-iteration Finding 4)": the string is **bumped from `"1.0.0"` to `"1.1.0"`** in lockstep with the `plan_revisions` map + `plan_set_fingerprint` shape change, with the ADaM-side matcher updated in the same change (so no runtime break). It records that the context export is a transient cross-module DTO (plain string, no migration, consumer does not pin the value) and that the other unrelated `"1.0.0"` literals in `service.py` are left untouched. The decision is stated, which is all the NIT required.

### NIT #5 — §2.6 step 7 downgrade guard — CONFIRMED FIXED

- **§2.6 step 7** restates the guard precisely under "Precise guard (fourth-iteration Finding 5)": downgrade raises if any `aggregate_id` has plan rows spanning **more than one distinct `domain_code`** (SDTM) / `dataset_code` (ADaM), **or** if any row carries injected `sdtm_read`/`adam_read` pins (`upstream_plan_pins` non-empty or a read node in the payload). The only safely-reversible case is a single-`domain_code`/`dataset_code` aggregate (possibly with multiple revisions of that one domain) with no injected read pins. This replaces the imprecise ">1 plan row per aggregate_id" predicate that would have fired on a never-split aggregate that merely accumulated revisions. The §8 error-table downgrade row matches the restated predicate.

---

## Check for newly introduced HIGH/MEDIUM defects

I inspected every section the five edits touched for internal contradictions or regressions and found none:

- The `upstream_state` discriminator is used consistently: step-2 absent/misaligned cases carry `upstream_state`; the step-4 stale case carries `{domain, upstream_code, pinned_revision, current_revision}`. The §8 table rows reflect each distinct failure condition without overlap.
- The §9 §4.7 "symmetric with each other" wording does not contradict the dropped Specification-parity claim; §3.1/§3.2 already establish spec/input keep `workbench.revision` while plan writes do not touch it.
- The restated §2.6 downgrade predicate is consistent between §2.6 step 7 and the §8 error-table downgrade row.
- The bumped context `schema_version` is coherent with the §3.4 ADaM matcher update (reads the new keys) and does not affect any persisted/typed JSONB `Literal` contract.
- The three-value `alignment_reasons` enumeration in §9 §4.7 agrees with §2.3, §3.4, and §6 step 3.

---

## Verified Assumptions

- §6 step 2 contains the never-authored-sibling rejection with `upstream_state: "absent"` and the symmetric ADaM code. (design.md §6 step 2)
- §8 error table contains both the "sibling not aligned at pin time" and the distinct "sibling has no plan row (never authored)" rows, the latter carrying `upstream_state: "absent"`. (design.md §8)
- §10 unit-test list calls out the never-authored-sibling test explicitly. (design.md §10, Unit)
- §9 §4.7 edit rewrites the concurrency/alignment-parity sentence and states the per-domain/per-dataset ETag is distinct from the Spec/input token, with spec/input staleness surfaced via `alignment_state` and per-plan atomic replace. (design.md §9)
- §9 §4.7 edit records `derivation_plan_alignment_required` as a never-implemented placeholder removed in favor of the implemented `sdtm_plan_misaligned`/`sdtm_plan_alignment` + new `sdtm_plan_upstream_misaligned`. (design.md §9)
- §9 §4.7 edit replaces the enumeration sentence with the three-value `{specification_changed, input_changed, upstream_plan_changed}`, empty iff `alignment_state == current`, as part of the enumerated edit list. (design.md §9)
- §3.4 states the context `schema_version` is bumped to `"1.1.0"` with rationale and ADaM-matcher lockstep. (design.md §3.4)
- §2.6 step 7 restates the downgrade guard on distinct `domain_code`/`dataset_code` and injected read pins; §8 table matches. (design.md §2.6, §8)

## Unverified / Wrong Assumptions in the Design

- None. This pass was scoped to the five document edits; each was located in the normative section and cross-checked against the §8 error table, §10 test plan, and §15 resolution log, and all agree. No code was re-read this pass per the review instruction (document-only review); the fourth-iteration pass already confirmed the underlying "verified in code" claims.

---

## Verdict

HIGH findings: 0. MEDIUM findings: 0. NIT findings: 0.

All five requested fixes are applied correctly and no new HIGH/MEDIUM defect was introduced ⇒ **APPROVED**.
