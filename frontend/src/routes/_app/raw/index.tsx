import * as React from 'react'
import type { AxiosError } from 'axios'
import { createFileRoute, useNavigate } from '@tanstack/react-router'
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
import { useCursorList } from '@/hooks/use-cursor-list'
import {
  getListRawAggregatesQueryKey,
  useCreateRawAggregate,
  useListRawAggregates,
} from '@/api/generated/raw/raw'
import type {
  AggregateCollection,
  AggregateCreate,
  AggregateResponse,
} from '@/api/generated/model'
import { jsonRequest } from '@/lib/requests'

export const Route = createFileRoute('/_app/raw/')({
  component: RawListPage,
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

function RawListPage() {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const { currentStudyId, isLoading: studiesLoading } = useCurrentStudy()

  // Cursor-paginated list of the study's Raw workbenches (Requirement 2.1).
  // Study-scope gating: no study -> no request, EmptyState below (R2.2).
  const { items, isLoading, isFetching, isError, error, hasMore, loadMore } =
    useCursorList<
      AggregateResponse,
      AggregateCollection,
      Parameters<typeof useListRawAggregates>[2],
      AxiosError
    >({
      useListHook: useListRawAggregates,
      studyId: currentStudyId ?? '',
      enabled: !!currentStudyId,
    })

  const [createOpen, setCreateOpen] = React.useState(false)

  // On a 201 the mutation resolves; invalidating the list key refreshes it so
  // the new workbench appears (Requirement 2.3). A problem+json rejects the
  // mutateAsync promise, so ResourceFormDialog surfaces title/detail, retains
  // the entered values, and the list is NOT refreshed (Requirement 2.4).
  const create = useCreateRawAggregate({
    mutation: {
      onSuccess: () =>
        qc.invalidateQueries({
          queryKey: getListRawAggregatesQueryKey(currentStudyId ?? undefined),
        }),
    },
    request: jsonRequest(),
  })

  const noStudy = !studiesLoading && !currentStudyId

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Raw workbenches"
        description={
          <>
            Raw workbenches from{' '}
            <code>GET /api/v1/studies/{'{study_id}'}/raw</code>.
          </>
        }
        actions={
          <Button
            size="sm"
            disabled={!currentStudyId}
            onClick={() => setCreateOpen(true)}
          >
            <Plus /> New workbench
          </Button>
        }
      />
      <ResourceTable
        columns={columns}
        rows={items}
        getRowId={(row) => row.id}
        isLoading={isLoading || studiesLoading}
        isError={isError}
        error={error}
        resourceLabel="raw workbenches"
        onRowClick={(row) =>
          navigate({ to: '/raw/$rawId', params: { rawId: row.id } })
        }
        emptyState={
          noStudy ? (
            <EmptyState
              title="No study selected"
              description="Create a study first to view its raw workbenches."
            />
          ) : undefined
        }
      />

      {hasMore && (
        <div className="flex justify-center">
          <Button
            size="sm"
            variant="outline"
            disabled={isFetching}
            onClick={loadMore}
          >
            {isFetching ? 'Loading…' : 'Load more'}
          </Button>
        </div>
      )}

      <ResourceFormDialog<AggregateCreate>
        open={createOpen}
        onOpenChange={setCreateOpen}
        title="New raw workbench"
        description="Create a minimal raw aggregate shell."
        fields={createFields}
        initialValues={{}}
        submitLabel="Create workbench"
        successMessage="Raw workbench created."
        isSubmitting={create.isPending}
        submitError={create.error}
        onSubmit={(data) =>
          create.mutateAsync({ studyId: currentStudyId!, data })
        }
      />
    </div>
  )
}
