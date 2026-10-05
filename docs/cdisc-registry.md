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

## Complete CDISC Library snapshot

An administrator can snapshot every concrete resource reachable from the CDISC Library product and Controlled Terminology catalogs:

```powershell
$env:CDISC_LIBRARY_API_KEY = "<key>"
python -m app.cdisc_registry snapshot-all
python -m app.cdisc_registry register-snapshot `
  schemas/cdisc-library/<overall-last-updated>/snapshot-manifest.json
Remove-Item Env:CDISC_LIBRARY_API_KEY
```

The credential is read through the settings secret type and is never placed in a manifest, registry record, resource file, URL, or log. The crawler accepts only HTTPS requests to the configured CDISC Library origin, does not follow redirects, bounds response sizes and retries, and records canonical JSON plus SHA-256 for every resource. It follows concrete `/mdr/` links and excludes `/mdr/root/` aliases because those aliases represent mutable current content. A new snapshot and explicit aggregate selection are required to adopt later publications.

The registration command verifies the manifest and every resource checksum before committing. Standard Library resources remain individually queryable assets. Each terminology package is also normalized into immutable codelists and terms while its complete source response remains available as an asset.

## Ingestion boundary

`python -m app.cdisc_registry` is an offline administrative command. It validates versioned Pydantic manifests, safe repository-relative paths, SHA-256 checksums, product identity, uniqueness, and compatibility targets before committing. The API remains read-only for provider catalogs. There is deliberately no runtime fetch, "latest" alias, silent upgrade, or API-key storage.

Deployments must review their right to retain and distribute CDISC publication content under their applicable access and license terms. Tests use synthetic concepts and package metadata and never download standards at runtime.
