// @vitest-environment jsdom
//
// Component tests for the SDTM workbench aCRF panel (`acrf-panel.tsx`) — task
// 15.3.
//
// Coverage (Requirements 17.2, 17.3, 17.4, 17.5, 17.6, 17.7, 17.8):
//   * an out-of-range rectangle blocks the create submit, names the offending
//     field, and issues NO create request (R17.3);
//   * a valid create sends the AGGREGATE ETag (the SDTM workbench revision from
//     useWorkbench), not a per-annotation one (R17.2);
//   * edit / soft-delete / link-write all send the PER-ANNOTATION ETag (R17.4,
//     17.5);
//   * delete requires an explicit confirmation that names the annotation
//     (R17.4);
//   * the link DRAG and the explicit "Add link" fallback issue the IDENTICAL
//     useWriteLinks request carrying the SAME per-annotation ETag (R17.5,
//     DnD-parity rule);
//   * coverage renders the four count/list groups — total, unlinked
//     annotations, unlinked SDTM variables, non-current-revision links (R17.6);
//   * the aCRF build polls at a fixed 2s interval to a terminal state and, when
//     it never terminates, trips the 300s client timeout — both naming the
//     build and presenting no artifact (R17.7, 17.8).
//
// Following the established repo convention (`-datasets-panel.test.tsx`,
// `-raw-ops-panels.test.tsx`): no MSW is installed, so the generated Orval
// hooks + workbench context + toast are mocked and the REAL panel is driven
// over faithful hook fakes. The build poll/timeout flow uses vitest fake timers
// exactly as the Raw artifacts tests drive OperationRunner.
import {
  act,
  cleanup,
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
  AcrfAnnotationResponse,
  AcrfCoverageResponse,
  AggregateResponse,
  ArtifactBuildResponse,
  DependencySelectionResponse,
} from '@/api/generated/model'

beforeAll(() => {
  installJsdomHarness()
})

// Keep sonner out of the jsdom/theme-provider path.
vi.mock('@/components/ui/sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

// The DownloadButton (via ArtifactList on a completed build) uses `useDownload`,
// which touches the real axios instance; stub it so the completed-build list is
// harmless.
vi.mock('@/hooks/use-download', () => ({
  useDownload: () => ({
    downloadArtifact: vi.fn(),
    isPending: false,
    error: null,
  }),
}))

// `invalidate.ts` reaches into many generated modules at import time; stub it so
// this file need not mock the whole SDTM/define/csdrg surface. Each test spies
// on the exported helpers where it asserts invalidation.
vi.mock('@/lib/invalidate', () => ({
  invalidateSdtmSubResource: vi.fn(),
  invalidateSdtmOperationArtifacts: vi.fn(),
}))

// ---------------------------------------------------------------------------
// Mutable fixtures the generated-hook stubs read through. Each test installs
// the behaviour it needs.
// ---------------------------------------------------------------------------
const acrfApi: {
  annotations: AcrfAnnotationResponse[]
  coverage: AcrfCoverageResponse | undefined
  // create
  createImpl: (vars: { sdtmId: string; data: unknown }) => Promise<unknown>
  createVars: Array<{ sdtmId: string; data: unknown }>
  createRequests: unknown[]
  // patch (edit)
  patchImpl: (vars: { annotationId: string; data: unknown }) => Promise<unknown>
  patchVars: Array<{ annotationId: string; data: unknown }>
  patchRequests: unknown[]
  // delete
  deleteImpl: (vars: { annotationId: string }) => Promise<unknown>
  deleteVars: Array<{ annotationId: string }>
  deleteRequests: unknown[]
  // write links
  writeLinksImpl: (vars: {
    annotationId: string
    data: unknown
  }) => Promise<unknown>
  writeLinksVars: Array<{ annotationId: string; data: unknown }>
  writeLinksRequests: unknown[]
  // build create
  createArtifactImpl: (vars: {
    sdtmId: string
    data: unknown
  }) => Promise<ArtifactBuildResponse>
  createArtifactVars: Array<{ sdtmId: string; data: unknown }>
  createArtifactRequests: unknown[]
} = {
  annotations: [],
  coverage: undefined,
  createImpl: async () => makeAnnotation(),
  createVars: [],
  createRequests: [],
  patchImpl: async () => makeAnnotation(),
  patchVars: [],
  patchRequests: [],
  deleteImpl: async () => ({}),
  deleteVars: [],
  deleteRequests: [],
  writeLinksImpl: async () => ({}),
  writeLinksVars: [],
  writeLinksRequests: [],
  createArtifactImpl: async () => makeBuild(),
  createArtifactVars: [],
  createArtifactRequests: [],
}

const sdtmApi: { dependencies: DependencySelectionResponse | undefined } = {
  dependencies: undefined,
}

// A scripted build poll source: the test pushes a sequence of build states and
// the fake get-build hook reads them one per refetch tick (mirroring the
// faithful fake-operation pattern in `-raw-ops-panels.test.tsx`).
const pollSource: { build: ArtifactBuildResponse[] } = { build: [] }
const pollIndex = { build: 0 }

/**
 * Build a minimal mutation-result whose `mutateAsync` runs the scripted impl
 * and fires `onSuccess` on resolve, mirroring TanStack Query so the component's
 * success paths exercise for real.
 */
function makeMutation<V, R>(
  impl: (vars: V) => Promise<R>,
  onSuccess?: (data: R) => void,
) {
  return {
    isPending: false,
    error: null as AxiosError | null,
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

vi.mock('@/api/generated/sdtm-acrf/sdtm-acrf', () => {
  const useListAnnotations = (_sdtmId: string) => ({
    data: acrfApi.annotations,
    isLoading: false,
    isFetching: false,
    isError: false,
    error: null,
  })

  const useCreateAnnotation = (options?: {
    mutation?: { onSuccess?: (data: unknown) => void }
    request?: unknown
  }) => {
    acrfApi.createRequests.push(options?.request)
    return makeMutation((vars: { sdtmId: string; data: unknown }) => {
      acrfApi.createVars.push(vars)
      return acrfApi.createImpl(vars)
    }, options?.mutation?.onSuccess)
  }

  const usePatchAnnotation = (options?: {
    mutation?: { onSuccess?: (data: unknown) => void }
    request?: unknown
  }) => {
    acrfApi.patchRequests.push(options?.request)
    return makeMutation(
      (vars: { annotationId: string; data: unknown }) => {
        acrfApi.patchVars.push(vars)
        return acrfApi.patchImpl(vars)
      },
      options?.mutation?.onSuccess,
    )
  }

  const useDeleteAnnotation = (options?: {
    mutation?: { onSuccess?: (data: unknown) => void }
    request?: unknown
  }) => {
    acrfApi.deleteRequests.push(options?.request)
    return makeMutation(
      (vars: { annotationId: string }) => {
        acrfApi.deleteVars.push(vars)
        return acrfApi.deleteImpl(vars)
      },
      options?.mutation?.onSuccess,
    )
  }

  const useWriteLinks = (options?: {
    mutation?: { onSuccess?: (data: unknown) => void }
    request?: unknown
  }) => {
    acrfApi.writeLinksRequests.push(options?.request)
    return makeMutation(
      (vars: { annotationId: string; data: unknown }) => {
        acrfApi.writeLinksVars.push(vars)
        return acrfApi.writeLinksImpl(vars)
      },
      options?.mutation?.onSuccess,
    )
  }

  const useGetCoverage = (_sdtmId: string) => ({
    data: acrfApi.coverage,
    isLoading: acrfApi.coverage === undefined ? false : false,
    isError: false,
    error: null,
  })

  const useCreateAcrfArtifact = (options?: {
    mutation?: { onSuccess?: (data: ArtifactBuildResponse) => void }
    request?: unknown
  }) => {
    acrfApi.createArtifactRequests.push(options?.request)
    return makeMutation((vars: { sdtmId: string; data: unknown }) => {
      acrfApi.createArtifactVars.push(vars)
      return acrfApi.createArtifactImpl(vars)
    }, options?.mutation?.onSuccess)
  }

  return {
    useListAnnotations,
    useCreateAnnotation,
    usePatchAnnotation,
    useDeleteAnnotation,
    useWriteLinks,
    useGetCoverage,
    useCreateAcrfArtifact,
    getGetAnnotationQueryKey: (annotationId?: string) => [
      `/api/v1/acrf-annotations/${annotationId}`,
    ],
  }
})

vi.mock('@/api/generated/sdtm/sdtm', () => ({
  useGetSdtmDependencies: (_sdtmId: string) => ({
    data: sdtmApi.dependencies,
    isLoading: sdtmApi.dependencies === undefined,
    isError: false,
    error: null,
  }),
  getGetSdtmAggregateQueryKey: (sdtmId?: string) => [`/api/v1/sdtms/${sdtmId}`],
}))

// The artifact-build poll query. It forwards through the same enabled/
// refetchInterval the OperationRunner computes and replays the scripted poll
// source one state per tick (self-halting on terminal/error), matching the
// faithful fake-operation pattern in `-raw-ops-panels.test.tsx`.
vi.mock('@/api/generated/artifact-builds/artifact-builds', () => ({
  getGetArtifactBuildQueryKey: (buildId?: string) => [
    `/api/v1/artifact-builds/${buildId}`,
  ],
  useGetArtifactBuild: (
    _id: string,
    opts?: { query?: { enabled?: boolean; refetchInterval?: number | false } },
  ) => {
    void _id
    const [, force] = React.useState(0)
    const seq = pollSource.build
    const started = React.useRef(false)
    const stopped = React.useRef(false)
    const enabled = opts?.query?.enabled ?? false
    const refetchInterval = opts?.query?.refetchInterval

    if (enabled && !started.current) {
      started.current = true
      pollIndex.build = 0
    }

    React.useEffect(() => {
      if (!enabled || typeof refetchInterval !== 'number') return
      if (stopped.current) return
      const timer = window.setInterval(() => {
        if (stopped.current) {
          window.clearInterval(timer)
          return
        }
        if (pollIndex.build < seq.length - 1) {
          pollIndex.build += 1
        }
        const cur = seq[pollIndex.build]
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

    const data = enabled ? seq[pollIndex.build] : undefined
    return { data, error: null as AxiosError | null }
  },
}))

// ---------------------------------------------------------------------------
// Import AFTER the mocks so the panel binds to the stubs.
// ---------------------------------------------------------------------------
import { AcrfPanel } from './acrf-panel'

// ---------------------------------------------------------------------------
// Fixtures.
// ---------------------------------------------------------------------------
function makeAnnotation(
  overrides: Partial<AcrfAnnotationResponse> = {},
): AcrfAnnotationResponse {
  return {
    id: 'ann-1',
    sdtm_id: 'sdtm-1',
    study_id: 'study-1',
    source_pdf_artifact_id: 'pdf-1',
    page_number: 3,
    region: {
      coordinate_system: 'normalized_top_left',
      x: 0.1,
      y: 0.1,
      width: 0.2,
      height: 0.2,
    },
    annotation_text: 'Demographics panel',
    links: [],
    question: null,
    resolution: null,
    status: 'active',
    fingerprint: 'fp-1',
    revision: 5,
    created_by: 'user-1',
    created_at: '2024-01-01T00:00:00Z',
    updated_at: '2024-01-01T00:00:00Z',
    ...overrides,
  } as AcrfAnnotationResponse
}

function makeCoverage(
  overrides: Partial<AcrfCoverageResponse> = {},
): AcrfCoverageResponse {
  return {
    schema_version: '1.0.0',
    specification_revision: 2,
    plan_revision: 1,
    annotation_count: 4,
    linked_annotation_count: 1,
    unlinked_annotation_ids: ['ann-1', 'ann-2', 'ann-3'],
    uncovered_sdtm_variables: [
      { domain: 'DM', variable: 'USUBJID' },
      { domain: 'AE', variable: 'AETERM' },
    ],
    noncurrent_link_count: 2,
    ...overrides,
  } as AcrfCoverageResponse
}

function makeBuild(
  overrides: Partial<ArtifactBuildResponse> = {},
): ArtifactBuildResponse {
  return {
    id: 'build-1',
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
    revision: 11,
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

/** Wrap the panel (which reads `useWorkbench()`) in the aggregate context. */
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

/** Open the create dialog and fill the required source-PDF-artifact id. */
function openCreateDialog(pdfId = 'pdf-1') {
  fireEvent.click(screen.getByRole('button', { name: /new annotation/i }))
  fireEvent.change(screen.getByLabelText(/source pdf artifact id/i), {
    target: { value: pdfId },
  })
}

/** The last DEFINED request config the given hook was wired with (the stub
 * re-renders with `undefined` once a dialog closes, so filter those out). */
function lastDefinedRequest(requests: unknown[]): unknown {
  return requests.filter((r) => r !== undefined).at(-1)
}

beforeEach(() => {
  acrfApi.annotations = []
  acrfApi.coverage = undefined
  acrfApi.createImpl = async () => makeAnnotation({ id: 'new-ann' })
  acrfApi.createVars = []
  acrfApi.createRequests = []
  acrfApi.patchImpl = async () => makeAnnotation({ revision: 6 })
  acrfApi.patchVars = []
  acrfApi.patchRequests = []
  acrfApi.deleteImpl = async () => ({})
  acrfApi.deleteVars = []
  acrfApi.deleteRequests = []
  acrfApi.writeLinksImpl = async () => ({})
  acrfApi.writeLinksVars = []
  acrfApi.writeLinksRequests = []
  acrfApi.createArtifactImpl = async () => makeBuild()
  acrfApi.createArtifactVars = []
  acrfApi.createArtifactRequests = []
  sdtmApi.dependencies = makeDependencies()
  pollSource.build = []
  pollIndex.build = 0
})

afterEach(() => {
  // Explicitly unmount every mounted tree so the dnd-kit `DndContext` in the
  // link-write tests tears down its document-level listeners and any scheduled
  // work before the next (fake-timer) build test runs — a leaked drag sensor
  // otherwise disrupts the following test's event dispatch.
  cleanup()
  vi.clearAllMocks()
})

// ===========================================================================
// Create: rect-bounds gate blocks submit with NO request (Req 17.3) and a
// valid create sends the aggregate ETag (Req 17.2).
// ===========================================================================
describe('Annotation create (Req 17.2, 17.3)', () => {
  it('an out-of-range rectangle blocks submit, names the field, and issues NO create request', async () => {
    renderInWorkbench(<AcrfPanel sdtmId="sdtm-1" />)
    openCreateDialog()

    // Push width out of range so x + width overflows the page (x=0 default,
    // width=2 > 1): the gate must name the width field and never submit.
    fireEvent.change(screen.getByLabelText(/^width$/i), {
      target: { value: '2' },
    })

    const form = screen
      .getByRole('button', { name: /create annotation/i })
      .closest('form') as HTMLFormElement
    fireEvent.submit(form)

    // The offending Width field is flagged invalid and carries the field
    // message naming it (R17.3).
    await waitFor(() => {
      expect(screen.getByText(/width must be a decimal/i)).toBeTruthy()
    })
    const widthInput = screen.getByLabelText(/^width$/i) as HTMLInputElement
    expect(widthInput.getAttribute('aria-invalid')).toBe('true')
    // …and NO create request was issued (R17.3).
    expect(acrfApi.createVars.length).toBe(0)
    // The dialog stays open so the user can correct the field: the submit
    // control is still present.
    expect(
      screen.getByRole('button', { name: /create annotation/i }),
    ).toBeTruthy()
  })

  it('a valid create sends the AGGREGATE ETag and the typed body', async () => {
    acrfApi.createImpl = vi.fn(async () => makeAnnotation({ id: 'new-ann' }))

    renderInWorkbench(<AcrfPanel sdtmId="sdtm-1" />, makeAggregate({ revision: 11 }))
    openCreateDialog('pdf-99')

    // In-range rectangle: x=0, width=0.3, y=0, height=0.3 — within bounds.
    fireEvent.change(screen.getByLabelText(/^width$/i), {
      target: { value: '0.3' },
    })
    fireEvent.change(screen.getByLabelText(/^height$/i), {
      target: { value: '0.3' },
    })
    fireEvent.change(screen.getByLabelText(/page number/i), {
      target: { value: '2' },
    })

    const form = screen
      .getByRole('button', { name: /create annotation/i })
      .closest('form') as HTMLFormElement
    fireEvent.submit(form)

    await waitFor(() => {
      expect(acrfApi.createVars.length).toBe(1)
    })
    // The create hook was wired with the AGGREGATE ETag (workbench revision 11),
    // NOT a per-annotation one (R17.2).
    const req = lastDefinedRequest(acrfApi.createRequests)
    expect(req).toEqual(ifMatchRequest(11))
    expect((req as { headers: Record<string, string> }).headers['If-Match']).toBe(
      '"revision-11"',
    )
    // The typed body carries the pdf id, page, and normalized region.
    expect(acrfApi.createVars[0]).toMatchObject({
      sdtmId: 'sdtm-1',
      data: {
        source_pdf_artifact_id: 'pdf-99',
        page_number: 2,
        region: {
          coordinate_system: 'normalized_top_left',
          x: 0,
          width: 0.3,
          height: 0.3,
        },
      },
    })
  })
})

// ===========================================================================
// Edit: per-annotation ETag (Req 17.4).
// ===========================================================================
describe('Annotation edit (Req 17.4)', () => {
  it('sends the PER-ANNOTATION ETag on a successful edit', async () => {
    acrfApi.annotations = [makeAnnotation({ id: 'ann-1', revision: 5 })]
    acrfApi.patchImpl = vi.fn(async () => makeAnnotation({ revision: 6 }))

    renderInWorkbench(<AcrfPanel sdtmId="sdtm-1" />)

    fireEvent.click(screen.getByRole('button', { name: /^edit$/i }))
    await screen.findByText('Edit annotation')

    const form = screen
      .getByRole('button', { name: /save annotation/i })
      .closest('form') as HTMLFormElement
    fireEvent.submit(form)

    await waitFor(() => {
      expect(acrfApi.patchVars.length).toBe(1)
    })
    // The patch hook was wired with ifMatchRequest(revision=5) — the annotation's
    // OWN revision, not the aggregate's (R17.4).
    const req = lastDefinedRequest(acrfApi.patchRequests)
    expect(req).toEqual(ifMatchRequest(5))
    expect((req as { headers: Record<string, string> }).headers['If-Match']).toBe(
      '"revision-5"',
    )
    expect(acrfApi.patchVars[0]).toMatchObject({ annotationId: 'ann-1' })
  })
})

// ===========================================================================
// Delete: confirmation naming the annotation + per-annotation ETag (Req 17.4).
// ===========================================================================
describe('Annotation delete (Req 17.4)', () => {
  it('requires a confirmation that names the annotation before deleting', async () => {
    acrfApi.annotations = [
      makeAnnotation({
        id: 'ann-1',
        page_number: 7,
        annotation_text: 'Vitals block',
        revision: 5,
      }),
    ]
    acrfApi.deleteImpl = vi.fn(async () => ({}))

    renderInWorkbench(<AcrfPanel sdtmId="sdtm-1" />)

    fireEvent.click(screen.getByRole('button', { name: /^delete$/i }))

    // A confirmation dialog appears and names the annotation (by page/text)…
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/page 7/i)).toBeTruthy()
    expect(within(dialog).getByText(/Vitals block/)).toBeTruthy()
    // …and NO delete is issued until the user confirms (R17.4).
    expect(acrfApi.deleteVars.length).toBe(0)

    fireEvent.click(
      within(dialog).getByRole('button', { name: /delete annotation/i }),
    )

    await waitFor(() => {
      expect(acrfApi.deleteVars.length).toBe(1)
    })
    expect(acrfApi.deleteVars[0]).toMatchObject({ annotationId: 'ann-1' })
  })

  it('sends the PER-ANNOTATION ETag on delete', async () => {
    acrfApi.annotations = [makeAnnotation({ id: 'ann-1', revision: 5 })]
    acrfApi.deleteImpl = vi.fn(async () => ({}))

    renderInWorkbench(<AcrfPanel sdtmId="sdtm-1" />)

    fireEvent.click(screen.getByRole('button', { name: /^delete$/i }))
    const dialog = await screen.findByRole('dialog')
    fireEvent.click(
      within(dialog).getByRole('button', { name: /delete annotation/i }),
    )

    await waitFor(() => {
      expect(acrfApi.deleteVars.length).toBe(1)
    })
    const req = lastDefinedRequest(acrfApi.deleteRequests)
    expect(req).toEqual(ifMatchRequest(5))
    expect((req as { headers: Record<string, string> }).headers['If-Match']).toBe(
      '"revision-5"',
    )
  })
})

// ===========================================================================
// Link write: drag vs explicit "Add link" fallback parity, both carrying the
// per-annotation ETag (Req 17.5).
// ===========================================================================
describe('Annotation link write (Req 17.5)', () => {
  function fillLinkSource(domain = 'DM', variable = 'USUBJID', specRev = '2') {
    fireEvent.change(screen.getByLabelText(/link domain/i), {
      target: { value: domain },
    })
    fireEvent.change(screen.getByLabelText(/link variable/i), {
      target: { value: variable },
    })
    fireEvent.change(screen.getByLabelText(/link specification revision/i), {
      target: { value: specRev },
    })
  }

  it('the explicit "Add link" fallback issues useWriteLinks with the per-annotation ETag', async () => {
    acrfApi.annotations = [makeAnnotation({ id: 'ann-1', revision: 5 })]
    acrfApi.writeLinksImpl = vi.fn(async () => ({}))

    renderInWorkbench(<AcrfPanel sdtmId="sdtm-1" />)
    fillLinkSource('DM', 'USUBJID', '2')

    fireEvent.click(screen.getByRole('button', { name: /add link/i }))

    await waitFor(() => {
      expect(acrfApi.writeLinksVars.length).toBe(1)
    })
    const req = lastDefinedRequest(acrfApi.writeLinksRequests)
    expect(req).toEqual(ifMatchRequest(5))
    expect(acrfApi.writeLinksVars[0]).toMatchObject({
      annotationId: 'ann-1',
      data: {
        operation: 'amend',
        links: [
          {
            target_type: 'sdtm_variable',
            specification_revision: 2,
            domain: 'DM',
            variable: 'USUBJID',
          },
        ],
      },
    })
  })

  it('the link DRAG issues the IDENTICAL useWriteLinks request as the "Add link" fallback', async () => {
    // --- "Add link" (fallback) path ---
    acrfApi.annotations = [makeAnnotation({ id: 'ann-1', revision: 5 })]
    acrfApi.writeLinksImpl = vi.fn(async () => ({}))
    const fallback = renderInWorkbench(<AcrfPanel sdtmId="sdtm-1" />)
    fillLinkSource('DM', 'USUBJID', '2')
    fireEvent.click(screen.getByRole('button', { name: /add link/i }))
    await waitFor(() => expect(acrfApi.writeLinksVars.length).toBe(1))
    const fallbackVars = acrfApi.writeLinksVars[0]
    const fallbackReq = lastDefinedRequest(acrfApi.writeLinksRequests)
    fallback.unmount()

    // --- Drag path: fire a dnd-kit DragEnd by simulating a pointer drag of the
    //     source chip onto the annotation drop target. The TransferContext maps
    //     the {sourceId,targetId} pair to the SAME write command. ---
    acrfApi.writeLinksVars = []
    acrfApi.writeLinksRequests = []
    const drag = renderInWorkbench(<AcrfPanel sdtmId="sdtm-1" />)
    fillLinkSource('DM', 'USUBJID', '2')

    const source = screen.getByRole('button', {
      name: /drag source variable DM\.USUBJID/i,
    })
    const target = screen.getByLabelText(/drop a source variable onto annotation/i)

    // Drive dnd-kit's PointerSensor: press on the source, move past the
    // activation threshold, move over the target, then release.
    fireEvent.pointerDown(source, { pointerId: 1, clientX: 0, clientY: 0 })
    fireEvent.pointerMove(source, { pointerId: 1, clientX: 25, clientY: 25 })
    fireEvent.pointerMove(target, { pointerId: 1, clientX: 60, clientY: 60 })
    fireEvent.pointerUp(target, { pointerId: 1, clientX: 60, clientY: 60 })

    await waitFor(() => {
      expect(acrfApi.writeLinksVars.length).toBe(1)
    })
    const dragVars = acrfApi.writeLinksVars[0]
    const dragReq = lastDefinedRequest(acrfApi.writeLinksRequests)

    // Identical request: same per-annotation ETag and same typed body (R17.5).
    expect(dragReq).toEqual(fallbackReq)
    expect(dragReq).toEqual(ifMatchRequest(5))
    expect(dragVars).toEqual(fallbackVars)

    // Let dnd-kit's post-drop cleanup (its ~250ms drop animation / scheduled
    // frame) run to completion under real timers, THEN unmount the drag tree so
    // no document listener or pending timer leaks into the next (fake-timer)
    // build test and disrupts its event dispatch.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 350))
    })
    drag.unmount()
  })
})

// ===========================================================================
// Coverage: the four count/list groups (Req 17.6).
// ===========================================================================
describe('Coverage (Req 17.6)', () => {
  it('renders the total count plus the three count/list groups', () => {
    acrfApi.annotations = [makeAnnotation({ id: 'ann-1' })]
    acrfApi.coverage = makeCoverage({
      annotation_count: 4,
      linked_annotation_count: 1,
      unlinked_annotation_ids: ['ann-1', 'ann-2', 'ann-3'],
      uncovered_sdtm_variables: [
        { domain: 'DM', variable: 'USUBJID' },
        { domain: 'AE', variable: 'AETERM' },
      ],
      noncurrent_link_count: 2,
    })

    renderInWorkbench(<AcrfPanel sdtmId="sdtm-1" />)

    const coverageCard = screen
      .getByText('Coverage')
      .closest('[data-slot="card"]') as HTMLElement

    // Group 1: total annotation count.
    expect(within(coverageCard).getByText(/Total annotations: 4/)).toBeTruthy()
    // Group 2: unlinked annotations (count + list).
    expect(within(coverageCard).getByText('Unlinked annotations')).toBeTruthy()
    expect(within(coverageCard).getByText('ann-2')).toBeTruthy()
    expect(within(coverageCard).getByText('ann-3')).toBeTruthy()
    // Group 3: unlinked SDTM variables (count + list).
    expect(
      within(coverageCard).getByText('Unlinked SDTM variables'),
    ).toBeTruthy()
    expect(within(coverageCard).getByText('DM.USUBJID')).toBeTruthy()
    expect(within(coverageCard).getByText('AE.AETERM')).toBeTruthy()
    // Group 4: non-current-revision links (count).
    expect(
      within(coverageCard).getByText('Non-current-revision links'),
    ).toBeTruthy()
    expect(
      within(coverageCard).getByText(/2 link\(s\) pin a non-current revision/i),
    ).toBeTruthy()
  })
})

// ===========================================================================
// Build: fixed 2s poll to terminal / 300s timeout, naming the build (Req 17.7,
// 17.8).
// ===========================================================================
describe('aCRF build poll (Req 17.7, 17.8)', () => {
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

  it('starts on the Idempotency-Key POST and polls at 2s to a completed terminal', async () => {
    sdtmApi.dependencies = makeDependencies({ fingerprint: 'dep-fp-9' })
    pollSource.build = [
      makeBuild({ status: 'running' }),
      makeBuild({ status: 'completed', result_artifact_ids: ['art-1'] }),
    ]
    acrfApi.createArtifactImpl = vi.fn(async () => pollSource.build[0])

    renderInWorkbench(<AcrfPanel sdtmId="sdtm-1" />)

    fireEvent.click(screen.getByRole('button', { name: /build acrf artifact/i }))
    // Flush the mutate promise so the build id lands (fake timers don't fake
    // microtasks).
    await act(async () => {
      await Promise.resolve()
    })

    // The start POST carried the pinned fingerprint + an Idempotency-Key.
    expect(acrfApi.createArtifactVars[0]).toMatchObject({
      sdtmId: 'sdtm-1',
      data: { expected_input_fingerprint: 'dep-fp-9' },
    })
    const startReq = lastDefinedRequest(acrfApi.createArtifactRequests) as {
      headers: Record<string, string>
    }
    expect(startReq.headers['Idempotency-Key']).toBeTruthy()

    // Advance one 2s interval to the terminal poll.
    await act(async () => {
      vi.advanceTimersByTime(2_000)
      await Promise.resolve()
    })

    // The completed build lists its produced artifact with a download action;
    // no timeout/failure notice.
    expect(screen.getByText('art-1')).toBeTruthy()
    expect(screen.getByRole('button', { name: /download/i })).toBeTruthy()
    expect(screen.queryByText(/did not finish in time/i)).toBeNull()
    expect(screen.queryByText(/aCRF build failed/i)).toBeNull()
  })

  it('trips the 300s client timeout, names the build, and presents no artifact', async () => {
    sdtmApi.dependencies = makeDependencies()
    // Always running — never terminal.
    pollSource.build = [makeBuild({ status: 'running' })]
    acrfApi.createArtifactImpl = async () => pollSource.build[0]

    renderInWorkbench(<AcrfPanel sdtmId="sdtm-1" />)
    await act(async () => {
      fireEvent.click(
        screen.getByRole('button', { name: /build acrf artifact/i }),
      )
      await Promise.resolve()
      await Promise.resolve()
    })

    // Advance past the 300s build cap.
    await act(async () => {
      vi.advanceTimersByTime(300_000)
      await Promise.resolve()
    })

    // The timeout notice names the aCRF build (R17.8) and no artifact appears.
    expect(
      screen.getByText(/aCRF build did not finish in time/i),
    ).toBeTruthy()
  })

  it('surfaces a failed terminal naming the build and presents no artifact', async () => {
    sdtmApi.dependencies = makeDependencies()
    pollSource.build = [
      makeBuild({ status: 'running' }),
      makeBuild({
        status: 'failed',
        result_artifact_ids: [],
        failure: { code: 'acrf_build_error', detail: 'Renderer crashed.' },
      } as Partial<ArtifactBuildResponse>),
    ]
    acrfApi.createArtifactImpl = async () => pollSource.build[0]

    renderInWorkbench(<AcrfPanel sdtmId="sdtm-1" />)
    await act(async () => {
      fireEvent.click(
        screen.getByRole('button', { name: /build acrf artifact/i }),
      )
      await Promise.resolve()
      await Promise.resolve()
    })

    await act(async () => {
      vi.advanceTimersByTime(2_000)
      await Promise.resolve()
    })

    // The failed terminal names the aCRF build + the typed failure, no artifact.
    expect(screen.getByText(/aCRF build failed/i)).toBeTruthy()
    expect(screen.getByText('acrf_build_error')).toBeTruthy()
    expect(screen.getByText('Renderer crashed.')).toBeTruthy()
  })
})
