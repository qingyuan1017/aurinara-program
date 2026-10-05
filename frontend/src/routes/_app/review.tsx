import { createFileRoute } from '@tanstack/react-router'
import { formatDate } from '@/lib/utils'
import { PageHeader } from '@/components/layout/page-header'
import { ResourceTable } from '@/components/data/resource-table'
import type { ResourceColumn } from '@/components/data/resource-table'
import { EmptyState } from '@/components/data/states'
import { StatusBadge } from '@/components/data/status-badge'
import { useCurrentStudy } from '@/components/study-provider'
import { useListReviewItems } from '@/api/generated/review/review'
import type { ReviewItemResponse } from '@/api/generated/model'

export const Route = createFileRoute('/_app/review')({
  component: ReviewPage,
})

const columns: ResourceColumn<ReviewItemResponse>[] = [
  { key: 'target_module', header: 'Module' },
  { key: 'target_entity_type', header: 'Entity type' },
  {
    key: 'question',
    header: 'Question',
    className: 'max-w-sm truncate',
  },
  {
    key: 'priority',
    header: 'Priority',
    cell: (row) => <StatusBadge status={row.priority} />,
  },
  {
    key: 'status',
    header: 'Status',
    cell: (row) => <StatusBadge status={row.status} />,
  },
  {
    key: 'updated_at',
    header: 'Updated',
    cell: (row) => formatDate(row.updated_at),
  },
]

function ReviewPage() {
  const { currentStudyId, isLoading: studiesLoading } = useCurrentStudy()
  const { data, isLoading, isError, error } = useListReviewItems(
    currentStudyId ?? '',
    { query: { enabled: !!currentStudyId } },
  )

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Review items"
        description={
          <>
            Review items from{' '}
            <code>GET /api/v1/studies/{'{study_id}'}/review-items</code>.
          </>
        }
      />
      <ResourceTable
        columns={columns}
        rows={data ?? []}
        getRowId={(row) => row.id}
        isLoading={isLoading || studiesLoading}
        isError={isError}
        error={error}
        resourceLabel="review items"
        emptyState={
          !studiesLoading && !currentStudyId ? (
            <EmptyState
              title="No study selected"
              description="Create a study first to view its review items."
            />
          ) : undefined
        }
      />
    </div>
  )
}
