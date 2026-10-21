import * as React from 'react'
import type { AxiosError } from 'axios'
import { createFileRoute, Link, useNavigate } from '@tanstack/react-router'
import { useQueryClient } from '@tanstack/react-query'
import { Loader2, Save } from 'lucide-react'
import { DetailHeader } from '@/components/data/detail-header'
import { EmptyState, ErrorState } from '@/components/data/states'
import { StatusBadge } from '@/components/data/status-badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { toast } from '@/components/ui/sonner'
import { useCurrentStudy } from '@/components/study-context'
import {
  DocumentBuildPanel,
  DocumentContentPanel,
  DocumentDependenciesPanel,
  DocumentEvidencePanel,
  DocumentProtocolContextPanel,
  DocumentUsdmPanel,
  DocumentValidationPanel,
} from '@/components/workbench/document-panels'
import type { DocumentResponse } from '@/api/generated/model'
import {
  getGetDocumentQueryKey,
  useGetDocument,
  useListDocuments,
  usePatchDocument,
} from '@/api/generated/documents/documents'
import { useListSourceFiles } from '@/api/generated/artifacts/artifacts'
import { ifMatchRequest } from '@/lib/requests'
import { parseProblem, stalenessAlert } from '@/lib/problems'

const TABS = [
  'metadata',
  'content',
  'usdm',
  'evidence',
  'protocol-context',
  'validation',
  'artifacts',
  'dependencies',
] as const
type Tab = (typeof TABS)[number]

export const Route = createFileRoute('/_app/documents/$documentId')({
  validateSearch: (search: Record<string, unknown>): { tab: Tab } => ({
    tab:
      typeof search.tab === 'string' && TABS.includes(search.tab as Tab)
        ? (search.tab as Tab)
        : 'metadata',
  }),
  component: DocumentDetailPage,
})

function DocumentMetadataPanel({ document }: { document: DocumentResponse }) {
  const qc = useQueryClient()
  const { currentStudyId } = useCurrentStudy()
  const documents = useListDocuments(currentStudyId ?? '', { query: { enabled: !!currentStudyId } })
  const sourceFiles = useListSourceFiles(currentStudyId ?? '', { limit: 200 }, { query: { enabled: !!currentStudyId } })
  const patch = usePatchDocument({ request: ifMatchRequest(document.revision) })
  const [name, setName] = React.useState(document.name)
  const [status, setStatus] = React.useState(document.status)
  const [sourcePdfFileId, setSourcePdfFileId] = React.useState(
    document.source_pdf_file_id ?? '',
  )
  const [relatedIds, setRelatedIds] = React.useState<string[]>(document.related_document_ids)
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    setName(document.name)
    setStatus(document.status)
    setSourcePdfFileId(document.source_pdf_file_id ?? '')
    setRelatedIds(document.related_document_ids)
  }, [document])

  async function save() {
    try {
      await patch.mutateAsync({
        documentId: document.id,
        data: {
          name,
          status,
          source_pdf_file_id: sourcePdfFileId.trim() || null,
          related_document_ids: relatedIds,
        },
      })
      await qc.invalidateQueries({ queryKey: getGetDocumentQueryKey(document.id) })
      setError(null)
      toast.success('Document metadata saved.')
    } catch (caught) {
      const axiosError = caught as AxiosError
      setError(
        stalenessAlert(axiosError) ??
          parseProblem(axiosError).detail ??
          axiosError.message,
      )
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Document metadata</CardTitle>
        <CardDescription>
          Maintain identity, lifecycle state, source PDF, and explicit related-document links.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4 md:grid-cols-2">
        <div className="flex flex-col gap-2">
          <Label htmlFor="document-name">Name</Label>
          <Input id="document-name" value={name} onChange={(event) => setName(event.target.value)} />
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="document-status">Status</Label>
          <select id="document-status" value={status} onChange={(event) => setStatus(event.target.value)} className="h-9 rounded-md border bg-background px-3 text-sm"><option value="draft">Draft</option><option value="in_review">In review</option><option value="approved">Approved</option><option value="retired">Retired</option></select>
        </div>
        <div className="flex flex-col gap-2 md:col-span-2">
          <Label htmlFor="source-pdf">Source PDF</Label>
          <select id="source-pdf" value={sourcePdfFileId} onChange={(event) => setSourcePdfFileId(event.target.value)} className="h-9 rounded-md border bg-background px-3 text-sm"><option value="">No source PDF</option>{(sourceFiles.data?.items ?? []).filter((file) => file.media_type === 'application/pdf').map((file) => <option key={file.id} value={file.id}>{file.filename}</option>)}</select>
        </div>
        <div className="flex flex-col gap-2 md:col-span-2">
          <Label>Related documents</Label>
          <div className="max-h-48 space-y-1 overflow-y-auto rounded-md border p-2">{(documents.data ?? []).filter((item) => item.id !== document.id).map((item) => <label key={item.id} className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-muted"><input type="checkbox" checked={relatedIds.includes(item.id)} onChange={(event) => setRelatedIds((current) => event.target.checked ? [...current, item.id] : current.filter((id) => id !== item.id))} /><span>{item.document_code} · {item.name}</span></label>)}{!documents.isLoading && (documents.data?.length ?? 0) <= 1 ? <p className="px-2 py-1 text-sm text-muted-foreground">No other documents are available.</p> : null}</div>
        </div>
        {error && <p className="text-destructive text-sm md:col-span-2" role="alert">{error}</p>}
        <div className="flex justify-end md:col-span-2">
          <Button disabled={patch.isPending || !name.trim()} onClick={save}>
            {patch.isPending ? <Loader2 className="animate-spin" /> : <Save />} Save metadata
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

function DocumentDetailPage() {
  const { documentId } = Route.useParams()
  const { tab } = Route.useSearch()
  const navigate = useNavigate()
  const { currentStudyId, isLoading: studiesLoading } = useCurrentStudy()
  const query = useGetDocument(documentId, { query: { enabled: !!currentStudyId } })

  if (!currentStudyId) {
    return studiesLoading ? <Skeleton className="h-40 w-full" /> : <EmptyState title="No study selected" description="Select a study to open this document." />
  }
  if (query.isError) return <ErrorState error={query.error} resourceLabel="document" />
  if (query.isLoading || !query.data) return <Skeleton className="h-96 w-full" />
  if (query.data.study_id !== currentStudyId) return <EmptyState title="Not available in this study" description="This document belongs to a different study than the one selected." />

  const document = query.data
  const panels: Record<Tab, React.ReactNode> = {
    metadata: <DocumentMetadataPanel document={document} />,
    content: <DocumentContentPanel document={document} />,
    usdm: <DocumentUsdmPanel document={document} />,
    evidence: <DocumentEvidencePanel document={document} />,
    'protocol-context': <DocumentProtocolContextPanel document={document} />,
    validation: <DocumentValidationPanel document={document} />,
    artifacts: <DocumentBuildPanel document={document} />,
    dependencies: <DocumentDependenciesPanel document={document} />,
  }

  return (
    <div className="flex flex-col gap-6">
      <Button asChild variant="ghost" className="w-fit"><Link to="/documents">Back to documents</Link></Button>
      <DetailHeader fields={[
        { label: 'Code', value: document.document_code },
        { label: 'Name', value: document.name },
        { label: 'Type', value: document.document_type.replaceAll('_', ' ') },
        { label: 'Status', value: <StatusBadge status={document.status} /> },
        { label: 'Revision', value: document.revision },
        { label: 'Content schema', value: document.content_schema_version },
      ]} />
      <Tabs value={tab} onValueChange={(value) => navigate({ to: '/documents/$documentId', params: { documentId }, search: { tab: value as Tab }, replace: true })}>
        <TabsList>
          {TABS.map((value) => <TabsTrigger key={value} value={value}>{value.replaceAll('-', ' ')}</TabsTrigger>)}
        </TabsList>
        {TABS.map((value) => <TabsContent key={value} value={value}>{panels[value]}</TabsContent>)}
      </Tabs>
    </div>
  )
}
