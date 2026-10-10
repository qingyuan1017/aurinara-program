# Artifact Catalog

## 1. Catalog rules

This catalog defines every Release 1 artifact, its source of truth, prerequisites, media type, and downstream use. Artifact bytes and metadata are immutable. Rebuilding produces a new artifact ID even when the bytes happen to be identical.

Artifact types are owned through the startup module registry. Each type in this catalog has exactly one registered owner and builder contract. A deployment-added module may add types through its reviewed `ModuleDescriptor` and versioned catalog documentation; startup rejects duplicate type ownership. Shared artifact services dispatch through the registered artifact capability rather than module-name branches.

Every artifact record contains:

```text
id
study_id
module
artifact_type
owner_type
owner_id
filename
media_type
object_key
sha256
size
input_fingerprint
dependency_selection_revision
dependency_fingerprint
input_selection_revision
source_specification_revision
source_specification_fingerprint
source_plan_type
source_plan_revision
compiler_fingerprint
generator_name
generator_version
status
validation_run_id
reconciliation_run_id
execution_run_id
created_by
created_at
```

The object key is derived from the byte checksum and never from a user-supplied path. The display filename is normalized separately. `dependency_selection_revision` is null only when an artifact has no clinical owning aggregate. `input_selection_revision`, `source_specification_revision`, and `source_specification_fingerprint` are required for SDTM and ADaM transformation outputs and null when the artifact type has no such source. The dependency fingerprint covers the complete resolved dependency snapshot. `source_plan_type` is a registered module-owned type such as `sdtm_derivation`, `adam_derivation`, or `tlf_program`, or null. An artifact manifest records every selected Standard version and asset checksum, Terminology release and extension revision, Reference identity and revision, Template version and checksum, compatibility decision, selected upstream input IDs and checksums, validation rule-pack version, module-owned Specification and source-plan revisions and internal IR/operator/compiler versions when applicable, generator settings, and warnings from the bound validation or reconciliation run.

Artifacts become stale when the current fingerprint of any declared dependency differs from `input_fingerprint`, when the owning aggregate accepts a different dependency selection, or when a selected mutable logical dependency is superseded and requires explicit refresh. Merely publishing a new immutable Standard, Terminology release, or Template version does not stale a pinned artifact. Stale artifacts remain available for audit and comparison but are rejected by submission packaging. A package accepts exact artifact IDs only; it never silently selects the newest version.

## 2. Shared artifact types

| Artifact type                  | Format              | Created by               | Required inputs                               | Package use                                                      |
| ------------------------------ | ------------------- | ------------------------ | --------------------------------------------- | ---------------------------------------------------------------- |
| `source_file`                  | Original media type | Upload service           | Validated upload                              | Upstream evidence/input; included only when selected and allowed |
| `validation_report_json`       | JSON                | Validation service       | Completed validation run                      | `reports/`                                                       |
| `validation_report_pdf`        | PDF                 | Shared document renderer | Completed validation run                      | `reports/`                                                       |
| `execution_manifest`           | JSON                | Execution service        | Valid plan, selected inputs, compiled program | Traceability/reporting                                           |
| `execution_stdout`             | text/plain          | Runner                   | Completed execution attempt                   | Execution logs                                                   |
| `execution_stderr`             | text/plain          | Runner                   | Completed execution attempt                   | Execution logs                                                   |
| `execution_metrics`            | JSON                | Runner                   | Completed execution attempt                   | Execution logs/reporting                                         |
| `submission_manifest`          | JSON                | Packaging service        | Accepted artifact selection                   | Package root as `manifest.json`                                  |
| `submission_checksums`         | text/plain          | Packaging service        | Final package entries                         | Package root as `checksums.sha256`                               |
| `submission_validation_report` | JSON and/or PDF     | Packaging service        | Completed package reconciliation              | Immutable package companion and `reports/`                       |
| `submission_zip`               | ZIP                 | Packaging service        | Successful package validation                 | Downloadable final package                                       |

Validation reports are generated even when errors exist. Failed build attempts retain structured failure metadata; partial output bytes are not published as available artifacts.

## 3. Shared component artifacts

| Artifact type                       | Format | Prerequisites                                                     | Principal source                               | Package use                                                               |
| ----------------------------------- | ------ | ----------------------------------------------------------------- | ---------------------------------------------- | ------------------------------------------------------------------------- |
| `standards_selection_manifest_json` | JSON   | Selected versions, assets, and compatibility links validated      | Exact study-owned dependency selection         | `support/standards/` when selected                                        |
| `terminology_release_manifest_json` | JSON   | Release assets and checksums validated                            | Exact terminology release                      | `support/terminology/` when selected                                      |
| `terminology_extension_json`        | JSON   | Extension values and base-release references valid                | Study terminology extension revision           | `support/terminology/` when selected                                      |
| `reference_data_json`               | JSON   | Selected study Reference revisions valid                          | Exact selected Reference revisions             | `support/reference/` when selected                                        |
| `reference_data_xlsx`               | XLSX   | Same as JSON                                                      | Same typed selected revisions                  | `support/reference/` when selected                                        |
| `template_selection_manifest_json`  | JSON   | Selected template assets and compatibility metadata valid         | Exact study-owned dependency selection         | Supporting provenance when selected                                       |
| `review_report_json`                | JSON   | Selected review items and comments resolved and visible to caller | Exact review-item IDs and revisions            | `reports/review/`                                                         |
| `review_report_pdf`                 | PDF    | Same as JSON plus exact compatible report template                | Shared `Document` representation               | `reports/review/`                                                         |
| `validation_rule_pack_json`         | JSON   | Rule versions, parameters, and applicability valid                | Released or study-scoped rule pack revision    | `support/validation/` when selected                                       |
| `reconciliation_report_json`        | JSON   | Reconciliation run terminal                                       | Immutable reconciliation run                   | `reports/reconciliation/`                                                 |
| `reconciliation_report_pdf`         | PDF    | Same as JSON plus exact compatible report template                | Same run and shared renderer                   | `reports/reconciliation/`                                                 |
| `raw_dependency_manifest`           | JSON   | Current exact Raw dependency selection                            | Raw workbench and resolved provider checksums  | Phase 1 provenance evidence; not a submission substitute for Raw metadata |
| `documents_dependency_manifest`     | JSON   | Current exact Documents dependency selection                      | Document and resolved provider checksums       | Phase 1 provenance evidence                                               |
| `sdtm_dependency_manifest`          | JSON   | Current exact SDTM dependency selection                           | SDTM workbench and resolved provider checksums | Phase 1 provenance evidence                                               |
| `adam_dependency_manifest`          | JSON   | Current exact ADaM dependency selection                           | ADaM workbench and resolved provider checksums | Phase 1 provenance evidence                                               |
| `tlf_dependency_manifest`           | JSON   | Current exact TLF dependency selection                            | TLF workbench and resolved provider checksums  | Phase 1 provenance evidence                                               |

Shared provider artifacts are study-scoped exports of exact dependency selections, not exports of a mutable global catalog. They never embed licensed terminology content unless the selected release permits redistribution; manifests may contain identifiers, versions, provenance, and checksums instead. Review artifacts contain only items the requester is authorized to see. Rule-pack artifacts are declarative data and never contain executable code.

## 4. Raw artifacts

| Artifact type                | Format | Prerequisites                             | Principal source             | Package use                                       |
| ---------------------------- | ------ | ----------------------------------------- | ---------------------------- | ------------------------------------------------- |
| `raw_metadata_json`          | JSON   | Valid saved dataset and variable metadata | Raw workbench revision       | Supporting documentation when explicitly selected |
| `raw_dictionary_xlsx`        | XLSX   | Valid saved dataset and variable metadata | Raw workbench revision       | Supporting documentation when explicitly selected |
| `raw_validation_report_json` | JSON   | Completed Raw validation                  | Immutable validation run     | `reports/` when explicitly selected               |
| `raw_validation_report_pdf`  | PDF    | Completed Raw validation                  | Same run and shared renderer | `reports/` when explicitly selected               |

Each raw dataset record binds to an exact immutable source-file record and its corresponding `source_file` artifact from the shared catalog. The Raw module does not copy or overwrite the uploaded bytes. A replacement upload creates a new source-file record and artifact, and rebinding a dataset creates a new workbench revision whose dependency fingerprint includes the file artifact ID and checksum.

Bulk dataset import (`POST /api/v1/raw/{raw_id}/datasets/import`) creates the same `raw_dataset` and `raw_dataset_file_bindings` records with identical provenance as single-dataset create; it introduces no new artifact type.

Raw metadata artifacts include dataset and variable natural keys, labels, physical attributes, ordinal positions, user-authored descriptions, roles, controlled terminology references, source-file artifact IDs and checksums, and the validated workbench revision. They do not contain data rows. Original source files are excluded from submission packages unless an explicit package policy permits them and the caller selects their exact artifact IDs.

## 5. Documents artifacts

| Artifact type                                              | Format | Prerequisites                                                                                                         | Principal source                                                      | Suggested filename                                         |
| ---------------------------------------------------------- | ------ | --------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------- | ---------------------------------------------------------- |
| `protocol_original`                                        | PDF    | Successful upload checks                                                                                              | Uploaded protocol file                                                | `protocol.pdf`                                             |
| `protocol_usdm`                                            | JSON   | Valid saved USDM structure                                                                                            | Versioned USDM document                                               | `protocol-usdm.json`                                       |
| `protocol_summary_docx`                                    | DOCX   | No blocking protocol validation issues                                                                                | Shared `Document` built from USDM and saved narrative                 | `protocol-summary.docx`                                    |
| `protocol_summary_pdf`                                     | PDF    | Same as DOCX                                                                                                          | Same shared `Document`                                                | `protocol-summary.pdf`                                     |
| `protocol_annotated_evidence`                              | PDF    | Valid evidence coordinates and entity links                                                                           | Original PDF plus evidence records                                    | `protocol-annotated-evidence.pdf`                          |
| `protocol_evidence_manifest_json`                          | JSON   | Evidence set validated                                                                                                | Evidence records and linked USDM IDs                                  | `protocol-evidence.json`                                   |
| `protocol_evidence_manifest_csv`                           | CSV    | Evidence set validated                                                                                                | Same as JSON                                                          | `protocol-evidence.csv`                                    |
| `protocol_amendment_summary_of_change_pdf`                 | PDF    | Amendment references and change entries valid                                                                         | Manually maintained amendment summary content                         | `protocol-amendment-summary-of-change.pdf`                 |
| `protocol_deviation_document_pdf`                          | PDF    | Required deviation sections and references valid                                                                      | Manually maintained protocol deviation content                        | `protocol-deviation-document.pdf`                          |
| `aggregate_study_risk_profile_pdf`                         | PDF    | Risk entries, owners, status values, and references valid                                                             | Manually maintained aggregate risk profile                            | `aggregate-study-risk-profile.pdf`                         |
| `data_management_plan_pdf`                                 | PDF    | Required plan sections and responsibilities valid                                                                     | Manually maintained data management plan                              | `data-management-plan.pdf`                                 |
| `statistical_analysis_plan_structured_content_json`        | JSON   | SAP content passes contract validation                                                                                | Structured SAP content                                                | `statistical-analysis-plan.json`                           |
| `statistical_analysis_plan_docx`                           | DOCX   | Required sections complete; estimands complete; references valid; material assumptions resolved; no validation errors | Shared `Document`                                                     | `statistical-analysis-plan.docx`                           |
| `statistical_analysis_plan_pdf`                            | PDF    | Same as DOCX                                                                                                          | Same shared `Document`                                                | `statistical-analysis-plan.pdf`                            |
| `centralized_monitoring_platform_setup_documentation_pdf`  | PDF    | Platform setup fields, roles, data feeds, and review sections valid                                                   | Manually maintained setup documentation                               | `centralized-monitoring-platform-setup-documentation.pdf`  |
| `protocol_deviation_dataset_xlsx`                          | XLSX   | Deviation rows and controlled values valid                                                                            | Manually maintained or atomically imported PD dataset rows            | `protocol-deviation-dataset.xlsx`                          |
| `aggregate_study_brief_pdf`                                | PDF    | Required study summary sections and references valid                                                                  | Manually maintained aggregate study brief                             | `aggregate-study-brief.pdf`                                |
| `study_data_summary_pdf`                                   | PDF    | Dataset references and summary sections valid                                                                         | Manually maintained study data summary                                | `study-data-summary.pdf`                                   |
| `standard_quality_dashboard_qe_details_xlsx`               | XLSX   | QE detail rows and controlled values valid                                                                            | Manually maintained or atomically imported QE details                 | `standard-quality-dashboard-qe-details.xlsx`               |
| `standard_quality_dashboard_sqe_audit_capa_details_xlsx`   | XLSX   | SQE, audit, and CAPA rows and references valid                                                                        | Manually maintained or atomically imported SQE and Audit CAPA details | `standard-quality-dashboard-sqe-audit-capa-details.xlsx`   |
| `standard_quality_dashboard_audit_observation_detail_xlsx` | XLSX   | Audit observation rows and references valid                                                                           | Manually maintained or atomically imported audit observations         | `standard-quality-dashboard-audit-observation-detail.xlsx` |
| `signals_report_xlsx`                                      | XLSX   | Signal rows, status values, owners, and references valid                                                              | Manually maintained or atomically imported signals                    | `signals-report.xlsx`                                      |
| `actions_report_xlsx`                                      | XLSX   | Action rows, status values, owners, due dates, and references valid                                                   | Manually maintained or atomically imported actions                    | `actions-report.xlsx`                                      |
| `document_citation_report_json`                            | JSON   | Citation links resolved                                                                                               | Citations and cross-document alignment                                | `<document-code>-citations.json`                           |
| `document_citation_report_csv`                             | CSV    | Same as JSON                                                                                                          | Same report model                                                     | `<document-code>-citations.csv`                            |
| `document_validation_report_json`                          | JSON   | Completed document validation                                                                                         | Immutable validation run                                              | `<document-code>-validation.json`                          |
| `document_validation_report_pdf`                           | PDF    | Completed document validation                                                                                         | Same run and shared renderer                                          | `<document-code>-validation.pdf`                           |

Protocol validation covers the selected USDM schema, identifier uniqueness, relationship integrity, objectives, endpoints, arms, epochs, interventions, eligibility, schedules, amendments, and evidence coverage. Evidence coordinates must be within the referenced PDF page and preserve the page coordinate system in metadata.

All generated narrative PDF artifacts in this module are rendered from the shared `Document` representation; uploaded originals and annotated evidence overlays retain their source/evidence-specific builders. All XLSX artifacts are rendered with `openpyxl` from typed, versioned sheet and row contracts. The clinical content, risks, deviations, signals, actions, observations, CAPA details, and review decisions come only from persisted user-maintained records; builders do not infer or propose them.

The Statistical Analysis Plan uses a read-only protocol context. Its artifacts fingerprint both manually maintained SAP content and the exact Protocol entities and revisions selected by the user. Other cross-document references likewise record exact document IDs and revisions. Workbook validation covers required sheets and columns, stable row identifiers, controlled values, date and identifier formats, duplicate keys, and referential integrity before any import is committed or artifact is generated.

## 6. SDTM artifacts

| Artifact type               | Format    | Prerequisites                                                                                                                                                  | Principal source                                 | Package location                          |
| --------------------------- | --------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------ | ----------------------------------------- |
| `sdtm_specification_json`   | JSON      | Valid Specification aligned with the selected standards                                                                                                        | Exact SDTM Specification revision                | Supporting documentation when selected    |
| `sdtm_specification`        | XLSX      | Valid domains, variables, value-level metadata, terminology bindings, and trace targets                                                                        | SDTM Specification                               | `sdtm/` or package documentation location |
| `sdtm_derivation_plan_json` | JSON      | Valid per-domain Derivation Plan aligned to the SDTM Specification and exact Raw input selection; `manifest.domain_code` and per-domain `source_plan_revision` | Canonical per-domain SDTM Derivation Plan        | `sdtm/programs/`                          |
| `sdtm_program_python`       | Python    | Valid aligned Specification and the one per-domain Derivation Plan with exact Raw inputs; `manifest.domain_code` and per-domain `source_plan_revision`         | Shared compiler framework                        | `sdtm/programs/`                          |
| `sdtm_program_r`            | R         | Same                                                                                                                                                           | Deterministic compiler                           | `sdtm/programs/`                          |
| `sdtm_program_sas`          | SAS       | Same                                                                                                                                                           | Deterministic compiler                           | `sdtm/programs/`                          |
| `sdtm_dataset_xpt`          | XPT v5    | Successful Python/R execution or accepted external SAS execution; output reconciliation                                                                        | Execution output                                 | `sdtm/data/`                              |
| `sdtm_execution_log`        | Text/JSON | Execution attempt                                                                                                                                              | Runner logs and metrics                          | `reports/` or `sdtm/programs/`            |
| `sdtm_derivation_report`    | PDF/JSON  | Valid aligned Specification and Derivation Plan                                                                                                                | Derivation Plan, assertions, and target metadata | `reports/`                                |
| `sdtm_lineage_report`       | PDF/JSON  | Resolved raw-to-target links                                                                                                                                   | Derivation and trace links                       | `reports/`                                |
| `sdtm_validation_report`    | PDF/JSON  | Completed validation                                                                                                                                           | Validation run                                   | `reports/`                                |
| `sdtm_acrf`                 | PDF       | Reconciled annotations and coverage                                                                                                                            | CRF PDF and aCRF annotations                     | `sdtm/acrf/`                              |
| `sdtm_define_xml_20`        | XML       | Define validation, XSD validation, dataset and aCRF reconciliation                                                                                             | Version-neutral Define model                     | `sdtm/define/`                            |
| `sdtm_define_xml_21`        | XML       | Same for 2.1                                                                                                                                                   | Version-neutral Define model                     | `sdtm/define/`                            |
| `sdtm_csdrg_docx`           | DOCX      | Required factual and narrative sections valid                                                                                                                  | cSDRG content and selected metadata              | `sdtm/reviewers-guide/`                   |
| `sdtm_csdrg_pdf`            | PDF       | Same                                                                                                                                                           | Same shared `Document`                           | `sdtm/reviewers-guide/`                   |

There is one `sdtm_dataset_xpt` artifact per selected approved domain. The artifact owner identifies the domain and execution run. SDTM programs and XPTs are per domain: each carries `manifest.domain_code` and the per-domain `source_plan_revision`. Splitting the legacy single plan into per-domain plans recomputes each plan fingerprint, so artifacts built from the pre-split aggregate plan become stale; stale artifacts are retained for audit but rejected from new submission packages. The platform must verify XPT v5 constraints during both write and read-back.

An aCRF annotation may reference multiple SDTM variables, Raw variables, and stable nodes or assertions in an exact per-domain SDTM Derivation Plan revision (the annotation link additionally carries the owning `domain`). Coverage reports identify unannotated CRF regions in scope, unresolved links, and Define references that lack matching annotations.

Define initialization may add missing structures inferred from the exact SDTM Specification and selected output artifacts; it does not overwrite manually edited structures. Both Define versions are independent artifacts tied to the same version-neutral model revision.

## 7. ADaM artifacts

| Artifact type               | Format    | Prerequisites                                                                                                                                                      | Principal source                           | Package location                          |
| --------------------------- | --------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------ | ----------------------------------------- |
| `adam_specification_json`   | JSON      | Valid datasets, variables, parameters, value-level metadata, methods, terminology, and trace targets                                                               | Exact ADaM Specification revision          | Supporting documentation when selected    |
| `adam_specification`        | XLSX      | Valid datasets, variables, parameters, value-level metadata, methods, terminology, and trace targets                                                               | ADaM Specification                         | `adam/` or package documentation location |
| `adam_derivation_plan_json` | JSON      | Valid per-dataset Derivation Plan aligned to the ADaM Specification and exact SDTM input selection; `manifest.dataset_code` and per-dataset `source_plan_revision` | Canonical per-dataset ADaM Derivation Plan | `adam/programs/`                          |
| `adam_program_python`       | Python    | Valid per-dataset Derivation Plan and exact SDTM inputs; `manifest.dataset_code` and per-dataset `source_plan_revision`                                            | Shared compiler framework                  | `adam/programs/`                          |
| `adam_program_r`            | R         | Same                                                                                                                                                               | Deterministic compiler                     | `adam/programs/`                          |
| `adam_program_sas`          | SAS       | Same                                                                                                                                                               | Deterministic compiler                     | `adam/programs/`                          |
| `adam_dataset_csv`          | CSV       | Successful execution and declared output-schema validation                                                                                                         | Execution output                           | Supporting execution evidence             |
| `adam_dataset_xpt`          | XPT v5    | Successful execution and independent read-back verification                                                                                                        | Execution output                           | `adam/data/`                              |
| `adam_execution_log`        | Text/JSON | Execution attempt                                                                                                                                                  | Runner logs and metrics                    | `reports/` or `adam/programs/`            |
| `adam_derivation_report`    | PDF/JSON  | Valid derivations and method alignment                                                                                                                             | Derivation Plan and ADaM Specification     | `reports/`                                |
| `adam_traceability_report`  | PDF/JSON  | Resolved SDTM-to-ADaM links                                                                                                                                        | Trace links and selected inputs            | `reports/`                                |
| `adam_validation_report`    | PDF/JSON  | Completed validation                                                                                                                                               | Validation run                             | `reports/`                                |
| `adam_define_xml_20`        | XML       | XSD and dataset reconciliation                                                                                                                                     | Version-neutral ADaM Define model          | `adam/define/`                            |
| `adam_define_xml_21`        | XML       | Same for 2.1                                                                                                                                                       | Version-neutral ADaM Define model          | `adam/define/`                            |
| `adam_adrg_docx`            | DOCX      | Required factual and narrative sections valid                                                                                                                      | ADRG content and metadata                  | `adam/reviewers-guide/`                   |
| `adam_adrg_pdf`             | PDF       | Same                                                                                                                                                               | Same shared `Document`                     | `adam/reviewers-guide/`                   |

Each ADaM execution fingerprints the exact SDTM input selection, ADaM Specification revision, Derivation Plan revision, dependency selection, normalized IR/operator/compiler versions, runner image, runtime parameters, and declared output schemas. The traceability report must resolve every declared SDTM origin to an artifact and variable in that exact input set, every method to its documented Derivation Plan nodes and outputs, and every Protocol/SAP relationship to verified Documents and ADaM trace endpoints.

## 8. TLF artifacts

| Artifact type                  | Format    | Prerequisites                                            | Principal source                       | Package location         |
| ------------------------------ | --------- | -------------------------------------------------------- | -------------------------------------- | ------------------------ |
| `tlf_dependency_manifest`      | JSON      | Current exact dependency selection                       | Dependency capability                  | Supporting documentation |
| `tlf_shell_json`               | JSON      | Valid current shell                                      | Shell model                            | Supporting documentation |
| `tlf_bindings_json`            | JSON      | Exact validated ADaM bindings                            | Bindings model                         | Supporting documentation |
| `tlf_assumptions_json`         | JSON      | Valid manually authored assumptions                      | Assumptions model                      | Supporting documentation |
| `tlf_ars_json`                 | JSON      | Complete analysis references and leaf coverage           | ARS model                              | Supporting documentation |
| `tlf_program_plan_json`        | JSON      | Every ARS analysis mapped to one typed step               | ProgramPlan model                      | Supporting documentation |
| `tlf_program_python`           | Python    | Valid shell, bindings, assumptions, ARS, and ProgramPlan | Shared compiler framework              | `tlf/programs/`          |
| `tlf_program_r`                | R         | Same                                                     | Deterministic compiler                 | `tlf/programs/`          |
| `tlf_program_sas`              | SAS       | Same                                                     | Deterministic compiler                 | `tlf/programs/`          |
| `tlf_result_csv`               | CSV       | Successful execution and result validation               | Execution output                       | `tlf/results/`           |
| `tlf_result_parquet`           | Parquet   | Same normalized result and exact execution                | Execution output                       | `tlf/results/`           |
| `tlf_table_rtf`                | RTF       | Result bound to shell and run                            | Output renderer                        | `tlf/outputs/`           |
| `tlf_table_pdf`                | PDF       | Same                                                     | Output renderer                        | `tlf/outputs/`           |
| `tlf_listing_rtf`              | RTF       | Same                                                     | Output renderer                        | `tlf/outputs/`           |
| `tlf_listing_pdf`              | PDF       | Same                                                     | Output renderer                        | `tlf/outputs/`           |
| `tlf_figure_png`               | PNG       | Figure result and specification valid                    | Figure renderer                        | `tlf/outputs/`           |
| `tlf_figure_svg`               | SVG       | Same                                                     | Figure renderer                        | `tlf/outputs/`           |
| `tlf_figure_pdf`               | PDF       | Same                                                     | Figure renderer                        | `tlf/outputs/`           |
| `tlf_execution_log`            | Text/JSON | Execution attempt                                        | Runner logs and metrics                | `reports/`               |
| `tlf_validation_report`        | JSON      | Completed current validation                             | Validation run                         | `reports/`               |
| `tlf_output_index`             | JSON      | Current successful run and selected normalized result    | TLF run, result, and ProgramPlan       | `tlf/outputs/`           |

Every TLF computation records the source ProgramPlan revision, normalized Analysis/Dataflow IR fingerprint, procedure/operator versions, and compiler version. Every rendered output records the workbench ID, compiled program artifact and checksum, execution run ID, input ADaM artifact IDs and checksums, result artifact ID and checksum, renderer and Template versions, and shell revision. Layout and rendering never enter compiler IR. Programs, results, and rendered outputs from different runs cannot be combined in one package.

## 9. Submission package

The request specifies the desired modules and exact artifact IDs. A successful package has this layout:

```text
raw/
support/standards/
support/terminology/
support/reference/
support/validation/
documents/protocol/
documents/sap/
documents/operations/
documents/quality/
sdtm/data/
sdtm/programs/
sdtm/define/
sdtm/acrf/
sdtm/reviewers-guide/
adam/data/
adam/programs/
adam/define/
adam/reviewers-guide/
tlf/programs/
tlf/results/
tlf/outputs/
reports/
reports/review/
reports/reconciliation/
manifest.json
checksums.sha256
```

The `raw/` directory is present only when the package request explicitly selects the Raw module. It contains metadata and data-dictionary artifacts by default; original source files require a separately configured package policy and exact artifact selection.

A deployment-added module with the package-contribution capability may add paths only below its registered lowercase module root, such as `labs/`. Its contributor returns a closed options contract, required artifact types, reconciliation requirements, and deterministic trusted path rules. It cannot write into another module's root or into reserved `support/`, `reports/`, `manifest.json`, or `checksums.sha256` paths. The central packaging service still performs ownership, checksum, collision, traversal, Unicode, and staleness checks.

Shared component artifacts are included only by exact artifact ID. Licensed terminology payloads are never added unless the pinned asset's distribution policy explicitly allows it; a version-and-checksum manifest is used otherwise.

Documents artifacts are placed under deterministic type-owned paths. Protocol and Statistical Analysis Plan artifacts use their dedicated directories; study plans, briefs, summaries, and monitoring setup documents use `documents/operations/`; quality dashboards, deviation datasets, signals, and actions use `documents/quality/`. When multiple records of one type are selected, package filenames include the server-validated `document_code`; user-facing filenames are never used as archive paths.

Before assembly, the packaging service:

1. verifies that the requester can access the study and every artifact belongs to it;
2. invokes each selected registered module's package contributor and verifies all required artifacts were explicitly selected;
3. rejects artifacts that are unavailable, stale, invalid, or tied to failed/incomplete runs;
4. verifies each artifact's dependency-selection revision, provider checksums, lifecycle state, and compatibility evidence, and rejects inconsistent cross-artifact selections without upgrading them;
5. downloads and recalculates every SHA-256 checksum;
6. executes registered module reconciliation requirements, including each Define document against its selected datasets;
7. reconciles the aCRF with the selected SDTM Define document;
8. reconciles ADaM lineage with the selected SDTM datasets;
9. verifies TLF programs, results, and outputs share one run lineage;
10. rejects duplicate case-normalized filenames, reserved names, absolute paths, traversal segments, and unsafe archive paths;
11. writes a deterministic manifest and checksum file, then validates the completed ZIP.

The manifest lists package path, artifact ID, artifact type, owner, source filename, SHA-256, size, media type, generator and version, validation run, reconciliation run when applicable, execution run, input fingerprint, dependency-selection revision and fingerprint, input-selection revision, source Specification revision/fingerprint when applicable, exact Standard versions, Terminology releases and extension revisions, Reference identities and revisions, Template versions, rule-pack versions, module source-plan type/revision and internal IR/operator/procedure/compiler versions when applicable, compatibility decision, and warning summary for each entry.

The ZIP and package validation report are stored as immutable artifacts. A later rebuild creates a new package and does not replace the prior one.

## 10. Retention and deletion

Release 1 should use retention policies rather than hard deletion for generated artifacts. Deleting an owning workbench or study is outside ordinary module operations and requires a separately designed administrative lifecycle. Object-store lifecycle rules must not remove bytes while an artifact or package record still references them.
