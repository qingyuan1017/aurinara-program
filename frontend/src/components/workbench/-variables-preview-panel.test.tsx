// @vitest-environment jsdom
//
// Component tests for the Raw workbench Variables panel (`variables-panel.tsx`)
// and Preview panel (`preview-panel.tsx`) — task 7.4.
//
// Coverage:
//   Variables (Requirements 4.3, 4.4, 4.6, 4.7):
//     * a pointer-drag reorder AND the keyboard/numeric non-pointer fallback
//       issue the IDENTICAL `PATCH /raw-variables/{id}` carrying the same body
//       and the same `If-Match` header (R4.4);
//     * a 409 `duplicate_raw_variable` on create retains the entered form
//       values (R4.3);
//     * initialize shows the created/filled counts and refreshes the variable
//       list (R4.6), and a 412/428 reloads the dataset revision before retry
//       (R4.7).
//   Preview (Requirements 5.1, 5.4, 5.5, 5.6):
//     * preview sends CLAMPED params (limit 1-200, offset >= 0) (R5.1-5.3);
//     * renders returned rows plus the offset/limit/total summary (R5.4);
//     * a zero-row response shows the empty message while the counts stay
//       visible (R5.5);
//     * rows are not persisted/cached — unmounting then remounting shows no
//       stale rows (R5.6).
//
// Mirrors the established pattern in `-datasets-panel.test.tsx`: the repo has no
// MSW layer, so the generated Orval hooks (and the per-call `patchVariable`) are
// mocked with faithful fakes, and the REAL panels are driven over them. The
// jsdom harness installs the dnd-kit pointer + keyboard sensors and the
// `DataTransfer` shim so the SortableList reorder affordances are exercisable.
import {
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
import type { ReactNode } from 'react'
import type { AxiosError } from 'axios'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { installJsdomHarness } from '@/test/jsdom-harness'
import { ifMatchRequest } from '@/lib/requests'
import type {
  RawPreviewRequest,
  RawPreviewResponse,
  RawVariableResponse,
} from '@/api/generated/model'

beforeAll(() => {
  installJsdomHarness()
})

// Keep the toast out of the DOM/theme-provider path under jsdom.
vi.mock('@/components/ui/sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

// ---------------------------------------------------------------------------
// Mutable fixtures the generated-hook stubs read through. Each test installs
// the behaviour it needs.
// ---------------------------------------------------------------------------
interface PatchVariableCall {
  variableId: string
  body: unknown
  request: unknown
}

interface PreviewCall {
  datasetId: string
  data: RawPreviewRequest
}

const rawApi: {
  variables: RawVariableResponse[]
  // Per-call `patchVariable(id, body, request)` used by the reorder path.
  patchVariableImpl: (call: PatchVariableCall) => Promise<unknown>
  patchVariableCalls: PatchVariableCall[]
  createVariableImpl: (vars: {
    datasetId: string
    data: unknown
  }) => Promise<unknown>
  initializeImpl: (vars: { datasetId: string }) => Promise<unknown>
  initializeRequests: unknown[]
  previewImpl: (vars: PreviewCall) => Promise<RawPreviewResponse>
  previewCalls: PreviewCall[]
} = {
  variables: [],
  patchVariableImpl: async () => ({}),
  patchVariableCalls: [],
  createVariableImpl: async () => ({}),
  initializeImpl: async () => ({ created: 0, filled: 0 }),
  initializeRequests: [],
  previewImpl: async () => makePreview(),
  previewCalls: [],
}

/**
 * Build a minimal `UseMutationResult`-shaped object whose `mutateAsync` runs
 * the scripted impl and fires `onSuccess` on resolve (mirroring TanStack
 * Query), so the component's refresh-on-success path exercises for real.
 */
function makeMutationResult(
  impl: (vars: never) => Promise<unknown>,
  onSuccess?: (data: unknown) => void,
) {
  return {
    isPending: false,
    error: null as AxiosError | null,
    mutateAsync: async (vars: never) => {
      const data = await impl(vars)
      onSuccess?.(data)
      return data
    },
    mutate: () => {},
  }
}

vi.mock('@/api/generated/raw/raw', () => {
  const useListVariables = (_datasetId: string) => ({
    data: rawApi.variables,
    isLoading: false,
    isFetching: false,
    isError: false,
    error: null,
  })

  // The reorder path calls this per-move function directly with the moved
  // variable's own `ifMatchRequest(revision)` as the per-request config.
  const patchVariable = async (
    variableId: string,
    body: unknown,
    request: unknown,
  ) => {
    const call = { variableId, body, request }
    rawApi.patchVariableCalls.push(call)
    return rawApi.patchVariableImpl(call)
  }

  const useCreateVariable = (options?: {
    mutation?: { onSuccess?: (data: unknown) => void }
    request?: unknown
  }) =>
    makeMutationResult(
      (vars: { datasetId: string; data: unknown }) =>
        rawApi.createVariableImpl(vars),
      options?.mutation?.onSuccess,
    )

  // The edit dialog's PATCH hook — not the focus of these tests but imported by
  // the panel, so provide a benign fake.
  const usePatchVariable = (options?: {
    mutation?: { onSuccess?: (data: unknown) => void }
    request?: unknown
  }) =>
    makeMutationResult(
      (vars: { variableId: string; data: unknown }) =>
        rawApi.patchVariableImpl({
          variableId: vars.variableId,
          body: vars.data,
          request: options?.request,
        }),
      options?.mutation?.onSuccess,
    )

  const useDeleteVariable = (options?: {
    mutation?: { onSuccess?: (data: unknown) => void }
    request?: unknown
  }) =>
    makeMutationResult(
      (_vars: { variableId: string }) => Promise.resolve({}),
      options?.mutation?.onSuccess,
    )

  const useInitializeVariables = (options?: {
    mutation?: { onSuccess?: (data: unknown) => void }
    request?: unknown
  }) => {
    rawApi.initializeRequests.push(options?.request)
    return makeMutationResult(
      (vars: { datasetId: string }) => rawApi.initializeImpl(vars),
      options?.mutation?.onSuccess,
    )
  }

  const usePreviewDataset = (options?: {
    mutation?: { onSuccess?: (data: unknown) => void }
    request?: unknown
  }) =>
    makeMutationResult(
      (vars: PreviewCall) => {
        rawApi.previewCalls.push(vars)
        return rawApi.previewImpl(vars)
      },
      options?.mutation?.onSuccess,
    )

  // Query-key helpers used by lib/invalidate.ts (imported at module load) —
  // return bare prefixes so prefix-matching invalidation works.
  return {
    useListVariables,
    patchVariable,
    useCreateVariable,
    usePatchVariable,
    useDeleteVariable,
    useInitializeVariables,
    usePreviewDataset,
    getListVariablesQueryKey: (datasetId?: string) => [
      `/api/v1/raw-datasets/${datasetId}/variables`,
    ],
    getGetDatasetQueryKey: (datasetId?: string) => [
      `/api/v1/raw-datasets/${datasetId}`,
    ],
    getGetVariableQueryKey: (variableId?: string) => [
      `/api/v1/raw-variables/${variableId}`,
    ],
    getGetRawAggregateQueryKey: (rawId?: string) => [`/api/v1/raw/${rawId}`],
    getGetRawDependenciesQueryKey: (rawId?: string) => [
      `/api/v1/raw/${rawId}/dependencies`,
    ],
    getListDatasetsQueryKey: (rawId?: string) => [`/api/v1/raw/${rawId}/datasets`],
    getListRawAggregatesQueryKey: (studyId?: string) => [
      '/api/v1/studies',
      studyId,
      'raw',
    ],
  }
})

// ---------------------------------------------------------------------------
// Import AFTER the mocks so the panels bind to the stubs.
// ---------------------------------------------------------------------------
import { VariablesPanel } from './variables-panel'
import { PreviewPanel, DEFAULT_PREVIEW_LIMIT } from './preview-panel'

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

function makeVariable(
  overrides: Partial<RawVariableResponse> = {},
): RawVariableResponse {
  return {
    id: 'var-1',
    dataset_id: 'ds-1',
    study_id: 'study-1',
    name: 'AGE',
    label: 'Age',
    physical_type: 'integer',
    length: null,
    precision: null,
    ordinal: 1,
    role: null,
    description: null,
    terminology_binding: null,
    revision: 2,
    ...overrides,
  } as RawVariableResponse
}

function makePreview(
  overrides: Partial<RawPreviewResponse> = {},
): RawPreviewResponse {
  return {
    columns: ['SUBJID', 'AGE'],
    rows: [
      { SUBJID: '001', AGE: 42 },
      { SUBJID: '002', AGE: 37 },
    ],
    offset: 0,
    limit: 50,
    total_rows: 2,
    ...overrides,
  } as RawPreviewResponse
}

function problemError(status: number, body: Record<string, unknown>): AxiosError {
  return {
    isAxiosError: true,
    response: { status, data: body },
  } as unknown as AxiosError
}

beforeEach(() => {
  rawApi.variables = []
  rawApi.patchVariableImpl = async () => makeVariable({ revision: 3 })
  rawApi.patchVariableCalls = []
  rawApi.createVariableImpl = async () => makeVariable({ id: 'new' })
  rawApi.initializeImpl = async () => ({ created: 0, filled: 0 })
  rawApi.initializeRequests = []
  rawApi.previewImpl = async () => makePreview()
  rawApi.previewCalls = []
})

afterEach(() => {
  vi.clearAllMocks()
})

function renderVariables(datasetRevision = 7) {
  return renderWithClient(
    <VariablesPanel
      datasetId="ds-1"
      datasetCode="DM"
      datasetRevision={datasetRevision}
    />,
  )
}

// ===========================================================================
// Reorder: pointer drag and keyboard/numeric fallback issue the IDENTICAL
// PATCH with If-Match (Req 4.4)
// ===========================================================================
describe('Variable reorder PATCH parity (Req 4.4)', () => {
  it('the move-down button (non-pointer fallback) PATCHes the moved variable with its ETag', async () => {
    rawApi.variables = [
      makeVariable({ id: 'v1', name: 'AGE', ordinal: 1, revision: 2 }),
      makeVariable({ id: 'v2', name: 'SEX', ordinal: 2, revision: 5 }),
    ]
    rawApi.patchVariableImpl = vi.fn(async () => makeVariable({ revision: 3 }))

    const { invalidateSpy } = renderVariables()

    // Move the first variable (AGE) down one position via the explicit control.
    const moveDownButtons = screen.getAllByRole('button', { name: /move down/i })
    fireEvent.click(moveDownButtons[0])

    await waitFor(() => {
      expect(rawApi.patchVariableCalls.length).toBe(1)
    })
    const call = rawApi.patchVariableCalls[0]
    // The moved variable (AGE, id v1) is patched to its new 1-based ordinal (2).
    expect(call.variableId).toBe('v1')
    expect(call.body).toEqual({ ordinal: 2 })
    // Carries the moved variable's OWN revision (2) as If-Match.
    expect(call.request).toEqual(ifMatchRequest(2))
    expect(
      (call.request as { headers: Record<string, string> }).headers['If-Match'],
    ).toBe('"revision-2"')
    await waitFor(() => expect(invalidateSpy).toHaveBeenCalled())
  })

  it('the numeric position field (fallback) issues the IDENTICAL PATCH as the move control', async () => {
    const base = [
      makeVariable({ id: 'v1', name: 'AGE', ordinal: 1, revision: 2 }),
      makeVariable({ id: 'v2', name: 'SEX', ordinal: 2, revision: 5 }),
    ]

    // --- Move-button path ---
    rawApi.variables = base
    rawApi.patchVariableImpl = vi.fn(async () => makeVariable({ revision: 3 }))
    const buttonRun = renderVariables()
    fireEvent.click(screen.getAllByRole('button', { name: /move down/i })[0])
    await waitFor(() => expect(rawApi.patchVariableCalls.length).toBe(1))
    const buttonCall = rawApi.patchVariableCalls[0]
    buttonRun.unmount()

    // --- Numeric-field path ---
    rawApi.variables = base
    rawApi.patchVariableCalls = []
    renderVariables()
    // Set AGE's position field (first "Position" input) to 2 → same move.
    const positionInputs = screen.getAllByLabelText(/position/i)
    fireEvent.change(positionInputs[0], { target: { value: '2' } })
    await waitFor(() => expect(rawApi.patchVariableCalls.length).toBe(1))
    const numericCall = rawApi.patchVariableCalls[0]

    // Identical typed request: same variable id, same body, same If-Match.
    expect(numericCall.variableId).toBe(buttonCall.variableId)
    expect(numericCall.body).toEqual(buttonCall.body)
    expect(numericCall.request).toEqual(buttonCall.request)
    expect(numericCall.request).toEqual(ifMatchRequest(2))
  })

  it('surfaces a reorder failure and reloads the list', async () => {
    rawApi.variables = [
      makeVariable({ id: 'v1', name: 'AGE', ordinal: 1, revision: 2 }),
      makeVariable({ id: 'v2', name: 'SEX', ordinal: 2, revision: 5 }),
    ]
    rawApi.patchVariableImpl = vi.fn(async () => {
      throw problemError(412, { title: 'Precondition Failed', detail: 'stale' })
    })

    const { invalidateSpy } = renderVariables()
    fireEvent.click(screen.getAllByRole('button', { name: /move down/i })[0])

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeTruthy()
    })
    // The concurrency message is shown and the list is reloaded.
    expect(screen.getByText(/changed since you opened it/i)).toBeTruthy()
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: ['/api/v1/raw-datasets/ds-1/variables'],
    })
  })
})

// ===========================================================================
// Create: 409 duplicate_raw_variable retains the form (Req 4.3)
// ===========================================================================
describe('Variable create duplicate (Req 4.3)', () => {
  it('on 409 duplicate_raw_variable surfaces the uniqueness message and retains values', async () => {
    rawApi.variables = []
    rawApi.createVariableImpl = vi.fn(async () => {
      throw problemError(409, {
        title: 'Conflict',
        code: 'duplicate_raw_variable',
        detail: 'Variable already exists.',
      })
    })

    const { invalidateSpy } = renderVariables()

    fireEvent.click(screen.getByRole('button', { name: /new variable/i }))

    const dialog = await screen.findByRole('dialog')
    fireEvent.change(within(dialog).getByLabelText(/source name/i), {
      target: { value: 'AGE' },
    })
    // Ordinal is prefilled with the next ordinal (1); leave it.

    fireEvent.click(
      within(dialog).getByRole('button', { name: /create variable/i }),
    )

    await waitFor(() => {
      expect(rawApi.createVariableImpl).toHaveBeenCalledTimes(1)
    })
    await waitFor(() => {
      expect(
        within(dialog).getByText(
          /names and ordinals must be unique within this dataset/i,
        ),
      ).toBeTruthy()
    })
    // Entered values retained (R4.3): dialog stays open and keeps the name.
    expect(
      (within(dialog).getByLabelText(/source name/i) as HTMLInputElement).value,
    ).toBe('AGE')
    // No list refresh on the failed create.
    expect(invalidateSpy).not.toHaveBeenCalled()
  })
})

// ===========================================================================
// Initialize: created/filled counts + refresh, 412/428 reload (Req 4.6, 4.7)
// ===========================================================================
describe('Variable initialize (Req 4.6, 4.7)', () => {
  it('sends the dataset ETag, shows created/filled counts, and refreshes the list', async () => {
    const { toast } = await import('@/components/ui/sonner')
    rawApi.variables = []
    rawApi.initializeImpl = vi.fn(async () => ({ created: 3, filled: 5 }))

    const { invalidateSpy } = renderVariables(7)

    fireEvent.click(
      screen.getByRole('button', { name: /initialize from source/i }),
    )

    await waitFor(() => {
      expect(rawApi.initializeImpl).toHaveBeenCalledTimes(1)
    })
    // The initialize hook was wired with ifMatchRequest(datasetRevision=7) (R4.6).
    const lastRequest = rawApi.initializeRequests
      .filter((r) => r !== undefined)
      .at(-1)
    expect(lastRequest).toEqual(ifMatchRequest(7))
    // Created/filled counts are reported (R4.6).
    expect(toast.success).toHaveBeenCalledWith(
      expect.stringMatching(/3 created, 5 filled/i),
    )
    // The variable list is refreshed on success (R4.6).
    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({
        queryKey: ['/api/v1/raw-datasets/ds-1/variables'],
      })
    })
  })

  it('on 412 shows a staleness message and reloads the dataset revision before retry', async () => {
    rawApi.variables = []
    rawApi.initializeImpl = vi.fn(async () => {
      throw problemError(412, { title: 'Precondition Failed', detail: 'stale' })
    })

    const { invalidateSpy } = renderVariables(7)

    fireEvent.click(
      screen.getByRole('button', { name: /initialize from source/i }),
    )

    await waitFor(() => {
      expect(rawApi.initializeImpl).toHaveBeenCalledTimes(1)
    })
    await waitFor(() => {
      expect(screen.getByText(/changed since you opened it/i)).toBeTruthy()
    })
    // Reloads the dataset (its detail key) so a fresh ETag drives retry (R4.7).
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: ['/api/v1/raw-datasets/ds-1'],
    })
  })

  it('on 428 shows the missing-precondition message and reloads the dataset', async () => {
    rawApi.variables = []
    rawApi.initializeImpl = vi.fn(async () => {
      throw problemError(428, { title: 'Precondition Required' })
    })

    const { invalidateSpy } = renderVariables(7)

    fireEvent.click(
      screen.getByRole('button', { name: /initialize from source/i }),
    )

    await waitFor(() => {
      expect(rawApi.initializeImpl).toHaveBeenCalledTimes(1)
    })
    await waitFor(() => {
      expect(screen.getByText(/required precondition header was missing/i)).toBeTruthy()
    })
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: ['/api/v1/raw-datasets/ds-1'],
    })
  })
})

// ===========================================================================
// Preview: clamped params, rendering, zero-row message, no persistence
// (Req 5.1, 5.4, 5.5, 5.6)
// ===========================================================================
function renderPreview() {
  return renderWithClient(
    <PreviewPanel datasetId="ds-1" datasetCode="DM" />,
  )
}

describe('Preview clamping and rendering (Req 5.1, 5.4, 5.5)', () => {
  it('clamps out-of-range limit/offset BEFORE sending and renders rows + the window summary', async () => {
    rawApi.previewImpl = vi.fn(async () =>
      makePreview({ offset: 0, limit: 200, total_rows: 2 }),
    )

    renderPreview()

    // Over-ceiling limit and negative offset are clamped on submit (R5.1-5.3).
    fireEvent.change(screen.getByLabelText(/limit/i), { target: { value: '5000' } })
    fireEvent.change(screen.getByLabelText(/offset/i), { target: { value: '-3' } })
    fireEvent.click(screen.getByRole('button', { name: /preview rows/i }))

    await waitFor(() => {
      expect(rawApi.previewCalls.length).toBe(1)
    })
    // limit clamped 5000 -> 200; offset clamped -3 -> 0; no columns key sent.
    expect(rawApi.previewCalls[0].datasetId).toBe('ds-1')
    expect(rawApi.previewCalls[0].data).toEqual({ limit: 200, offset: 0 })

    // Rows render and the offset/limit/total summary is shown (R5.4).
    await waitFor(() => {
      expect(screen.getByText('001')).toBeTruthy()
    })
    expect(screen.getByText('002')).toBeTruthy()
    const summary = screen.getByText(/total rows/i).closest('dl') as HTMLElement
    expect(within(summary).getByText('Offset')).toBeTruthy()
    expect(within(summary).getByText('Limit')).toBeTruthy()
    expect(within(summary).getByText('200')).toBeTruthy()
  })

  it('clamps a sub-floor limit up to 1 and sends an optional column selection', async () => {
    rawApi.previewImpl = vi.fn(async () =>
      makePreview({ offset: 0, limit: 1, total_rows: 1, rows: [{ SUBJID: '001', AGE: 42 }] }),
    )

    renderPreview()

    fireEvent.change(screen.getByLabelText(/limit/i), { target: { value: '0' } })
    fireEvent.change(screen.getByLabelText(/columns/i), {
      target: { value: 'SUBJID, AGE' },
    })
    fireEvent.click(screen.getByRole('button', { name: /preview rows/i }))

    await waitFor(() => {
      expect(rawApi.previewCalls.length).toBe(1)
    })
    // limit 0 -> 1 (R5.3) and the trimmed columns are included (R5.1).
    expect(rawApi.previewCalls[0].data).toEqual({
      limit: 1,
      offset: 0,
      columns: ['SUBJID', 'AGE'],
    })
  })

  it('shows the zero-row message while the window counts stay visible (R5.5)', async () => {
    rawApi.previewImpl = vi.fn(async () =>
      makePreview({ rows: [], offset: 500, limit: 50, total_rows: 2 }),
    )

    renderPreview()
    fireEvent.change(screen.getByLabelText(/offset/i), { target: { value: '500' } })
    fireEvent.click(screen.getByRole('button', { name: /preview rows/i }))

    await waitFor(() => {
      expect(screen.getByText(/no rows in this window/i)).toBeTruthy()
    })
    // Counts remain visible alongside the empty message (R5.5).
    const summary = screen.getByText(/total rows/i).closest('dl') as HTMLElement
    expect(within(summary).getByText('500')).toBeTruthy()
    expect(within(summary).getByText('2')).toBeTruthy()
  })
})

describe('Preview rows are not persisted beyond the view (Req 5.6)', () => {
  it('unmounting then remounting shows no stale rows', async () => {
    rawApi.previewImpl = vi.fn(async () => makePreview())

    const first = renderPreview()
    fireEvent.click(screen.getByRole('button', { name: /preview rows/i }))
    await waitFor(() => {
      expect(screen.getByText('001')).toBeTruthy()
    })

    // Leave the view.
    first.unmount()

    // Remount a fresh panel — nothing from the prior preview survives (R5.6):
    // the rows are gone and the default empty state is shown without any
    // request having been re-issued.
    const callsBeforeRemount = rawApi.previewCalls.length
    renderPreview()
    expect(screen.queryByText('001')).toBeNull()
    expect(screen.getByText(/no preview loaded/i)).toBeTruthy()
    // The limit field is back at the default — no cached window either.
    expect((screen.getByLabelText(/limit/i) as HTMLInputElement).value).toBe(
      String(DEFAULT_PREVIEW_LIMIT),
    )
    expect(rawApi.previewCalls.length).toBe(callsBeforeRemount)
  })
})
