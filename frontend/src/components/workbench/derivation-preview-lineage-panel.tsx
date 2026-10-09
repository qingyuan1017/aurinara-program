import * as React from 'react'
import type { AxiosError } from 'axios'
import {
  Background,
  Controls,
  ReactFlow,
  ReactFlowProvider,
  type Edge,
  type Node,
} from '@xyflow/react'
import { Loader2 } from 'lucide-react'

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import {
  FormControl,
  FormDescription,
  FormItem,
  FormLabel,
} from '@/components/ui/form'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { EmptyState } from '@/components/data/states'
import { clampLimit } from '@/components/workbench/preview-panel'
import { jsonRequest } from '@/lib/requests'
import { parseProblem } from '@/lib/problems'
import {
  usePreviewPlan,
  useValidatePlan,
  useGetLineage,
} from '@/api/generated/sdtm/sdtm'
import type { AppSdtmRoutesPreviewRequest as PreviewRequest } from '@/api/generated/model'

/**
 * SDTM derivation preview, inline plan validation, and read-only lineage
 * (Requirements 12.5-12.7, 13.1-13.6; task 13.1).
 *
 * This panel sits under the Derivation Plan editor and drives the three
 * read-only, `200`-inline plan endpoints:
 *
 * - **Preview** (`POST /derivation-plan/preview` via `usePreviewPlan`): an
 *   optional domain selection plus a `limit` the client constrains to 1-200
 *   (reusing {@link clampLimit}). The produced per-domain outputs are rendered
 *   together with the resolved specification / plan / input-selection revisions.
 *   Each requested domain shows an explicit empty-result indication when it
 *   produced zero rows. A `422 sdtm_preview_domain_unknown` lists which
 *   requested domains the plan did not produce. Nothing is cached beyond this
 *   view: the response lives only in local state (a mutation, never a query).
 * - **Validation** (`POST /derivation-plan/validate` via `useValidatePlan`):
 *   shows the returned status and IR fingerprint. A `problem+json` leaves the
 *   last displayed validation result unchanged (the previous success is kept).
 * - **Lineage** (`GET /lineage` via `useGetLineage`): rendered as a read-only
 *   React Flow graph (no palette, no connect, no inspector writes).
 *
 * All three endpoints require an aligned plan server-side; when the plan is
 * misaligned the parent panel passes `disabled` so preview/validate are
 * blocked, matching the alignment gate on compile/execute (Requirement 12.4).
 */
export interface DerivationPreviewLineagePanelProps {
  sdtmId: string
  /**
   * When true the plan is misaligned (or otherwise not previewable/validatable);
   * the preview and validate controls are disabled. Lineage also requires an
   * aligned plan server-side, so its query is gated on the same flag.
   */
  disabled?: boolean
}

/** Shape of the `200` preview body the backend returns (opaque in the generated model). */
interface PreviewResult {
  schema_version?: string
  ir_fingerprint?: string
  input_selection_revision?: number
  specification_revision?: number
  plan_revision?: number
  limit?: number
  outputs: Record<string, Array<Record<string, unknown>>>
}

/** Shape of the `200` validate body the backend returns. */
interface ValidateResult {
  status?: string
  ir_fingerprint?: string
}

/** Shape of the `200` lineage body: `outputs` maps a produced dataset to its ancestor node ids. */
interface LineageResult {
  ir_fingerprint?: string
  outputs: Record<string, string[]>
}

export function DerivationPreviewLineagePanel({
  sdtmId,
  disabled = false,
}: DerivationPreviewLineagePanelProps) {
  return (
    <div className="flex flex-col gap-4">
      <PlanValidation sdtmId={sdtmId} disabled={disabled} />
      <PlanPreview sdtmId={sdtmId} disabled={disabled} />
      <PlanLineage sdtmId={sdtmId} disabled={disabled} />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Inline plan validation (Requirement 12.6)
// ---------------------------------------------------------------------------

function PlanValidation({
  sdtmId,
  disabled,
}: {
  sdtmId: string
  disabled: boolean
}) {
  // The last successful validation result, kept so a later problem+json leaves
  // the displayed plan/validation unchanged (R12.6). Local state only.
  const [result, setResult] = React.useState<ValidateResult | null>(null)
  const [error, setError] = React.useState<string | null>(null)

  const validate = useValidatePlan()

  async function handleValidate() {
    setError(null)
    try {
      const response = (await validate.mutateAsync({ sdtmId })) as ValidateResult
      setResult(response)
    } catch (err) {
      // A problem leaves the previously displayed result untouched; only the
      // transient error notice is updated.
      const axiosError = err as AxiosError
      setError(
        parseProblem(axiosError).detail ??
          axiosError.message ??
          'Could not validate the derivation plan.',
      )
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Inline plan validation</CardTitle>
        <CardDescription>
          Lower the aligned plan and report its status and IR fingerprint.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <Button
          type="button"
          onClick={handleValidate}
          disabled={disabled || validate.isPending}
          className="w-fit"
        >
          {validate.isPending && <Loader2 className="animate-spin" />}
          {validate.isPending ? 'Validating…' : 'Validate plan'}
        </Button>

        {error && <InlineError message={error} />}

        {result && (
          <dl className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
            <div className="flex items-center gap-2">
              <dt className="text-muted-foreground font-medium">Status</dt>
              <dd>
                <Badge variant={result.status === 'valid' ? 'secondary' : 'destructive'}>
                  {result.status ?? 'unknown'}
                </Badge>
              </dd>
            </div>
            <div className="flex items-center gap-2">
              <dt className="text-muted-foreground font-medium">IR fingerprint</dt>
              <dd>
                <code className="text-xs break-all">{result.ir_fingerprint ?? '—'}</code>
              </dd>
            </div>
          </dl>
        )}
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Preview (Requirements 12.5, 13.1-13.5)
// ---------------------------------------------------------------------------

function PlanPreview({
  sdtmId,
  disabled,
}: {
  sdtmId: string
  disabled: boolean
}) {
  // Preview rows live only in local state so they are never cached beyond this
  // view (R13.5). A mutation (not a query) keeps TanStack Query from caching.
  const [result, setResult] = React.useState<PreviewResult | null>(null)
  // The domains the user asked for, retained to drive the per-domain empty-row
  // indication and the unknown-domain report.
  const [requestedDomains, setRequestedDomains] = React.useState<string[]>([])
  const [unknownDomains, setUnknownDomains] = React.useState<string[]>([])
  const [error, setError] = React.useState<string | null>(null)

  const [limitText, setLimitText] = React.useState('50')
  const [domainsText, setDomainsText] = React.useState('')

  const preview = usePreviewPlan({ request: jsonRequest() })

  async function handlePreview(event: React.FormEvent) {
    event.preventDefault()
    setError(null)
    setUnknownDomains([])

    // Constrain the limit to the backend-accepted 1-200 window before sending
    // (R13.2), reusing the shared clamp so the behaviour matches Raw preview.
    const limit = clampLimit(Number.parseInt(limitText, 10))
    setLimitText(String(limit))

    const domains = domainsText
      .split(',')
      .map((d) => d.trim())
      .filter((d) => d.length > 0)
    setRequestedDomains(domains)

    const body: PreviewRequest = { limit }
    // Optional domain selection: omit the key entirely when none chosen so the
    // backend previews every produced domain (R13.1).
    if (domains.length > 0) {
      body.domains = domains
    }

    try {
      const response = (await preview.mutateAsync({
        sdtmId,
        data: body,
      })) as unknown as PreviewResult
      setResult(response)
    } catch (err) {
      const axiosError = err as AxiosError
      const problem = parseProblem(axiosError)
      setResult(null)
      if (
        axiosError.response?.status === 422 &&
        problem.code === 'sdtm_preview_domain_unknown'
      ) {
        // Identify which requested domains the plan did not produce (R13.4).
        setUnknownDomains(unknownFromProblem(problem.detail, domains))
        setError(
          problem.detail ??
            'Some requested domains were not produced by the plan.',
        )
        return
      }
      setError(
        problem.detail ?? axiosError.message ?? 'Could not preview the plan.',
      )
    }
  }

  // The domains to render: those the user requested, or every produced output
  // when no selection was made.
  const renderedDomains = result
    ? requestedDomains.length > 0
      ? requestedDomains
      : Object.keys(result.outputs).sort()
    : []

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Preview</CardTitle>
        <CardDescription>
          Evaluate the aligned plan over the exact selected Raw inputs with a
          bounded row window. Rows are shown for this view only and are not
          cached.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <form
          onSubmit={handlePreview}
          className="grid gap-4 sm:grid-cols-[8rem_1fr_auto] sm:items-end"
        >
          <FormItem>
            <FormLabel htmlFor="plan-preview-limit">Limit</FormLabel>
            <FormControl>
              <Input
                id="plan-preview-limit"
                inputMode="numeric"
                value={limitText}
                onChange={(e) => setLimitText(e.target.value)}
              />
            </FormControl>
            <FormDescription>1–200</FormDescription>
          </FormItem>

          <FormItem>
            <FormLabel htmlFor="plan-preview-domains">
              Domains (optional)
            </FormLabel>
            <FormControl>
              <Input
                id="plan-preview-domains"
                placeholder="Leave blank for all produced domains"
                value={domainsText}
                onChange={(e) => setDomainsText(e.target.value)}
              />
            </FormControl>
            <FormDescription>Comma-separated domain names.</FormDescription>
          </FormItem>

          <Button
            type="submit"
            disabled={disabled || preview.isPending}
            className="w-fit"
          >
            {preview.isPending && <Loader2 className="animate-spin" />}
            {preview.isPending ? 'Loading…' : 'Preview'}
          </Button>
        </form>

        {error && (
          <InlineError message={error}>
            {unknownDomains.length > 0 && (
              <ul className="mt-1 list-disc pl-5">
                {unknownDomains.map((domain) => (
                  <li key={domain}>
                    <code>{domain}</code> was not produced by the plan.
                  </li>
                ))}
              </ul>
            )}
          </InlineError>
        )}

        {result && (
          <div className="flex flex-col gap-4">
            <PreviewRevisions result={result} />
            {renderedDomains.length === 0 ? (
              <EmptyState
                title="No domains produced"
                description="The plan produced no domain outputs for this preview."
              />
            ) : (
              renderedDomains.map((domain) => (
                <DomainOutput
                  key={domain}
                  domain={domain}
                  rows={result.outputs[domain] ?? []}
                />
              ))
            )}
          </div>
        )}

        {!result && !error && !preview.isPending && (
          <EmptyState
            title="No preview loaded"
            description="Choose an optional domain selection and a row limit, then preview."
          />
        )}
      </CardContent>
    </Card>
  )
}

/** The resolved specification / plan / input-selection revisions (R13.3). */
function PreviewRevisions({ result }: { result: PreviewResult }) {
  return (
    <dl className="text-muted-foreground flex flex-wrap gap-x-6 gap-y-1 text-sm">
      <Field label="Specification revision" value={result.specification_revision} />
      <Field label="Plan revision" value={result.plan_revision} />
      <Field
        label="Input Selection revision"
        value={result.input_selection_revision}
      />
      <Field label="Limit" value={result.limit} />
      {result.ir_fingerprint && (
        <div className="flex gap-1">
          <dt className="font-medium">IR fingerprint</dt>
          <dd>
            <code className="text-xs break-all">{result.ir_fingerprint}</code>
          </dd>
        </div>
      )}
    </dl>
  )
}

function Field({ label, value }: { label: string; value: number | undefined }) {
  return (
    <div className="flex gap-1">
      <dt className="font-medium">{label}</dt>
      <dd>{value ?? '—'}</dd>
    </div>
  )
}

/** Render one produced domain's rows, or an explicit empty-result indication (R13.3). */
function DomainOutput({
  domain,
  rows,
}: {
  domain: string
  rows: Array<Record<string, unknown>>
}) {
  const columns = React.useMemo(() => {
    const seen = new Set<string>()
    for (const row of rows) {
      for (const key of Object.keys(row)) seen.add(key)
    }
    return Array.from(seen)
  }, [rows])

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <h4 className="text-sm font-medium">
          <code>{domain}</code>
        </h4>
        <Badge variant="outline">{rows.length} rows</Badge>
      </div>

      {rows.length === 0 ? (
        <p
          className="text-muted-foreground rounded-md border border-dashed px-3 py-2 text-sm"
          data-slot="domain-empty"
        >
          The plan produced no rows for <code>{domain}</code> in this window.
        </p>
      ) : (
        <div className="rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                {columns.map((column) => (
                  <TableHead key={column}>{column}</TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row, rowIndex) => (
                <TableRow key={rowIndex}>
                  {columns.map((column) => (
                    <TableCell key={column}>{formatCell(row[column])}</TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Lineage (Requirement 12.7)
// ---------------------------------------------------------------------------

function PlanLineage({
  sdtmId,
  disabled,
}: {
  sdtmId: string
  disabled: boolean
}) {
  // Lineage requires an aligned plan server-side; gate the query on the same
  // alignment flag the preview/validate controls use so a misaligned plan does
  // not fire a request that would 409/422.
  const query = useGetLineage(sdtmId, {
    query: { enabled: !disabled },
  })

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Lineage</CardTitle>
        <CardDescription>
          Produced-dataset lineage rendered as a read-only graph.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {disabled ? (
          <EmptyState
            title="Lineage unavailable"
            description="Align the derivation plan to view its lineage."
          />
        ) : query.isLoading ? (
          <Skeleton className="h-80 w-full" />
        ) : query.isError ? (
          <InlineError
            message={
              parseProblem(query.error as AxiosError).detail ??
              'Could not load lineage.'
            }
          />
        ) : (
          <LineageGraph lineage={(query.data as LineageResult | undefined) ?? null} />
        )}
      </CardContent>
    </Card>
  )
}

/**
 * Build a read-only React Flow graph from the lineage map (dataset -> ancestor
 * node ids) and render it with no palette, connect handles, or inspector — the
 * canvas is purely a viewer (R12.7).
 */
function LineageGraph({ lineage }: { lineage: LineageResult | null }) {
  const { nodes, edges } = React.useMemo(
    () => lineageToGraph(lineage),
    [lineage],
  )

  if (nodes.length === 0) {
    return (
      <EmptyState
        title="No lineage"
        description="The plan produced no datasets to show lineage for."
      />
    )
  }

  return (
    <div className="h-80 w-full overflow-hidden rounded-md border">
      <ReactFlowProvider>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodesConnectable={false}
          nodesDraggable={false}
          elementsSelectable={false}
          edgesFocusable={false}
          fitView
          proOptions={{ hideAttribution: true }}
          aria-label="Derivation plan lineage graph (read-only)"
        >
          <Background />
          <Controls showInteractive={false} />
        </ReactFlow>
      </ReactFlowProvider>
    </div>
  )
}

/**
 * Pure transform of the lineage map into read-only React Flow nodes/edges.
 *
 * Each key of `outputs` is a produced dataset, and its value is the sorted list
 * of ancestor node ids. Every referenced id (dataset or ancestor) becomes a
 * node; an edge is drawn from each ancestor to the dataset it feeds. Positions
 * are a deterministic two-column auto-layout (ancestors on the left, produced
 * datasets on the right) kept entirely as client-only view state.
 */
export function lineageToGraph(lineage: LineageResult | null): {
  nodes: Node[]
  edges: Edge[]
} {
  if (!lineage || !lineage.outputs) return { nodes: [], edges: [] }

  const outputs = lineage.outputs
  const datasets = Object.keys(outputs)
  const datasetSet = new Set(datasets)

  const ancestors = new Set<string>()
  for (const dataset of datasets) {
    for (const ancestor of outputs[dataset] ?? []) {
      if (!datasetSet.has(ancestor)) ancestors.add(ancestor)
    }
  }

  const ancestorList = Array.from(ancestors).sort()
  const nodes: Node[] = []

  ancestorList.forEach((id, index) => {
    nodes.push({
      id,
      position: { x: 0, y: index * 90 },
      data: { label: id },
      type: 'input',
      draggable: false,
      connectable: false,
    })
  })

  datasets.sort().forEach((dataset, index) => {
    nodes.push({
      id: dataset,
      position: { x: 320, y: index * 90 },
      data: { label: dataset },
      type: 'output',
      draggable: false,
      connectable: false,
    })
  })

  const edges: Edge[] = []
  for (const dataset of datasets) {
    for (const ancestor of outputs[dataset] ?? []) {
      edges.push({
        id: `${ancestor}->${dataset}`,
        source: ancestor,
        target: dataset,
      })
    }
  }

  return { nodes, edges }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Parse the unknown-domain list out of a `sdtm_preview_domain_unknown` detail.
 * The backend formats the detail as `The plan did not produce: A, B.`; this
 * intersects the parsed names with the user's requested domains so only
 * genuinely-requested-but-unproduced domains are reported, falling back to the
 * requested set when the detail cannot be parsed.
 */
export function unknownFromProblem(
  detail: string | undefined,
  requested: string[],
): string[] {
  if (!detail) return requested
  const match = detail.match(/produce:\s*(.+?)\.?$/)
  if (!match) return requested
  const parsed = match[1]
    .split(',')
    .map((d) => d.trim())
    .filter((d) => d.length > 0)
  const parsedSet = new Set(parsed)
  const fromRequested = requested.filter((d) => parsedSet.has(d))
  return fromRequested.length > 0 ? fromRequested : parsed
}

/** Render a single cell value; nullish values show an em dash. */
function formatCell(value: unknown): React.ReactNode {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

/** Inline error notice for a failed inline operation. */
function InlineError({
  message,
  children,
}: {
  message: string
  children?: React.ReactNode
}) {
  return (
    <div
      role="alert"
      className="border-destructive/50 bg-destructive/10 text-destructive rounded-md border px-3 py-2 text-sm"
    >
      {message}
      {children}
    </div>
  )
}
