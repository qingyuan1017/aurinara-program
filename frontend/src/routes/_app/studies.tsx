import * as React from 'react'
import { createFileRoute } from '@tanstack/react-router'
import { useQueryClient } from '@tanstack/react-query'
import { Pencil, Plus } from 'lucide-react'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { PageHeader } from '@/components/layout/page-header'
import { StatusBadge } from '@/components/data/status-badge'
import {
  ResourceFormDialog,
  type FieldDescriptor,
} from '@/components/forms/resource-form-dialog'
import {
  getGetStudyQueryKey,
  getListStudiesQueryKey,
  useCreateStudy,
  useListStudies,
  usePatchStudy,
} from '@/api/generated/studies/studies'
import type {
  StudyCreate,
  StudyPatch,
  StudyResponse,
} from '@/api/generated/model'
import { ifMatchRequest, jsonRequest } from '@/lib/requests'

export const Route = createFileRoute('/_app/studies')({
  component: StudiesPage,
})

const createFields: FieldDescriptor<StudyCreate>[] = [
  {
    name: 'code',
    label: 'Code',
    control: 'text',
    required: true,
    placeholder: 'STUDY-001',
    pattern: {
      re: /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/,
      message:
        'Code must start with a letter or number and use only letters, numbers, ., _ or - (max 64).',
    },
  },
  {
    name: 'name',
    label: 'Name',
    control: 'text',
    required: true,
    maxLength: 255,
  },
]

const editFields: FieldDescriptor<StudyPatch>[] = [
  { name: 'name', label: 'Name', control: 'text', maxLength: 255 },
  {
    name: 'status',
    label: 'Status',
    control: 'select',
    options: [
      { label: 'Active', value: 'active' },
      { label: 'Closed', value: 'closed' },
    ],
  },
]

function StudiesPage() {
  const qc = useQueryClient()
  const { data, isLoading, isError, error } = useListStudies()
  const [createOpen, setCreateOpen] = React.useState(false)
  const [editing, setEditing] = React.useState<StudyResponse | null>(null)

  const create = useCreateStudy({
    mutation: {
      onSuccess: () =>
        qc.invalidateQueries({ queryKey: getListStudiesQueryKey() }),
    },
    request: jsonRequest(),
  })

  const patch = usePatchStudy({
    mutation: {
      onSuccess: () => {
        qc.invalidateQueries({ queryKey: getListStudiesQueryKey() })
        if (editing)
          qc.invalidateQueries({ queryKey: getGetStudyQueryKey(editing.id) })
      },
    },
    request: editing ? ifMatchRequest(editing.revision) : undefined,
  })

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Studies"
        description={
          <>
            Studies returned by <code>GET /api/v1/studies</code>.
          </>
        }
        actions={
          <Button size="sm" onClick={() => setCreateOpen(true)}>
            <Plus /> New study
          </Button>
        }
      />

      {isLoading && (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-32 w-full" />
          ))}
        </div>
      )}

      {isError && (
        <Card>
          <CardHeader>
            <CardTitle className="text-destructive">
              Could not load studies
            </CardTitle>
            <CardDescription>
              {error?.response?.status === 401
                ? 'Not authenticated. Set a bearer token (see auth.ts) to call the API.'
                : (error?.message ?? 'Request failed.')}
            </CardDescription>
          </CardHeader>
        </Card>
      )}

      {!isLoading && !isError && data && data.items.length === 0 && (
        <Card>
          <CardHeader>
            <CardTitle>No studies yet</CardTitle>
            <CardDescription>
              Create a study to get started.
            </CardDescription>
          </CardHeader>
        </Card>
      )}

      {!isLoading && !isError && data && data.items.length > 0 && (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {data.items.map((study) => (
            <Card key={study.id}>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle className="text-base">{study.name}</CardTitle>
                  <StatusBadge status={study.status} />
                </div>
                <CardDescription>Code: {study.code}</CardDescription>
              </CardHeader>
              <CardContent className="text-muted-foreground flex items-end justify-between text-xs">
                <div>
                  <div>Revision {study.revision}</div>
                  <div>Created by {study.created_by}</div>
                </div>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setEditing(study)}
                >
                  <Pencil /> Edit
                </Button>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      <ResourceFormDialog<StudyCreate>
        open={createOpen}
        onOpenChange={setCreateOpen}
        title="New study"
        description="Create a study and become its owner."
        fields={createFields}
        initialValues={{}}
        submitLabel="Create study"
        successMessage="Study created."
        isSubmitting={create.isPending}
        submitError={create.error}
        onSubmit={(data) => create.mutateAsync({ data })}
      />

      <ResourceFormDialog<StudyPatch>
        open={!!editing}
        onOpenChange={(open) => {
          if (!open) setEditing(null)
        }}
        title="Edit study"
        description="Update study metadata."
        fields={editFields}
        initialValues={
          editing
            ? {
                name: editing.name,
                status: editing.status as StudyPatch['status'],
              }
            : {}
        }
        submitLabel="Save changes"
        successMessage="Study updated."
        isSubmitting={patch.isPending}
        submitError={patch.error}
        onSubmit={(data) =>
          patch.mutateAsync({ studyId: editing!.id, data })
        }
      />
    </div>
  )
}
