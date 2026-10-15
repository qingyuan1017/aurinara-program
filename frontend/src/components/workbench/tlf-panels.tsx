import * as React from 'react'
import type { AxiosError } from 'axios'
import { useQueryClient } from '@tanstack/react-query'
import { Loader2, Save } from 'lucide-react'
import { JsonAuthoringPanel } from './json-authoring-panel'
import { ArtifactList } from './artifact-list'
import { OperationRunner } from './operation-runner'
import { useWorkbench } from './workbench-context'
import { IssueList } from '@/components/data/issue-list'
import { ErrorState } from '@/components/data/states'
import { PageHeader } from '@/components/layout/page-header'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { toast } from '@/components/ui/sonner'
import type {
  ArtifactBuildResponse,
  AuthoringResponse,
  DependencySelectionInput,
  ExecutionRunResponse,
  PreviewResponse,
  TlfArs,
  TlfAssumptions,
  TlfBindings,
  TlfExecutionRequest,
  TlfProgramPlan,
  TlfShell,
  ValidationRunResponse,
} from '@/api/generated/model'
import {
  getGetArsQueryKey,
  getGetAssumptionsQueryKey,
  getGetBindingsQueryKey,
  getGetProgramPlanQueryKey,
  getGetShellQueryKey,
  getGetTlfAggregateQueryKey,
  getGetTlfDependenciesQueryKey,
  useCompileTlf,
  useCreateTlfArtifacts,
  useExecuteTlf,
  useGetArs,
  useGetAssumptions,
  useGetBindings,
  useGetProgramPlan,
  useGetShell,
  useGetTlfDependencies,
  usePreviewProgramPlan,
  usePutArs,
  usePutAssumptions,
  usePutBindings,
  usePutProgramPlan,
  usePutShell,
  useRenderTlf,
  useReplaceTlfDependencies,
  useValidateProgramPlan,
  useValidateTlf,
} from '@/api/generated/tlf/tlf'
import { useGetArtifactBuild } from '@/api/generated/artifact-builds/artifact-builds'
import { useGetExecutionRun } from '@/api/generated/execution/execution'
import { idempotentRequest, ifMatchRequest } from '@/lib/requests'
import { parseProblem, stalenessAlert } from '@/lib/problems'

const EMPTY_SHELL: TlfShell = {
  schema_version: '1.0.0',
  output_code: '',
  output_type: 'table',
  title: '',
  columns: [],
  rows: [],
  footnotes: [],
  orientation: 'landscape',
}
const EMPTY_BINDINGS: TlfBindings = {
  schema_version: '1.0.0',
  datasets: [],
  named: [],
}
const EMPTY_ASSUMPTIONS: TlfAssumptions = { schema_version: '1.0.0', items: [] }
const EMPTY_ARS: TlfArs = { schema_version: '1.0.0', analyses: [] }

type ContentQuery = {
  data: AuthoringResponse | undefined
  isLoading: boolean
  error: AxiosError | null
  refetch: () => Promise<unknown>
}

function invalidateContent(
  qc: ReturnType<typeof useQueryClient>,
  tlfId: string,
  key: readonly unknown[],
) {
  void qc.invalidateQueries({ queryKey: key })
  void qc.invalidateQueries({ queryKey: getGetTlfAggregateQueryKey(tlfId) })
}

function ContentPanel<T extends object>({
  title,
  description,
  query,
  emptyValue,
  saving,
  save,
}: {
  title: string
  description: React.ReactNode
  query: ContentQuery
  emptyValue: T
  saving: boolean
  save: (value: T) => Promise<AuthoringResponse>
}) {
  return (
    <JsonAuthoringPanel
      title={title}
      description={description}
      value={query.data}
      isLoading={query.isLoading}
      error={query.error}
      emptyValue={emptyValue}
      isSaving={saving}
      onSave={save}
      onReload={() => query.refetch()}
    />
  )
}

export function TlfShellPanel({ tlfId }: { tlfId: string }) {
  const qc = useQueryClient()
  const { revision } = useWorkbench()
  const query = useGetShell(tlfId)
  const mutation = usePutShell({ request: ifMatchRequest(revision) })
  return (
    <ContentPanel
      title="Shell"
      description="Define the manually authored output structure, headings, rows, columns, and footnotes."
      query={query}
      emptyValue={EMPTY_SHELL}
      saving={mutation.isPending}
      save={async (data) => {
        const saved = await mutation.mutateAsync({ tlfId, data })
        invalidateContent(qc, tlfId, getGetShellQueryKey(tlfId))
        return saved
      }}
    />
  )
}

export function TlfBindingsPanel({ tlfId }: { tlfId: string }) {
  const qc = useQueryClient()
  const { revision } = useWorkbench()
  const query = useGetBindings(tlfId)
  const mutation = usePutBindings({ request: ifMatchRequest(revision) })
  return (
    <ContentPanel
      title="ADaM bindings"
      description="Pin exact validated ADaM datasets and manually name population, parameter, statistic, and grouping bindings."
      query={query}
      emptyValue={EMPTY_BINDINGS}
      saving={mutation.isPending}
      save={async (data) => {
        const saved = await mutation.mutateAsync({ tlfId, data })
        invalidateContent(qc, tlfId, getGetBindingsQueryKey(tlfId))
        return saved
      }}
    />
  )
}

export function TlfAssumptionsPanel({ tlfId }: { tlfId: string }) {
  const qc = useQueryClient()
  const { revision } = useWorkbench()
  const query = useGetAssumptions(tlfId)
  const mutation = usePutAssumptions({ request: ifMatchRequest(revision) })
  return (
    <ContentPanel
      title="Assumptions"
      description="Record user-authored analysis assumptions. The platform does not propose or infer them."
      query={query}
      emptyValue={EMPTY_ASSUMPTIONS}
      saving={mutation.isPending}
      save={async (data) => {
        const saved = await mutation.mutateAsync({ tlfId, data })
        invalidateContent(qc, tlfId, getGetAssumptionsQueryKey(tlfId))
        return saved
      }}
    />
  )
}

export function TlfArsPanel({ tlfId }: { tlfId: string }) {
  const qc = useQueryClient()
  const { revision } = useWorkbench()
  const query = useGetArs(tlfId)
  const mutation = usePutArs({ request: ifMatchRequest(revision) })
  return (
    <ContentPanel
      title="Analysis Results Standard"
      description="Map every leaf shell row to one manually specified analysis and exact named bindings."
      query={query}
      emptyValue={EMPTY_ARS}
      saving={mutation.isPending}
      save={async (data) => {
        const saved = await mutation.mutateAsync({ tlfId, data })
        invalidateContent(qc, tlfId, getGetArsQueryKey(tlfId))
        return saved
      }}
    />
  )
}

export function TlfProgramPlanPanel({ tlfId }: { tlfId: string }) {
  const qc = useQueryClient()
  const { revision } = useWorkbench()
  const query = useGetProgramPlan(tlfId)
  const shell = useGetShell(tlfId)
  const bindings = useGetBindings(tlfId)
  const assumptions = useGetAssumptions(tlfId)
  const ars = useGetArs(tlfId)
  const mutation = usePutProgramPlan({ request: ifMatchRequest(revision) })
  const emptyValue = React.useMemo<TlfProgramPlan>(() => ({
    schema_version: '1.0.0',
    shell_revision: shell.data?.revision ?? 1,
    bindings_revision: bindings.data?.revision ?? 1,
    assumptions_revision: assumptions.data?.revision ?? 1,
    ars_revision: ars.data?.revision ?? 1,
    output_filename: '',
    custom_functions: [],
    steps: [],
  }), [ars.data?.revision, assumptions.data?.revision, bindings.data?.revision, shell.data?.revision])
  return (
    <ContentPanel
      title="ProgramPlan"
      description="Author structured statistical procedures, optional per-language custom functions, and pin the exact current Shell, Bindings, Assumptions, and ARS revisions."
      query={query}
      emptyValue={emptyValue}
      saving={mutation.isPending}
      save={async (data) => {
        const saved = await mutation.mutateAsync({ tlfId, data })
        invalidateContent(qc, tlfId, getGetProgramPlanQueryKey(tlfId))
        return saved
      }}
    />
  )
}

export function TlfDependenciesPanel({ tlfId }: { tlfId: string }) {
  const qc = useQueryClient()
  const { revision } = useWorkbench()
  const query = useGetTlfDependencies(tlfId)
  const mutation = useReplaceTlfDependencies({ request: ifMatchRequest(revision) })
  const [draft, setDraft] = React.useState('{}')
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    if (!query.data) return
    const { standards, terminology, references, templates, reaffirmation_reason } = query.data
    setDraft(JSON.stringify({
      standards,
      terminology,
      references,
      templates,
      ...(reaffirmation_reason ? { reaffirmation_reason } : {}),
    }, null, 2))
  }, [query.data])

  if (query.isError) {
    return <ErrorState error={query.error} resourceLabel="TLF dependencies" />
  }

  async function save() {
    try {
      const data = JSON.parse(draft) as DependencySelectionInput
      await mutation.mutateAsync({ tlfId, data })
      await Promise.all([
        qc.invalidateQueries({ queryKey: getGetTlfDependenciesQueryKey(tlfId) }),
        qc.invalidateQueries({ queryKey: getGetTlfAggregateQueryKey(tlfId) }),
      ])
      setError(null)
      toast.success('Dependency selection replaced.')
    } catch (caught) {
      if (caught instanceof SyntaxError) setError(caught.message)
      else {
        const axiosError = caught as AxiosError
        setError(stalenessAlert(axiosError) ?? parseProblem(axiosError).detail ?? axiosError.message)
      }
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Dependencies</CardTitle>
        <CardDescription>Pin exact standards, terminology, references, and presentation templates.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <Textarea rows={20} className="font-mono text-xs" value={draft} onChange={(event) => setDraft(event.target.value)} />
        {query.data && <p className="text-muted-foreground text-xs">Revision {query.data.revision} · state {query.data.state} · fingerprint <code>{query.data.fingerprint}</code></p>}
        {error && <p className="text-destructive text-sm" role="alert">{error}</p>}
        <div className="flex justify-end">
          <Button onClick={save} disabled={mutation.isPending}>
            {mutation.isPending ? <Loader2 className="animate-spin" /> : <Save />} Replace selection
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

export function TlfValidationPanel({ tlfId }: { tlfId: string }) {
  const plan = useValidateProgramPlan()
  const all = useValidateTlf()
  const preview = usePreviewProgramPlan()
  const [run, setRun] = React.useState<ValidationRunResponse | null>(null)
  const [previewResult, setPreviewResult] = React.useState<PreviewResponse | null>(null)
  const [error, setError] = React.useState<string | null>(null)

  async function validate(action: () => Promise<ValidationRunResponse>) {
    try { setRun(await action()); setError(null) }
    catch (caught) { const axiosError = caught as AxiosError; setError(parseProblem(axiosError).detail ?? axiosError.message) }
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title="Validation & preview" description="Validate exact authored revisions and inspect normalized Analysis IR before compilation." />
      <div className="flex flex-wrap gap-2">
        <Button onClick={() => validate(() => plan.mutateAsync({ tlfId }))} disabled={plan.isPending}>Validate ProgramPlan</Button>
        <Button variant="outline" onClick={() => validate(() => all.mutateAsync({ tlfId }))} disabled={all.isPending}>Validate complete TLF</Button>
        <Button variant="outline" onClick={async () => {
          try { setPreviewResult(await preview.mutateAsync({ tlfId })); setError(null) }
          catch (caught) { const axiosError = caught as AxiosError; setError(parseProblem(axiosError).detail ?? axiosError.message) }
        }} disabled={preview.isPending}>Preview Analysis IR</Button>
      </div>
      {error && <p className="text-destructive text-sm" role="alert">{error}</p>}
      {run && <>
        <Card><CardHeader><CardTitle>Validation run</CardTitle><CardDescription>{run.validator_name} {run.validator_version} · {run.status} · fingerprint <code>{run.input_fingerprint}</code></CardDescription></CardHeader></Card>
        <IssueList issues={run.issues} />
      </>}
      {previewResult && <Card><CardHeader><CardTitle>Normalized Analysis IR</CardTitle><CardDescription>{previewResult.procedure_count} procedure(s) · <code>{previewResult.analysis_ir_fingerprint}</code></CardDescription></CardHeader><CardContent><pre className="max-h-[34rem] overflow-auto rounded-md bg-muted p-4 text-xs">{JSON.stringify(previewResult.normalized_analysis_ir, null, 2)}</pre></CardContent></Card>}
    </div>
  )
}

function BuildResult({ build }: { build: ArtifactBuildResponse }) {
  return <ArtifactList artifacts={build.result_artifact_ids.map((id) => ({ id }))} />
}

export function TlfBuildPanel({ tlfId }: { tlfId: string }) {
  const [fingerprint, setFingerprint] = React.useState('')
  const [backend, setBackend] = React.useState('python')
  const [format, setFormat] = React.useState('pdf')
  const [types, setTypes] = React.useState('')
  const [compileId, setCompileId] = React.useState<string | null>(null)
  const [renderId, setRenderId] = React.useState<string | null>(null)
  const [artifactId, setArtifactId] = React.useState<string | null>(null)
  const compile = useCompileTlf({ request: idempotentRequest() })
  const render = useRenderTlf({ request: idempotentRequest() })
  const artifacts = useCreateTlfArtifacts({ request: idempotentRequest() })

  async function start(kind: 'compile' | 'render' | 'artifacts') {
    try {
      if (kind === 'compile') setCompileId((await compile.mutateAsync({ tlfId, data: { backend, expected_input_fingerprint: fingerprint } })).id)
      if (kind === 'render') setRenderId((await render.mutateAsync({ tlfId, data: { format, expected_input_fingerprint: fingerprint } })).id)
      if (kind === 'artifacts') setArtifactId((await artifacts.mutateAsync({ tlfId, data: { artifact_types: types.split(',').map((value) => value.trim()).filter(Boolean), expected_input_fingerprint: fingerprint } })).id)
    } catch (caught) {
      const axiosError = caught as AxiosError
      const problem = parseProblem(axiosError)
      toast.error(problem.title ?? 'Operation could not start', { description: problem.detail })
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title="Compile, render & artifacts" description="Create immutable programs and rendered outputs from exact validated TLF inputs." />
      <Card><CardHeader><CardTitle>Exact input fingerprint</CardTitle><CardDescription>Paste the fingerprint from the validated authoring manifest. The backend rejects stale inputs.</CardDescription></CardHeader><CardContent><Input value={fingerprint} onChange={(event) => setFingerprint(event.target.value)} placeholder="64-character SHA-256" /></CardContent></Card>
      <Card><CardHeader><CardTitle>Compile</CardTitle></CardHeader><CardContent className="flex flex-col gap-4"><Select value={backend} onValueChange={setBackend}><SelectTrigger className="w-48"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="python">Python</SelectItem><SelectItem value="r">R</SelectItem><SelectItem value="sas">SAS</SelectItem></SelectContent></Select><OperationRunner<ArtifactBuildResponse> operationLabel="TLF compile" operationId={compileId} useGetOperation={useGetArtifactBuild} intervalMs={2000} timeoutMs={300000} onStart={() => start('compile')} startLabel="Compile program" startDisabled={!fingerprint} renderResult={(result) => <BuildResult build={result} />} /></CardContent></Card>
      <Card><CardHeader><CardTitle>Render</CardTitle></CardHeader><CardContent className="flex flex-col gap-4"><Select value={format} onValueChange={setFormat}><SelectTrigger className="w-48"><SelectValue /></SelectTrigger><SelectContent>{['pdf','rtf','png','svg'].map((item) => <SelectItem key={item} value={item}>{item.toUpperCase()}</SelectItem>)}</SelectContent></Select><OperationRunner<ArtifactBuildResponse> operationLabel="TLF render" operationId={renderId} useGetOperation={useGetArtifactBuild} intervalMs={2000} timeoutMs={300000} onStart={() => start('render')} startLabel="Render output" startDisabled={!fingerprint} renderResult={(result) => <BuildResult build={result} />} /></CardContent></Card>
      <Card><CardHeader><CardTitle>Additional artifacts</CardTitle><CardDescription>Comma-separated registered TLF artifact types.</CardDescription></CardHeader><CardContent className="flex flex-col gap-4"><Input value={types} onChange={(event) => setTypes(event.target.value)} placeholder="tlf_table_pdf" /><OperationRunner<ArtifactBuildResponse> operationLabel="TLF artifact build" operationId={artifactId} useGetOperation={useGetArtifactBuild} intervalMs={2000} timeoutMs={300000} onStart={() => start('artifacts')} startLabel="Build artifacts" startDisabled={!fingerprint || !types.trim()} renderResult={(result) => <BuildResult build={result} />} /></CardContent></Card>
    </div>
  )
}

export function TlfExecutionPanel({ tlfId }: { tlfId: string }) {
  const [draft, setDraft] = React.useState(() => JSON.stringify({
    language: 'python',
    program_artifact_id: '',
    input_artifact_ids: [],
    validation_run_id: '',
    bindings_revision: 1,
    shell_revision: 1,
    program_plan_revision: 1,
    compiler_fingerprint: '',
    expected_input_fingerprint: '',
    limits: { cpu: 1, memory_mb: 1024, runtime_seconds: 300, output_bytes: 104857600 },
  } satisfies TlfExecutionRequest, null, 2))
  const [runId, setRunId] = React.useState<string | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const execute = useExecuteTlf({ request: idempotentRequest() })

  async function start() {
    try {
      const data = JSON.parse(draft) as TlfExecutionRequest
      setRunId((await execute.mutateAsync({ tlfId, data })).id)
      setError(null)
    } catch (caught) {
      if (caught instanceof SyntaxError) setError(caught.message)
      else { const axiosError = caught as AxiosError; setError(parseProblem(axiosError).detail ?? axiosError.message) }
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title="Execution" description="Execute an immutable generated program against exact validated inputs in the isolated runner." />
      <div><Label htmlFor="tlf-execution">Pinned execution request</Label><Textarea id="tlf-execution" rows={20} className="mt-2 font-mono text-xs" value={draft} onChange={(event) => setDraft(event.target.value)} /></div>
      {error && <p className="text-destructive text-sm" role="alert">{error}</p>}
      <OperationRunner<ExecutionRunResponse> operationLabel="TLF execution" operationId={runId} useGetOperation={useGetExecutionRun} intervalMs={2000} timeoutMs={300000} onStart={start} startLabel="Execute program" renderResult={(run) => <Card><CardHeader><CardTitle>Execution {run.status}</CardTitle><CardDescription>Run <code>{run.id}</code> · exit code {run.exit_code ?? '—'}</CardDescription></CardHeader><CardContent><ArtifactList title="Output artifacts" artifacts={run.output_artifact_ids.map((id) => ({ id }))} /></CardContent></Card>} />
    </div>
  )
}
