import * as React from 'react'
import type { AxiosError } from 'axios'
import { useQueryClient } from '@tanstack/react-query'
import { Download, Loader2, Save, Trash2 } from 'lucide-react'
import { JsonAuthoringPanel } from './json-authoring-panel'
import { ArtifactList } from './artifact-list'
import { OperationRunner } from './operation-runner'
import { IssueList } from '@/components/data/issue-list'
import { ErrorState } from '@/components/data/states'
import { PageHeader } from '@/components/layout/page-header'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { toast } from '@/components/ui/sonner'
import type {
  ArtifactBuildResponse,
  DependencySelectionInput,
  DocumentResponse,
  EvidenceCreate,
  PutContentBody,
  UsdmDocument,
  ValidationRunResponse,
} from '@/api/generated/model'
import {
  getGetContentQueryKey,
  getGetDependenciesQueryKey,
  getGetDocumentQueryKey,
  getGetUsdmQueryKey,
  getListEvidenceQueryKey,
  deleteEvidence,
  useCreateDocumentArtifacts,
  useCreateEvidence,
  useGetContent,
  useGetDependencies,
  useGetProtocolContext,
  useGetUsdm,
  useListEvidence,
  usePutContent,
  usePutDependencies,
  usePutUsdm,
  useValidateDocumentEndpoint,
} from '@/api/generated/documents/documents'
import { useGetArtifactBuild } from '@/api/generated/artifact-builds/artifact-builds'
import { idempotentRequest, ifMatchRequest } from '@/lib/requests'
import { parseProblem, stalenessAlert } from '@/lib/problems'
import { useDownload } from '@/hooks/use-download'

async function refreshAggregate(
  qc: ReturnType<typeof useQueryClient>,
  documentId: string,
  key: readonly unknown[],
) {
  await Promise.all([
    qc.invalidateQueries({ queryKey: key }),
    qc.invalidateQueries({ queryKey: getGetDocumentQueryKey(documentId) }),
  ])
}

export function DocumentContentPanel({ document }: { document: DocumentResponse }) {
  const qc = useQueryClient()
  const query = useGetContent(document.id)
  const save = usePutContent({ request: ifMatchRequest(document.revision) })
  const download = useDownload()
  return <div className="flex flex-col gap-4"><JsonAuthoringPanel<PutContentBody>
    title="Structured content"
    description="Author the versioned content contract for this document type. Templates control presentation, never clinical narrative."
    value={query.data}
    isLoading={query.isLoading}
    error={query.error}
    emptyValue={{}}
    isSaving={save.isPending}
    onReload={() => query.refetch()}
    onSave={async (data) => {
      const result = await save.mutateAsync({ documentId: document.id, data })
      await refreshAggregate(qc, document.id, getGetContentQueryKey(document.id))
      return result
    }}
  /><div><Button variant="outline" disabled={!query.data || download.isPending} onClick={() => download.downloadDocumentContent(document.id, 'json', `${document.document_code}.json`)}>{download.isPending ? <Loader2 className="animate-spin" /> : <Download />} Export JSON</Button></div></div>
}

export function DocumentUsdmPanel({ document }: { document: DocumentResponse }) {
  const qc = useQueryClient()
  const query = useGetUsdm(document.id, { query: { enabled: document.document_type === 'protocol' } })
  const save = usePutUsdm({ request: ifMatchRequest(document.revision) })
  const download = useDownload()
  if (document.document_type !== 'protocol') return <Card><CardHeader><CardTitle>USDM not applicable</CardTitle><CardDescription>Only Protocol documents own a USDM representation.</CardDescription></CardHeader></Card>
  const empty: UsdmDocument = { schema_version: '1.0.0', usdm_version: '', study_version: '', entities: [], relationships: [] }
  return <div className="flex flex-col gap-4"><JsonAuthoringPanel<UsdmDocument>
    title="Protocol USDM"
    description="Maintain the pinned user-authored USDM subset and its entity relationships."
    value={query.data}
    isLoading={query.isLoading}
    error={query.error}
    emptyValue={empty}
    isSaving={save.isPending}
    onReload={() => query.refetch()}
    onSave={async (data) => {
      const result = await save.mutateAsync({ documentId: document.id, data })
      await refreshAggregate(qc, document.id, getGetUsdmQueryKey(document.id))
      return result
    }}
  /><div><Button variant="outline" disabled={!query.data || download.isPending} onClick={() => download.downloadDocumentUsdm(document.id, `${document.document_code}-usdm.json`)}>{download.isPending ? <Loader2 className="animate-spin" /> : <Download />} Export USDM</Button></div></div>
}

export function DocumentDependenciesPanel({ document }: { document: DocumentResponse }) {
  const qc = useQueryClient()
  const query = useGetDependencies(document.id)
  const replace = usePutDependencies({ request: ifMatchRequest(document.revision) })
  const [draft, setDraft] = React.useState('{}')
  const [error, setError] = React.useState<string | null>(null)
  React.useEffect(() => { if (query.data) { const { standards, terminology, references, templates, reaffirmation_reason } = query.data; setDraft(JSON.stringify({ standards, terminology, references, templates, ...(reaffirmation_reason ? { reaffirmation_reason } : {}) }, null, 2)) } }, [query.data])
  if (query.isError) return <ErrorState error={query.error} resourceLabel="document dependencies" />
  async function save() { try { await replace.mutateAsync({ documentId: document.id, data: JSON.parse(draft) as DependencySelectionInput }); await refreshAggregate(qc, document.id, getGetDependenciesQueryKey(document.id)); setError(null); toast.success('Dependency selection replaced.') } catch (caught) { if (caught instanceof SyntaxError) setError(caught.message); else { const axiosError = caught as AxiosError; setError(stalenessAlert(axiosError) ?? parseProblem(axiosError).detail ?? axiosError.message) } } }
  return <Card><CardHeader><CardTitle>Dependencies</CardTitle><CardDescription>Pin exact Standards, Terminology, Reference, and Template revisions.</CardDescription></CardHeader><CardContent className="flex flex-col gap-4"><Textarea rows={20} className="font-mono text-xs" value={draft} onChange={(event) => setDraft(event.target.value)} />{query.data && <p className="text-muted-foreground text-xs">Revision {query.data.revision} · {query.data.state} · <code>{query.data.fingerprint}</code></p>}{error && <p className="text-destructive text-sm" role="alert">{error}</p>}<div className="flex justify-end"><Button onClick={save} disabled={replace.isPending}>{replace.isPending ? <Loader2 className="animate-spin" /> : <Save />} Replace selection</Button></div></CardContent></Card>
}

const EMPTY_EVIDENCE: EvidenceCreate = {
  source_pdf_file_id: '',
  page_number: 1,
  region: {
    coordinate_system: 'pdf_points_top_left',
    page_width: 612,
    page_height: 792,
    rectangle: [0, 0, 1, 1],
  },
  linked_usdm_entity_ids: [],
  status: 'open',
}

export function DocumentEvidencePanel({ document }: { document: DocumentResponse }) {
  const qc = useQueryClient()
  const query = useListEvidence(document.id)
  const create = useCreateEvidence({ request: ifMatchRequest(document.revision) })
  const [draft, setDraft] = React.useState(JSON.stringify(EMPTY_EVIDENCE, null, 2))
  const [error, setError] = React.useState<string | null>(null)
  async function add() { try { await create.mutateAsync({ documentId: document.id, data: JSON.parse(draft) as EvidenceCreate }); await refreshAggregate(qc, document.id, getListEvidenceQueryKey(document.id)); setError(null); toast.success('Evidence added.') } catch (caught) { if (caught instanceof SyntaxError) setError(caught.message); else { const axiosError = caught as AxiosError; setError(parseProblem(axiosError).detail ?? axiosError.message) } } }
  async function deleteItem(id: string, revision: number) {
    try {
      await deleteEvidence(id, ifMatchRequest(revision))
      await refreshAggregate(qc, document.id, getListEvidenceQueryKey(document.id))
      setError(null)
      toast.success('Evidence deleted.')
    } catch (caught) {
      const axiosError = caught as AxiosError
      setError(parseProblem(axiosError).detail ?? axiosError.message)
    }
  }
  return <div className="flex flex-col gap-6"><PageHeader title="Evidence" description="Maintain source-PDF evidence regions and explicit USDM entity links." />{query.isError ? <ErrorState error={query.error} resourceLabel="document evidence" /> : <div className="rounded-md border">{(query.data ?? []).map((item) => <div key={item.id} className="flex items-start justify-between gap-4 border-b p-4 last:border-b-0"><div className="text-sm"><div className="font-medium">Page {item.page_number} · {item.status}</div><code className="text-muted-foreground text-xs">{item.id}</code><div className="text-muted-foreground mt-1">{item.linked_usdm_entity_ids.length} linked USDM entities</div></div><Button size="icon" variant="ghost" aria-label="Delete evidence" onClick={() => deleteItem(item.id, item.revision)}><Trash2 /></Button></div>)}</div>}<Card><CardHeader><CardTitle>Add evidence</CardTitle><CardDescription>Author an exact evidence record as typed JSON.</CardDescription></CardHeader><CardContent className="flex flex-col gap-4"><Textarea rows={14} className="font-mono text-xs" value={draft} onChange={(event) => setDraft(event.target.value)} />{error && <p className="text-destructive text-sm" role="alert">{error}</p>}<div className="flex justify-end"><Button onClick={add} disabled={create.isPending}>Add evidence</Button></div></CardContent></Card></div>
}

export function DocumentValidationPanel({ document }: { document: DocumentResponse }) {
  const validate = useValidateDocumentEndpoint()
  const [run, setRun] = React.useState<ValidationRunResponse | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  return <div className="flex flex-col gap-6"><PageHeader title="Validation" description="Create an immutable validation snapshot over the exact document revisions." /><div><Button disabled={validate.isPending} onClick={async () => { try { setRun(await validate.mutateAsync({ documentId: document.id })); setError(null) } catch (caught) { const e = caught as AxiosError; setError(parseProblem(e).detail ?? e.message) } }}>{validate.isPending && <Loader2 className="animate-spin" />} Validate document</Button></div>{error && <p className="text-destructive text-sm">{error}</p>}{run && <><Card><CardHeader><CardTitle>{run.status}</CardTitle><CardDescription>{run.validator_name} {run.validator_version} · <code>{run.input_fingerprint}</code></CardDescription></CardHeader></Card><IssueList issues={run.issues} /></>}</div>
}

export function DocumentBuildPanel({ document }: { document: DocumentResponse }) {
  const [fingerprint, setFingerprint] = React.useState(''); const [types, setTypes] = React.useState(''); const [buildId, setBuildId] = React.useState<string | null>(null)
  const build = useCreateDocumentArtifacts({ request: idempotentRequest() })
  async function start() { try { const result = await build.mutateAsync({ documentId: document.id, data: { artifact_types: types.split(',').map((value) => value.trim()).filter(Boolean), expected_input_fingerprint: fingerprint } }); setBuildId(result.id) } catch (caught) { const e = caught as AxiosError; toast.error(parseProblem(e).title ?? 'Build could not start', { description: parseProblem(e).detail }) } }
  return <div className="flex flex-col gap-6"><PageHeader title="Artifacts" description="Build immutable document artifacts from the exact validated content and dependency revisions." /><Card><CardHeader><CardTitle>Build request</CardTitle><CardDescription>Specify registered artifact types and the exact current input fingerprint.</CardDescription></CardHeader><CardContent className="grid gap-4 sm:grid-cols-2"><div className="flex flex-col gap-2"><Label htmlFor="doc-types">Artifact types</Label><Input id="doc-types" value={types} onChange={(event) => setTypes(event.target.value)} placeholder="document_pdf, document_docx" /></div><div className="flex flex-col gap-2"><Label htmlFor="doc-fingerprint">Input fingerprint</Label><Input id="doc-fingerprint" value={fingerprint} onChange={(event) => setFingerprint(event.target.value)} /></div></CardContent></Card><OperationRunner operationLabel="document artifact build" operationId={buildId} useGetOperation={useGetArtifactBuild} intervalMs={2000} timeoutMs={300000} onStart={start} startLabel="Build artifacts" startDisabled={!types.trim() || fingerprint.length !== 64} renderResult={(result: ArtifactBuildResponse) => <ArtifactList artifacts={result.result_artifact_ids.map((id) => ({ id }))} />} /></div>
}

export function DocumentProtocolContextPanel({ document }: { document: DocumentResponse }) {
  const query = useGetProtocolContext(document.id, { query: { enabled: document.document_type !== 'protocol' } })
  if (document.document_type === 'protocol') return <Card><CardHeader><CardTitle>Protocol context</CardTitle><CardDescription>A Protocol provides context to related documents; it does not consume another Protocol.</CardDescription></CardHeader></Card>
  if (query.isError) return <ErrorState error={query.error} resourceLabel="protocol context" />
  return <Card><CardHeader><CardTitle>Protocol context</CardTitle><CardDescription>Read-only exact Protocol/USDM context selected by this document.</CardDescription></CardHeader><CardContent><pre className="max-h-[36rem] overflow-auto rounded-md bg-muted p-4 text-xs">{JSON.stringify(query.data ?? {}, null, 2)}</pre></CardContent></Card>
}
