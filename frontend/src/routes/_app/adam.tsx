import * as React from 'react'
import { createFileRoute } from '@tanstack/react-router'
import { useQueryClient } from '@tanstack/react-query'
import { Plus } from 'lucide-react'
import { PageHeader } from '@/components/layout/page-header'
import { ResourceTable } from '@/components/data/resource-table'
import type { ResourceColumn } from '@/components/data/resource-table'
import { EmptyState } from '@/components/data/states'
import { StatusBadge } from '@/components/data/status-badge'
import { Button } from '@/components/ui/button'
import {
  ResourceFormDialog,
  type FieldDescriptor,
} from '@/components/forms/resource-form-dialog'
import { useCurrentStudy } from '@/components/study-provider'
import {
  getListAdamAggregatesQueryKey,
  useCreateAdamAggregate,
  useListAdamAggregates,
} from '@/api/generated/adam/adam'
import type { AggregateCreate, AggregateResponse } from '@/api/generated/model'
import { jsonRequest } from '@/lib/requests'

export const Route = createFileRoute('/_app/adam')({
  component: AdamPage,
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

const createFields: FieldDescriptor<AggregateCreate>[] = [
  { name: 'code', label: 'Code', control: 'text', required: true },
  { name: 'name', label: 'Name', control: 'text', required: true },
  { name: 'document_type', label: 'Document type', control: 'text' },
]

function AdamPage() {
  const qc = useQueryClient()
  const { currentStudyId, isLoading: studiesLoading } = useCurrentStudy()
  const { data, isLoading, isError, error } = useListAdamAggregates(
    currentStudyId ?? '',
    undefined,
    { query: { enabled: !!currentStudyId } },
  )

  const [createOpen, setCreateOpen] = React.useState(false)

  const create = useCreateAdamAggregate({
    mutation: {
      onSuccess: () =>
        qc.invalidateQueries({
          queryKey: getListAdamAggregatesQueryKey(currentStudyId ?? undefined),
        }),
    },
    request: jsonRequest(),
  })

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="ADaM datasets"
        description={
          <>
            ADaM aggregates from{' '}
            <code>GET /api/v1/studies/{'{study_id}'}/adams</code>.
          </>
        }
        actions={
          <Button
            size="sm"
            disabled={!currentStudyId}
            onClick={() => setCreateOpen(true)}
          >
            <Plus /> New dataset
          </Button>
        }
      />
      <ResourceTable
        columns={columns}
        rows={data?.items ?? []}
        getRowId={(row) => row.id}
        isLoading={isLoading || studiesLoading}
        isError={isError}
        error={error}
        resourceLabel="ADaM datasets"
        emptyState={
          !studiesLoading && !currentStudyId ? (
            <EmptyState
              title="No study selected"
              description="Create a study first to view its ADaM datasets."
            />
          ) : undefined
        }
      />

      <ResourceFormDialog<AggregateCreate>
        open={createOpen}
        onOpenChange={setCreateOpen}
        title="New ADaM dataset"
        description="Create a minimal ADaM aggregate shell."
        fields={createFields}
        initialValues={{}}
        submitLabel="Create dataset"
        successMessage="ADaM dataset created."
        isSubmitting={create.isPending}
        submitError={create.error}
        onSubmit={(data) =>
          create.mutateAsync({ studyId: currentStudyId!, data })
        }
      />
    </div>
  )
}
