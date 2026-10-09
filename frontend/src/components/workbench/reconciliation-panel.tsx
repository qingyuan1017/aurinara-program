import * as React from 'react'
import type { AxiosError } from 'axios'
import { useQueryClient } from '@tanstack/react-query'

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { IssueList } from '@/components/data/issue-list'
import { OperationRunner } from '@/components/workbench/operation-runner'
import { useWorkbench } from '@/components/workbench/workbench-context'
import {
  OPERATION_POLL_PRESETS,
  type OperationQueryOpts,
  type OperationQueryState,
} from '@/hooks/use-operation-poll'
import { useIdempotencyKey } from '@/lib/requests'
import { parseProblem } from '@/lib/problems'
import {
  invalidateRawOperationArtifacts,
} from '@/lib/invalidate'
import {
  getGetRawAggregateQueryKey,
  useReconcileRawSourceSchema,
} from '@/api/generated/raw/raw'
import {
  getGetReconciliationQueryKey,
  useGetReconciliation,
} from '@/api/generated/reconciliation/reconciliation'
import type { ReconciliationResponse } from '@/api/generated/model'

/**
 * The 409 problem code the backend returns when the pinned expected Raw
 * revision is no longer current for a reconciliation request (Requirement 7.3).
 */
const STALE_RECONCILE_INPUT_CODE = 'stale_raw_reconciliation_input'

/** Terminal statuses for a reconciliation run (Requirement 7.2). */
const RECONCILE_TERMINAL_STATUSES = ['completed', 'failed'] as const

/**
 * Adapter around the generated `useGetReconciliation` query so it matches the
 * minimal `(id, opts) => { data, error }` shape {@link OperationRunner} expects
 * (the generated hook otherwise carries extra TanStack fields).
 */
function usePollReconciliationRun(
  id: string,
  opts: OperationQueryOpts,
): OperationQueryState<ReconciliationResponse> {
  const query = useGetReconciliation(id, {
    query: {
      enabled: opts.query.enabled,
      refetchInterval: opts.query.refetchInterval,
    },
  })
  return { data: query.data, error: query.error as AxiosError | null }
}

/**
 * Render the per-severity counts and full issue list of a terminal
 * reconciliation run (Requirement 7.4). The run carries both pre-counted
 * `error_count`/`warning_count`/`info_count` fields and the full `issues[]`
 * array in the common issue model, which `IssueList` renders (with its own
 * per-severity summary and empty state).
 */
function ReconciliationResult({
  run,
  rawId,
  studyId,
}: {
  run: ReconciliationResponse
  rawId: string
  studyId: string
}) {
  const qc = useQueryClient()
  // A completed `202` reconciliation produces a report artifact and advances
  // the aggregate's latest-run state; reload the study-scoped artifact
  // collection and the aggregate detail so dependent views refetch (R21.6).
  React.useEffect(() => {
    invalidateRawOperationArtifacts(qc, rawId, studyId)
  }, [qc, rawId, studyId, run.id])

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Reconciliation result</CardTitle>
          <CardDescription className="flex flex-wrap items-center gap-2">
            <span>Status:</span>
            <Badge variant={run.status === 'failed' ? 'destructive' : 'secondary'}>
              {run.status}
            </Badge>
            <Badge variant="destructive">Error: {run.error_count}</Badge>
            <Badge variant="secondary">Warning: {run.warning_count}</Badge>
            <Badge variant="outline">Info: {run.info_count}</Badge>
          </CardDescription>
        </CardHeader>
        <CardContent>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-3">
            <div>
              <dt className="text-muted-foreground text-xs">Run ID</dt>
              <dd className="text-sm break-all">{run.id}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground text-xs">Type</dt>
              <dd className="text-sm break-all">{run.reconciliation_type}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground text-xs">Version</dt>
              <dd className="text-sm break-all">
                {run.reconciliation_version}
              </dd>
            </div>
          </dl>
        </CardContent>
      </Card>

      <IssueList
        issues={run.issues as Record<string, unknown>[]}
        emptyTitle="No reconciliation issues"
        emptyDescription="This reconciliation run produced no issues."
      />
    </div>
  )
}

/**
 * Raw Reconciliation panel (Requirement 7).
 *
 * - Starts a reconciliation via `POST /api/v1/raw/{raw_id}/reconcile` with the
 *   expected current Raw revision and a stable `Idempotency-Key` (7.1, 21.2).
 * - On `202` it polls `GET /api/v1/reconciliation-runs/{id}` at 1-5s to a
 *   terminal status (`completed`/`failed`), capping at 120s with a timeout
 *   notice, via {@link OperationRunner} + `useOperationPoll` (7.2).
 * - A `409 stale_raw_reconciliation_input` shows a message that the expected
 *   revision is no longer current and offers a reload action that re-fetches
 *   the current Raw revision (7.3).
 * - A terminal run renders its per-severity counts and the full issue list
 *   (7.4).
 * - A reconcile request or poll `problem+json` surfaces its `title`/`detail`
 *   and stops polling (handled by `OperationRunner`/`useOperationPoll`) (7.5).
 */
export function ReconciliationPanel() {
  const { aggregate, studyId } = useWorkbench()
  const rawId = aggregate.id
  const qc = useQueryClient()

  // One stable Idempotency-Key per attempt, held across automatic retries.
  const idempotency = useIdempotencyKey()

  // The reconciliation-run id returned by the 202 start response; drives the
  // poll. Null until a start succeeds.
  const [runId, setRunId] = React.useState<string | null>(null)

  const reconcile = useReconcileRawSourceSchema({
    mutation: {
      onSuccess: (run) => {
        // The 202 body is the created reconciliation run; poll it by id.
        setRunId(run.id)
        void qc.invalidateQueries({
          queryKey: getGetReconciliationQueryKey(run.id),
        })
      },
    },
    request: idempotency.requestConfig,
  })

  const startError = reconcile.error as AxiosError | null
  const startProblem = startError ? parseProblem(startError) : null
  const isStaleInput =
    startError?.response?.status === 409 &&
    startProblem?.code === STALE_RECONCILE_INPUT_CODE
  // Any other start failure (non-stale) surfaces its problem detail/title.
  const isOtherStartError = !!startError && !isStaleInput

  async function handleStart() {
    // Mint a fresh key for this attempt so retries of this attempt reuse it,
    // and clear any prior run/error before starting.
    idempotency.begin()
    setRunId(null)
    reconcile.reset()
    try {
      await reconcile.mutateAsync({
        rawId,
        data: { expected_raw_revision: aggregate.revision },
      })
    } catch {
      // Error state is rendered inline from `reconcile.error`; the stale-input
      // reload action is offered below. Swallow to avoid an unhandled rejection.
    }
  }

  // 7.3: reload the current Raw aggregate revision so a retry pins the current
  // revision, and reset the mutation error.
  async function handleReloadRevision() {
    await qc.invalidateQueries({ queryKey: getGetRawAggregateQueryKey(rawId) })
    reconcile.reset()
  }

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Reconcile source schema</CardTitle>
          <CardDescription>
            Queue an immutable comparison of maintained Raw metadata against the
            bound source bytes via{' '}
            <code>POST /api/v1/raw/{'{raw_id}'}/reconcile</code>. The current
            revision (<span className="font-medium">{aggregate.revision}</span>)
            is pinned as the expected Raw revision.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <OperationRunner<ReconciliationResponse>
            operationLabel="reconciliation run"
            operationId={runId}
            useGetOperation={usePollReconciliationRun}
            intervalMs={OPERATION_POLL_PRESETS.fast.intervalMs}
            timeoutMs={OPERATION_POLL_PRESETS.fast.timeoutMs}
            terminalStatuses={RECONCILE_TERMINAL_STATUSES}
            onStart={handleStart}
            startLabel="Start reconciliation"
            startDisabled={reconcile.isPending}
            renderResult={(run) => (
              <ReconciliationResult run={run} rawId={rawId} studyId={studyId} />
            )}
          />
        </CardContent>
      </Card>

      {/* 7.3: stale expected-revision message + reload action. */}
      {isStaleInput && (
        <div
          role="alert"
          className="border-destructive/50 text-destructive flex flex-col gap-1 rounded-md border px-4 py-3 text-sm"
        >
          <span className="font-medium">
            The expected Raw revision is no longer current.
          </span>
          <span className="text-destructive/90">
            {startProblem?.detail ??
              'This workbench changed since you opened it. Reload the current revision before reconciling again.'}
          </span>
          <button
            type="button"
            onClick={handleReloadRevision}
            className="text-destructive mt-1 w-fit font-medium underline underline-offset-2"
          >
            Reload current revision
          </button>
        </div>
      )}

      {/* 7.5 (start request): any other start failure surfaces title/detail. */}
      {isOtherStartError && startProblem && (
        <div
          role="alert"
          className="border-destructive/50 text-destructive flex flex-col gap-1 rounded-md border px-4 py-3 text-sm"
        >
          <span className="font-medium">
            {startProblem.code ?? 'Reconciliation could not be started'}
          </span>
          <span className="text-destructive/90">
            {startProblem.detail ??
              startError?.message ??
              'The reconciliation request failed.'}
          </span>
        </div>
      )}
    </div>
  )
}

export default ReconciliationPanel
