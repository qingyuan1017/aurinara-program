import { createFileRoute } from '@tanstack/react-router'
import { formatDate } from '@/lib/utils'
import { PageHeader } from '@/components/layout/page-header'
import { ResourceTable } from '@/components/data/resource-table'
import type { ResourceColumn } from '@/components/data/resource-table'
import { EmptyState } from '@/components/data/states'
import { StatusBadge } from '@/components/data/status-badge'
import { useCurrentStudy } from '@/components/study-provider'
import { useListIntegrations } from '@/api/generated/integrations/integrations'
import type { IntegrationResponse } from '@/api/generated/model'

export const Route = createFileRoute('/_app/integrations')({
  component: IntegrationsPage,
})

const columns: ResourceColumn<IntegrationResponse>[] = [
  { key: 'integration_code', header: 'Code' },
  { key: 'display_name', header: 'Name' },
  { key: 'direction', header: 'Direction' },
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

function IntegrationsPage() {
  const { currentStudyId, isLoading: studiesLoading } = useCurrentStudy()
  const { data, isLoading, isError, error } = useListIntegrations(
    currentStudyId ?? '',
    { query: { enabled: !!currentStudyId } },
  )

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Integrations"
        description={
          <>
            Integrations from{' '}
            <code>GET /api/v1/studies/{'{study_id}'}/integrations</code>.
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
        resourceLabel="integrations"
        emptyState={
          !studiesLoading && !currentStudyId ? (
            <EmptyState
              title="No study selected"
              description="Create a study first to view its integrations."
            />
          ) : undefined
        }
      />
    </div>
  )
}
