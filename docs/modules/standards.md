# Standards module

Status: implemented as a read-only catalog of exact standard products, versions,
checksum-addressed assets, and compatibility relationships. CDISC releases are acquired
on demand from CDISC Library by the offline administration command; public API and worker
operations never call the provider.

## Use it

Seed the catalogs with `uv run python -m app.catalog_seed`, then discover products and pin
an exact version ID in a clinical module's dependency selection:

```powershell
$products = Invoke-RestMethod -Uri "$base/standards?provider=CDISC" -Headers $headers
$product = Invoke-RestMethod -Uri "$base/standards/$($products[0].id)" -Headers $headers
$versions = Invoke-RestMethod -Uri "$base/standards/$($product.id)/versions" -Headers $headers
Invoke-RestMethod -Uri "$base/standard-versions/$($versions[0].id)/assets" -Headers $headers
Invoke-RestMethod -Uri "$base/standard-versions/$($versions[0].id)/compatibilities" -Headers $headers
```

Use filters such as provider, module, purpose, lifecycle, and compatible version when they
appear in OpenAPI. Filters narrow the catalog; they never choose a version for an aggregate.
Asset content is returned from the immutable object-store snapshot after checksum verification.

There are no runtime create, edit, or delete endpoints. Importing a standard is an explicit
administrator operation selecting one exact CDISC Library href. Existing aggregates remain
pinned when a newer version is published or imported.
