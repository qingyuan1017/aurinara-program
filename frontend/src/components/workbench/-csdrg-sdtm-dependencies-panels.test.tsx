// @vitest-environment jsdom
//
// Component tests for the two SDTM task-17.3 panels:
//   * `csdrg-panel.tsx`              — nine narrative sections, validate, build.
//   * `sdtm-dependencies-panel.tsx`  — 422 issues / 412 refresh / banner.
//
// Coverage (Requirements 19.3, 19.4, 19.5, 20.3, 20.4, 20.5):
//   cSDRG: the nine CSDRG_SECTIONS render as editable fields that preserve the
//     user's typed content and are NEVER auto-populated — an un-authored
//     section stays empty (R19.3); validate surfaces an absent/whitespace-only
//     required section as an error-severity issue (R19.4); the cSDRG build
//     polls at the fixed 2s interval to a terminal state (R19.5).
//   SDTM dependencies: a 422 `dependency_selection_invalid` renders each
//     incompatibility (R20.3); a 412 shows the concurrency message and reloads
//     the current revision before retry (R20.4); a `dependency_refresh_required`
//     state shows the banner and disables the save control (R20.5).
//
// Following the repo convention (`-raw-ops-panels.test.tsx`,
// `-sdtm-validation-panel.test.tsx`): no MSW is installed, so the generated
// Orval hooks + study/toast/download/invalidate are mocked and the REAL panels
// are driven over faithful hook fakes. The build poll uses vitest fake timers
// exactly as the Raw/SDTM ops suites drive `OperationRunner`.
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
  CsdrgResponse,
  DependencySelectionResponse,
  SdtmCsdrgModel,
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
// real axios instance; stub it so a completed build's artifact list is inert.
vi.mock('@/hooks/use-download', () => ({
  useDownload: () => ({
    downloadArtifact: vi.fn(),
    isPending: false,
    error: null,
  }),
}))

// `invalidate.ts` reaches into many generated modules at import time; stub the
// two helpers the two panels use so this file need not mock the whole surface.
vi.mock('@/lib/invalidate', () => ({
  invalidateSdtmSubResource: vi.fn(),
  invalidateSdtmDependencies: vi.fn(),
  invalidateSdtmOperationArtifacts: vi.fn(),
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

const csdrgApi: {
  // GET cSDRG
  getCsdrg: GetState<CsdrgResponse>
  // initialize
  initializeImpl: (vars: { sdtmId: string; data: unknown }) => Promise<unknown>
  // put (save narrative)
  putImpl: (vars: { sdtmId: string; data: SdtmCsdrgModel }) => Promise<unknown>
  putVars: Array<{ sdtmId: string; data: SdtmCsdrgModel }>
  // validate (synchronous)
  validateImpl: (vars: { sdtmId: string }) => Promise<ValidationRunResponse>
  // create artifacts (202)
  createArtifactsImpl: (vars: {
    sdtmId: string
    data: unknown
  }) => Promise<ArtifactBuildResponse>
} = {
  getCsdrg: { data: undefined, error: null, isLoading: false, isError: false },
  initializeImpl: async () => ({}),
  putImpl: async () => ({}),
  putVars: [],
  validateImpl: async () => makeRun(),
  createArtifactsImpl: async () => makeBuild(),
}

const sdtmApi: {
  dependencies: DependencySelectionResponse | undefined
  replaceDependenciesImpl: (vars: {
    sdtmId: string
    data: unknown
  }) => Promise<unknown>
} = {
  dependencies: undefined,
  replaceDependenciesImpl: async () => ({}),
}

// A scripted build-poll source: the test pushes a sequence of build states and
// the fake get-build hook (below) reads them one per refetch tick.
const pollSource: { build: ArtifactBuildResponse[] } = { build: [] }
const pollIndex = { build: 0 }

/**
 * Build a minimal mutation-result whose `mutateAsync` runs the scripted impl
 * and fires `onSuccess` on resolve so the panel's success path (invalidation /
 * poll kickoff) exercises for real.
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

vi.mock('@/api/generated/sdtm-csdrg/sdtm-csdrg', () => {
  const useGetCsdrg = (sdtmId: string) => {
    void sdtmId
    return csdrgApi.getCsdrg
  }

  const useInitializeCsdrg = (options?: {
    mutation?: { onSuccess?: (data: unknown) => void }
    request?: unknown
  }) =>
    makeMutation(
      (vars: { sdtmId: string; data: unknown }) => csdrgApi.initializeImpl(vars),
      options?.mutation?.onSuccess,
    )

  const usePutCsdrg = (options?: {
    mutation?: { onSuccess?: (data: unknown) => void }
    request?: unknown
  }) =>
    makeMutation((vars: { sdtmId: string; data: SdtmCsdrgModel }) => {
      csdrgApi.putVars.push(vars)
      return csdrgApi.putImpl(vars)
    }, options?.mutation?.onSuccess)

  const useValidateCsdrg = (options?: {
    mutation?: { onSuccess?: (data: ValidationRunResponse) => void }
    request?: unknown
  }) =>
    makeMutation(
      (vars: { sdtmId: string }) => csdrgApi.validateImpl(vars),
      options?.mutation?.onSuccess,
    )

  const useCreateCsdrgArtifacts = (options?: {
    mutation?: { onSuccess?: (data: ArtifactBuildResponse) => void }
    request?: unknown
  }) =>
    makeMutation(
      (vars: { sdtmId: string; data: unknown }) =>
        csdrgApi.createArtifactsImpl(vars),
      options?.mutation?.onSuccess,
    )

  return {
    useGetCsdrg,
    useInitializeCsdrg,
    usePutCsdrg,
    useValidateCsdrg,
    useCreateCsdrgArtifacts,
    getGetCsdrgQueryKey: (sdtmId?: string) => [`/api/v1/sdtms/${sdtmId}/csdrg`],
  }
})

vi.mock('@/api/generated/sdtm/sdtm', () => {
  const useGetSdtmDependencies = (sdtmId: string) => ({
    data: sdtmApi.dependencies,
    error: null,
    isLoading: sdtmApi.dependencies === undefined,
    isError: false,
    queryKey: [`/api/v1/sdtms/${sdtmId}/dependencies`],
  })

  const useReplaceSdtmDependencies = (options?: {
    mutation?: { onSuccess?: (data: unknown) => void }
    request?: unknown
  }) =>
    makeMutation(
      (vars: { sdtmId: string; data: unknown }) =>
        sdtmApi.replaceDependenciesImpl(vars),
      options?.mutation?.onSuccess,
    )

  return {
    useGetSdtmDependencies,
    useReplaceSdtmDependencies,
    getGetSdtmAggregateQueryKey: (sdtmId?: string) => [`/api/v1/sdtms/${sdtmId}`],
    getGetSdtmDependenciesQueryKey: (sdtmId?: string) => [
      `/api/v1/sdtms/${sdtmId}/dependencies`,
    ],
  }
})

// The cSDRG build polls `useGetArtifactBuild`. Replay the scripted poll source
// one state per refetch interval, self-halting on terminal — the same faithful
// fake-operation pattern used by the Raw ops suite.
vi.mock('@/api/generated/artifact-builds/artifact-builds', () => ({
  getGetArtifactBuildQueryKey: (id?: string) => [`/api/v1/artifact-builds/${id}`],
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
// Import AFTER the mocks so the panels bind to the stubs.
// ---------------------------------------------------------------------------
import { CsdrgPanel, CSDRG_SECTIONS } from './csdrg-panel'
import { SdtmDependenciesPanel } from './sdtm-dependencies-panel'

// ---------------------------------------------------------------------------
// Fixtures.
// ---------------------------------------------------------------------------
function makeRun(
  overrides: Partial<ValidationRunResponse> = {},
): ValidationRunResponse {
  return {
    id: 'vr-1',
    study_id: 'study-1',
    owner_id: 'sdtm-1',
    status: 'passed',
    validator_name: 'csdrg-validator',
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

/**
 * A loaded cSDRG response. `payload` carries the typed authoring model the
 * panel edits; by default no narrative is authored so every required section
 * renders empty (never auto-populated).
 */
function makeCsdrg(
  modelOverrides: Partial<SdtmCsdrgModel> = {},
  responseOverrides: Partial<CsdrgResponse> = {},
): CsdrgResponse {
  const model: SdtmCsdrgModel = {
    schema_version: '1.0.0',
    title: 'Clinical Study Data Reviewer Guide',
    version: '1.0',
    specification_revision: 4,
    define_revision: 2,
    reconciliation_run_id: 'rr-1',
    output_artifact_ids: ['art-prev'],
    dataset_facts: [{ dataset: 'DM' }] as SdtmCsdrgModel['dataset_facts'],
    narrative_sections: [],
    ...modelOverrides,
  }
  return {
    id: 'csdrg-1',
    aggregate_id: 'sdtm-1',
    study_id: 'study-1',
    revision: 5,
    schema_version: '1.0.0',
    specification_revision: 4,
    define_revision: 2,
    reconciliation_run_id: 'rr-1',
    payload: model as unknown as CsdrgResponse['payload'],
    fingerprint: 'f'.repeat(64),
    created_by: 'user-1',
    created_at: '2024-01-01T00:00:00Z',
    ...responseOverrides,
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
  csdrgApi.getCsdrg = {
    data: undefined,
    error: null,
    isLoading: false,
    isError: false,
  }
  csdrgApi.initializeImpl = async () => ({})
  csdrgApi.putImpl = async () => ({})
  csdrgApi.putVars = []
  csdrgApi.validateImpl = async () => makeRun()
  csdrgApi.createArtifactsImpl = async () => makeBuild()
  sdtmApi.dependencies = undefined
  sdtmApi.replaceDependenciesImpl = async () => ({})
  pollSource.build = []
  pollIndex.build = 0
})

afterEach(() => {
  vi.clearAllMocks()
})

// ===========================================================================
// cSDRG — nine narrative sections (Req 19.3)
// ===========================================================================
describe('CsdrgPanel narrative sections (Req 19.3)', () => {
  it('renders exactly the nine required sections as editable fields', () => {
    csdrgApi.getCsdrg = {
      data: makeCsdrg(),
      error: null,
      isLoading: false,
      isError: false,
    }

    renderInWorkbench(<CsdrgPanel sdtmId="sdtm-1" />)

    // Nine section fields render, each labelled by its fixed heading and keyed
    // by its stable section id.
    expect(CSDRG_SECTIONS).toHaveLength(9)
    for (const section of CSDRG_SECTIONS) {
      const field = screen.getByLabelText(section.heading) as HTMLTextAreaElement
      expect(field).toBeTruthy()
      expect(field.getAttribute('data-section-id')).toBe(section.id)
    }
  })

  it('never auto-populates: an un-authored section stays empty', () => {
    // No narrative authored at all.
    csdrgApi.getCsdrg = {
      data: makeCsdrg({ narrative_sections: [] }),
      error: null,
      isLoading: false,
      isError: false,
    }

    renderInWorkbench(<CsdrgPanel sdtmId="sdtm-1" />)

    // Every one of the nine fields is empty (the panel infers nothing).
    for (const section of CSDRG_SECTIONS) {
      const field = screen.getByLabelText(section.heading) as HTMLTextAreaElement
      expect(field.value).toBe('')
      // The "Required — not authored" marker is shown for the empty field.
    }
    expect(
      screen.getAllByText('Required — not authored').length,
    ).toBe(CSDRG_SECTIONS.length)
  })

  it('preserves the user-authored content exactly and only seeds from saved paragraphs', async () => {
    const authored = CSDRG_SECTIONS[0]
    csdrgApi.getCsdrg = {
      data: makeCsdrg({
        narrative_sections: [
          {
            section_id: authored.id,
            heading: authored.heading,
            paragraphs: ['First paragraph.', 'Second paragraph.'],
          },
        ],
      }),
      error: null,
      isLoading: false,
      isError: false,
    }

    renderInWorkbench(<CsdrgPanel sdtmId="sdtm-1" />)

    // The authored section is seeded verbatim (paragraphs joined by a blank line).
    const first = screen.getByLabelText(authored.heading) as HTMLTextAreaElement
    expect(first.value).toBe('First paragraph.\n\nSecond paragraph.')

    // The other eight remain empty — no inference bled across sections.
    for (const section of CSDRG_SECTIONS.slice(1)) {
      const field = screen.getByLabelText(section.heading) as HTMLTextAreaElement
      expect(field.value).toBe('')
    }

    // Typing is preserved verbatim and round-trips into the saved model on save.
    const second = screen.getByLabelText(
      CSDRG_SECTIONS[1].heading,
    ) as HTMLTextAreaElement
    fireEvent.change(second, { target: { value: 'Freshly typed narrative.' } })
    expect(second.value).toBe('Freshly typed narrative.')

    fireEvent.click(screen.getByRole('button', { name: /save csdrg/i }))
    await waitFor(() => {
      expect(csdrgApi.putVars.length).toBe(1)
    })
    const saved = csdrgApi.putVars[0].data
    const savedSecond = (saved.narrative_sections ?? []).find(
      (s) => s.section_id === CSDRG_SECTIONS[1].id,
    )
    // The authored text is preserved verbatim as the section's paragraph.
    expect(savedSecond?.paragraphs).toEqual(['Freshly typed narrative.'])
    // The untouched first section preserves its original two paragraphs.
    const savedFirst = (saved.narrative_sections ?? []).find(
      (s) => s.section_id === authored.id,
    )
    expect(savedFirst?.paragraphs).toEqual([
      'First paragraph.',
      'Second paragraph.',
    ])
  })
})

// ===========================================================================
// cSDRG — validate surfaces whitespace-only sections as errors (Req 19.4)
// ===========================================================================
describe('CsdrgPanel validate (Req 19.4)', () => {
  it('surfaces an absent/whitespace-only required section as an error issue', async () => {
    // One section carries only whitespace paragraphs; the rest are absent. Both
    // must surface as error-severity issues (the backend run itself is clean).
    const whitespaceSection = CSDRG_SECTIONS[2]
    csdrgApi.getCsdrg = {
      data: makeCsdrg({
        narrative_sections: [
          {
            section_id: whitespaceSection.id,
            heading: whitespaceSection.heading,
            paragraphs: ['   ', '\t\n'],
          },
        ],
      }),
      error: null,
      isLoading: false,
      isError: false,
    }
    // Backend returns a clean synchronous run (no issues of its own).
    csdrgApi.validateImpl = async () =>
      makeRun({ status: 'passed', issues: [], error_count: 0 })

    renderInWorkbench(<CsdrgPanel sdtmId="sdtm-1" />)
    fireEvent.click(screen.getByRole('button', { name: /validate csdrg/i }))

    // The client-side check flags all nine (whitespace-only + the eight absent)
    // as error-severity issues.
    await waitFor(() => {
      expect(
        screen.getByText(
          `The required cSDRG narrative section "${whitespaceSection.heading}" is absent or contains only whitespace.`,
        ),
      ).toBeTruthy()
    })
    // The whitespace-only section is treated the same as an absent one.
    expect(
      screen.getByText(
        `The required cSDRG narrative section "${CSDRG_SECTIONS[0].heading}" is absent or contains only whitespace.`,
      ),
    ).toBeTruthy()

    // The validate result card recounts error severity to include the client
    // findings — all nine required sections are missing narrative here.
    const code = 'SDTM_CSDRG_REQUIRED_SECTION_MISSING'
    expect(screen.getAllByText(code).length).toBe(CSDRG_SECTIONS.length)
    // The run summary recounts a non-zero error count driven by the client
    // issues (surfaced on both the run-summary badge and the IssueList summary).
    expect(
      screen.getAllByText(`Error: ${CSDRG_SECTIONS.length}`).length,
    ).toBeGreaterThan(0)
  })

  it('reports no client section error once every section is authored', async () => {
    const authored = CSDRG_SECTIONS.map((section) => ({
      section_id: section.id,
      heading: section.heading,
      paragraphs: [`Authored ${section.heading}.`],
    }))
    csdrgApi.getCsdrg = {
      data: makeCsdrg({ narrative_sections: authored }),
      error: null,
      isLoading: false,
      isError: false,
    }
    csdrgApi.validateImpl = async () => makeRun({ status: 'passed', issues: [] })

    renderInWorkbench(<CsdrgPanel sdtmId="sdtm-1" />)
    fireEvent.click(screen.getByRole('button', { name: /validate csdrg/i }))

    // The run settles with no issues: the empty IssueList state renders and no
    // whitespace/absent client issue is synthesized.
    await screen.findByText(
      'All nine required narrative sections are authored and this validation run produced no issues.',
    )
    expect(screen.getByText('Error: 0')).toBeTruthy()
    expect(
      screen.queryByText(/is absent or contains only whitespace/i),
    ).toBeNull()
  })
})

// ===========================================================================
// cSDRG — build polls at 2s (Req 19.5)
// ===========================================================================
describe('CsdrgPanel build poll (Req 19.5)', () => {
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

  it('builds the cSDRG artifact and polls at a fixed 2s interval to a completed terminal', async () => {
    csdrgApi.getCsdrg = {
      data: makeCsdrg(),
      error: null,
      isLoading: false,
      isError: false,
    }
    pollSource.build = [
      makeBuild({ status: 'running' }),
      makeBuild({ status: 'completed', result_artifact_ids: ['art-csdrg-1'] }),
    ]
    csdrgApi.createArtifactsImpl = async () => pollSource.build[0]

    renderInWorkbench(<CsdrgPanel sdtmId="sdtm-1" />)

    fireEvent.click(screen.getByRole('button', { name: /build csdrg artifact/i }))
    await act(async () => {
      await Promise.resolve()
    })

    // The runner shows the polling state before any interval elapses.
    expect(screen.getByText(/running csdrg build/i)).toBeTruthy()

    // Advancing LESS than the 2s interval does not yet reach the terminal poll.
    await act(async () => {
      vi.advanceTimersByTime(1_000)
      await Promise.resolve()
    })
    expect(screen.getByText(/running csdrg build/i)).toBeTruthy()
    expect(screen.queryByRole('button', { name: /download/i })).toBeNull()

    // Completing the 2s interval reaches the completed terminal and lists the
    // produced artifact.
    await act(async () => {
      vi.advanceTimersByTime(1_000)
      await Promise.resolve()
    })

    expect(screen.getByRole('button', { name: /download/i })).toBeTruthy()
    expect(screen.queryByText(/running csdrg build/i)).toBeNull()
  })
})

// ===========================================================================
// SDTM Dependencies (Req 20.3, 20.4, 20.5)
// ===========================================================================
describe('SdtmDependenciesPanel invalid selection (Req 20.3)', () => {
  it('renders each incompatibility on a 422 dependency_selection_invalid', async () => {
    sdtmApi.dependencies = makeDependencies({ state: 'current' })
    sdtmApi.replaceDependenciesImpl = async () => {
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

    renderInWorkbench(<SdtmDependenciesPanel sdtmId="sdtm-1" />)

    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: /replace selection/i }),
      ).toBeTruthy()
    })
    fireEvent.click(screen.getByRole('button', { name: /replace selection/i }))

    await waitFor(() => {
      expect(
        screen.getByText('Terminology release is not compatible.'),
      ).toBeTruthy()
    })
    expect(screen.getByText('A required standard is unselected.')).toBeTruthy()
    expect(screen.getByText(/Pin a compatible release\./)).toBeTruthy()
    expect(screen.getByText('The selection has incompatibilities.')).toBeTruthy()
  })
})

describe('SdtmDependenciesPanel concurrency (Req 20.4)', () => {
  it('shows the concurrency message and reloads the current revision on a 412', async () => {
    sdtmApi.dependencies = makeDependencies({ state: 'current', revision: 3 })
    sdtmApi.replaceDependenciesImpl = async () => {
      throw problemError(412, { title: 'Precondition Failed', detail: 'stale' })
    }

    const { invalidateSpy } = renderInWorkbench(
      <SdtmDependenciesPanel sdtmId="sdtm-1" />,
    )

    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: /replace selection/i }),
      ).toBeTruthy()
    })
    fireEvent.click(screen.getByRole('button', { name: /replace selection/i }))

    // Concurrency message surfaced…
    await waitFor(() => {
      expect(screen.getByText(/changed since you opened it/i)).toBeTruthy()
    })
    // …and the current selection revision is reloaded before retry (R20.4).
    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: ['/api/v1/sdtms/sdtm-1/dependencies'],
    })
  })
})

describe('SdtmDependenciesPanel refresh-required banner (Req 20.5)', () => {
  it('shows the banner and disables the save control when a refresh is required', async () => {
    sdtmApi.dependencies = makeDependencies({
      state: 'dependency_refresh_required',
    })

    renderInWorkbench(<SdtmDependenciesPanel sdtmId="sdtm-1" />)

    // The persistent staleness banner is shown.
    await waitFor(() => {
      expect(
        screen.getByText('Dependency selection needs a refresh'),
      ).toBeTruthy()
    })
    // The save (start-operation) control is disabled (R20.5).
    expect(
      (
        screen.getByRole('button', {
          name: /replace selection/i,
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true)
  })

  it('leaves the save control enabled when the selection is current', async () => {
    sdtmApi.dependencies = makeDependencies({ state: 'current' })

    renderInWorkbench(<SdtmDependenciesPanel sdtmId="sdtm-1" />)

    await waitFor(() => {
      expect(
        screen.getByRole('button', { name: /replace selection/i }),
      ).toBeTruthy()
    })
    expect(
      (
        screen.getByRole('button', {
          name: /replace selection/i,
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(false)
    // No banner when current.
    expect(
      screen.queryByText('Dependency selection needs a refresh'),
    ).toBeNull()
  })
})
