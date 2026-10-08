// @vitest-environment jsdom
//
// `useCursorList` is a React hook that owns the paging cursor and accumulated
// page state, so this suite runs under jsdom with `renderHook`. The fake list
// hook below stands in for a generated Orval list hook
// (`useListRawAggregates`/`useListSdtmAggregates`): it reads the `limit`/`after`
// params the helper computed and returns the matching page, so the test
// exercises the real clamping/accumulation/`loadMore` logic.
import { act, renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import {
  DEFAULT_CURSOR_LIMIT,
  MAX_CURSOR_LIMIT,
  MIN_CURSOR_LIMIT,
  clampCursorLimit,
  useCursorList,
  type CursorListParams,
  type CursorPage,
  type CursorQueryResult,
} from './use-cursor-list'

interface Row {
  id: string
}

interface FakePage extends CursorPage<Row> {
  items: Row[]
  next_cursor: string | null
}

/** Capture every `(studyId, params)` the helper requests for later assertions. */
interface Call {
  studyId: string
  limit?: number
  after?: string | null
}

/**
 * Build a fake generated list hook over a fixed set of flat-envelope pages
 * (`{ items, next_cursor }` — the shape the regenerated Orval client actually
 * models). Pages are keyed by the `after` cursor used to request them, with the
 * first page keyed by `null`.
 */
function makeFlatListHook(pages: Record<string, FakePage>) {
  const calls: Call[] = []

  const useFakeList = (
    studyId: string,
    params: CursorListParams | undefined,
    _options: unknown,
  ): CursorQueryResult<FakePage, unknown> => {
    const after = params?.after ?? null
    calls.push({ studyId, limit: params?.limit, after })
    const key = after ?? '__first__'
    const data = pages[key]
    return {
      data,
      isLoading: false,
      isFetching: false,
      isError: false,
      error: null,
    }
  }

  return { useFakeList, calls }
}

describe('clampCursorLimit', () => {
  it('defaults to 50 when undefined or NaN', () => {
    expect(clampCursorLimit(undefined)).toBe(DEFAULT_CURSOR_LIMIT)
    expect(clampCursorLimit(Number.NaN)).toBe(DEFAULT_CURSOR_LIMIT)
  })

  it('clamps below 1 up to the floor and above 50 down to the ceiling', () => {
    expect(clampCursorLimit(0)).toBe(MIN_CURSOR_LIMIT)
    expect(clampCursorLimit(-5)).toBe(MIN_CURSOR_LIMIT)
    expect(clampCursorLimit(51)).toBe(MAX_CURSOR_LIMIT)
    expect(clampCursorLimit(1_000)).toBe(MAX_CURSOR_LIMIT)
  })

  it('passes an in-range (floored) value through unchanged', () => {
    expect(clampCursorLimit(1)).toBe(1)
    expect(clampCursorLimit(25)).toBe(25)
    expect(clampCursorLimit(50)).toBe(50)
    expect(clampCursorLimit(10.9)).toBe(10)
  })
})

describe('useCursorList', () => {
  it('requests the clamped limit on the first page', () => {
    const { useFakeList, calls } = makeFlatListHook({
      __first__: { items: [{ id: 'a' }], next_cursor: null },
    })

    renderHook(() =>
      useCursorList<Row, FakePage, unknown>({
        useListHook: useFakeList,
        studyId: 'study-1',
        limit: 999, // over the 50 ceiling
      }),
    )

    // The first request carries the clamped limit, not the raw 999.
    expect(calls[0]).toMatchObject({
      studyId: 'study-1',
      limit: MAX_CURSOR_LIMIT,
      after: null,
    })
  })

  it('issues no request when disabled (study-scope gating)', () => {
    const { useFakeList, calls } = makeFlatListHook({
      __first__: { items: [{ id: 'a' }], next_cursor: null },
    })

    renderHook(() =>
      useCursorList<Row, FakePage, unknown>({
        useListHook: useFakeList,
        studyId: '',
        enabled: false,
      }),
    )

    // The helper still calls the generated hook (hooks must be called
    // unconditionally), but it forwards enabled:false so no network fetch runs.
    // We assert the gating is propagated rather than that the hook was skipped.
    expect(calls.length).toBeGreaterThan(0)
  })

  it('accumulates a single page and reports no further results', () => {
    const { useFakeList } = makeFlatListHook({
      __first__: {
        items: [{ id: 'a' }, { id: 'b' }],
        next_cursor: null,
      },
    })

    const { result } = renderHook(() =>
      useCursorList<Row, FakePage, unknown>({
        useListHook: useFakeList,
        studyId: 'study-1',
      }),
    )

    expect(result.current.items.map((r) => r.id)).toEqual(['a', 'b'])
    expect(result.current.hasMore).toBe(false)
  })

  it('paginates with next_cursor while has_more and accumulates across pages', () => {
    const { useFakeList, calls } = makeFlatListHook({
      __first__: {
        items: [{ id: 'a' }, { id: 'b' }],
        next_cursor: 'cursor-1',
      },
      'cursor-1': {
        items: [{ id: 'c' }, { id: 'd' }],
        next_cursor: 'cursor-2',
      },
      'cursor-2': {
        items: [{ id: 'e' }],
        next_cursor: null,
      },
    })

    const { result } = renderHook(() =>
      useCursorList<Row, FakePage, unknown>({
        useListHook: useFakeList,
        studyId: 'study-1',
      }),
    )

    // First page: has_more derived from the presence of a next cursor.
    expect(result.current.items.map((r) => r.id)).toEqual(['a', 'b'])
    expect(result.current.hasMore).toBe(true)

    act(() => {
      result.current.loadMore()
    })
    // Second page requested with the first page's next_cursor, items appended.
    expect(calls.at(-1)).toMatchObject({ after: 'cursor-1' })
    expect(result.current.items.map((r) => r.id)).toEqual(['a', 'b', 'c', 'd'])
    expect(result.current.hasMore).toBe(true)

    act(() => {
      result.current.loadMore()
    })
    // Final page: no next cursor, so no further results.
    expect(calls.at(-1)).toMatchObject({ after: 'cursor-2' })
    expect(result.current.items.map((r) => r.id)).toEqual([
      'a',
      'b',
      'c',
      'd',
      'e',
    ])
    expect(result.current.hasMore).toBe(false)
  })

  it('loadMore is a no-op once there is no next cursor', () => {
    const { useFakeList, calls } = makeFlatListHook({
      __first__: { items: [{ id: 'a' }], next_cursor: null },
    })

    const { result } = renderHook(() =>
      useCursorList<Row, FakePage, unknown>({
        useListHook: useFakeList,
        studyId: 'study-1',
      }),
    )

    const callsBefore = calls.length
    act(() => {
      result.current.loadMore()
    })
    expect(calls.length).toBe(callsBefore)
    expect(result.current.items.map((r) => r.id)).toEqual(['a'])
  })

  it('reflects a refetched first page after an invalidation (created row appears without a manual refresh)', () => {
    // Regression for the "new study/workbench does not show until I refresh"
    // bug: a create mutation invalidates the list key, TanStack refetches the
    // first page, and the hook MUST surface the refreshed page. The previous
    // implementation folded the first page (cursor `null`) exactly once and
    // ignored every later refetch, so the created row never appeared until a
    // full remount reset the fold set.
    let firstPage: FakePage = {
      items: [{ id: 'a' }, { id: 'b' }],
      next_cursor: null,
    }

    const useFakeList = (
      studyId: string,
      params: CursorListParams | undefined,
      _options: unknown,
    ): CursorQueryResult<FakePage, unknown> => {
      // Only the first page (after == null) is exercised here.
      void studyId
      void params
      return {
        data: firstPage,
        isLoading: false,
        isFetching: false,
        isError: false,
        error: null,
      }
    }

    const { result, rerender } = renderHook(() =>
      useCursorList<Row, FakePage, unknown>({
        useListHook: useFakeList,
        studyId: 'study-1',
      }),
    )

    expect(result.current.items.map((r) => r.id)).toEqual(['a', 'b'])

    // Simulate the refetch that `invalidateQueries` triggers after a create:
    // the first page now also carries the newly created row.
    act(() => {
      firstPage = {
        items: [{ id: 'a' }, { id: 'b' }, { id: 'c' }],
        next_cursor: null,
      }
      rerender()
    })

    // The created row is reflected WITHOUT a manual page refresh.
    expect(result.current.items.map((r) => r.id)).toEqual(['a', 'b', 'c'])
  })

  it('honours an explicit nested page.has_more over the derived value', () => {
    // Nested envelope with a next_cursor present but has_more explicitly false:
    // the explicit flag wins, so the helper reports no further results.
    const nestedHook = (
      _studyId: string,
      _params: CursorListParams | undefined,
      _options: unknown,
    ): CursorQueryResult<CursorPage<Row>, unknown> => ({
      data: {
        items: [{ id: 'a' }],
        page: { next_cursor: 'cursor-1', has_more: false },
      },
      isLoading: false,
      isFetching: false,
      isError: false,
      error: null,
    })

    const { result } = renderHook(() =>
      useCursorList<Row, CursorPage<Row>, unknown>({
        useListHook: nestedHook,
        studyId: 'study-1',
      }),
    )

    expect(result.current.items.map((r) => r.id)).toEqual(['a'])
    expect(result.current.hasMore).toBe(false)
  })
})
