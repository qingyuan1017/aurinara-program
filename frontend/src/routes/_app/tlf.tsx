import { createFileRoute } from '@tanstack/react-router'
import { PageHeader } from '@/components/layout/page-header'
import { ResourceTable } from '@/components/data/resource-table'
import type { ResourceColumn } from '@/components/data/resource-table'
import { EmptyState } from '@/components/data/states'
import { StatusBadge } from '@/components/data/status-badge'
import { useCurrentStudy } from '@/components/study-provider'
import { useListTlfAggregates } from '@/api/generated/tlf/tlf'
import type { AggregateResponse } from '@/api/generated/model'

export const Route = createFileRoute('/_app/tlf')({
  component: TlfPage,
})

const columns: ResourceColumn<AggregateResponse>[] = [
  { key: 'code', header: 'Code' },
  { key: 'name', header: 'Name' },
  {
    key: 'status',
    header: 'Status',
    cell: (row) => <StatusBadge status={row.status} />,
  },
  { key: 'revision', header: 'Revision' },
]

function TlfPage() {
  const { currentStudyId, isLoading: studiesLoading } = useCurrentStudy()
  const { data, isLoading, isError, error } = useListTlfAggregates(
    currentStudyId ?? '',
    undefined,
    { query: { enabled: !!currentStudyId } },
  )

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Tables, Listings & Figures"
        description={
          <>
            TLF aggregates from{' '}
            <code>GET /api/v1/studies/{'{study_id}'}/tlfs</code>.
          </>
        }
      />
      <ResourceTable
        columns={columns}
        rows={data?.items ?? []}
        getRowId={(row) => row.id}
        isLoading={isLoading || studiesLoading}
        isError={isError}
        error={error}
        resourceLabel="TLF datasets"
        emptyState={
          !studiesLoading && !currentStudyId ? (
            <EmptyState
              title="No study selected"
              description="Create a study first to view its TLF datasets."
            />
          ) : undefined
        }
      />
    </div>
  )
}
