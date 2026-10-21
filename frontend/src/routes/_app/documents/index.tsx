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
import { useCurrentStudy } from '@/components/study-context'
import {
  getListDocumentsQueryKey,
  useCreateDocument,
  useListDocuments,
} from '@/api/generated/documents/documents'
import { DocumentType } from '@/api/generated/model/documentType'
import type { DocumentCreate, DocumentResponse } from '@/api/generated/model'
import { jsonRequest } from '@/lib/requests'
import { useListSourceFiles } from '@/api/generated/artifacts/artifacts'

export const Route = createFileRoute('/_app/documents/')({ component: DocumentsPage })

const columns: ResourceColumn<DocumentResponse>[] = [
  { key: 'document_code', header: 'Code' },
  { key: 'name', header: 'Name' },
  { key: 'document_type', header: 'Type' },
  { key: 'status', header: 'Status', cell: (row) => <StatusBadge status={row.status} /> },
  { key: 'revision', header: 'Revision' },
  { key: 'updated_at', header: 'Updated', cell: (row) => formatDate(row.updated_at) },
]

const baseFields: FieldDescriptor<DocumentCreate>[] = [
  { name: 'document_code', label: 'Code', control: 'text', required: true },
  { name: 'name', label: 'Name', control: 'text', required: true },
  {
    name: 'document_type', label: 'Document type', control: 'select', required: true,
    options: Object.values(DocumentType).map((value) => ({ label: value.replaceAll('_', ' '), value })),
  },
]

function DocumentsPage() {
  const qc = useQueryClient(); const navigate = useNavigate()
  const { currentStudyId, isLoading: studiesLoading } = useCurrentStudy()
  const query = useListDocuments(currentStudyId ?? '', { query: { enabled: !!currentStudyId } })
  const sourceFiles = useListSourceFiles(currentStudyId ?? '', { limit: 200 }, { query: { enabled: !!currentStudyId } })
  const fields = React.useMemo<FieldDescriptor<DocumentCreate>[]>(() => [
    ...baseFields,
    {
      name: 'source_pdf_file_id',
      label: 'Protocol source PDF',
      control: 'select',
      placeholder: sourceFiles.isLoading ? 'Loading source files…' : 'Select a PDF',
      options: (sourceFiles.data?.items ?? [])
        .filter((file) => file.media_type === 'application/pdf')
        .map((file) => ({ value: file.id, label: file.filename })),
    },
    {
      name: 'related_document_ids',
      label: 'Related documents',
      control: 'multiselect',
      options: (query.data ?? []).map((document) => ({
        value: document.id,
        label: `${document.document_code} · ${document.name}`,
      })),
      helpText: 'Choose any existing documents that provide context for this one.',
    },
  ], [query.data, sourceFiles.data, sourceFiles.isLoading])
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
