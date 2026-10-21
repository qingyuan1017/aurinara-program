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
import { useCurrentStudy } from '@/components/study-context'
import {
  getListSdtmAggregatesQueryKey,
  useCreateSdtmAggregate,
  useListSdtmAggregates,
} from '@/api/generated/sdtm/sdtm'
import type {
  AggregateCollection,
  AggregateCreate,
  AggregateResponse,
} from '@/api/generated/model'
import { jsonRequest } from '@/lib/requests'
import { useCursorList } from '@/hooks/use-cursor-list'

export const Route = createFileRoute('/_app/sdtm/')({
  component: SdtmListPage,
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

function SdtmListPage() {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const { currentStudyId, isLoading: studiesLoading } = useCurrentStudy()

  // Cursor-paginated workbench list. The helper gates the request on study
  // scope (`enabled`) and issues NO request when no study is selected
  // (Requirements 9.1, 9.4).
  const { items, isLoading, isFetching, isError, error, hasMore, loadMore } =
    useCursorList<
      AggregateResponse,
      AggregateCollection,
      Parameters<typeof useListSdtmAggregates>[2],
      AxiosError
    >({
      useListHook: useListSdtmAggregates,
      studyId: currentStudyId ?? '',
      enabled: !!currentStudyId,
    })

  const [createOpen, setCreateOpen] = React.useState(false)

  // Create via the typed hook; refresh the list on success (Requirement 9.2).
  // problem+json surfacing (title/detail) and form-input retention are handled
  // by ResourceFormDialog, which only closes the dialog on a resolved submit.
  const create = useCreateSdtmAggregate({
    mutation: {
      onSuccess: () =>
        qc.invalidateQueries({
          queryKey: getListSdtmAggregatesQueryKey(currentStudyId ?? undefined),
        }),
    },
    request: jsonRequest(),
  })

  const noStudy = !studiesLoading && !currentStudyId

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="SDTM workbenches"
        description={
          <>
            SDTM aggregates from{' '}
            <code>GET /api/v1/studies/{'{study_id}'}/sdtms</code>.
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
        error={error as never}
        resourceLabel="SDTM workbenches"
        onRowClick={(row) =>
          navigate({
            to: '/sdtm/$sdtmId',
            params: { sdtmId: row.id },
            search: { tab: 'input-selection' },
          })
        }
        emptyState={
          noStudy ? (
            <EmptyState
              title="No study selected"
              description="Create a study first to view its SDTM workbenches."
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
        title="New SDTM workbench"
        description="Create a minimal SDTM aggregate shell."
        fields={createFields}
        initialValues={{}}
        submitLabel="Create workbench"
        successMessage="SDTM workbench created."
        isSubmitting={create.isPending}
        submitError={create.error}
        onSubmit={(data) =>
          create.mutateAsync({ studyId: currentStudyId!, data })
        }
      />
    </div>
  )
}
