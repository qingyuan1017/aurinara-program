import * as React from 'react'
import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { useQueryClient } from '@tanstack/react-query'
import { Plus } from 'lucide-react'
import { formatDate } from '@/lib/utils'
import { PageHeader } from '@/components/layout/page-header'
import { ResourceTable } from '@/components/data/resource-table'
import type { ResourceColumn } from '@/components/data/resource-table'
import { EmptyState } from '@/components/data/states'
import { StatusBadge } from '@/components/data/status-badge'
import { Button } from '@/components/ui/button'
import { ResourceFormDialog, type FieldDescriptor } from '@/components/forms/resource-form-dialog'
import { useCurrentStudy } from '@/components/study-provider'
import {
  getListDocumentsQueryKey,
  useCreateDocument,
  useListDocuments,
} from '@/api/generated/documents/documents'
import { DocumentType } from '@/api/generated/model/documentType'
import type { DocumentCreate, DocumentResponse } from '@/api/generated/model'
import { jsonRequest } from '@/lib/requests'

export const Route = createFileRoute('/_app/documents/')({ component: DocumentsPage })

const columns: ResourceColumn<DocumentResponse>[] = [
  { key: 'document_code', header: 'Code' },
  { key: 'name', header: 'Name' },
  { key: 'document_type', header: 'Type' },
  { key: 'status', header: 'Status', cell: (row) => <StatusBadge status={row.status} /> },
  { key: 'revision', header: 'Revision' },
  { key: 'updated_at', header: 'Updated', cell: (row) => formatDate(row.updated_at) },
]

const fields: FieldDescriptor<DocumentCreate>[] = [
  { name: 'document_code', label: 'Code', control: 'text', required: true },
  { name: 'name', label: 'Name', control: 'text', required: true },
  {
    name: 'document_type', label: 'Document type', control: 'select', required: true,
    options: Object.values(DocumentType).map((value) => ({ label: value.replaceAll('_', ' '), value })),
  },
  { name: 'source_pdf_file_id', label: 'Protocol source PDF file ID', control: 'text' },
  { name: 'related_document_ids', label: 'Related document IDs', control: 'tags' },
]

function DocumentsPage() {
  const qc = useQueryClient(); const navigate = useNavigate()
  const { currentStudyId, isLoading: studiesLoading } = useCurrentStudy()
  const query = useListDocuments(currentStudyId ?? '', { query: { enabled: !!currentStudyId } })
  const [open, setOpen] = React.useState(false)
  const create = useCreateDocument({
    mutation: { onSuccess: () => qc.invalidateQueries({ queryKey: getListDocumentsQueryKey(currentStudyId ?? undefined) }) },
    request: jsonRequest(),
  })
  return <div className="flex flex-col gap-6">
    <PageHeader title="Documents" description="Manually author, validate, review, and build Protocol, SAP, operational, and quality deliverables." actions={<Button size="sm" disabled={!currentStudyId} onClick={() => setOpen(true)}><Plus /> New document</Button>} />
    <ResourceTable columns={columns} rows={query.data ?? []} getRowId={(row) => row.id} isLoading={query.isLoading || studiesLoading} isError={query.isError} error={query.error} resourceLabel="documents" onRowClick={(row) => navigate({ to: '/documents/$documentId', params: { documentId: row.id }, search: { tab: 'metadata' } })} emptyState={!studiesLoading && !currentStudyId ? <EmptyState title="No study selected" description="Select a study to view its documents." /> : undefined} />
    <ResourceFormDialog<DocumentCreate> open={open} onOpenChange={setOpen} title="New document" description="Create a manually authored document aggregate." fields={fields} initialValues={{ content_schema_version: '1.0.0' }} submitLabel="Create document" successMessage="Document created." isSubmitting={create.isPending} submitError={create.error} onSubmit={(data) => create.mutateAsync({ studyId: currentStudyId!, data })} />
  </div>
}
