// @vitest-environment jsdom
//
// Component tests for the Raw workbench Datasets panel (`datasets-panel.tsx`)
// — task 6.2.
//
// Coverage (Requirements 3.2, 3.3, 3.5, 3.6, 3.7, 3.8):
//   * a DROPPED file and a BROWSED file issue the IDENTICAL multipart
//     `POST /studies/{study_id}/source-files` (R3.2) and surface the SAME
//     413/415 handling while retaining the dataset form (R3.3);
//   * a 409 `duplicate_raw_dataset_code` retains the create form (R3.5);
//   * rebind (R3.6) and retire (R3.7) send the dataset ETag as `If-Match` and
//     surface the 412 reload path (R3.8);
//   * retire requires a confirmation that names the dataset (R3.7).
//   * initialize-all coordinates every dataset's existing source initializer,
//     preserves each If-Match revision, refreshes affected queries, and reports
//     partial failures without skipping later datasets.
//
// Like the Raw screens tests, the repo mocks the generated Orval hooks + study
// provider + toast rather than running a network layer (no MSW is installed),
// so these tests drive the REAL `DatasetsPanel` over faithful hook fakes and
// assert the exact body/params/headers the component funnels through the
// mutation `request` option and `useCreateSourceFile`.
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
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
  RawDatasetResponse,
  RawInitializeResponse,
  SourceFileResponse,
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
interface CreateSourceFileVars {
  studyId: string
  data: { file: unknown }
}

const rawApi: {
  datasets: RawDatasetResponse[]
  createDatasetImpl: (vars: { rawId: string; data: unknown }) => Promise<unknown>
  createDatasetRequests: unknown[]
  patchDatasetImpl: (vars: { datasetId: string; data: unknown }) => Promise<unknown>
  patchDatasetRequests: unknown[]
  retireDatasetImpl: (vars: { datasetId: string }) => Promise<unknown>
  retireDatasetRequests: unknown[]
  initializeVariablesImpl: (
    datasetId: string,
    request?: unknown,
  ) => Promise<RawInitializeResponse>
  initializeVariablesCalls: { datasetId: string; request?: unknown }[]
} = {
  datasets: [],
  createDatasetImpl: async () => ({}),
  createDatasetRequests: [],
  patchDatasetImpl: async () => ({}),
  patchDatasetRequests: [],
  retireDatasetImpl: async () => ({}),
  retireDatasetRequests: [],
  initializeVariablesImpl: async () =>
    ({ created: 0, filled: 0 }) as RawInitializeResponse,
  initializeVariablesCalls: [],
}

const sourceFileApi: {
  createImpl: (vars: CreateSourceFileVars) => Promise<unknown>
  calls: CreateSourceFileVars[]
} = {
  createImpl: async () => ({}),
  calls: [],
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
  const initializeVariables = (datasetId: string, request?: unknown) => {
    rawApi.initializeVariablesCalls.push({ datasetId, request })
    return rawApi.initializeVariablesImpl(datasetId, request)
  }

  const useListDatasets = (_rawId: string) => ({
    data: rawApi.datasets,
    isLoading: false,
    isFetching: false,
    isError: false,
    error: null,
  })

  const useCreateDataset = (options?: {
    mutation?: { onSuccess?: (data: unknown) => void }
    request?: unknown
  }) => {
    rawApi.createDatasetRequests.push(options?.request)
    return makeMutationResult(
      (vars: { rawId: string; data: unknown }) => rawApi.createDatasetImpl(vars),
      options?.mutation?.onSuccess,
    )
  }

  const usePatchDataset = (options?: {
    mutation?: { onSuccess?: (data: unknown) => void }
    request?: unknown
  }) => {
    rawApi.patchDatasetRequests.push(options?.request)
    return makeMutationResult(
      (vars: { datasetId: string; data: unknown }) =>
        rawApi.patchDatasetImpl(vars),
      options?.mutation?.onSuccess,
    )
  }

  const useRetireDataset = (options?: {
    mutation?: { onSuccess?: (data: unknown) => void }
    request?: unknown
  }) => {
    rawApi.retireDatasetRequests.push(options?.request)
    return makeMutationResult(
      (vars: { datasetId: string }) => rawApi.retireDatasetImpl(vars),
      options?.mutation?.onSuccess,
    )
  }

  // Query-key helpers used by lib/invalidate.ts (imported at module load) —
  // return bare prefixes so prefix-matching invalidation works.
  return {
    initializeVariables,
    useListDatasets,
    useCreateDataset,
    usePatchDataset,
    useRetireDataset,
    getListDatasetsQueryKey: (rawId?: string) => [`/api/v1/raw/${rawId}/datasets`],
    getGetDatasetQueryKey: (datasetId?: string) => [
      `/api/v1/raw-datasets/${datasetId}`,
    ],
    getGetRawAggregateQueryKey: (rawId?: string) => [`/api/v1/raw/${rawId}`],
    getGetRawDependenciesQueryKey: (rawId?: string) => [
      `/api/v1/raw/${rawId}/dependencies`,
    ],
    getGetVariableQueryKey: (variableId?: string) => [
      `/api/v1/raw-variables/${variableId}`,
    ],
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

vi.mock('@/api/generated/artifacts/artifacts', () => {
  const useCreateSourceFile = (options?: {
    mutation?: { onSuccess?: (data: unknown) => void }
    request?: unknown
  }) =>
    makeMutationResult(
      (vars: CreateSourceFileVars) => {
        sourceFileApi.calls.push(vars)
        return sourceFileApi.createImpl(vars)
      },
      options?.mutation?.onSuccess,
    )

  return {
    useCreateSourceFile,
    getListArtifactsQueryKey: (studyId?: string) => ['/api/v1/artifacts', studyId],
  }
})

// Stub out the child drill-in panels so this file tests only the Datasets
// panel's own flows (the Variables/Preview panels have their own tests and pull
// in dnd-kit / preview queries we don't exercise here). The bulk-import dialog
// is likewise stubbed — it has its own `-raw-bulk-import.test.tsx` and consumes
// the bulk source-file/import hooks that this file's mocks intentionally omit.
vi.mock('@/components/workbench/raw-bulk-import-dialog', () => ({
  RawBulkImportDialog: () => <div data-testid="raw-bulk-import-dialog" />,
}))
vi.mock('@/components/workbench/variables-panel', () => ({
  VariablesPanel: () => <div data-testid="variables-panel" />,
}))
vi.mock('@/components/workbench/preview-panel', () => ({
  PreviewPanel: () => <div data-testid="preview-panel" />,
}))

// ---------------------------------------------------------------------------
// Import AFTER the mocks so the panel binds to the stubs.
// ---------------------------------------------------------------------------
import { DatasetsPanel } from './datasets-panel'

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

function makeDataset(
  overrides: Partial<RawDatasetResponse> = {},
): RawDatasetResponse {
  return {
    id: 'ds-1',
    raw_id: 'raw-1',
    code: 'DM',
    label: 'Demographics',
    description: null,
    current_source_file_id: 'sf-0',
    status: 'active',
    revision: 4,
    ...overrides,
  } as RawDatasetResponse
}

function makeSourceFile(
  overrides: Partial<SourceFileResponse> = {},
): SourceFileResponse {
  return {
    id: 'sf-1',
    study_id: 'study-1',
    filename: 'dm.xpt',
    media_type: 'application/x-sas-xport',
    ...overrides,
  } as SourceFileResponse
}

function problemError(status: number, body: Record<string, unknown>): AxiosError {
  return {
    isAxiosError: true,
    response: { status, data: body },
  } as unknown as AxiosError
}

/** Build a File for drop/browse paths. */
function makeFile(name = 'dm.xpt'): File {
  return new File(['raw-bytes'], name, {
    type: 'application/x-sas-xport',
  })
}

beforeEach(() => {
  rawApi.datasets = []
  rawApi.createDatasetImpl = async () => makeDataset({ id: 'new' })
  rawApi.createDatasetRequests = []
  rawApi.patchDatasetImpl = async () => makeDataset({ revision: 5 })
  rawApi.patchDatasetRequests = []
  rawApi.retireDatasetImpl = async () => ({})
  rawApi.retireDatasetRequests = []
  rawApi.initializeVariablesImpl = async () =>
    ({ created: 0, filled: 0 }) as RawInitializeResponse
  rawApi.initializeVariablesCalls = []
  sourceFileApi.createImpl = async () => makeSourceFile()
  sourceFileApi.calls = []
})

afterEach(() => {
  vi.clearAllMocks()
})

// ===========================================================================
// Initialize all datasets from their bound sources
// ===========================================================================
describe('Initialize all datasets', () => {
  it('is disabled when the workbench has no datasets', () => {
    renderWithClient(<DatasetsPanel rawId="raw-1" studyId="study-1" />)

    expect(
      (
        screen.getByRole('button', {
          name: /initialize all from source/i,
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true)
  })

  it('initializes every dataset with its own revision and refreshes its data', async () => {
    rawApi.datasets = [
      makeDataset({ id: 'ds-dm', code: 'DM', revision: 4 }),
      makeDataset({ id: 'ds-ae', code: 'AE', revision: 7 }),
    ]
    rawApi.initializeVariablesImpl = vi.fn(async (datasetId: string) =>
      datasetId === 'ds-ae'
        ? ({ created: 3, filled: 1 } as RawInitializeResponse)
        : ({ created: 2, filled: 0 } as RawInitializeResponse),
    )
    const { toast } = await import('@/components/ui/sonner')
    const { invalidateSpy } = renderWithClient(
      <DatasetsPanel rawId="raw-1" studyId="study-1" />,
    )

    fireEvent.click(
      screen.getByRole('button', { name: /initialize all from source/i }),
    )

    await waitFor(() => {
      expect(rawApi.initializeVariablesCalls).toHaveLength(2)
    })
    // The panel sorts by code, and the bulk action follows that stable order.
    expect(rawApi.initializeVariablesCalls).toEqual([
      { datasetId: 'ds-ae', request: ifMatchRequest(7) },
      { datasetId: 'ds-dm', request: ifMatchRequest(4) },
    ])
    await waitFor(() => {
      expect(toast.success).toHaveBeenCalledWith(
        'Initialized 2 datasets: 5 variables created, 1 field filled.',
      )
    })
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: ['/api/v1/raw-datasets/ds-ae/variables'],
    })
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: ['/api/v1/raw-datasets/ds-dm/variables'],
    })
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: ['/api/v1/raw/raw-1/datasets'],
    })
  })

  it('continues after a failure and reports the failed dataset codes', async () => {
    rawApi.datasets = [
      makeDataset({ id: 'ds-ae', code: 'AE', revision: 2 }),
      makeDataset({ id: 'ds-dm', code: 'DM', revision: 4 }),
      makeDataset({ id: 'ds-lb', code: 'LB', revision: 6 }),
    ]
    rawApi.initializeVariablesImpl = vi.fn(async (datasetId: string) => {
      if (datasetId === 'ds-dm') {
        throw problemError(422, {
          title: 'Unprocessable Content',
          detail: 'Source inspection failed.',
        })
      }
      return { created: 1, filled: 0 } as RawInitializeResponse
    })
    const { toast } = await import('@/components/ui/sonner')
    renderWithClient(<DatasetsPanel rawId="raw-1" studyId="study-1" />)

    fireEvent.click(
      screen.getByRole('button', { name: /initialize all from source/i }),
    )

    await waitFor(() => {
      expect(rawApi.initializeVariablesCalls).toHaveLength(3)
    })
    expect(rawApi.initializeVariablesCalls.map((call) => call.datasetId)).toEqual(
      ['ds-ae', 'ds-dm', 'ds-lb'],
    )
    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith(
        'Initialized 2 of 3 datasets. Failed: DM. 2 variables created, 0 fields filled.',
      )
    })
  })
})

// Open the create dialog and return the dropzone's hidden file input.
function openCreateDialog(): HTMLInputElement {
  fireEvent.click(screen.getByRole('button', { name: /new dataset/i }))
  return screen.getByTestId('file-dropzone-input') as HTMLInputElement
}

// ===========================================================================
// Drop vs browse parity + 413/415 handling (Req 3.2, 3.3)
// ===========================================================================
describe('Source-file upload: drop vs browse parity (Req 3.2)', () => {
  it('a browsed file issues the multipart POST with the study id and file', async () => {
    sourceFileApi.createImpl = vi.fn(async () => makeSourceFile())

    renderWithClient(<DatasetsPanel rawId="raw-1" studyId="study-1" />)
    const input = openCreateDialog()

    const file = makeFile()
    fireEvent.change(input, { target: { files: [file] } })

    await waitFor(() => {
      expect(sourceFileApi.calls.length).toBe(1)
    })
    expect(sourceFileApi.calls[0].studyId).toBe('study-1')
    expect(sourceFileApi.calls[0].data.file).toBe(file)
  })

  it('a dropped file issues the IDENTICAL multipart POST as the browse path', async () => {
    const browseCalls: CreateSourceFileVars[] = []
    const dropCalls: CreateSourceFileVars[] = []

    // --- Browse path ---
    sourceFileApi.createImpl = vi.fn(async () => makeSourceFile())
    const browse = renderWithClient(
      <DatasetsPanel rawId="raw-1" studyId="study-1" />,
    )
    const input = openCreateDialog()
    const browsedFile = makeFile('dm.xpt')
    fireEvent.change(input, { target: { files: [browsedFile] } })
    await waitFor(() => expect(sourceFileApi.calls.length).toBe(1))
    browseCalls.push(...sourceFileApi.calls)
    browse.unmount()

    // --- Drop path ---
    sourceFileApi.calls = []
    const drop = renderWithClient(
      <DatasetsPanel rawId="raw-1" studyId="study-1" />,
    )
    fireEvent.click(screen.getByRole('button', { name: /new dataset/i }))
    const dropzone = screen.getByLabelText(/source file upload drop target/i)
    const droppedFile = makeFile('dm.xpt')
    const dataTransfer = new DataTransfer()
    dataTransfer.items.add(droppedFile)
    fireEvent.drop(dropzone, { dataTransfer })
    await waitFor(() => expect(sourceFileApi.calls.length).toBe(1))
    dropCalls.push(...sourceFileApi.calls)
    drop.unmount()

    // Identical request shape: same study id and the same single-file payload
    // key — the drop and browse routes funnel through the same multipart POST.
    expect(dropCalls[0].studyId).toBe(browseCalls[0].studyId)
    expect(dropCalls[0].data.file).toBe(droppedFile)
    expect(browseCalls[0].data.file).toBe(browsedFile)
    expect(Object.keys(dropCalls[0].data)).toEqual(
      Object.keys(browseCalls[0].data),
    )
  })

  it('surfaces a 413 size message on the browse path and retains the dataset form', async () => {
    sourceFileApi.createImpl = async () => {
      throw problemError(413, { title: 'Payload Too Large' })
    }

    renderWithClient(<DatasetsPanel rawId="raw-1" studyId="study-1" />)
    const input = openCreateDialog()

    // Enter dataset form values first; they must survive the upload failure.
    fireEvent.change(screen.getByLabelText(/code/i), { target: { value: 'DM' } })
    fireEvent.change(screen.getByLabelText(/label/i), {
      target: { value: 'Demographics' },
    })

    fireEvent.change(input, { target: { files: [makeFile()] } })

    await waitFor(() => {
      expect(screen.getByText(/exceeds the accepted size limit/i)).toBeTruthy()
    })
    // The dataset form fields are retained (R3.3).
    expect((screen.getByLabelText(/code/i) as HTMLInputElement).value).toBe('DM')
    expect((screen.getByLabelText(/label/i) as HTMLInputElement).value).toBe(
      'Demographics',
    )
  })

  it('surfaces a 415 media-type message on the drop path and retains the dataset form', async () => {
    sourceFileApi.createImpl = async () => {
      throw problemError(415, { title: 'Unsupported Media Type' })
    }

    renderWithClient(<DatasetsPanel rawId="raw-1" studyId="study-1" />)
    fireEvent.click(screen.getByRole('button', { name: /new dataset/i }))

    fireEvent.change(screen.getByLabelText(/code/i), { target: { value: 'AE' } })
    fireEvent.change(screen.getByLabelText(/label/i), {
      target: { value: 'Adverse Events' },
    })

    const dropzone = screen.getByLabelText(/source file upload drop target/i)
    const dataTransfer = new DataTransfer()
    dataTransfer.items.add(makeFile('ae.csv'))
    fireEvent.drop(dropzone, { dataTransfer })

    await waitFor(() => {
      expect(screen.getByText(/unsupported media type/i)).toBeTruthy()
    })
    // The dataset form fields are retained on the drop path too (R3.3).
    expect((screen.getByLabelText(/code/i) as HTMLInputElement).value).toBe('AE')
    expect((screen.getByLabelText(/label/i) as HTMLInputElement).value).toBe(
      'Adverse Events',
    )
  })
})

// ===========================================================================
// Create: 409 duplicate code retains form (Req 3.5)
// ===========================================================================
describe('Dataset create duplicate code (Req 3.5)', () => {
  it('on 409 duplicate_raw_dataset_code retains the entered values', async () => {
    sourceFileApi.createImpl = async () => makeSourceFile()
    rawApi.createDatasetImpl = vi.fn(async () => {
      throw problemError(409, {
        title: 'Conflict',
        code: 'duplicate_raw_dataset_code',
        detail: 'Dataset code already exists.',
      })
    })

    const { invalidateSpy } = renderWithClient(
      <DatasetsPanel rawId="raw-1" studyId="study-1" />,
    )
    const input = openCreateDialog()

    fireEvent.change(screen.getByLabelText(/code/i), { target: { value: 'DM' } })
    fireEvent.change(screen.getByLabelText(/label/i), {
      target: { value: 'Demographics' },
    })
    // Upload a source file so the create submit is enabled.
    fireEvent.change(input, { target: { files: [makeFile()] } })
    await waitFor(() => {
      expect(screen.getByText(/dm\.xpt/i)).toBeTruthy()
    })

    fireEvent.click(screen.getByRole('button', { name: /create dataset/i }))

    await waitFor(() => {
      expect(rawApi.createDatasetImpl).toHaveBeenCalledTimes(1)
    })
    // Uniqueness message is surfaced and the entered values are retained (R3.5).
    await waitFor(() => {
      expect(
        screen.getByText(/codes must be unique within this workbench/i),
      ).toBeTruthy()
    })
    expect((screen.getByLabelText(/code/i) as HTMLInputElement).value).toBe('DM')
    expect((screen.getByLabelText(/label/i) as HTMLInputElement).value).toBe(
      'Demographics',
    )
    // No list refresh on the failed create.
    expect(invalidateSpy).not.toHaveBeenCalled()
  })
})

// ===========================================================================
// Rebind: If-Match + 412 reload (Req 3.6, 3.8)
// ===========================================================================
describe('Dataset rebind (Req 3.6, 3.8)', () => {
  it('sends the dataset ETag as If-Match on a successful rebind', async () => {
    rawApi.datasets = [makeDataset({ id: 'ds-1', code: 'DM', revision: 4 })]
    sourceFileApi.createImpl = async () => makeSourceFile({ id: 'sf-9' })
    rawApi.patchDatasetImpl = vi.fn(async () => makeDataset({ revision: 5 }))

    const { invalidateSpy } = renderWithClient(
      <DatasetsPanel rawId="raw-1" studyId="study-1" />,
    )

    fireEvent.click(screen.getByRole('button', { name: /rebind/i }))
    // Upload a corrected source file inside the rebind dialog.
    const input = screen.getByTestId('file-dropzone-input') as HTMLInputElement
    fireEvent.change(input, { target: { files: [makeFile()] } })
    await waitFor(() => expect(sourceFileApi.calls.length).toBe(1))

    fireEvent.click(screen.getByRole('button', { name: /rebind dataset/i }))

    await waitFor(() => {
      expect(rawApi.patchDatasetImpl).toHaveBeenCalledTimes(1)
    })
    // The patch hook was wired with ifMatchRequest(revision=4) (R3.6). The hook
    // re-renders with `undefined` once the dialog closes, so assert against the
    // last DEFINED request config (the one present while the dialog was open).
    const lastRequest = rawApi.patchDatasetRequests
      .filter((r) => r !== undefined)
      .at(-1)
    expect(lastRequest).toEqual(ifMatchRequest(4))
    expect(
      (lastRequest as { headers: Record<string, string> }).headers['If-Match'],
    ).toBe('"revision-4"')
    expect(
      (rawApi.patchDatasetImpl as ReturnType<typeof vi.fn>).mock.calls[0][0],
    ).toMatchObject({ datasetId: 'ds-1', data: { source_file_id: 'sf-9' } })
    // Success invalidates the dataset collection + detail.
    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalled()
    })
  })

  it('on 412 shows the concurrency message and reloads the current revision', async () => {
    rawApi.datasets = [makeDataset({ id: 'ds-1', code: 'DM', revision: 4 })]
    sourceFileApi.createImpl = async () => makeSourceFile({ id: 'sf-9' })
    rawApi.patchDatasetImpl = vi.fn(async () => {
      throw problemError(412, { title: 'Precondition Failed', detail: 'stale' })
    })

    const { invalidateSpy } = renderWithClient(
      <DatasetsPanel rawId="raw-1" studyId="study-1" />,
    )

    fireEvent.click(screen.getByRole('button', { name: /rebind/i }))
    const input = screen.getByTestId('file-dropzone-input') as HTMLInputElement
    fireEvent.change(input, { target: { files: [makeFile()] } })
    await waitFor(() => expect(sourceFileApi.calls.length).toBe(1))

    fireEvent.click(screen.getByRole('button', { name: /rebind dataset/i }))

    await waitFor(() => {
      expect(rawApi.patchDatasetImpl).toHaveBeenCalledTimes(1)
    })
    // Concurrency message surfaced…
    await waitFor(() => {
      expect(screen.getByText(/changed since you opened it/i)).toBeTruthy()
    })
    // …and the current dataset revision is reloaded before any retry (R3.8):
    // the dataset detail key is invalidated.
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: ['/api/v1/raw-datasets/ds-1'],
    })
  })
})

// ===========================================================================
// Retire: confirmation naming the dataset + If-Match + 412 reload
// (Req 3.7, 3.8)
// ===========================================================================
describe('Dataset retire (Req 3.7, 3.8)', () => {
  it('requires a confirmation that names the dataset before deleting', async () => {
    rawApi.datasets = [
      makeDataset({ id: 'ds-1', code: 'DM', label: 'Demographics', revision: 4 }),
    ]
    rawApi.retireDatasetImpl = vi.fn(async () => ({}))

    renderWithClient(<DatasetsPanel rawId="raw-1" studyId="study-1" />)

    fireEvent.click(screen.getByRole('button', { name: /retire/i }))

    // A confirmation dialog appears and names the dataset by its code (R3.7).
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText('DM')).toBeTruthy()
    // No delete has been issued until the user confirms.
    expect(rawApi.retireDatasetImpl).not.toHaveBeenCalled()

    fireEvent.click(
      within(dialog).getByRole('button', { name: /retire dataset/i }),
    )

    await waitFor(() => {
      expect(rawApi.retireDatasetImpl).toHaveBeenCalledTimes(1)
    })
    expect(
      (rawApi.retireDatasetImpl as ReturnType<typeof vi.fn>).mock.calls[0][0],
    ).toMatchObject({ datasetId: 'ds-1' })
  })

  it('sends the dataset ETag as If-Match on retire', async () => {
    rawApi.datasets = [makeDataset({ id: 'ds-1', code: 'DM', revision: 4 })]
    rawApi.retireDatasetImpl = vi.fn(async () => ({}))

    renderWithClient(<DatasetsPanel rawId="raw-1" studyId="study-1" />)

    fireEvent.click(screen.getByRole('button', { name: /retire/i }))
    const dialog = await screen.findByRole('dialog')
    fireEvent.click(
      within(dialog).getByRole('button', { name: /retire dataset/i }),
    )

    await waitFor(() => {
      expect(rawApi.retireDatasetImpl).toHaveBeenCalledTimes(1)
    })
    // The retire hook was wired with ifMatchRequest(revision=4). The hook
    // re-renders with `undefined` once the confirm dialog closes, so assert
    // against the last DEFINED request config (present while confirming).
    const lastRequest = rawApi.retireDatasetRequests
      .filter((r) => r !== undefined)
      .at(-1)
    expect(lastRequest).toEqual(ifMatchRequest(4))
    expect(
      (lastRequest as { headers: Record<string, string> }).headers['If-Match'],
    ).toBe('"revision-4"')
  })

  it('on 412 surfaces the concurrency message and reloads the current revision', async () => {
    rawApi.datasets = [makeDataset({ id: 'ds-1', code: 'DM', revision: 4 })]
    rawApi.retireDatasetImpl = vi.fn(async () => {
      throw problemError(412, { title: 'Precondition Failed', detail: 'stale' })
    })

    const { invalidateSpy } = renderWithClient(
      <DatasetsPanel rawId="raw-1" studyId="study-1" />,
    )

    fireEvent.click(screen.getByRole('button', { name: /retire/i }))
    const dialog = await screen.findByRole('dialog')
    fireEvent.click(
      within(dialog).getByRole('button', { name: /retire dataset/i }),
    )

    await waitFor(() => {
      expect(rawApi.retireDatasetImpl).toHaveBeenCalledTimes(1)
    })
    // The ConfirmDialog surfaces the staleness message (R3.8)…
    await waitFor(() => {
      expect(screen.getByText(/changed since you opened it/i)).toBeTruthy()
    })
    // …and the current dataset revision is reloaded before retry (R3.8).
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: ['/api/v1/raw-datasets/ds-1'],
    })
  })
})
