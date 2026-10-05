import { createFileRoute } from '@tanstack/react-router'
import { formatBytes, formatDate } from '@/lib/utils'
import { PageHeader } from '@/components/layout/page-header'
import { ResourceTable } from '@/components/data/resource-table'
import type { ResourceColumn } from '@/components/data/resource-table'
import { EmptyState } from '@/components/data/states'
import { StatusBadge } from '@/components/data/status-badge'
import { useCurrentStudy } from '@/components/study-provider'
import { useListArtifacts } from '@/api/generated/artifacts/artifacts'
import type { ArtifactResponse } from '@/api/generated/model'

export const Route = createFileRoute('/_app/packaging')({
  component: PackagingPage,
})

const columns: ResourceColumn<ArtifactResponse>[] = [
  { key: 'module', header: 'Module' },
  { key: 'artifact_type', header: 'Type' },
  { key: 'filename', header: 'Filename' },
  { key: 'media_type', header: 'Media type' },
  {
    key: 'size',
    header: 'Size',
    className: 'text-right',
    cell: (row) => formatBytes(row.size),
  },
  {
    key: 'status',
    header: 'Status',
    cell: (row) => <StatusBadge status={row.status} />,
  },
  {
    key: 'created_at',
    header: 'Created',
    cell: (row) => formatDate(row.created_at),
  },
]

function PackagingPage() {
  const { currentStudyId, isLoading: studiesLoading } = useCurrentStudy()
  const { data, isLoading, isError, error } = useListArtifacts(
    currentStudyId ?? '',
    undefined,
    { query: { enabled: !!currentStudyId } },
  )

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Submission artifacts"
        description="Generated artifacts available for packaging. There is no submission-package list API yet, so this lists the study's artifacts."
      />
      <ResourceTable
        columns={columns}
        rows={data?.items ?? []}
        getRowId={(row) => row.id}
        isLoading={isLoading || studiesLoading}
        isError={isError}
        error={error}
        resourceLabel="artifacts"
        emptyState={
          !studiesLoading && !currentStudyId ? (
            <EmptyState
              title="No study selected"
              description="Create a study first to view its artifacts."
            />
          ) : undefined
        }
      />
    </div>
  )
}
