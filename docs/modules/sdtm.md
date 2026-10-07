# SDTM module

Status: Phase 3 authoring, preview, execution, XPT, aCRF, version-neutral Define with 2.0/2.1
rendering, and cSDRG slices implemented. It
provides exact Raw input selection, atomic Specification and Derivation Plan revisions,
alignment enforcement, validation, lineage, immutable Python/R/SAS program artifacts, isolated
Python/R execution, XPT v5 outputs, and persisted typed aCRF annotations.

## Select exact Raw inputs

Create the SDTM workbench, then `PUT /sdtms/{id}/input-selection` with its current `ETag`.
The request names an exact Raw workbench/revision, successful Raw validation run, Raw
dependency fingerprint, and every selected source-file artifact ID/checksum. The module
resolves these through Raw's registered context-export capability; it never queries Raw
repositories directly or substitutes a newer file.

`GET /sdtms/{id}/raw-context` returns the verified immutable context DTO. Any Raw dataset,
variable, or file-binding change marks the selection `input_refresh_required`, marks the
current plan `misaligned`, and stales SDTM artifacts without rewriting authored content.

## Author the Specification

`PUT /sdtms/{id}/specification` requires `If-Match` and replaces one complete versioned
contract atomically. Domains own their variables, value-level metadata, keys, sort order,
expected output name, roles, origins, and exact terminology bindings. Natural keys and all
internal references are validated before the immutable revision is committed.

JSON or XLSX import uses `POST /sdtms/{id}/specification/import`; it requires the current
`If-Match` value and an `Idempotency-Key`. XLSX uses the versioned `Metadata`, `Domains`,
`Variables`, and `ValueLevel` sheets. Keys, sort order, typed conditions, and terminology bindings
are serialized explicitly rather than inferred from display formatting. Every sheet and
cross-sheet reference is validated before one atomic revision is committed. Replaying the same
key and bytes returns the original revision; reusing the key for different bytes is rejected.

`GET /sdtms/{id}/specification/export?format=json|xlsx` provides a non-persisting exchange file.
A Specification revision makes the prior Derivation Plan misaligned.

## Author the Derivation Plan

`PUT /sdtms/{id}/derivation-plan` accepts an atomic typed DAG pinned to the current
`specification_revision` and `input_selection_revision`. Supported SDTM authoring nodes are
Raw reads, filters, selections, typed-expression derivations, explicit casts, joins, unions,
long reshaping, controlled-terminology mappings, grouping/aggregation, deterministic sequencing,
sorts, assertions, and domain writes.
Join nodes explicitly identify their left and right inputs, which must also be represented by
incoming graph edges. Raw Python, R, SAS, SQL, and arbitrary expression strings are rejected by
the strict contract.

Saving validates graph acyclicity, declared domain targets, and output coverage for derived
domains, then lowers through the internal Dataflow IR. Use:

- `POST /sdtms/{id}/derivation-plan/validate` for alignment and lowering validation;
- `GET /sdtms/{id}/lineage` for stable transitive node lineage; and
- `POST /sdtms/{id}/validate` for an immutable validation snapshot over exact dependency,
  input, Specification, plan, and normalized IR fingerprints.

`POST /sdtms/{id}/derivation-plan/preview` evaluates the aligned plan through the same
normalized IR used by compilation. Supply optional `domains` and a `limit` from 1 to 200.
The route re-verifies the exact selected artifact IDs and checksums through Raw's typed
capability, limits each source dataset to 10,000 rows, and neither persists nor logs rows.
The preview evaluator supports the same reads, selections, filters, typed derivations, casts,
joins, unions, long reshaping, controlled-terminology mappings, grouping/aggregation,
sequencing, sorts, assertions, and writes used by compilation. Terminology mappings are
explicitly authored and declare whether an unmapped value is rejected, preserved, or set to
null. Cast nodes declare whether invalid source values are rejected or normalized to null;
sequence nodes declare grouping, ordering, output column, and starting value.

## Author aCRF annotations

Upload the immutable CRF PDF through `POST /studies/{study_id}/source-files`, then create an
annotation with `POST /sdtms/{id}/acrf/annotations`. Creation requires the workbench's current
`If-Match` value. Each annotation identifies the exact source PDF artifact and page, and uses a
normalized top-left rectangle (`x`, `y`, `width`, and `height`, each within 0 through 1). The
service verifies that the artifact is an available PDF in the same study and that the page exists.

Annotations may link to any combination of:

- an SDTM variable in an exact `specification_revision`;
- a Raw variable from the workbench's selected Raw context; or
- a stable node in an exact `plan_revision`.

Raw targets are resolved through Raw's registered entity and context capabilities rather than
through Raw persistence. `POST /acrf-annotations/{id}/links` either replaces all links or amends
them atomically and requires the annotation `ETag`. `PATCH /acrf-annotations/{id}` edits the
region, page, text, question, resolution, or open/resolved status. `DELETE` is a soft deletion so
the evidence record remains retained. Both operations also require the annotation `ETag`.

`GET /sdtms/{id}/acrf/coverage` reports current annotation counts, unlinked annotations, SDTM
variables not linked against the current Specification revision, and links pinned to non-current
Specification or plan revisions. An annotation change increments the SDTM workbench revision,
stales prior artifacts, and is frozen into the next SDTM validation input manifest.

After validating the current workbench, `POST /sdtms/{id}/acrf/artifacts` creates a durable
artifact build for `sdtm_acrf`. The builder requires at least one linked active annotation, one
shared immutable source PDF, and a current validation snapshot. It overlays the exact saved
regions, records the source checksum and annotation revisions, and publishes a new immutable PDF;
the internal source object locator is not included in its public manifest.

## Author version-neutral Define metadata

`POST /sdtms/{id}/define/initialize` creates a new immutable Define revision from the current
exact SDTM Specification and explicitly selected available `sdtm_dataset_xpt` artifact IDs. It
requires the SDTM workbench `ETag` and an `expected_define_revision` (`null` for the first
revision). Initialization adds missing datasets, variables, and XPT leaves, but preserves existing
labels, structures, origins, codelists, methods, comments, document references, and other manual
edits. It refuses to replace an existing output selection implicitly.

`PUT /sdtms/{id}/define` replaces the complete version-neutral model atomically and also requires
the workbench `ETag`. The model includes exact Specification and output-artifact bindings,
datasets, items, leaf definitions, origins, aCRF references, document references, codelists,
methods, and comments. Internal and external references are checked before saving.

`POST /sdtms/{id}/define/validate` creates an immutable validation snapshot. It checks alignment
with the current Specification, dataset/item coverage, exact available XPT artifacts, active
aCRF references, and deterministic rendering against both pinned local Define-XML 2.0 and 2.1
XSD suites. The snapshot records the checksum fingerprint of each participating schema suite.
Define edits stale only Define/cSDRG evidence; they do not incorrectly stale the selected XPT
datasets or compiled programs.

`POST /sdtms/{id}/define/reconcile` requires an exact `define_revision`, its fingerprint, and an
`Idempotency-Key`. It snapshots that immutable Define revision, every selected XPT artifact
ID/checksum, and every active aCRF annotation revision. The durable worker compares dataset
coverage, variable names/types/lengths, leaf identities/checksums/filenames, and bidirectional
aCRF-to-Define variable references through the registered `sdtm_define_outputs` capability. It
publishes an immutable reconciliation report with stable common-model issues and rejects inputs
that change during evaluation.

`GET /sdtms/{id}/define/render?version=2.0|2.1` returns a non-persisting XML preview only after
the exact current Define revision has a zero-error validation covering both current local schema
fingerprints. `POST /sdtms/{id}/define/artifacts` accepts one or both versions, the canonical
build-input fingerprint, and an `Idempotency-Key`. Artifact publication additionally requires a
successful zero-error reconciliation matching the exact Define revision and selected XPT
checksums. Each immutable XML artifact records its Define and Specification revisions, XPT
checksums, dependency selection, schema fingerprint, validation run, and reconciliation run.
The repository-pinned schema sources, licenses, commits, and individual checksums are documented
in `schemas/cdisc/define-xml/PROVENANCE.md`; validation runs without network access and does not
claim regulatory certification or parity with a commercial validator.

## Author and build the cSDRG

First select the exact `REPORT_LAYOUT` Template version separately for
`sdtm_csdrg_docx` and `sdtm_csdrg_pdf` through `PUT /sdtms/{id}/dependencies`. Then call
`POST /sdtms/{id}/csdrg/initialize` with the workbench `ETag`, expected cSDRG revision, current
Define revision, and the successful zero-error Define/XPT/aCRF reconciliation run. The
initializer copies factual dataset labels, structures, row counts, variable counts, exact XPT
artifact IDs, and checksums. It creates the required blank section headings but never writes
clinical narrative.

Edit the complete contract with `PUT /sdtms/{id}/csdrg`. Factual rows and evidence bindings are
read-only in effect: the service rejects values that differ from the exact current Define and XPT
evidence. User-authored titles, version text, headings, and paragraphs are preserved when
initialization is repeated to refresh factual structures. The required manual sections are
`study_data_overview`, `standards_and_versions`, `trial_design`, `domain_notes`,
`conformance_issues`, `sponsor_defined_domains`, `controlled_terminology`, `data_dependencies`,
and `reviewer_guidance`.

`POST /sdtms/{id}/csdrg/validate` creates an immutable validation snapshot. Missing or empty
required narratives are errors. `POST /sdtms/{id}/csdrg/artifacts` requires an
`Idempotency-Key`, the current canonical input fingerprint, an error-free cSDRG validation, and
one exact compatible Template selection per requested format. It publishes new immutable DOCX
and/or PDF artifacts through the shared renderer-neutral `Document` representation and records
the cSDRG validation and reconciliation run IDs on each artifact.

## Build metadata and programs

After successful current validation, `POST /sdtms/{id}/artifacts` can request:

- `sdtm_dependency_manifest`
- `sdtm_specification` (XLSX)
- `sdtm_specification_json`
- `sdtm_derivation_plan_json`
- `sdtm_derivation_report` (JSON)
- `sdtm_lineage_report` (JSON)
- `sdtm_lineage_report_json`
- `sdtm_validation_report` (JSON)
- `sdtm_validation_report_json`
- `sdtm_program_python`
- `sdtm_program_r`
- `sdtm_program_sas`

`POST /sdtms/{id}/compile` is a convenience route selecting one of `python`, `r`, or `sas`.
Both routes require `Idempotency-Key` and the expected canonical build fingerprint. Artifact
records freeze input-selection, Specification, source-plan, IR, validation, dependency, and
compiler provenance. Compiler version `1.4.0` implements these operators for Python and R;
SAS compilation returns `backend_capability_missing` before artifact publication for an operator
whose equivalent SAS semantics are not yet implemented.

The shared execution API persists exact immutable run requests, verifies that the
program, validation, input artifacts, revisions, and compiler fingerprint agree, enforces
server limit ceilings, and supports idempotent creation, status, bounded logs, outputs, and
cancellation. The execution dispatcher stages exact supported tabular inputs as CSV in a fresh
workspace and
runs generated Python or R in a disposable non-root, read-only, network-disabled Docker
container with CPU, memory, process, time, log, and output limits. It validates declared
CSV outputs, generates deterministic XPORT v5, reads each XPT back to verify names, labels,
types, character widths, row count, and values, then publishes immutable
`sdtm_dataset_csv` and `sdtm_dataset_xpt` artifacts before destroying the workspace.
Every terminal attempt also publishes an immutable `sdtm_execution_log` JSON artifact containing
bounded stdout/stderr, exit status, timing metrics, and typed failure metadata. It carries the
same exact input, validation, Specification, plan, compiler, and execution-run provenance as the
dataset artifacts and is not treated as a dataset output.

Use `POST /sdtms/{id}/execute` as the module convenience route or
`POST /execution-runs` as the shared route. Both require `Idempotency-Key`, the exact
program/input artifact IDs, validation and authoring revisions, compiler and input
fingerprints, and accepted limits. Exact CSV, flat JSON, and first-sheet XLSX Raw inputs are
staged as deterministic UTF-8 CSV inside the disposable workspace; empty declared outputs retain
their XPT variable metadata. SAS execution without an external adapter terminates with
`runner_not_configured`.
