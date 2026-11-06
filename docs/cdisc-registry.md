# CDISC registry coverage

The registry is designed around exact published packages, not a mutable "current CDISC" setting. A deployment can pin every approved release it is licensed or otherwise permitted to use, and every clinical aggregate selects exact release identities.

## Standards coverage

The product contract supports the CDISC product shapes used by the CDISC Library and published download packages:

- data collection: CDASH and CDASHIG;
- tabulation: SDTM, SDTMIG variants, and SENDIG variants;
- analysis: ADaM and ADaMIG variants;
- data exchange: ODM-XML, Define-XML, and Dataset-XML;
- foundational and digital protocol products, including DDF/USDM;
- therapeutic-area user guides and other implementation guides;
- measures and questionnaires represented as measure products with checked assets.

The family name remains data rather than a source-code enum so a newly published CDISC product can be registered without changing the database model. `product_type` captures the stable behavior needed by the platform. Model-to-guide and other release relationships are exact, directional compatibility records. A required relationship is enforced when a module saves its dependency selection.

## Controlled Terminology coverage

The terminology package contract supports ADaM, CDASH, DDF, Define-XML, MRCT, SDTM, SEND, and future CDISC CT products. It preserves:

- package code, terminology product, release version and publication date;
- NCI concept IDs for codelists and terms;
- codelist and term submission values;
- names/decodes, definitions, NCI preferred terms, and synonyms;
- codelist extensibility;
- active and retired terms;
- exact compatibility evidence linking a terminology scope to a standard version and dependency purpose.

Sponsor extensions remain separate study-owned overlays. They cannot shadow a published concept or submission value and cannot add a value to a non-extensible codelist. Retired published terms remain resolvable as historical content and are not silently replaced.

## On-demand CDISC Library acquisition

CDISC Library is the upstream source. An administrator imports only the exact product or terminology release required by a study or deployment:

```powershell
$env:CDISC_LIBRARY_API_KEY = "<key>"
python -m app.cdisc_registry import-selection /mdr/sdtmig/3-4
python -m app.cdisc_registry import-selection /mdr/ct/packages/sdtmct-2024-09-27
Remove-Item Env:CDISC_LIBRARY_API_KEY
```

The credential is read through the settings secret type and is never placed in a registry record, resource file, URL, or log. The importer accepts only HTTPS requests to the configured CDISC Library origin, does not follow redirects, bounds response sizes, retries, and graph size, and records canonical JSON plus SHA-256 for every selected resource. It follows only the selected root and descendant `/mdr/` links. Catalogs and `/mdr/root/` aliases are rejected because they do not identify an immutable exact release.

Verified bytes are published from an ephemeral staging workspace to checksum-addressed object storage before the registry transaction begins. The transaction records the selected href, acquisition time, Library update metadata, resource count, group checksum, and individual assets. Temporary files are destroyed at command completion. Standard Library resources remain individually queryable assets. Each selected terminology package is normalized into immutable codelists and terms while its source responses remain available as assets.

The legacy complete-snapshot commands remain available only to register already-existing repository snapshots. They are not the acquisition path for new deployments.

## Ingestion boundary

`python -m app.cdisc_registry` is an offline administrative command. On-demand acquisition validates the concrete provider identity, selected graph boundary, canonical bytes, SHA-256 checksums, product identity, and uniqueness before committing. Exceptional repository-backed imports continue to validate versioned Pydantic manifests, safe paths, and compatibility targets. The public API remains read-only for provider catalogs. There is deliberately no operation-time fetch, "latest" alias, silent upgrade, or API-key storage.

Deployments must review their right to retain and distribute CDISC publication content under their applicable access and license terms. Tests use synthetic concepts and package metadata and never contact CDISC.
