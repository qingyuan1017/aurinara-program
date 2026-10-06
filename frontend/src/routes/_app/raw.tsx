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
  getListRawAggregatesQueryKey,
  useCreateRawAggregate,
  useListRawAggregates,
} from '@/api/generated/raw/raw'
import type { AggregateCreate, AggregateResponse } from '@/api/generated/model'
import { jsonRequest } from '@/lib/requests'

export const Route = createFileRoute('/_app/raw')({
  component: RawPage,
})

const createFields: FieldDescriptor<AggregateCreate>[] = [
  { name: 'code', label: 'Code', control: 'text', required: true },
  { name: 'name', label: 'Name', control: 'text', required: true },
  { name: 'document_type', label: 'Document type', control: 'text' },
]

const columns: ResourceColumn<AggregateResponse>[] = [
  { key: 'code', header: 'Code' },
  { key: 'name', header: 'Name' },
  {
    key: 'document_type',
    header: 'Document type',
    cell: (row) => row.document_type ?? '—',
  },
  {
    key: 'status',
    header: 'Status',
    cell: (row) => <StatusBadge status={row.status} />,
  },
  { key: 'revision', header: 'Revision' },
]

function RawPage() {
  const qc = useQueryClient()
  const { currentStudyId, isLoading: studiesLoading } = useCurrentStudy()
  const { data, isLoading, isError, error } = useListRawAggregates(
    currentStudyId ?? '',
    undefined,
    { query: { enabled: !!currentStudyId } },
  )

  const [createOpen, setCreateOpen] = React.useState(false)

  const create = useCreateRawAggregate({
    mutation: {
      onSuccess: () =>
        qc.invalidateQueries({
          queryKey: getListRawAggregatesQueryKey(currentStudyId ?? undefined),
        }),
    },
    request: jsonRequest(),
  })

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Raw datasets"
        description={
          <>
            Raw aggregates from{' '}
            <code>GET /api/v1/studies/{'{study_id}'}/raw</code>.
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
        resourceLabel="raw datasets"
        emptyState={
          !studiesLoading && !currentStudyId ? (
            <EmptyState
              title="No study selected"
              description="Create a study first to view its raw datasets."
            />
          ) : undefined
        }
      />

      <ResourceFormDialog<AggregateCreate>
        open={createOpen}
        onOpenChange={setCreateOpen}
        title="New raw dataset"
        description="Create a minimal raw aggregate shell."
        fields={createFields}
        initialValues={{}}
        submitLabel="Create dataset"
        successMessage="Raw dataset created."
        isSubmitting={create.isPending}
        submitError={create.error}
        onSubmit={(data) =>
          create.mutateAsync({ studyId: currentStudyId!, data })
        }
      />
    </div>
  )
}
