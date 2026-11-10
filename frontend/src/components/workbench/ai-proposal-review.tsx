import { useMemo, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { AxiosError } from 'axios'
import { Bot, Check, CircleAlert, Loader2, ShieldCheck, X } from 'lucide-react'
import { toast } from 'sonner'
import { listAgents } from '@/api/generated/ai-proposals/ai-proposals'
import {
  createProposal as createAdamProposal,
  listProposals as listAdamProposals,
  postAcceptAdamProposal,
  postRejectAdamProposal,
  postRequestRevisionAdamProposal,
} from '@/api/generated/adam/adam'
import type { ProposalResponse } from '@/api/generated/model'
import {
  createProposal as createTlfProposal,
  listProposals as listTlfProposals,
  postAcceptTlfProposal,
  postRejectTlfProposal,
  postRequestRevisionTlfProposal,
} from '@/api/generated/tlf/tlf'
import { Badge } from '@/components/ui/badge'
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
import { Textarea } from '@/components/ui/textarea'
import { useWorkbench } from '@/components/workbench/workbench-context'
import { parseProblem } from '@/lib/problems'

type Module = 'adam' | 'tlf'
type Decision = 'accepted' | 'rejected' | 'revision_requested'

interface TargetField {
  key: string
  label: string
  placeholder?: string
  defaultValue?: string
  uppercase?: boolean
}

interface Props {
  module: Module
  aggregateId: string
  proposalType: string
  title: string
  description: string
  targetFields?: TargetField[]
  manualEditor?: ReactNode
}

const api = {
  adam: {
    create: createAdamProposal,
    list: listAdamProposals,
    accept: postAcceptAdamProposal,
    reject: postRejectAdamProposal,
    revise: postRequestRevisionAdamProposal,
  },
  tlf: {
    create: createTlfProposal,
    list: listTlfProposals,
    accept: postAcceptTlfProposal,
    reject: postRejectTlfProposal,
    revise: postRequestRevisionTlfProposal,
  },
}

function errorMessage(error: unknown) {
  const problem = parseProblem(error as AxiosError)
  return problem.detail ?? (error instanceof Error ? error.message : 'The operation failed.')
}

function statusVariant(status: ProposalResponse['status']) {
  if (status === 'accepted') return 'default' as const
  if (status === 'rejected' || status === 'failed') return 'destructive' as const
  if (status === 'review_required') return 'secondary' as const
  return 'outline' as const
}

function readable(value: string) {
  return value.replaceAll('_', ' ')
}

function platformAgentLabel(proposal: ProposalResponse) {
  const name = proposal.generation_parameters.platform_agent_name
  const revision = proposal.generation_parameters.platform_agent_revision
  if (typeof name === 'string' && typeof revision === 'number') {
    return `${name} · revision ${revision}`
  }
  return 'Platform agent selection retained as evidence'
}

function StructuredProposal({ proposal }: { proposal: ProposalResponse }) {
  const content = proposal.payload?.proposal as Record<string, unknown> | undefined
  const outputs = Array.isArray(content?.outputs)
    ? (content.outputs as Array<Record<string, unknown>>)
    : null
  const datasets = Array.isArray(content?.datasets)
    ? (content.datasets as Array<Record<string, unknown>>)
    : null
  const nodes = Array.isArray(content?.nodes)
    ? (content.nodes as Array<Record<string, unknown>>)
    : null

  return (
    <div className="space-y-4">
      {outputs && (
        <div className="grid gap-3 lg:grid-cols-2">
          {outputs.map((output, index) => {
            const shell = output.shell as Record<string, unknown> | undefined
            const value = shell ?? output
            const code = String(output.output_code ?? value.output_code ?? `Output ${index + 1}`)
            return (
              <Card key={`${code}-${index}`} className="bg-muted/20">
                <CardHeader className="pb-3">
                  <div className="flex items-center justify-between gap-3">
                    <CardTitle className="font-mono text-sm">{code}</CardTitle>
                    {value.output_type ? <Badge variant="outline">{String(value.output_type)}</Badge> : null}
                  </div>
                  <CardDescription>{String(value.title ?? 'Programming proposal')}</CardDescription>
                </CardHeader>
                <CardContent className="space-y-2 text-xs">
                  {value.basis ? <p><strong>Basis:</strong> {String(value.basis)}</p> : null}
                  {value.source_reference ? <p><strong>Source:</strong> {String(value.source_reference)}</p> : null}
                  {Array.isArray(value.blocking_items) && value.blocking_items.length > 0 ? (
                    <p className="text-amber-700"><strong>Blockers:</strong> {value.blocking_items.join('; ')}</p>
                  ) : null}
                  <details><summary className="cursor-pointer font-medium">Inspect typed content</summary><pre className="mt-2 max-h-80 overflow-auto rounded bg-muted p-3">{JSON.stringify(output, null, 2)}</pre></details>
                </CardContent>
              </Card>
            )
          })}
        </div>
      )}
      {datasets && (
        <div className="grid gap-3 lg:grid-cols-2">
          {datasets.map((dataset, index) => (
            <Card key={String(dataset.code ?? index)} className="bg-muted/20">
              <CardHeader className="pb-3">
                <CardTitle className="font-mono text-sm">{String(dataset.code ?? `Dataset ${index + 1}`)}</CardTitle>
                <CardDescription>{String(dataset.label ?? dataset.description ?? '')}</CardDescription>
              </CardHeader>
              <CardContent className="text-xs">{Array.isArray(dataset.variables) ? `${dataset.variables.length} variables` : 'Dataset metadata'}<details><summary className="mt-2 cursor-pointer font-medium">Inspect metadata</summary><pre className="mt-2 max-h-80 overflow-auto rounded bg-muted p-3">{JSON.stringify(dataset, null, 2)}</pre></details></CardContent>
            </Card>
          ))}
        </div>
      )}
      {nodes && <p className="text-sm">Typed derivation graph: {nodes.length} nodes · {Array.isArray(content?.edges) ? content.edges.length : 0} edges</p>}
      {!outputs && !datasets && <pre className="max-h-[36rem] overflow-auto rounded-md bg-muted p-4 text-xs">{JSON.stringify(content, null, 2)}</pre>}
    </div>
  )
}

export function AiProposalReview({
  module,
  aggregateId,
  proposalType,
  title,
  description,
  targetFields = [],
  manualEditor,
}: Props) {
  const { aggregate, revision } = useWorkbench()
  const queryClient = useQueryClient()
  const selectedApi = api[module]
  const [targets, setTargets] = useState<Record<string, string>>(() =>
    Object.fromEntries(targetFields.map((field) => [field.key, field.defaultValue ?? ''])),
  )
  const [guidance, setGuidance] = useState('')
  const [selectedAgentId, setSelectedAgentId] = useState('')
  const [rationale, setRationale] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const queryKey = [module, aggregateId, 'proposals'] as const
  const proposals = useQuery({
    queryKey,
    queryFn: () => selectedApi.list(aggregateId),
    refetchInterval: 3_000,
  })
  const agents = useQuery({ queryKey: ['assistance', 'agents'], queryFn: () => listAgents() })
  const activeAgentId = selectedAgentId || agents.data?.[0]?.id || ''
  const items = useMemo(
    () => (proposals.data?.items ?? []).filter((item) => item.proposal_type === proposalType),
    [proposalType, proposals.data?.items],
  )
  const selected = items.find((item) => item.id === selectedId) ?? items[0] ?? null

  const create = useMutation({
    mutationFn: () => selectedApi.create(aggregateId, {
      agent_id: activeAgentId,
      proposal_type: proposalType,
      target: Object.fromEntries(Object.entries(targets).filter(([, value]) => value.trim())),
      guidance: guidance.trim() || null,
    }, { headers: { 'Idempotency-Key': crypto.randomUUID() } }),
    onSuccess: async (proposal) => {
      setSelectedId(proposal.id)
      await queryClient.invalidateQueries({ queryKey })
      toast.success('AI proposal queued for generation.')
    },
    onError: (error) => toast.error(errorMessage(error)),
  })
  const decide = useMutation({
    mutationFn: ({ proposal, decision }: { proposal: ProposalResponse; decision: Decision }) => {
      const options = { headers: { 'If-Match': `"revision-${revision}"`, 'Idempotency-Key': crypto.randomUUID() } }
      const body = { rationale: rationale.trim() }
      if (decision === 'accepted') return selectedApi.accept(aggregateId, proposal.id, body, options)
      if (decision === 'rejected') return selectedApi.reject(aggregateId, proposal.id, body, options)
      return selectedApi.revise(aggregateId, proposal.id, body, options)
    },
    onSuccess: async () => {
      setRationale('')
      await queryClient.invalidateQueries()
      toast.success('Reviewer decision recorded.')
    },
    onError: (error) => toast.error(errorMessage(error)),
  })

  return (
    <div className="flex flex-col gap-6">
      {manualEditor ? (
        <div className="space-y-3">
          <div>
            <h2 className="text-lg font-semibold">Manual authoring</h2>
            <p className="text-sm text-muted-foreground">
              Create from scratch or edit the current typed content directly. The same
              validation, concurrency, lineage, and staleness rules apply.
            </p>
          </div>
          {manualEditor}
        </div>
      ) : null}

      <div className="border-t pt-6">
        <div className="mb-3">
          <h2 className="text-lg font-semibold">AI proposal and human review</h2>
          <p className="text-sm text-muted-foreground">
            Use the agent when you want an evidence-grounded draft instead of authoring manually.
          </p>
        </div>
      <Card className="border-primary/25 bg-gradient-to-br from-primary/10 via-card to-card">
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div><div className="flex items-center gap-2"><Bot className="size-5 text-primary" /><CardTitle>{title}</CardTitle><Badge variant="outline">AI proposes · human decides</Badge></div><CardDescription className="mt-2">{description}</CardDescription></div>
            <span className="flex items-center gap-2 text-xs text-muted-foreground"><ShieldCheck className="size-4 text-emerald-600" />Exact base revision {aggregate.revision}</span>
          </div>
        </CardHeader>
        <CardContent className="grid gap-4 lg:grid-cols-[repeat(auto-fit,minmax(12rem,1fr))_minmax(16rem,2fr)_auto] lg:items-end">
          <div className="space-y-2">
            <Label htmlFor={`${proposalType}-agent`}>Platform agent</Label>
            <select
              id={`${proposalType}-agent`}
              className="border-input h-9 w-full rounded-md border bg-transparent px-3 text-sm"
              value={activeAgentId}
              onChange={(event) => setSelectedAgentId(event.target.value)}
            >
              {!activeAgentId ? <option value="">No clinical agents available</option> : null}
              {agents.data?.map((agent) => (
                <option key={agent.id} value={agent.id}>{agent.name} · revision {agent.revision}</option>
              ))}
            </select>
            {agents.isError ? <p className="text-xs text-destructive">Agent catalog is unavailable.</p> : null}
          </div>
          {targetFields.map((field) => <div className="space-y-2" key={field.key}><Label htmlFor={`${proposalType}-${field.key}`}>{field.label}</Label><Input id={`${proposalType}-${field.key}`} value={targets[field.key] ?? ''} placeholder={field.placeholder} onChange={(event) => setTargets((current) => ({ ...current, [field.key]: field.uppercase ? event.target.value.toUpperCase() : event.target.value }))} /></div>)}
          <div className="space-y-2"><Label htmlFor={`${proposalType}-guidance`}>Reviewer guidance</Label><Input id={`${proposalType}-guidance`} value={guidance} onChange={(event) => setGuidance(event.target.value)} placeholder="Study-specific constraints or requested focus" /></div>
          <Button onClick={() => create.mutate()} disabled={create.isPending || !activeAgentId || targetFields.some((field) => !(targets[field.key] ?? '').trim())}>{create.isPending ? <Loader2 className="animate-spin" /> : <Bot />}Generate proposal</Button>
        </CardContent>
      </Card>
      </div>

      <div className="grid gap-6 xl:grid-cols-[20rem_minmax(0,1fr)]">
        <Card><CardHeader><CardTitle className="text-base">Proposal history</CardTitle><CardDescription>Immutable attempts and reviewer outcomes.</CardDescription></CardHeader><CardContent className="space-y-2">{proposals.isLoading ? <Loader2 className="animate-spin" /> : items.length === 0 ? <p className="text-sm text-muted-foreground">No proposal requested yet.</p> : items.map((item) => <button type="button" key={item.id} onClick={() => setSelectedId(item.id)} className={`w-full rounded-lg border p-3 text-left hover:bg-muted ${selected?.id === item.id ? 'border-primary bg-primary/5' : ''}`}><div className="flex items-center justify-between"><span className="font-mono text-xs">{item.id.slice(0, 8)}</span><Badge variant={statusVariant(item.status)}>{readable(item.status)}</Badge></div><p className="mt-2 text-xs text-muted-foreground">Base r{item.base_revision} · {new Date(item.created_at).toLocaleString()}</p></button>)}</CardContent></Card>
        <div className="space-y-6">
          {!selected ? <Card><CardContent className="py-10 text-center text-sm text-muted-foreground">Generate a proposal to begin review.</CardContent></Card> : <>
            <Card><CardHeader><div className="flex flex-wrap items-center justify-between gap-2"><CardTitle className="text-base">Typed proposal</CardTitle><Badge variant={statusVariant(selected.status)}>{readable(selected.status)}</Badge></div><CardDescription>{platformAgentLabel(selected)} · instruction {selected.instruction_version}</CardDescription></CardHeader><CardContent>{selected.status === 'queued' || selected.status === 'running' ? <div className="flex items-center gap-2 text-sm"><Loader2 className="animate-spin" />Generation is in progress.</div> : selected.failure ? <p className="text-destructive text-sm">{String(selected.failure.detail ?? 'Generation failed.')}</p> : <StructuredProposal proposal={selected} />}</CardContent></Card>
            {selected.payload && <div className="grid gap-4 md:grid-cols-2"><EvidenceCard title="Assumptions" values={selected.assumptions} /><EvidenceCard title="Unresolved items" values={selected.unresolved_items} warning /><EvidenceCard title="Evidence references" values={selected.evidence_references} /><EvidenceCard title="Model limitations" values={selected.model_limitations} warning /></div>}
            {selected.validation_issues.length > 0 && <Card className="border-amber-500/40"><CardHeader><CardTitle className="flex items-center gap-2 text-base"><CircleAlert className="size-4" />Deterministic findings</CardTitle></CardHeader><CardContent><pre className="overflow-auto text-xs">{JSON.stringify(selected.validation_issues, null, 2)}</pre></CardContent></Card>}
            {selected.status === 'review_required' && <Card><CardHeader><CardTitle className="text-base">Human decision</CardTitle><CardDescription>Rationale is permanent review evidence. Request revision instead of editing AI content.</CardDescription></CardHeader><CardContent className="space-y-4"><Textarea value={rationale} onChange={(event) => setRationale(event.target.value)} placeholder="Required reviewer rationale or revision guidance" /><div className="flex flex-wrap gap-2"><Button onClick={() => decide.mutate({ proposal: selected, decision: 'accepted' })} disabled={!rationale.trim() || decide.isPending}><Check />Accept</Button><Button variant="outline" onClick={() => decide.mutate({ proposal: selected, decision: 'revision_requested' })} disabled={!rationale.trim() || decide.isPending}><Bot />Request revision</Button><Button variant="destructive" onClick={() => decide.mutate({ proposal: selected, decision: 'rejected' })} disabled={!rationale.trim() || decide.isPending}><X />Reject</Button></div></CardContent></Card>}
          </>}
        </div>
      </div>
    </div>
  )
}

function EvidenceCard({ title, values, warning = false }: { title: string; values: string[]; warning?: boolean }) {
  return <Card className={warning ? 'border-amber-500/30' : ''}><CardHeader className="pb-2"><CardTitle className="text-sm">{title}</CardTitle></CardHeader><CardContent>{values.length === 0 ? <p className="text-xs text-muted-foreground">None reported.</p> : <ul className="list-disc space-y-1 pl-4 text-xs">{values.map((value, index) => <li key={`${value}-${index}`}>{value}</li>)}</ul>}</CardContent></Card>
}
