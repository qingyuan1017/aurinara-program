# Dependency-consuming module workflow

Raw, SDTM, ADaM, and TLF currently share one implemented Phase 1 workflow. Documents uses
the same dependency-selection shape but adds type-specific authoring and generation.

## Replace an exact dependency selection

First read the aggregate and retain its `ETag`. Then send the complete selection—not a
partial patch—to its `/dependencies` endpoint:

```json
{
  "standards": [
    {"purpose":"dependency_contract","standard_version_id":"<standard-version-uuid>"}
  ],
  "terminology": [
    {
      "scope":"controlled_values",
      "terminology_release_id":"<release-uuid>",
      "terminology_extension_revision_ids":[]
    }
  ],
  "references": [
    {
      "purpose":"study_context",
      "reference_id":"<reference-uuid>",
      "reference_revision_id":"<reference-revision-uuid>"
    }
  ],
  "templates": [
    {
      "purpose":"presentation",
      "artifact_type":"raw_dependency_manifest",
      "template_version_id":"<template-version-uuid>"
    }
  ]
}
```

Every ID is exact and validated for lifecycle, module applicability, purpose/scope, study
ownership, and compatibility. Omit categories the aggregate does not consume. Duplicate
purposes/scopes are rejected. The response contains selection `revision`, `state`, and
`fingerprint`.

If a selected Reference or terminology-extension revision is superseded, the state becomes
`dependency_refresh_required`. Explicitly replace or reaffirm the complete selection before
building again; Aurinara never silently follows “latest”.

## Build the current manifest artifact

Use `POST /artifact-builds` with the module's owner entity type (`raw_workbench`,
`sdtm_workbench`, `adam_workbench`, or `tlf_workbench`) and its sole current artifact type.
The request requires `Idempotency-Key` and the exact canonical input fingerprint described
in [shared platform usage](platform.md#work-with-artifacts-and-builds). Poll the returned
build resource, then retrieve the immutable artifact by ID.
