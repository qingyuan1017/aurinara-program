import * as React from 'react'
import { createFileRoute } from '@tanstack/react-router'
import { useQueryClient } from '@tanstack/react-query'
import { Pencil, Trash2 } from 'lucide-react'
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
import { ConfirmDialog } from '@/components/forms/confirm-dialog'
import { useCurrentStudy } from '@/components/study-provider'
import {
  getGetReferenceQueryKey,
  getListReferencesQueryKey,
  useListReferences,
  usePatchReference,
  useRetireReference,
} from '@/api/generated/reference/reference'
import type { ReferencePatch, ReferenceResponse } from '@/api/generated/model'
import { ifMatchRequest } from '@/lib/requests'

export const Route = createFileRoute('/_app/reference')({
  component: ReferencePage,
})

const columns: ResourceColumn<ReferenceResponse>[] = [
  { key: 'reference_type', header: 'Type' },
  { key: 'natural_key', header: 'Natural key' },
  { key: 'display_name', header: 'Display name' },
  {
    key: 'status',
    header: 'Status',
    cell: (row) => <StatusBadge status={row.status} />,
  },
  { key: 'revision', header: 'Revision' },
]

const editFields: FieldDescriptor<ReferencePatch>[] = [
  { name: 'display_name', label: 'Display name', control: 'text' },
]

function ReferencePage() {
  const qc = useQueryClient()
  const { currentStudyId, isLoading: studiesLoading } = useCurrentStudy()
  const { data, isLoading, isError, error } = useListReferences(
    currentStudyId ?? '',
    { query: { enabled: !!currentStudyId } },
  )

  const [editing, setEditing] = React.useState<ReferenceResponse | null>(null)
  const [retiring, setRetiring] = React.useState<ReferenceResponse | null>(null)

  const listKey = getListReferencesQueryKey(currentStudyId ?? undefined)

  const patch = usePatchReference({
    mutation: {
      onSuccess: () => {
        qc.invalidateQueries({ queryKey: listKey })
        if (editing)
          qc.invalidateQueries({
            queryKey: getGetReferenceQueryKey(editing.id),
          })
      },
    },
    request: editing ? ifMatchRequest(editing.revision) : undefined,
  })

  const retire = useRetireReference({
    mutation: {
      onSuccess: () => qc.invalidateQueries({ queryKey: listKey }),
    },
    request: retiring ? ifMatchRequest(retiring.revision) : undefined,
  })

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Reference"
        description={
          <>
            Reference data from{' '}
            <code>GET /api/v1/studies/{'{study_id}'}/reference</code>.
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
        resourceLabel="reference data"
        emptyState={
          !studiesLoading && !currentStudyId ? (
            <EmptyState
              title="No study selected"
              description="Create a study first to view its reference data."
            />
          ) : undefined
        }
        rowActions={(row) => (
          <div className="flex justify-end gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={() => setEditing(row)}
            >
              <Pencil /> Edit
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setRetiring(row)}
            >
              <Trash2 /> Retire
            </Button>
          </div>
        )}
      />

      <ResourceFormDialog<ReferencePatch>
        open={!!editing}
        onOpenChange={(open) => {
          if (!open) setEditing(null)
        }}
        title="Edit reference"
        description="Update the display name. Field values are left unchanged."
        fields={editFields}
        initialValues={
          editing ? { display_name: editing.display_name } : {}
        }
        submitLabel="Save changes"
        successMessage="Reference updated."
        isSubmitting={patch.isPending}
        submitError={patch.error}
        onSubmit={(data) =>
          patch.mutateAsync({ referenceId: editing!.id, data })
        }
      />

      <ConfirmDialog
        open={!!retiring}
        onOpenChange={(open) => {
          if (!open) setRetiring(null)
        }}
        title="Retire reference"
        description={
          retiring
            ? `Retire "${retiring.display_name}"? This marks the reference as retired.`
            : undefined
        }
        confirmLabel="Retire"
        destructive
        isPending={retire.isPending}
        error={retire.error}
        onConfirm={() =>
          retire.mutateAsync({ referenceId: retiring!.id })
        }
      />
    </div>
  )
}
