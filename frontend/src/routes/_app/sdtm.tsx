import { createFileRoute } from '@tanstack/react-router'
import { PageHeader } from '@/components/layout/page-header'
import { ResourceTable } from '@/components/data/resource-table'
import type { ResourceColumn } from '@/components/data/resource-table'
import { EmptyState } from '@/components/data/states'
import { StatusBadge } from '@/components/data/status-badge'
import { useCurrentStudy } from '@/components/study-provider'
import { useListSdtmAggregates } from '@/api/generated/sdtm/sdtm'
import type { AggregateResponse } from '@/api/generated/model'

export const Route = createFileRoute('/_app/sdtm')({
  component: SdtmPage,
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

function SdtmPage() {
  const { currentStudyId, isLoading: studiesLoading } = useCurrentStudy()
  const { data, isLoading, isError, error } = useListSdtmAggregates(
    currentStudyId ?? '',
    undefined,
    { query: { enabled: !!currentStudyId } },
  )

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="SDTM datasets"
        description={
          <>
            SDTM aggregates from{' '}
            <code>GET /api/v1/studies/{'{study_id}'}/sdtms</code>.
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
        resourceLabel="SDTM datasets"
        emptyState={
          !studiesLoading && !currentStudyId ? (
            <EmptyState
              title="No study selected"
              description="Create a study first to view its SDTM datasets."
            />
          ) : undefined
        }
      />
    </div>
  )
}
