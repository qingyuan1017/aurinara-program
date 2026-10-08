import * as React from 'react'
import { AlertTriangle, Loader2 } from 'lucide-react'
import type { AxiosError } from 'axios'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { cn } from '@/lib/utils'
import { parseProblem } from '@/lib/problems'
import {
  useOperationPoll,
  type OperationPollResult,
  type OperationQueryOpts,
  type OperationQueryState,
} from '@/hooks/use-operation-poll'

/**
 * Generic `202`+poll widget: a start trigger, a {@link useOperationPoll} loop,
 * and a terminal render-result slot. It drives every long-running Raw/SDTM
 * flow (Raw reconcile/artifacts; SDTM validate/compile/execute; aCRF/Define/
 * cSDRG builds; Define reconcile) and gives them one shape for the four
 * outcomes:
 *
 * - `polling` — a spinner and the elapsed clock while the backend works.
 * - successful terminal — defers to {@link OperationRunnerProps.renderResult},
 *   which lists artifacts/outputs/issues (Requirement 8.4, 14.1).
 * - `failed` terminal — renders the typed failure object recorded on the
 *   resource and presents no artifact/output (Requirement 8.5). A `failed`
 *   resource never reaches `renderResult`.
 * - client `timed-out` — a notice naming the affected run/build, distinct from
 *   a server-reported failure.
 *
 * A poll `problem+json` (`phase === 'error'`) surfaces its `title`/`detail`.
 */

/** A status-bearing operation resource (build/run) the runner can inspect. */
interface OperationResource {
  status?: string
  /** Typed failure object recorded on a failed terminal resource. */
  failure?: Record<string, unknown> | null
}

export interface OperationRunnerProps<T extends OperationResource> {
  /**
   * Human label for the operation, used verbatim in the timeout and failure
   * notices so they name the affected run/build (e.g. "artifact build",
   * "reconciliation run", "validation run").
   */
  operationLabel: string
  /**
   * The operation/run/build id to poll, or `null` before the start trigger has
   * produced one. The poll stays dormant (`idle`) until this is set.
   */
  operationId: string | null
  /** Wraps the generated get-operation query (forwarded to {@link useOperationPoll}). */
  useGetOperation: (id: string, opts: OperationQueryOpts) => OperationQueryState<T>
  /** Base poll interval in milliseconds (clamped to 1-5s by the hook). */
  intervalMs: number
  /** Wall-clock deadline in milliseconds (120_000 or 300_000 per requirement). */
  timeoutMs: number
  /** Statuses treated as terminal; forwarded to {@link useOperationPoll}. */
  terminalStatuses?: readonly string[]
  /**
   * Statuses treated as a *failure* terminal. When the terminal status is one
   * of these, the runner renders the typed failure and never calls
   * {@link renderResult}. Defaults to `['failed']`.
   */
  failureStatuses?: readonly string[]
  /**
   * Renders the successful terminal resource (artifacts, outputs, issue list).
   * Only called on a non-failure terminal status.
   */
  renderResult: (resource: T) => React.ReactNode
  /**
   * The start trigger. Rendered above the result; typically a configured
   * `<Button>` wired to the start mutation. Receives the current phase so it
   * can disable itself while polling.
   */
  renderTrigger?: (poll: OperationPollResult<T>) => React.ReactNode
  /** Optional start action rendered as a default button when `renderTrigger` is omitted. */
  onStart?: () => void
  /** Label for the default start button. */
  startLabel?: string
  /** Disable the default start button (e.g. gated by staleness/alignment). */
  startDisabled?: boolean
  className?: string
}

function problemText(error: AxiosError): { title: string; detail: string } {
  const problem = parseProblem(error)
  const title = (problem as { title?: string }).title ?? 'Operation failed'
  const detail = problem.detail ?? error.message ?? 'The request failed.'
  return { title, detail }
}

/** Extract a readable `{ code, detail }` from a typed failure object. */
function failureText(
  failure: Record<string, unknown> | null | undefined,
): { code?: string; detail?: string } {
  if (!failure || typeof failure !== 'object') return {}
  const code =
    typeof failure.code === 'string' ? failure.code : undefined
  const detail =
    typeof failure.detail === 'string'
      ? failure.detail
      : typeof failure.message === 'string'
        ? (failure.message as string)
        : undefined
  return { code, detail }
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
        'flex items-start gap-3 rounded-md border px-4 py-3 text-sm',
        tone === 'destructive'
          ? 'border-destructive/50 text-destructive'
          : 'border-border text-muted-foreground',
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

export function OperationRunner<T extends OperationResource>({
  operationLabel,
  operationId,
  useGetOperation,
  intervalMs,
  timeoutMs,
  terminalStatuses,
  failureStatuses = ['failed'],
  renderResult,
  renderTrigger,
  onStart,
  startLabel = 'Start',
  startDisabled,
  className,
}: OperationRunnerProps<T>) {
  const poll = useOperationPoll<T>({
    operationId,
    useGetOperation,
    intervalMs,
    timeoutMs,
    terminalStatuses,
  })

  const { phase, data, problem } = poll
  const isFailureTerminal =
    phase === 'terminal' &&
    typeof data?.status === 'string' &&
    failureStatuses.includes(data.status)

  return (
    <div className={cn('flex flex-col gap-4', className)}>
      {renderTrigger ? (
        renderTrigger(poll)
      ) : onStart ? (
        <div>
          <Button
            type="button"
            onClick={onStart}
            disabled={startDisabled || phase === 'polling'}
          >
            {phase === 'polling' && <Loader2 className="animate-spin" aria-hidden />}
            {startLabel}
          </Button>
        </div>
      ) : null}

      {phase === 'polling' && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Loader2 className="size-4 animate-spin" aria-hidden />
              Running {operationLabel}
            </CardTitle>
            <CardDescription>
              Polling for a result… ({Math.round(poll.elapsedMs / 1000)}s elapsed)
            </CardDescription>
          </CardHeader>
        </Card>
      )}

      {phase === 'error' && problem && (
        <Notice {...problemText(problem)} />
      )}

      {phase === 'timed-out' && (
        <Notice
          title={`The ${operationLabel} did not finish in time`}
          detail={`The ${operationLabel} is still running on the server after ${Math.round(
            timeoutMs / 1000,
          )}s. No result is available yet — check back shortly.`}
        />
      )}

      {isFailureTerminal &&
        (() => {
          const { code, detail } = failureText(data?.failure)
          return (
            <Notice
              title={`The ${operationLabel} failed`}
              detail={
                <span className="flex flex-col gap-1">
                  {code && (
                    <code className="text-xs font-semibold">{code}</code>
                  )}
                  <span>
                    {detail ??
                      'The operation reported a failure and produced no artifacts.'}
                  </span>
                </span>
              }
            />
          )
        })()}

      {phase === 'terminal' && !isFailureTerminal && data && renderResult(data)}
    </div>
  )
}

export default OperationRunner
