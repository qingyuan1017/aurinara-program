import * as React from 'react'
import type { AxiosError } from 'axios'
import { Loader2 } from 'lucide-react'

import { StatusBadge } from '@/components/data/status-badge'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import {
  useOperationPoll,
  OPERATION_POLL_PRESETS,
  type OperationQueryOpts,
  type OperationQueryState,
} from '@/hooks/use-operation-poll'
import { useGetDatasetImport } from '@/api/generated/raw/raw'
import type {
  RawDatasetImportResponse,
  RawDatasetImportResponseStatus,
  ValidationIssue,
} from '@/api/generated/model'
import { cn } from '@/lib/utils'
import { parseProblem } from '@/lib/problems'

/**
 * Terminal statuses for a bulk dataset import. The import service settles to
 * `succeeded`, `failed`, or `cancelled`.
 */
export const IMPORT_TERMINAL = ['succeeded', 'failed', 'cancelled'] as const

export interface RawBulkImportStatusProps {
  /** The import id returned by the `202` submit. */
  importId: string
  /** Called on each render with the current status (for the dialog's gating). */
  onStatus?: (status: RawDatasetImportResponseStatus) => void
  /** Called once the import reaches a terminal status. */
  onTerminal?: (response: RawDatasetImportResponse) => void
}

/**
 * Adapts {@link useGetDatasetImport} to the {@link useOperationPoll} contract:
 * forwards the computed `enabled`/`refetchInterval` and disables `retry` so a
 * `problem+json` surfaces immediately and halts polling.
 */
function useDatasetImportOperation(
  id: string,
  opts: OperationQueryOpts,
): OperationQueryState<RawDatasetImportResponse> {
  const query = useGetDatasetImport(id, {
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

/** Render a single per-entry validation issue (failure detail). */
function IssueRow({ issue }: { issue: ValidationIssue }) {
  const locationParts = [
    issue.dataset ? `dataset ${issue.dataset}` : null,
    issue.variable ? `variable ${issue.variable}` : null,
    issue.field_path ? issue.field_path : null,
  ].filter((part): part is string => !!part)

  return (
    <li className="flex flex-col gap-0.5 rounded-md border px-3 py-2">
      <span className="flex items-center gap-2">
        <StatusBadge status={issue.severity} />
        <code className="text-xs font-semibold">{issue.code}</code>
        {locationParts.length > 0 && (
          <span className="text-muted-foreground text-xs">
            {locationParts.join(' · ')}
          </span>
        )}
      </span>
      <span>{issue.message}</span>
      {issue.suggestion && (
        <span className="text-muted-foreground text-xs">{issue.suggestion}</span>
      )}
    </li>
  )
}

/**
 * The inline status/polling panel (phase 3). It drives the shared
 * {@link useOperationPoll} over {@link useDatasetImportOperation} until the
 * import reaches a terminal status, then renders the all-or-nothing outcome:
 *
 * - `succeeded` → N datasets created (count only; no object keys);
 * - `failed`   → the typed failure object plus the per-entry issue list;
 * - `cancelled`→ a neutral notice stating no datasets were created.
 *
 * It never implies partial success. The parent gates the cancel control and
 * fires invalidation via {@link RawBulkImportStatusProps.onStatus}/`onTerminal`.
 */
export function RawBulkImportStatus({
  importId,
  onStatus,
  onTerminal,
}: RawBulkImportStatusProps) {
  const poll = useOperationPoll<RawDatasetImportResponse>({
    operationId: importId,
    useGetOperation: useDatasetImportOperation,
    intervalMs: OPERATION_POLL_PRESETS.fast.intervalMs,
    timeoutMs: OPERATION_POLL_PRESETS.fast.timeoutMs,
    terminalStatuses: IMPORT_TERMINAL,
  })

  const response = poll.data
  const status = response?.status

  // Surface the current status to the parent so it can gate the cancel control.
  React.useEffect(() => {
    if (status) onStatus?.(status)
  }, [status, onStatus])

  // Fire the terminal callback once per settled import.
  const terminalId =
    poll.phase === 'terminal' && response ? response.id : null
  React.useEffect(() => {
    if (terminalId && response) onTerminal?.(response)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [terminalId])

  const pollProblem = poll.problem ? parseProblem(poll.problem) : null
  const failure = response?.failure as Record<string, unknown> | null | undefined
  const terminal = poll.phase === 'terminal' && response ? response : undefined

  return (
    <div className="flex flex-col gap-4">
      {/* In-flight polling: spinner + progress + elapsed clock. */}
      {poll.phase === 'polling' && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Loader2 className="size-4 animate-spin" aria-hidden />
              Importing datasets
            </CardTitle>
            <CardDescription className="flex flex-wrap items-center gap-2">
              {status && <StatusBadge status={status} />}
              <span>
                {response
                  ? `Inspected ${response.files_inspected} of ${response.entry_count} files`
                  : 'Starting…'}{' '}
                ({Math.round(poll.elapsedMs / 1000)}s elapsed)
              </span>
            </CardDescription>
          </CardHeader>
        </Card>
      )}

      {/* A `problem+json` from a poll (e.g. 404/403): polling stops. */}
      {pollProblem && (
        <Notice
          title={pollProblem.title ?? 'The import status could not be loaded'}
          detail={pollProblem.detail}
        />
      )}

      {/* Client timeout: the import is still running server-side. */}
      {poll.phase === 'timed-out' && (
        <Notice
          tone="muted"
          title="The import did not finish in time"
          detail="The import is still running on the server. No result is available yet — check back shortly."
        />
      )}

      {/* Terminal outcome (all-or-nothing). */}
      {terminal && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Import result</CardTitle>
            <CardDescription className="flex flex-wrap items-center gap-2">
              <StatusBadge status={terminal.status} />
              <span>
                {terminal.entry_count} dataset
                {terminal.entry_count === 1 ? '' : 's'} requested
              </span>
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            {terminal.status === 'succeeded' && (
              <Notice
                tone="muted"
                title={`${terminal.result_dataset_ids.length} dataset${
                  terminal.result_dataset_ids.length === 1 ? '' : 's'
                } created`}
                detail="The import completed and every requested dataset was created."
              />
            )}

            {terminal.status === 'cancelled' && (
              <Notice
                tone="muted"
                title="The import was cancelled"
                detail="No datasets were created."
              />
            )}

            {terminal.status === 'failed' && (
              <>
                <Notice
                  title="The import failed"
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
                          : 'No datasets were created. Review the per-entry issues below.'}
                      </span>
                    </span>
                  }
                />
                {terminal.issues.length > 0 && (
                  <ul className="flex flex-col gap-2">
                    {terminal.issues.map((issue) => (
                      <IssueRow key={issue.id} issue={issue} />
                    ))}
                  </ul>
                )}
              </>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  )
}

export default RawBulkImportStatus
