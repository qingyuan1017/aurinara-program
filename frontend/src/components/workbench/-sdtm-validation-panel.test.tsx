// @vitest-environment jsdom
//
// Component tests for the SDTM Validation panel (`sdtm-validation-panel.tsx`) —
// task 13.3 (Requirements 14.1-14.5).
//
// Flows covered:
//   * trigger validation (R14.1): the start POST returns `202` + a
//     Validation_Run id, which the panel then polls to a terminal status;
//   * poll to terminal `passed`/`failed` (R14.2) via `useGetValidationRun`
//     through `useOperationPoll` — exercised under vitest fake timers exactly
//     like the `use-operation-poll` suite;
//   * render status + per-severity counts + validator name/version + the full
//     common `IssueList` (R14.2, R14.3, R14.4);
//   * a request `problem+json` renders its `title`/`detail` + `issues[]`
//     (R14.5) — asserted for both the start POST and a poll error.
//
// The repo has no MSW layer, so the generated `useValidateSdtm` /
// `useGetValidationRun` hooks are mocked. The validate mutation is a plain
// controllable fake; the get-validation-run query is the same faithful
// self-terminating fake used by the shared `useOperationPoll` tests, so the
// REAL polling logic (interval, terminal stop, problem stop) runs under fake
// timers.
import { act, fireEvent, render, screen, within } from '@testing-library/react'
import {
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from 'vitest'
import type { AxiosError } from 'axios'
import { useEffect, useRef, useState } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { installJsdomHarness } from '@/test/jsdom-harness'
import type {
  OperationQueryOpts,
  OperationQueryState,
} from '@/hooks/use-operation-poll'

beforeAll(() => {
  installJsdomHarness()
})

// ---------------------------------------------------------------------------
// The validate mutation stub: a controllable `UseMutationResult` whose
// `.mutate()` sets `data`/`error` and re-renders the panel. A ref holds the
// current scripted behaviour so a test can make validation 202-succeed (data
// with an `id`) or 422-fail (a problem+json error).
//
// Because the panel re-renders in response to the mutation (just as TanStack
// Query would push a state update after `mutate`), the mock hook subscribes to
// a tiny external store: `mutate` updates the store and notifies subscribers,
// forcing the panel to re-render with the new `data`/`error`.
// ---------------------------------------------------------------------------
interface ValidateState {
  data: { id: string } | undefined
  error: AxiosError | null
}

const validateStore: {
  state: ValidateState
  listeners: Set<() => void>
} = {
  state: { data: undefined, error: null },
  listeners: new Set(),
}

function setValidateState(next: ValidateState) {
  validateStore.state = next
  for (const listener of validateStore.listeners) listener()
}

// The script that runs when the panel calls `validate.mutate(...)`.
const validateOnMutate: { current: () => void } = { current: () => {} }

// ---------------------------------------------------------------------------
// The get-validation-run query: a faithful self-terminating fake that re-reads
// a scripted status source on the `refetchInterval` the poll asks for and halts
// on terminal/problem — identical to the shared useOperationPoll test harness.
// A per-test `source` drives the run's status progression.
// ---------------------------------------------------------------------------
interface Run {
  status: string
  [k: string]: unknown
}

let runSource: (pollIndex: number) => OperationQueryState<Run> = () => ({
  data: undefined,
  error: null,
})
const SDTM_TERMINAL = ['passed', 'failed'] as const
const pollState = { pollCount: 0 }

function isStop(s: OperationQueryState<Run>): boolean {
  return (
    s.error != null ||
    (typeof s.data?.status === 'string' &&
      SDTM_TERMINAL.includes(s.data.status as (typeof SDTM_TERMINAL)[number]))
  )
}

// `invalidate.ts` reaches into many generated modules at import time; stub the
// one helper the validation panel calls on a terminal run so this file need not
// mock the whole SDTM/raw/artifacts surface.
vi.mock('@/lib/invalidate', () => ({
  invalidateSdtmOperationArtifacts: vi.fn(),
}))

vi.mock('@/api/generated/sdtm/sdtm', () => {
  const useValidateSdtm = () => {
    // Subscribe to the external validate store so a `mutate` re-renders the
    // panel with the new data/error (mirroring a real mutation state push).
    const [, force] = useState(0)
    useEffect(() => {
      const listener = () => force((n) => n + 1)
      validateStore.listeners.add(listener)
      return () => {
        validateStore.listeners.delete(listener)
      }
    }, [])
    return {
      isPending: false,
      data: validateStore.state.data,
      error: validateStore.state.error,
      mutate: () => validateOnMutate.current(),
      mutateAsync: async () => validateStore.state.data,
    }
  }

  return { useValidateSdtm }
})

// `useGetValidationRun` now lives in the shared `validation` tag module (it is
// not re-exported from the SDTM tag), so mock it there. The faithful
// self-terminating poll fake mirrors the real
// `useGetValidationRun(runId, { query })` signature the panel's adapter calls.
vi.mock('@/api/generated/validation/validation', () => {
  const useGetValidationRun = (
    _runId: string,
    opts: { query: OperationQueryOpts['query'] & { retry?: boolean } },
  ): OperationQueryState<Run> => {
    const [, forceRender] = useState(0)
    const current = useRef<OperationQueryState<Run>>({ data: undefined, error: null })
    const stopped = useRef(false)
    const startedAt = useRef<number | null>(null)
    const startedRef = useRef(false)
    const timeoutMs = 120_000

    const { enabled, refetchInterval } = opts.query

    if (enabled && !startedRef.current) {
      startedRef.current = true
      startedAt.current = Date.now()
      current.current = runSource(pollState.pollCount)
      pollState.pollCount += 1
      stopped.current = isStop(current.current)
    }

    useEffect(() => {
      if (!enabled || typeof refetchInterval !== 'number') return
      if (stopped.current) return
      const timer = window.setInterval(() => {
        const started = startedAt.current ?? Date.now()
        if (stopped.current || Date.now() - started >= timeoutMs) {
          window.clearInterval(timer)
          return
        }
        current.current = runSource(pollState.pollCount)
        pollState.pollCount += 1
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

  return { useGetValidationRun }
})

// Import AFTER the mock so the panel binds to the stubs.
import { SdtmValidationPanel } from './sdtm-validation-panel'

function makeIssue(overrides: Record<string, unknown> = {}) {
  return {
    id: 'i1',
    code: 'SDTM_VAR_MISSING_LABEL',
    severity: 'error',
    message: 'Variable AGE is missing a label.',
    suggestion: 'Add a label in the specification.',
    entity_type: 'variable',
    entity_id: 'var-age',
    field_path: 'variables[0].label',
    dataset: 'DM',
    variable: 'AGE',
    ...overrides,
  }
}

function makeRun(overrides: Partial<Run> = {}): Run {
  return {
    id: 'run-1',
    study_id: 'study-1',
    module_key: 'sdtm',
    owner_type: 'sdtm',
    owner_id: 'sdtm-1',
    status: 'passed',
    validator_name: 'sdtm-validator',
    validator_version: '1.4.2',
    input_fingerprint: 'fp-1',
    started_at: '2024-01-01T00:00:00Z',
    completed_at: '2024-01-01T00:00:05Z',
    error_count: 0,
    warning_count: 0,
    info_count: 0,
    issues: [],
    report_artifact_ids: [],
    failure: null,
    created_by: 'user-1',
    ...overrides,
  }
}

function problemError(
  status: number,
  body: Record<string, unknown>,
): AxiosError {
  return {
    isAxiosError: true,
    message: 'Request failed',
    response: { status, data: body },
  } as unknown as AxiosError
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(0)
  validateStore.state = { data: undefined, error: null }
  validateStore.listeners.clear()
  validateOnMutate.current = () => {}
  runSource = () => ({ data: undefined, error: null })
  pollState.pollCount = 0
})

afterEach(() => {
  act(() => {
    vi.runOnlyPendingTimers()
  })
  vi.useRealTimers()
  vi.clearAllMocks()
})

function renderPanel() {
  // The panel reads a QueryClient to invalidate artifact/aggregate collections
  // once a validation run reaches a terminal status, so provide one.
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={qc}>
      <SdtmValidationPanel sdtmId="sdtm-1" />
    </QueryClientProvider>,
  )
}

// ===========================================================================
// Idle: no run yet
// ===========================================================================
describe('SDTM validation idle state', () => {
  it('shows the no-run empty state before any validation', () => {
    renderPanel()
    expect(screen.getByText(/no validation run yet/i)).toBeTruthy()
  })
})

// ===========================================================================
// Poll to terminal `passed`: counts + validator + full IssueList
// (Req 14.1, 14.2, 14.3, 14.4)
// ===========================================================================
describe('SDTM validation polls a 202 run to a terminal status (Req 14.1-14.4)', () => {
  it('polls to `passed` and renders counts, validator name/version, and the empty IssueList', () => {
    // The 202 start POST yields a run id; the run polls running -> passed.
    validateOnMutate.current = () => {
      setValidateState({ data: { id: 'run-1' }, error: null })
    }
    runSource = (i) =>
      i < 1
        ? { data: makeRun({ status: 'running' }), error: null }
        : { data: makeRun({ status: 'passed' }), error: null }

    renderPanel()

    act(() => {
      fireEvent.click(screen.getByRole('button', { name: /run validation/i }))
    })
    // One poll interval later the run settles `passed` (R14.2).
    act(() => {
      vi.advanceTimersByTime(2_000)
    })

    // The validation-run summary card renders (exact title).
    expect(screen.getByText('Validation run')).toBeTruthy()
    // Per-severity counts render on the run card (split text nodes) (R14.3).
    const runCard = screen.getByText('Validation run').closest(
      '[data-slot="card"]',
    ) as HTMLElement
    expect(within(runCard).getByText(/Error:/)).toBeTruthy()
    expect(within(runCard).getByText(/Warning:/)).toBeTruthy()
    expect(within(runCard).getByText(/Info:/)).toBeTruthy()
    // Validator name + version (R14.4).
    expect(within(runCard).getByText(/sdtm-validator/)).toBeTruthy()
    expect(within(runCard).getByText(/1\.4\.2/)).toBeTruthy()
    // The empty IssueList state renders for a clean run.
    expect(screen.getByText('No issues')).toBeTruthy()
  })

  it('polls to `failed`, shows the block notice, and renders the full common issue list (Req 14.2, 14.3)', () => {
    validateOnMutate.current = () => {
      setValidateState({ data: { id: 'run-2' }, error: null })
    }
    const failedRun = makeRun({
      status: 'failed',
      error_count: 1,
      warning_count: 1,
      issues: [
        makeIssue(),
        makeIssue({
          id: 'i2',
          code: 'SDTM_VAR_LENGTH_SHORT',
          severity: 'warning',
          message: 'Length too short.',
        }),
      ],
    })
    runSource = (i) =>
      i < 1
        ? { data: makeRun({ status: 'running' }), error: null }
        : { data: failedRun, error: null }

    renderPanel()
    act(() => {
      fireEvent.click(screen.getByRole('button', { name: /run validation/i }))
    })
    act(() => {
      vi.advanceTimersByTime(2_000)
    })

    // The failed-run block notice is shown (error-severity blocks downstream).
    expect(screen.getByText('Validation failed')).toBeTruthy()
    expect(screen.getByText(/block sdtm generation and execution/i)).toBeTruthy()
    // Counts reflect the failed run on the run summary card.
    const runCard = screen.getByText('Validation run').closest(
      '[data-slot="card"]',
    ) as HTMLElement
    expect(within(runCard).getByText(/Error:/)).toBeTruthy()
    expect(within(runCard).getByText(/Warning:/)).toBeTruthy()
    // The full common issue model renders (code + message + metadata) (R14.3).
    expect(screen.getByText('SDTM_VAR_MISSING_LABEL')).toBeTruthy()
    expect(screen.getByText('SDTM_VAR_LENGTH_SHORT')).toBeTruthy()
    expect(screen.getByText('Variable AGE is missing a label.')).toBeTruthy()
    expect(screen.getByText('Length too short.')).toBeTruthy()
    // Both issues render their common-model metadata (field_path), one per issue.
    expect(screen.getAllByText('variables[0].label').length).toBe(2)
  })
})

// ===========================================================================
// Problem surfacing (Req 14.5)
// ===========================================================================
describe('SDTM validation surfaces a request problem+json (Req 14.5)', () => {
  it('renders the start POST problem title/detail + issues[]', () => {
    // The start POST itself returns a problem+json (no run id, no polling).
    validateOnMutate.current = () => {
      setValidateState({
        data: undefined,
        error: problemError(422, {
          title: 'Validation could not start',
          detail: 'The derivation plan is misaligned.',
          issues: [makeIssue({ message: 'Plan is misaligned with the specification.' })],
        }),
      })
    }

    renderPanel()
    act(() => {
      fireEvent.click(screen.getByRole('button', { name: /run validation/i }))
    })

    // The problem title + detail surface (R14.5)…
    expect(screen.getByText('Validation could not start')).toBeTruthy()
    expect(screen.getByText('The derivation plan is misaligned.')).toBeTruthy()
    // …and the problem's issues[] render.
    expect(
      screen.getByText('Plan is misaligned with the specification.'),
    ).toBeTruthy()
    // No run view is shown.
    expect(screen.queryByText(/validation run/i)).toBeNull()
  })

  it('surfaces a poll problem+json and stops polling (Req 14.5)', () => {
    validateOnMutate.current = () => {
      setValidateState({ data: { id: 'run-3' }, error: null })
    }
    const pollProblem = problemError(409, {
      title: 'Run lookup failed',
      detail: 'The validation run input is stale.',
    })
    // Healthy first read, then a problem+json on the next poll.
    runSource = (i) =>
      i < 1
        ? { data: makeRun({ status: 'running' }), error: null }
        : { data: makeRun({ status: 'running' }), error: pollProblem }

    renderPanel()
    act(() => {
      fireEvent.click(screen.getByRole('button', { name: /run validation/i }))
    })
    const countAtStart = pollState.pollCount
    act(() => {
      vi.advanceTimersByTime(2_000) // poll #2 -> problem
    })

    // The poll problem's title/detail surface (R14.5).
    expect(screen.getByText('Run lookup failed')).toBeTruthy()
    expect(screen.getByText('The validation run input is stale.')).toBeTruthy()

    // Polling halts after surfacing the problem.
    const countAtError = pollState.pollCount
    expect(countAtError).toBeGreaterThan(countAtStart)
    act(() => {
      vi.advanceTimersByTime(60_000)
    })
    expect(pollState.pollCount).toBe(countAtError)
  })
})
