import { createFileRoute } from '@tanstack/react-router'
import { PageHeader } from '@/components/layout/page-header'
import { ResourceTable } from '@/components/data/resource-table'
import type { ResourceColumn } from '@/components/data/resource-table'
import { StatusBadge } from '@/components/data/status-badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  useListReleases,
  useListStandards,
  useListTemplates,
} from '@/api/generated/provider-catalogs/provider-catalogs'
import type {
  CatalogIdentity,
  StandardProductResponse,
  TerminologyReleaseResponse,
} from '@/api/generated/model'

export const Route = createFileRoute('/_app/standards')({
  component: StandardsPage,
})

const productColumns: ResourceColumn<StandardProductResponse>[] = [
  { key: 'code', header: 'Code' },
  { key: 'name', header: 'Name' },
  { key: 'provider', header: 'Provider' },
  { key: 'family', header: 'Family' },
  { key: 'product_type', header: 'Product type' },
  { key: 'scope', header: 'Scope' },
]

const releaseColumns: ResourceColumn<TerminologyReleaseResponse>[] = [
  { key: 'code', header: 'Code' },
  { key: 'version', header: 'Version' },
  { key: 'provider', header: 'Provider' },
  { key: 'product', header: 'Product' },
  {
    key: 'lifecycle',
    header: 'Lifecycle',
    cell: (row) => <StatusBadge status={row.lifecycle} />,
  },
  { key: 'content_schema_version', header: 'Content schema' },
]

const templateColumns: ResourceColumn<CatalogIdentity>[] = [
  { key: 'code', header: 'Code' },
  { key: 'name', header: 'Name' },
]

function ProductsTab() {
  const { data, isLoading, isError, error } = useListStandards()
  return (
    <ResourceTable
      columns={productColumns}
      rows={data ?? []}
      getRowId={(row) => row.id}
      isLoading={isLoading}
      isError={isError}
      error={error}
      resourceLabel="standard products"
    />
  )
}

function ReleasesTab() {
  const { data, isLoading, isError, error } = useListReleases()
  return (
    <ResourceTable
      columns={releaseColumns}
      rows={data ?? []}
      getRowId={(row) => row.id}
      isLoading={isLoading}
      isError={isError}
      error={error}
      resourceLabel="terminology releases"
    />
  )
}

function TemplatesTab() {
  const { data, isLoading, isError, error } = useListTemplates()
  return (
    <ResourceTable
      columns={templateColumns}
      rows={data ?? []}
      getRowId={(row) => row.id}
      isLoading={isLoading}
      isError={isError}
      error={error}
      resourceLabel="templates"
    />
  )
}

function StandardsPage() {
  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Standards catalog"
        description="Standard products, terminology releases, and templates from the provider catalog."
      />
      <Tabs defaultValue="products">
        <TabsList>
          <TabsTrigger value="products">Products</TabsTrigger>
          <TabsTrigger value="releases">Terminology releases</TabsTrigger>
          <TabsTrigger value="templates">Templates</TabsTrigger>
        </TabsList>
        <TabsContent value="products">
          <ProductsTab />
        </TabsContent>
        <TabsContent value="releases">
          <ReleasesTab />
        </TabsContent>
        <TabsContent value="templates">
          <TemplatesTab />
        </TabsContent>
      </Tabs>
    </div>
  )
}
