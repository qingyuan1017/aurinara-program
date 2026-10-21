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
import { ResourceFormDialog, type FieldDescriptor } from '@/components/forms/resource-form-dialog'
import { useCurrentStudy } from '@/components/study-context'
import { getListAdamAggregatesQueryKey, useCreateAdamAggregate, useListAdamAggregates } from '@/api/generated/adam/adam'
import type { AggregateCreate, AggregateResponse } from '@/api/generated/model'
import { jsonRequest } from '@/lib/requests'

export const Route = createFileRoute('/_app/adam/')({ component: AdamPage })

const columns: ResourceColumn<AggregateResponse>[] = [
  { key: 'code', header: 'Code' }, { key: 'name', header: 'Name' },
  { key: 'status', header: 'Status', cell: (row) => <StatusBadge status={row.status} /> },
  { key: 'revision', header: 'Revision' },
]
const fields: FieldDescriptor<AggregateCreate>[] = [
  { name: 'code', label: 'Code', control: 'text', required: true },
  { name: 'name', label: 'Name', control: 'text', required: true },
  { name: 'document_type', label: 'Document type', control: 'text' },
]

function AdamPage() {
  const qc = useQueryClient(); const navigate = useNavigate(); const { currentStudyId, isLoading: studiesLoading } = useCurrentStudy(); const [open, setOpen] = React.useState(false)
  const query = useListAdamAggregates(currentStudyId ?? '', undefined, { query: { enabled: !!currentStudyId } })
  const create = useCreateAdamAggregate({ mutation: { onSuccess: () => qc.invalidateQueries({ queryKey: getListAdamAggregatesQueryKey(currentStudyId ?? undefined) }) }, request: jsonRequest() })
  return <div className="flex flex-col gap-6"><PageHeader title="ADaM workbenches" description="Author the aggregate Specification, exact SDTM selection, one typed derivation plan per dataset, Define metadata, and ADRG." actions={<Button size="sm" disabled={!currentStudyId} onClick={() => setOpen(true)}><Plus /> New ADaM workbench</Button>} /><ResourceTable columns={columns} rows={query.data?.items ?? []} getRowId={(row) => row.id} isLoading={query.isLoading || studiesLoading} isError={query.isError} error={query.error} resourceLabel="ADaM workbenches" onRowClick={(row) => navigate({ to: '/adam/$adamId', params: { adamId: row.id }, search: { tab: 'inputs' } })} emptyState={!studiesLoading && !currentStudyId ? <EmptyState title="No study selected" description="Select a study to view its ADaM workbenches." /> : undefined} /><ResourceFormDialog<AggregateCreate> open={open} onOpenChange={setOpen} title="New ADaM workbench" description="Create the shell; all clinical mappings and derivations remain manually authored." fields={fields} initialValues={{}} submitLabel="Create workbench" successMessage="ADaM workbench created." isSubmitting={create.isPending} submitError={create.error} onSubmit={(data) => create.mutateAsync({ studyId: currentStudyId!, data })} /></div>
}
