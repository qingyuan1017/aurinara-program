import * as React from 'react'
import type { AxiosError } from 'axios'
import { useQueryClient } from '@tanstack/react-query'
import { Loader2, Play, Save } from 'lucide-react'
import { JsonAuthoringPanel } from './json-authoring-panel'
import { IssueList } from '@/components/data/issue-list'
import { ErrorState } from '@/components/data/states'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { toast } from '@/components/ui/sonner'
import type {
  AdamAdrgModel,
  AdamArtifactRequest,
  AdamDefineModel,
  AdamDerivationPlan,
  AdamExecutionRequest,
  AdamInputSelectionWrite,
  AdamSpecification,
  AggregateResponse,
  AppAdamRoutesCompileRequest,
  DependencySelectionInput,
  ValidationRunResponse,
} from '@/api/generated/model'
import {
  getGetAdamDependenciesQueryKey,
  getGetInputSelectionQueryKey,
  getGetPlanQueryKey,
  getGetSpecificationQueryKey,
  useCompileAdam,
  useCreateAdamArtifacts,
  useExecuteAdam,
  useGetAdamDependencies,
  useGetAdamLineage,
  useGetInputSelection,
  useGetPlan,
  useGetSdtmContext,
  useGetSpecification,
  useListAdamPlans,
  usePreviewAdamPlan,
  usePutInputSelection,
  usePutPlan,
  usePutSpecification,
  useReplaceAdamDependencies,
  useValidateAdam,
  useValidateAdamDataset,
  useValidateAdamPlan,
} from '@/api/generated/adam/adam'
import {
  getGetDefineQueryKey,
  useGetDefine,
  usePutDefine,
  useValidateDefine,
} from '@/api/generated/adam-define/adam-define'
import {
  getGetAdrgQueryKey,
  useGetAdrg,
  usePutAdrg,
  useValidateAdrg,
} from '@/api/generated/adam-adrg/adam-adrg'
import { idempotentRequest, ifMatchRequest } from '@/lib/requests'
import { parseProblem, stalenessAlert } from '@/lib/problems'

function ReadOnlyJson({ title, description, query }: { title: string; description: string; query: { data?: unknown; isLoading: boolean; isError: boolean; error: AxiosError | null } }) {
  if (query.isError) return <ErrorState error={query.error} resourceLabel={title.toLowerCase()} />
  return <Card><CardHeader><CardTitle>{title}</CardTitle><CardDescription>{description}</CardDescription></CardHeader><CardContent>{query.isLoading ? <Loader2 className="animate-spin" /> : <pre className="max-h-[42rem] overflow-auto rounded-md bg-muted p-4 text-xs">{JSON.stringify(query.data ?? {}, null, 2)}</pre>}</CardContent></Card>
}

function JsonAction<T extends object>({ title, description, initialValue, pending, onRun }: { title: string; description: string; initialValue: T; pending: boolean; onRun: (payload: T) => Promise<unknown> }) {
  const [draft, setDraft] = React.useState(JSON.stringify(initialValue, null, 2))
  const [result, setResult] = React.useState<unknown>()
  const [error, setError] = React.useState<string | null>(null)
  async function run() { try { const payload = JSON.parse(draft); setResult(await onRun(payload)); setError(null) } catch (caught) { if (caught instanceof SyntaxError) setError(caught.message); else { const axiosError = caught as AxiosError; setError(parseProblem(axiosError).detail ?? axiosError.message) } } }
  return <Card><CardHeader><CardTitle>{title}</CardTitle><CardDescription>{description}</CardDescription></CardHeader><CardContent className="flex flex-col gap-4"><Textarea rows={14} className="font-mono text-xs" value={draft} onChange={(event) => setDraft(event.target.value)} />{error && <p className="text-destructive text-sm" role="alert">{error}</p>}<div><Button disabled={pending} onClick={run}>{pending ? <Loader2 className="animate-spin" /> : <Play />} Run</Button></div>{result !== undefined && <pre className="max-h-80 overflow-auto rounded-md bg-muted p-4 text-xs">{JSON.stringify(result, null, 2)}</pre>}</CardContent></Card>
}

export function AdamDependenciesPanel({ aggregate }: { aggregate: AggregateResponse }) {
  const qc = useQueryClient(); const query = useGetAdamDependencies(aggregate.id); const saveMutation = useReplaceAdamDependencies({ request: ifMatchRequest(aggregate.revision) })
  const [draft, setDraft] = React.useState('{}'); const [error, setError] = React.useState<string | null>(null)
  React.useEffect(() => { if (query.data) { const { standards, terminology, references, templates, reaffirmation_reason } = query.data; setDraft(JSON.stringify({ standards, terminology, references, templates, ...(reaffirmation_reason ? { reaffirmation_reason } : {}) }, null, 2)) } }, [query.data])
  if (query.isError) return <ErrorState error={query.error} resourceLabel="ADaM dependencies" />
  async function save() { try { await saveMutation.mutateAsync({ adamId: aggregate.id, data: JSON.parse(draft) as DependencySelectionInput }); await qc.invalidateQueries({ queryKey: getGetAdamDependenciesQueryKey(aggregate.id) }); setError(null); toast.success('ADaM dependency selection replaced.') } catch (caught) { if (caught instanceof SyntaxError) setError(caught.message); else { const e = caught as AxiosError; setError(stalenessAlert(e) ?? parseProblem(e).detail ?? e.message) } } }
  return <Card><CardHeader><CardTitle>Dependencies</CardTitle><CardDescription>Pin exact shared provider revisions for this ADaM aggregate.</CardDescription></CardHeader><CardContent className="flex flex-col gap-4"><Textarea rows={20} className="font-mono text-xs" value={draft} onChange={(e) => setDraft(e.target.value)} />{query.data && <p className="text-muted-foreground text-xs">Revision {query.data.revision} · {query.data.state} · <code>{query.data.fingerprint}</code></p>}{error && <p className="text-destructive text-sm">{error}</p>}<div className="flex justify-end"><Button onClick={save} disabled={saveMutation.isPending}>{saveMutation.isPending ? <Loader2 className="animate-spin" /> : <Save />} Replace selection</Button></div></CardContent></Card>
}

export function AdamInputSelectionPanel({ aggregate }: { aggregate: AggregateResponse }) {
  const qc = useQueryClient(); const query = useGetInputSelection(aggregate.id); const save = usePutInputSelection({ request: ifMatchRequest(query.data?.revision ?? aggregate.revision) })
  const empty: AdamInputSelectionWrite = { sdtm_id: '', sdtm_revision: 1, validation_run_id: '', xpt_artifacts: [], sdtm_dependency_fingerprint: '' }
  return <JsonAuthoringPanel<AdamInputSelectionWrite> title="SDTM input selection" description="Select exact validated SDTM XPT artifacts and the dependency fingerprint they were built from." value={query.data} isLoading={query.isLoading} error={query.error} emptyValue={empty} isSaving={save.isPending} onReload={() => query.refetch()} onSave={async (data) => { const result = await save.mutateAsync({ adamId: aggregate.id, data }); await qc.invalidateQueries({ queryKey: getGetInputSelectionQueryKey(aggregate.id) }); return result }} />
}

export function AdamSpecificationPanel({ aggregate }: { aggregate: AggregateResponse }) {
  const qc = useQueryClient(); const query = useGetSpecification(aggregate.id); const save = usePutSpecification({ request: ifMatchRequest(query.data?.revision ?? aggregate.revision) })
  const empty: AdamSpecification = { schema_version: '1.0.0', datasets: [], methods: [], trace_targets: [] }
  return <JsonAuthoringPanel<AdamSpecification> title="ADaM Specification" description="Author all datasets, variables, parameters, origins, methods, terminology bindings, and trace targets in one versioned contract." value={query.data} isLoading={query.isLoading} error={query.error} emptyValue={empty} isSaving={save.isPending} onReload={() => query.refetch()} onSave={async (data) => { const result = await save.mutateAsync({ adamId: aggregate.id, data }); await qc.invalidateQueries({ queryKey: getGetSpecificationQueryKey(aggregate.id) }); return result }} />
}

export function AdamPlanPanel({ aggregate }: { aggregate: AggregateResponse }) {
  const qc = useQueryClient(); const heads = useListAdamPlans(aggregate.id); const [dataset, setDataset] = React.useState(''); const query = useGetPlan(aggregate.id, dataset, { query: { enabled: !!dataset } }); const save = usePutPlan({ request: ifMatchRequest(query.data?.revision ?? aggregate.revision) }); const validate = useValidateAdamPlan(); const preview = usePreviewAdamPlan(); const [result, setResult] = React.useState<unknown>()
  const empty: AdamDerivationPlan = { schema_version: '1.1.0', dataset: dataset || 'ADSL', specification_revision: 1, input_selection_revision: 1, custom_functions: [], nodes: [], edges: [] }
  return <div className="flex flex-col gap-6"><Card><CardHeader><CardTitle>Per-dataset plan</CardTitle><CardDescription>Select an authored dataset or enter the code for a new plan.</CardDescription></CardHeader><CardContent className="flex flex-col gap-3"><div className="flex flex-wrap gap-2">{heads.data?.items.map((head) => <Button key={head.id} size="sm" variant={dataset === head.dataset ? 'default' : 'outline'} onClick={() => setDataset(head.dataset)}>{head.dataset} · r{head.revision} · {head.alignment_state}</Button>)}</div><Label htmlFor="adam-dataset">Dataset code</Label><Input id="adam-dataset" value={dataset} onChange={(event) => setDataset(event.target.value.toUpperCase())} placeholder="ADSL" /></CardContent></Card>{dataset && <><JsonAuthoringPanel<AdamDerivationPlan> title={`${dataset} Derivation Plan`} description="Author the typed SDTM/predecessor-to-analysis DAG and optional per-language custom functions. Missing language bodies compile as non-executable TODO programs." value={query.data} isLoading={query.isLoading} error={query.error} emptyValue={{ ...empty, dataset }} isSaving={save.isPending} onReload={() => query.refetch()} onSave={async (data) => { const response = await save.mutateAsync({ adamId: aggregate.id, datasetCode: dataset, data }); await qc.invalidateQueries({ queryKey: getGetPlanQueryKey(aggregate.id, dataset) }); return response }} /><div className="flex gap-2"><Button variant="outline" disabled={validate.isPending} onClick={async () => setResult(await validate.mutateAsync({ adamId: aggregate.id, datasetCode: dataset }))}>Validate plan</Button><Button variant="outline" disabled={preview.isPending} onClick={async () => setResult(await preview.mutateAsync({ adamId: aggregate.id, datasetCode: dataset, data: { limit: 100 } }))}>Preview 100 rows</Button></div>{result !== undefined && <pre className="max-h-96 overflow-auto rounded-md bg-muted p-4 text-xs">{JSON.stringify(result, null, 2)}</pre>}</>}</div>
}

export function AdamContextPanel({ aggregate }: { aggregate: AggregateResponse }) {
  const context = useGetSdtmContext(aggregate.id); const lineage = useGetAdamLineage(aggregate.id)
  return <div className="grid gap-6 xl:grid-cols-2"><ReadOnlyJson title="Pinned SDTM context" description="Read-only context resolved from the exact input selection." query={context} /><ReadOnlyJson title="ADaM lineage" description="Resolved origins and cross-module lineage for the authored specification and plans." query={lineage} /></div>
}

export function AdamValidationPanel({ aggregate }: { aggregate: AggregateResponse }) {
  const all = useValidateAdam(); const one = useValidateAdamDataset(); const [dataset, setDataset] = React.useState(''); const [run, setRun] = React.useState<ValidationRunResponse | null>(null)
  return <div className="flex flex-col gap-4"><Card><CardHeader><CardTitle>Validation snapshots</CardTitle><CardDescription>Validate the complete aggregate or one aligned dataset.</CardDescription></CardHeader><CardContent className="flex flex-wrap items-end gap-3"><Button disabled={all.isPending} onClick={async () => setRun(await all.mutateAsync({ adamId: aggregate.id }))}>Validate all datasets</Button><div className="flex flex-col gap-2"><Label htmlFor="validate-dataset">Dataset</Label><Input id="validate-dataset" value={dataset} onChange={(e) => setDataset(e.target.value.toUpperCase())} placeholder="ADSL" /></div><Button variant="outline" disabled={!dataset || one.isPending} onClick={async () => setRun(await one.mutateAsync({ adamId: aggregate.id, datasetCode: dataset }))}>Validate dataset</Button></CardContent></Card>{run && <><Card><CardHeader><CardTitle>{run.status}</CardTitle><CardDescription>{run.error_count} errors · {run.warning_count} warnings · <code>{run.input_fingerprint}</code></CardDescription></CardHeader></Card><IssueList issues={run.issues} /></>}</div>
}

export function AdamOperationsPanel({ aggregate }: { aggregate: AggregateResponse }) {
  const buildKey = React.useMemo(() => idempotentRequest(), []); const compileKey = React.useMemo(() => idempotentRequest(), []); const executeKey = React.useMemo(() => idempotentRequest(), [])
  const build = useCreateAdamArtifacts({ request: buildKey }); const compile = useCompileAdam({ request: compileKey }); const execute = useExecuteAdam({ request: executeKey })
  return <div className="grid gap-6 xl:grid-cols-3"><JsonAction<AdamArtifactRequest> title="Build artifacts" description="Build immutable outputs from exact validated inputs." initialValue={{ artifact_types: ['adam_xpt'], expected_input_fingerprint: '', dataset_code: 'ADSL' }} pending={build.isPending} onRun={(data) => build.mutateAsync({ adamId: aggregate.id, data })} /><JsonAction<AppAdamRoutesCompileRequest> title="Compile program" description="Compile a deterministic Python, R, or SAS program for one dataset." initialValue={{ backend: 'python', expected_input_fingerprint: '', dataset_code: 'ADSL' }} pending={compile.isPending} onRun={(data) => compile.mutateAsync({ adamId: aggregate.id, data })} /><JsonAction<AdamExecutionRequest> title="Execute program" description="Submit an exact immutable program and inputs to the isolated execution service." initialValue={{ language: 'python', program_artifact_id: '', input_artifact_ids: [], validation_run_id: '', input_selection_revision: 1, source_specification_revision: 1, source_plan_revision: 1, compiler_fingerprint: '', expected_input_fingerprint: '', limits: { cpu: 1, memory_mb: 1024, runtime_seconds: 300, output_bytes: 104857600 } }} pending={execute.isPending} onRun={(data) => execute.mutateAsync({ adamId: aggregate.id, data })} /></div>
}

export function AdamDefinePanel({ aggregate }: { aggregate: AggregateResponse }) {
  const qc = useQueryClient(); const query = useGetDefine(aggregate.id); const save = usePutDefine({ request: ifMatchRequest(query.data?.revision ?? aggregate.revision) }); const validate = useValidateDefine(); const empty: AdamDefineModel = { schema_version: '1.0.0', specification_revision: 1, input_selection_revision: 1, study_oid: '', metadata_version_oid: '', name: '', standard_name: 'ADaM-IG', standard_version: '', output_artifact_ids: [], datasets: [], methods: [], leaves: [] }
  return <div className="flex flex-col gap-4"><JsonAuthoringPanel<AdamDefineModel> title="ADaM Define metadata" description="Maintain version-neutral Define-XML metadata over exact authored and output evidence." value={query.data} isLoading={query.isLoading} error={query.error} emptyValue={empty} isSaving={save.isPending} onReload={() => query.refetch()} onSave={async (data) => { const response = await save.mutateAsync({ adamId: aggregate.id, data }); await qc.invalidateQueries({ queryKey: getGetDefineQueryKey(aggregate.id) }); return response }} /><Button className="w-fit" variant="outline" disabled={validate.isPending} onClick={async () => { const response = await validate.mutateAsync({ adamId: aggregate.id }); toast.success(`Define validation: ${response.status}`) }}>Validate Define</Button></div>
}

export function AdamAdrgPanel({ aggregate }: { aggregate: AggregateResponse }) {
  const qc = useQueryClient(); const query = useGetAdrg(aggregate.id); const save = usePutAdrg({ request: ifMatchRequest(query.data?.revision ?? aggregate.revision) }); const validate = useValidateAdrg(); const empty: AdamAdrgModel = { schema_version: '1.0.0', title: '', version: '', specification_revision: 1, input_selection_revision: 1, plan_revision: 1, define_revision: 1, reconciliation_run_id: '', output_artifact_ids: [], dataset_facts: [], execution_facts: [], narrative_sections: [] }
  return <div className="flex flex-col gap-4"><JsonAuthoringPanel<AdamAdrgModel> title="ADRG" description="Maintain immutable dataset/execution facts separately from manually authored reviewer-guide narrative." value={query.data} isLoading={query.isLoading} error={query.error} emptyValue={empty} isSaving={save.isPending} onReload={() => query.refetch()} onSave={async (data) => { const response = await save.mutateAsync({ adamId: aggregate.id, data }); await qc.invalidateQueries({ queryKey: getGetAdrgQueryKey(aggregate.id) }); return response }} /><Button className="w-fit" variant="outline" disabled={validate.isPending} onClick={async () => { const response = await validate.mutateAsync({ adamId: aggregate.id }); toast.success(`ADRG validation: ${response.status}`) }}>Validate ADRG</Button></div>
}
