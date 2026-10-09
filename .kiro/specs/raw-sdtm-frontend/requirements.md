# Requirements Document

## Introduction

This feature builds the React frontend screens for the Raw and SDTM modules of the Clinical Artifact Platform. The Phase 3 backend (commit e8413ae) added the complete Raw and SDTM HTTP surface — Raw dataset/variable management, SDTM Specification and Derivation Plan authoring, Define-XML 2.0/2.1, aCRF annotation, cSDRG, XPT export, validation, compilation, and execution — but the frontend currently exposes only minimal aggregate-list placeholder screens (`frontend/src/routes/_app/raw.tsx` and `sdtm.tsx`), and the Orval-generated typed client (`frontend/src/api/generated/{raw,sdtm}`) predates the buildout and does not yet contain hooks for the new endpoints.

The scope is the browser-facing authoring, viewing, and artifact-generation experience for Raw and SDTM, grounded strictly in the endpoints the backend exposes in `src/app/raw/routes.py`, `src/app/sdtm/routes.py`, `src/app/sdtm/define.py`, `src/app/sdtm/acrf.py`, and `src/app/sdtm/csdrg.py`, and the transport conventions in `docs/api-contract.md`. All API access goes through the Orval-generated TanStack Query hooks over the custom axios instance; the frontend does not hand-author calls that bypass the generated client where a generated hook exists. Screens respect study scope, optimistic-concurrency `If-Match`/`ETag`, `Idempotency-Key`, `202 Accepted` + status-resource polling for long-running work, cursor pagination, and RFC 9457 `problem+json` error surfacing.

The following are out of scope for this feature: changing any backend route or contract, implementing ADaM/TLF/Documents screens, building a PDF canvas rendering engine for aCRF overlay, and any AI-assisted authoring (prohibited by platform boundaries). The frontend never infers clinical content; it only presents and edits what the user authors through typed backend commands.

## Glossary

- **Frontend**: The React 18 + TypeScript + Vite single-page application in `frontend/`, using TanStack Router (file-based routes under `src/routes/_app`), TanStack Query, Radix UI/shadcn components, and sonner toasts.
- **Generated_Client**: The Orval-produced typed API layer under `frontend/src/api/generated`, consisting of per-tag TanStack Query hooks that call the backend `/api/v1` surface through the custom axios instance.
- **Study_Context**: The currently selected study, provided by the `useCurrentStudy` study-provider hook, whose `currentStudyId` scopes every Raw and SDTM request.
- **Raw_Workbench**: A Raw aggregate owning datasets, each bound to one immutable source file, addressed as `/api/v1/raw/{raw_id}`.
- **Raw_Dataset**: A manually maintained dataset record bound to an immutable source file, addressed as `/api/v1/raw-datasets/{dataset_id}`.
- **Raw_Variable**: Manually maintained physical metadata for a column of a Raw_Dataset, addressed as `/api/v1/raw-variables/{variable_id}`.
- **SDTM_Workbench**: An SDTM aggregate addressed as `/api/v1/sdtms/{sdtm_id}` that owns an input selection, a Specification, a Derivation Plan, aCRF annotations, Define metadata, and a cSDRG.
- **Input_Selection**: The exact, pinned Raw inputs a SDTM_Workbench consumes, addressed as `/api/v1/sdtms/{sdtm_id}/input-selection`.
- **Specification**: The versioned SDTM target-metadata contract (domains, variables, value-level metadata, keys, terminology bindings), addressed as `/api/v1/sdtms/{sdtm_id}/specification`.
- **Derivation_Plan**: The versioned SDTM typed raw-to-domain DAG, addressed as `/api/v1/sdtms/{sdtm_id}/derivation-plan`.
- **Alignment_State**: The server-computed state (`aligned`/`misaligned`, or input `current`/`input_refresh_required`) indicating whether a Derivation_Plan matches its pinned Specification and Input_Selection revisions.
- **Validation_Run**: An immutable validation snapshot resource addressed as `/api/v1/validation-runs/{validation_run_id}`, with status, issue counts, and the common issue list.
- **Artifact_Build**: An asynchronous build operation addressed as `/api/v1/artifact-builds/{build_id}` that produces immutable Artifacts.
- **Artifact**: An immutable generated file addressed as `/api/v1/artifacts/{artifact_id}`, downloadable through `/api/v1/artifacts/{artifact_id}/download`.
- **Execution_Run**: An isolated program-execution operation addressed as `/api/v1/execution-runs/{run_id}` with logs and outputs.
- **ETag**: The opaque optimistic-concurrency token returned on a mutable aggregate response, supplied back as `If-Match` on edits (the backend form is the string `"revision-{N}"`).
- **Problem_Response**: An RFC 9457 `application/problem+json` error body carrying `title`, `detail`, `code`, and an optional `issues` array.

## Requirements

### Requirement 1: Regenerate the typed API client

**User Story:** As a frontend developer, I want the generated API client to include the Phase 3 Raw and SDTM endpoints, so that every screen consumes typed hooks instead of hand-written calls.

#### Acceptance Criteria

1. WHEN the backend OpenAPI document is exported without error and the client is regenerated, THE Generated_Client SHALL expose a typed TanStack Query hook for each of the Raw dataset, variable, initialize, preview, validate, reconcile, and artifact endpoints under `src/api/generated/raw`.
2. WHEN the backend OpenAPI document is exported without error and the client is regenerated, THE Generated_Client SHALL expose a typed TanStack Query hook for each of the SDTM input-selection, raw-context, specification, derivation-plan, lineage, validate, compile, execute, define, acrf, and csdrg endpoints under `src/api/generated/sdtm`.
3. WHERE a generated hook exists for a Raw or SDTM backend operation, THE Frontend SHALL invoke that operation only through the generated hook and SHALL NOT issue a hand-authored call for that operation.
4. WHERE a backend endpoint returns a binary or XML body that the Generated_Client cannot model as a typed JSON response, THE Frontend SHALL retrieve that body through the custom axios instance using the same base URL and bearer authentication applied to generated hooks.
5. IF the Frontend reaches a Raw or SDTM operation for which no generated hook exists after regeneration, THEN THE Frontend SHALL surface a build-time type error rather than issuing an untyped runtime call.

### Requirement 2: Browse and manage Raw workbenches

**User Story:** As a data manager, I want to list, create, open, edit, and retire Raw workbenches, so that I can organize raw source datasets for a study.

#### Acceptance Criteria

1. WHEN a Study_Context is selected, THE Frontend SHALL list the study's Raw workbenches from `GET /api/v1/studies/{study_id}/raw` using opaque cursor pagination with a page size between 1 and 50 and SHALL request the next page using the `next_cursor` from the previous page while `has_more` is true.
2. IF no Study_Context is selected, THEN THE Frontend SHALL display an empty-state message directing the user to select a study and SHALL NOT issue the list request.
3. WHEN the user submits the create-workbench form, THE Frontend SHALL create the workbench through `POST /api/v1/studies/{study_id}/raw` and, on a `201` response, SHALL refresh the list to include the new workbench.
4. IF a create-workbench request returns a Problem_Response, THEN THE Frontend SHALL display the response `title` and `detail`, retain the user's entered form values, and SHALL NOT refresh the list.
5. WHEN the user edits a Raw_Workbench name or status, THE Frontend SHALL send `PATCH /api/v1/raw/{raw_id}` with the current ETag as the `If-Match` header.
6. IF a Raw_Workbench edit returns `412 Precondition Failed`, THEN THE Frontend SHALL display a message stating the workbench was changed by another update, SHALL discard the stale edit, and SHALL reload the current revision from `GET /api/v1/raw/{raw_id}` before allowing a retry.
7. IF a Raw_Workbench edit returns `428 Precondition Required`, THEN THE Frontend SHALL reload the current revision to obtain a fresh ETag before resubmitting the edit.
8. WHEN the user opens a Raw_Workbench, THE Frontend SHALL display its detail view showing the workbench code, name, status, and revision from `GET /api/v1/raw/{raw_id}`.

### Requirement 3: Manage Raw datasets and source-file bindings

**User Story:** As a data manager, I want to register, view, rebind, and retire datasets within a Raw workbench, so that each dataset points at the correct immutable source file.

#### Acceptance Criteria

1. WHEN a Raw_Workbench detail view is open, THE Frontend SHALL list its datasets from `GET /api/v1/raw/{raw_id}/datasets` ordered ascending by dataset code.
2. WHEN the user uploads a source file, THE Frontend SHALL create the immutable source file through `POST /api/v1/studies/{study_id}/source-files` as multipart form data and, on success, SHALL use the returned source-file ID for a dataset binding.
3. IF a source-file upload returns `413` or `415`, THEN THE Frontend SHALL display a message indicating the file exceeds the accepted size or is an unsupported media type, and SHALL retain the dataset form so the user can select a different file.
4. WHEN the user creates a dataset, THE Frontend SHALL send `POST /api/v1/raw/{raw_id}/datasets` with the dataset code, label, and selected source-file ID.
5. IF a dataset create returns `409 duplicate_raw_dataset_code`, THEN THE Frontend SHALL display a message that dataset codes must be unique within the workbench and SHALL retain the entered form values.
6. WHEN the user rebinds a dataset to a corrected source file, THE Frontend SHALL send `PATCH /api/v1/raw-datasets/{dataset_id}` with the current ETag as the `If-Match` header.
7. WHEN the user confirms retirement of a dataset through an explicit confirmation action that names the dataset, THE Frontend SHALL send `DELETE /api/v1/raw-datasets/{dataset_id}` with the current ETag as the `If-Match` header.
8. IF a dataset rebind or retire returns `412 Precondition Failed`, THEN THE Frontend SHALL display a concurrency message and reload the current dataset revision before allowing a retry.

### Requirement 4: Maintain Raw variables and factual initialization

**User Story:** As a data manager, I want to view, create, edit, delete, and initialize dataset variables, so that maintained physical metadata reflects the source file.

#### Acceptance Criteria

1. WHEN a Raw_Dataset detail view is open, THE Frontend SHALL list its variables from `GET /api/v1/raw-datasets/{dataset_id}/variables` ordered ascending by ordinal position.
2. WHEN the user creates a Raw_Variable, THE Frontend SHALL send `POST /api/v1/raw-datasets/{dataset_id}/variables` with the maintained metadata fields source name, label, physical type, length or precision where applicable, ordinal position, role, controlled terminology reference, and description.
3. IF a variable create or edit returns `409 duplicate_raw_variable`, THEN THE Frontend SHALL display a message that variable names and ordinals must be unique within the dataset and SHALL retain the entered form values.
4. WHEN the user edits a Raw_Variable, THE Frontend SHALL send `PATCH /api/v1/raw-variables/{variable_id}` with the current ETag as the `If-Match` header.
5. WHEN the user confirms deletion of a Raw_Variable through an explicit confirmation action that names the variable, THE Frontend SHALL send `DELETE /api/v1/raw-variables/{variable_id}` with the current ETag as the `If-Match` header.
6. WHEN the user requests factual initialization, THE Frontend SHALL call `POST /api/v1/raw-datasets/{dataset_id}/variables/initialize` with the current dataset ETag as the `If-Match` header and, on success, SHALL display the created count and filled count from the response and refresh the variable list.
7. IF a factual-initialization request returns `412 Precondition Failed` or `428 Precondition Required`, THEN THE Frontend SHALL reload the current dataset revision to obtain a fresh ETag before allowing the user to retry initialization.

### Requirement 5: Preview Raw dataset rows

**User Story:** As a data manager, I want to preview a bounded window of rows from a dataset's bound source file, so that I can confirm the data before authoring downstream metadata.

#### Acceptance Criteria

1. WHEN the user requests a preview, THE Frontend SHALL call `POST /api/v1/raw-datasets/{dataset_id}/preview` with an optional column selection, a zero-based offset of 0 or greater, and a row limit between 1 and 200.
2. WHERE the user requests a row limit below 1 or above 200, THE Frontend SHALL clamp the limit to 1 or 200 respectively before sending the request.
3. WHERE the user requests an offset below 0, THE Frontend SHALL set the offset to 0 before sending the request.
4. WHEN a preview response is received, THE Frontend SHALL display the returned columns and rows together with the response offset, limit, and total row count.
5. WHEN a preview response contains zero rows, THE Frontend SHALL display a message that the requested window contains no rows while still showing the offset, limit, and total row count.
6. THE Frontend SHALL NOT persist or cache preview rows beyond the lifetime of the preview view.

### Requirement 6: Validate a Raw workbench and surface issues

**User Story:** As a data manager, I want to validate a Raw workbench and read its issues, so that I can correct physical-schema problems before generating artifacts.

#### Acceptance Criteria

1. WHEN the user triggers Raw validation, THE Frontend SHALL call `POST /api/v1/raw/{raw_id}/validate` and display the resulting Validation_Run status and the per-severity issue counts (error, warning, info).
2. WHEN a Validation_Run contains one or more issues, THE Frontend SHALL display, for each issue, its code, severity, message, suggestion, dataset, variable, and field path from the common issue model, and SHALL display an empty-state message when the issue list is empty.
3. WHILE a displayed Validation_Run status is `failed`, THE Frontend SHALL display a persistent notice stating that error-severity issues block Raw artifact generation.
4. WHEN the user opens a Validation_Run from a reference, THE Frontend SHALL retrieve it by ID from `GET /api/v1/validation-runs/{validation_run_id}` and display its status and issue counts.
5. IF a `GET /api/v1/validation-runs/{validation_run_id}` request returns `404`, THEN THE Frontend SHALL display a not-found message indicating the referenced Validation_Run is unavailable and SHALL NOT display stale run content.

### Requirement 7: Reconcile Raw source schema

**User Story:** As a data manager, I want to run a source-schema reconciliation and read its report, so that I have an immutable comparison of maintained metadata against the bound source bytes.

#### Acceptance Criteria

1. WHEN the user starts a Raw reconciliation, THE Frontend SHALL call `POST /api/v1/raw/{raw_id}/reconcile` with the expected current Raw revision and an `Idempotency-Key` header.
2. WHEN a reconciliation request returns `202 Accepted`, THE Frontend SHALL read the returned reconciliation-run location and poll `GET /api/v1/reconciliation-runs/{reconciliation_run_id}` at an interval between 1 and 5 seconds until the run reaches a terminal status of `completed` or `failed`, stopping after a maximum of 120 seconds and displaying a timeout notice if no terminal status is reached.
3. IF a reconciliation request returns `409 stale_raw_reconciliation_input`, THEN THE Frontend SHALL display a message stating that the expected Raw revision is no longer current and SHALL present a reload action that re-fetches the current Raw revision.
4. WHEN a reconciliation run reaches a terminal status, THE Frontend SHALL display its per-severity issue counts and the full issue list using the common issue model fields.
5. IF a reconciliation request or poll returns a Problem_Response, THEN THE Frontend SHALL display its `title` and `detail` and SHALL stop polling.

### Requirement 8: Generate and download Raw artifacts

**User Story:** As a data manager, I want to generate Raw metadata and dictionary artifacts and download them, so that I can produce the Raw deliverables.

#### Acceptance Criteria

1. WHEN the user selects one or more supported Raw artifact types, THE Frontend SHALL call `POST /api/v1/raw/{raw_id}/artifacts` with the selected artifact types, the expected input fingerprint, and an `Idempotency-Key` header.
2. THE Frontend SHALL restrict the selectable Raw artifact types to exactly `raw_dependency_manifest`, `raw_metadata_json`, `raw_data_dictionary_xlsx`, and `raw_validation_report_json`, and SHALL disable the submit action while no artifact type is selected.
3. WHEN an Artifact_Build is accepted with `202`, THE Frontend SHALL poll `GET /api/v1/artifact-builds/{build_id}` at an interval between 1 and 5 seconds until it reaches a terminal status of `completed` or `failed`, stopping after a maximum of 120 seconds and displaying a timeout notice if no terminal status is reached.
4. WHEN an Artifact_Build reaches the `completed` status, THE Frontend SHALL list each produced Artifact and present a download action that retrieves it through `GET /api/v1/artifacts/{artifact_id}/download`.
5. IF an Artifact_Build reaches the `failed` status, THEN THE Frontend SHALL display the typed failure code and detail returned on the build resource and SHALL NOT present any download action.

### Requirement 9: Browse and manage SDTM workbenches

**User Story:** As an SDTM programmer, I want to list, create, and open SDTM workbenches for a study, so that I can author SDTM deliverables.

#### Acceptance Criteria

1. WHEN a Study_Context is selected, THE Frontend SHALL list the study's SDTM workbenches from `GET /api/v1/studies/{study_id}/sdtms` using cursor pagination.
2. WHEN the user submits the create-workbench form, THE Frontend SHALL create the workbench through `POST /api/v1/studies/{study_id}/sdtms` and, on a success response, refresh the list to include the created workbench.
3. WHEN the user opens an SDTM_Workbench, THE Frontend SHALL display a detail view that presents, as distinct and individually reachable sections, the input selection, Specification, Derivation Plan, aCRF, Define, cSDRG, validation, and artifact areas.
4. IF no Study_Context is selected, THEN THE Frontend SHALL display an empty-state message directing the user to select a study and SHALL NOT issue the list request.
5. IF a create-workbench request returns a Problem_Response, THEN THE Frontend SHALL display its `title` and `detail` and SHALL retain the user's form input.

### Requirement 10: Select and view exact Raw inputs for SDTM

**User Story:** As an SDTM programmer, I want to pin exact Raw inputs and read the resolved Raw context, so that my SDTM work consumes a specific validated Raw revision.

#### Acceptance Criteria

1. WHEN the user saves an input selection, THE Frontend SHALL send `PUT /api/v1/sdtms/{sdtm_id}/input-selection` with the exact `raw_id`, Raw revision, successful Raw validation-run ID, selected source-file artifact IDs with checksums, Raw dependency fingerprint, and the SDTM_Workbench ETag as `If-Match`.
2. WHEN an input selection exists, THE Frontend SHALL display the current selection from `GET /api/v1/sdtms/{sdtm_id}/input-selection` including its revision and state.
3. WHEN the user views the resolved Raw context, THE Frontend SHALL display it from `GET /api/v1/sdtms/{sdtm_id}/raw-context`.
4. IF an input-selection save returns `422 sdtm_raw_artifact_invalid` or `422 sdtm_raw_validation_invalid`, THEN THE Frontend SHALL display the specific Problem_Response `detail` and SHALL render its `issues` array when present.
5. WHILE an Input_Selection state is `input_refresh_required`, THE Frontend SHALL display a persistent notice stating that dependent SDTM work is stale and requires a refreshed selection.
6. IF an input-selection save returns `412`, THEN THE Frontend SHALL display a concurrency-conflict message and SHALL present a reload action that re-fetches the current SDTM_Workbench revision before retrying.

### Requirement 11: Author and exchange the SDTM Specification

**User Story:** As an SDTM programmer, I want to view, edit, import, and export the SDTM Specification, so that I can maintain target domain and variable metadata.

#### Acceptance Criteria

1. WHEN an SDTM_Workbench Specification view is open, THE Frontend SHALL display the current Specification from `GET /api/v1/sdtms/{sdtm_id}/specification` including its revision and schema version.
2. IF the Specification is not yet saved and the request returns `404 sdtm_specification_required`, THEN THE Frontend SHALL display an unsaved-Specification empty state.
3. WHEN the user saves a complete Specification, THE Frontend SHALL send `PUT /api/v1/sdtms/{sdtm_id}/specification` with the SDTM_Workbench ETag as `If-Match`.
4. WHEN the user imports a Specification file, THE Frontend SHALL send `POST /api/v1/sdtms/{sdtm_id}/specification/import` with the SDTM_Workbench ETag as `If-Match` and an `Idempotency-Key` header.
5. IF a Specification import returns `422 sdtm_specification_import_invalid`, THEN THE Frontend SHALL display the Problem_Response `detail` describing the invalid import and SHALL render its `issues` array when present.
6. WHEN the user exports the Specification, THE Frontend SHALL request `GET /api/v1/sdtms/{sdtm_id}/specification/export` with a `format` query value restricted to exactly `json` or `xlsx` and deliver the response as a download.
7. IF a Specification save returns `412`, THEN THE Frontend SHALL display a concurrency-conflict message and SHALL present a reload action that re-fetches the current Specification revision before retrying.

### Requirement 12: Author the SDTM Derivation Plan and surface alignment

**User Story:** As an SDTM programmer, I want to view and save the Derivation Plan and see its alignment state, so that I can define raw-to-domain transformations that stay consistent with the Specification and inputs.

#### Acceptance Criteria

1. WHEN the Derivation Plan view is open, THE Frontend SHALL display the current plan from `GET /api/v1/sdtms/{sdtm_id}/derivation-plan` including its revision, pinned specification revision, pinned input-selection revision, and Alignment_State value (`aligned` or `misaligned`).
2. WHEN the user saves a Derivation Plan, THE Frontend SHALL send `PUT /api/v1/sdtms/{sdtm_id}/derivation-plan` with the SDTM_Workbench ETag as `If-Match` and the pinned specification and input-selection revisions.
3. IF a Derivation Plan save returns `409 stale_input_fingerprint`, THEN THE Frontend SHALL display an error message indicating that the plan's pinned revisions do not match current inputs, SHALL identify the input (specification or input-selection) whose revision changed, and SHALL retain the user's unsaved plan edits.
4. WHILE a Derivation Plan Alignment_State is `misaligned`, THE Frontend SHALL display a misalignment notice and SHALL disable the validate, preview, compile, and execute actions.
5. WHEN the user requests plan validation, THE Frontend SHALL call `POST /api/v1/sdtms/{sdtm_id}/derivation-plan/validate` and, on success, display the returned status and IR fingerprint.
6. IF a plan validation request returns a Problem_Response, THEN THE Frontend SHALL display its `title` and `detail` and SHALL leave the previously displayed plan unchanged.
7. WHEN the user requests lineage, THE Frontend SHALL display the node lineage from `GET /api/v1/sdtms/{sdtm_id}/lineage`.

### Requirement 13: Preview SDTM derivation output

**User Story:** As an SDTM programmer, I want to preview derived domain rows from the aligned plan, so that I can inspect transformation output before compiling.

#### Acceptance Criteria

1. WHEN the user requests a derivation preview, THE Frontend SHALL call `POST /api/v1/sdtms/{sdtm_id}/derivation-plan/preview` with an optional domain selection and a row limit between 1 and 200 inclusive.
2. WHERE the user requests a preview limit outside the 1-to-200 inclusive range, THE Frontend SHALL constrain the request limit to the nearest value within that range before sending.
3. WHEN a preview response is received, THE Frontend SHALL display the produced domain outputs together with the specification revision, plan revision, and input-selection revision in the response.
4. WHEN a preview response contains no produced rows for a requested domain, THE Frontend SHALL display an empty-result indication for that domain rather than a blank view.
5. IF a preview returns `422 sdtm_preview_domain_unknown`, THEN THE Frontend SHALL display which requested domains were not produced.
6. THE Frontend SHALL NOT persist or cache preview rows beyond the lifetime of the preview view.

### Requirement 14: Validate an SDTM workbench

**User Story:** As an SDTM programmer, I want to validate the SDTM workbench and read its validation snapshot, so that I can confirm readiness before generating artifacts or executing programs.

#### Acceptance Criteria

1. WHEN the user triggers SDTM validation, THE Frontend SHALL call `POST /api/v1/sdtms/{sdtm_id}/validate` and, when accepted with `202`, SHALL poll the returned validation-run `Location` until the Validation_Run reaches a terminal status (`passed` or `failed`).
2. WHEN a Validation_Run reaches a terminal status, THE Frontend SHALL display the Validation_Run status and the per-severity issue counts (error, warning, and info counts).
3. WHEN a Validation_Run contains issues, THE Frontend SHALL display each issue's code, severity, message, suggestion, entity type, entity ID, field path, dataset, and variable from the common issue model.
4. THE Frontend SHALL display the validator name and validator version recorded on the Validation_Run.
5. IF a validation request returns a Problem_Response, THEN THE Frontend SHALL display its `title` and `detail` and SHALL render the `issues` array when present.

### Requirement 15: Compile SDTM programs

**User Story:** As an SDTM programmer, I want to compile the aligned plan into a Python, R, or SAS program, so that I can obtain generated program artifacts.

#### Acceptance Criteria

1. WHEN the user compiles, THE Frontend SHALL call `POST /api/v1/sdtms/{sdtm_id}/compile` with a backend value of `python`, `r`, or `sas`, the expected input fingerprint, and an `Idempotency-Key` header.
2. WHEN a compile request is accepted with `202`, THE Frontend SHALL poll the returned Artifact_Build `Location` until it reaches a terminal status (succeeded or failed) and, on success, SHALL list the produced program artifacts.
3. IF a polled Artifact_Build reaches a failed terminal status, THEN THE Frontend SHALL display the typed failure object recorded on the build resource and SHALL NOT list any partial program artifacts.
4. IF a compile returns `409 backend_capability_missing`, THEN THE Frontend SHALL display that the selected backend cannot implement the declared semantics.
5. WHERE the user requests additional SDTM metadata or report artifact types, THE Frontend SHALL call `POST /api/v1/sdtms/{sdtm_id}/artifacts` with the selected artifact types, expected input fingerprint, and an `Idempotency-Key` header.

### Requirement 16: Execute SDTM programs and view run output

**User Story:** As an SDTM programmer, I want to execute a compiled program against the exact inputs and read logs and outputs, so that I can produce SDTM datasets.

#### Acceptance Criteria

1. WHEN the user submits an execution, THE Frontend SHALL call `POST /api/v1/sdtms/{sdtm_id}/execute` with the language, program artifact ID, input artifact IDs, validation-run ID, pinned input-selection, specification, and plan revisions, compiler fingerprint, expected input fingerprint, accepted limits, and an `Idempotency-Key` header.
2. WHEN an execution is accepted with `202`, THE Frontend SHALL poll `GET /api/v1/execution-runs/{run_id}` until the Execution_Run reaches a terminal status (succeeded or failed).
3. WHEN an Execution_Run reaches a terminal status, THE Frontend SHALL display its status, timing, resource metrics, logs from `GET /api/v1/execution-runs/{run_id}/logs`, and output artifacts from `GET /api/v1/execution-runs/{run_id}/outputs`.
4. IF an Execution_Run terminates with `runner_not_configured`, THEN THE Frontend SHALL display that SAS execution requires an external runner and SHALL present the successfully generated program as still available.
5. IF an Execution_Run reaches a failed terminal status other than `runner_not_configured`, THEN THE Frontend SHALL display the typed failure object recorded on the run and SHALL present any captured logs when available.

### Requirement 17: Author aCRF annotations and view coverage

**User Story:** As an SDTM programmer, I want to create, edit, link, and delete aCRF annotations and view coverage, so that I can document CRF-to-SDTM traceability.

#### Acceptance Criteria

1. WHEN the aCRF view is open, THE Frontend SHALL list annotations from `GET /api/v1/sdtms/{sdtm_id}/acrf/annotations`.
2. WHEN the user creates an annotation, THE Frontend SHALL call `POST /api/v1/sdtms/{sdtm_id}/acrf/annotations` with the source PDF artifact ID, a page number that is an integer greater than or equal to 1, a normalized top-left rectangle whose `x`, `y`, `width`, and `height` are each a decimal within 0 through 1 inclusive, and the SDTM_Workbench ETag as `If-Match`.
3. IF the user submits an annotation rectangle where any of `x`, `y`, `width`, or `height` is outside 0 through 1 inclusive, or where `x + width` or `y + height` exceeds 1, THEN THE Frontend SHALL block submission and display a validation message identifying the out-of-range field, without issuing the create request.
4. WHEN the user edits or soft-deletes an annotation, THE Frontend SHALL send `PATCH` or `DELETE /api/v1/acrf-annotations/{annotation_id}` with the annotation ETag as `If-Match`, requiring an explicit confirmation before issuing the `DELETE`.
5. WHEN the user replaces or amends annotation links, THE Frontend SHALL call `POST /api/v1/acrf-annotations/{annotation_id}/links` with the annotation ETag as `If-Match`.
6. WHEN the user views coverage, THE Frontend SHALL display, from `GET /api/v1/sdtms/{sdtm_id}/acrf/coverage`, the total annotation count, the count and list of unlinked annotations, the count and list of unlinked SDTM variables, and the count and list of links pinned to non-current revisions.
7. WHEN the user builds the aCRF artifact, THE Frontend SHALL call `POST /api/v1/sdtms/{sdtm_id}/acrf/artifacts` with an `Idempotency-Key` header, then poll the resulting Artifact_Build at an interval of 2 seconds until it reaches a terminal state or 300 seconds elapse.
8. IF a polled Artifact_Build reaches a failed terminal state or polling reaches 300 seconds without a terminal state, THEN THE Frontend SHALL stop polling and display a build-failure or build-timeout indication that identifies the affected build, without presenting any artifact as available.

### Requirement 18: Author, validate, render, reconcile, and build Define-XML

**User Story:** As an SDTM programmer, I want to initialize, edit, validate, render, reconcile, and build Define-XML, so that I can produce version-neutral Define metadata and its 2.0/2.1 artifacts.

#### Acceptance Criteria

1. WHEN the Define view is open, THE Frontend SHALL display the current Define model from `GET /api/v1/sdtms/{sdtm_id}/define`.
2. WHEN the user initializes Define, THE Frontend SHALL call `POST /api/v1/sdtms/{sdtm_id}/define/initialize` with the SDTM_Workbench ETag, the expected Define revision, and the selected XPT artifact IDs.
3. WHEN the user saves the Define model, THE Frontend SHALL send `PUT /api/v1/sdtms/{sdtm_id}/define` with the SDTM_Workbench ETag as `If-Match`.
4. WHEN the user validates Define, THE Frontend SHALL call `POST /api/v1/sdtms/{sdtm_id}/define/validate` and display the resulting Validation_Run with its status, error and warning counts, and full issue list.
5. WHEN the user renders Define, THE Frontend SHALL request `GET /api/v1/sdtms/{sdtm_id}/define/render` with a `version` query value of exactly `2.0` or `2.1` and present the returned XML as a non-persisting preview.
6. WHEN the user reconciles Define, THE Frontend SHALL call `POST /api/v1/sdtms/{sdtm_id}/define/reconcile` with the exact Define revision, its fingerprint, and an `Idempotency-Key` header, then poll the resulting reconciliation run at an interval of 2 seconds until it reaches a terminal state or 300 seconds elapse.
7. WHEN the user builds Define artifacts, THE Frontend SHALL call `POST /api/v1/sdtms/{sdtm_id}/define/artifacts` with the selected version or versions, the canonical build-input fingerprint, and an `Idempotency-Key` header, then poll the resulting Artifact_Build at an interval of 2 seconds until it reaches a terminal state or 300 seconds elapse.
8. IF a polled reconciliation run or Artifact_Build reaches a failed terminal state or polling reaches 300 seconds without a terminal state, THEN THE Frontend SHALL stop polling and display a failure or timeout indication that identifies the affected run or build, without presenting any artifact as available.
9. IF an initialize, save, validate, reconcile, or build request returns a Problem_Response with code `409` indicating a stale revision or stale build input, THEN THE Frontend SHALL display a staleness-conflict message and refresh the current Define model before allowing retry.

### Requirement 19: Author, validate, and build the cSDRG

**User Story:** As an SDTM programmer, I want to initialize, edit, validate, and build the cSDRG, so that I can produce the reviewer guide with manually authored narrative.

#### Acceptance Criteria

1. WHEN the cSDRG view is open, THE Frontend SHALL display the current cSDRG from `GET /api/v1/sdtms/{sdtm_id}/csdrg`.
2. WHEN the user initializes the cSDRG, THE Frontend SHALL call `POST /api/v1/sdtms/{sdtm_id}/csdrg/initialize` with the SDTM_Workbench ETag, the expected cSDRG revision, the current Define revision, and the successful Define/XPT/aCRF reconciliation run ID.
3. WHEN the user saves cSDRG content, THE Frontend SHALL send `PUT /api/v1/sdtms/{sdtm_id}/csdrg` with the SDTM_Workbench ETag as `If-Match`, and SHALL present the required narrative sections `study_data_overview`, `standards_and_versions`, `trial_design`, `domain_notes`, `conformance_issues`, `sponsor_defined_domains`, `controlled_terminology`, `data_dependencies`, and `reviewer_guidance` as editable text fields, each preserving user-entered content without inferring or auto-populating clinical narrative.
4. WHEN the user validates the cSDRG, THE Frontend SHALL call `POST /api/v1/sdtms/{sdtm_id}/csdrg/validate` and display the resulting issues, treating any of the nine required narrative sections that is absent or contains only whitespace as an error-severity issue.
5. WHEN the user builds cSDRG artifacts, THE Frontend SHALL call `POST /api/v1/sdtms/{sdtm_id}/csdrg/artifacts` with an `Idempotency-Key` header, then poll the resulting Artifact_Build at an interval of 2 seconds until it reaches a terminal state or 300 seconds elapse.
6. IF a polled Artifact_Build reaches a failed terminal state or polling reaches 300 seconds without a terminal state, THEN THE Frontend SHALL stop polling and display a build-failure or build-timeout indication that identifies the affected build, without presenting any artifact as available.

### Requirement 20: Manage Raw and SDTM dependency selections

**User Story:** As a user, I want to view and replace the dependency selection for a Raw or SDTM workbench, so that each aggregate binds exact standards, terminology, reference, and template versions.

#### Acceptance Criteria

1. WHEN a dependency view is open, THE Frontend SHALL display the current selection from `GET /api/v1/raw/{raw_id}/dependencies` or `GET /api/v1/sdtms/{sdtm_id}/dependencies` including its revision and state.
2. WHEN the user replaces a dependency selection, THE Frontend SHALL send `PUT` to the corresponding dependencies route with the complete selection and the aggregate ETag as `If-Match`.
3. IF a dependency replacement returns `422 dependency_selection_invalid` or `422 dependency_selection_incomplete`, THEN THE Frontend SHALL display each incompatibility from the Problem_Response `issues` array, showing its message and, when present, its suggestion.
4. IF a dependency replacement returns `412`, THEN THE Frontend SHALL display a concurrency-conflict message and refresh the current selection before allowing retry.
5. WHILE a dependency-selection state is `dependency_refresh_required`, THE Frontend SHALL indicate that new validation, build, execution, and reconciliation operations are blocked until the selection is refreshed, and SHALL disable the controls that start those operations.

### Requirement 21: Consistent concurrency, idempotency, and error handling

**User Story:** As a user, I want conditional edits, retry-safe operations, and clear errors across Raw and SDTM screens, so that my work is protected from lost updates and transient failures.

#### Acceptance Criteria

1. WHEN the Frontend issues a `PATCH`, `PUT`, or `DELETE` against a mutable Raw or SDTM aggregate, THE Frontend SHALL include the current ETag as the `If-Match` header derived through the shared request helper.
2. WHEN the Frontend starts a bulk import, build, compile, execution, or reconciliation operation, THE Frontend SHALL include an `Idempotency-Key` header whose value is identical across automatic retries of that same operation attempt.
3. IF a request returns `428 Precondition Required`, THEN THE Frontend SHALL display that a required precondition header was missing and refresh the resource to obtain its current ETag before allowing retry.
4. IF a request returns `412 Precondition Failed`, THEN THE Frontend SHALL display a concurrency-conflict message and refresh the resource to obtain its current ETag before allowing retry.
5. IF a request returns a Problem_Response, THEN THE Frontend SHALL display the `title` and `detail`, and SHALL render each entry of the `issues` array when the array is present and non-empty.
6. WHEN a mutation returns a success response, THE Frontend SHALL invalidate the TanStack Query keys for the affected aggregate and its dependent collections so dependent views reload current data.
