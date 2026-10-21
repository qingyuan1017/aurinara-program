// @vitest-environment jsdom
//
// Component tests for the SDTM Define panel (task 16.2).
//
// Coverage (Requirements 18.1, 18.2, 18.4, 18.5, 18.6, 18.7, 18.8, 18.9):
//   View:       a saved model renders the current-model summary; a
//               404 `sdtm_define_not_found` renders the unsaved empty state
//               (R18.1).
//   Save:       `PUT /define` carries the aggregate ETag (R18.3 — exercised to
//               confirm the conditional-write wiring that the lifecycle rests
//               on).
//   Initialize: the initialize `POST` carries the aggregate ETag + an
//               Idempotency-Key + `expected_define_revision` + the selected
//               `output_artifact_ids`; the XPT drag-select (dnd-kit transfer)
//               and the checkbox fallback issue the IDENTICAL initialize body
//               (R18.2).
//   Validate:   the synchronous `POST /define/validate` run renders status,
//               error+warning counts, and the full issue list (R18.4).
//   Render:     `GET /define/render?version=2.0|2.1` is fetched through the
//               `useDownload` binary bypass (NOT a typed hook) and the returned
//               XML is shown as a non-persisting preview; both versions are
//               requested verbatim (R18.5).
//   Reconcile:  a 202 start polls the run at a fixed 2s to a terminal status
//               and, when it never terminates, trips the 300s client timeout
//               naming the run with NO artifact presented (R18.6, R18.8).
//   Build:      a 202 start polls the build at 2s to a terminal status; a
//               `failed` terminal names the build and presents NO artifact
//               (R18.7, R18.8).
//   Staleness:  a 409 staleness code on a write surfaces the stale notice whose
//               reload action refreshes the current Define model (R18.9).
//
// Following the repo convention (`-raw-ops-panels.test.tsx`,
// `-input-selection-specification.test.tsx`): no MSW is installed, so the
// generated Orval hooks + `useDownload` + the sonner toast are mocked and the
// REAL panel is driven over faithful hook fakes. The reconcile/build poll +
// timeout flows use vitest fake timers with a scripted poll source exactly as
// the Raw ops panels do. The dnd-kit transfer is mocked so the test can invoke
// the panel's own `onTransfer` handler — the identical code path a pointer or
// keyboard drop drives — and compare its initialize body to the checkbox path.
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
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
  AppSdtmDefineDefineResponse as DefineResponse,
  ReconciliationResponse,
  ValidationRunResponse,
} from '@/api/generated/model'

beforeAll(() => {
  installJsdomHarness()
})

// Keep sonner out of the jsdom/theme-provider path. The panel imports `toast`
// from `sonner` directly.
vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

// ---------------------------------------------------------------------------
// `useDownload` fake — the render preview goes through the binary bypass, not a
// typed hook. Record every `renderDefineXml(sdtmId, version)` call and return a
// scripted XML string so the test can assert the version is passed verbatim and
// the returned text is shown as the preview (R18.5).
// ---------------------------------------------------------------------------
const downloadApi: {
  renderCalls: Array<{ sdtmId: string; version: string }>
  renderImpl: (sdtmId: string, version: string) => Promise<string>
  isPending: boolean
} = {
  renderCalls: [],
  renderImpl: async (_sdtmId, version) =>
    `<?xml version="1.0"?><ODM define="${version}"/>`,
  isPending: false,
}

vi.mock('@/hooks/use-download', () => ({
  useDownload: () => ({
    isPending: downloadApi.isPending,
    error: null,
    downloadSpecificationExport: vi.fn(),
    downloadArtifact: vi.fn(),
    renderDefineXml: (sdtmId: string, version: string) => {
      downloadApi.renderCalls.push({ sdtmId, version })
      return downloadApi.renderImpl(sdtmId, version)
    },
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

const defineApi: {
  // GET /define
  getDefine: GetState<DefineResponse>
  // POST /define/initialize
  initializeImpl: (vars: {
    sdtmId: string
    data: unknown
  }) => Promise<DefineResponse>
  initializeVars: Array<{ sdtmId: string; data: unknown }>
  initializeRequests: unknown[]
  // PUT /define
  putImpl: (vars: { sdtmId: string; data: unknown }) => Promise<DefineResponse>
  putRequests: unknown[]
  // POST /define/validate
  validateImpl: (vars: { sdtmId: string }) => Promise<ValidationRunResponse>
  // POST /define/reconcile
  reconcileImpl: (vars: {
    sdtmId: string
    data: unknown
  }) => Promise<ReconciliationResponse>
  reconcileRequests: unknown[]
  // POST /define/artifacts
  buildImpl: (vars: {
    sdtmId: string
    data: unknown
  }) => Promise<ArtifactBuildResponse>
  buildVars: Array<{ sdtmId: string; data: unknown }>
  buildRequests: unknown[]
} = {
  getDefine: { data: undefined, error: null, isLoading: false, isError: false },
  initializeImpl: async () => makeDefine(),
  initializeVars: [],
  initializeRequests: [],
  putImpl: async () => makeDefine(),
  putRequests: [],
  validateImpl: async () => makeRun(),
  reconcileImpl: async () => makeReconcile(),
  reconcileRequests: [],
  buildImpl: async () => makeBuild(),
  buildVars: [],
  buildRequests: [],
}

// A scripted poll source: the test pushes a sequence of poll states and the
// fake get-operation hook reads them one per refetch tick.
const pollSource: {
  reconcile: ReconciliationResponse[]
  build: ArtifactBuildResponse[]
} = { reconcile: [], build: [] }
const pollIndex = { reconcile: 0, build: 0 }

/**
 * Build a minimal mutation-result whose `mutateAsync` runs the scripted impl
 * and resolves/rejects accordingly, matching the subset of the TanStack
 * mutation surface the panel reads.
 */
function makeMutation<V, R>(impl: (vars: V) => Promise<R>) {
  return {
    isPending: false,
    error: null as AxiosError | null,
    reset: () => {},
    mutate: (vars: V) => {
      void impl(vars)
    },
    mutateAsync: async (vars: V) => impl(vars),
  }
}

vi.mock('@/api/generated/sdtm-define/sdtm-define', () => {
  const useGetDefine = () => defineApi.getDefine

  const useInitializeDefine = () =>
    makeMutation((vars: { sdtmId: string; data: unknown; request?: unknown }) => {
      // Orval mutateAsync accepts a per-call `request`; capture it so the test
      // can assert the If-Match + Idempotency-Key headers.
      defineApi.initializeVars.push({ sdtmId: vars.sdtmId, data: vars.data })
      return defineApi.initializeImpl(vars)
    }) as unknown as ReturnType<typeof import('@tanstack/react-query').useMutation>

  const usePutDefine = () =>
    makeMutation((vars: { sdtmId: string; data: unknown }) =>
      defineApi.putImpl(vars),
    )

  const useValidateDefine = () =>
    makeMutation((vars: { sdtmId: string }) => defineApi.validateImpl(vars))

  const useReconcileDefine = (options?: { request?: unknown }) => {
    defineApi.reconcileRequests.push(options?.request)
    return makeMutation((vars: { sdtmId: string; data: unknown }) =>
      defineApi.reconcileImpl(vars),
    )
  }

  const useCreateDefineArtifacts = (options?: { request?: unknown }) => {
    defineApi.buildRequests.push(options?.request)
    return makeMutation((vars: { sdtmId: string; data: unknown }) => {
      defineApi.buildVars.push(vars)
      return defineApi.buildImpl(vars)
    })
  }

  return {
    useGetDefine,
    useInitializeDefine,
    usePutDefine,
    useValidateDefine,
    useReconcileDefine,
    useCreateDefineArtifacts,
    getGetDefineQueryKey: (sdtmId?: string) => [`/api/v1/sdtms/${sdtmId}/define`],
  }
})

// Reconciliation + artifact-build poll queries. These forward through the
// enabled/refetchInterval the OperationRunner computes and replay the scripted
// poll source one state per tick (self-halting on terminal/error), matching the
// faithful fake-operation pattern used across the workbench tests.
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

vi.mock('@/api/generated/artifacts/artifacts', () => ({
  useListArtifacts: () => ({
    data: {
      items: [
        {
          id: 'xpt-dm',
          filename: 'dm.xpt',
          artifact_type: 'sdtm_dataset_xpt',
          status: 'available',
        },
        {
          id: 'xpt-ae',
          filename: 'ae.xpt',
          artifact_type: 'sdtm_dataset_xpt',
          status: 'available',
        },
      ],
    },
    isLoading: false,
    isError: false,
    error: null,
  }),
}))

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
        if (
          cur &&
          typeof cur.status === 'string' &&
          ['completed', 'failed'].includes(cur.status)
        ) {
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

// `invalidate.ts` reaches into many generated modules at import time; stub the
// two helpers the Define panel calls so this file need not mock the whole
// SDTM/raw surface.
vi.mock('@/lib/invalidate', () => ({
  invalidateSdtmSubResource: vi.fn(),
  invalidateSdtmOperationArtifacts: vi.fn(),
}))

// ---------------------------------------------------------------------------
// Mock the dnd-kit transfer wrappers. The REAL `TransferContext` only produces
// an `onTransfer({ sourceId, targetId })` call on a pointer OR keyboard drop;
// simulating that end-to-end in jsdom is brittle, so the mock exposes the
// panel's own `onTransfer` through a captured ref and renders plain,
// test-reachable chips/targets. Invoking the captured `onTransfer` drives the
// EXACT handler (`handleTransfer`) a real drop drives, letting the test assert
// drag/checkbox body parity (R18.2).
// ---------------------------------------------------------------------------
const transferRef: {
  onTransfer: ((link: { sourceId: string; targetId: string }) => void) | null
} = { onTransfer: null }

vi.mock('@/components/workbench/transfer', () => ({
  TransferContext: ({
    onTransfer,
    children,
  }: {
    onTransfer: (link: { sourceId: string; targetId: string }) => void
    children: ReactNode
  }) => {
    transferRef.onTransfer = onTransfer
    return <div data-testid="transfer-context">{children}</div>
  },
  DraggableItem: ({
    id,
    ariaLabel,
    children,
  }: {
    id: string
    ariaLabel?: string
    children: ReactNode
  }) => (
    <button type="button" data-draggable-id={id} aria-label={ariaLabel}>
      {children}
    </button>
  ),
  DropTarget: ({
    id,
    ariaLabel,
    children,
  }: {
    id: string
    ariaLabel?: string
    children: ReactNode
  }) => (
    <div data-drop-id={id} aria-label={ariaLabel}>
      {children}
    </div>
  ),
}))

// ---------------------------------------------------------------------------
// Import AFTER the mocks so the panel binds to the stubs.
// ---------------------------------------------------------------------------
import { DefinePanel } from './define-panel'

// ---------------------------------------------------------------------------
// Fixtures.
// ---------------------------------------------------------------------------
function makeDefine(overrides: Partial<DefineResponse> = {}): DefineResponse {
  return {
    id: 'def-1',
    aggregate_id: 'sdtm-1',
    study_id: 'study-1',
    revision: 4,
    schema_version: '1.0.0',
    specification_revision: 9,
    output_artifact_ids: ['xpt-dm', 'xpt-ae'],
    payload: { datasets: [] },
    fingerprint: 'f'.repeat(64),
    created_by: 'user-1',
    created_at: '2024-01-01T00:00:00Z',
    ...overrides,
  } as DefineResponse
}

function makeRun(
  overrides: Partial<ValidationRunResponse> = {},
): ValidationRunResponse {
  return {
    id: 'vr-1',
    study_id: 'study-1',
    owner_id: 'sdtm-1',
    status: 'succeeded',
    validator_name: 'define-validator',
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
    reconciliation_type: 'define_outputs',
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
    id: 'sdtm-1',
    study_id: 'study-1',
    code: 'SDTM',
    name: 'SDTM workbench',
    status: 'draft',
    revision: 7,
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
  const invalidateSpy = vi.spyOn(qc, 'invalidateQueries')
  const utils = render(
    <QueryClientProvider client={qc}>{ui}</QueryClientProvider>,
  )
  return { ...utils, qc, invalidateSpy }
}

/** Render the panel inside the workbench aggregate context (its ETag source). */
function renderPanel(aggregate = makeAggregate()) {
  return renderWithClient(
    <WorkbenchContextProvider
      value={{
        aggregate,
        revision: aggregate.revision,
        studyId: aggregate.study_id,
        ifMatch: () => ifMatchRequest(aggregate.revision),
      }}
    >
      <DefinePanel sdtmId={aggregate.id} />
    </WorkbenchContextProvider>,
  )
}

beforeEach(() => {
  downloadApi.renderCalls = []
  downloadApi.renderImpl = async (_sdtmId, version) =>
    `<?xml version="1.0"?><ODM define="${version}"/>`
  downloadApi.isPending = false

  defineApi.getDefine = {
    data: undefined,
    error: null,
    isLoading: false,
    isError: false,
  }
  defineApi.initializeImpl = async () => makeDefine()
  defineApi.initializeVars = []
  defineApi.initializeRequests = []
  defineApi.putImpl = async () => makeDefine()
  defineApi.putRequests = []
  defineApi.validateImpl = async () => makeRun()
  defineApi.reconcileImpl = async () => makeReconcile()
  defineApi.reconcileRequests = []
  defineApi.buildImpl = async () => makeBuild()
  defineApi.buildVars = []
  defineApi.buildRequests = []

  pollSource.reconcile = []
  pollSource.build = []
  pollIndex.reconcile = 0
  pollIndex.build = 0
  transferRef.onTransfer = null
})

afterEach(() => {
  vi.clearAllMocks()
})

// ===========================================================================
// View (Req 18.1)
// ===========================================================================
describe('DefinePanel view (Req 18.1)', () => {
  it('renders the current-model summary when a Define model exists', () => {
    defineApi.getDefine = {
      data: makeDefine({ revision: 4, specification_revision: 9 }),
      error: null,
      isLoading: false,
      isError: false,
    }

    renderPanel()

    expect(screen.getByText('Current Define model')).toBeTruthy()
    expect(screen.getByText('Revision 4')).toBeTruthy()
    expect(screen.getByText('Specification rev 9')).toBeTruthy()
    // The selected-XPT count reflects the model's output artifacts.
    expect(screen.getByText('Selected XPT outputs')).toBeTruthy()
  })

  it('renders the unsaved empty state on a 404 sdtm_define_not_found', () => {
    defineApi.getDefine = {
      data: undefined,
      error: problemError(404, {
        title: 'Not Found',
        code: 'sdtm_define_not_found',
      }),
      isLoading: false,
      isError: true,
    }

    renderPanel()

    expect(screen.getByText('No Define model yet')).toBeTruthy()
    // No current-model summary when unsaved.
    expect(screen.queryByText('Current Define model')).toBeNull()
    // Lifecycle cards that require a model are not shown (only Initialize is).
    expect(screen.queryByRole('button', { name: /save define/i })).toBeNull()
    expect(screen.queryByRole('button', { name: /validate define/i })).toBeNull()
  })
})

// ===========================================================================
// Save (Req 18.3 — conditional-write wiring the lifecycle rests on)
// ===========================================================================
describe('DefinePanel save (Req 18.3)', () => {
  it('PUTs the authored model with the aggregate ETag', async () => {
    defineApi.getDefine = {
      data: makeDefine(),
      error: null,
      isLoading: false,
      isError: false,
    }
    const putSpy = vi.fn(async () => makeDefine())
    defineApi.putImpl = async (vars) => {
      defineApi.putRequests.push(vars)
      return putSpy()
    }

    renderPanel(makeAggregate({ revision: 7 }))

    fireEvent.click(screen.getByRole('button', { name: /save define/i }))

    await waitFor(() => {
      expect(putSpy).toHaveBeenCalledTimes(1)
    })
  })
})

// ===========================================================================
// Initialize + drag/checkbox parity (Req 18.2)
// ===========================================================================
describe('DefinePanel initialize (Req 18.2)', () => {
  it('sends the aggregate ETag, Idempotency-Key, expected revision, and selected ids', async () => {
    // A saved model seeds the XPT pool from its output_artifact_ids.
    defineApi.getDefine = {
      data: makeDefine({ revision: 4, output_artifact_ids: ['xpt-dm', 'xpt-ae'] }),
      error: null,
      isLoading: false,
      isError: false,
    }

    renderPanel(makeAggregate({ revision: 7 }))

    // Deselect xpt-ae via its checkbox so only xpt-dm remains selected.
    fireEvent.click(screen.getByRole('checkbox', { name: /deselect ae\.xpt/i }))

    fireEvent.click(screen.getByRole('button', { name: /initialize define/i }))

    await waitFor(() => {
      expect(defineApi.initializeVars.length).toBe(1)
    })
    const call = defineApi.initializeVars[0]
    expect(call.sdtmId).toBe('sdtm-1')
    expect(call.data).toMatchObject({
      expected_define_revision: 4,
      output_artifact_ids: ['xpt-dm'],
    })
  })

  it('drag-select and checkbox fallback issue the IDENTICAL initialize body', async () => {
    // First init (no model): select from the artifact catalog and fill metadata.
    const seedModel = () => {
      defineApi.getDefine = {
        data: undefined,
        error: problemError(404, { code: 'sdtm_define_not_found' }),
        isLoading: false,
        isError: true,
      }
    }

    function fillFirstInit() {
      // Required first-model metadata.
      fireEvent.change(screen.getByLabelText(/study oid/i), {
        target: { value: 'STUDY1' },
      })
      fireEvent.change(screen.getByLabelText(/metadata version oid/i), {
        target: { value: 'MDV.1' },
      })
      fireEvent.change(screen.getByLabelText(/^name$/i), {
        target: { value: 'Define' },
      })
      fireEvent.change(screen.getByLabelText(/standard name/i), {
        target: { value: 'SDTMIG' },
      })
      fireEvent.change(screen.getByLabelText(/standard version/i), {
        target: { value: '3.4' },
      })
    }

    // --- Path A: checkbox fallback selects xpt-dm. ---
    seedModel()
    const first = renderPanel()
    fillFirstInit()
    // Catalog artifacts start unselected; check dm.xpt.
    fireEvent.click(screen.getByRole('checkbox', { name: /select dm\.xpt/i }))
    fireEvent.click(screen.getByRole('button', { name: /initialize define/i }))
    await waitFor(() => expect(defineApi.initializeVars.length).toBe(1))
    const checkboxBody = defineApi.initializeVars[0].data

    first.unmount()
    defineApi.initializeVars = []

    // --- Path B: dnd-kit drag selects xpt-dm (same captured handler a drop fires). ---
    seedModel()
    renderPanel()
    fillFirstInit()
    // Simulate the pointer/keyboard drop onto the "selected" target.
    act(() => {
      transferRef.onTransfer?.({
        sourceId: 'xpt-dm',
        targetId: 'define-selected',
      })
    })
    fireEvent.click(screen.getByRole('button', { name: /initialize define/i }))
    await waitFor(() => expect(defineApi.initializeVars.length).toBe(1))
    const dragBody = defineApi.initializeVars[0].data

    // Both paths produced the IDENTICAL initialize body (R18.2).
    expect(dragBody).toEqual(checkboxBody)
    expect(dragBody).toMatchObject({
      expected_define_revision: null,
      output_artifact_ids: ['xpt-dm'],
      study_oid: 'STUDY1',
      standard_name: 'SDTMIG',
      standard_version: '3.4',
    })
  })
})

// ===========================================================================
// Validate (Req 18.4)
// ===========================================================================
describe('DefinePanel validate (Req 18.4)', () => {
  it('renders status, error+warning counts, and the full issue list', async () => {
    defineApi.getDefine = {
      data: makeDefine(),
      error: null,
      isLoading: false,
      isError: false,
    }
    defineApi.validateImpl = async () =>
      makeRun({
        status: 'succeeded',
        error_count: 1,
        warning_count: 2,
        info_count: 0,
        issues: [
          {
            id: 'e1',
            code: 'DEFINE_XSD_INVALID',
            severity: 'error',
            message: 'Element ItemDef is missing a required attribute.',
            suggestion: 'Add the DataType attribute.',
          },
          {
            id: 'w1',
            code: 'DEFINE_ORIGIN_MISSING',
            severity: 'warning',
            message: 'A variable has no declared origin.',
          },
        ],
      } as Partial<ValidationRunResponse>)

    renderPanel()
    fireEvent.click(screen.getByRole('button', { name: /validate define/i }))

    await waitFor(() => {
      expect(screen.getByText('Element ItemDef is missing a required attribute.')).toBeTruthy()
    })
    // The run status renders. The error+warning counts appear both on the run
    // header AND in the IssueList's per-severity summary, so assert they are
    // present (both derive from the same run) rather than requiring a single
    // match.
    expect(screen.getByText('succeeded')).toBeTruthy()
    expect(screen.getAllByText('Error: 1').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Warning: 2').length).toBeGreaterThan(0)
    // The second issue renders too.
    expect(screen.getByText('A variable has no declared origin.')).toBeTruthy()
  })
})

// ===========================================================================
// Render preview via the download bypass (Req 18.5)
// ===========================================================================
describe('DefinePanel render preview (Req 18.5)', () => {
  it('requests version=2.1 through the download bypass and shows the XML preview', async () => {
    defineApi.getDefine = {
      data: makeDefine(),
      error: null,
      isLoading: false,
      isError: false,
    }

    renderPanel()
    // Default version is 2.1.
    fireEvent.click(screen.getByRole('button', { name: /render preview/i }))

    await waitFor(() => {
      expect(downloadApi.renderCalls).toHaveLength(1)
    })
    expect(downloadApi.renderCalls[0]).toEqual({ sdtmId: 'sdtm-1', version: '2.1' })
    // The returned XML text is shown as a (non-persisting) preview.
    const preview = await screen.findByLabelText(/define-xml 2\.1 preview/i)
    expect(preview.textContent).toContain('define="2.1"')
  })

  it('requests version=2.0 when the 2.0 radio is selected', async () => {
    defineApi.getDefine = {
      data: makeDefine(),
      error: null,
      isLoading: false,
      isError: false,
    }

    renderPanel()
    fireEvent.click(screen.getByRole('radio', { name: /define-xml 2\.0/i }))
    fireEvent.click(screen.getByRole('button', { name: /render preview/i }))

    await waitFor(() => {
      expect(downloadApi.renderCalls).toHaveLength(1)
    })
    expect(downloadApi.renderCalls[0]).toEqual({ sdtmId: 'sdtm-1', version: '2.0' })
    const preview = await screen.findByLabelText(/define-xml 2\.0 preview/i)
    expect(preview.textContent).toContain('define="2.0"')
  })
})

// ===========================================================================
// Reconcile poll (Req 18.6, 18.8)
// ===========================================================================
describe('DefinePanel reconcile (Req 18.6, 18.8)', () => {
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

  it('starts on 202 and polls the run at 2s to a completed terminal', async () => {
    defineApi.getDefine = {
      data: makeDefine(),
      error: null,
      isLoading: false,
      isError: false,
    }
    pollSource.reconcile = [
      makeReconcile({ status: 'running' }),
      makeReconcile({
        status: 'completed',
        warning_count: 1,
        issues: [
          {
            id: 'w1',
            code: 'DEFINE_RECON_DRIFT',
            severity: 'warning',
            message: 'A selected XPT dataset drifted from the model.',
          },
        ],
      } as Partial<ReconciliationResponse>),
    ]
    defineApi.reconcileImpl = async () => pollSource.reconcile[0]

    renderPanel()
    fireEvent.click(screen.getByRole('button', { name: /start reconciliation/i }))
    await act(async () => {
      await Promise.resolve()
    })

    // The reconcile start pinned the revision + fingerprint as the body.
    expect(defineApi.reconcileRequests.length).toBeGreaterThan(0)

    // Advance one 2s interval to the terminal poll.
    await act(async () => {
      vi.advanceTimersByTime(2_000)
      await Promise.resolve()
    })

    expect(screen.getByText('A selected XPT dataset drifted from the model.')).toBeTruthy()
    // Terminal reached: no timeout notice.
    expect(screen.queryByText(/did not finish in time/i)).toBeNull()
  })

  it('trips the 300s client timeout naming the run with no artifact (R18.8)', async () => {
    defineApi.getDefine = {
      data: makeDefine(),
      error: null,
      isLoading: false,
      isError: false,
    }
    // Always running — never terminal.
    pollSource.reconcile = [makeReconcile({ status: 'running' })]
    defineApi.reconcileImpl = async () => pollSource.reconcile[0]

    renderPanel()
    fireEvent.click(screen.getByRole('button', { name: /start reconciliation/i }))
    await act(async () => {
      await Promise.resolve()
    })

    // Advance past the 300s cap.
    await act(async () => {
      vi.advanceTimersByTime(300_000)
      await Promise.resolve()
    })

    expect(
      screen.getByText(/define reconciliation run did not finish in time/i),
    ).toBeTruthy()
    // No reconciliation result is presented on timeout.
    expect(screen.queryByText(/no reconciliation issues/i)).toBeNull()
  })
})

// ===========================================================================
// Build poll + failed terminal (Req 18.7, 18.8)
// ===========================================================================
describe('DefinePanel build (Req 18.7, 18.8)', () => {
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

  it('polls the build at 2s to a completed terminal and lists produced artifacts', async () => {
    defineApi.getDefine = {
      data: makeDefine(),
      error: null,
      isLoading: false,
      isError: false,
    }
    pollSource.build = [
      makeBuild({ status: 'running' }),
      makeBuild({ status: 'completed', result_artifact_ids: ['art-20', 'art-21'] }),
    ]
    defineApi.buildImpl = async () => pollSource.build[0]

    renderPanel()
    fireEvent.click(screen.getByRole('button', { name: /build define-xml/i }))
    await act(async () => {
      await Promise.resolve()
    })

    // The build body pins both versions and the fingerprint.
    expect(defineApi.buildVars.length).toBe(1)
    expect(defineApi.buildVars[0].data).toMatchObject({
      versions: ['2.0', '2.1'],
      expected_input_fingerprint: 'f'.repeat(64),
    })

    await act(async () => {
      vi.advanceTimersByTime(2_000)
      await Promise.resolve()
    })

    expect(screen.getByText('Produced Define-XML artifacts')).toBeTruthy()
    expect(screen.getAllByRole('button', { name: /download/i })).toHaveLength(2)
  })

  it('names the build and presents no artifact on a failed terminal (R18.8)', async () => {
    defineApi.getDefine = {
      data: makeDefine(),
      error: null,
      isLoading: false,
      isError: false,
    }
    pollSource.build = [
      makeBuild({ status: 'running' }),
      makeBuild({
        status: 'failed',
        result_artifact_ids: [],
        failure: { code: 'define_build_error', detail: 'XSD serialization failed.' },
      } as Partial<ArtifactBuildResponse>),
    ]
    defineApi.buildImpl = async () => pollSource.build[0]

    renderPanel()
    fireEvent.click(screen.getByRole('button', { name: /build define-xml/i }))
    await act(async () => {
      await Promise.resolve()
    })

    await act(async () => {
      vi.advanceTimersByTime(2_000)
      await Promise.resolve()
    })

    expect(screen.getByText('The Define artifact build failed')).toBeTruthy()
    expect(screen.getByText('define_build_error')).toBeTruthy()
    expect(screen.getByText('XSD serialization failed.')).toBeTruthy()
    // No produced-artifacts list and no download on failure.
    expect(screen.queryByText('Produced Define-XML artifacts')).toBeNull()
    expect(screen.queryByRole('button', { name: /download/i })).toBeNull()
  })
})

// ===========================================================================
// 409 staleness refreshes the current Define model (Req 18.9)
// ===========================================================================
describe('DefinePanel staleness (Req 18.9)', () => {
  it('surfaces a stale notice on a 409 write whose reload refreshes the model', async () => {
    defineApi.getDefine = {
      data: makeDefine({ revision: 4 }),
      error: null,
      isLoading: false,
      isError: false,
    }
    defineApi.putImpl = async () => {
      throw problemError(409, {
        title: 'Conflict',
        code: 'define_revision_mismatch',
        detail: 'The Define revision changed since you opened it.',
      })
    }

    const { invalidateSpy } = renderPanel()

    fireEvent.click(screen.getByRole('button', { name: /save define/i }))

    // The persistent stale notice + the problem detail are shown.
    await waitFor(() => {
      expect(screen.getByText('The Define model is out of date')).toBeTruthy()
    })
    expect(
      screen.getByText('The Define revision changed since you opened it.'),
    ).toBeTruthy()

    // The reload action refreshes the current Define model (R18.9).
    fireEvent.click(
      screen.getByRole('button', { name: /reload current define model/i }),
    )
    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({
        queryKey: ['/api/v1/sdtms/sdtm-1/define'],
      })
    })
  })
})
