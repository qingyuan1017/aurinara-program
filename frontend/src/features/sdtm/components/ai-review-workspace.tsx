import { useMemo, useState, type ReactNode } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import type { AxiosError } from 'axios'
import {
  Activity,
  ArrowRight,
  Bot,
  Check,
  CircleAlert,
  Clock3,
  FileDiff,
  Loader2,
  MessageSquareText,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  X,
} from 'lucide-react'
import { toast } from 'sonner'
import { useListAgents } from '@/api/generated/ai-proposals/ai-proposals'
import {
  createProposal,
  getListProposalsQueryKey,
  postAcceptProposal,
  postRejectProposal,
  postRequestProposalRevision,
  useListProposals,
} from '@/api/generated/sdtm/sdtm'
import type { ProposalResponse } from '@/api/generated/model'
import { IssueList } from '@/components/data/issue-list'
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
import { Separator } from '@/components/ui/separator'
import { Textarea } from '@/components/ui/textarea'
import { useWorkbench } from '@/components/workbench/workbench-context'
import { parseProblem } from '@/lib/problems'

export type SdtmProposalType =
  | 'sdtm_specification'
  | 'sdtm_domain_mapping'
  | 'sdtm_variable_mapping'
  | 'sdtm_program'
  | 'sdtm_define'
  | 'sdtm_csdrg'

interface AiReviewWorkspaceProps {
  sdtmId: string
  proposalType: SdtmProposalType
  title: string
  description: string
  needsDomain?: boolean
  needsLanguage?: boolean
  reviewPrelude?: ReactNode
  reviewEpilogue?: ReactNode
}

interface SdtmStageWorkspaceProps {
  title: string
  description: string
  agentMessage: string
  actionLabel: string
  onAction: () => void
  children: ReactNode
  unframed?: boolean
}

type Decision = 'accepted' | 'rejected' | 'revision_requested'

function statusVariant(status: ProposalResponse['status']) {
  if (status === 'accepted') return 'default' as const
  if (status === 'failed' || status === 'rejected') return 'destructive' as const
  if (status === 'review_required') return 'secondary' as const
  return 'outline' as const
}

function readableStatus(status: string) {
  return status.replaceAll('_', ' ')
}

function errorMessage(error: unknown) {
  const problem = parseProblem(error as AxiosError)
  return problem?.detail ?? (error instanceof Error ? error.message : 'The operation failed.')
}

function platformAgentLabel(proposal: ProposalResponse) {
  const name = proposal.generation_parameters.platform_agent_name
  const revision = proposal.generation_parameters.platform_agent_revision
  if (typeof name === 'string' && typeof revision === 'number') {
    return `${name} · revision ${revision}`
  }
  return 'Platform agent selection retained as evidence.'
}

export function AiReviewWorkspace({
  sdtmId,
  proposalType,
  title,
  description,
  needsDomain = false,
  needsLanguage = false,
  reviewPrelude,
  reviewEpilogue,
}: AiReviewWorkspaceProps) {
  const { aggregate, revision } = useWorkbench()
  const queryClient = useQueryClient()
  const proposals = useListProposals(sdtmId, {
    query: { refetchInterval: 3_000 },
  })
  const agents = useListAgents()
  const [domain, setDomain] = useState('DM')
  const [language, setLanguage] = useState('python')
  const [guidance, setGuidance] = useState('')
  const [selectedAgentId, setSelectedAgentId] = useState('')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [rationale, setRationale] = useState('')

  const items = useMemo(
    () =>
      (proposals.data?.items ?? []).filter(
        (proposal) => proposal.proposal_type === proposalType,
      ),
    [proposalType, proposals.data?.items],
  )
  const selected =
    items.find((proposal) => proposal.id === selectedId) ?? items[0] ?? null
  const activeAgentId = selectedAgentId || agents.data?.[0]?.id || ''

  const create = useMutation({
    mutationFn: () =>
      createProposal(
        sdtmId,
        {
          agent_id: activeAgentId,
          proposal_type: proposalType,
          target: {
            ...(needsDomain ? { domain: domain.trim().toUpperCase() } : {}),
            ...(needsLanguage ? { language } : {}),
          },
          guidance: guidance.trim() || null,
        },
        {
          headers: {
            'Content-Type': 'application/json',
            'Idempotency-Key': crypto.randomUUID(),
          },
        },
      ),
    onSuccess: async (proposal) => {
      setSelectedId(proposal.id)
      setGuidance('')
      await queryClient.invalidateQueries({
        queryKey: getListProposalsQueryKey(sdtmId),
      })
      toast.success('AI proposal queued for generation.')
    },
    onError: (error) => toast.error(errorMessage(error)),
  })

  const decide = useMutation({
    mutationFn: async ({ proposal, decision }: { proposal: ProposalResponse; decision: Decision }) => {
      const request = {
        headers: {
          'Content-Type': 'application/json',
          'If-Match': `"revision-${revision}"`,
          'Idempotency-Key': crypto.randomUUID(),
        },
      }
      const body = { rationale: rationale.trim() }
      if (decision === 'accepted') {
        return postAcceptProposal(sdtmId, proposal.id, body, request)
      }
      if (decision === 'rejected') {
        return postRejectProposal(sdtmId, proposal.id, body, request)
      }
      return postRequestProposalRevision(sdtmId, proposal.id, body, request)
    },
    onSuccess: async (proposal) => {
      setRationale('')
      await queryClient.invalidateQueries()
      toast.success(`Proposal ${readableStatus(proposal.status)}.`)
    },
    onError: (error) => toast.error(errorMessage(error)),
  })

  const agentIsActive =
    create.isPending || selected?.status === 'queued' || selected?.status === 'running'
  const specificationSummary =
    proposalType === 'sdtm_specification' && selected?.payload
      ? summarizeSpecification(selected.payload)
      : null
  const evidenceSections = selected
    ? [
        { title: 'Assumptions', items: selected.assumptions },
        { title: 'Unresolved items', items: selected.unresolved_items },
        { title: 'Evidence references', items: selected.evidence_references },
        { title: 'Model limitations', items: selected.model_limitations },
      ].filter((section) => section.items.length > 0)
    : []

  return (
    <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_19rem] 2xl:grid-cols-[minmax(0,1fr)_22rem]">
      <main className="min-w-0 space-y-6">
        {reviewPrelude}
        <Card className="overflow-hidden">
          <CardHeader className="border-b bg-muted/30">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="space-y-2">
                <div className="flex flex-wrap items-center gap-2">
                  <CardTitle>{title}</CardTitle>
                  <Badge variant="outline">Human review</Badge>
                </div>
                <CardDescription className="max-w-3xl">{description}</CardDescription>
              </div>
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <ShieldCheck className="size-4 text-emerald-600" />
                Exact base revision {aggregate.revision}
              </div>
            </div>
          </CardHeader>

          <CardContent className="flex flex-col gap-5 pt-6">
            {!selected ? (
              <div className="flex min-h-64 flex-col items-center justify-center rounded-xl border border-dashed bg-muted/20 px-6 text-center">
                <FileDiff className="mb-4 size-10 text-muted-foreground" />
                <p className="font-medium">No proposal is ready for review</p>
                <p className="mt-2 max-w-md text-sm text-muted-foreground">
                  Give the SDTM agent direction in the right panel. Its typed proposal will appear
                  here with the exact evidence, diff, and validation results.
                </p>
              </div>
            ) : (
              <>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant={statusVariant(selected.status)}>
                    {readableStatus(selected.status)}
                  </Badge>
                  <span className="text-sm text-muted-foreground">
                    {selected.diff.length} proposed change{selected.diff.length === 1 ? '' : 's'}
                  </span>
                </div>

                {specificationSummary ? (
                  <div className="grid gap-3 sm:grid-cols-3">
                    <SummaryMetric label="Proposed domains" value={specificationSummary.domains} />
                    <SummaryMetric label="Proposed variables" value={specificationSummary.variables} />
                    <SummaryMetric
                      label="Value-level items"
                      value={specificationSummary.valueLevelMetadata}
                    />
                  </div>
                ) : null}

                {selected.status === 'queued' || selected.status === 'running' ? (
                  <div className="flex items-center gap-3 rounded-lg border bg-primary/5 p-4 text-sm">
                    <Loader2 className="size-5 animate-spin text-primary" />
                    Generation is running in the durable worker. This review view refreshes
                    automatically.
                  </div>
                ) : null}
                {selected.failure ? (
                  <div className="flex gap-3 rounded-lg border border-destructive/40 bg-destructive/5 p-4 text-sm">
                    <CircleAlert className="size-5 shrink-0 text-destructive" />
                    <pre className="min-w-0 whitespace-pre-wrap break-words">
                      {JSON.stringify(selected.failure, null, 2)}
                    </pre>
                  </div>
                ) : null}

                {selected.diff.length ? (
                  <ReviewSection
                    title="Base-to-proposal diff"
                    description="Only these reviewed changes will become active if you accept the proposal."
                  >
                    <details className="rounded-lg border">
                      <summary className="cursor-pointer px-4 py-3 text-sm font-medium">
                        Review {selected.diff.length} field-level change{selected.diff.length === 1 ? '' : 's'}
                      </summary>
                      <pre className="max-h-80 overflow-auto border-t bg-background p-4 text-xs">
                        {JSON.stringify(selected.diff, null, 2)}
                      </pre>
                    </details>
                  </ReviewSection>
                ) : null}

                {evidenceSections.length ? (
                  <div className="grid gap-4 md:grid-cols-2">
                    {evidenceSections.map((section) => (
                      <EvidenceList key={section.title} {...section} />
                    ))}
                  </div>
                ) : (
                  <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-4 text-sm">
                    No assumptions, unresolved items, or model limitations were declared.
                  </div>
                )}

                {selected.validation_issues.length ? (
                  <ReviewSection
                    title="Deterministic validation issues"
                    description="Authoritative platform checks; the AI cannot override these findings."
                  >
                    <IssueList issues={selected.validation_issues} />
                  </ReviewSection>
                ) : null}

                {selected.payload ? (
                  <details className="rounded-lg border bg-muted/10">
                    <summary className="cursor-pointer px-4 py-3 text-sm font-medium">
                      Technical proposal and generation provenance
                    </summary>
                    <div className="space-y-4 border-t p-4">
                      <div className="flex flex-wrap gap-2 text-xs">
                        <Badge variant="outline">instruction {selected.instruction_version}</Badge>
                        <Badge variant="outline">context {selected.context_fingerprint.slice(0, 12)}</Badge>
                        {selected.response_checksum ? (
                          <Badge variant="outline">
                            response {selected.response_checksum.slice(0, 12)}
                          </Badge>
                        ) : null}
                        <Badge variant="outline">{platformAgentLabel(selected)}</Badge>
                      </div>
                      <pre className="max-h-[34rem] overflow-auto rounded-lg bg-muted p-4 text-xs">
                        {JSON.stringify(selected.payload, null, 2)}
                      </pre>
                    </div>
                  </details>
                ) : null}

                {selected.status === 'review_required' ? (
                  <div className="space-y-3 rounded-xl border border-primary/20 bg-primary/5 p-5">
                    <div>
                      <Label htmlFor={`${proposalType}-rationale`}>Human review rationale</Label>
                      <p className="mt-1 text-xs text-muted-foreground">
                        Your decision and rationale are retained as reviewer evidence.
                      </p>
                    </div>
                    <Textarea
                      id={`${proposalType}-rationale`}
                      value={rationale}
                      placeholder="Explain why this proposal should be accepted, revised, or rejected."
                      onChange={(event) => setRationale(event.target.value)}
                    />
                    <div className="flex flex-wrap gap-2">
                      <Button
                        disabled={!rationale.trim() || decide.isPending}
                        onClick={() => decide.mutate({ proposal: selected, decision: 'accepted' })}
                      >
                        <Check /> Accept proposal
                      </Button>
                      <Button
                        variant="outline"
                        disabled={!rationale.trim() || decide.isPending}
                        onClick={() =>
                          decide.mutate({ proposal: selected, decision: 'revision_requested' })
                        }
                      >
                        <RefreshCw /> Request revision
                      </Button>
                      <Button
                        variant="destructive"
                        disabled={!rationale.trim() || decide.isPending}
                        onClick={() => decide.mutate({ proposal: selected, decision: 'rejected' })}
                      >
                        <X /> Reject
                      </Button>
                    </div>
                  </div>
                ) : null}
              </>
            )}
          </CardContent>
        </Card>
        {reviewEpilogue}
      </main>

      <aside className="min-w-0 lg:sticky lg:top-20 lg:max-h-[calc(100vh-6rem)] lg:overflow-y-auto">
        <Card className="overflow-hidden border-primary/35 shadow-md">
          <CardHeader className="border-b bg-gradient-to-br from-primary/15 via-primary/5 to-card">
            <div className="flex items-start justify-between gap-3">
              <div className="flex gap-3">
                <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-sm">
                  <Bot className="size-5" />
                </div>
                <div>
                  <CardTitle className="text-base">SDTM Agent</CardTitle>
                  <CardDescription className="mt-1">{readableStatus(proposalType)}</CardDescription>
                </div>
              </div>
              <Badge variant={agentIsActive ? 'default' : 'outline'} className="gap-1">
                <span
                  className={`size-1.5 rounded-full ${
                    agentIsActive ? 'animate-pulse bg-primary-foreground' : 'bg-emerald-500'
                  }`}
                />
                {agentIsActive ? 'Working' : 'Ready'}
              </Badge>
            </div>
          </CardHeader>

          <CardContent className="space-y-5 pt-5">
            <div className="space-y-3">
              <div className="flex items-center gap-2 text-sm font-medium">
                <Sparkles className="size-4 text-primary" />
                New proposal
              </div>
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
                {agents.isError ? (
                  <p className="text-xs text-destructive">Agent catalog is unavailable.</p>
                ) : null}
              </div>
              {needsDomain ? (
                <div className="space-y-2">
                  <Label htmlFor={`${proposalType}-domain`}>Target domain</Label>
                  <Input
                    id={`${proposalType}-domain`}
                    value={domain}
                    maxLength={8}
                    onChange={(event) => setDomain(event.target.value.toUpperCase())}
                  />
                </div>
              ) : null}
              {needsLanguage ? (
                <div className="space-y-2">
                  <Label htmlFor={`${proposalType}-language`}>Program language</Label>
                  <select
                    id={`${proposalType}-language`}
                    className="border-input h-9 w-full rounded-md border bg-transparent px-3 text-sm"
                    value={language}
                    onChange={(event) => setLanguage(event.target.value)}
                  >
                    <option value="python">Python</option>
                    <option value="r">R</option>
                    <option value="sas">SAS</option>
                  </select>
                </div>
              ) : null}
              <div className="space-y-2">
                <Label htmlFor={`${proposalType}-guidance`}>Guidance for the agent</Label>
                <Textarea
                  id={`${proposalType}-guidance`}
                  value={guidance}
                  rows={4}
                  placeholder="Add study-specific constraints, reviewer direction, or corrections…"
                  onChange={(event) => setGuidance(event.target.value)}
                />
              </div>
              <Button
                className="w-full"
                onClick={() => create.mutate()}
                disabled={create.isPending || !activeAgentId || (needsDomain && !domain.trim())}
              >
                {create.isPending ? <Loader2 className="animate-spin" /> : <MessageSquareText />}
                Generate proposal
              </Button>
              <p className="text-xs leading-relaxed text-muted-foreground">
                The agent proposes against revision {aggregate.revision}. Nothing becomes active
                until an authorized human accepts it.
              </p>
            </div>

            <Separator />

            <div className="space-y-3">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <Activity className="size-4 text-primary" />
                  Agent activity
                </div>
                {selected ? (
                  <Badge variant={statusVariant(selected.status)}>
                    {readableStatus(selected.status)}
                  </Badge>
                ) : null}
              </div>
              <div className="relative space-y-3 border-l pl-4 text-sm">
                <ActivityItem
                  title={selected ? 'Context assembled' : 'Waiting for direction'}
                  detail={
                    selected
                      ? `Pinned to base revision ${selected.base_revision}`
                      : 'Start a proposal above.'
                  }
                  active={!selected}
                />
                {selected ? (
                  <ActivityItem
                    title={
                      selected.status === 'queued' || selected.status === 'running'
                        ? 'Generating typed proposal'
                        : 'Proposal generation complete'
                    }
                    detail={platformAgentLabel(selected)}
                    active={selected.status === 'queued' || selected.status === 'running'}
                  />
                ) : null}
                {selected?.status === 'review_required' ? (
                  <ActivityItem
                    title="Human decision required"
                    detail="Review the center panel and record a rationale."
                    active
                  />
                ) : null}
              </div>
            </div>

            <Separator />

            <div className="space-y-3">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <Clock3 className="size-4 text-primary" />
                  Proposal history
                </div>
                <Badge variant="outline">{items.length}</Badge>
              </div>
              {proposals.isLoading ? (
                <Loader2 className="size-4 animate-spin" />
              ) : items.length === 0 ? (
                <p className="text-xs text-muted-foreground">No generation attempts yet.</p>
              ) : (
                <div className="space-y-2">
                  {items.map((proposal) => (
                    <button
                      key={proposal.id}
                      type="button"
                      className={`w-full rounded-lg border p-3 text-left transition-colors hover:bg-muted ${
                        selected?.id === proposal.id ? 'border-primary bg-primary/5' : ''
                      }`}
                      onClick={() => setSelectedId(proposal.id)}
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-mono text-xs">{proposal.id.slice(0, 8)}</span>
                        <Badge variant={statusVariant(proposal.status)}>
                          {readableStatus(proposal.status)}
                        </Badge>
                      </div>
                      <p className="mt-2 text-xs text-muted-foreground">
                        Base r{proposal.base_revision} ·{' '}
                        {new Date(proposal.created_at).toLocaleString()}
                      </p>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      </aside>
    </div>
  )
}

export function SdtmStageWorkspace({
  title,
  description,
  agentMessage,
  actionLabel,
  onAction,
  children,
  unframed = false,
}: SdtmStageWorkspaceProps) {
  const { aggregate } = useWorkbench()

  return (
    <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_19rem] 2xl:grid-cols-[minmax(0,1fr)_22rem]">
      <main className="min-w-0 space-y-6">
        {unframed ? (
          children
        ) : (
          <Card className="overflow-hidden border-primary/15">
            <CardHeader className="border-b bg-muted/30">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <CardTitle>{title}</CardTitle>
                    <Badge variant="outline">Reviewer workspace</Badge>
                  </div>
                  <CardDescription>{description}</CardDescription>
                </div>
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <ShieldCheck className="size-4 text-emerald-600" />
                  Accepted inputs only · revision {aggregate.revision}
                </div>
              </div>
            </CardHeader>
            <CardContent className="pt-6">{children}</CardContent>
          </Card>
        )}
      </main>

      <aside className="min-w-0 lg:sticky lg:top-20">
        <Card className="overflow-hidden border-primary/35 shadow-md">
          <CardHeader className="border-b bg-gradient-to-br from-primary/15 via-primary/5 to-card">
            <div className="flex items-start justify-between gap-3">
              <div className="flex gap-3">
                <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-sm">
                  <Bot className="size-5" />
                </div>
                <div>
                  <CardTitle className="text-base">SDTM Agent</CardTitle>
                  <CardDescription className="mt-1">Stage monitor</CardDescription>
                </div>
              </div>
              <Badge variant="outline" className="gap-1">
                <span className="size-1.5 rounded-full bg-emerald-500" />
                Ready
              </Badge>
            </div>
          </CardHeader>
          <CardContent className="space-y-5 pt-5">
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-sm font-medium">
                <Activity className="size-4 text-primary" />
                Agent activity
              </div>
              <p className="text-sm leading-relaxed text-muted-foreground">{agentMessage}</p>
            </div>
            <div className="relative space-y-3 border-l pl-4 text-sm">
              <ActivityItem
                title="Accepted context loaded"
                detail={`Monitoring aggregate revision ${aggregate.revision}.`}
              />
              <ActivityItem
                title="Human review remains authoritative"
                detail="Deterministic operations cannot silently change accepted clinical content."
                active
              />
            </div>
            <Separator />
            <Button variant="outline" className="w-full" onClick={onAction}>
              {actionLabel}
              <ArrowRight />
            </Button>
          </CardContent>
        </Card>
      </aside>
    </div>
  )
}

function summarizeSpecification(payload: Record<string, unknown>) {
  const envelope = payload.proposal
  const proposal =
    typeof envelope === 'object' && envelope !== null
      ? (envelope as Record<string, unknown>)
      : payload
  const domains = Array.isArray(proposal.domains) ? proposal.domains : []
  let variables = 0
  let valueLevelMetadata = 0
  for (const domain of domains) {
    if (typeof domain !== 'object' || domain === null) continue
    const record = domain as Record<string, unknown>
    variables += Array.isArray(record.variables) ? record.variables.length : 0
    valueLevelMetadata += Array.isArray(record.value_level_metadata)
      ? record.value_level_metadata.length
      : 0
  }
  return { domains: domains.length, variables, valueLevelMetadata }
}

function SummaryMetric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border bg-muted/20 p-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-2xl font-semibold">{value}</p>
    </div>
  )
}

function ReviewSection({
  title,
  description,
  children,
}: {
  title: string
  description: string
  children: ReactNode
}) {
  return (
    <section className="space-y-3">
      <div>
        <h3 className="text-sm font-semibold">{title}</h3>
        <p className="mt-1 text-xs text-muted-foreground">{description}</p>
      </div>
      {children}
    </section>
  )
}

function ActivityItem({
  title,
  detail,
  active = false,
}: {
  title: string
  detail: string
  active?: boolean
}) {
  return (
    <div className="relative">
      <span
        className={`absolute -left-[1.29rem] top-1 size-2 rounded-full ring-4 ring-card ${
          active ? 'animate-pulse bg-primary' : 'bg-emerald-500'
        }`}
      />
      <p className="font-medium">{title}</p>
      <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{detail}</p>
    </div>
  )
}

function EvidenceList({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="rounded-lg border p-4">
      <p className="mb-2 text-sm font-medium">{title}</p>
      {items.length ? (
        <ul className="list-disc space-y-1 pl-5 text-sm text-muted-foreground">
          {items.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-muted-foreground">None declared.</p>
      )}
    </div>
  )
}
