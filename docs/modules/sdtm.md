# SDTM Module

The SDTM module supports direct human create/edit and AI-assisted proposal/review for target
metadata, declared lineage, executable programs, Define metadata, and cSDRG narrative. Both paths
use the same exact Raw inputs, typed contracts, validation, staleness, and immutable revisions.
For AI output, humans review immutable context, provenance, diffs, assumptions, unresolved items,
evidence references, limitations, and deterministic validation findings before accepting,
rejecting, or requesting a revision. Only manually saved or human-accepted code may execute, and
declared lineage remains distinct from executable logic.

aCRF annotation retains the existing deterministic/manual evidence editor until its PDF extraction,
redaction, and typed proposal path is implemented. It is the remaining SDTM authoring exception and
must not be presented as AI-authored content.

## Workbench sequence

The workbench presents the following review stages:

1. Source review
2. Domain mapping
3. Variable and value-level metadata
4. Program review
5. Execution
6. aCRF
7. Define and validation
8. cSDRG and submission

There is no SDTM graph editor or compiler lowering. A manually saved or human-accepted proposed
program revision is the executable authority. Domain and Variable Mappings are reviewer-facing,
human-authored or human-accepted declared lineage.

## Specification and value contexts

One immutable Specification revision covers every SDTM domain. New authoring uses content schema `2.0.0`. Historical earlier-schema revisions remain readable but cannot drive new mappings or generation until a user explicitly reviews and saves a current-schema revision.

The selected SDTMIG identity remains explicit, but Specification operations do not read its
retained catalog asset. Catalog/domain discovery, reads, deterministic population, direct saves,
import/replay, exports, and Specification AI proposal generation or acceptance call the canonical
CDISC Library resource live with the server-side API key. Saved revisions record the canonical
href and response checksum; a missing credential or unavailable provider fails visibly and never
falls back to the repository snapshot.

Older Library representations contain a small number of documented omissions and labels that
exceed the XPT v5 40-character limit. The initializer applies only reviewed, variable-specific
normalizations for those known records; it never supplies a generic default for unknown missing
metadata. The live provider response remains the checksummed provenance source.

Each domain contains variables, keys, sort order, sequencing metadata, output naming, terminology bindings, value-level metadata, and reusable value contexts. A value context has a stable `id`, reviewer-facing `label`, `discriminator_variable`, operator (`eq`, `ne`, or `in`), and typed `values`. `eq` and `ne` require one value. `in` requires a non-empty unique list. Value-level metadata references `context_id`; it does not duplicate a condition.

## Domain Mapping

Each generated domain has one immutable Domain Mapping head pinned to the current Specification and Raw input-selection revisions. It declares one or more total inputs from selected Raw datasets and/or upstream SDTM domains. The workbench supports dragging available datasets and domains into their respective selections while retaining direct field editing as an accessible fallback.

Raw datasets must exist in the exact selected Raw context. Upstream domains must exist in the Specification. Duplicate inputs, self-references, and cross-domain cycles are rejected. References to upstream domains remain logical here; a test or generation request selects the exact upstream XPT artifacts it consumes.

An imported domain is the alternate provider for a domain. Imported domains are inspected and validated against the current Specification and require neither Variable Mapping nor a Code Workarea. Import inspection never creates clinical metadata or mappings. The optional imported-domain lookup returns an empty successful result when no imported revision exists, because that is the normal initial state for a generated domain.

## Variable Mapping

Each generated domain has one immutable sparse Variable Mapping head pinned to the current Specification and Domain Mapping revisions. The editor renders SDTM variables as rows and one implicit Default column plus one column for each reusable value context in the domain. Qualified variables from datasets declared in Domain Mapping can be dragged into any matrix cell; a drop appends the source in order without replacing existing sources or creating duplicates.

A cell key is `(target_variable, context_id)`, where null `context_id` means Default. A non-empty cell contains an ordered unique list of qualified sources such as `raw:RAWDM.SEX` or `sdtm:DM.USUBJID`. Every source dataset must be declared by the current Domain Mapping.

Empty cells are valid. They do not mean constant, derived, invalid, or incomplete because the program remains authoritative. aCRF annotations target exact SDTM variable rows and may independently target Raw variables; graph-node annotation targets are not supported.

## Code Workareas

A domain can have multiple named workareas, including multiple workareas for the same language. Domain and language (`python`, `r`, or `sas`) are fixed after creation. Name and source edits create immutable code revisions pinned to the current Specification, Domain Mapping, and Variable Mapping heads. No global active workarea is chosen.

Programs receive an input manifest and can read only the full staged datasets declared by Domain Mapping. Raw inputs come from the exact current Raw input selection. Every upstream SDTM input is an exact XPT artifact selected in the run request. The workarea renders one selector for each declared upstream domain, offers only available XPT artifacts owned by the same SDTM workbench, and preselects the current Output Selection when one exists. External network access remains disabled and existing runner CPU, memory, process, runtime, cancellation, output-size, non-root, and cleanup controls apply.

R workareas run in the reviewed R 4.5.1 image with `jsonlite`, `tidyr`, and `tidyr`'s dependency
set installed from a frozen repository snapshot. Programs cannot install packages at runtime
because execution has no external network access. Expanding the supported package set requires
a reviewed, rebuilt runner image and runner conformance coverage.

The program must write exactly its own domain CSV in the declared output location. Undeclared outputs or domains are rejected.

### Run Test

`Run Test` executes the current immutable code revision asynchronously against the full exact inputs. It returns a bounded output preview and bounded/redacted stdout and stderr. It publishes no output or log artifacts and destroys the temporary workspace.

### Generate artifacts

Generation snapshots the code revision, runs it against the full exact inputs, and requires the output CSV to match the current Specification exactly. Validation checks declared variables, rejects undeclared variables, validates types, keys, sorting, XPT v5 constraints, and XPT read-back.

Success exposes immutable program, CSV, XPT, execution-log, and output-validation artifacts together. Ordinary failure exposes no partial output artifacts. A SAS workarea retains a reviewable program when no external runner exists, returns `runner_not_configured`, and does not satisfy output readiness. Python, R, and SAS generations are validated independently; SDTM does not automatically compare their results.

## Output Selection

The revisioned Output Selection chooses exactly one successful generation run or aligned imported revision for every Specification domain. The selected XPT for each downstream generated domain must match the exact upstream XPT artifacts that run consumed. The server never resolves “latest.”

A current coherent Output Selection is required before aggregate SDTM validation, Define reconciliation, cSDRG and other all-domain artifacts, downstream ADaM context export, or packaging. Replacing the set stales downstream evidence without rewriting or deleting prior runs and artifacts.

## Staleness

- Specification or Raw input-selection changes misalign affected mappings and block testing and generation until explicit reviewed saves realign them.
- Domain Mapping changes misalign its Variable Mapping and stale output readiness.
- Variable Mapping changes stale selected outputs because declared lineage changed.
- Editing a workarea creates a new code revision and does not stale prior immutable runs.
- Replacing an upstream output requires downstream regeneration and an atomic coherent Output Selection update.

## APIs

All routes are under `/api/v1`.

```text
GET /sdtm-workbenches/{id}/domain-mappings
GET|PUT /sdtm-workbenches/{id}/domains/{domain}/domain-mapping
GET|PUT /sdtm-workbenches/{id}/domains/{domain}/variable-mapping

GET|POST /sdtm-workbenches/{id}/code-workareas
GET|PUT /sdtm-workbenches/{id}/code-workareas/{workarea_id}
POST /sdtm-workbenches/{id}/code-workareas/{workarea_id}:archive
POST /sdtm-workbenches/{id}/code-workareas/{workarea_id}:test
POST /sdtm-workbenches/{id}/code-workareas/{workarea_id}:generate
GET /sdtm-code-runs/{run_id}

GET|PUT /sdtm-workbenches/{id}/output-selection
GET /sdtm-workbenches/{id}/program-artifact-readiness
GET /sdtm-workbenches/{id}/lineage
POST /sdtm-workbenches/{id}:validate
POST /sdtm-workbenches/{id}/domains/{domain}:validate
POST /sdtm-workbenches/{id}/artifacts:build
```

Mapping, workarea, and Output Selection mutations use ETag/`If-Match` concurrency. Test and generation requests require `Idempotency-Key` and return `202 Accepted` with a status resource. The removed graph-plan, graph-preview, SDTM compile, and SDTM execute routes have no compatibility aliases.

## Artifact provenance

Generated programs and outputs record the exact Specification, mapping revisions, code revision, originating proposal/decision, input artifacts, dependency selection, validation evidence, runner settings, and SHA-256 checksums. Mapping and lineage deliverables identify their contents as human-accepted declared lineage and not inferred from program execution. Immutable prior evidence remains recoverable when stale, but stale evidence cannot be selected for downstream use or a new package.
