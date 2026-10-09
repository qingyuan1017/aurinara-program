// @vitest-environment jsdom
//
// Component tests for the two SDTM operation panels (task 14.3):
//   * `compile-panel.tsx`    — compile one backend + build extra artifacts (R15).
//   * `execution-panel.tsx`  — submit the full pinned body + poll a run (R16).
//
// Coverage (Requirements 15.1, 15.2, 15.3, 15.4, 16.1, 16.2, 16.3, 16.4, 16.5):
//   Compile: a compile start sends `backend` + the pinned
//     `expected_input_fingerprint` + a syntactically valid `Idempotency-Key`
//     (R15.1), the returned build id polls to a terminal via OperationRunner
//     (R15.2), a `failed` terminal shows the typed failure and presents NO
//     partial artifacts (R15.3), and a `409 backend_capability_missing` on
//     compile shows the capability message (R15.4).
//   Execution: a start sends the full pinned body — language, program/input
//     artifact ids, validation-run id, pinned input-selection/specification/plan
//     revisions, compiler + expected input fingerprints, and the accepted
//     limits — with a valid `Idempotency-Key` (R16.1); the returned run id polls
//     to a terminal (R16.2) and renders status + timing + resource metrics plus
//     the captured logs and output artifacts (R16.3); a `runner_not_configured`
//     terminal keeps the generated program available and is NOT a hard failure
//     (R16.5); and any other `failed` terminal shows the typed failure together
//     with the captured logs (R16.4).
//
// Following the established repo convention (`-raw-ops-panels.test.tsx`): no MSW
// is installed, so the generated Orval hooks + study/toast/download are mocked
// and the REAL panels are driven over faithful hook fakes. The poll flows use
// vitest fake timers exactly as the Raw ops panels drive OperationRunner /
// useOperationPoll (flush mutate microtasks with
// `await act(async () => { await Promise.resolve() })`; no waitFor inside a
// fake-timer block).
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import {
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from 'vitest'
import * as React from 'react'
import type { ReactNode } from 'react'
import type { AxiosError, AxiosRequestConfig } from 'axios'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { installJsdomHarness } from '@/test/jsdom-harness'
import { WorkbenchContextProvider } from '@/components/workbench/workbench-context'
import { ifMatchRequest } from '@/lib/requests'
import type {
  AggregateResponse,
  ArtifactBuildResponse,
  ExecutionRunResponse,
  GetExecutionLogs200,
  GetExecutionOutputs200,
  InputSelectionResponse,
} from '@/api/generated/model'

beforeAll(() => {
  installJsdomHarness()
})

// Keep sonner out of the jsdom/theme-provider path.
vi.mock('@/components/ui/sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

// ArtifactList's DownloadButton calls `useDownload` (touches the real axios
// instance); stub it so a completed-artifact list is harmless.
vi.mock('@/hooks/use-download', () => ({
  useDownload: () => ({
    downloadArtifact: vi.fn(),
    isPending: false,
    error: null,
  }),
}))

// `invalidate.ts` reaches into many generated modules at import time; stub the
// one helper the compile panel uses so this file need not pull the whole
// SDTM/define/csdrg/acrf surface.
vi.mock('@/lib/invalidate', () => ({
  invalidateSdtmOperationArtifacts: vi.fn(),
}))

// ---------------------------------------------------------------------------
// Mutable fixtures the generated-hook stubs read through.
// ---------------------------------------------------------------------------
interface GetState<T> {
  data: T | undefined
  error: AxiosError | null
  isLoading: boolean
  isError: boolean
}

const sdtmApi: {
  // input selection (drives the pinned fingerprint)
  selection: GetState<InputSelectionResponse>
  // compile start (202)
  compileImpl: (vars: { sdtmId: string; data: unknown }) => Promise<ArtifactBuildResponse>
  compileError: AxiosError | null
  compileVars: Array<{ sdtmId: string; data: unknown }>
  compileRequests: Array<AxiosRequestConfig | undefined>
  // extra artifacts create (202)
  createArtifactsImpl: (vars: {
    sdtmId: string
    data: unknown
  }) => Promise<ArtifactBuildResponse>
  createArtifactsVars: Array<{ sdtmId: string; data: unknown }>
  // execute start (202)
  executeImpl: (vars: {
    sdtmId: string
    data: unknown
  }) => Promise<ExecutionRunResponse>
  executeError: AxiosError | null
  executeVars: Array<{ sdtmId: string; data: unknown }>
  executeRequests: Array<AxiosRequestConfig | undefined>
} = {
  selection: { data: undefined, error: null, isLoading: false, isError: false },
  compileImpl: async () => makeBuild(),
  compileError: null,
  compileVars: [],
  compileRequests: [],
  createArtifactsImpl: async () => makeBuild(),
  createArtifactsVars: [],
  executeImpl: async () => makeRun(),
  executeError: null,
  executeVars: [],
  executeRequests: [],
}

// Execution logs/outputs the fake get-hooks read through.
const execDetails: {
  logs: GetExecutionLogs200 | undefined
  outputs: GetExecutionOutputs200 | undefined
} = { logs: undefined, outputs: undefined }

// Scripted poll sources: the test pushes a sequence and the fake get-operation
// hook replays one state per refetch tick, self-halting on a terminal status.
const pollSource: { build: ArtifactBuildResponse[]; exec: ExecutionRunResponse[] } = {
  build: [],
  exec: [],
}
const pollIndex = { build: 0, exec: 0 }

/**
 * A faithful mutation fake: `mutateAsync` runs the scripted impl, fires
 * `onSuccess` on resolve so the panel's success path (poll kickoff) runs for
 * real, and surfaces the fixture error inline each render.
 */
function makeMutation<V, R>(
  impl: (vars: V) => Promise<R>,
  onSuccess?: (data: R) => void,
  getError?: () => AxiosError | null,
) {
  return {
    isPending: false,
    error: (getError?.() ?? null) as AxiosError | null,
    reset: () => {},
    mutate: (vars: V) => {
      void impl(vars).then((d) => onSuccess?.(d))
    },
    mutateAsync: async (vars: V) => {
      const data = await impl(vars)
      onSuccess?.(data)
      return data
    },
  }
}

vi.mock('@/api/generated/sdtm/sdtm', () => {
  const useGetInputSelection = () => sdtmApi.selection

  const useCompileSdtm = (options?: {
    mutation?: { onSuccess?: (data: ArtifactBuildResponse) => void }
    request?: AxiosRequestConfig
  }) => {
    sdtmApi.compileRequests.push(options?.request)
    return makeMutation(
      (vars: { sdtmId: string; data: unknown }) => {
        sdtmApi.compileVars.push(vars)
        return sdtmApi.compileImpl(vars)
      },
      options?.mutation?.onSuccess,
      () => sdtmApi.compileError,
    )
  }

  const useCreateSdtmArtifacts = (options?: {
    mutation?: { onSuccess?: (data: ArtifactBuildResponse) => void }
    request?: AxiosRequestConfig
  }) =>
    makeMutation(
      (vars: { sdtmId: string; data: unknown }) => {
        sdtmApi.createArtifactsVars.push(vars)
        return sdtmApi.createArtifactsImpl(vars)
      },
      options?.mutation?.onSuccess,
    )

  const useExecuteSdtm = (options?: {
    mutation?: { onSuccess?: (data: ExecutionRunResponse) => void }
    request?: AxiosRequestConfig
  }) => {
    sdtmApi.executeRequests.push(options?.request)
    return makeMutation(
      (vars: { sdtmId: string; data: unknown }) => {
        sdtmApi.executeVars.push(vars)
        return sdtmApi.executeImpl(vars)
      },
      options?.mutation?.onSuccess,
      () => sdtmApi.executeError,
    )
  }

  return {
    useGetInputSelection,
    useCompileSdtm,
    useCreateSdtmArtifacts,
    useExecuteSdtm,
  }
})

vi.mock('@/api/generated/artifact-builds/artifact-builds', () => ({
  getGetArtifactBuildQueryKey: (id?: string) => [`/api/v1/artifact-builds/${id}`],
  useGetArtifactBuild: makeScriptedGet('build', ['completed', 'failed']),
}))

vi.mock('@/api/generated/execution/execution', () => ({
  getGetExecutionRunQueryKey: (id?: string) => [`/api/v1/execution-runs/${id}`],
  useGetExecutionRun: makeScriptedGet('exec', ['succeeded', 'failed', 'cancelled']),
  useGetExecutionLogs: () => ({
    data: execDetails.logs,
    error: null as AxiosError | null,
    isLoading: false,
  }),
  useGetExecutionOutputs: () => ({
    data: execDetails.outputs,
    error: null as AxiosError | null,
    isLoading: false,
  }),
}))

/**
 * A scripted get-operation hook factory. It advances through the matching
 * `pollSource[kind]` sequence once per refetch interval the caller forwards and
 * self-halts once a terminal status is reached — close enough to a real
 * TanStack refetch loop for the panel + useOperationPoll under fake timers.
 */
function makeScriptedGet(kind: 'build' | 'exec', terminal: string[]) {
  return (
    _id: string,
    opts?: {
      query?: { enabled?: boolean; refetchInterval?: number | false; retry?: boolean }
    },
  ) => {
    void _id
    const [, force] = React.useState(0)
    const seq = pollSource[kind]
    const started = React.useRef(false)
    const stopped = React.useRef(false)
    const enabled = opts?.query?.enabled ?? false
    const refetchInterval = opts?.query?.refetchInterval

    if (enabled && !started.current) {
      started.current = true
      pollIndex[kind] = 0
    }

    React.useEffect(() => {
      if (!enabled || typeof refetchInterval !== 'number') return
      if (stopped.current) return
      const timer = window.setInterval(() => {
        if (stopped.current) {
          window.clearInterval(timer)
          return
        }
        if (pollIndex[kind] < seq.length - 1) {
          pollIndex[kind] += 1
        }
        const cur = seq[pollIndex[kind]] as { status?: string } | undefined
        if (cur && typeof cur.status === 'string' && terminal.includes(cur.status)) {
          stopped.current = true
          window.clearInterval(timer)
        }
        force((n) => n + 1)
      }, refetchInterval)
      return () => window.clearInterval(timer)
    }, [enabled, refetchInterval, seq])

    const data = enabled ? seq[pollIndex[kind]] : undefined
    return { data, error: null as AxiosError | null }
  }
}

// ---------------------------------------------------------------------------
// Import AFTER the mocks so the panels bind to the stubs.
// ---------------------------------------------------------------------------
import { CompilePanel } from './compile-panel'
import { ExecutionPanel } from './execution-panel'

// ---------------------------------------------------------------------------
// Fixtures.
// ---------------------------------------------------------------------------
function makeBuild(
  overrides: Partial<ArtifactBuildResponse> = {},
): ArtifactBuildResponse {
  return {
    id: 'ab-1',
    study_id: 'study-1',
    module_key: 'sdtm',
    owner_type: 'sdtm',
    owner_id: 'sdtm-1',
    artifact_types: ['sdtm_program_python'],
    options: {},
    input_fingerprint: 'fp-1',
    status: 'running',
    result_artifact_ids: [],
    failure: null,
    started_at: null,
    completed_at: null,
    created_by: 'user-1',
    created_at: '2024-01-01T00:00:00Z',
    ...overrides,
  } as ArtifactBuildResponse
}

function makeRun(overrides: Partial<ExecutionRunResponse> = {}): ExecutionRunResponse {
  return {
    id: 'er-1',
    study_id: 'study-1',
    module: 'sdtm',
    owner_type: 'sdtm',
    owner_id: 'sdtm-1',
    language: 'python',
    program_artifact_id: 'prog-1',
    input_artifact_ids: ['in-1'],
    validation_run_id: 'vr-1',
    input_selection_revision: 2,
    source_specification_revision: 3,
    source_plan_type: 'sdtm_derivation_plan',
    source_plan_revision: 4,
    compiler_fingerprint: 'c'.repeat(64),
    input_fingerprint: 'f'.repeat(64),
    limits: {},
    status: 'running',
    output_artifact_ids: [],
    failure: null,
    exit_code: null,
    metrics: {},
    cancellation_requested_at: null,
    started_at: null,
    completed_at: null,
    created_by: 'user-1',
    created_at: '2024-01-01T00:00:00Z',
    ...overrides,
  } as ExecutionRunResponse
}

function makeSelection(
  overrides: Partial<InputSelectionResponse> = {},
): InputSelectionResponse {
  return {
    revision: 2,
    state: 'current',
    payload: {} as InputSelectionResponse['payload'],
    fingerprint: 'input-fp-1',
    ...overrides,
  }
}

function makeAggregate(
  overrides: Partial<AggregateResponse> = {},
): AggregateResponse {
  return {
    id: 'sdtm-1',
    study_id: 'study-1',
    code: 'SDTM',
    name: 'SDTM workbench',
    status: 'draft',
    revision: 5,
    ...overrides,
  }
}

function problemError(status: number, body: Record<string, unknown>): AxiosError {
  return {
    isAxiosError: true,
    message: 'request failed',
    response: { status, data: body },
  } as unknown as AxiosError
}

function renderWithClient(ui: ReactNode) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

/** Wrap a panel that reads `useWorkbench()` in the aggregate context. */
function renderInWorkbench(ui: ReactNode, aggregate = makeAggregate()) {
  return renderWithClient(
    <WorkbenchContextProvider
      value={{
        aggregate,
        revision: aggregate.revision,
        studyId: aggregate.study_id,
        ifMatch: () => ifMatchRequest(aggregate.revision),
      }}
    >
      {ui}
    </WorkbenchContextProvider>,
  )
}

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

function readIdempotencyKey(
  request: AxiosRequestConfig | undefined,
): string | undefined {
  const headers = request?.headers as Record<string, string> | undefined
  return headers?.['Idempotency-Key']
}

beforeEach(() => {
  sdtmApi.selection = {
    data: makeSelection(),
    error: null,
    isLoading: false,
    isError: false,
  }
  sdtmApi.compileImpl = async () => makeBuild()
  sdtmApi.compileError = null
  sdtmApi.compileVars = []
  sdtmApi.compileRequests = []
  sdtmApi.createArtifactsImpl = async () => makeBuild()
  sdtmApi.createArtifactsVars = []
  sdtmApi.executeImpl = async () => makeRun()
  sdtmApi.executeError = null
  sdtmApi.executeVars = []
  sdtmApi.executeRequests = []
  execDetails.logs = undefined
  execDetails.outputs = undefined
  pollSource.build = []
  pollSource.exec = []
  pollIndex.build = 0
  pollIndex.exec = 0
})

afterEach(() => {
  vi.clearAllMocks()
})

// ===========================================================================
// Compile (Req 15.1, 15.4)
// ===========================================================================
describe('CompilePanel start request (Req 15.1)', () => {
  it('sends the selected backend + pinned fingerprint + a valid Idempotency-Key', async () => {
    sdtmApi.selection = {
      data: makeSelection({ fingerprint: 'input-fp-9' }),
      error: null,
      isLoading: false,
      isError: false,
    }

    renderInWorkbench(<CompilePanel sdtmId="sdtm-1" />)

    // Pick the R backend (the radio with value "r"), then compile.
    const rRadio = document.getElementById('compile-backend-r') as HTMLInputElement
    fireEvent.click(rRadio)
    fireEvent.click(screen.getByRole('button', { name: /^compile$/i }))
    await act(async () => {
      await Promise.resolve()
    })

    expect(sdtmApi.compileVars).toHaveLength(1)
    expect(sdtmApi.compileVars[0]).toMatchObject({
      sdtmId: 'sdtm-1',
      data: { backend: 'r', expected_input_fingerprint: 'input-fp-9' },
    })

    // The compile carried a syntactically valid Idempotency-Key (R21.2).
    const key = readIdempotencyKey(
      sdtmApi.compileRequests[sdtmApi.compileRequests.length - 1],
    )
    expect(key).toMatch(UUID_RE)
  })

  it('shows the capability-missing message on a 409 backend_capability_missing (R15.4)', async () => {
    const capProblem = problemError(409, {
      title: 'Conflict',
      code: 'backend_capability_missing',
      detail: 'The R backend cannot implement the declared semantics.',
    })
    sdtmApi.compileImpl = async () => {
      throw capProblem
    }
    sdtmApi.compileError = capProblem

    renderInWorkbench(<CompilePanel sdtmId="sdtm-1" />)
    fireEvent.click(screen.getByRole('button', { name: /^compile$/i }))

    await waitFor(() => {
      expect(screen.getByText('This backend cannot compile the plan')).toBeTruthy()
    })
    expect(
      screen.getByText('The R backend cannot implement the declared semantics.'),
    ).toBeTruthy()
  })
})

describe('CompilePanel poll + terminal (Req 15.2, 15.3)', () => {
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

  it('polls the build to a completed terminal and lists produced program artifacts (R15.2)', async () => {
    pollSource.build = [
      makeBuild({ status: 'running' }),
      makeBuild({
        status: 'completed',
        result_artifact_ids: ['prog-art-1'],
      }),
    ]
    sdtmApi.compileImpl = async () => pollSource.build[0]

    renderInWorkbench(<CompilePanel sdtmId="sdtm-1" />)
    fireEvent.click(screen.getByRole('button', { name: /^compile$/i }))
    await act(async () => {
      await Promise.resolve()
    })

    // Advance one interval to the terminal poll.
    await act(async () => {
      vi.advanceTimersByTime(2_000)
      await Promise.resolve()
    })

    expect(screen.getByText('Produced artifacts')).toBeTruthy()
    expect(screen.getAllByRole('button', { name: /download/i })).toHaveLength(1)
  })

  it('shows the typed failure and NO partial artifacts on a failed terminal (R15.3)', async () => {
    pollSource.build = [
      makeBuild({ status: 'running' }),
      makeBuild({
        status: 'failed',
        result_artifact_ids: [],
        failure: { code: 'sdtm_compile_error', detail: 'Lowering failed.' },
      } as Partial<ArtifactBuildResponse>),
    ]
    sdtmApi.compileImpl = async () => pollSource.build[0]

    renderInWorkbench(<CompilePanel sdtmId="sdtm-1" />)
    fireEvent.click(screen.getByRole('button', { name: /^compile$/i }))
    await act(async () => {
      await Promise.resolve()
    })

    await act(async () => {
      vi.advanceTimersByTime(2_000)
      await Promise.resolve()
    })

    // Typed failure object surfaced…
    expect(screen.getByText('The compile failed')).toBeTruthy()
    expect(screen.getByText('sdtm_compile_error')).toBeTruthy()
    expect(screen.getByText('Lowering failed.')).toBeTruthy()
    // …and NO produced-artifacts list or download on failure.
    expect(screen.queryByText('Produced artifacts')).toBeNull()
    expect(screen.queryByRole('button', { name: /download/i })).toBeNull()
  })
})

// ===========================================================================
// Execution (Req 16.1, 16.2, 16.3, 16.4, 16.5)
// ===========================================================================

/**
 * Fill the execution form with a complete, parseable pinned body so the
 * client guard passes and `useExecuteSdtm` receives the typed request.
 */
function fillExecutionForm() {
  fireEvent.change(screen.getByLabelText(/program artifact id/i), {
    target: { value: 'prog-77' },
  })
  fireEvent.change(screen.getByLabelText(/input artifact ids/i), {
    target: { value: 'in-1, in-2' },
  })
  fireEvent.change(screen.getByLabelText(/validation-run id/i), {
    target: { value: 'vr-55' },
  })
  fireEvent.change(screen.getByLabelText(/input-selection revision/i), {
    target: { value: '2' },
  })
  fireEvent.change(screen.getByLabelText(/specification revision/i), {
    target: { value: '3' },
  })
  fireEvent.change(screen.getByLabelText(/plan revision/i), {
    target: { value: '4' },
  })
  fireEvent.change(screen.getByLabelText(/compiler fingerprint/i), {
    target: { value: 'c'.repeat(64) },
  })
  fireEvent.change(screen.getByLabelText(/expected input fingerprint/i), {
    target: { value: 'f'.repeat(64) },
  })
}

describe('ExecutionPanel start request (Req 16.1)', () => {
  it('sends the full pinned body + limits + a valid Idempotency-Key', async () => {
    renderInWorkbench(<ExecutionPanel sdtmId="sdtm-1" />)

    fillExecutionForm()
    fireEvent.click(screen.getByRole('button', { name: /^execute$/i }))
    await act(async () => {
      await Promise.resolve()
    })

    expect(sdtmApi.executeVars).toHaveLength(1)
    const vars = sdtmApi.executeVars[0] as { sdtmId: string; data: Record<string, unknown> }
    expect(vars.sdtmId).toBe('sdtm-1')
    expect(vars.data).toMatchObject({
      language: 'python',
      program_artifact_id: 'prog-77',
      input_artifact_ids: ['in-1', 'in-2'],
      validation_run_id: 'vr-55',
      input_selection_revision: 2,
      source_specification_revision: 3,
      source_plan_revision: 4,
      compiler_fingerprint: 'c'.repeat(64),
      expected_input_fingerprint: 'f'.repeat(64),
      // The accepted limits from the default form values.
      limits: {
        cpu: 1,
        memory_mb: 2048,
        runtime_seconds: 600,
        output_bytes: 52428800,
      },
    })

    const key = readIdempotencyKey(
      sdtmApi.executeRequests[sdtmApi.executeRequests.length - 1],
    )
    expect(key).toMatch(UUID_RE)
  })

  it('blocks submit with a message when a required field is missing (no request)', async () => {
    renderInWorkbench(<ExecutionPanel sdtmId="sdtm-1" />)

    // Leave the form empty (no input artifact ids): the client guard blocks.
    fireEvent.click(screen.getByRole('button', { name: /^execute$/i }))
    await act(async () => {
      await Promise.resolve()
    })

    expect(sdtmApi.executeVars).toHaveLength(0)
    expect(
      screen.getByText(/at least one input artifact id is required/i),
    ).toBeTruthy()
  })
})

describe('ExecutionPanel poll + terminal (Req 16.2, 16.3)', () => {
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

  it('polls the run to a succeeded terminal and renders status + timing + metrics + logs + outputs', async () => {
    pollSource.exec = [
      makeRun({ status: 'running' }),
      makeRun({
        status: 'succeeded',
        exit_code: 0,
        started_at: '2024-01-01T00:00:00Z',
        completed_at: '2024-01-01T00:00:12Z',
        metrics: { peak_memory_mb: 512, cpu_seconds: 8 },
        output_artifact_ids: ['out-1'],
      } as Partial<ExecutionRunResponse>),
    ]
    sdtmApi.executeImpl = async () => pollSource.exec[0]
    execDetails.logs = { stdout: 'hello stdout', stderr: '', truncated: false }
    execDetails.outputs = {
      items: [
        { artifact_id: 'out-1', artifact_type: 'sdtm_dataset_xpt', sha256: 'abc', size: 10 },
      ],
    }

    renderInWorkbench(<ExecutionPanel sdtmId="sdtm-1" />)
    fillExecutionForm()
    fireEvent.click(screen.getByRole('button', { name: /^execute$/i }))
    await act(async () => {
      await Promise.resolve()
    })

    await act(async () => {
      vi.advanceTimersByTime(2_000)
      await Promise.resolve()
    })

    // Status + timing + resource metrics. The terminal state is already
    // rendered after the act() tick above, so read synchronously (no waitFor /
    // findByText under fake timers).
    const runCard = screen.getByText('Execution run').closest(
      '[data-slot="card"]',
    ) as HTMLElement
    expect(within(runCard).getByText('succeeded')).toBeTruthy()
    expect(within(runCard).getByText('exit 0')).toBeTruthy()
    expect(within(runCard).getByText('Duration')).toBeTruthy()
    expect(within(runCard).getByText('12.00s')).toBeTruthy()
    expect(within(runCard).getByText('peak_memory_mb')).toBeTruthy()
    expect(within(runCard).getByText('512')).toBeTruthy()

    // Captured logs.
    expect(screen.getByText('hello stdout')).toBeTruthy()
    // Output artifacts (succeeded run).
    expect(screen.getByText('Output artifacts')).toBeTruthy()
    expect(screen.getAllByRole('button', { name: /download/i })).toHaveLength(1)
  })
})

describe('ExecutionPanel SAS runner_not_configured (Req 16.5)', () => {
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

  it('keeps the program available and is not treated as a hard failure', async () => {
    pollSource.exec = [
      makeRun({ status: 'running' }),
      makeRun({
        status: 'failed',
        language: 'sas',
        failure: { code: 'runner_not_configured', detail: 'No external SAS runner.' },
      } as Partial<ExecutionRunResponse>),
    ]
    sdtmApi.executeImpl = async () => pollSource.exec[0]
    execDetails.logs = { stdout: '', stderr: '', truncated: false }

    renderInWorkbench(<ExecutionPanel sdtmId="sdtm-1" />)
    fillExecutionForm()
    fireEvent.click(screen.getByRole('button', { name: /^execute$/i }))
    await act(async () => {
      await Promise.resolve()
    })

    await act(async () => {
      vi.advanceTimersByTime(2_000)
      await Promise.resolve()
    })

    // The runner-not-configured notice explains SAS needs an external runner…
    expect(
      screen.getByText('SAS execution needs an external runner'),
    ).toBeTruthy()
    expect(screen.getByText(/generated SAS program remains available/i)).toBeTruthy()
    // …and it is NOT shown as a hard failure.
    expect(screen.queryByText('The execution run failed')).toBeNull()
  })
})

describe('ExecutionPanel hard failure (Req 16.4)', () => {
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

  it('shows the typed failure object together with the captured logs', async () => {
    pollSource.exec = [
      makeRun({ status: 'running' }),
      makeRun({
        status: 'failed',
        exit_code: 1,
        failure: { code: 'nonzero_exit', detail: 'The program exited with status 1.' },
      } as Partial<ExecutionRunResponse>),
    ]
    sdtmApi.executeImpl = async () => pollSource.exec[0]
    execDetails.logs = {
      stdout: 'partial output',
      stderr: 'Traceback: boom',
      truncated: false,
    }

    renderInWorkbench(<ExecutionPanel sdtmId="sdtm-1" />)
    fillExecutionForm()
    fireEvent.click(screen.getByRole('button', { name: /^execute$/i }))
    await act(async () => {
      await Promise.resolve()
    })

    await act(async () => {
      vi.advanceTimersByTime(2_000)
      await Promise.resolve()
    })

    // Typed failure object…
    expect(screen.getByText('The execution run failed')).toBeTruthy()
    expect(screen.getByText('nonzero_exit')).toBeTruthy()
    expect(screen.getByText('The program exited with status 1.')).toBeTruthy()
    // …plus the captured logs for a failed run (R16.4).
    expect(screen.getByText('partial output')).toBeTruthy()
    expect(screen.getByText('Traceback: boom')).toBeTruthy()
    // A failed run presents no output artifacts.
    expect(screen.queryByText('Output artifacts')).toBeNull()
  })
})
