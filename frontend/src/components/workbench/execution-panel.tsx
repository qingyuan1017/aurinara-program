import * as React from 'react'
import type { AxiosError } from 'axios'
import { Loader2 } from 'lucide-react'
import { PageHeader } from '@/components/layout/page-header'
import { EmptyState } from '@/components/data/states'
import { StatusBadge } from '@/components/data/status-badge'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from '@/components/ui/sonner'
import { ArtifactList } from '@/components/workbench/artifact-list'
import type { ArtifactListItem } from '@/components/workbench/artifact-list'
import { useWorkbench } from '@/components/workbench/workbench-context'
import { cn } from '@/lib/utils'
import { invalidateSdtmOperationArtifacts } from '@/lib/invalidate'
import { useExecuteSdtm } from '@/api/generated/sdtm/sdtm'
import {
  useGetExecutionRun,
  useGetExecutionLogs,
  useGetExecutionOutputs,
} from '@/api/generated/execution/execution'
import type {
  ExecutionRunResponse,
  GetExecutionLogs200,
  GetExecutionOutputs200,
  SdtmExecutionRequest,
} from '@/api/generated/model'
import {
  useOperationPoll,
  OPERATION_POLL_PRESETS,
  type OperationQueryOpts,
  type OperationQueryState,
} from '@/hooks/use-operation-poll'
import { useIdempotencyKey } from '@/lib/requests'
import { parseProblem } from '@/lib/problems'

export interface ExecutionPanelProps {
  /** The SDTM workbench id to execute (path parameter for the POST). */
  sdtmId: string
}

/**
 * Terminal statuses for an execution run. The run service settles a run to
 * `succeeded`, `failed`, or `cancelled` (see `src/app/execution`). The SAS
 * "no external runner" case is a `failed` terminal whose `failure.code` is
 * `runner_not_configured` — handled specially below (Requirement 16.5).
 */
const EXECUTION_TERMINAL = ['succeeded', 'failed', 'cancelled'] as const

/** The three first-party/adapter execution languages (backend `^(python|r|sas)$`). */
const EXECUTION_LANGUAGES = [
  { value: 'python', label: 'Python' },
  { value: 'r', label: 'R' },
  { value: 'sas', label: 'SAS (external runner)' },
] as const

/** The pinned-input fields authored via the form (no cross-tab store yet). */
interface ExecutionFormState {
  language: string
  program_artifact_id: string
  input_artifact_ids: string
  validation_run_id: string
  input_selection_revision: string
  source_specification_revision: string
  source_plan_revision: string
  compiler_fingerprint: string
  expected_input_fingerprint: string
  cpu: string
  memory_mb: string
  runtime_seconds: string
  output_bytes: string
}

const EMPTY_FORM: ExecutionFormState = {
  language: 'python',
  program_artifact_id: '',
  input_artifact_ids: '',
  validation_run_id: '',
  input_selection_revision: '',
  source_specification_revision: '',
  source_plan_revision: '',
  compiler_fingerprint: '',
  expected_input_fingerprint: '',
  cpu: '1',
  memory_mb: '2048',
  runtime_seconds: '600',
  output_bytes: '52428800',
}

/** Split a comma/whitespace/newline separated id list into trimmed entries. */
function parseIdList(raw: string): string[] {
  return raw
    .split(/[\s,]+/)
    .map((item) => item.trim())
    .filter((item) => item.length > 0)
}

/**
 * Build the typed {@link SdtmExecutionRequest} body from the form, or return
 * `null` with the first validation message when a required field is missing or
 * a numeric field cannot be parsed. The backend remains authoritative; this is
 * only a client guard so an obviously incomplete body is not submitted.
 */
function buildRequest(
  form: ExecutionFormState,
): { body: SdtmExecutionRequest } | { error: string } {
  const inputIds = parseIdList(form.input_artifact_ids)
  if (inputIds.length === 0) {
    return { error: 'At least one input artifact id is required.' }
  }
  const required: [keyof ExecutionFormState, string][] = [
    ['program_artifact_id', 'Program artifact id'],
    ['validation_run_id', 'Validation-run id'],
    ['compiler_fingerprint', 'Compiler fingerprint'],
    ['expected_input_fingerprint', 'Expected input fingerprint'],
  ]
  for (const [key, label] of required) {
    if (!form[key].trim()) return { error: `${label} is required.` }
  }

  const numericFields: [keyof ExecutionFormState, string][] = [
    ['input_selection_revision', 'Input-selection revision'],
    ['source_specification_revision', 'Specification revision'],
    ['source_plan_revision', 'Plan revision'],
    ['cpu', 'CPU limit'],
    ['memory_mb', 'Memory limit (MB)'],
    ['runtime_seconds', 'Runtime limit (s)'],
    ['output_bytes', 'Output size limit (bytes)'],
  ]
  const numbers: Partial<Record<keyof ExecutionFormState, number>> = {}
  for (const [key, label] of numericFields) {
    const parsed = Number(form[key])
    if (!Number.isFinite(parsed)) return { error: `${label} must be a number.` }
    numbers[key] = parsed
  }

  return {
    body: {
      language: form.language,
      program_artifact_id: form.program_artifact_id.trim(),
      input_artifact_ids: inputIds,
      validation_run_id: form.validation_run_id.trim(),
      input_selection_revision: numbers.input_selection_revision!,
      source_specification_revision: numbers.source_specification_revision!,
      source_plan_revision: numbers.source_plan_revision!,
      compiler_fingerprint: form.compiler_fingerprint.trim(),
      expected_input_fingerprint: form.expected_input_fingerprint.trim(),
      limits: {
        cpu: numbers.cpu!,
        memory_mb: numbers.memory_mb!,
        runtime_seconds: numbers.runtime_seconds!,
        output_bytes: numbers.output_bytes!,
      },
    },
  }
}

/** Does this terminal run carry the SAS `runner_not_configured` failure? */
function isRunnerNotConfigured(run: ExecutionRunResponse): boolean {
  const failure = run.failure
  return (
    !!failure &&
    typeof failure === 'object' &&
    (failure as { code?: unknown }).code === 'runner_not_configured'
  )
}

/**
 * Adapts the generated {@link useGetExecutionRun} query to the shape
 * {@link useOperationPoll} expects: forwards the computed
 * `enabled`/`refetchInterval` through `opts.query` so the generated query
 * drives the polling, and projects back `{ data, error }`. `retry` is disabled
 * so a `problem+json` surfaces immediately and stops polling.
 */
function useExecutionRunOperation(
  runId: string,
  opts: OperationQueryOpts,
): OperationQueryState<ExecutionRunResponse> {
  const query = useGetExecutionRun(runId, {
    query: { ...opts.query, retry: false },
  })
  return { data: query.data, error: query.error as AxiosError | null }
}

function Notice({
  title,
  detail,
  tone = 'destructive',
}: {
  title: string
  detail?: React.ReactNode
  tone?: 'destructive' | 'muted'
}) {
  return (
    <div
      role="alert"
      className={cn(
        'flex flex-col gap-1 rounded-md border px-4 py-3 text-sm',
        tone === 'destructive'
          ? 'border-destructive/50 text-destructive'
          : 'border-border text-muted-foreground',
      )}
    >
      <span className="font-medium">{title}</span>
      {detail && <span className="opacity-90">{detail}</span>}
    </div>
  )
}

/** A labeled metric row inside the status/metrics grid. */
function Metric({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex flex-col">
      <dt className="text-muted-foreground text-xs font-medium">{label}</dt>
      <dd className="text-sm break-all">{value ?? '—'}</dd>
    </div>
  )
}

/**
 * Elapsed wall-clock between `started_at` and `completed_at`, when both are
 * present, rendered as a seconds figure; otherwise `null`.
 */
function runDurationSeconds(run: ExecutionRunResponse): number | null {
  if (!run.started_at || !run.completed_at) return null
  const start = Date.parse(run.started_at)
  const end = Date.parse(run.completed_at)
  if (Number.isNaN(start) || Number.isNaN(end)) return null
  return Math.max(0, (end - start) / 1000)
}

/** Status + timing + resource-metrics card for a terminal (or in-flight) run. */
function RunStatus({ run }: { run: ExecutionRunResponse }) {
  const duration = runDurationSeconds(run)
  const metrics = (run.metrics ?? {}) as Record<string, unknown>
  const metricEntries = Object.entries(metrics)
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Execution run</CardTitle>
        <CardDescription className="flex flex-wrap items-center gap-2">
          <StatusBadge status={run.status} />
          <Badge variant="outline">{run.language}</Badge>
          {typeof run.exit_code === 'number' && (
            <Badge variant="secondary">exit {run.exit_code}</Badge>
          )}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <Metric label="Started" value={run.started_at ?? '—'} />
          <Metric label="Completed" value={run.completed_at ?? '—'} />
          <Metric
            label="Duration"
            value={duration === null ? '—' : `${duration.toFixed(2)}s`}
          />
        </dl>
        {metricEntries.length > 0 && (
          <div>
            <p className="text-muted-foreground mb-1 text-xs font-medium">
              Resource metrics
            </p>
            <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3">
              {metricEntries.map(([key, value]) => (
                <Metric key={key} label={key} value={String(value)} />
              ))}
            </dl>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

/** Captured stdout/stderr for a run, loaded only once a run id exists. */
function RunLogs({ runId }: { runId: string }) {
  const query = useGetExecutionLogs(runId, { query: { retry: false } })
  const logs = query.data as GetExecutionLogs200 | undefined
  const stdout = typeof logs?.stdout === 'string' ? logs.stdout : ''
  const stderr = typeof logs?.stderr === 'string' ? logs.stderr : ''
  const truncated = logs?.truncated === true

  if (query.isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Loader2 className="size-4 animate-spin" aria-hidden />
            Loading logs…
          </CardTitle>
        </CardHeader>
      </Card>
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Logs</CardTitle>
        {truncated && (
          <CardDescription>Output truncated to the log limit.</CardDescription>
        )}
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div>
          <p className="text-muted-foreground mb-1 text-xs font-medium">stdout</p>
          <pre className="bg-muted max-h-64 overflow-auto rounded-md p-3 text-xs whitespace-pre-wrap">
            {stdout || '(empty)'}
          </pre>
        </div>
        <div>
          <p className="text-muted-foreground mb-1 text-xs font-medium">stderr</p>
          <pre className="bg-muted max-h-64 overflow-auto rounded-md p-3 text-xs whitespace-pre-wrap">
            {stderr || '(empty)'}
          </pre>
        </div>
      </CardContent>
    </Card>
  )
}

/** Output artifacts produced by a successful run (Requirement 16.3). */
function RunOutputs({ runId }: { runId: string }) {
  const query = useGetExecutionOutputs(runId, { query: { retry: false } })
  const outputs = query.data as GetExecutionOutputs200 | undefined
  const rawItems = Array.isArray(outputs?.items) ? outputs.items : []

  const artifacts: ArtifactListItem[] = rawItems
    .map((item) => {
      const record = (item ?? {}) as Record<string, unknown>
      const id = record.artifact_id
      if (typeof id !== 'string') return null
      return {
        id,
        artifact_type:
          typeof record.artifact_type === 'string'
            ? record.artifact_type
            : undefined,
        sha256: typeof record.sha256 === 'string' ? record.sha256 : undefined,
        size: typeof record.size === 'number' ? record.size : undefined,
      } as ArtifactListItem
    })
    .filter((item): item is ArtifactListItem => item !== null)

  return (
    <ArtifactList
      artifacts={artifacts}
      title="Output artifacts"
      emptyTitle="No output artifacts"
      emptyDescription="This run produced no downloadable outputs."
    />
  )
}

/**
 * SDTM Execution tab body (Requirement 16).
 *
 * Flow:
 * - The user authors the full pinned-input body via form fields — language,
 *   program artifact id, input artifact ids, validation-run id, the pinned
 *   input-selection/specification/plan revisions, the compiler fingerprint, the
 *   expected input fingerprint, and the accepted limits (there is no cross-tab
 *   state store yet, so these are entered explicitly) (R16.1).
 * - Submit via `useExecuteSdtm` (`POST /api/v1/sdtms/{sdtm_id}/execute`),
 *   carrying a stable `Idempotency-Key` held across the automatic retries of
 *   the attempt (R16.1, R21.2). The `202` returns an execution-run resource.
 * - Poll `useGetExecutionRun` through {@link useOperationPoll} at 1-5s with a
 *   120s cap until the run reaches a terminal status (R16.2).
 * - On a terminal run, render status + timing + resource metrics, the captured
 *   logs (`useGetExecutionLogs`), and the output artifacts
 *   (`useGetExecutionOutputs`) (R16.3).
 * - A `runner_not_configured` terminal (SAS without an external runner) is not
 *   treated as a hard failure: a notice explains SAS needs an external runner
 *   and the generated program remains available (R16.5). Any other `failed`
 *   terminal shows the typed failure object together with any captured logs
 *   (R16.4).
 */
export function ExecutionPanel({ sdtmId }: ExecutionPanelProps) {
  const qc = useQueryClient()
  const { studyId } = useWorkbench()
  const [form, setForm] = React.useState<ExecutionFormState>(EMPTY_FORM)
  const [runId, setRunId] = React.useState<string | null>(null)
  const [formError, setFormError] = React.useState<string | null>(null)

  // One stable Idempotency-Key per execution attempt (R21.2); `begin()` mints a
  // fresh key when the user starts a new run.
  const idempotency = useIdempotencyKey()
  const execute = useExecuteSdtm({ request: idempotency.requestConfig })

  const poll = useOperationPoll<ExecutionRunResponse>({
    operationId: runId,
    useGetOperation: useExecutionRunOperation,
    intervalMs: OPERATION_POLL_PRESETS.fast.intervalMs,
    timeoutMs: OPERATION_POLL_PRESETS.fast.timeoutMs,
    terminalStatuses: EXECUTION_TERMINAL,
  })

  function update<K extends keyof ExecutionFormState>(
    key: K,
    value: ExecutionFormState[K],
  ) {
    setForm((prev) => ({ ...prev, [key]: value }))
  }

  async function handleStart() {
    const result = buildRequest(form)
    if ('error' in result) {
      setFormError(result.error)
      return
    }
    setFormError(null)
    // New attempt: mint a fresh key so this run's automatic retries reuse it
    // while a distinct run gets a distinct key.
    idempotency.begin()
    try {
      const run = await execute.mutateAsync({ sdtmId, data: result.body })
      setRunId(run.id)
    } catch (error) {
      const problem = parseProblem(error as AxiosError)
      toast.error(problem.title ?? 'Execution could not be started', {
        description: problem.detail,
      })
    }
  }

  const startProblem = execute.error
    ? parseProblem(execute.error as AxiosError)
    : null
  const pollProblem = poll.problem ? parseProblem(poll.problem) : null
  const problem = startProblem ?? pollProblem

  const run = poll.phase === 'terminal' ? poll.data : undefined

  // A completed `202` execution run produces output artifacts and advances the
  // aggregate's latest-run state; once terminal, reload the study-scoped
  // artifact collection and the aggregate detail so dependent views refetch
  // (R21.6). Keyed on the terminal run id so it fires once per finished run.
  const terminalRunId = run?.id ?? null
  React.useEffect(() => {
    if (!terminalRunId) return
    invalidateSdtmOperationArtifacts(qc, sdtmId, studyId)
  }, [qc, sdtmId, studyId, terminalRunId])

  const runnerNotConfigured = run ? isRunnerNotConfigured(run) : false
  const failure = run?.failure as Record<string, unknown> | null | undefined
  const isHardFailure =
    !!run && run.status === 'failed' && !runnerNotConfigured

  const isBusy = execute.isPending || poll.phase === 'polling'

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Execution"
        description={
          <>
            Submit an exact SDTM execution via{' '}
            <code>POST /api/v1/sdtms/{'{sdtm_id}'}/execute</code>. All pinned
            inputs are authored below.
          </>
        }
      />

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Pinned execution inputs</CardTitle>
          <CardDescription>
            The run binds a successful validation run and exact immutable inputs.
            Provide the pinned revisions, fingerprints, and accepted limits.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="exec-language">Language</Label>
              <Select
                value={form.language}
                onValueChange={(value) => update('language', value)}
              >
                <SelectTrigger id="exec-language">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {EXECUTION_LANGUAGES.map((lang) => (
                    <SelectItem key={lang.value} value={lang.value}>
                      {lang.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="exec-program">Program artifact id</Label>
              <Input
                id="exec-program"
                value={form.program_artifact_id}
                onChange={(e) => update('program_artifact_id', e.target.value)}
                placeholder="artifact UUID"
              />
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="exec-inputs">Input artifact ids</Label>
            <Input
              id="exec-inputs"
              value={form.input_artifact_ids}
              onChange={(e) => update('input_artifact_ids', e.target.value)}
              placeholder="comma or newline separated artifact UUIDs"
            />
            <p className="text-muted-foreground text-xs">
              At least one id. Separate multiple ids with commas or whitespace.
            </p>
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="exec-validation">Validation-run id</Label>
              <Input
                id="exec-validation"
                value={form.validation_run_id}
                onChange={(e) => update('validation_run_id', e.target.value)}
                placeholder="validation-run UUID"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="exec-input-selection-rev">
                Input-selection revision
              </Label>
              <Input
                id="exec-input-selection-rev"
                type="number"
                min={1}
                value={form.input_selection_revision}
                onChange={(e) =>
                  update('input_selection_revision', e.target.value)
                }
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="exec-spec-rev">Specification revision</Label>
              <Input
                id="exec-spec-rev"
                type="number"
                min={1}
                value={form.source_specification_revision}
                onChange={(e) =>
                  update('source_specification_revision', e.target.value)
                }
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="exec-plan-rev">Plan revision</Label>
              <Input
                id="exec-plan-rev"
                type="number"
                min={1}
                value={form.source_plan_revision}
                onChange={(e) =>
                  update('source_plan_revision', e.target.value)
                }
              />
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="exec-compiler-fp">Compiler fingerprint</Label>
              <Input
                id="exec-compiler-fp"
                value={form.compiler_fingerprint}
                onChange={(e) => update('compiler_fingerprint', e.target.value)}
                placeholder="64-char hex"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="exec-input-fp">Expected input fingerprint</Label>
              <Input
                id="exec-input-fp"
                value={form.expected_input_fingerprint}
                onChange={(e) =>
                  update('expected_input_fingerprint', e.target.value)
                }
                placeholder="64-char hex"
              />
            </div>
          </div>

          <fieldset className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <legend className="text-muted-foreground mb-1 w-full text-xs font-medium">
              Accepted limits
            </legend>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="exec-cpu">CPU</Label>
              <Input
                id="exec-cpu"
                type="number"
                min={0}
                value={form.cpu}
                onChange={(e) => update('cpu', e.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="exec-mem">Memory (MB)</Label>
              <Input
                id="exec-mem"
                type="number"
                min={0}
                value={form.memory_mb}
                onChange={(e) => update('memory_mb', e.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="exec-runtime">Runtime (s)</Label>
              <Input
                id="exec-runtime"
                type="number"
                min={0}
                value={form.runtime_seconds}
                onChange={(e) => update('runtime_seconds', e.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="exec-output-bytes">Output (bytes)</Label>
              <Input
                id="exec-output-bytes"
                type="number"
                min={0}
                value={form.output_bytes}
                onChange={(e) => update('output_bytes', e.target.value)}
              />
            </div>
          </fieldset>

          {formError && (
            <p className="text-destructive text-sm" role="alert">
              {formError}
            </p>
          )}

          <div>
            <Button type="button" onClick={handleStart} disabled={isBusy}>
              {isBusy && <Loader2 className="animate-spin" aria-hidden />}
              Execute
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* A `problem+json` from the start POST or a poll (R16.4 transport path). */}
      {problem && (
        <Notice
          title={
            (problem as { title?: string }).title ??
            problem.detail ??
            'Execution failed to start'
          }
          detail={
            (problem as { title?: string }).title ? problem.detail : undefined
          }
        />
      )}

      {/* Polling in flight after the `202`: spinner + elapsed clock (R16.2). */}
      {poll.phase === 'polling' && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Loader2 className="size-4 animate-spin" aria-hidden />
              Running execution
            </CardTitle>
            <CardDescription>
              Polling for a result… ({Math.round(poll.elapsedMs / 1000)}s
              elapsed)
            </CardDescription>
          </CardHeader>
        </Card>
      )}

      {/* Client-side timeout: still running server-side past the 120s cap. */}
      {poll.phase === 'timed-out' && (
        <Notice
          title="The execution run did not finish in time"
          detail="The execution run is still running on the server. No result is available yet — check back shortly."
        />
      )}

      {/* Terminal run: status/timing/metrics + logs + outputs (R16.3). */}
      {run && runId && (
        <div className="flex flex-col gap-4">
          <RunStatus run={run} />

          {/* SAS with no external runner: not a hard failure — the generated
              program remains available (R16.5). */}
          {runnerNotConfigured && (
            <Notice
              tone="muted"
              title="SAS execution needs an external runner"
              detail="No external SAS runner is configured, so this program was not executed. The generated SAS program remains available for download and the result does not invalidate it."
            />
          )}

          {/* Any other failure: show the typed failure object (R16.4). The
              captured logs render below regardless. */}
          {isHardFailure && (
            <Notice
              title="The execution run failed"
              detail={
                <span className="flex flex-col gap-1">
                  {typeof failure?.code === 'string' && (
                    <code className="text-xs font-semibold">
                      {failure.code as string}
                    </code>
                  )}
                  <span>
                    {typeof failure?.detail === 'string'
                      ? (failure.detail as string)
                      : 'The run reported a failure. Review the captured logs below.'}
                  </span>
                </span>
              }
            />
          )}

          {/* Captured logs for every terminal run, including failures (R16.3/16.4). */}
          <RunLogs runId={runId} />

          {/* Output artifacts (only a succeeded run produces any). */}
          {run.status === 'succeeded' && <RunOutputs runId={runId} />}
        </div>
      )}

      {poll.phase === 'idle' && !problem && (
        <EmptyState
          title="No execution run yet"
          description="Author the pinned inputs and execute to see status, metrics, logs, and outputs."
        />
      )}
    </div>
  )
}

export default ExecutionPanel
