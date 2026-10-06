import { createFileRoute, Link } from '@tanstack/react-router'
import { PageHeader } from '@/components/layout/page-header'
import { DetailHeader } from '@/components/data/detail-header'
import { ResourceTable } from '@/components/data/resource-table'
import type { ResourceColumn } from '@/components/data/resource-table'
import { ErrorState } from '@/components/data/states'
import { StatusBadge } from '@/components/data/status-badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { formatDate } from '@/lib/utils'
import {
  useGetStandardVersion,
  useListStandardAssets,
  useListStandardCompatibilities,
} from '@/api/generated/provider-catalogs/provider-catalogs'
import type {
  StandardAssetResponse,
  StandardCompatibilityResponse,
} from '@/api/generated/model'

export const Route = createFileRoute('/_app/standards/versions/$versionId')({
  component: StandardVersionPage,
})

const assetColumns: ResourceColumn<StandardAssetResponse>[] = [
  { key: 'role', header: 'Role' },
  { key: 'media_type', header: 'Media type' },
  { key: 'checksum', header: 'Checksum' },
  { key: 'title', header: 'Title', cell: (row) => row.title ?? '—' },
  {
    key: 'resource_type',
    header: 'Resource type',
    cell: (row) => row.resource_type ?? '—',
  },
  {
    key: 'required',
    header: 'Required',
    cell: (row) => (row.required ? 'Yes' : 'No'),
  },
  {
    key: 'canonical_href',
    header: 'Canonical href',
    cell: (row) =>
      row.canonical_href ? (
        <a
          href={row.canonical_href}
          target="_blank"
          rel="noreferrer"
          className="underline"
        >
          link
        </a>
      ) : (
        '—'
      ),
  },
]

const compatibilityColumns: ResourceColumn<StandardCompatibilityResponse>[] = [
  { key: 'relationship', header: 'Relationship' },
  { key: 'target_version_id', header: 'Target version id' },
  {
    key: 'required',
    header: 'Required',
    cell: (row) => (row.required ? 'Yes' : 'No'),
  },
]

function StandardVersionPage() {
  const { versionId } = Route.useParams()

  const {
    data: version,
    isLoading,
    isError,
    error,
  } = useGetStandardVersion(versionId)

  const assets = useListStandardAssets(versionId)
  const compatibilities = useListStandardCompatibilities(versionId)

  return (
    <div className="flex flex-col gap-6">
      {version ? (
        <Button asChild variant="ghost" className="w-fit">
          <Link
            to="/standards/products/$standardId"
            params={{ standardId: version.product_id }}
          >
            Back to product
          </Link>
        </Button>
      ) : (
        <Button asChild variant="ghost" className="w-fit">
          <Link to="/standards">Back to standards</Link>
        </Button>
      )}

      <PageHeader
        title={version ? `Version ${version.version}` : 'Standard version'}
      />

      {isError ? (
        <ErrorState error={error} resourceLabel="standard version" />
      ) : isLoading ? (
        <div className="grid grid-cols-2 gap-x-6 gap-y-3 md:grid-cols-3">
          {Array.from({ length: 8 }).map((_, index) => (
            <Skeleton key={index} className="h-10 w-full" />
          ))}
        </div>
      ) : version ? (
        <DetailHeader
          fields={[
            { label: 'Version', value: version.version },
            {
              label: 'Lifecycle',
              value: <StatusBadge status={version.lifecycle} />,
            },
            { label: 'Content schema', value: version.content_schema_version },
            { label: 'Checksum', value: version.checksum },
            {
              label: 'Publication date',
              value: formatDate(version.publication_date),
            },
            { label: 'Created', value: formatDate(version.created_at) },
            {
              label: 'Applicable modules',
              value: version.applicable_modules.join(', ') || '—',
            },
            { label: 'Purposes', value: version.purposes.join(', ') || '—' },
          ]}
        />
      ) : null}

      <Tabs defaultValue="assets">
        <TabsList>
          <TabsTrigger value="assets">Assets</TabsTrigger>
          <TabsTrigger value="compatibilities">Compatibilities</TabsTrigger>
        </TabsList>
        <TabsContent value="assets">
          <ResourceTable
            columns={assetColumns}
            rows={assets.data ?? []}
            getRowId={(row) => row.id}
            isLoading={assets.isLoading}
            isError={assets.isError}
            error={assets.error}
            resourceLabel="assets"
          />
        </TabsContent>
        <TabsContent value="compatibilities">
          <ResourceTable
            columns={compatibilityColumns}
            rows={compatibilities.data ?? []}
            getRowId={(row) => row.id}
            isLoading={compatibilities.isLoading}
            isError={compatibilities.isError}
            error={compatibilities.error}
            resourceLabel="compatibilities"
          />
        </TabsContent>
      </Tabs>
    </div>
  )
}
