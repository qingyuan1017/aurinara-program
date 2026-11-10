import * as React from 'react'
import type { AxiosError } from 'axios'
import { useQueryClient } from '@tanstack/react-query'
import { Loader2, Save } from 'lucide-react'
import type {
  ArtifactBuildResponse,
  DependencySelectionInput,
  ExecutionRunResponse,
  PreviewResponse,
  TlfArs,
  TlfAssumptions,
  TlfBindings,
  TlfExecutionRequest,
  TlfInputSelectionWrite,
  TlfOutputInventory,
  TlfProgramPlan,
  TlfShell,
  ValidationRunResponse,
} from '@/api/generated/model'
import {
  getGetArsQueryKey,
  getGetAssumptionsQueryKey,
  getGetBindingsQueryKey,
  getGetInventoryQueryKey,
  getGetInputSelectionQueryKey,
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
  useGetInventory,
  useGetInputSelection,
  useGetProgramPlan,
  useGetShell,
  useGetTlfDependencies,
  usePreviewProgramPlan,
  usePutArs,
  usePutAssumptions,
  usePutBindings,
  usePutInventory,
  usePutInputSelection,
  usePutProgramPlan,
  usePutShell,
  useRenderTlf,
  useReplaceTlfDependencies,
  useValidateProgramPlan,
  useValidateTlf,
} from '@/api/generated/tlf/tlf'
import { useGetArtifactBuild } from '@/api/generated/artifact-builds/artifact-builds'
import { useGetExecutionRun } from '@/api/generated/execution/execution'
import { ArtifactList } from '@/components/workbench/artifact-list'
import { JsonAuthoringPanel } from '@/components/workbench/json-authoring-panel'
import { OperationRunner } from '@/components/workbench/operation-runner'
import { useWorkbench } from '@/components/workbench/workbench-context'
import { IssueList } from '@/components/data/issue-list'
import { ErrorState } from '@/components/data/states'
import { PageHeader } from '@/components/layout/page-header'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { toast } from '@/components/ui/sonner'
import { parseProblem, stalenessAlert } from '@/lib/problems'
import { idempotentRequest, ifMatchRequest } from '@/lib/requests'

const EMPTY_INPUTS: TlfInputSelectionWrite = { schema_version: '1.0.0', documents: [], datasets: [] }

export function TlfInputSelectionPanel({ tlfId }: { tlfId: string }) {
  const qc = useQueryClient()
  const { revision } = useWorkbench()
  const query = useGetInputSelection(tlfId, { query: { retry: false } })
  const save = usePutInputSelection({ request: ifMatchRequest(revision) })
  return <JsonAuthoringPanel<TlfInputSelectionWrite> title="Exact source and ADaM selection" description="Operator-controlled selection of accepted SAP/Protocol revisions and exact validated ADaM artifacts. AI cannot choose or substitute these inputs." value={query.data} isLoading={query.isLoading} error={query.error} emptyValue={EMPTY_INPUTS} isSaving={save.isPending} onReload={() => query.refetch()} onSave={async (data) => {
    const result = await save.mutateAsync({ tlfId, data })
    await Promise.all([qc.invalidateQueries({ queryKey: getGetInputSelectionQueryKey(tlfId) }), qc.invalidateQueries({ queryKey: getGetTlfAggregateQueryKey(tlfId) })])
    return result
  }} />
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
    setDraft(JSON.stringify({ standards, terminology, references, templates, ...(reaffirmation_reason ? { reaffirmation_reason } : {}) }, null, 2))
  }, [query.data])
  if (query.isError) return <ErrorState error={query.error} resourceLabel="TLF dependencies" />
  async function save() {
    try {
      await mutation.mutateAsync({ tlfId, data: JSON.parse(draft) as DependencySelectionInput })
      await Promise.all([qc.invalidateQueries({ queryKey: getGetTlfDependenciesQueryKey(tlfId) }), qc.invalidateQueries({ queryKey: getGetTlfAggregateQueryKey(tlfId) })])
      setError(null); toast.success('Dependency selection replaced.')
    } catch (caught) {
      const axiosError = caught as AxiosError
      setError(caught instanceof SyntaxError ? caught.message : stalenessAlert(axiosError) ?? parseProblem(axiosError).detail ?? axiosError.message)
    }
  }
  return <Card><CardHeader><CardTitle>Dependencies</CardTitle><CardDescription>Pin exact standards, terminology, reference, ARS, and presentation versions.</CardDescription></CardHeader><CardContent className="flex flex-col gap-4"><Textarea rows={16} className="font-mono text-xs" value={draft} onChange={(event) => setDraft(event.target.value)} />{error && <p className="text-destructive text-sm">{error}</p>}<div className="flex justify-end"><Button onClick={save} disabled={mutation.isPending}>{mutation.isPending ? <Loader2 className="animate-spin" /> : <Save />}Replace selection</Button></div></CardContent></Card>
}

async function refreshTlfAuthoring(
  queryClient: ReturnType<typeof useQueryClient>,
  tlfId: string,
  queryKey: readonly unknown[],
) {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey }),
    queryClient.invalidateQueries({ queryKey: getGetTlfAggregateQueryKey(tlfId) }),
  ])
}

export function TlfInventoryPanel({ tlfId }: { tlfId: string }) {
  const queryClient = useQueryClient()
  const { revision } = useWorkbench()
  const query = useGetInventory(tlfId, { query: { retry: false } })
  const save = usePutInventory({ request: ifMatchRequest(revision) })
  const empty: TlfOutputInventory = { schema_version: '1.0.0', outputs: [] }

  return <JsonAuthoringPanel<TlfOutputInventory>
    title="Output inventory"
    description="Create or edit the study-wide table, listing, and figure inventory manually. Output identities become the authoritative scope for later stages."
    value={query.data}
    isLoading={query.isLoading}
    error={query.error as AxiosError | null}
    emptyValue={empty}
    isSaving={save.isPending}
    onReload={() => query.refetch()}
    onSave={async (data) => {
      const result = await save.mutateAsync({ tlfId, data })
      await refreshTlfAuthoring(queryClient, tlfId, getGetInventoryQueryKey(tlfId))
      return result
    }}
  />
}

export function TlfAnalysisAuthoringPanel({ tlfId }: { tlfId: string }) {
  const queryClient = useQueryClient()
  const { revision } = useWorkbench()
  const [outputCode, setOutputCode] = React.useState('T-01')
  const inventory = useGetInventory(tlfId, { query: { retry: false } })
  const inputs = useGetInputSelection(tlfId, { query: { retry: false } })
  const shell = useGetShell(tlfId, outputCode, { query: { retry: false, enabled: !!outputCode } })
  const bindings = useGetBindings(tlfId, outputCode, { query: { retry: false, enabled: !!outputCode } })
  const assumptions = useGetAssumptions(tlfId, outputCode, { query: { retry: false, enabled: !!outputCode } })
  const ars = useGetArs(tlfId, outputCode, { query: { retry: false, enabled: !!outputCode } })
  const saveShell = usePutShell({ request: ifMatchRequest(revision) })
  const saveBindings = usePutBindings({ request: ifMatchRequest(revision) })
  const saveAssumptions = usePutAssumptions({ request: ifMatchRequest(revision) })
  const saveArs = usePutArs({ request: ifMatchRequest(revision) })
  const inventoryOutput = (inventory.data?.payload.outputs as Array<Record<string, unknown>> | undefined)?.find((item) => item.output_code === outputCode)
  const selectedDatasets = Array.isArray(inputs.data?.payload.datasets)
    ? inputs.data.payload.datasets as TlfBindings['datasets']
    : []
  const emptyShell: TlfShell = {
    schema_version: '1.0.0',
    output_code: outputCode,
    output_type: (inventoryOutput?.output_type as TlfShell['output_type']) ?? 'table',
    title: String(inventoryOutput?.title ?? ''),
    subtitle: null,
    columns: [{ id: 'value', label: 'Value', order: 1 }],
    rows: [{ id: 'row1', parent_id: null, label: 'Row 1', order: 1, leaf: true }],
    footnotes: [],
    orientation: 'portrait',
  }
  const emptyBindings: TlfBindings = { schema_version: '1.0.0', datasets: selectedDatasets, named: [] }
  const emptyAssumptions: TlfAssumptions = { schema_version: '1.0.0', items: [] }
  const emptyArs: TlfArs = { schema_version: '1.0.0', analyses: [] }

  return <div className="flex flex-col gap-6">
    <Card><CardHeader><CardTitle>Manual analysis target</CardTitle><CardDescription>Select an output declared in the current inventory, then create or edit its typed analysis contracts.</CardDescription></CardHeader><CardContent><OutputCode value={outputCode} onChange={setOutputCode} /></CardContent></Card>
    <JsonAuthoringPanel<TlfShell> title={`${outputCode} shell`} description="Author titles, display columns, hierarchical rows, footnotes, and orientation." value={shell.data} isLoading={shell.isLoading} error={shell.error as AxiosError | null} emptyValue={emptyShell} isSaving={saveShell.isPending} onReload={() => shell.refetch()} onSave={async (data) => { const result = await saveShell.mutateAsync({ tlfId, outputCode, data }); await refreshTlfAuthoring(queryClient, tlfId, getGetShellQueryKey(tlfId, outputCode)); return result }} />
    <JsonAuthoringPanel<TlfBindings> title={`${outputCode} ADaM bindings`} description="Bind the exact selected ADaM artifacts and name the population, parameter, and statistic values used by this output." value={bindings.data} isLoading={bindings.isLoading} error={bindings.error as AxiosError | null} emptyValue={emptyBindings} isSaving={saveBindings.isPending} onReload={() => bindings.refetch()} onSave={async (data) => { const result = await saveBindings.mutateAsync({ tlfId, outputCode, data }); await refreshTlfAuthoring(queryClient, tlfId, getGetBindingsQueryKey(tlfId, outputCode)); return result }} />
    <JsonAuthoringPanel<TlfAssumptions> title={`${outputCode} assumptions`} description="Record explicit analysis assumptions; leave the list empty when none are needed." value={assumptions.data} isLoading={assumptions.isLoading} error={assumptions.error as AxiosError | null} emptyValue={emptyAssumptions} isSaving={saveAssumptions.isPending} onReload={() => assumptions.refetch()} onSave={async (data) => { const result = await saveAssumptions.mutateAsync({ tlfId, outputCode, data }); await refreshTlfAuthoring(queryClient, tlfId, getGetAssumptionsQueryKey(tlfId, outputCode)); return result }} />
    <JsonAuthoringPanel<TlfArs> title={`${outputCode} ARS`} description="Map each leaf shell row to one exact dataset, population, optional parameter, and statistic binding." value={ars.data} isLoading={ars.isLoading} error={ars.error as AxiosError | null} emptyValue={emptyArs} isSaving={saveArs.isPending} onReload={() => ars.refetch()} onSave={async (data) => { const result = await saveArs.mutateAsync({ tlfId, outputCode, data }); await refreshTlfAuthoring(queryClient, tlfId, getGetArsQueryKey(tlfId, outputCode)); return result }} />
  </div>
}

export function TlfProgramPlanPanel({ tlfId }: { tlfId: string }) {
  const queryClient = useQueryClient()
  const { revision } = useWorkbench()
  const [outputCode, setOutputCode] = React.useState('T-01')
  const shell = useGetShell(tlfId, outputCode, { query: { retry: false, enabled: !!outputCode } })
  const bindings = useGetBindings(tlfId, outputCode, { query: { retry: false, enabled: !!outputCode } })
  const assumptions = useGetAssumptions(tlfId, outputCode, { query: { retry: false, enabled: !!outputCode } })
  const ars = useGetArs(tlfId, outputCode, { query: { retry: false, enabled: !!outputCode } })
  const plan = useGetProgramPlan(tlfId, outputCode, { query: { retry: false, enabled: !!outputCode } })
  const save = usePutProgramPlan({ request: ifMatchRequest(revision) })
  const empty: TlfProgramPlan = {
    schema_version: '1.0.0',
    shell_revision: shell.data?.revision ?? 1,
    bindings_revision: bindings.data?.revision ?? 1,
    assumptions_revision: assumptions.data?.revision ?? 1,
    ars_revision: ars.data?.revision ?? 1,
    output_filename: `${outputCode.toLowerCase().replaceAll('-', '_')}.csv`,
    custom_functions: [],
    steps: [],
  }

  return <div className="flex flex-col gap-6">
    <Card><CardHeader><CardTitle>Manual programming target</CardTitle><CardDescription>Select an output and author its language-neutral ProgramPlan against the current analysis revisions.</CardDescription></CardHeader><CardContent><OutputCode value={outputCode} onChange={setOutputCode} /></CardContent></Card>
    <JsonAuthoringPanel<TlfProgramPlan> title={`${outputCode} ProgramPlan`} description="Author one typed analysis step per ARS analysis. Raw language code remains limited to declared custom functions." value={plan.data} isLoading={plan.isLoading} error={plan.error as AxiosError | null} emptyValue={empty} isSaving={save.isPending} onReload={() => plan.refetch()} onSave={async (data) => { const result = await save.mutateAsync({ tlfId, outputCode, data }); await refreshTlfAuthoring(queryClient, tlfId, getGetProgramPlanQueryKey(tlfId, outputCode)); return result }} />
  </div>
}

export function TlfValidationPanel({ tlfId }: { tlfId: string }) {
  const plan = useValidateProgramPlan(); const all = useValidateTlf(); const preview = usePreviewProgramPlan()
  const [outputCode, setOutputCode] = React.useState('T-01')
  const [run, setRun] = React.useState<ValidationRunResponse | null>(null)
  const [previewResult, setPreviewResult] = React.useState<PreviewResponse | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  async function validate(action: () => Promise<ValidationRunResponse>) { try { setRun(await action()); setError(null) } catch (caught) { setError(parseProblem(caught as AxiosError).detail ?? String(caught)) } }
  return <div className="flex flex-col gap-6"><PageHeader title="Validation & Analysis IR" description="Validate one accepted portfolio output and inspect its normalized, non-editable Analysis IR." /><OutputCode value={outputCode} onChange={setOutputCode} /><div className="flex flex-wrap gap-2"><Button onClick={() => validate(() => plan.mutateAsync({ tlfId, params: { output_code: outputCode } }))}>Validate ProgramPlan</Button><Button variant="outline" onClick={() => validate(() => all.mutateAsync({ tlfId, params: { output_code: outputCode } }))}>Validate output</Button><Button variant="outline" onClick={async () => { try { setPreviewResult(await preview.mutateAsync({ tlfId, params: { output_code: outputCode } })); setError(null) } catch (caught) { setError(parseProblem(caught as AxiosError).detail ?? String(caught)) } }}>Preview IR</Button></div>{error && <p className="text-destructive text-sm">{error}</p>}{run && <><Card><CardHeader><CardTitle>Validation {run.status}</CardTitle><CardDescription><code>{run.input_fingerprint}</code></CardDescription></CardHeader></Card><IssueList issues={run.issues} /></>}{previewResult && <Card><CardHeader><CardTitle>Normalized Analysis IR</CardTitle><CardDescription>{previewResult.procedure_count} procedures · <code>{previewResult.analysis_ir_fingerprint}</code></CardDescription></CardHeader><CardContent><pre className="max-h-[34rem] overflow-auto rounded bg-muted p-4 text-xs">{JSON.stringify(previewResult.normalized_analysis_ir, null, 2)}</pre></CardContent></Card>}</div>
}

function OutputCode({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return <div className="max-w-xs space-y-2"><Label htmlFor="tlf-output-code">Output code</Label><Input id="tlf-output-code" value={value} onChange={(event) => onChange(event.target.value.toUpperCase())} /></div>
}

function BuildResult({ build }: { build: ArtifactBuildResponse }) { return <ArtifactList artifacts={build.result_artifact_ids.map((id) => ({ id }))} /> }

export function TlfBuildPanel({ tlfId }: { tlfId: string }) {
  const [outputCode, setOutputCode] = React.useState('T-01'); const [fingerprint, setFingerprint] = React.useState(''); const [backend, setBackend] = React.useState('python'); const [format, setFormat] = React.useState('pdf'); const [types, setTypes] = React.useState(''); const [operationId, setOperationId] = React.useState<string | null>(null)
  const compile = useCompileTlf({ request: idempotentRequest() }); const render = useRenderTlf({ request: idempotentRequest() }); const artifacts = useCreateTlfArtifacts({ request: idempotentRequest() })
  async function start(kind: 'compile' | 'render' | 'artifacts') {
    try {
      const result = kind === 'compile' ? await compile.mutateAsync({ tlfId, data: { backend, output_code: outputCode, expected_input_fingerprint: fingerprint } }) : kind === 'render' ? await render.mutateAsync({ tlfId, data: { format, output_code: outputCode, expected_input_fingerprint: fingerprint } }) : await artifacts.mutateAsync({ tlfId, data: { output_code: outputCode, artifact_types: types.split(',').map((value) => value.trim()).filter(Boolean), expected_input_fingerprint: fingerprint } })
      setOperationId(result.id)
    } catch (caught) { const problem = parseProblem(caught as AxiosError); toast.error(problem.title ?? 'Build could not start', { description: problem.detail }) }
  }
  return <div className="flex flex-col gap-6"><PageHeader title="Compile, render & artifacts" description="Operate on one explicit accepted portfolio output at a time." /><Card><CardContent className="grid gap-4 pt-6 md:grid-cols-2"><OutputCode value={outputCode} onChange={setOutputCode} /><div><Label>Exact input fingerprint</Label><Input value={fingerprint} onChange={(event) => setFingerprint(event.target.value)} /></div></CardContent></Card><Card><CardHeader><CardTitle>Operation</CardTitle></CardHeader><CardContent className="space-y-4"><div className="flex flex-wrap gap-3"><Select value={backend} onValueChange={setBackend}><SelectTrigger className="w-40"><SelectValue /></SelectTrigger><SelectContent>{['python','r','sas'].map((value) => <SelectItem key={value} value={value}>{value.toUpperCase()}</SelectItem>)}</SelectContent></Select><Button onClick={() => start('compile')} disabled={!fingerprint}>Compile</Button><Select value={format} onValueChange={setFormat}><SelectTrigger className="w-32"><SelectValue /></SelectTrigger><SelectContent>{['pdf','rtf','png','svg'].map((value) => <SelectItem key={value} value={value}>{value.toUpperCase()}</SelectItem>)}</SelectContent></Select><Button variant="outline" onClick={() => start('render')} disabled={!fingerprint}>Render</Button></div><div className="flex gap-3"><Input value={types} onChange={(event) => setTypes(event.target.value)} placeholder="Additional artifact types" /><Button variant="outline" onClick={() => start('artifacts')} disabled={!fingerprint || !types.trim()}>Build artifacts</Button></div><OperationRunner<ArtifactBuildResponse> operationLabel="TLF build" operationId={operationId} useGetOperation={useGetArtifactBuild} intervalMs={2000} timeoutMs={300000} onStart={() => start('compile')} startLabel="Run again" startDisabled={!fingerprint} renderResult={(result) => <BuildResult build={result} />} /></CardContent></Card></div>
}

export function TlfExecutionPanel({ tlfId }: { tlfId: string }) {
  const [draft, setDraft] = React.useState(() => JSON.stringify({ output_code: 'T-01', language: 'python', program_artifact_id: '', input_artifact_ids: [], validation_run_id: '', bindings_revision: 1, shell_revision: 1, program_plan_revision: 1, compiler_fingerprint: '', expected_input_fingerprint: '', limits: { cpu: 1, memory_mb: 1024, runtime_seconds: 300, output_bytes: 104857600 } }, null, 2)); const [runId, setRunId] = React.useState<string | null>(null); const [error, setError] = React.useState<string | null>(null); const execute = useExecuteTlf({ request: idempotentRequest() })
  async function start() { try { setRunId((await execute.mutateAsync({ tlfId, data: JSON.parse(draft) as TlfExecutionRequest })).id); setError(null) } catch (caught) { setError(caught instanceof SyntaxError ? caught.message : parseProblem(caught as AxiosError).detail ?? String(caught)) } }
  return <div className="flex flex-col gap-6"><PageHeader title="Execution" description="Execute an immutable generated program for one exact output in the isolated runner." /><div><Label htmlFor="tlf-execution">Pinned execution request</Label><Textarea id="tlf-execution" rows={20} className="mt-2 font-mono text-xs" value={draft} onChange={(event) => setDraft(event.target.value)} /></div>{error && <p className="text-destructive text-sm">{error}</p>}<OperationRunner<ExecutionRunResponse> operationLabel="TLF execution" operationId={runId} useGetOperation={useGetExecutionRun} intervalMs={2000} timeoutMs={300000} onStart={start} startLabel="Execute program" renderResult={(run) => <Card><CardHeader><CardTitle>Execution {run.status}</CardTitle></CardHeader><CardContent><ArtifactList title="Output artifacts" artifacts={run.output_artifact_ids.map((id) => ({ id }))} /></CardContent></Card>} /></div>
}
