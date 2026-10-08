// @vitest-environment jsdom
//
// Component tests for the four Raw operation panels (task 8.5):
//   * `raw-validation-panel.tsx`   — synchronous validate + open-by-id (R6).
//   * `reconciliation-panel.tsx`   — 202 + poll + 409 stale reload (R7).
//   * `artifacts-panel.tsx`        — four fixed types + poll + failed (R8).
//   * `dependencies-panel.tsx`     — 422 issues / 412 refresh / banner (R20).
//
// Coverage (Requirements 6.1, 6.3, 6.5, 7.2, 7.3, 8.2, 8.3, 8.5, 20.3, 20.4,
// 20.5):
//   Validation: a synchronous 200 ValidationRun renders status + per-severity
//     counts + the IssueList (empty state when none); a `failed` run shows the
//     persistent block notice (R6.1/6.3); open-by-id renders the referenced run
//     and a 404 shows a not-found notice with NO stale content (R6.5).
//   Reconcile: a 202 start polls the run to a terminal status and, when it
//     never terminates, trips the client timeout (R7.2); a 409
//     `stale_raw_reconciliation_input` shows the stale message + a reload action
//     that re-fetches the current Raw aggregate revision (R7.3).
//   Artifacts: exactly the four fixed Raw types are offered and nothing else;
//     the submit control is disabled while none is selected (R8.2); a started
//     build polls to a terminal status via OperationRunner (R8.3); a `failed`
//     terminal shows the typed failure and NO download (R8.5).
//   Dependencies: a 422 `dependency_selection_invalid` renders each
//     incompatibility (R20.3); a 412 shows the concurrency message and reloads
//     the current revision before retry (R20.4); a `dependency_refresh_required`
//     state shows the banner and disables the save control (R20.5).
//
// Following the established repo convention (`-datasets-panel.test.tsx`,
// `-input-selection-specification.test.tsx`, `shared-components.test.tsx`): no
// MSW is installed, so the generated Orval hooks + study/toast/download are
// mocked and the REAL panels are driven over faithful hook fakes. The poll /
// timeout flows use vitest fake timers exactly as `shared-components.test.tsx`
// drives `OperationRunner`.
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from '@testing-library/react'
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
import type { AxiosError } from 'axios'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { installJsdomHarness } from '@/test/jsdom-harness'
import { WorkbenchContextProvider } from '@/components/workbench/workbench-context'
import { ifMatchRequest } from '@/lib/requests'
import type {
  AggregateResponse,
  ArtifactBuildResponse,
  DependencySelectionResponse,
  ReconciliationResponse,
  ValidationRunResponse,
} from '@/api/generated/model'

beforeAll(() => {
  installJsdomHarness()
})

// Keep sonner out of the jsdom/theme-provider path.
vi.mock('@/components/ui/sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

// The DownloadButton (via ArtifactList) uses `useDownload`, which touches the
// real axios instance; stub it so the completed-artifacts list is harmless.
vi.mock('@/hooks/use-download', () => ({
  useDownload: () => ({
    downloadArtifact: vi.fn(),
    isPending: false,
    error: null,
  }),
}))

// ---------------------------------------------------------------------------
// Mutable fixtures the generated-hook stubs read through. Each test installs
// the behaviour it needs.
// ---------------------------------------------------------------------------
interface GetState<T> {
  data: T | undefined
  error: AxiosError | null
  isLoading: boolean
  isError: boolean
}

const rawApi: {
  // validate (synchronous mutation)
  validateImpl: (vars: { rawId: string }) => Promise<ValidationRunResponse>
  validateError: AxiosError | null
  // validation-run open-by-id
  validationRun: GetState<ValidationRunResponse>
  // reconcile start (202)
  reconcileImpl: (vars: {
    rawId: string
    data: unknown
  }) => Promise<ReconciliationResponse>
  reconcileError: AxiosError | null
  reconcileRequests: unknown[]
  // artifact create (202)
  createArtifactsImpl: (vars: {
    rawId: string
    data: unknown
  }) => Promise<ArtifactBuildResponse>
  createArtifactsVars: Array<{ rawId: string; data: unknown }>
  createArtifactsRequests: unknown[]
  // artifact-build input-fingerprint preview
  previewFingerprintImpl: (vars: {
    rawId: string
    data: unknown
  }) => Promise<{ input_fingerprint: string }>
  previewFingerprintVars: Array<{ rawId: string; data: unknown }>
  // dependencies
  dependencies: DependencySelectionResponse | undefined
  replaceDependenciesImpl: (vars: {
    rawId: string
    data: unknown
  }) => Promise<unknown>
  replaceDependenciesRequests: unknown[]
} = {
  validateImpl: async () => makeRun(),
  validateError: null,
  validationRun: { data: undefined, error: null, isLoading: false, isError: false },
  reconcileImpl: async () => makeReconcile(),
  reconcileError: null,
  reconcileRequests: [],
  createArtifactsImpl: async () => makeBuild(),
  createArtifactsVars: [],
  createArtifactsRequests: [],
  previewFingerprintImpl: async () => ({ input_fingerprint: 'build-fp-1' }),
  previewFingerprintVars: [],
  dependencies: undefined,
  replaceDependenciesImpl: async () => ({}),
  replaceDependenciesRequests: [],
}

// A scripted poll source: the test pushes a sequence of poll states and the
// fake get-operation hook (below) reads them one per refetch tick.
const pollSource: { reconcile: ReconciliationResponse[]; build: ArtifactBuildResponse[] } =
  { reconcile: [], build: [] }
const pollIndex = { reconcile: 0, build: 0 }

/**
 * Build a minimal mutation-result whose `mutateAsync` runs the scripted impl,
 * records the error on resolve-reject, and fires `onSuccess` on resolve so the
 * panel's success path (poll kickoff / invalidation) exercises for real. The
 * `error` field is refreshed from the fixture each render so an inline error
 * surface (reconcile stale) reads the current value.
 */
function makeMutation<V, R>(
  impl: (vars: V) => Promise<R>,
  onSuccess?: (data: R) => void,
  getError?: () => AxiosError | null,
  reset?: () => void,
) {
  return {
    isPending: false,
    error: (getError?.() ?? null) as AxiosError | null,
    reset: reset ?? (() => {}),
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

vi.mock('@/api/generated/raw/raw', () => {
  // Stateful validate fake: like TanStack's useMutation, it holds `data` after
  // a successful `mutate` so the panel (which reads `validate.data`) renders the
  // synchronous run.
  const useValidateRaw = () => {
    const [data, setData] = React.useState<ValidationRunResponse | undefined>(
      undefined,
    )
    const [error, setError] = React.useState<AxiosError | null>(null)
    return {
      isPending: false,
      data,
      error: error ?? rawApi.validateError,
      reset: () => {
        setData(undefined)
        setError(null)
      },
      mutate: (vars: { rawId: string }) => {
        rawApi.validateImpl(vars).then(setData, (e: AxiosError) => setError(e))
      },
      mutateAsync: async (vars: { rawId: string }) => {
        const run = await rawApi.validateImpl(vars)
        setData(run)
        return run
      },
    }
  }

  const useReconcileRawSourceSchema = (options?: {
    mutation?: { onSuccess?: (data: ReconciliationResponse) => void }
    request?: unknown
  }) => {
    rawApi.reconcileRequests.push(options?.request)
    return makeMutation(
      (vars: { rawId: string; data: unknown }) => rawApi.reconcileImpl(vars),
      options?.mutation?.onSuccess,
      () => rawApi.reconcileError,
      () => {
        rawApi.reconcileError = null
      },
    )
  }

  const useCreateRawArtifacts = (options?: {
    mutation?: { onSuccess?: (data: ArtifactBuildResponse) => void }
    request?: unknown
  }) => {
    rawApi.createArtifactsRequests.push(options?.request)
    return makeMutation(
      (vars: { rawId: string; data: unknown }) => {
        rawApi.createArtifactsVars.push(vars)
        return rawApi.createArtifactsImpl(vars)
      },
      options?.mutation?.onSuccess,
    )
  }

  const usePreviewRawArtifactFingerprint = (options?: {
    mutation?: { onSuccess?: (data: { input_fingerprint: string }) => void }
    request?: unknown
  }) =>
    makeMutation(
      (vars: { rawId: string; data: unknown }) => {
        rawApi.previewFingerprintVars.push(vars)
        return rawApi.previewFingerprintImpl(vars)
      },
      options?.mutation?.onSuccess,
    )

  const useGetRawDependencies = (_rawId: string) => ({
    data: rawApi.dependencies,
    error: null,
    isLoading: rawApi.dependencies === undefined,
    isError: false,
    queryKey: [`/api/v1/raw/${_rawId}/dependencies`],
  })

  const useReplaceRawDependencies = (options?: {
    mutation?: { onSuccess?: (data: unknown) => void }
    request?: unknown
  }) => {
    rawApi.replaceDependenciesRequests.push(options?.request)
    return makeMutation(
      (vars: { rawId: string; data: unknown }) =>
        rawApi.replaceDependenciesImpl(vars),
      options?.mutation?.onSuccess,
    )
  }

  return {
    useValidateRaw,
    useReconcileRawSourceSchema,
    useCreateRawArtifacts,
    usePreviewRawArtifactFingerprint,
    useGetRawDependencies,
    useReplaceRawDependencies,
    getGetRawAggregateQueryKey: (rawId?: string) => [`/api/v1/raw/${rawId}`],
    getGetRawDependenciesQueryKey: (rawId?: string) => [
      `/api/v1/raw/${rawId}/dependencies`,
    ],
    getListDatasetsQueryKey: (rawId?: string) => [`/api/v1/raw/${rawId}/datasets`],
    getGetDatasetQueryKey: (id?: string) => [`/api/v1/raw-datasets/${id}`],
    getGetVariableQueryKey: (id?: string) => [`/api/v1/raw-variables/${id}`],
    getListRawAggregatesQueryKey: (studyId?: string) => [
      '/api/v1/studies',
      studyId,
      'raw',
    ],
    getListVariablesQueryKey: (datasetId?: string) => [
      `/api/v1/raw-datasets/${datasetId}/variables`,
    ],
  }
})

// `useGetValidationRun` is owned by the shared `validation` tag module (the Raw
// tag does not re-export it), so the open-by-id lookup is mocked there.
vi.mock('@/api/generated/validation/validation', () => ({
  useGetValidationRun: () => rawApi.validationRun,
}))

// Reconciliation + artifact-build poll queries. These forward through the same
// enabled/refetchInterval the OperationRunner computes and replay the scripted
// poll source one state per tick (self-halting on terminal/error), matching the
// faithful fake-operation pattern in `shared-components.test.tsx`.
vi.mock('@/api/generated/reconciliation/reconciliation', () => ({
  getGetReconciliationQueryKey: (id?: string) => [
    `/api/v1/reconciliation-runs/${id}`,
  ],
  useGetReconciliation: makeScriptedGet('reconcile'),
}))

vi.mock('@/api/generated/artifact-builds/artifact-builds', () => ({
  getGetArtifactBuildQueryKey: (id?: string) => [`/api/v1/artifact-builds/${id}`],
  useGetArtifactBuild: makeScriptedGet('build'),
}))

// A scripted get-operation hook factory. It advances through the matching
// `pollSource[kind]` sequence once per refetch interval the caller passes, and
// stops once a terminal/undefined-interval is reached — close enough to a real
// TanStack refetch loop for the panel + useOperationPoll under fake timers.
function makeScriptedGet(kind: 'reconcile' | 'build') {
  return (
    _id: string,
    opts?: { query?: { enabled?: boolean; refetchInterval?: number | false } },
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
        const cur = seq[pollIndex[kind]]
        if (cur && typeof cur.status === 'string' &&
          ['completed', 'failed'].includes(cur.status)) {
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

// `invalidate.ts` reaches into many generated modules at import time; stub it
// so this file need not mock the whole SDTM/define/csdrg/acrf surface.
vi.mock('@/lib/invalidate', () => ({
  invalidateRawDependencies: vi.fn(),
  invalidateRawOperationArtifacts: vi.fn(),
}))

// ---------------------------------------------------------------------------
// Import AFTER the mocks so the panels bind to the stubs.
// ---------------------------------------------------------------------------
import { RawValidationPanel } from './raw-validation-panel'
import { ReconciliationPanel } from './reconciliation-panel'
import { ArtifactsPanel, RAW_ARTIFACT_TYPES } from './artifacts-panel'
import { DependenciesPanel } from './dependencies-panel'

// ---------------------------------------------------------------------------
// Fixtures.
// ---------------------------------------------------------------------------
function makeRun(
  overrides: Partial<ValidationRunResponse> = {},
): ValidationRunResponse {
  return {
    id: 'vr-1',
    study_id: 'study-1',
    owner_id: 'raw-1',
    status: 'passed',
    validator_name: 'raw-validator',
    validator_version: '1.0.0',
    input_fingerprint: 'fp-1',
    started_at: null,
    completed_at: null,
    error_count: 0,
    warning_count: 0,
    info_count: 0,
    issues: [],
    report_artifact_ids: [],
    ...overrides,
  } as ValidationRunResponse
}

function makeReconcile(
  overrides: Partial<ReconciliationResponse> = {},
): ReconciliationResponse {
  return {
    id: 'rr-1',
    study_id: 'study-1',
    reconciliation_type: 'raw_source_schema',
    reconciliation_version: '1.0.0',
    status: 'running',
    input_fingerprint: 'fp-1',
    started_at: null,
    completed_at: null,
    error_count: 0,
    warning_count: 0,
    info_count: 0,
    issues: [],
    report_artifact_ids: [],
    ...overrides,
  } as ReconciliationResponse
}

function makeBuild(
  overrides: Partial<ArtifactBuildResponse> = {},
): ArtifactBuildResponse {
  return {
    id: 'ab-1',
    input_fingerprint: 'fp-1',
    status: 'running',
    result_artifact_ids: [],
    failure: null,
    started_at: null,
    ...overrides,
  } as ArtifactBuildResponse
}

function makeAggregate(
  overrides: Partial<AggregateResponse> = {},
): AggregateResponse {
  return {
    id: 'raw-1',
    study_id: 'study-1',
    code: 'RAW',
    name: 'Raw workbench',
    status: 'draft',
    revision: 7,
    ...overrides,
  }
}

function makeDependencies(
  overrides: Partial<DependencySelectionResponse> = {},
): DependencySelectionResponse {
  return {
    standards: [],
    terminology: [],
    references: [],
    templates: [],
    revision: 3,
    state: 'current',
    fingerprint: 'dep-fp-1',
    ...overrides,
  } as DependencySelectionResponse
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
  const invalidateSpy = vi.spyOn(qc, 'invalidateQueries')
  const utils = render(
    <QueryClientProvider client={qc}>{ui}</QueryClientProvider>,
  )
  return { ...utils, qc, invalidateSpy }
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

beforeEach(() => {
  rawApi.validateImpl = async () => makeRun()
  rawApi.validateError = null
  rawApi.validationRun = { data: undefined, error: null, isLoading: false, isError: false }
  rawApi.reconcileImpl = async () => makeReconcile()
  rawApi.reconcileError = null
  rawApi.reconcileRequests = []
  rawApi.createArtifactsImpl = async () => makeBuild()
  rawApi.createArtifactsVars = []
  rawApi.createArtifactsRequests = []
  rawApi.previewFingerprintImpl = async () => ({ input_fingerprint: 'build-fp-1' })
  rawApi.previewFingerprintVars = []
  rawApi.dependencies = undefined
  rawApi.replaceDependenciesImpl = async () => ({})
  rawApi.replaceDependenciesRequests = []
  pollSource.reconcile = []
  pollSource.build = []
  pollIndex.reconcile = 0
  pollIndex.build = 0
})

afterEach(() => {
  vi.clearAllMocks()
})

// ===========================================================================
// Raw Validation (Req 6.1, 6.3, 6.5)
// ===========================================================================
describe('RawValidationPanel synchronous validate (Req 6.1, 6.3)', () => {
  it('renders status, per-severity counts, and issues on a 200 run', async () => {
    rawApi.validateImpl = async () =>
      makeRun({
        status: 'passed',
        error_count: 0,
        warning_count: 2,
        info_count: 1,
        issues: [
          {
            id: 'i1',
            code: 'RAW_LABEL_MISSING',
            severity: 'warning',
            message: 'Variable AGE is missing a label.',
            suggestion: 'Add a label.',
          },
          {
            id: 'i2',
            code: 'RAW_LENGTH_HINT',
            severity: 'warning',
            message: 'Length may be too small.',
          },
          {
            id: 'i3',
            code: 'RAW_INFO',
            severity: 'info',
            message: 'For your information.',
          },
        ],
      } as Partial<ValidationRunResponse>)

    renderWithClient(<RawValidationPanel rawId="raw-1" />)
    fireEvent.click(screen.getByRole('button', { name: /run validation/i }))

    const runCard = (await screen.findByText('Validation run')).closest(
      '[data-slot="card"]',
    ) as HTMLElement
    // Per-severity counts (the run header badges), scoped to the run card so
    // they don't collide with the IssueList's own per-severity summary.
    expect(within(runCard).getByText('Error: 0')).toBeTruthy()
    expect(within(runCard).getByText('Warning: 2')).toBeTruthy()
    expect(within(runCard).getByText('Info: 1')).toBeTruthy()
    // Validator identity.
    expect(screen.getByText(/raw-validator/)).toBeTruthy()
    // The IssueList renders the issues.
    expect(screen.getByText('Variable AGE is missing a label.')).toBeTruthy()
    expect(screen.getByText('RAW_LENGTH_HINT')).toBeTruthy()
  })

  it('renders the IssueList empty state when a run has no issues', async () => {
    rawApi.validateImpl = async () => makeRun({ status: 'passed', issues: [] })

    renderWithClient(<RawValidationPanel rawId="raw-1" />)
    fireEvent.click(screen.getByRole('button', { name: /run validation/i }))

    await waitFor(() => {
      expect(
        screen.getByText('This validation run produced no issues.'),
      ).toBeTruthy()
    })
  })

  it('shows the persistent block notice on a failed run (R6.3)', async () => {
    rawApi.validateImpl = async () =>
      makeRun({
        status: 'failed',
        error_count: 1,
        issues: [
          {
            id: 'e1',
            code: 'RAW_REQUIRED_MISSING',
            severity: 'error',
            message: 'A required value is missing.',
          },
        ],
      } as Partial<ValidationRunResponse>)

    renderWithClient(<RawValidationPanel rawId="raw-1" />)
    fireEvent.click(screen.getByRole('button', { name: /run validation/i }))

    await waitFor(() => {
      expect(screen.getByText('Artifact generation blocked')).toBeTruthy()
    })
    expect(
      screen.getByText(/block Raw artifact generation/i),
    ).toBeTruthy()
  })
})

describe('RawValidationPanel open-by-id (Req 6.5)', () => {
  it('renders the referenced run when the lookup resolves', () => {
    rawApi.validationRun = {
      data: makeRun({ id: 'vr-99', status: 'passed', warning_count: 1 }),
      error: null,
      isLoading: false,
      isError: false,
    }

    renderWithClient(<RawValidationPanel rawId="raw-1" />)
    fireEvent.change(screen.getByLabelText(/validation run id/i), {
      target: { value: 'vr-99' },
    })
    fireEvent.click(screen.getByRole('button', { name: /^open$/i }))

    // The looked-up run renders its own ValidationRunView.
    expect(screen.getAllByText('Validation run').length).toBeGreaterThan(0)
    expect(screen.getByText('Warning: 1')).toBeTruthy()
  })

  it('shows a not-found notice and NO stale content on a 404', () => {
    rawApi.validationRun = {
      data: undefined,
      error: problemError(404, { title: 'Not Found' }),
      isLoading: false,
      isError: true,
    }

    renderWithClient(<RawValidationPanel rawId="raw-1" />)
    fireEvent.change(screen.getByLabelText(/validation run id/i), {
      target: { value: 'missing-id' },
    })
    fireEvent.click(screen.getByRole('button', { name: /^open$/i }))

    // Not-found notice is shown…
    expect(screen.getByText('Validation run not found')).toBeTruthy()
    expect(
      screen.getByText('The referenced validation run is unavailable.'),
    ).toBeTruthy()
    // …and NO stale run content: no "Validation run" card from the lookup.
    expect(screen.queryByText('Validation run')).toBeNull()
  })
})

// ===========================================================================
// Raw Reconciliation (Req 7.2, 7.3)
// ===========================================================================
describe('ReconciliationPanel poll (Req 7.2)', () => {
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

  it('starts on 202 and polls the run to a completed terminal', async () => {
    // Scripted poll: running -> completed on the first refetch tick.
    pollSource.reconcile = [
      makeReconcile({ status: 'running' }),
      makeReconcile({
        status: 'completed',
        error_count: 0,
        warning_count: 1,
        info_count: 0,
        issues: [
          {
            id: 'w1',
            code: 'RECON_DRIFT',
            severity: 'warning',
            message: 'Schema drift detected.',
          },
        ],
      } as Partial<ReconciliationResponse>),
    ]
    rawApi.reconcileImpl = async () => pollSource.reconcile[0]

    renderInWorkbench(<ReconciliationPanel />)

    // Start: the 202 body id drives the poll. Flush the mutate promise so
    // onSuccess sets the run id (fake timers don't fake microtasks).
    fireEvent.click(screen.getByRole('button', { name: /start reconciliation/i }))
    await act(async () => {
      await Promise.resolve()
    })

    // The start pins the expected current revision as the body.
    expect(rawApi.reconcileRequests.length).toBeGreaterThan(0)

    // Advance one interval to the terminal poll.
    await act(async () => {
      vi.advanceTimersByTime(2_000)
      await Promise.resolve()
    })

    expect(screen.getByText('Reconciliation result')).toBeTruthy()
    expect(screen.getByText('Schema drift detected.')).toBeTruthy()
    // Polling stopped: no timeout notice.
    expect(screen.queryByText(/did not finish in time/i)).toBeNull()
  })

  it('trips the client timeout when the run never terminates (R7.2)', async () => {
    // Always running — never terminal.
    pollSource.reconcile = [makeReconcile({ status: 'running' })]
    rawApi.reconcileImpl = async () => pollSource.reconcile[0]

    renderInWorkbench(<ReconciliationPanel />)
    fireEvent.click(screen.getByRole('button', { name: /start reconciliation/i }))
    await act(async () => {
      await Promise.resolve()
    })

    // Advance past the 120s cap.
    await act(async () => {
      vi.advanceTimersByTime(120_000)
      await Promise.resolve()
    })

    expect(
      screen.getByText(/reconciliation run did not finish in time/i),
    ).toBeTruthy()
    expect(screen.queryByText('Reconciliation result')).toBeNull()
  })
})

describe('ReconciliationPanel stale input (Req 7.3)', () => {
  it('shows the stale message + reload action on a 409 stale_raw_reconciliation_input', async () => {
    const staleProblem = problemError(409, {
      title: 'Conflict',
      code: 'stale_raw_reconciliation_input',
      detail: 'Pinned revision 7 is behind the current revision 9.',
    })
    rawApi.reconcileImpl = async () => {
      throw staleProblem
    }
    // The hook exposes the mutation error inline; mirror it on the fixture.
    rawApi.reconcileError = staleProblem

    const { invalidateSpy } = renderInWorkbench(<ReconciliationPanel />)

    fireEvent.click(screen.getByRole('button', { name: /start reconciliation/i }))

    // The panel's stale title + the problem detail are both shown.
    await waitFor(() => {
      expect(
        screen.getByText('The expected Raw revision is no longer current.'),
      ).toBeTruthy()
    })
    expect(
      screen.getByText('Pinned revision 7 is behind the current revision 9.'),
    ).toBeTruthy()

    // The reload action re-fetches the current Raw aggregate revision (R7.3).
    fireEvent.click(screen.getByRole('button', { name: /reload current revision/i }))
    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({
        queryKey: ['/api/v1/raw/raw-1'],
      })
    })
  })
})

// ===========================================================================
// Raw Artifacts (Req 8.2, 8.3, 8.5)
// ===========================================================================
describe('ArtifactsPanel fixed types + submit gating (Req 8.2)', () => {
  it('offers exactly the four fixed Raw types and nothing else', () => {
    rawApi.dependencies = makeDependencies()
    renderWithClient(<ArtifactsPanel rawId="raw-1" studyId="study-1" />)

    // Exactly four artifact-type checkboxes within the fieldset.
    const group = screen.getByRole('group', { name: /raw artifact types/i })
    const checkboxes = within(group).getAllByRole('checkbox')
    expect(checkboxes).toHaveLength(RAW_ARTIFACT_TYPES.length)
    expect(checkboxes).toHaveLength(4)
    for (const type of RAW_ARTIFACT_TYPES) {
      expect(within(group).getByText(type.value)).toBeTruthy()
    }
  })

  it('disables the submit control while no type is selected (R8.2)', () => {
    rawApi.dependencies = makeDependencies()
    renderWithClient(<ArtifactsPanel rawId="raw-1" studyId="study-1" />)

    const submit = screen.getByRole('button', {
      name: /build artifacts/i,
    }) as HTMLButtonElement
    expect(submit.disabled).toBe(true)

    // Selecting one type enables it.
    fireEvent.click(screen.getByLabelText(/dependency manifest/i))
    expect(
      (screen.getByRole('button', { name: /build artifacts/i }) as HTMLButtonElement)
        .disabled,
    ).toBe(false)
  })

  it('resolves the fingerprint for the selected set and submits it', async () => {
    rawApi.previewFingerprintImpl = vi.fn(async () => ({
      input_fingerprint: 'build-fp-9',
    }))
    rawApi.createArtifactsImpl = vi.fn(async () => makeBuild())

    renderWithClient(<ArtifactsPanel rawId="raw-1" studyId="study-1" />)
    fireEvent.click(screen.getByLabelText(/metadata \(json\)/i))

    fireEvent.click(screen.getByRole('button', { name: /build artifacts/i }))
    await waitFor(() => {
      expect(rawApi.createArtifactsVars.length).toBe(1)
    })
    // The fingerprint is resolved from the preview endpoint for exactly the
    // selected artifact-type set before the build is started.
    expect(rawApi.previewFingerprintVars).toHaveLength(1)
    expect(rawApi.previewFingerprintVars[0]).toMatchObject({
      rawId: 'raw-1',
      data: { artifact_types: ['raw_metadata_json'] },
    })
    expect(rawApi.createArtifactsVars[0]).toMatchObject({
      rawId: 'raw-1',
      data: {
        artifact_types: ['raw_metadata_json'],
        expected_input_fingerprint: 'build-fp-9',
      },
    })
  })
})

describe('ArtifactsPanel poll + failed terminal (Req 8.3, 8.5)', () => {
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

  it('polls the build to a completed terminal and lists produced artifacts', async () => {
    rawApi.dependencies = makeDependencies()
    pollSource.build = [
      makeBuild({ status: 'running' }),
      makeBuild({ status: 'completed', result_artifact_ids: ['art-1', 'art-2'] }),
    ]
    rawApi.createArtifactsImpl = async () => pollSource.build[0]

    renderWithClient(<ArtifactsPanel rawId="raw-1" studyId="study-1" />)
    fireEvent.click(screen.getByLabelText(/dependency manifest/i))

    fireEvent.click(screen.getByRole('button', { name: /build artifacts/i }))
    await act(async () => {
      await Promise.resolve()
    })

    await act(async () => {
      vi.advanceTimersByTime(2_000)
      await Promise.resolve()
    })

    expect(screen.getByText('Produced artifacts')).toBeTruthy()
    // Two produced artifact rows with download buttons.
    expect(screen.getAllByRole('button', { name: /download/i })).toHaveLength(2)
  })

  it('shows the typed failure and NO download on a failed terminal (R8.5)', async () => {
    rawApi.dependencies = makeDependencies()
    pollSource.build = [
      makeBuild({ status: 'running' }),
      makeBuild({
        status: 'failed',
        result_artifact_ids: [],
        failure: { code: 'raw_build_error', detail: 'Generator crashed.' },
      } as Partial<ArtifactBuildResponse>),
    ]
    rawApi.createArtifactsImpl = async () => pollSource.build[0]

    renderWithClient(<ArtifactsPanel rawId="raw-1" studyId="study-1" />)
    fireEvent.click(screen.getByLabelText(/dependency manifest/i))

    fireEvent.click(screen.getByRole('button', { name: /build artifacts/i }))
    await act(async () => {
      await Promise.resolve()
    })

    await act(async () => {
      vi.advanceTimersByTime(2_000)
      await Promise.resolve()
    })

    expect(screen.getByText('The artifact build failed')).toBeTruthy()
    expect(screen.getByText('raw_build_error')).toBeTruthy()
    expect(screen.getByText('Generator crashed.')).toBeTruthy()
    // No produced-artifacts list and no download action on failure.
    expect(screen.queryByText('Produced artifacts')).toBeNull()
    expect(screen.queryByRole('button', { name: /download/i })).toBeNull()
  })
})

// ===========================================================================
// Raw Dependencies (Req 20.3, 20.4, 20.5)
// ===========================================================================
describe('DependenciesPanel invalid selection (Req 20.3)', () => {
  it('renders each incompatibility on a 422 dependency_selection_invalid', async () => {
    rawApi.dependencies = makeDependencies({ state: 'current' })
    rawApi.replaceDependenciesImpl = async () => {
      throw problemError(422, {
        title: 'Unprocessable',
        code: 'dependency_selection_invalid',
        detail: 'The selection has incompatibilities.',
        issues: [
          {
            id: 'd1',
            code: 'TERMINOLOGY_INCOMPATIBLE',
            severity: 'error',
            message: 'Terminology release is not compatible.',
            suggestion: 'Pin a compatible release.',
          },
          {
            id: 'd2',
            code: 'STANDARD_MISSING',
            severity: 'error',
            message: 'A required standard is unselected.',
            suggestion: 'Select the SDTMIG standard.',
          },
        ],
      })
    }

    renderInWorkbench(<DependenciesPanel rawId="raw-1" />)

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /replace selection/i })).toBeTruthy()
    })
    fireEvent.click(screen.getByRole('button', { name: /replace selection/i }))

    await waitFor(() => {
      expect(screen.getByText('Terminology release is not compatible.')).toBeTruthy()
    })
    expect(screen.getByText('A required standard is unselected.')).toBeTruthy()
    expect(screen.getByText(/Pin a compatible release\./)).toBeTruthy()
    expect(screen.getByText('The selection has incompatibilities.')).toBeTruthy()
  })
})

describe('DependenciesPanel concurrency (Req 20.4)', () => {
  it('shows the concurrency message and reloads the current revision on a 412', async () => {
    rawApi.dependencies = makeDependencies({ state: 'current', revision: 3 })
    rawApi.replaceDependenciesImpl = async () => {
      throw problemError(412, { title: 'Precondition Failed', detail: 'stale' })
    }

    const { invalidateSpy } = renderInWorkbench(<DependenciesPanel rawId="raw-1" />)

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /replace selection/i })).toBeTruthy()
    })
    fireEvent.click(screen.getByRole('button', { name: /replace selection/i }))

    // Concurrency message surfaced…
    await waitFor(() => {
      expect(screen.getByText(/changed since you opened it/i)).toBeTruthy()
    })
    // …and the current selection revision is reloaded before retry (R20.4).
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: ['/api/v1/raw/raw-1/dependencies'],
    })
  })
})

describe('DependenciesPanel refresh-required banner (Req 20.5)', () => {
  it('shows the banner and disables the save control when a refresh is required', async () => {
    rawApi.dependencies = makeDependencies({
      state: 'dependency_refresh_required',
    })

    renderInWorkbench(<DependenciesPanel rawId="raw-1" />)

    // The persistent staleness banner is shown.
    await waitFor(() => {
      expect(
        screen.getByText('Dependency selection needs a refresh'),
      ).toBeTruthy()
    })
    // The save (start-operation) control is disabled (R20.5).
    expect(
      (screen.getByRole('button', { name: /replace selection/i }) as HTMLButtonElement)
        .disabled,
    ).toBe(true)
  })

  it('leaves the save control enabled when the selection is current', async () => {
    rawApi.dependencies = makeDependencies({ state: 'current' })

    renderInWorkbench(<DependenciesPanel rawId="raw-1" />)

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /replace selection/i })).toBeTruthy()
    })
    expect(
      (screen.getByRole('button', { name: /replace selection/i }) as HTMLButtonElement)
        .disabled,
    ).toBe(false)
    // No banner when current.
    expect(
      screen.queryByText('Dependency selection needs a refresh'),
    ).toBeNull()
  })
})
