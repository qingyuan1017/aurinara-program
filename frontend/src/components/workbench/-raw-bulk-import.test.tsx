// @vitest-environment jsdom
//
// Component/integration tests for the Raw bulk-import dialog (two-phase flow):
//   phase 1  multi-file upload via createSourceFilesBulk;
//   phase 2  editable entry table — code-pattern + intra-batch duplicate guards;
//   submit   createDatasetImport carrying a syntactically valid Idempotency-Key;
//   phase 3  status panel polling getDatasetImport queued->running->succeeded,
//            rendering per-entry issues on failure, and a cancel control wired
//            to cancelDatasetImport while non-terminal.
//
// Following the established repo convention (`-compile-execution-panels.test.tsx`):
// no MSW is installed, so the generated Orval hooks + toast + invalidate are
// mocked and the REAL dialog is driven over faithful hook fakes. The poll flow
// uses a scripted get-operation hook under vitest fake timers.
import { act, fireEvent, render, screen } from '@testing-library/react'
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
import type {
  RawDatasetImportResponse,
  SourceFileBulkResponse,
  SourceFileResponse,
} from '@/api/generated/model'

beforeAll(() => {
  installJsdomHarness()
})

vi.mock('@/components/ui/sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

const invalidateRawDataset = vi.fn()
vi.mock('@/lib/invalidate', () => ({
  invalidateRawDataset: (...args: unknown[]) => invalidateRawDataset(...args),
}))

// ---------------------------------------------------------------------------
// Mutable fixtures the generated-hook stubs read through.
// ---------------------------------------------------------------------------
const rawApi: {
  bulkImpl: (vars: {
    studyId: string
    data: { files: unknown[] }
  }) => Promise<SourceFileBulkResponse>
  bulkVars: Array<{ studyId: string; data: { files: unknown[] } }>
  importImpl: (vars: {
    rawId: string
    data: unknown
  }) => Promise<RawDatasetImportResponse>
  importVars: Array<{ rawId: string; data: unknown }>
  importRequests: Array<AxiosRequestConfig | undefined>
  cancelVars: Array<{ importId: string }>
} = {
  bulkImpl: async () => makeBulkResponse(),
  bulkVars: [],
  importImpl: async () => makeImport(),
  importVars: [],
  importRequests: [],
  cancelVars: [],
}

// Scripted poll source: the test pushes a sequence and the fake get-hook
// replays one state per refetch tick, self-halting on a terminal status.
const pollSource: { import: RawDatasetImportResponse[] } = { import: [] }
const pollIndex = { import: 0 }

function makeMutation<V, R>(
  impl: (vars: V) => Promise<R>,
  getError?: () => AxiosError | null,
) {
  return {
    isPending: false,
    error: (getError?.() ?? null) as AxiosError | null,
    reset: () => {},
    mutate: (vars: V) => {
      void impl(vars)
    },
    mutateAsync: async (vars: V) => impl(vars),
  }
}

vi.mock('@/api/generated/artifacts/artifacts', () => ({
  useCreateSourceFilesBulk: () =>
    makeMutation((vars: { studyId: string; data: { files: unknown[] } }) => {
      rawApi.bulkVars.push(vars)
      return rawApi.bulkImpl(vars)
    }),
}))

vi.mock('@/api/generated/raw/raw', () => ({
  getGetDatasetImportQueryKey: (id?: string) => [
    `/api/v1/raw-dataset-imports/${id}`,
  ],
  useGetDatasetImport: makeScriptedGet('import', [
    'succeeded',
    'failed',
    'cancelled',
  ]),
  useCreateDatasetImport: (options?: { request?: AxiosRequestConfig }) => {
    rawApi.importRequests.push(options?.request)
    return makeMutation((vars: { rawId: string; data: unknown }) => {
      rawApi.importVars.push(vars)
      return rawApi.importImpl(vars)
    })
  },
  useCancelDatasetImport: () =>
    makeMutation((vars: { importId: string }) => {
      rawApi.cancelVars.push(vars)
      return Promise.resolve(makeImport({ status: 'cancelled' }))
    }),
}))

/** A scripted get-operation hook factory (as the SDTM panel tests use). */
function makeScriptedGet(kind: 'import', terminal: string[]) {
  return (
    _id: string,
    opts?: {
      query?: {
        enabled?: boolean
        refetchInterval?: number | false
        retry?: boolean
      }
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
        if (
          cur &&
          typeof cur.status === 'string' &&
          terminal.includes(cur.status)
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

// Import AFTER the mocks so the dialog binds to the stubs.
import { RawBulkImportDialog } from './raw-bulk-import-dialog'

// ---------------------------------------------------------------------------
// Fixtures.
// ---------------------------------------------------------------------------
function makeFile(id: string, filename = `${id}.xpt`): SourceFileResponse {
  return {
    id,
    study_id: 'study-1',
    artifact_id: `artifact-${id}`,
    filename,
    media_type: 'application/x-sas-xport',
    sha256: 'a'.repeat(64),
    size: 1024,
    created_by: 'user-1',
    created_at: '2024-01-01T00:00:00Z',
  }
}

function makeBulkResponse(
  items: SourceFileResponse[] = [makeFile('file-1', 'dm.xpt'), makeFile('file-2', 'ae.xpt')],
): SourceFileBulkResponse {
  return { items }
}

function makeImport(
  overrides: Partial<RawDatasetImportResponse> = {},
): RawDatasetImportResponse {
  return {
    id: 'import-1',
    raw_id: 'raw-1',
    study_id: 'study-1',
    status: 'queued',
    schema_version: '1.0.0',
    entry_count: 2,
    files_inspected: 0,
    input_fingerprint: 'f'.repeat(64),
    result_dataset_ids: [],
    issues: [],
    failure: null,
    started_at: null,
    completed_at: null,
    created_by: 'user-1',
    created_at: '2024-01-01T00:00:00Z',
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

function renderDialog() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const ui: ReactNode = (
    <QueryClientProvider client={qc}>
      <RawBulkImportDialog
        rawId="raw-1"
        studyId="study-1"
        open
        onOpenChange={() => {}}
      />
    </QueryClientProvider>
  )
  return render(ui)
}

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

function readIdempotencyKey(
  request: AxiosRequestConfig | undefined,
): string | undefined {
  const headers = request?.headers as Record<string, string> | undefined
  return headers?.['Idempotency-Key']
}

/** Upload two files, advancing the dialog to the author phase. */
async function uploadTwoFiles() {
  const input = screen.getByTestId('file-dropzone-input') as HTMLInputElement
  fireEvent.change(input, {
    target: {
      files: [
        new File(['x'], 'dm.xpt', { type: 'application/octet-stream' }),
        new File(['y'], 'ae.xpt', { type: 'application/octet-stream' }),
      ],
    },
  })
  fireEvent.click(screen.getByRole('button', { name: /upload files/i }))
  await act(async () => {
    await Promise.resolve()
  })
}

beforeEach(() => {
  rawApi.bulkImpl = async () => makeBulkResponse()
  rawApi.bulkVars = []
  rawApi.importImpl = async () => makeImport()
  rawApi.importVars = []
  rawApi.importRequests = []
  rawApi.cancelVars = []
  pollSource.import = []
  pollIndex.import = 0
  invalidateRawDataset.mockClear()
})

afterEach(() => {
  vi.clearAllMocks()
})

// ===========================================================================
// Phase 1 → 2: upload happy path seeds one row per returned file.
// ===========================================================================
describe('bulk upload (phase 1 → 2)', () => {
  it('uploads the picked files and seeds one row per returned file in order', async () => {
    renderDialog()
    await uploadTwoFiles()

    // The bulk upload carried the two picked files.
    expect(rawApi.bulkVars).toHaveLength(1)
    expect(rawApi.bulkVars[0].studyId).toBe('study-1')
    expect(rawApi.bulkVars[0].data.files).toHaveLength(2)

    // One author row per returned file, each defaulting to its own source.
    const codeInputs = screen.getAllByLabelText('Dataset code')
    expect(codeInputs).toHaveLength(2)
    const sourceSelects = screen.getAllByLabelText('Source file')
    expect(sourceSelects).toHaveLength(2)
    // Code and label are pre-populated from the file names (dm.xpt, ae.xpt).
    expect((codeInputs[0] as HTMLInputElement).value).toBe('DM')
    expect((codeInputs[1] as HTMLInputElement).value).toBe('AE')
    // With valid, distinct derived codes the batch is ready to submit.
    expect(
      (screen.getByRole('button', { name: /submit import/i }) as HTMLButtonElement)
        .disabled,
    ).toBe(false)
  })

  it('shows a top-level alert and retains the author entry on a 413 upload failure', async () => {
    rawApi.bulkImpl = async () => {
      throw problemError(413, { title: 'Too large' })
    }
    renderDialog()
    await uploadTwoFiles()

    expect(screen.getByRole('alert').textContent).toMatch(/exceed the accepted size/i)
    // Still in the select phase: the upload button is present.
    expect(screen.getByRole('button', { name: /upload files/i })).toBeTruthy()
  })
})

// ===========================================================================
// Phase 2: client-side code-pattern + intra-batch duplicate guards.
// ===========================================================================
describe('entry-table validation (phase 2)', () => {
  it('keeps submit disabled on an invalid code pattern and enables it when valid', async () => {
    renderDialog()
    await uploadTwoFiles()

    const codeInputs = screen.getAllByLabelText('Dataset code')
    const labelInputs = screen.getAllByLabelText('Dataset label')

    // Invalid leading-digit code on the first row.
    fireEvent.change(codeInputs[0], { target: { value: '1DM' } })
    fireEvent.change(labelInputs[0], { target: { value: 'Demographics' } })
    fireEvent.change(codeInputs[1], { target: { value: 'AE' } })
    fireEvent.change(labelInputs[1], { target: { value: 'Adverse Events' } })

    const submit = screen.getByRole('button', {
      name: /submit import/i,
    }) as HTMLButtonElement
    expect(submit.disabled).toBe(true)
    expect(
      screen.getByText(/code must start with a letter/i),
    ).toBeTruthy()

    // Correct the code: submit becomes enabled.
    fireEvent.change(codeInputs[0], { target: { value: 'DM' } })
    expect(submit.disabled).toBe(false)
  })

  it('detects intra-batch duplicate codes before submit', async () => {
    renderDialog()
    await uploadTwoFiles()

    const codeInputs = screen.getAllByLabelText('Dataset code')
    const labelInputs = screen.getAllByLabelText('Dataset label')
    fireEvent.change(codeInputs[0], { target: { value: 'DM' } })
    fireEvent.change(labelInputs[0], { target: { value: 'Demographics' } })
    fireEvent.change(codeInputs[1], { target: { value: 'DM' } })
    fireEvent.change(labelInputs[1], { target: { value: 'Duplicate' } })

    const submit = screen.getByRole('button', {
      name: /submit import/i,
    }) as HTMLButtonElement
    expect(submit.disabled).toBe(true)
    expect(
      screen.getAllByText(/duplicate code within this batch/i).length,
    ).toBeGreaterThanOrEqual(2)
    expect(rawApi.importVars).toHaveLength(0)
  })
})

// ===========================================================================
// Submit: carries a valid Idempotency-Key; a 422 maps issues onto rows.
// ===========================================================================
describe('submit (phase 2 → 3)', () => {
  async function authorValidRows() {
    const codeInputs = screen.getAllByLabelText('Dataset code')
    const labelInputs = screen.getAllByLabelText('Dataset label')
    fireEvent.change(codeInputs[0], { target: { value: 'DM' } })
    fireEvent.change(labelInputs[0], { target: { value: 'Demographics' } })
    fireEvent.change(codeInputs[1], { target: { value: 'AE' } })
    fireEvent.change(labelInputs[1], { target: { value: 'Adverse Events' } })
  }

  it('submits the entries with a syntactically valid Idempotency-Key', async () => {
    renderDialog()
    await uploadTwoFiles()
    await authorValidRows()

    fireEvent.click(screen.getByRole('button', { name: /submit import/i }))
    await act(async () => {
      await Promise.resolve()
    })

    expect(rawApi.importVars).toHaveLength(1)
    const vars = rawApi.importVars[0] as { rawId: string; data: { schema_version: string; entries: { code: string }[] } }
    expect(vars.rawId).toBe('raw-1')
    expect(vars.data.schema_version).toBe('1.0.0')
    expect(vars.data.entries.map((e) => e.code)).toEqual(['DM', 'AE'])

    const key = readIdempotencyKey(
      rawApi.importRequests[rawApi.importRequests.length - 1],
    )
    expect(key).toMatch(UUID_RE)
  })

  it('maps a 422 issue onto the matching row and retains edits', async () => {
    rawApi.importImpl = async () => {
      throw problemError(422, {
        title: 'Unprocessable',
        issues: [
          {
            id: 'i1',
            code: 'duplicate_raw_dataset_code',
            severity: 'error',
            message: 'A dataset with code DM already exists.',
            dataset: 'DM',
            module: 'raw',
            entity_type: 'raw_dataset',
          },
        ],
      })
    }
    renderDialog()
    await uploadTwoFiles()
    await authorValidRows()

    fireEvent.click(screen.getByRole('button', { name: /submit import/i }))
    await act(async () => {
      await Promise.resolve()
    })

    // The issue message is rendered against the DM row, edits retained.
    expect(
      screen.getByText('A dataset with code DM already exists.'),
    ).toBeTruthy()
    expect(
      (screen.getAllByLabelText('Dataset code')[0] as HTMLInputElement).value,
    ).toBe('DM')
  })

  it('shows the staleness banner and retains edits on a 409', async () => {
    rawApi.importImpl = async () => {
      throw problemError(409, {
        title: 'Conflict',
        code: 'idempotency_key_reused',
      })
    }
    renderDialog()
    await uploadTwoFiles()
    await authorValidRows()

    fireEvent.click(screen.getByRole('button', { name: /submit import/i }))
    await act(async () => {
      await Promise.resolve()
    })

    expect(screen.getByRole('alert').textContent).toMatch(
      /already submitted with different inputs/i,
    )
    expect(
      (screen.getAllByLabelText('Dataset code')[0] as HTMLInputElement).value,
    ).toBe('DM')
  })
})

// ===========================================================================
// Phase 3: polling queued -> running -> succeeded; failure issues; cancel.
// ===========================================================================
describe('status panel (phase 3)', () => {
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

  async function authorAndSubmit() {
    const codeInputs = screen.getAllByLabelText('Dataset code')
    const labelInputs = screen.getAllByLabelText('Dataset label')
    fireEvent.change(codeInputs[0], { target: { value: 'DM' } })
    fireEvent.change(labelInputs[0], { target: { value: 'Demographics' } })
    fireEvent.change(codeInputs[1], { target: { value: 'AE' } })
    fireEvent.change(labelInputs[1], { target: { value: 'Adverse Events' } })
    fireEvent.click(screen.getByRole('button', { name: /submit import/i }))
    await act(async () => {
      await Promise.resolve()
    })
  }

  it('transitions queued -> running -> succeeded and invalidates the dataset list', async () => {
    pollSource.import = [
      makeImport({ status: 'queued' }),
      makeImport({ status: 'running', files_inspected: 1 }),
      makeImport({
        status: 'succeeded',
        files_inspected: 2,
        result_dataset_ids: ['ds-1', 'ds-2'],
      }),
    ]
    rawApi.importImpl = async () => pollSource.import[0]

    renderDialog()
    // Fake timers are active; drive the pre-poll phases through act() ticks.
    await act(async () => {
      const input = screen.getByTestId('file-dropzone-input') as HTMLInputElement
      fireEvent.change(input, {
        target: {
          files: [
            new File(['x'], 'dm.xpt', { type: 'application/octet-stream' }),
            new File(['y'], 'ae.xpt', { type: 'application/octet-stream' }),
          ],
        },
      })
      fireEvent.click(screen.getByRole('button', { name: /upload files/i }))
      await Promise.resolve()
    })
    await authorAndSubmit()

    // queued -> running
    await act(async () => {
      vi.advanceTimersByTime(2_000)
      await Promise.resolve()
    })
    // running -> succeeded
    await act(async () => {
      vi.advanceTimersByTime(2_000)
      await Promise.resolve()
    })

    expect(screen.getByText('2 datasets created')).toBeTruthy()
    expect(invalidateRawDataset).toHaveBeenCalledWith(
      expect.anything(),
      'raw-1',
    )
  })

  it('renders the typed failure and per-entry issues on a failed terminal', async () => {
    pollSource.import = [
      makeImport({ status: 'running' }),
      makeImport({
        status: 'failed',
        failure: { code: 'raw_import_failed', detail: 'The import was rejected.' },
        issues: [
          {
            id: 'i1',
            code: 'duplicate_raw_dataset_code',
            severity: 'error',
            message: 'Code DM already exists.',
            dataset: 'DM',
            module: 'raw',
            entity_type: 'raw_dataset',
          },
        ],
      }),
    ]
    rawApi.importImpl = async () => pollSource.import[0]

    renderDialog()
    await act(async () => {
      const input = screen.getByTestId('file-dropzone-input') as HTMLInputElement
      fireEvent.change(input, {
        target: {
          files: [
            new File(['x'], 'dm.xpt', { type: 'application/octet-stream' }),
            new File(['y'], 'ae.xpt', { type: 'application/octet-stream' }),
          ],
        },
      })
      fireEvent.click(screen.getByRole('button', { name: /upload files/i }))
      await Promise.resolve()
    })
    await authorAndSubmit()

    await act(async () => {
      vi.advanceTimersByTime(2_000)
      await Promise.resolve()
    })

    expect(screen.getByText('The import failed')).toBeTruthy()
    expect(screen.getByText('raw_import_failed')).toBeTruthy()
    expect(screen.getByText('Code DM already exists.')).toBeTruthy()
    expect(invalidateRawDataset).not.toHaveBeenCalled()
  })

  it('shows a cancel control while non-terminal and calls cancelDatasetImport', async () => {
    pollSource.import = [
      makeImport({ status: 'queued' }),
      makeImport({ status: 'running' }),
    ]
    rawApi.importImpl = async () => pollSource.import[0]

    renderDialog()
    await act(async () => {
      const input = screen.getByTestId('file-dropzone-input') as HTMLInputElement
      fireEvent.change(input, {
        target: {
          files: [
            new File(['x'], 'dm.xpt', { type: 'application/octet-stream' }),
            new File(['y'], 'ae.xpt', { type: 'application/octet-stream' }),
          ],
        },
      })
      fireEvent.click(screen.getByRole('button', { name: /upload files/i }))
      await Promise.resolve()
    })
    await authorAndSubmit()

    const cancelButton = screen.getByRole('button', { name: /cancel import/i })
    fireEvent.click(cancelButton)
    await act(async () => {
      await Promise.resolve()
    })

    expect(rawApi.cancelVars).toEqual([{ importId: 'import-1' }])
  })
})
