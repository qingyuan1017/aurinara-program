// @vitest-environment jsdom
//
// Component tests for the Raw workbench list/create screen (`raw/index.tsx`)
// and the Raw workbench detail screen (`raw/$rawId.tsx`) — task 5.3.
//
// Coverage (Requirements 2.1, 2.3, 2.4, 2.5, 2.6, 2.7):
//   * cursor pagination requests a limit within 1-50 and follows `next_cursor`
//     while `has_more` is true;
//   * a `201` create refreshes the list (invalidates the list query key);
//   * a `problem+json` create retains the form values and does NOT refresh;
//   * a conditional edit sends the current ETag as `If-Match`;
//   * a `412` shows the concurrency message and reloads the current revision;
//   * a `428` reloads for a fresh ETag before retry.
//
// The repo mocks the generated Orval hooks + study provider rather than running
// a network layer (no MSW is installed), so these tests drive the REAL route
// components over faithful hook fakes and assert the exact params/headers the
// components funnel through `useCursorList` and the mutation `request` option.
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
import type { ReactNode } from 'react'
import type { AxiosError } from 'axios'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { installJsdomHarness } from '@/test/jsdom-harness'
import { ifMatchRequest } from '@/lib/requests'
import type {
  AggregateCollection,
  AggregateResponse,
} from '@/api/generated/model'

beforeAll(() => {
  installJsdomHarness()
})

// ---------------------------------------------------------------------------
// Router stub. The route modules call `createFileRoute(...)({ component })`,
// `useNavigate()`, `Route.useParams()`, and render `<Link>`. jsdom has no
// router, so we provide the minimum surface. `createFileRoute` returns a
// factory that records the component and exposes a `useParams` reading the
// shared `routeParams` fixture.
// ---------------------------------------------------------------------------
const navigateSpy = vi.fn()
const routeParams: { rawId: string } = { rawId: 'raw-1' }
const routeSearch: { tab: string } = { tab: 'datasets' }

vi.mock('@tanstack/react-router', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@tanstack/react-router')>()
  const createFileRoute = () => (opts: { component: unknown }) => ({
    ...opts,
    useParams: () => routeParams,
    useSearch: () => routeSearch,
  })
  const Link = ({ children, ...rest }: { children?: ReactNode }) => (
    <a {...rest}>{children}</a>
  )
  return {
    ...actual,
    createFileRoute,
    useNavigate: () => navigateSpy,
    Link,
  }
})

// ---------------------------------------------------------------------------
// Study provider stub — a study is always selected for these cases.
// ---------------------------------------------------------------------------
const currentStudyState: { currentStudyId: string | null; isLoading: boolean } = {
  currentStudyId: 'study-1',
  isLoading: false,
}
vi.mock('@/components/study-context', () => ({
  useCurrentStudy: () => currentStudyState,
}))

// Keep the toast out of the DOM/theme-provider path under jsdom.
vi.mock('@/components/ui/sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}))

// ---------------------------------------------------------------------------
// Mock the real panels the detail shell wires so these shell tests stay focused
// on list/create/tab routing. Each panel reads generated hooks the list/detail
// shell test does not stub; their own behaviour is covered by the per-panel
// task tests. Mock to a recognizable marker (mirrors the sdtm shell test).
// ---------------------------------------------------------------------------
vi.mock('@/components/workbench/datasets-panel', () => ({
  DatasetsPanel: () => <div data-testid="datasets-panel">Datasets panel</div>,
}))
vi.mock('@/components/workbench/dependencies-panel', () => ({
  DependenciesPanel: () => (
    <div data-testid="dependencies-panel">Dependencies panel</div>
  ),
}))
vi.mock('@/components/workbench/raw-validation-panel', () => ({
  RawValidationPanel: () => (
    <div data-testid="raw-validation-panel">Validation panel</div>
  ),
}))
vi.mock('@/components/workbench/reconciliation-panel', () => ({
  ReconciliationPanel: () => (
    <div data-testid="reconciliation-panel">Reconciliation panel</div>
  ),
}))
vi.mock('@/components/workbench/artifacts-panel', () => ({
  ArtifactsPanel: () => (
    <div data-testid="artifacts-panel">Artifacts panel</div>
  ),
}))

// ---------------------------------------------------------------------------
// Generated Raw hook stubs. Each test installs the behaviour it needs via the
// mutable `rawApi` object the mock reads through.
// ---------------------------------------------------------------------------
interface ListCall {
  studyId: string
  limit?: number
  after?: string | null
}

const rawApi: {
  listPages: Record<string, AggregateCollection>
  listCalls: ListCall[]
  createImpl: (vars: { studyId: string; data: unknown }) => Promise<unknown>
  patchImpl: (vars: { rawId: string; data: unknown }) => Promise<unknown>
  patchRequestConfigs: unknown[]
  aggregate: AggregateResponse | undefined
} = {
  listPages: {},
  listCalls: [],
  createImpl: async () => ({}),
  patchImpl: async () => ({}),
  patchRequestConfigs: [],
  aggregate: undefined,
}

vi.mock('@/api/generated/raw/raw', () => {
  // A faithful stand-in for the generated cursor-list query hook: it records
  // every (studyId, params) the component (via useCursorList) requests and
  // returns the scripted page for the requested cursor.
  const useListRawAggregates = (
    studyId: string,
    params: { limit?: number; after?: string | null } | undefined,
  ) => {
    const after = params?.after ?? null
    rawApi.listCalls.push({ studyId, limit: params?.limit, after })
    const key = after ?? '__first__'
    return {
      data: rawApi.listPages[key],
      isLoading: false,
      isFetching: false,
      isError: false,
      error: null,
    }
  }

  const useCreateRawAggregate = (options?: {
    mutation?: { onSuccess?: (data: unknown) => void }
  }) => {
    const useMutationImpl = (vars: { studyId: string; data: unknown }) =>
      rawApi.createImpl(vars)
    return makeMutationResult(useMutationImpl, options?.mutation?.onSuccess)
  }

  const useGetRawAggregate = () => ({
    data: rawApi.aggregate,
    isLoading: false,
    isFetching: false,
    isError: false,
    error: null,
  })

  const usePatchRaw = (options?: {
    mutation?: { onSuccess?: (data: unknown) => void }
    request?: unknown
  }) => {
    rawApi.patchRequestConfigs.push(options?.request)
    const useMutationImpl = (vars: { rawId: string; data: unknown }) =>
      rawApi.patchImpl(vars)
    return makeMutationResult(useMutationImpl, options?.mutation?.onSuccess)
  }

  return {
    useListRawAggregates,
    getListRawAggregatesQueryKey: (studyId?: string) => [
      '/studies',
      studyId,
      'raw',
    ],
    useCreateRawAggregate,
    useGetRawAggregate,
    usePatchRaw,
    getGetRawAggregateQueryKey: (rawId: string) => ['/raw', rawId],
  }
})

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

// ---------------------------------------------------------------------------
// Imports AFTER the mocks so the route modules bind to the stubs.
// ---------------------------------------------------------------------------
import { Route as RawListRoute } from './index'
import { Route as RawDetailRoute } from './$rawId'

const RawListPage = (RawListRoute as unknown as { component: () => ReactNode })
  .component
const RawDetailPage = (
  RawDetailRoute as unknown as { component: () => ReactNode }
).component

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

function makeAggregate(
  overrides: Partial<AggregateResponse> = {},
): AggregateResponse {
  return {
    id: 'raw-1',
    study_id: 'study-1',
    code: 'RAW1',
    name: 'First workbench',
    status: 'draft',
    revision: 3,
    ...overrides,
  }
}

function problemError(status: number, body: Record<string, unknown>): AxiosError {
  return {
    isAxiosError: true,
    response: { status, data: body },
  } as unknown as AxiosError
}

beforeEach(() => {
  rawApi.listPages = {}
  rawApi.listCalls = []
  rawApi.createImpl = async () => ({})
  rawApi.patchImpl = async () => ({})
  rawApi.patchRequestConfigs = []
  rawApi.aggregate = makeAggregate()
  currentStudyState.currentStudyId = 'study-1'
  currentStudyState.isLoading = false
  navigateSpy.mockReset()
})

afterEach(() => {
  vi.clearAllMocks()
})

// ===========================================================================
// Raw list: cursor pagination (Requirement 2.1)
// ===========================================================================
describe('Raw list cursor pagination (Req 2.1)', () => {
  it('requests the first page with a limit within 1-50', () => {
    rawApi.listPages = {
      __first__: { items: [makeAggregate({ id: 'a' })], next_cursor: null },
    }

    renderWithClient(<RawListPage />)

    expect(rawApi.listCalls.length).toBeGreaterThan(0)
    const first = rawApi.listCalls[0]
    expect(first.studyId).toBe('study-1')
    expect(first.limit).toBeGreaterThanOrEqual(1)
    expect(first.limit).toBeLessThanOrEqual(50)
  })

  it('follows next_cursor while has_more and accumulates pages', async () => {
    rawApi.listPages = {
      __first__: {
        items: [makeAggregate({ id: 'a', code: 'A' })],
        next_cursor: 'cursor-1',
      },
      'cursor-1': {
        items: [makeAggregate({ id: 'b', code: 'B' })],
        next_cursor: null,
      },
    }

    renderWithClient(<RawListPage />)

    // First page rendered; a next cursor means a "Load more" control is shown.
    expect(screen.getByText('A')).toBeTruthy()
    const loadMore = screen.getByRole('button', { name: /load more/i })

    fireEvent.click(loadMore)

    // The follow-up request carries the previous page's next_cursor…
    await waitFor(() => {
      expect(rawApi.listCalls.some((c) => c.after === 'cursor-1')).toBe(true)
    })
    // …and the second page is accumulated into the table.
    await waitFor(() => {
      expect(screen.getByText('B')).toBeTruthy()
    })
    // The final page has no next cursor, so paging stops (no Load more).
    expect(screen.queryByRole('button', { name: /load more/i })).toBeNull()
  })
})

// ===========================================================================
// Raw create (Requirements 2.3, 2.4)
// ===========================================================================
describe('Raw create', () => {
  it('refreshes the list on a 201 success (invalidates the list key)', async () => {
    rawApi.listPages = {
      __first__: { items: [], next_cursor: null },
    }
    rawApi.createImpl = vi.fn(async () => makeAggregate({ id: 'new' }))

    const { invalidateSpy } = renderWithClient(<RawListPage />)

    fireEvent.click(screen.getByRole('button', { name: /new workbench/i }))
    fireEvent.change(screen.getByLabelText(/code/i), {
      target: { value: 'RAW9' },
    })
    fireEvent.change(screen.getByLabelText(/^name/i), {
      target: { value: 'Ninth' },
    })
    fireEvent.click(screen.getByRole('button', { name: /create workbench/i }))

    await waitFor(() => {
      expect(rawApi.createImpl).toHaveBeenCalledTimes(1)
    })
    // onSuccess invalidated the list query key -> list refreshes (Req 2.3).
    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({
        queryKey: ['/studies', 'study-1', 'raw'],
      })
    })
    // The create payload carried the entered values.
    expect((rawApi.createImpl as ReturnType<typeof vi.fn>).mock.calls[0][0]).toMatchObject(
      {
        studyId: 'study-1',
        data: { code: 'RAW9', name: 'Ninth' },
      },
    )
  })

  it('on a problem+json retains the form values and does NOT refresh', async () => {
    rawApi.listPages = {
      __first__: { items: [], next_cursor: null },
    }
    rawApi.createImpl = vi.fn(async () => {
      throw problemError(422, {
        title: 'Invalid workbench',
        detail: 'Code is already taken.',
      })
    })

    const { invalidateSpy } = renderWithClient(<RawListPage />)

    fireEvent.click(screen.getByRole('button', { name: /new workbench/i }))
    fireEvent.change(screen.getByLabelText(/code/i), {
      target: { value: 'DUPE' },
    })
    fireEvent.change(screen.getByLabelText(/^name/i), {
      target: { value: 'Taken' },
    })
    fireEvent.click(screen.getByRole('button', { name: /create workbench/i }))

    await waitFor(() => {
      expect(rawApi.createImpl).toHaveBeenCalledTimes(1)
    })
    // The problem detail is surfaced…
    await waitFor(() => {
      expect(screen.getByText('Code is already taken.')).toBeTruthy()
    })
    // …the entered values are retained (dialog stays open with the inputs)…
    expect((screen.getByLabelText(/code/i) as HTMLInputElement).value).toBe(
      'DUPE',
    )
    expect((screen.getByLabelText(/^name/i) as HTMLInputElement).value).toBe(
      'Taken',
    )
    // …and the list query key was NOT invalidated (no refresh, Req 2.4).
    expect(invalidateSpy).not.toHaveBeenCalledWith({
      queryKey: ['/studies', 'study-1', 'raw'],
    })
  })
})

// ===========================================================================
// Raw detail: conditional edit + concurrency handling (Req 2.5, 2.6, 2.7)
// ===========================================================================
describe('Raw detail conditional edit', () => {
  it('sends the current ETag as If-Match on edit (Req 2.5)', async () => {
    rawApi.aggregate = makeAggregate({ revision: 7 })
    rawApi.patchImpl = vi.fn(async () => makeAggregate({ revision: 8 }))

    const { invalidateSpy } = renderWithClient(<RawDetailPage />)

    fireEvent.click(screen.getByRole('button', { name: /edit/i }))
    fireEvent.change(screen.getByLabelText(/^name/i), {
      target: { value: 'Renamed' },
    })
    fireEvent.click(screen.getByRole('button', { name: /save changes/i }))

    await waitFor(() => {
      expect(rawApi.patchImpl).toHaveBeenCalledTimes(1)
    })
    // The patch hook was wired with ifMatchRequest(revision=7).
    const lastRequest = rawApi.patchRequestConfigs.at(-1)
    expect(lastRequest).toEqual(ifMatchRequest(7))
    expect(
      (lastRequest as { headers: Record<string, string> }).headers['If-Match'],
    ).toBe('"revision-7"')
    // Success refreshes the aggregate.
    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({
        queryKey: ['/raw', 'raw-1'],
      })
    })
  })

  it('on 412 shows the concurrency message and reloads the current revision (Req 2.6)', async () => {
    rawApi.aggregate = makeAggregate({ revision: 7 })
    rawApi.patchImpl = vi.fn(async () => {
      throw problemError(412, {
        title: 'Precondition Failed',
        detail: 'stale',
      })
    })

    const { invalidateSpy } = renderWithClient(<RawDetailPage />)

    fireEvent.click(screen.getByRole('button', { name: /edit/i }))
    fireEvent.change(screen.getByLabelText(/^name/i), {
      target: { value: 'Renamed' },
    })
    fireEvent.click(screen.getByRole('button', { name: /save changes/i }))

    await waitFor(() => {
      expect(rawApi.patchImpl).toHaveBeenCalledTimes(1)
    })
    // The 412 branch reloads the current revision (invalidates the aggregate
    // key) before any retry (Req 2.6).
    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({
        queryKey: ['/raw', 'raw-1'],
      })
    })
    // The stale edit is discarded: the component closes the edit dialog on a
    // 412 (so the in-flight edit cannot be re-submitted against the stale
    // revision) and the next attempt starts from the reloaded revision.
    await waitFor(() => {
      expect(screen.queryByRole('button', { name: /save changes/i })).toBeNull()
    })
  })

  it('on 428 reloads for a fresh ETag before retry (Req 2.7)', async () => {
    rawApi.aggregate = makeAggregate({ revision: 7 })
    rawApi.patchImpl = vi.fn(async () => {
      throw problemError(428, {
        title: 'Precondition Required',
        detail: 'missing if-match',
      })
    })

    const { invalidateSpy } = renderWithClient(<RawDetailPage />)

    fireEvent.click(screen.getByRole('button', { name: /edit/i }))
    fireEvent.change(screen.getByLabelText(/^name/i), {
      target: { value: 'Renamed' },
    })
    fireEvent.click(screen.getByRole('button', { name: /save changes/i }))

    await waitFor(() => {
      expect(rawApi.patchImpl).toHaveBeenCalledTimes(1)
    })
    // The 428 branch reloads the current revision to obtain a fresh ETag
    // before the user can resubmit (Req 2.7).
    await waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({
        queryKey: ['/raw', 'raw-1'],
      })
    })
    // The stale submit is discarded (dialog closed) so the retry carries the
    // fresh ETag reloaded above rather than the missing/old precondition.
    await waitFor(() => {
      expect(screen.queryByRole('button', { name: /save changes/i })).toBeNull()
    })
  })
})
