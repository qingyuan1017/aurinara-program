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

In the interactive workbench, the user selects only the Raw data version. The UI resolves
that version's active datasets, bound source-file artifacts and checksums, matching successful
validation run, and dependency fingerprint, then submits the complete exact-pin request. These
provenance values remain explicit in the persisted selection without becoming separate user
choices.

`GET /sdtms/{id}/raw-context` returns the verified immutable context DTO. Any Raw dataset,
variable, or file-binding change marks the selection `input_refresh_required`, marks the
current plan `misaligned`, and stales SDTM artifacts without rewriting authored content.

## Author the Specification

`PUT /sdtms/{id}/specification` requires `If-Match` and replaces one complete versioned
contract atomically. Domains own their variables, value-level metadata, keys, sort order,
expected output name, roles, origins, and exact terminology bindings. Natural keys and all
internal references are validated before the immutable revision is committed.

The interactive Specification page stages domain and variable create, edit, delete, and
ordering changes in one draft before issuing that atomic `PUT`. Variable renames preserve
domain key, sort-order, and value-level references. Deleting a variable removes only references
to that deleted variable; the page blocks save and identifies any required metadata that must be
completed before the full contract is valid.

`GET /sdtms/{id}/specification/initialization-options` resolves the exact selected SDTM
implementation guide and lists its concrete domain names and variable counts by core status.
`POST /sdtms/{id}/specification/initialize` requires the current `If-Match` value, an explicit
non-empty domain selection, and whether to add only Required and Expected variables. It resolves
and checksum-verifies the selected industry-standard asset, adds only the selected missing
structures, and creates a new immutable Specification revision. Existing domain and variable
values and ordering are preserved; the variable filter never deletes an already-authored
Permissible variable. The parameterized `SUPPQUAL` pattern is left for explicit study authoring,
and initialization never supplies study mappings, derivations, terminology usage decisions, or
other clinical judgments.

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
Raw reads, filters, selections, typed-expression derivations, joins, unions,
long reshaping, grouping/aggregation, deterministic sequencing,
sorts, assertions, and domain writes.
Cast and controlled-terminology mapping are typed functions within a derivation assignment,
not standalone graph operators. Each function wraps a typed input expression and records its
invalid or unmapped-value policy alongside the assignment that produces the target column.
Join nodes explicitly identify their left and right inputs, which must also be represented by
incoming graph edges. Raw code in ordinary nodes and arbitrary expression strings are rejected.
The plan may declare typed `custom_functions` with stable IDs, fixed parameters and return types,
and one or more manually authored language bodies. Derivations call them through the typed
`custom_function` expression. Calls must resolve and match the declared arity.

The interactive editor keeps the outer graph at dataset-flow level and configures each `derive`
node as an ordered collection of variable recipes. Recipes are searchable and collapsible, show
a compact expression summary and same-domain dependencies, and can be duplicated or reordered;
the displayed top-to-bottom order is persisted in `assignment_order` and is the evaluation order;
the explicit list keeps recipe order stable when the assignment object is stored in JSONB. Built-in function calls retain their
typed positional wire contract but present stable parameter names, descriptions, and functional
categories to authors. Custom-function signatures use typed controls for IDs, ordered parameter
names, return types, and language bodies instead of a raw JSON editor. When a custom-function ID
or parameter list changes, calls in the open plan are updated by parameter name; new parameters
remain visibly incomplete until the user supplies their expressions. These affordances do not
generate mappings or derivations and do not alter the persisted `1.2.0` plan contract.

When a saved per-domain plan becomes misaligned, the workbench shows the recorded reason
(`specification_changed`, `input_changed`, or `upstream_plan_changed`) and keeps that immutable
revision read-only. **Start alignment revision** explicitly clones its authored graph and custom
functions into an editable draft pinned to the current Specification and current Input Selection.
The draft identifies both old and proposed revision pins and may be cancelled without changing
the saved plan. Saving uses the misaligned plan revision as `If-Match`, creates the next aligned
revision, and re-resolves server-owned upstream pins. A domain that uses `sdtm_read` must be saved
after its upstream domains have been aligned. Validation, preview, compilation, and execution
remain disabled while the saved head is misaligned, including while an alignment draft is open.

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
For `sdtm_read`, preview recursively evaluates the exact server-pinned sibling plan revision
and its pinned dependency closure over that same Raw selection; produced sibling rows are not
treated as another external input selection. Every plan remains bounded by the requested limit.
An unevaluable pinned sibling returns `422 sdtm_preview_upstream_invalid` naming that domain.
The preview evaluator supports the same reads, selections, filters, catalog-function derivations,
joins, unions, long reshaping, grouping/aggregation,
sequencing, sorts, assertions, and writes used by compilation. Terminology mappings are
explicitly authored and declare whether an unmapped value is rejected, preserved, or set to
null. Cast functions declare whether invalid source values are rejected or normalized to null;
sequence nodes declare grouping, ordering, output column, and starting value.
Custom functions are deliberately excluded from preview because user code never runs in the API
process; preview returns `preview_custom_function_unsupported` for a plan that calls one.

## Author aCRF annotations

Upload the immutable CRF PDF through `POST /studies/{study_id}/source-files`, then create an
annotation with `POST /sdtms/{id}/acrf/annotations`. Creation requires the workbench's current
`If-Match` value. Each annotation identifies the exact source PDF artifact and page, and uses a
normalized top-left rectangle (`x`, `y`, `width`, and `height`, each within 0 through 1). The
service verifies that the artifact is an available PDF in the same study and that the page exists.

The interactive aCRF workbench can load an authorized immutable source PDF in an in-app viewer.
It renders saved `normalized_top_left` regions as overlays on the matching source artifact and
page, provides page and zoom controls, and shows each region's annotation text, links, and
revision. The viewer reads the existing immutable artifact download resource and does not create
or modify annotation content.

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
compiler provenance. Compiler version `1.7.0` implements these operators and derivation functions for Python and R;
SAS compilation returns `backend_capability_missing` before artifact publication for an operator
whose equivalent SAS semantics are not yet implemented.

Custom-function bodies are selected independently per backend. A supplied body produces an
executable program for that language. A missing body produces a deterministic TODO stub with
`compiler.executable=false` and the function ID in `compiler.todo_functions`; it does not block
programs for languages that are implemented. Execution rejects only that incomplete artifact.

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
