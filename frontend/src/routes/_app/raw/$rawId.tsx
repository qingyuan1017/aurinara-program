import * as React from 'react'
import type { AxiosError } from 'axios'
import { createFileRoute, Link } from '@tanstack/react-router'
import { useQueryClient } from '@tanstack/react-query'
import { Pencil } from 'lucide-react'
import { PageHeader } from '@/components/layout/page-header'
import { Button } from '@/components/ui/button'
import {
  ResourceFormDialog,
  type FieldDescriptor,
} from '@/components/forms/resource-form-dialog'
import {
  WorkbenchDetailShell,
  type WorkbenchTab,
} from '@/components/workbench/workbench-detail-shell'
import { DatasetsPanel } from '@/components/workbench/datasets-panel'
import { ArtifactsPanel } from '@/components/workbench/artifacts-panel'
import { DependenciesPanel } from '@/components/workbench/dependencies-panel'
import { ReconciliationPanel } from '@/components/workbench/reconciliation-panel'
import { RawValidationPanel } from '@/components/workbench/raw-validation-panel'
import { useGetRawAggregate, usePatchRaw } from '@/api/generated/raw/raw'
import type { AggregateResponse, PatchRawBody } from '@/api/generated/model'
import { ifMatchRequest } from '@/lib/requests'
import { invalidateRawAggregate } from '@/lib/invalidate'

export const Route = createFileRoute('/_app/raw/$rawId')({
  component: RawDetailPage,
})

/**
 * Editable workbench fields. `status` is the backend-maintained lifecycle
 * string; the create form only sets code/name, so the detail edit surfaces
 * name and status (Requirement 2.5).
 */
const editFields: FieldDescriptor<PatchRawBody>[] = [
  { name: 'name', label: 'Name', control: 'text', required: true },
  { name: 'status', label: 'Status', control: 'text' },
]

function RawDetailPage() {
  const { rawId } = Route.useParams()
  const qc = useQueryClient()

  // The shell gates presentation on the selected study; this query is the
  // single aggregate source. `useGetRawAggregate` is enabled whenever `rawId`
  // is set, which it always is on this dynamic route.
  const query = useGetRawAggregate(rawId)
  const aggregate = query.data

  const [editOpen, setEditOpen] = React.useState(false)

  // name/status edit (Requirement 2.5): PATCH /api/v1/raw/{raw_id} with the
  // current ETag. The `request` option rebinds to the latest revision on every
  // render, so after a 412/428 reload the retry carries the fresh token.
  const patch = usePatchRaw({
    mutation: {
      // Reload the aggregate detail and the study-scoped aggregate list (its
      // name/status column changed) through the shared per-aggregate helper.
      onSuccess: () => invalidateRawAggregate(qc, rawId, aggregate?.study_id),
    },
    request: aggregate ? ifMatchRequest(aggregate.revision) : undefined,
  })

  // 412 (concurrency) and 428 (missing precondition) both require reloading the
  // current revision before a retry (Requirements 2.6, 2.7). We refetch the
  // aggregate so the shell shows the new revision and the next submit uses the
  // fresh ETag; the stale in-flight edit is discarded by closing the dialog.
  async function handleEdit(body: PatchRawBody) {
    try {
      await patch.mutateAsync({ rawId, data: body })
    } catch (error) {
      const status = (error as AxiosError).response?.status
      if (status === 412 || status === 428) {
        // Discard the stale edit and reload the current revision before retry.
        setEditOpen(false)
        invalidateRawAggregate(qc, rawId, aggregate?.study_id)
      }
      // Re-throw so ResourceFormDialog surfaces the concurrency/precondition
      // message (stalenessAlert maps 412/428) and retains the entered values
      // when the dialog stays open.
      throw error
    }
  }

  const tabs: WorkbenchTab[] = [
    {
      value: 'datasets',
      label: 'Datasets',
      render: (ctx) => (
        <DatasetsPanel rawId={rawId} studyId={ctx.studyId} />
      ),
    },
    {
      value: 'dependencies',
      label: 'Dependencies',
      render: () => <DependenciesPanel rawId={rawId} />,
    },
    {
      value: 'validation',
      label: 'Validation',
      render: () => <RawValidationPanel rawId={rawId} />,
    },
    {
      value: 'reconciliation',
      label: 'Reconciliation',
      render: () => <ReconciliationPanel />,
    },
    {
      value: 'artifacts',
      label: 'Artifacts',
      render: (ctx) => <ArtifactsPanel rawId={rawId} studyId={ctx.studyId} />,
    },
  ]

  return (
    <div className="flex flex-col gap-6">
      <Button asChild variant="ghost" className="w-fit">
        <Link to="/raw">Back to raw workbenches</Link>
      </Button>

      <PageHeader
        title={aggregate ? `${aggregate.code} ${aggregate.name}` : 'Raw workbench'}
        description={
          <>
            Raw workbench from <code>GET /api/v1/raw/{'{raw_id}'}</code>.
          </>
        }
        actions={
          <Button
            size="sm"
            variant="outline"
            disabled={!aggregate}
            onClick={() => setEditOpen(true)}
          >
            <Pencil /> Edit
          </Button>
        }
      />

      <WorkbenchDetailShell
        query={query}
        resourceLabel="raw workbench"
        tabs={tabs}
      />

      <ResourceFormDialog<PatchRawBody>
        open={editOpen}
        onOpenChange={setEditOpen}
        title="Edit raw workbench"
        description="Update the workbench name or status."
        fields={editFields}
        initialValues={initialEditValues(aggregate)}
        submitLabel="Save changes"
        successMessage="Raw workbench updated."
        isSubmitting={patch.isPending}
        submitError={patch.error}
        onSubmit={handleEdit}
      />
    </div>
  )
}

function initialEditValues(
  aggregate: AggregateResponse | undefined,
): Partial<PatchRawBody> {
  if (!aggregate) return {}
  return { name: aggregate.name, status: aggregate.status }
}
