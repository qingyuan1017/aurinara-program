import { createFileRoute } from '@tanstack/react-router'
import { formatDate } from '@/lib/utils'
import { PageHeader } from '@/components/layout/page-header'
import { ResourceTable } from '@/components/data/resource-table'
import type { ResourceColumn } from '@/components/data/resource-table'
import { EmptyState } from '@/components/data/states'
import { StatusBadge } from '@/components/data/status-badge'
import { useCurrentStudy } from '@/components/study-provider'
import { useListDocuments } from '@/api/generated/documents/documents'
import type { DocumentResponse } from '@/api/generated/model'

export const Route = createFileRoute('/_app/documents')({
  component: DocumentsPage,
})

const columns: ResourceColumn<DocumentResponse>[] = [
  { key: 'document_code', header: 'Code' },
  { key: 'name', header: 'Name' },
  { key: 'document_type', header: 'Type' },
  {
    key: 'status',
    header: 'Status',
    cell: (row) => <StatusBadge status={row.status} />,
  },
  { key: 'revision', header: 'Revision' },
  {
    key: 'updated_at',
    header: 'Updated',
    cell: (row) => formatDate(row.updated_at),
  },
]

function DocumentsPage() {
  const { currentStudyId, isLoading: studiesLoading } = useCurrentStudy()
  const { data, isLoading, isError, error } = useListDocuments(
    currentStudyId ?? '',
    { query: { enabled: !!currentStudyId } },
  )

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Documents"
        description={
          <>
            Documents from{' '}
            <code>GET /api/v1/studies/{'{study_id}'}/documents</code>.
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
        resourceLabel="documents"
        emptyState={
          !studiesLoading && !currentStudyId ? (
            <EmptyState
              title="No study selected"
              description="Create a study first to view its documents."
            />
          ) : undefined
        }
      />
    </div>
  )
}
