import * as React from 'react'
import { createFileRoute } from '@tanstack/react-router'
import { useQueryClient } from '@tanstack/react-query'
import { MessageSquarePlus, Pencil, Plus } from 'lucide-react'
import { formatDate } from '@/lib/utils'
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
  getGetReviewItemQueryKey,
  getListCommentsQueryKey,
  getListReviewItemsQueryKey,
  useCreateComment,
  useCreateReviewItem,
  useListReviewItems,
  usePatchReviewItem,
} from '@/api/generated/review/review'
import type {
  CommentCreate,
  ReviewItemCreate,
  ReviewItemPatch,
  ReviewItemResponse,
} from '@/api/generated/model'
import { ifMatchRequest, jsonRequest } from '@/lib/requests'

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

const createFields: FieldDescriptor<ReviewItemCreate>[] = [
  { name: 'target_module', label: 'Target module', control: 'text', required: true },
  {
    name: 'target_entity_type',
    label: 'Target entity type',
    control: 'text',
    required: true,
  },
  {
    name: 'target_entity_id',
    label: 'Target entity id',
    control: 'text',
    required: true,
  },
  { name: 'field_path', label: 'Field path', control: 'text' },
  {
    name: 'question',
    label: 'Question',
    control: 'textarea',
    required: true,
    maxLength: 4000,
  },
  { name: 'assignee', label: 'Assignee', control: 'text' },
  { name: 'priority', label: 'Priority', control: 'text' },
]

const editFields: FieldDescriptor<ReviewItemPatch>[] = [
  { name: 'assignee', label: 'Assignee', control: 'text' },
  { name: 'priority', label: 'Priority', control: 'text' },
  { name: 'status', label: 'Status', control: 'text' },
  { name: 'disposition', label: 'Disposition', control: 'text' },
  { name: 'resolution', label: 'Resolution', control: 'textarea' },
]

const commentFields: FieldDescriptor<CommentCreate>[] = [
  {
    name: 'body',
    label: 'Comment',
    control: 'textarea',
    required: true,
    maxLength: 8000,
  },
]

function ReviewPage() {
  const qc = useQueryClient()
  const { currentStudyId, isLoading: studiesLoading } = useCurrentStudy()
  const { data, isLoading, isError, error } = useListReviewItems(
    currentStudyId ?? '',
    { query: { enabled: !!currentStudyId } },
  )

  const [createOpen, setCreateOpen] = React.useState(false)
  const [editing, setEditing] = React.useState<ReviewItemResponse | null>(null)
  const [commenting, setCommenting] =
    React.useState<ReviewItemResponse | null>(null)

  const listKey = getListReviewItemsQueryKey(currentStudyId ?? undefined)

  const create = useCreateReviewItem({
    mutation: { onSuccess: () => qc.invalidateQueries({ queryKey: listKey }) },
    request: jsonRequest(),
  })

  const patch = usePatchReviewItem({
    mutation: {
      onSuccess: () => {
        qc.invalidateQueries({ queryKey: listKey })
        if (editing)
          qc.invalidateQueries({
            queryKey: getGetReviewItemQueryKey(editing.id),
          })
      },
    },
    request: editing ? ifMatchRequest(editing.revision) : undefined,
  })

  const comment = useCreateComment({
    mutation: {
      onSuccess: () => {
        if (commenting)
          qc.invalidateQueries({
            queryKey: getListCommentsQueryKey(commenting.id),
          })
      },
    },
    request: jsonRequest(),
  })

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
        actions={
          <Button
            size="sm"
            disabled={!currentStudyId}
            onClick={() => setCreateOpen(true)}
          >
            <Plus /> New review item
          </Button>
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
        rowActions={(row) => (
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="outline" onClick={() => setEditing(row)}>
              <Pencil /> Edit
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setCommenting(row)}
            >
              <MessageSquarePlus /> Comment
            </Button>
          </div>
        )}
      />

      <ResourceFormDialog<ReviewItemCreate>
        open={createOpen}
        onOpenChange={setCreateOpen}
        title="New review item"
        description="Raise a review item against a study artifact."
        fields={createFields}
        initialValues={{}}
        submitLabel="Create item"
        successMessage="Review item created."
        isSubmitting={create.isPending}
        submitError={create.error}
        onSubmit={(data) =>
          create.mutateAsync({ studyId: currentStudyId!, data })
        }
      />

      <ResourceFormDialog<ReviewItemPatch>
        open={!!editing}
        onOpenChange={(open) => {
          if (!open) setEditing(null)
        }}
        title="Edit review item"
        description="Update assignment and disposition."
        fields={editFields}
        initialValues={
          editing
            ? {
                assignee: editing.assignee,
                priority: editing.priority,
                status: editing.status,
                disposition: editing.disposition,
                resolution: editing.resolution,
              }
            : {}
        }
        submitLabel="Save changes"
        successMessage="Review item updated."
        isSubmitting={patch.isPending}
        submitError={patch.error}
        onSubmit={(data) =>
          patch.mutateAsync({ itemId: editing!.id, data })
        }
      />

      <ResourceFormDialog<CommentCreate>
        open={!!commenting}
        onOpenChange={(open) => {
          if (!open) setCommenting(null)
        }}
        title="Add comment"
        description="Add a comment to this review item."
        fields={commentFields}
        initialValues={{}}
        submitLabel="Add comment"
        successMessage="Comment added."
        isSubmitting={comment.isPending}
        submitError={comment.error}
        onSubmit={(data) =>
          comment.mutateAsync({ itemId: commenting!.id, data })
        }
      />
    </div>
  )
}
