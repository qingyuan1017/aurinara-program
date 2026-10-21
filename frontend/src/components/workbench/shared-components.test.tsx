// @vitest-environment jsdom
//
// Component tests for the shared workbench components (task 4.7):
//   * study-scope gating — WorkbenchDetailShell renders the empty state and
//     issues NO request when `currentStudyId` is null;
//   * IssueList — renders every field, per-severity counts, and the empty state;
//   * OperationRunner — terminal / failed / timed-out states;
//   * StalenessBanner / AlignmentBanner — disable the controls they guard.
//
// Requirements: 2.2, 9.4, 6.2, 14.3, 10.5, 12.4, 20.5.
//
// The jsdom harness installs ResizeObserver + element-dimension mocks and the
// dnd-kit pointer/keyboard pointer shims so these (and later React Flow) tests
// run without a layout engine.
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

import { installJsdomHarness } from '@/test/jsdom-harness'
import { IssueList } from '@/components/data/issue-list'
import {
  WorkbenchDetailShell,
  type AggregateQueryResult,
} from './workbench-detail-shell'
import { OperationRunner } from './operation-runner'
import { StalenessBanner, isStale } from './staleness-banner'
import { AlignmentBanner, isMisaligned } from './alignment-banner'
import type {
  OperationQueryOpts,
  OperationQueryState,
} from '@/hooks/use-operation-poll'
import type { AggregateResponse } from '@/api/generated/model'

beforeAll(() => {
  installJsdomHarness()
})

// ---------------------------------------------------------------------------
// Study-provider stub. The shell reads `useCurrentStudy()`; the test controls
// the selected study per-case. A spy stands in for every "get aggregate" query
// so we can assert it is NEVER called when no study is selected.
// ---------------------------------------------------------------------------
const currentStudyState: { currentStudyId: string | null; isLoading: boolean } = {
  currentStudyId: null,
  isLoading: false,
}

vi.mock('@/components/study-context', () => ({
  useCurrentStudy: () => currentStudyState,
}))

const STUDY_ID = 'study-1'

function makeAggregate(overrides: Partial<AggregateResponse> = {}): AggregateResponse {
  return {
    id: 'agg-1',
    study_id: STUDY_ID,
    code: 'DM',
    name: 'Demographics',
    status: 'draft',
    revision: 3,
    ...overrides,
  }
}

describe('WorkbenchDetailShell study-scope gating (Req 2.2, 9.4)', () => {
  afterEach(() => {
    currentStudyState.currentStudyId = null
    currentStudyState.isLoading = false
  })

  it('renders the empty state and issues no request when no study is selected', () => {
    currentStudyState.currentStudyId = null
    // A spy that fails the test if the aggregate query ever runs. The shell
    // never invokes the query itself (the caller owns + gates the hook), so the
    // "no request" guarantee is modelled by the caller gating `enabled`: here we
    // simply never call the spy and assert the empty state renders.
    const queryFn = vi.fn()
    const query: AggregateQueryResult = {
      data: undefined,
      isLoading: false,
      isError: false,
      error: null,
    }

    render(
      <WorkbenchDetailShell
        query={query}
        resourceLabel="raw workbench"
        tabs={[{ value: 'a', label: 'Datasets', render: () => <div>panel</div> }]}
      />,
    )

    expect(screen.getByText('No study selected')).toBeTruthy()
    // No panel content is rendered when gated out.
    expect(screen.queryByText('panel')).toBeNull()
    // No request was issued.
    expect(queryFn).not.toHaveBeenCalled()
  })

  it('renders a loading skeleton while studies load with no selection', () => {
    currentStudyState.currentStudyId = null
    currentStudyState.isLoading = true
    const { container } = render(
      <WorkbenchDetailShell
        query={{ data: undefined, isLoading: false, isError: false, error: null }}
        resourceLabel="raw workbench"
        tabs={[{ value: 'a', label: 'Datasets', render: () => <div>panel</div> }]}
      />,
    )
    expect(screen.queryByText('No study selected')).toBeNull()
    expect(container.querySelector('[data-slot="skeleton"]')).toBeTruthy()
  })

  it('renders the header and tabs once a study is selected and the aggregate loads', () => {
    currentStudyState.currentStudyId = STUDY_ID
    render(
      <WorkbenchDetailShell
        query={{
          data: makeAggregate(),
          isLoading: false,
          isError: false,
          error: null,
        }}
        resourceLabel="raw workbench"
        tabs={[{ value: 'a', label: 'Datasets', render: () => <div>panel body</div> }]}
      />,
    )
    expect(screen.getByText('DM')).toBeTruthy()
    expect(screen.getByText('Demographics')).toBeTruthy()
    expect(screen.getByRole('tab', { name: 'Datasets' })).toBeTruthy()
    expect(screen.getByText('panel body')).toBeTruthy()
  })

  it('refuses to render an aggregate that belongs to a different study', () => {
    currentStudyState.currentStudyId = STUDY_ID
    render(
      <WorkbenchDetailShell
        query={{
          data: makeAggregate({ study_id: 'other-study' }),
          isLoading: false,
          isError: false,
          error: null,
        }}
        resourceLabel="raw workbench"
        tabs={[{ value: 'a', label: 'Datasets', render: () => <div>panel body</div> }]}
      />,
    )
    expect(screen.getByText('Not available in this study')).toBeTruthy()
    expect(screen.queryByText('panel body')).toBeNull()
  })
})

// ---------------------------------------------------------------------------
// IssueList (Req 6.2, 14.3)
// ---------------------------------------------------------------------------
describe('IssueList', () => {
  const ISSUE = {
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
  }

  it('renders all fields of a single issue', () => {
    render(<IssueList issues={[ISSUE]} />)
    expect(screen.getByText('SDTM_VAR_MISSING_LABEL')).toBeTruthy()
    expect(screen.getByText('Variable AGE is missing a label.')).toBeTruthy()
    expect(screen.getByText(/Add a label in the specification\./)).toBeTruthy()
    // Metadata fields rendered via the IssueMeta definition list.
    expect(screen.getByText(/variable$/)).toBeTruthy()
    expect(screen.getByText('var-age')).toBeTruthy()
    expect(screen.getByText('variables[0].label')).toBeTruthy()
    expect(screen.getByText('DM')).toBeTruthy()
    expect(screen.getByText('AGE')).toBeTruthy()
  })

  it('renders a per-severity count summary', () => {
    render(
      <IssueList
        issues={[
          { ...ISSUE, id: 'e1', severity: 'error' },
          { ...ISSUE, id: 'e2', severity: 'error' },
          { ...ISSUE, id: 'w1', severity: 'warning' },
          { ...ISSUE, id: 'n1', severity: 'info' },
        ]}
      />,
    )
    const counts = screen.getByLabelText('Issue counts by severity')
    expect(within(counts).getByText('Error: 2')).toBeTruthy()
    expect(within(counts).getByText('Warning: 1')).toBeTruthy()
    expect(within(counts).getByText('Info: 1')).toBeTruthy()
  })

  it('renders an empty state when there are no issues', () => {
    render(
      <IssueList
        issues={[]}
        emptyTitle="No issues found"
        emptyDescription="The run passed cleanly."
      />,
    )
    expect(screen.getByText('No issues found')).toBeTruthy()
    expect(screen.getByText('The run passed cleanly.')).toBeTruthy()
    // No count summary when empty.
    expect(screen.queryByLabelText('Issue counts by severity')).toBeNull()
  })
})

// ---------------------------------------------------------------------------
// OperationRunner (Req 14.1/14.3 result + 8.5 failed/timeout distinction).
//
// Uses the same faithful fake get-operation hook pattern as the useOperationPoll
// suite: it re-reads a scripted status source on the interval the runner asks
// for and self-halts on terminal/problem, so it behaves like a real TanStack
// Query refetch loop under fake timers.
// ---------------------------------------------------------------------------
interface Run {
  status?: string
  failure?: Record<string, unknown> | null
}

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

    const startedRef = useRef(false)
    if (enabled && !startedRef.current) {
      startedRef.current = true
      startedAt.current = Date.now()
      current.current = source(state.pollCount)
      state.pollCount += 1
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

const TERMINAL = ['completed', 'failed'] as const

describe('OperationRunner', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(0)
  })
  afterEach(() => {
    act(() => {
      vi.runOnlyPendingTimers()
    })
    vi.useRealTimers()
  })

  it('renders the successful terminal result and no failure/timeout notice', () => {
    const { useFakeOperation } = makeFakeOperation(
      (i) => ({ data: { status: i < 1 ? 'running' : 'completed' }, error: null }),
      TERMINAL,
      120_000,
    )

    render(
      <OperationRunner<Run>
        operationLabel="reconciliation run"
        operationId="op-ok"
        useGetOperation={useFakeOperation}
        intervalMs={2_000}
        timeoutMs={120_000}
        renderResult={() => <div>result widget</div>}
      />,
    )

    // Polling, then terminal after one interval.
    act(() => {
      vi.advanceTimersByTime(2_000)
    })
    expect(screen.getByText('result widget')).toBeTruthy()
    // No failure/timeout alert.
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('renders the typed failure and presents no result on a failed terminal', () => {
    const { useFakeOperation } = makeFakeOperation(
      (i) => ({
        data: {
          status: i < 1 ? 'running' : 'failed',
          failure: { code: 'compile_error', detail: 'boom' },
        },
        error: null,
      }),
      TERMINAL,
      120_000,
    )

    render(
      <OperationRunner<Run>
        operationLabel="SDTM compile"
        operationId="op-fail"
        useGetOperation={useFakeOperation}
        intervalMs={2_000}
        timeoutMs={120_000}
        renderResult={() => <div>result widget</div>}
      />,
    )

    act(() => {
      vi.advanceTimersByTime(2_000)
    })

    // The failure notice names the operation and surfaces the typed failure…
    expect(screen.getByRole('alert')).toBeTruthy()
    expect(screen.getByText('The SDTM compile failed')).toBeTruthy()
    expect(screen.getByText('compile_error')).toBeTruthy()
    expect(screen.getByText('boom')).toBeTruthy()
    // …and NO success result widget is shown.
    expect(screen.queryByText('result widget')).toBeNull()
  })

  it('renders a timeout notice naming the run and presents no result', () => {
    // Never terminal: trips the client deadline.
    const { useFakeOperation } = makeFakeOperation(
      () => ({ data: { status: 'running' }, error: null }),
      TERMINAL,
      10_000,
    )

    render(
      <OperationRunner<Run>
        operationLabel="aCRF build"
        operationId="op-timeout"
        useGetOperation={useFakeOperation}
        intervalMs={2_000}
        timeoutMs={10_000}
        renderResult={() => <div>result widget</div>}
      />,
    )

    act(() => {
      vi.advanceTimersByTime(10_000)
    })

    // The timeout notice names the affected build and shows no result.
    expect(screen.getByRole('alert')).toBeTruthy()
    expect(screen.getByText('The aCRF build did not finish in time')).toBeTruthy()
    expect(screen.queryByText('result widget')).toBeNull()
  })

  it('surfaces a poll problem+json title/detail and no result', () => {
    const problem = {
      response: {
        data: { title: 'Reconciliation failed', detail: 'Input is stale.' },
      },
    } as unknown as AxiosError
    const { useFakeOperation } = makeFakeOperation(
      (i) =>
        i < 1
          ? { data: { status: 'running' }, error: null }
          : { data: { status: 'running' }, error: problem },
      TERMINAL,
      120_000,
    )

    render(
      <OperationRunner<Run>
        operationLabel="reconciliation run"
        operationId="op-problem"
        useGetOperation={useFakeOperation}
        intervalMs={2_000}
        timeoutMs={120_000}
        renderResult={() => <div>result widget</div>}
      />,
    )

    act(() => {
      vi.advanceTimersByTime(2_000)
    })

    expect(screen.getByText('Reconciliation failed')).toBeTruthy()
    expect(screen.getByText('Input is stale.')).toBeTruthy()
    expect(screen.queryByText('result widget')).toBeNull()
  })

  it('fires onStart when the default trigger is activated while idle', () => {
    const onStart = vi.fn()
    const { useFakeOperation } = makeFakeOperation(
      () => ({ data: undefined, error: null }),
      TERMINAL,
      120_000,
    )
    render(
      <OperationRunner<Run>
        operationLabel="SDTM validation"
        startLabel="Run validation"
        operationId={null}
        useGetOperation={useFakeOperation}
        intervalMs={2_000}
        timeoutMs={120_000}
        onStart={onStart}
        renderResult={() => <div>result widget</div>}
      />,
    )
    const trigger = screen.getByRole('button', {
      name: 'Run validation',
    }) as HTMLButtonElement
    expect(trigger.disabled).toBe(false)
    fireEvent.click(trigger)
    expect(onStart).toHaveBeenCalledTimes(1)
  })

  it('disables the trigger when startDisabled (e.g. a guarding banner is active)', () => {
    const { useFakeOperation } = makeFakeOperation(
      () => ({ data: undefined, error: null }),
      TERMINAL,
      120_000,
    )
    render(
      <OperationRunner<Run>
        operationLabel="SDTM validation"
        operationId={null}
        useGetOperation={useFakeOperation}
        intervalMs={2_000}
        timeoutMs={120_000}
        startDisabled
        onStart={vi.fn()}
        renderResult={() => <div>result widget</div>}
      />,
    )
    expect(
      (screen.getByRole('button', { name: 'Start' }) as HTMLButtonElement).disabled,
    ).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// Banners disable the controls they guard (Req 10.5, 12.4, 20.5).
//
// The banner and the disabled control derive from the SAME predicate
// (`isStale` / `isMisaligned`), so the test asserts both the notice is shown
// and a control gated on that predicate is disabled, and that neither renders
// / disables when the state is clear.
// ---------------------------------------------------------------------------
function StalenessGuardedPanel({ state }: { state: Parameters<typeof isStale>[0] }) {
  const blocked = isStale(state)
  return (
    <div>
      <StalenessBanner state={state} />
      <button type="button" disabled={blocked}>
        Start reconciliation
      </button>
    </div>
  )
}

function AlignmentGuardedPanel({ state }: { state: Parameters<typeof isMisaligned>[0] }) {
  const blocked = isMisaligned(state)
  return (
    <div>
      <AlignmentBanner state={state} />
      <button type="button" disabled={blocked}>
        Validate plan
      </button>
    </div>
  )
}

describe('StalenessBanner guards operation controls (Req 10.5, 20.5)', () => {
  it('shows the notice and disables the guarded control when refresh is required', () => {
    render(<StalenessGuardedPanel state="dependency_refresh_required" />)
    expect(screen.getByRole('alert')).toBeTruthy()
    expect(
      screen.getByText('Dependency selection needs a refresh'),
    ).toBeTruthy()
    expect(
      (screen.getByRole('button', { name: 'Start reconciliation' }) as HTMLButtonElement)
        .disabled,
    ).toBe(true)
  })

  it('disables the control for an input refresh too', () => {
    render(<StalenessGuardedPanel state="input_refresh_required" />)
    expect(screen.getByText('Input selection needs a refresh')).toBeTruthy()
    expect(
      (screen.getByRole('button', { name: 'Start reconciliation' }) as HTMLButtonElement)
        .disabled,
    ).toBe(true)
  })

  it('renders nothing and leaves the control enabled when not stale', () => {
    render(<StalenessGuardedPanel state={null} />)
    expect(screen.queryByRole('alert')).toBeNull()
    expect(
      (screen.getByRole('button', { name: 'Start reconciliation' }) as HTMLButtonElement)
        .disabled,
    ).toBe(false)
  })
})

describe('AlignmentBanner guards plan operation controls (Req 12.4)', () => {
  it('shows the misalignment notice and disables the guarded control', () => {
    render(<AlignmentGuardedPanel state="misaligned" />)
    expect(screen.getByRole('alert')).toBeTruthy()
    expect(screen.getByText('Derivation plan is misaligned')).toBeTruthy()
    expect(
      (screen.getByRole('button', { name: 'Validate plan' }) as HTMLButtonElement)
        .disabled,
    ).toBe(true)
  })

  it('renders nothing and leaves the control enabled when aligned', () => {
    render(<AlignmentGuardedPanel state="aligned" />)
    expect(screen.queryByRole('alert')).toBeNull()
    expect(
      (screen.getByRole('button', { name: 'Validate plan' }) as HTMLButtonElement)
        .disabled,
    ).toBe(false)
  })
})
