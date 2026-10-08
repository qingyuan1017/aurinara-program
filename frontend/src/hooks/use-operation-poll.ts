import { useCallback, useEffect, useRef, useState } from 'react'
import type { AxiosError } from 'axios'

/**
 * Shared polling hook for every `202` + status-resource flow in the Raw and
 * SDTM surface (Raw reconcile/artifacts; SDTM validate/compile/artifacts/
 * execute; aCRF/Define/cSDRG builds; Define reconcile).
 *
 * It wraps a generated "get operation" query with TanStack Query's
 * `refetchInterval` and a wall-clock deadline. While the operation is
 * non-terminal and the elapsed time is under the deadline it refetches at the
 * configured interval; once the resource reaches a terminal status, the
 * deadline passes, or a poll returns a `problem+json`, polling stops.
 *
 * Requirements: 7.2, 8.3, 14.1, 16.2, 17.7, 18.6, 18.7, 19.5 (and the related
 * 17.8, 18.8, 19.6 terminal/timeout semantics).
 */

/** Interval/cap presets per the requirements. */
export const OPERATION_POLL_PRESETS = {
  /**
   * 1-5s interval with a 120s cap: Raw reconcile/artifacts and SDTM
   * validate/compile/execute (Requirements 7.2, 8.3, 14.1, 16.2).
   */
  fast: { intervalMs: 2_000, timeoutMs: 120_000 },
  /**
   * Fixed 2s interval with a 300s cap: aCRF/Define/cSDRG builds and Define
   * reconcile (Requirements 17.7, 18.6, 18.7, 19.5).
   */
  build: { intervalMs: 2_000, timeoutMs: 300_000 },
} as const

/** Interval bounds for the 1-5s configurable presets. */
export const MIN_INTERVAL_MS = 1_000
export const MAX_INTERVAL_MS = 5_000

/** Terminal statuses recognised across operation resources. */
export const DEFAULT_TERMINAL_STATUSES = [
  'completed',
  'failed',
  'succeeded',
  'passed',
  'cancelled',
  'runner_not_configured',
] as const

export type OperationPhase =
  | 'idle'
  | 'polling'
  | 'terminal'
  | 'timed-out'
  | 'error'

/** A status-bearing operation resource. */
interface StatusResource {
  status?: string
}

/**
 * The thin adapter around a generated get-operation hook (e.g.
 * `useGetArtifactBuild`, `useGetReconciliationRun`, `useGetExecutionRun`,
 * `useGetValidationRun`). The hook forwards the computed `refetchInterval` and
 * `enabled` flag through `opts.query` so the generated query drives the actual
 * network polling, and reads back `data` + `error`.
 */
export interface OperationQueryOpts {
  query: {
    enabled: boolean
    refetchInterval: number | false
  }
}

export interface OperationQueryState<T> {
  data?: T
  error: AxiosError | null
}

export interface OperationPollOptions<T extends StatusResource> {
  /**
   * The operation/run/build id to poll. Polling is dormant (phase `idle`)
   * until this is a non-null id.
   */
  operationId: string | null
  /**
   * Wraps the generated get-operation query. Receives the id and the computed
   * query options (enabled + refetchInterval) and returns the current
   * `{ data, error }`.
   */
  useGetOperation: (id: string, opts: OperationQueryOpts) => OperationQueryState<T>
  /**
   * Base poll interval in milliseconds. Configurable presets are clamped to
   * the requirement's 1000-5000 window; the fixed-2s build preset passes 2000.
   */
  intervalMs: number
  /** Wall-clock deadline in milliseconds (120_000 or 300_000 per requirement). */
  timeoutMs: number
  /** Statuses treated as terminal. Defaults to {@link DEFAULT_TERMINAL_STATUSES}. */
  terminalStatuses?: readonly string[]
}

export interface OperationPollResult<T> {
  phase: OperationPhase
  /** The latest polled resource (final resource once terminal). */
  data: T | undefined
  /** The `problem+json` AxiosError that stopped polling, if any. */
  problem: AxiosError | null
  /** Milliseconds elapsed since polling started for the current operation. */
  elapsedMs: number
}

/** Clamp a configurable interval into the required 1-5s window. */
export function clampInterval(intervalMs: number): number {
  if (Number.isNaN(intervalMs)) return MIN_INTERVAL_MS
  return Math.min(Math.max(intervalMs, MIN_INTERVAL_MS), MAX_INTERVAL_MS)
}

export function useOperationPoll<T extends StatusResource>({
  operationId,
  useGetOperation,
  intervalMs,
  timeoutMs,
  terminalStatuses = DEFAULT_TERMINAL_STATUSES,
}: OperationPollOptions<T>): OperationPollResult<T> {
  const interval = clampInterval(intervalMs)

  // Wall-clock anchor: captured the first render an operationId is present and
  // reset whenever a new operation starts. `now` ticks on a timer so the
  // deadline is observed even between refetches (so `timed-out` is reached and
  // polling actually stops).
  const startRef = useRef<number | null>(null)
  const trackedIdRef = useRef<string | null>(null)
  const [now, setNow] = useState(() => Date.now())

  const stoppedRef = useRef(false)

  if (operationId !== trackedIdRef.current) {
    trackedIdRef.current = operationId
    startRef.current = operationId ? Date.now() : null
    stoppedRef.current = false
  }

  const startedAt = startRef.current
  const elapsedMs = startedAt === null ? 0 : Math.max(0, now - startedAt)
  const timedOut = startedAt !== null && elapsedMs >= timeoutMs

  const isTerminalStatus = useCallback(
    (s: string | undefined): boolean =>
      typeof s === 'string' && terminalStatuses.includes(s),
    [terminalStatuses],
  )

  // Keep the query mounted (so the final resource stays readable) but stop the
  // refetch loop once terminal, errored, or past the deadline.
  const enabled = operationId !== null
  const refetchInterval =
    operationId !== null && !timedOut && !stoppedRef.current ? interval : false

  const query = useGetOperation(operationId ?? '', {
    query: { enabled, refetchInterval },
  })

  const data = query.data
  const problem = query.error
  const isTerminal = isTerminalStatus(data?.status)

  // Latch the stop condition so the next render drops `refetchInterval` to
  // `false` and no further poll is scheduled.
  if ((isTerminal || problem) && !stoppedRef.current) {
    stoppedRef.current = true
  }

  // Drive a deadline timer so the component re-renders at the cap even if no
  // further refetch fires, flipping the phase to `timed-out` and halting polls.
  useEffect(() => {
    if (startedAt === null || isTerminal || problem) return
    const remaining = startedAt + timeoutMs - Date.now()
    if (remaining <= 0) {
      setNow(Date.now())
      return
    }
    const timer = window.setTimeout(() => setNow(Date.now()), remaining)
    return () => window.clearTimeout(timer)
  }, [startedAt, timeoutMs, isTerminal, problem])

  let phase: OperationPhase
  if (operationId === null) {
    phase = 'idle'
  } else if (problem) {
    phase = 'error'
  } else if (isTerminal) {
    phase = 'terminal'
  } else if (timedOut) {
    phase = 'timed-out'
  } else {
    phase = 'polling'
  }

  return { phase, data, problem, elapsedMs }
}

export default useOperationPoll
