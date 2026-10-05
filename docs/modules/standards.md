# Standards module

Status: implemented as a read-only catalog of repository-pinned standard products,
versions, assets, and compatibility relationships.

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
Asset content is returned from the checked repository copy after checksum verification.

There are no runtime create, edit, or delete endpoints. Publishing a standard is a reviewed
repository and seed-data change. Existing aggregates remain pinned when a newer version is
published.
