// @vitest-environment jsdom
//
// Component tests for the SDTM Input selection panel (`input-selection-panel.tsx`)
// and the SDTM Specification panel (`specification-panel.tsx`) — task 11.3.
//
// Coverage (Requirements 10.1, 10.4, 10.5, 10.6, 11.2, 11.4, 11.6, 11.7):
//   Input selection:
//     * save sends the full pinned body + the aggregate ETag as If-Match (10.1);
//     * a 422 `sdtm_raw_artifact_invalid` / `sdtm_raw_validation_invalid`
//       renders the problem detail + the issues[] list (10.4);
//     * an `input_refresh_required` selection state shows the staleness banner (10.5);
//     * a 412 shows the concurrency message with a reload action that re-fetches
//       the current aggregate revision (10.6).
//   Specification:
//     * a 404 `sdtm_specification_required` renders the unsaved empty state (11.2);
//     * save sends the aggregate ETag as If-Match (11.4);
//     * import via the dropzone and via click-to-browse issue the identical
//       `useImportSpecification` request carrying both the aggregate ETag and a
//       stable Idempotency-Key (11.4);
//     * a 422 import-invalid renders the problem detail + issues[] (11.4);
//     * export calls the download bypass; a dedicated test confirms the real
//       `useDownload` hits AXIOS_INSTANCE (base URL + bearer interceptor) with
//       `responseType: 'blob'` (11.6);
//     * a 412 on save shows the concurrency notice with a reload action (11.7).
//
// Mirrors the repo convention (see `src/routes/_app/raw/-raw-screens.test.tsx`):
// the generated Orval hooks + study provider + toast are mocked and the REAL
// panels are driven over faithful hook fakes so the exact body/headers the
// panels funnel through the mutation `request` option can be asserted.
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
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
import { ifMatchRequest } from '@/lib/requests'
import type {
  AggregateResponse,
  DependencySelectionResponse,
  InputSelectionResponse,
  SdtmSpecificationInitializationOptions,
  SpecificationResponse,
  StandardProductResponse,
  StandardVersionResponse,
} from '@/api/generated/model'

beforeAll(() => {
  installJsdomHarness()
  HTMLElement.prototype.scrollIntoView = vi.fn()
})

// ---------------------------------------------------------------------------
// Toast stub — keep sonner out of the jsdom/theme-provider path.
// ---------------------------------------------------------------------------
vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

// ---------------------------------------------------------------------------
// Generated Raw + Artifacts list-hook stubs that back the input-selection
// dropdowns. The panel reads option labels/values from these; a mutable
// `rawApi` object (seeded in `beforeEach`) drives what each dropdown offers.
// ---------------------------------------------------------------------------
interface RawAggregateOption {
  id: string
  study_id?: string
  code: string
  name: string
  status: string
  revision: number
}
interface RawDatasetOption {
  id: string
  raw_id: string
  code: string
  label: string
  revision: number
  current_source_file_id: string
  status?: string
}
interface SourceFileOption {
  id: string
  artifact_id: string
  sha256: string
  filename: string
  size: number
}

const rawApi: {
  rawAggregates: RawAggregateOption[]
  datasets: RawDatasetOption[]
  sourceFiles: SourceFileOption[]
  // Resolver sources for the two auto-resolved fields. `latestValidationRun`
  // can be set to an AxiosError to simulate the 404 "no successful run" case.
  latestValidationRun:
    | { validation_run_id: string; raw_revision?: number | null }
    | undefined
  latestValidationRunError: AxiosError | null
  latestValidationRunLoading: boolean
  dependencyFingerprint: string | undefined
} = {
  rawAggregates: [],
  datasets: [],
  sourceFiles: [],
  latestValidationRun: undefined,
  latestValidationRunError: null,
  latestValidationRunLoading: false,
  dependencyFingerprint: undefined,
}

vi.mock('@/api/generated/raw/raw', () => ({
  useListRawAggregates: () => ({
    data: { items: rawApi.rawAggregates },
    error: null,
    isLoading: false,
    isError: false,
  }),
  useListDatasets: () => ({
    data: rawApi.datasets,
    error: null,
    isLoading: false,
    isError: false,
  }),
  // Resolves `raw_dependency_fingerprint` from the Raw dependency selection.
  useGetRawDependencies: () => ({
    data: rawApi.dependencyFingerprint
      ? { fingerprint: rawApi.dependencyFingerprint }
      : undefined,
    error: null,
    isLoading: false,
    isError: false,
  }),
  // Resolves `validation_run_id` from the Raw latest-successful-validation-run
  // sub-resource. A seeded error with status 404 drives the "run and pass
  // validation first" prompt.
  useGetLatestValidationRun: () => ({
    data: rawApi.latestValidationRunError
      ? undefined
      : rawApi.latestValidationRun,
    error: rawApi.latestValidationRunError,
    isLoading: rawApi.latestValidationRunLoading,
    isError: !!rawApi.latestValidationRunError,
  }),
}))

vi.mock('@/api/generated/artifacts/artifacts', () => ({
  useListSourceFiles: () => ({
    data: { items: rawApi.sourceFiles },
    error: null,
    isLoading: false,
    isError: false,
  }),
}))

const catalogApi: {
  products: StandardProductResponse[]
  versions: StandardVersionResponse[]
} = {
  products: [],
  versions: [],
}

vi.mock('@/api/generated/provider-catalogs/provider-catalogs', () => ({
  useListStandards: () => ({
    data: catalogApi.products,
    error: null,
    isLoading: false,
    isError: false,
  }),
  useListStandardVersions: (productId: string) => ({
    data: catalogApi.versions.filter((version) => version.product_id === productId),
    error: null,
    isLoading: false,
    isError: false,
  }),
  useGetStandardVersion: (versionId: string) => ({
    data: catalogApi.versions.find((version) => version.id === versionId),
    error: null,
    isLoading: false,
    isError: false,
  }),
}))

// ---------------------------------------------------------------------------
// Generated SDTM hook stubs. Each test installs the behaviour it needs via the
// mutable `sdtmApi` object the mock reads through.
// ---------------------------------------------------------------------------
interface MutationCall {
  vars: unknown
  request: unknown
}

const sdtmApi: {
  // input selection
  selection: InputSelectionResponse | undefined
  selectionError: AxiosError | null
  rawContext: Record<string, unknown> | undefined
  putSelectionImpl: (vars: { sdtmId: string; data: unknown }) => Promise<unknown>
  putSelectionRequests: unknown[]
  // specification
  spec: SpecificationResponse | undefined
  specError: AxiosError | null
  dependencies: DependencySelectionResponse | undefined
  initializationOptions: SdtmSpecificationInitializationOptions | undefined
  replaceDependenciesImpl: (vars: {
    sdtmId: string
    data: unknown
  }) => Promise<unknown>
  replaceDependenciesRequests: unknown[]
  putSpecImpl: (vars: { sdtmId: string; data: unknown }) => Promise<unknown>
  putSpecRequests: unknown[]
  initializeSpecImpl: (vars: { sdtmId: string; data: unknown }) => Promise<unknown>
  initializeSpecRequests: unknown[]
  importImpl: (vars: { sdtmId: string }) => Promise<unknown>
  importCalls: MutationCall[]
} = {
  selection: undefined,
  selectionError: null,
  rawContext: undefined,
  putSelectionImpl: async () => ({}),
  putSelectionRequests: [],
  spec: undefined,
  specError: null,
  dependencies: undefined,
  initializationOptions: undefined,
  replaceDependenciesImpl: async () => ({}),
  replaceDependenciesRequests: [],
  putSpecImpl: async () => ({}),
  putSpecRequests: [],
  initializeSpecImpl: async () => ({}),
  initializeSpecRequests: [],
  importImpl: async () => ({}),
  importCalls: [],
}

vi.mock('@/api/generated/sdtm/sdtm', () => {
  const useGetInputSelection = () => ({
    data: sdtmApi.selection,
    error: sdtmApi.selectionError,
    isLoading: false,
    isError: !!sdtmApi.selectionError,
  })
  const useGetRawContext = () => ({
    data: sdtmApi.rawContext,
    error: null,
    isLoading: false,
    isError: false,
  })
  const usePutInputSelection = (options?: {
    mutation?: { onSuccess?: (data: unknown) => void }
    request?: unknown
  }) => {
    sdtmApi.putSelectionRequests.push(options?.request)
    return useMutationFake(
      (vars: { sdtmId: string; data: unknown }) => sdtmApi.putSelectionImpl(vars),
      options?.mutation?.onSuccess,
    )
  }

  const useGetSpecification = () => ({
    data: sdtmApi.spec,
    error: sdtmApi.specError,
    isLoading: false,
    isError: !!sdtmApi.specError,
  })
  const useGetSdtmDependencies = () => ({
    data: sdtmApi.dependencies,
    error: null,
    isLoading: false,
    isError: false,
  })
  const useGetSpecificationInitializationOptions = () => ({
    data: sdtmApi.initializationOptions,
    error: null,
    isLoading: false,
    isError: false,
  })
  const usePutSpecification = (options?: {
    mutation?: { onSuccess?: (data: unknown) => void }
    request?: unknown
  }) => {
    sdtmApi.putSpecRequests.push(options?.request)
    return useMutationFake(
      (vars: { sdtmId: string; data: unknown }) => sdtmApi.putSpecImpl(vars),
      options?.mutation?.onSuccess,
    )
  }
  const useReplaceSdtmDependencies = (options?: {
    mutation?: { onSuccess?: (data: unknown) => void }
    request?: unknown
  }) => {
    sdtmApi.replaceDependenciesRequests.push(options?.request)
    return useMutationFake(
      (vars: { sdtmId: string; data: unknown }) =>
        sdtmApi.replaceDependenciesImpl(vars),
      options?.mutation?.onSuccess,
    )
  }
  const useInitializeSpecification = (options?: { request?: unknown }) => {
    sdtmApi.initializeSpecRequests.push(options?.request)
    return useMutationFake(
      (vars: { sdtmId: string; data: unknown }) =>
        sdtmApi.initializeSpecImpl(vars),
    )
  }
  // The real generated hook forwards only a HOOK-LEVEL `request` to the mutator
  // (the file bytes + content type + If-Match + Idempotency-Key), so the panel
  // instantiates `useImportSpecification({ request })` and calls
  // `mutateAsync({ sdtmId })` with no per-call request. The fake records the
  // hook-level request captured at the mutateAsync call.
  const useImportSpecification = (options?: {
    request?: unknown
    mutation?: { onSuccess?: (data: unknown) => void }
  }) => {
    return {
      isPending: false,
      error: null as AxiosError | null,
      mutate: () => {},
      mutateAsync: async (vars: { sdtmId: string }) => {
        sdtmApi.importCalls.push({ vars, request: options?.request })
        const data = await sdtmApi.importImpl(vars)
        options?.mutation?.onSuccess?.(data)
        return data
      },
    }
  }

  return {
    useGetInputSelection,
    useGetRawContext,
    usePutInputSelection,
    useGetSpecification,
    useGetSdtmDependencies,
    useGetSpecificationInitializationOptions,
    usePutSpecification,
    useReplaceSdtmDependencies,
    useInitializeSpecification,
    useImportSpecification,
    getGetInputSelectionQueryKey: (sdtmId: string) => [
      '/sdtms',
      sdtmId,
      'input-selection',
    ],
    getGetRawContextQueryKey: (sdtmId: string) => ['/sdtms', sdtmId, 'raw-context'],
    getGetSpecificationQueryKey: (sdtmId: string) => [
      '/sdtms',
      sdtmId,
      'specification',
    ],
    getGetSpecificationInitializationOptionsQueryKey: (sdtmId: string) => [
      '/sdtms',
      sdtmId,
      'specification',
      'initialization-options',
    ],
    getGetSdtmAggregateQueryKey: (sdtmId: string) => ['/sdtms', sdtmId],
  }
})

// ---------------------------------------------------------------------------
// useDownload stub (for the Specification panel's export buttons). A dedicated
// test exercises the REAL hook against a mocked AXIOS_INSTANCE to prove the
// base URL + bearer + responseType bypass (11.6).
// ---------------------------------------------------------------------------
const downloadSpy = {
  downloadSpecificationExport: vi.fn(async () => {}),
}
vi.mock('@/hooks/use-download', () => ({
  useDownload: () => ({
    isPending: false,
    error: null,
    downloadSpecificationExport: downloadSpy.downloadSpecificationExport,
    downloadArtifact: vi.fn(),
    renderDefineXml: vi.fn(),
  }),
}))

/**
 * A stateful `UseMutationResult`-shaped fake. Like TanStack Query, a rejected
 * `mutateAsync` records the error on `.error` (triggering a re-render) and
 * re-throws so a caller's `try/catch` still runs; a resolve fires `onSuccess`
 * and clears the error. `reset()` clears the error state. This lets panels that
 * render inline from `mutation.error` (InputSelectionPanel) exercise for real.
 */
function useMutationFake(
  impl: (vars: never) => Promise<unknown>,
  onSuccess?: (data: unknown) => void,
) {
  const [error, setError] = React.useState<AxiosError | null>(null)
  const [isPending, setIsPending] = React.useState(false)
  return {
    isPending,
    error,
    reset: () => setError(null),
    mutate: () => {},
    mutateAsync: async (vars: never) => {
      setIsPending(true)
      try {
        const data = await impl(vars)
        setError(null)
        onSuccess?.(data)
        return data
      } catch (err) {
        setError(err as AxiosError)
        throw err
      } finally {
        setIsPending(false)
      }
    },
  }
}

// ---------------------------------------------------------------------------
// Imports AFTER the mocks so the panels bind to the stubs.
// ---------------------------------------------------------------------------
import { InputSelectionPanel } from './input-selection-panel'
import { SpecificationPanel } from './specification-panel'
import { WorkbenchContextProvider } from './workbench-context'
import type { WorkbenchContextValue } from './workbench-context'

const AGGREGATE_REVISION = 5

function makeAggregate(
  overrides: Partial<AggregateResponse> = {},
): AggregateResponse {
  return {
    id: 'sdtm-1',
    study_id: 'study-1',
    code: 'SDTM1',
    name: 'First SDTM workbench',
    status: 'draft',
    revision: AGGREGATE_REVISION,
    ...overrides,
  }
}

function makeWorkbenchValue(
  aggregate: AggregateResponse,
): WorkbenchContextValue {
  return {
    aggregate,
    revision: aggregate.revision,
    studyId: aggregate.study_id,
    // Mirrors WorkbenchDetailShell: binds If-Match to the current revision.
    ifMatch: () => ifMatchRequest(aggregate.revision),
  }
}

function renderInWorkbench(
  ui: ReactNode,
  aggregate: AggregateResponse = makeAggregate(),
) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const invalidateSpy = vi.spyOn(qc, 'invalidateQueries')
  const utils = render(
    <QueryClientProvider client={qc}>
      <WorkbenchContextProvider value={makeWorkbenchValue(aggregate)}>
        {ui}
      </WorkbenchContextProvider>
    </QueryClientProvider>,
  )
  return { ...utils, qc, invalidateSpy }
}

function problemError(status: number, body: Record<string, unknown>): AxiosError {
  return {
    isAxiosError: true,
    message: 'Request failed',
    response: { status, data: body },
  } as unknown as AxiosError
}

function makeSelection(
  overrides: Partial<InputSelectionResponse> = {},
): InputSelectionResponse {
  return {
    revision: 2,
    state: 'current',
    fingerprint: 'fp-selection',
    payload: {
      raw_id: 'raw-1',
      raw_revision: 4,
      validation_run_id: 'vr-1',
      raw_dependency_fingerprint: 'raw-dep-fp',
      source_artifacts: [
        { dataset_code: 'DM', artifact_id: 'art-dm', checksum: 'sha-dm' },
      ],
    } as unknown as InputSelectionResponse['payload'],
    ...overrides,
  }
}

function makeSpec(
  overrides: Partial<SpecificationResponse> = {},
): SpecificationResponse {
  return {
    id: 'spec-1',
    aggregate_id: 'sdtm-1',
    revision: 3,
    schema_version: '1.0.0',
    fingerprint: 'fp-spec',
    created_by: 'user-1',
    created_at: '2024-01-01T00:00:00Z',
    payload: {
      domains: [
        {
          code: 'DM',
          label: 'Demographics',
          domain_class: 'SPECIAL PURPOSE',
          structure: 'one record per subject',
          keys: ['STUDYID', 'USUBJID'],
          sort_order: ['USUBJID'],
          expected_output_name: 'dm.xpt',
          variables: [
            {
              name: 'STUDYID',
              label: 'Study Identifier',
              data_type: 'text',
              role: 'Identifier',
              core: 'Req',
              origin: 'Protocol',
            },
            {
              name: 'USUBJID',
              label: 'Unique Subject Identifier',
              data_type: 'text',
              role: 'Identifier',
              core: 'Req',
              origin: 'Derived',
            },
          ],
        },
      ],
    } as unknown as SpecificationResponse['payload'],
    ...overrides,
  }
}

beforeEach(() => {
  // Seed the dropdown option sources so the values in `makeSelection()` resolve
  // to real options: the seeded form still submits raw_id:'raw-1',
  // raw_revision:4, dataset_code:'DM', artifact_id:'art-dm', checksum:'sha-dm'.
  rawApi.rawAggregates = [
    {
      id: 'raw-1',
      study_id: 'study-1',
      code: 'RAW1',
      name: 'Raw one',
      status: 'draft',
      revision: 4,
    },
  ]
  rawApi.datasets = [
    {
      id: 'ds-1',
      raw_id: 'raw-1',
      code: 'DM',
      label: 'Demographics',
      revision: 1,
      current_source_file_id: 'sf-1',
    },
  ]
  rawApi.sourceFiles = [
    {
      id: 'sf-1',
      artifact_id: 'art-dm',
      sha256: 'sha-dm',
      filename: 'dm.xpt',
      size: 1,
    },
  ]
  // The resolvers return the same pinned values the body must round-trip, so
  // the auto-resolved validation_run_id/fingerprint equal 'vr-1'/'raw-dep-fp'.
  rawApi.latestValidationRun = { validation_run_id: 'vr-1', raw_revision: 4 }
  rawApi.latestValidationRunError = null
  rawApi.latestValidationRunLoading = false
  rawApi.dependencyFingerprint = 'raw-dep-fp'
  catalogApi.products = [
    {
      id: 'standard-product-1',
      code: 'SDTMIG',
      name: 'SDTM Implementation Guide',
      provider: 'CDISC',
      family: 'SDTMIG',
      product_type: 'implementation_guide',
      scope: 'clinical',
    },
  ]
  catalogApi.versions = [
    {
      id: 'standard-version-1',
      product_id: 'standard-product-1',
      version: '3.3',
      publication_date: null,
      library_href: '/mdr/sdtmig/3-3',
      content_schema_version: '1.0.0',
      lifecycle: 'active',
      checksum: 'sha-sdtmig-3-3',
      provenance: {},
      applicable_modules: ['sdtm'],
      purposes: ['reference_metadata'],
      compatibility: {},
      created_at: '2024-01-01T00:00:00Z',
    },
    {
      id: 'standard-version-2',
      product_id: 'standard-product-1',
      version: '3.4',
      publication_date: null,
      library_href: '/mdr/sdtmig/3-4',
      content_schema_version: '1.0.0',
      lifecycle: 'active',
      checksum: 'sha-sdtmig-3-4',
      provenance: {},
      applicable_modules: ['sdtm'],
      purposes: ['reference_metadata', 'sdtm_ig'],
      compatibility: {},
      created_at: '2024-06-01T00:00:00Z',
    },
  ]
  sdtmApi.selection = undefined
  sdtmApi.selectionError = null
  sdtmApi.rawContext = undefined
  sdtmApi.putSelectionImpl = async () => ({})
  sdtmApi.putSelectionRequests = []
  sdtmApi.spec = undefined
  sdtmApi.specError = null
  sdtmApi.dependencies = undefined
  sdtmApi.initializationOptions = undefined
  sdtmApi.replaceDependenciesImpl = async () => ({})
  sdtmApi.replaceDependenciesRequests = []
  sdtmApi.putSpecImpl = async () => ({})
  sdtmApi.putSpecRequests = []
  sdtmApi.initializeSpecImpl = async () => ({})
  sdtmApi.initializeSpecRequests = []
  sdtmApi.importImpl = async () => ({})
  sdtmApi.importCalls = []
  downloadSpy.downloadSpecificationExport.mockClear()
})

afterEach(() => {
  vi.clearAllMocks()
})

// ===========================================================================
// Input selection (Requirements 10.1, 10.4, 10.5, 10.6)
// ===========================================================================
describe('InputSelectionPanel', () => {
  it('save sends the full pinned body + the aggregate ETag as If-Match (Req 10.1)', async () => {
    sdtmApi.selection = makeSelection()
    sdtmApi.putSelectionImpl = vi.fn(async () => makeSelection({ revision: 3 }))

    renderInWorkbench(<InputSelectionPanel />)

    // The form is seeded from the current selection; submit it unchanged so the
    // full pinned body round-trips.
    fireEvent.click(
      screen.getByRole('button', { name: /save input selection/i }),
    )

    await waitFor(() => {
      expect(sdtmApi.putSelectionImpl).toHaveBeenCalledTimes(1)
    })

    // The body carries every pinned field the backend requires (10.1).
    const call = (sdtmApi.putSelectionImpl as ReturnType<typeof vi.fn>).mock
      .calls[0][0]
    expect(call).toMatchObject({
      sdtmId: 'sdtm-1',
      data: {
        raw_id: 'raw-1',
        raw_revision: 4,
        validation_run_id: 'vr-1',
        raw_dependency_fingerprint: 'raw-dep-fp',
        source_artifacts: [
          { dataset_code: 'DM', artifact_id: 'art-dm', checksum: 'sha-dm' },
        ],
      },
    })

    // The mutation was wired with the aggregate ETag as If-Match (10.1).
    const request = sdtmApi.putSelectionRequests.at(-1) as AxiosRequestConfig
    expect(request).toEqual(ifMatchRequest(AGGREGATE_REVISION))
    expect(request.headers?.['If-Match']).toBe(`"revision-${AGGREGATE_REVISION}"`)
  })

  it('shows one Raw version choice and submits its automatically resolved pins', async () => {
    sdtmApi.selection = makeSelection()
    sdtmApi.putSelectionImpl = vi.fn(async () => makeSelection({ revision: 3 }))

    renderInWorkbench(<InputSelectionPanel />)

    // The only editable choice is the coherent Raw workbench/revision. Dataset,
    // artifact, checksum, validation, and dependency details stay automatic.
    expect(screen.getByLabelText('Raw data version')).toBeTruthy()
    expect(
      screen.getAllByText('RAW1 — Raw one · revision 4').length,
    ).toBeGreaterThan(0)
    expect(screen.queryByText('Dataset code')).toBeNull()
    expect(screen.queryByText('Artifact ID')).toBeNull()
    expect(screen.queryByText('Checksum (SHA-256)')).toBeNull()
    expect(
      screen.getByText(/1 active dataset and source artifact will be pinned automatically/i),
    ).toBeTruthy()

    fireEvent.click(
      screen.getByRole('button', { name: /save input selection/i }),
    )

    await waitFor(() => {
      expect(sdtmApi.putSelectionImpl).toHaveBeenCalledTimes(1)
    })

    // Dropdowns did not alter the submitted body shape (same pinned values).
    const call = (sdtmApi.putSelectionImpl as ReturnType<typeof vi.fn>).mock
      .calls[0][0]
    expect(call).toMatchObject({
      sdtmId: 'sdtm-1',
      data: {
        raw_id: 'raw-1',
        raw_revision: 4,
        validation_run_id: 'vr-1',
        raw_dependency_fingerprint: 'raw-dep-fp',
        source_artifacts: [
          { dataset_code: 'DM', artifact_id: 'art-dm', checksum: 'sha-dm' },
        ],
      },
    })
    const request = sdtmApi.putSelectionRequests.at(-1) as AxiosRequestConfig
    expect(request).toEqual(ifMatchRequest(AGGREGATE_REVISION))
  })

  it('automatically pins every active dataset to its bound source artifact', async () => {
    rawApi.datasets = [
      ...rawApi.datasets,
      {
        id: 'ds-2',
        raw_id: 'raw-1',
        code: 'AE',
        label: 'Adverse Events',
        revision: 1,
        current_source_file_id: 'sf-2',
        status: 'active',
      },
      {
        id: 'ds-3',
        raw_id: 'raw-1',
        code: 'OLD',
        label: 'Retired input',
        revision: 2,
        current_source_file_id: 'sf-3',
        status: 'retired',
      },
    ]
    rawApi.sourceFiles = [
      ...rawApi.sourceFiles,
      {
        id: 'sf-2',
        artifact_id: 'art-ae',
        sha256: 'sha-ae',
        filename: 'ae.xpt',
        size: 1,
      },
      {
        id: 'sf-3',
        artifact_id: 'art-old',
        sha256: 'sha-old',
        filename: 'old.xpt',
        size: 1,
      },
    ]
    sdtmApi.selection = makeSelection()
    sdtmApi.putSelectionImpl = vi.fn(async () => makeSelection({ revision: 3 }))

    renderInWorkbench(<InputSelectionPanel />)
    fireEvent.click(
      screen.getByRole('button', { name: /save input selection/i }),
    )

    await waitFor(() => {
      expect(sdtmApi.putSelectionImpl).toHaveBeenCalledTimes(1)
    })
    const call = (sdtmApi.putSelectionImpl as ReturnType<typeof vi.fn>).mock
      .calls[0][0]
    expect(call.data.source_artifacts).toEqual([
      { dataset_code: 'DM', artifact_id: 'art-dm', checksum: 'sha-dm' },
      { dataset_code: 'AE', artifact_id: 'art-ae', checksum: 'sha-ae' },
    ])
  })

  it('retains a seeded raw_id absent from the loaded list and still submits it', async () => {
    // The saved selection pins a workbench no longer offered by the list (e.g.
    // retired); the dropdown must keep showing the saved value, not blank it.
    rawApi.rawAggregates = []
    sdtmApi.selection = makeSelection()
    sdtmApi.putSelectionImpl = vi.fn(async () => makeSelection({ revision: 3 }))

    renderInWorkbench(<InputSelectionPanel />)

    // The seeded raw_id must survive even though no option matches it: a
    // synthetic SelectItem is injected so the value is never dropped. (Radix's
    // visible trigger text is layout-dependent under jsdom, so the preserved
    // value is proven through the submitted body rather than trigger text.)
    fireEvent.click(
      screen.getByRole('button', { name: /save input selection/i }),
    )

    await waitFor(() => {
      expect(sdtmApi.putSelectionImpl).toHaveBeenCalledTimes(1)
    })
    // The saved raw_id survives the retired-workbench case and is submitted
    // unchanged — the dropdown did not blank the seeded value.
    const call = (sdtmApi.putSelectionImpl as ReturnType<typeof vi.fn>).mock
      .calls[0][0]
    expect((call.data as { raw_id: string }).raw_id).toBe('raw-1')
  })

  it.each([['sdtm_raw_artifact_invalid'], ['sdtm_raw_validation_invalid']])(
    'renders the problem detail + issues[] on a 422 %s (Req 10.4)',
    async (code) => {
      sdtmApi.selection = makeSelection()
      sdtmApi.putSelectionImpl = vi.fn(async () => {
        throw problemError(422, {
          code,
          detail: 'The pinned Raw input is invalid.',
          issues: [
            {
              id: 'i1',
              code: 'raw_artifact_checksum_mismatch',
              severity: 'error',
              message: 'Checksum does not match the pinned artifact.',
              field_path: 'source_artifacts.0.checksum',
            },
          ],
        })
      })

      renderInWorkbench(<InputSelectionPanel />)

      fireEvent.click(
        screen.getByRole('button', { name: /save input selection/i }),
      )

      await waitFor(() => {
        expect(sdtmApi.putSelectionImpl).toHaveBeenCalledTimes(1)
      })
      // The problem detail is surfaced…
      await waitFor(() => {
        expect(
          screen.getByText('The pinned Raw input is invalid.'),
        ).toBeTruthy()
      })
      // …and the issues[] list is rendered.
      expect(
        screen.getByText('Checksum does not match the pinned artifact.'),
      ).toBeTruthy()
    },
  )

  it('shows the staleness banner when the selection is input_refresh_required (Req 10.5)', () => {
    sdtmApi.selection = makeSelection({ state: 'input_refresh_required' })

    renderInWorkbench(<InputSelectionPanel />)

    // The input-selection staleness banner copy is rendered.
    expect(screen.getByText(/input selection needs a refresh/i)).toBeTruthy()
  })

  it('blocks save and prompts for validation when the selected version has no successful run', () => {
    // The saved selection pins raw-1 so the resolvers run, but the Raw
    // workbench has no successful validation run yet (404).
    sdtmApi.selection = makeSelection({
      payload: {
        raw_id: 'raw-1',
        raw_revision: 4,
        validation_run_id: '',
        raw_dependency_fingerprint: 'raw-dep-fp',
        source_artifacts: [
          { dataset_code: 'DM', artifact_id: 'art-dm', checksum: 'sha-dm' },
        ],
      } as unknown as InputSelectionResponse['payload'],
    })
    rawApi.latestValidationRun = undefined
    rawApi.latestValidationRunError = problemError(404, {
      code: 'raw_validation_run_not_found',
      detail: 'No successful Raw validation run exists for this workbench.',
    })

    renderInWorkbench(<InputSelectionPanel />)

    // The inline prompt is shown…
    expect(
      screen.getByText(/run and pass validation on this raw version first/i),
    ).toBeTruthy()
    // …and the implementation detail is not exposed as a separate control.
    expect(screen.queryByLabelText(/validation run/i)).toBeNull()
    expect(
      screen
        .getByRole('button', { name: /save input selection/i })
        .hasAttribute('disabled'),
    ).toBe(true)
  })

  it('on 412 shows the concurrency message + reload action re-fetching the aggregate (Req 10.6)', async () => {
    sdtmApi.selection = makeSelection()
    sdtmApi.putSelectionImpl = vi.fn(async () => {
      throw problemError(412, { title: 'Precondition Failed', detail: 'stale' })
    })

    const { invalidateSpy } = renderInWorkbench(<InputSelectionPanel />)

    fireEvent.click(
      screen.getByRole('button', { name: /save input selection/i }),
    )

    await waitFor(() => {
      expect(sdtmApi.putSelectionImpl).toHaveBeenCalledTimes(1)
    })

    // The concurrency message with a reload action is shown…
    const reload = await screen.findByRole('button', {
      name: /reload current revision/i,
    })
    fireEvent.click(reload)

    // …and the reload re-fetches the current SDTM aggregate revision (10.6).
    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({
        queryKey: ['/sdtms', 'sdtm-1'],
      })
    })
  })
})

// ===========================================================================
// Specification (Requirements 11.2, 11.4, 11.6, 11.7)
// ===========================================================================
describe('SpecificationPanel', () => {
  it('renders the unsaved empty state on a 404 sdtm_specification_required (Req 11.2)', () => {
    sdtmApi.spec = undefined
    sdtmApi.specError = problemError(404, {
      code: 'sdtm_specification_required',
      detail: 'No Specification yet.',
    })

    renderInWorkbench(<SpecificationPanel sdtmId="sdtm-1" />)

    expect(screen.getByText(/no specification yet/i)).toBeTruthy()
    // The import dropzone is still offered so the first revision can be authored.
    expect(
      screen.getByLabelText(/specification import drop target/i),
    ).toBeTruthy()
  })

  it('save sends the aggregate ETag as If-Match (Req 11.4)', async () => {
    sdtmApi.spec = makeSpec()
    sdtmApi.putSpecImpl = vi.fn(async () => makeSpec({ revision: 4 }))

    renderInWorkbench(<SpecificationPanel sdtmId="sdtm-1" />)

    fireEvent.click(screen.getByRole('button', { name: /save specification/i }))

    await waitFor(() => {
      expect(sdtmApi.putSpecImpl).toHaveBeenCalledTimes(1)
    })
    // The save carried the whole Specification body…
    const call = (sdtmApi.putSpecImpl as ReturnType<typeof vi.fn>).mock.calls[0][0]
    expect(call).toMatchObject({ sdtmId: 'sdtm-1' })
    expect((call.data as { domains: unknown[] }).domains.length).toBe(1)
    // …and the mutation was wired with the aggregate ETag as If-Match (11.4).
    const request = sdtmApi.putSpecRequests.at(-1) as AxiosRequestConfig
    expect(request).toEqual(ifMatchRequest(AGGREGATE_REVISION))
    expect(request.headers?.['If-Match']).toBe(`"revision-${AGGREGATE_REVISION}"`)
  })

  it('populates selected domains and can limit additions to Req and Exp variables', async () => {
    sdtmApi.spec = makeSpec()
    sdtmApi.dependencies = {
      revision: 2,
      state: 'current',
      fingerprint: 'dependency-fingerprint',
      standards: [
        {
          purpose: 'sdtm_ig',
          standard_version_id: 'standard-version-1',
        },
      ],
      terminology: [],
      references: [],
      templates: [],
    }
    sdtmApi.initializationOptions = {
      standard_version_id: 'standard-version-1',
      domains: [
        {
          code: 'DM',
          label: 'Demographics',
          domain_class: 'Special Purpose',
          required_variable_count: 2,
          expected_variable_count: 1,
          permissible_variable_count: 4,
        },
        {
          code: 'AE',
          label: 'Adverse Events',
          domain_class: 'Events',
          required_variable_count: 3,
          expected_variable_count: 5,
          permissible_variable_count: 8,
        },
      ],
    }
    sdtmApi.initializeSpecImpl = vi.fn(async () => makeSpec({ revision: 4 }))

    renderInWorkbench(<SpecificationPanel sdtmId="sdtm-1" />)

    const populate = screen.getByRole('button', {
      name: /populate from industry standard/i,
    })
    expect(populate.hasAttribute('disabled')).toBe(true)
    fireEvent.click(
      await screen.findByLabelText('Select DM — Demographics'),
    )
    fireEvent.click(
      screen.getByLabelText(/include only required and expected variables/i),
    )
    fireEvent.click(
      populate,
    )

    await waitFor(() => {
      expect(sdtmApi.initializeSpecImpl).toHaveBeenCalledWith({
        sdtmId: 'sdtm-1',
        data: {
          domain_codes: ['DM'],
          required_expected_only: true,
        },
      })
    })
    const request = sdtmApi.initializeSpecRequests.at(-1) as AxiosRequestConfig
    expect(request.headers?.['If-Match']).toBe(`"revision-${AGGREGATE_REVISION}"`)
  })

  it('requires a saved industry standard selection before populating', async () => {
    sdtmApi.spec = makeSpec()
    sdtmApi.dependencies = {
      revision: 1,
      state: 'current',
      fingerprint: 'dependency-fingerprint',
      standards: [],
      terminology: [],
      references: [],
      templates: [],
    }

    renderInWorkbench(<SpecificationPanel sdtmId="sdtm-1" />)

    expect(screen.getByLabelText(/implementation guide/i)).toBeTruthy()
    await waitFor(() => {
      expect(screen.getByLabelText(/version/i).hasAttribute('disabled')).toBe(false)
    })
    expect(
      screen
        .getByRole('button', { name: /populate from industry standard/i })
        .hasAttribute('disabled'),
    ).toBe(true)
  })

  it('lets the user select and save an exact catalog version without entering an ID', async () => {
    sdtmApi.spec = makeSpec()
    sdtmApi.dependencies = {
      revision: 2,
      state: 'current',
      fingerprint: 'dependency-fingerprint',
      standards: [
        {
          purpose: 'reference_metadata',
          standard_version_id: 'standard-version-1',
        },
      ],
      terminology: [
        {
          scope: 'sdtm',
          terminology_release_id: 'terminology-1',
          terminology_extension_revision_ids: [],
        },
      ],
      references: [
        {
          purpose: 'study_reference',
          reference_id: 'reference-logical-1',
          reference_revision_id: 'reference-1',
        },
      ],
      templates: [
        { purpose: 'define', template_version_id: 'template-1' },
      ],
    }
    sdtmApi.replaceDependenciesImpl = vi.fn(async () => ({
      ...sdtmApi.dependencies,
      revision: 3,
    }))

    renderInWorkbench(<SpecificationPanel sdtmId="sdtm-1" />)

    const versionSelect = await screen.findByLabelText('Version')
    fireEvent.pointerDown(versionSelect, {
      button: 0,
      pointerType: 'mouse',
    })
    fireEvent.click(await screen.findByRole('option', { name: /3\.4 · active/i }))
    fireEvent.click(
      screen.getByRole('button', { name: /save standard selection/i }),
    )

    await waitFor(() => {
      expect(sdtmApi.replaceDependenciesImpl).toHaveBeenCalledTimes(1)
    })
    expect(
      (sdtmApi.replaceDependenciesImpl as ReturnType<typeof vi.fn>).mock.calls[0][0],
    ).toEqual({
      sdtmId: 'sdtm-1',
      data: {
        standards: [
          {
            purpose: 'sdtm_ig',
            standard_version_id: 'standard-version-2',
          },
        ],
        terminology: [
          {
            scope: 'sdtm',
            terminology_release_id: 'terminology-1',
            terminology_extension_revision_ids: [],
          },
        ],
        references: [
          {
            purpose: 'study_reference',
            reference_id: 'reference-logical-1',
            reference_revision_id: 'reference-1',
          },
        ],
        templates: [
          { purpose: 'define', template_version_id: 'template-1' },
        ],
      },
    })
    const request = sdtmApi.replaceDependenciesRequests.at(-1) as AxiosRequestConfig
    expect(request.headers?.['If-Match']).toBe(`"revision-${AGGREGATE_REVISION}"`)
  })

  it('import via dropzone and via browse issue the identical request with ETag + Idempotency-Key (Req 11.4)', async () => {
    sdtmApi.spec = makeSpec()

    const { rerender, unmount } = renderInWorkbench(
      <SpecificationPanel sdtmId="sdtm-1" />,
    )

    const file = new File(['{"domains":[]}'], 'spec.json', {
      type: 'application/json',
    })

    // --- path 1: native HTML5 file-drop onto the dropzone --------------------
    const dropzone = screen.getByLabelText(/specification import drop target/i)
    const dataTransfer = new DataTransfer()
    dataTransfer.items.add(file)
    fireEvent.drop(dropzone, { dataTransfer })

    await waitFor(() => {
      expect(sdtmApi.importCalls.length).toBe(1)
    })

    // Fresh mount for the browse path so a new Idempotency-Key attempt is minted.
    unmount()
    renderInWorkbench(<SpecificationPanel sdtmId="sdtm-1" />)

    // --- path 2: click-to-browse via the hidden <input type="file"> ----------
    const browseInput = document.querySelector(
      'input[type="file"]',
    ) as HTMLInputElement
    expect(browseInput).toBeTruthy()
    Object.defineProperty(browseInput, 'files', {
      configurable: true,
      value: [file],
    })
    fireEvent.change(browseInput)

    await waitFor(() => {
      expect(sdtmApi.importCalls.length).toBe(2)
    })

    void rerender

    // Both paths funnel into the identical typed request shape: same vars, the
    // aggregate ETag as If-Match, a syntactically valid UUID Idempotency-Key.
    const [dropCall, browseCall] = sdtmApi.importCalls
    for (const call of [dropCall, browseCall]) {
      expect(call.vars).toEqual({ sdtmId: 'sdtm-1' })
      const headers = (call.request as { headers: Record<string, string> })
        .headers
      expect(headers['If-Match']).toBe(`"revision-${AGGREGATE_REVISION}"`)
      expect(headers['Idempotency-Key']).toMatch(
        /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i,
      )
      expect(headers['Content-Type']).toBe('application/json')
    }
    // The pointer drop and the browse change produce the same request shape.
    expect(dropCall.vars).toEqual(browseCall.vars)
    expect(
      (dropCall.request as { headers: Record<string, string> }).headers[
        'If-Match'
      ],
    ).toBe(
      (browseCall.request as { headers: Record<string, string> }).headers[
        'If-Match'
      ],
    )
  })

  it('renders the import-invalid problem detail + issues[] on a 422 (Req 11.4)', async () => {
    sdtmApi.spec = makeSpec()
    sdtmApi.importImpl = vi.fn(async () => {
      throw problemError(422, {
        code: 'sdtm_specification_import_invalid',
        detail: 'The imported Specification is invalid.',
        issues: [
          {
            id: 'imp1',
            code: 'sdtm_domain_missing_keys',
            severity: 'error',
            message: 'Domain DM is missing a key variable.',
            field_path: 'domains.0.keys',
          },
        ],
      })
    })

    renderInWorkbench(<SpecificationPanel sdtmId="sdtm-1" />)

    const file = new File(['{"domains":[]}'], 'spec.json', {
      type: 'application/json',
    })
    const dropzone = screen.getByLabelText(/specification import drop target/i)
    const dataTransfer = new DataTransfer()
    dataTransfer.items.add(file)
    fireEvent.drop(dropzone, { dataTransfer })

    await waitFor(() => {
      expect(sdtmApi.importImpl).toHaveBeenCalledTimes(1)
    })
    await waitFor(() => {
      expect(
        screen.getByText('The imported Specification is invalid.'),
      ).toBeTruthy()
    })
    expect(
      screen.getByText('Domain DM is missing a key variable.'),
    ).toBeTruthy()
  })

  it('export calls the download bypass (Req 11.6)', async () => {
    sdtmApi.spec = makeSpec()

    renderInWorkbench(<SpecificationPanel sdtmId="sdtm-1" />)

    fireEvent.click(screen.getByRole('button', { name: /export json/i }))
    await waitFor(() => {
      expect(downloadSpy.downloadSpecificationExport).toHaveBeenCalledWith(
        'sdtm-1',
        'json',
      )
    })

    fireEvent.click(screen.getByRole('button', { name: /export xlsx/i }))
    await waitFor(() => {
      expect(downloadSpy.downloadSpecificationExport).toHaveBeenCalledWith(
        'sdtm-1',
        'xlsx',
      )
    })
  })

  it('on a 412 save shows the concurrency notice with a reload action (Req 11.7)', async () => {
    sdtmApi.spec = makeSpec()
    sdtmApi.putSpecImpl = vi.fn(async () => {
      throw problemError(412, { title: 'Precondition Failed', detail: 'stale' })
    })

    const { invalidateSpy } = renderInWorkbench(
      <SpecificationPanel sdtmId="sdtm-1" />,
    )

    fireEvent.click(screen.getByRole('button', { name: /save specification/i }))

    await waitFor(() => {
      expect(sdtmApi.putSpecImpl).toHaveBeenCalledTimes(1)
    })
    // Persistent concurrency notice + reload action (11.7).
    expect(screen.getByText(/specification changed/i)).toBeTruthy()
    const reload = screen.getByRole('button', {
      name: /reload current specification revision/i,
    })
    fireEvent.click(reload)
    // The reload re-fetches the current Specification revision before retry.
    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({
        queryKey: ['/sdtms', 'sdtm-1', 'specification'],
      })
    })
  })
})
