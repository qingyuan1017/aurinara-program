# SDTM Module

The SDTM module is a manually authored workbench for selecting exact Raw inputs, maintaining target metadata and declared lineage, writing executable programs, validating exact outputs, and building reviewer and submission artifacts. It does not propose mappings, infer derivations, or treat declared lineage as executable logic.

## Workbench sequence

The workbench presents these authoring areas:

1. Input Selection
2. Specification
3. aCRF
4. Domain Mapping
5. Variable Mapping
6. Code Workareas
7. Define
8. cSDRG
9. Validation
10. Program & artifact readiness
11. Dependencies

There is no SDTM graph editor, compile tab, or separate execution tab. The authored program is the executable authority. Domain and Variable Mappings are reviewer-facing, author-maintained lineage.

## Specification and value contexts

One immutable Specification revision covers every SDTM domain. New authoring uses content schema `2.0.0`. Historical earlier-schema revisions remain readable but cannot drive new mappings or generation until a user explicitly reviews and saves a current-schema revision.

Each domain contains variables, keys, sort order, sequencing metadata, output naming, terminology bindings, value-level metadata, and reusable value contexts. A value context has a stable `id`, reviewer-facing `label`, `discriminator_variable`, operator (`eq`, `ne`, or `in`), and typed `values`. `eq` and `ne` require one value. `in` requires a non-empty unique list. Value-level metadata references `context_id`; it does not duplicate a condition.

## Domain Mapping

Each generated domain has one immutable Domain Mapping head pinned to the current Specification and Raw input-selection revisions. It declares one or more total inputs from selected Raw datasets and/or upstream SDTM domains. The workbench supports dragging available datasets and domains into their respective selections while retaining direct field editing as an accessible fallback.

Raw datasets must exist in the exact selected Raw context. Upstream domains must exist in the Specification. Duplicate inputs, self-references, and cross-domain cycles are rejected. References to upstream domains remain logical here; a test or generation request selects the exact upstream XPT artifacts it consumes.

An imported domain is the alternate provider for a domain. Imported domains are inspected and validated against the current Specification and require neither Variable Mapping nor a Code Workarea. Import inspection never creates clinical metadata or mappings.

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
GET /sdtms/{id}/domain-mappings
GET|PUT /sdtms/{id}/domains/{domain}/domain-mapping
GET|PUT /sdtms/{id}/domains/{domain}/variable-mapping

GET|POST /sdtms/{id}/code-workareas
GET|PUT /sdtms/{id}/code-workareas/{workarea_id}
POST /sdtms/{id}/code-workareas/{workarea_id}/archive
POST /sdtms/{id}/code-workareas/{workarea_id}/test
POST /sdtms/{id}/code-workareas/{workarea_id}/generate
GET /sdtm-code-runs/{run_id}

GET|PUT /sdtms/{id}/output-selection
GET /sdtms/{id}/program-artifact-readiness
GET /sdtms/{id}/lineage
POST /sdtms/{id}/validate
POST /sdtms/{id}/domains/{domain}/validate
POST /sdtms/{id}/artifacts
```

Mapping, workarea, and Output Selection mutations use ETag/`If-Match` concurrency. Test and generation requests require `Idempotency-Key` and return `202 Accepted` with a status resource. The removed graph-plan, graph-preview, SDTM compile, and SDTM execute routes have no compatibility aliases.

## Artifact provenance

Generated programs and outputs record the exact Specification, mapping revisions, code revision, input artifacts, dependency selection, validation evidence, runner settings, and SHA-256 checksums. Mapping and lineage deliverables identify their contents as author-maintained and not inferred from program execution. Immutable prior evidence remains recoverable when stale, but stale evidence cannot be selected for downstream use or a new package.
