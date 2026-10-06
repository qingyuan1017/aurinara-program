import { createFileRoute, Link, useNavigate } from '@tanstack/react-router'
import { PageHeader } from '@/components/layout/page-header'
import { DetailHeader } from '@/components/data/detail-header'
import { ResourceTable } from '@/components/data/resource-table'
import type { ResourceColumn } from '@/components/data/resource-table'
import { ErrorState } from '@/components/data/states'
import { StatusBadge } from '@/components/data/status-badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { formatDate } from '@/lib/utils'
import {
  useGetStandard,
  useListStandardVersions,
} from '@/api/generated/provider-catalogs/provider-catalogs'
import type { StandardVersionResponse } from '@/api/generated/model'

export const Route = createFileRoute('/_app/standards/products/$standardId')({
  component: StandardProductPage,
})

const versionColumns: ResourceColumn<StandardVersionResponse>[] = [
  { key: 'version', header: 'Version' },
  {
    key: 'lifecycle',
    header: 'Lifecycle',
    cell: (row) => <StatusBadge status={row.lifecycle} />,
  },
  { key: 'content_schema_version', header: 'Content schema' },
  {
    key: 'publication_date',
    header: 'Publication date',
    cell: (row) => formatDate(row.publication_date),
  },
  {
    key: 'created_at',
    header: 'Created',
    cell: (row) => formatDate(row.created_at),
  },
]

function StandardProductPage() {
  const { standardId } = Route.useParams()
  const navigate = useNavigate()

  const {
    data: product,
    isLoading,
    isError,
    error,
  } = useGetStandard(standardId)

  const versions = useListStandardVersions(standardId)

  return (
    <div className="flex flex-col gap-6">
      <Button asChild variant="ghost" className="w-fit">
        <Link to="/standards">Back to standards</Link>
      </Button>

      <PageHeader
        title={product ? `${product.code} — ${product.name}` : 'Standard product'}
      />

      {isError ? (
        <ErrorState error={error} resourceLabel="standard product" />
      ) : isLoading ? (
        <div className="grid grid-cols-2 gap-x-6 gap-y-3 md:grid-cols-3">
          {Array.from({ length: 6 }).map((_, index) => (
            <Skeleton key={index} className="h-10 w-full" />
          ))}
        </div>
      ) : product ? (
        <DetailHeader
          fields={[
            { label: 'Code', value: product.code },
            { label: 'Name', value: product.name },
            { label: 'Provider', value: product.provider },
            { label: 'Family', value: product.family },
            { label: 'Product type', value: product.product_type },
            { label: 'Scope', value: product.scope },
          ]}
        />
      ) : null}

      <ResourceTable
        columns={versionColumns}
        rows={versions.data ?? []}
        getRowId={(row) => row.id}
        isLoading={versions.isLoading}
        isError={versions.isError}
        error={versions.error}
        resourceLabel="standard versions"
        onRowClick={(row) =>
          navigate({
            to: '/standards/versions/$versionId',
            params: { versionId: row.id },
          })
        }
      />
    </div>
  )
}
