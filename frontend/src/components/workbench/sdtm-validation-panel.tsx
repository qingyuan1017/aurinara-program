import * as React from 'react'
import type { AxiosError } from 'axios'
import { AlertTriangle, Loader2 } from 'lucide-react'
import { PageHeader } from '@/components/layout/page-header'
import { EmptyState } from '@/components/data/states'
import { StatusBadge } from '@/components/data/status-badge'
import { IssueList } from '@/components/data/issue-list'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { cn } from '@/lib/utils'
import { useValidateSdtm } from '@/api/generated/sdtm/sdtm'
import { useGetValidationRun } from '@/api/generated/validation/validation'
import type { ValidationRunResponse } from '@/api/generated/model'
import {
  useOperationPoll,
  OPERATION_POLL_PRESETS,
  type OperationQueryOpts,
  type OperationQueryState,
} from '@/hooks/use-operation-poll'
import { parseProblem } from '@/lib/problems'
import { invalidateSdtmOperationArtifacts } from '@/lib/invalidate'
import { useQueryClient } from '@tanstack/react-query'

export interface SdtmValidationPanelProps {
  /** The SDTM workbench id to validate (path parameter for the POST). */
  sdtmId: string
}

/**
 * The terminal statuses for an SDTM validation run. Unlike the generic
 * operation poll (`completed`/`succeeded`), an SDTM Validation_Run settles to
 * `passed` or `failed` (Requirement 14.2).
 */
const SDTM_VALIDATION_TERMINAL = ['passed', 'failed'] as const

/**
 * Adapts the generated {@link useGetValidationRun} query to the shape
 * {@link useOperationPoll} expects: it forwards the computed
 * `enabled`/`refetchInterval` through `opts.query` so the generated query
 * drives the actual network polling, and reads back `data` + `error`. `retry`
 * is disabled so a `problem+json` surfaces immediately and stops polling.
 */
function useValidationRunOperation(
  runId: string,
  opts: OperationQueryOpts,
): OperationQueryState<ValidationRunResponse> {
  const query = useGetValidationRun(runId, {
    query: { ...opts.query, retry: false },
  })
  return { data: query.data, error: query.error as AxiosError | null }
}

/**
 * Render a single Validation_Run: status, per-severity counts, validator
 * name/version, and the full common-issue list (code, severity, message,
 * suggestion, entity type/id, field path, dataset, variable) with its own
 * empty state (Requirements 14.3, 14.4).
 */
function ValidationRunView({ run }: { run: ValidationRunResponse }) {
  const isFailed = run.status.toLowerCase() === 'failed'
  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Validation run</CardTitle>
          <CardDescription className="flex flex-wrap items-center gap-2">
            <StatusBadge status={run.status} />
            <Badge variant="destructive">Error: {run.error_count}</Badge>
            <Badge variant="secondary">Warning: {run.warning_count}</Badge>
            <Badge variant="outline">Info: {run.info_count}</Badge>
          </CardDescription>
        </CardHeader>
        <CardContent className="text-muted-foreground text-xs">
          <span className="font-medium">Validator: </span>
          {run.validator_name} {run.validator_version}
        </CardContent>
      </Card>

      {/* A `failed` run shows a persistent notice that error-severity issues
          block downstream SDTM generation/execution. */}
      {isFailed && (
        <Card className="border-destructive">
          <CardHeader>
            <CardTitle className="text-destructive text-base">
              Validation failed
            </CardTitle>
            <CardDescription>
              This workbench has error-severity issues. Error-severity issues
              block SDTM generation and execution until they are resolved.
            </CardDescription>
          </CardHeader>
        </Card>
      )}

      <IssueList
        issues={run.issues}
        emptyDescription="This validation run produced no issues."
      />
    </div>
  )
}

function Notice({
  title,
  detail,
}: {
  title: string
  detail?: React.ReactNode
}) {
  return (
    <div
      role="alert"
      className={cn(
        'flex items-start gap-3 rounded-md border px-4 py-3 text-sm',
        'border-destructive/50 text-destructive',
      )}
    >
      <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div className="flex flex-col gap-1">
        <span className="font-medium">{title}</span>
        {detail && <span className="opacity-90">{detail}</span>}
      </div>
    </div>
  )
}

/**
 * SDTM Validation tab body (Requirement 14).
 *
 * Flows:
 * - Trigger validation (R14.1): `POST /api/v1/sdtms/{sdtm_id}/validate` returns
 *   `202` with a Validation_Run resource. The run id is then polled via
 *   `GET /api/v1/validation-runs/{id}` ({@link useGetValidationRun}) through
 *   {@link useOperationPoll} at the 1-5s/120s cadence until the run reaches a
 *   terminal status (`passed`/`failed`).
 * - On a terminal status the run's status, per-severity counts, full
 *   {@link IssueList}, and validator name/version render (R14.2, R14.3, R14.4).
 * - A request `problem+json` — from either the start POST or a poll — surfaces
 *   its `title`/`detail` and any `issues[]` and stops polling (R14.5).
 */
export function SdtmValidationPanel({ sdtmId }: SdtmValidationPanelProps) {
  const qc = useQueryClient()
  const validate = useValidateSdtm()

  // The validation-run id returned by the `202` start POST. Polling is dormant
  // until this is set.
  const runId = validate.data?.id ?? null

  const poll = useOperationPoll<ValidationRunResponse>({
    operationId: runId,
    useGetOperation: useValidationRunOperation,
    intervalMs: OPERATION_POLL_PRESETS.fast.intervalMs,
    timeoutMs: OPERATION_POLL_PRESETS.fast.timeoutMs,
    terminalStatuses: SDTM_VALIDATION_TERMINAL,
  })

  // A completed `202` validation run advances the aggregate's latest-run state
  // and produces a validation-report artifact; once the run reaches a terminal
  // status, reload the study-scoped artifact collection and the aggregate
  // detail so dependent views refetch (R21.6). Keyed on the terminal run id so
  // it fires once per finished run.
  const terminalRunId =
    poll.phase === 'terminal' ? (poll.data?.id ?? runId) : null
  React.useEffect(() => {
    if (!terminalRunId) return
    invalidateSdtmOperationArtifacts(qc, sdtmId)
  }, [qc, sdtmId, terminalRunId])

  // A `problem+json` from the start POST (R14.5).
  const startProblem = validate.error
    ? parseProblem(validate.error as AxiosError)
    : null
  // A `problem+json` from a poll (R14.5).
  const pollProblem = poll.problem ? parseProblem(poll.problem) : null
  const problem = startProblem ?? pollProblem

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Validation"
        description={
          <>
            Run SDTM validation (
            <code>POST /api/v1/sdtms/{'{sdtm_id}'}/validate</code>) and review
            the resulting issues.
          </>
        }
        actions={
          <Button
            size="sm"
            onClick={() => validate.mutate({ sdtmId })}
            disabled={validate.isPending || poll.phase === 'polling'}
          >
            {(validate.isPending || poll.phase === 'polling') && (
              <Loader2 className="animate-spin" aria-hidden />
            )}
            Run validation
          </Button>
        }
      />

      {problem && (
        <div className="flex flex-col gap-3">
          <Notice
            title={
              (problem as { title?: string }).title ??
              problem.detail ??
              'Validation failed to run'
            }
            detail={
              (problem as { title?: string }).title
                ? problem.detail
                : undefined
            }
          />
          {problem.issues && problem.issues.length > 0 && (
            <IssueList
              issues={problem.issues as ReadonlyArray<Record<string, unknown>>}
            />
          )}
        </div>
      )}

      {/* Polling in flight after a `202`: spinner + elapsed clock. */}
      {poll.phase === 'polling' && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Loader2 className="size-4 animate-spin" aria-hidden />
              Running validation
            </CardTitle>
            <CardDescription>
              Polling for a result… ({Math.round(poll.elapsedMs / 1000)}s
              elapsed)
            </CardDescription>
          </CardHeader>
        </Card>
      )}

      {/* Client-side timeout: the run is still running server-side past the cap. */}
      {poll.phase === 'timed-out' && (
        <Notice
          title="The validation run did not finish in time"
          detail="The validation run is still running on the server. No result is available yet — check back shortly."
        />
      )}

      {/* Terminal (`passed`/`failed`): render the full run. */}
      {poll.phase === 'terminal' && poll.data ? (
        <ValidationRunView run={poll.data} />
      ) : (
        poll.phase === 'idle' &&
        !problem && (
          <EmptyState
            title="No validation run yet"
            description="Run validation to see the status, issue counts, and issues."
          />
        )
      )}
    </div>
  )
}

export default SdtmValidationPanel
