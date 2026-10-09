// @vitest-environment jsdom
//
// `useOperationPoll` is a React hook driven by wall-clock time and TanStack
// Query's `refetchInterval`, so this suite runs under jsdom with vitest fake
// timers. The hook does NOT issue network requests itself: it hands a computed
// `refetchInterval` to a generated get-operation query and reads back the
// resulting `{ data, error }`. The fake adapter below stands in for that
// generated query, re-polling on the interval the hook asks for exactly as
// TanStack Query would, so the test exercises the real interval/deadline/stop
// logic rather than a mock of it.
import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AxiosError } from 'axios'
import { useEffect, useRef, useState } from 'react'

import {
  OPERATION_POLL_PRESETS,
  useOperationPoll,
  type OperationQueryOpts,
  type OperationQueryState,
} from './use-operation-poll'

interface Run {
  status?: string
}

/**
 * Build a fake get-operation hook that emulates how TanStack Query drives
 * `useOperationPoll`'s refetch loop: while the hook asks for a numeric
 * `refetchInterval` it re-reads the current status on that cadence and
 * re-renders; the moment the hook settles the operation (a terminal status or a
 * `problem+json`) the loop stops — which is exactly when a real query, told
 * `refetchInterval: false`, would stop scheduling fetches.
 *
 * The self-termination is driven by the observed resource, not by inspecting
 * the hook: under vitest fake timers `advanceTimersByTime` drains all due timer
 * callbacks synchronously before React flushes effects, so a plain
 * `setInterval` cleared in an effect would over-fire. Re-reading the source and
 * halting on the same terminal/error condition the hook keys off keeps the fake
 * faithful without peeking at hook internals.
 *
 * `pollCount` records how many reads happened, letting a test assert the
 * cadence (interval) and that polling actually stops.
 */
function makeFakeOperation(
  source: (pollIndex: number) => OperationQueryState<Run>,
  terminalStatuses: readonly string[],
  timeoutMs: number,
) {
  const state = { pollCount: 0 }

  const isStop = (s: OperationQueryState<Run>): boolean =>
    s.error != null ||
    (typeof s.data?.status === 'string' &&
      terminalStatuses.includes(s.data.status))

  const useFakeOperation = (
    _id: string,
    opts: OperationQueryOpts,
  ): OperationQueryState<Run> => {
    const [, forceRender] = useState(0)
    const current = useRef<OperationQueryState<Run>>({ data: undefined, error: null })
    const stopped = useRef(false)
    const startedAt = useRef<number | null>(null)

    const { enabled, refetchInterval } = opts.query

    // Mirror a query's immediate initial fetch when it first becomes enabled.
    const startedRef = useRef(false)
    if (enabled && !startedRef.current) {
      startedRef.current = true
      startedAt.current = Date.now()
      current.current = source(state.pollCount)
      state.pollCount += 1
      stopped.current = isStop(current.current)
    }

    // Re-poll on the cadence the hook requests. The loop halts on exactly the
    // conditions under which the hook drops `refetchInterval` to false — a
    // terminal/problem resource or the wall-clock deadline — so a real query
    // would stop scheduling fetches at the same instant. Computing the stop
    // from the same inputs (rather than peeking at a re-render that fake timers
    // would not interleave mid-advance) keeps the fake a faithful stand-in.
    useEffect(() => {
      if (!enabled || typeof refetchInterval !== 'number') return
      if (stopped.current) return
      const timer = window.setInterval(() => {
        const started = startedAt.current ?? Date.now()
        if (stopped.current || Date.now() - started >= timeoutMs) {
          window.clearInterval(timer)
          return
        }
        current.current = source(state.pollCount)
        state.pollCount += 1
        if (isStop(current.current)) {
          stopped.current = true
          window.clearInterval(timer)
        }
        forceRender((n) => n + 1)
      }, refetchInterval)
      return () => window.clearInterval(timer)
    }, [enabled, refetchInterval])

    return current.current
  }

  return { useFakeOperation, state }
}

/** Terminal statuses the fake treats as stop conditions in these tests. */
const TERMINAL = ['completed', 'failed'] as const

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(0)
})

afterEach(() => {
  // Flush any timer the hook still has armed (e.g. its deadline timer) inside
  // `act` so a trailing state update does not warn about an unwrapped update.
  act(() => {
    vi.runOnlyPendingTimers()
  })
  vi.useRealTimers()
})

describe('useOperationPoll', () => {
  it('is idle with no operationId and issues no polls', () => {
    const { useFakeOperation, state } = makeFakeOperation(
      () => ({ data: { status: 'running' }, error: null }),
      TERMINAL,
      OPERATION_POLL_PRESETS.fast.timeoutMs,
    )

    const { result } = renderHook(() =>
      useOperationPoll<Run>({
        operationId: null,
        useGetOperation: useFakeOperation,
        intervalMs: OPERATION_POLL_PRESETS.fast.intervalMs,
        timeoutMs: OPERATION_POLL_PRESETS.fast.timeoutMs,
      }),
    )

    expect(result.current.phase).toBe('idle')
    expect(state.pollCount).toBe(0)
  })

  it('polls at the configured interval while non-terminal', () => {
    const { useFakeOperation, state } = makeFakeOperation(
      () => ({ data: { status: 'running' }, error: null }),
      TERMINAL,
      120_000,
    )

    const { result } = renderHook(() =>
      useOperationPoll<Run>({
        operationId: 'op-1',
        useGetOperation: useFakeOperation,
        intervalMs: 2_000,
        timeoutMs: 120_000,
      }),
    )

    // Initial read on mount.
    expect(result.current.phase).toBe('polling')
    expect(state.pollCount).toBe(1)

    // Each 2s tick triggers exactly one additional poll.
    act(() => {
      vi.advanceTimersByTime(2_000)
    })
    expect(state.pollCount).toBe(2)

    act(() => {
      vi.advanceTimersByTime(4_000)
    })
    expect(state.pollCount).toBe(4)
    expect(result.current.phase).toBe('polling')
  })

  it('clamps a sub-second interval up to the 1s floor', () => {
    const { useFakeOperation, state } = makeFakeOperation(
      () => ({ data: { status: 'running' }, error: null }),
      TERMINAL,
      120_000,
    )

    renderHook(() =>
      useOperationPoll<Run>({
        operationId: 'op-clamp',
        useGetOperation: useFakeOperation,
        intervalMs: 100, // below the 1000ms floor
        timeoutMs: 120_000,
      }),
    )

    expect(state.pollCount).toBe(1)
    // Nothing fires before the clamped 1s floor...
    act(() => {
      vi.advanceTimersByTime(999)
    })
    expect(state.pollCount).toBe(1)
    // ...and a poll fires exactly at 1s.
    act(() => {
      vi.advanceTimersByTime(1)
    })
    expect(state.pollCount).toBe(2)
  })

  it('stops polling when the resource reaches a terminal status', () => {
    // Non-terminal for the first two reads, then terminal.
    const { useFakeOperation, state } = makeFakeOperation(
      (i) => ({ data: { status: i < 2 ? 'running' : 'completed' }, error: null }),
      TERMINAL,
      120_000,
    )

    const { result } = renderHook(() =>
      useOperationPoll<Run>({
        operationId: 'op-term',
        useGetOperation: useFakeOperation,
        intervalMs: 2_000,
        timeoutMs: 120_000,
      }),
    )

    expect(result.current.phase).toBe('polling')

    act(() => {
      vi.advanceTimersByTime(2_000) // poll #2 -> still running
    })
    expect(result.current.phase).toBe('polling')

    act(() => {
      vi.advanceTimersByTime(2_000) // poll #3 -> completed
    })
    expect(result.current.phase).toBe('terminal')
    expect(result.current.data?.status).toBe('completed')

    const countAtTerminal = state.pollCount
    // No further polling once terminal, even as time marches on.
    act(() => {
      vi.advanceTimersByTime(60_000)
    })
    expect(state.pollCount).toBe(countAtTerminal)
  })

  it('enters timed-out at the deadline and stops polling', () => {
    const { useFakeOperation, state } = makeFakeOperation(
      () => ({ data: { status: 'running' }, error: null }),
      TERMINAL,
      10_000,
    )

    const { result } = renderHook(() =>
      useOperationPoll<Run>({
        operationId: 'op-timeout',
        useGetOperation: useFakeOperation,
        intervalMs: 2_000,
        timeoutMs: 10_000,
      }),
    )

    expect(result.current.phase).toBe('polling')

    // Advance up to just before the 10s cap: still polling.
    act(() => {
      vi.advanceTimersByTime(8_000)
    })
    expect(result.current.phase).toBe('polling')

    // Cross the deadline: a dedicated deadline timer flips phase to timed-out.
    act(() => {
      vi.advanceTimersByTime(2_000)
    })
    expect(result.current.phase).toBe('timed-out')

    const countAtTimeout = state.pollCount
    // Polling has stopped: no further reads after the cap.
    act(() => {
      vi.advanceTimersByTime(30_000)
    })
    expect(state.pollCount).toBe(countAtTimeout)
  })

  it('stops and surfaces the problem body on a problem+json error', () => {
    const problem = {
      response: {
        data: {
          type: 'about:blank',
          title: 'Reconciliation failed',
          detail: 'The input fingerprint is stale.',
        },
      },
    } as unknown as AxiosError

    // Healthy for the first read, then a problem+json on the next poll.
    const { useFakeOperation, state } = makeFakeOperation(
      (i) =>
        i < 1
          ? { data: { status: 'running' }, error: null }
          : { data: { status: 'running' }, error: problem },
      TERMINAL,
      120_000,
    )

    const { result } = renderHook(() =>
      useOperationPoll<Run>({
        operationId: 'op-problem',
        useGetOperation: useFakeOperation,
        intervalMs: 2_000,
        timeoutMs: 120_000,
      }),
    )

    expect(result.current.phase).toBe('polling')

    act(() => {
      vi.advanceTimersByTime(2_000) // poll #2 -> problem
    })

    expect(result.current.phase).toBe('error')
    const body = result.current.problem?.response?.data as {
      title?: string
      detail?: string
    }
    expect(body?.title).toBe('Reconciliation failed')
    expect(body?.detail).toBe('The input fingerprint is stale.')

    const countAtError = state.pollCount
    // Polling halts after surfacing the problem.
    act(() => {
      vi.advanceTimersByTime(60_000)
    })
    expect(state.pollCount).toBe(countAtError)
  })
})
