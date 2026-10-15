import * as React from 'react'
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
import {
  getListTlfAggregatesQueryKey,
  useCreateTlfAggregate,
  useListTlfAggregates,
} from '@/api/generated/tlf/tlf'
import type { AggregateCreate, AggregateResponse } from '@/api/generated/model'
import { jsonRequest } from '@/lib/requests'

export const Route = createFileRoute('/_app/tlf/')({ component: TlfListPage })

const columns: ResourceColumn<AggregateResponse>[] = [
  { key: 'code', header: 'Code' },
  { key: 'name', header: 'Name' },
  { key: 'status', header: 'Status', cell: (row) => <StatusBadge status={row.status} /> },
  { key: 'revision', header: 'Revision' },
]

const createFields: FieldDescriptor<AggregateCreate>[] = [
  { name: 'code', label: 'Code', control: 'text', required: true },
  { name: 'name', label: 'Name', control: 'text', required: true },
]

function TlfListPage() {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const { currentStudyId, isLoading: studiesLoading } = useCurrentStudy()
  const query = useListTlfAggregates(currentStudyId ?? '', undefined, {
    query: { enabled: !!currentStudyId },
  })
  const [createOpen, setCreateOpen] = React.useState(false)
  const create = useCreateTlfAggregate({
    mutation: {
      onSuccess: () => qc.invalidateQueries({
        queryKey: getListTlfAggregatesQueryKey(currentStudyId ?? undefined),
      }),
    },
    request: jsonRequest(),
  })

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Tables, Listings & Figures"
        description="Author shells, ADaM bindings, assumptions, ARS, and ProgramPlans; then validate, compile, execute, and render outputs."
        actions={
          <Button size="sm" disabled={!currentStudyId} onClick={() => setCreateOpen(true)}>
            <Plus /> New TLF workbench
          </Button>
        }
      />
      <ResourceTable
        columns={columns}
        rows={query.data?.items ?? []}
        getRowId={(row) => row.id}
        isLoading={query.isLoading || studiesLoading}
        isError={query.isError}
        error={query.error}
        resourceLabel="TLF workbenches"
        onRowClick={(row) => navigate({ to: '/tlf/$tlfId', params: { tlfId: row.id }, search: { tab: 'shell' } })}
        emptyState={!studiesLoading && !currentStudyId ? (
          <EmptyState title="No study selected" description="Select a study to view its TLF workbenches." />
        ) : undefined}
      />
      <ResourceFormDialog<AggregateCreate>
        open={createOpen}
        onOpenChange={setCreateOpen}
        title="New TLF workbench"
        description="Create a TLF aggregate shell; clinical content is authored after creation."
        fields={createFields}
        initialValues={{}}
        submitLabel="Create workbench"
        successMessage="TLF workbench created."
        isSubmitting={create.isPending}
        submitError={create.error}
        onSubmit={(data) => create.mutateAsync({ studyId: currentStudyId!, data })}
      />
    </div>
  )
}
