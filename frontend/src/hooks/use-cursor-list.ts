import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

/**
 * Cursor-pagination accumulator for the generated workbench list hooks
 * (`useListRawAggregates`, `useListSdtmAggregates`, and any other Orval list
 * hook with the same `(studyId, params, options)` shape).
 *
 * The helper owns the paging cursor and accumulated page state so each screen
 * stays declarative: it holds the current `after` cursor in state, requests a
 * `limit` clamped to 1-50 (default 50 — Requirement 2.1 / 9.1), accumulates
 * `items` across pages, and exposes `loadMore()` that is enabled only while the
 * current page reports more results.
 *
 * ## Response-shape tolerance
 *
 * The backend `docs/api-contract.md` documents a nested page envelope
 * (`{ items, page: { next_cursor, has_more } }`), while the regenerated Orval
 * client models the flat collection the API actually returns
 * (`{ items, next_cursor }`, with no `has_more`). Rather than silently binding
 * to one shape, this helper reads whichever is present:
 *
 * - `items` is read from the top level.
 * - the next cursor is read from `page.next_cursor` when a `page` envelope is
 *   present, otherwise from the top-level `next_cursor`.
 * - `has_more` is used verbatim when the response provides it; otherwise it is
 *   derived from the presence of a next cursor (`next_cursor != null`).
 *
 * This keeps the helper correct against the current generated client and
 * forward-compatible if the contract mismatch is reconciled toward the
 * documented envelope.
 */

/** Minimal item identity the helper relies on for de-duplication across pages. */
export interface CursorListItem {
  id: string
}

/** The cursor-paginated response envelope the helper understands. */
export interface CursorPage<TItem> {
  items?: TItem[] | null
  next_cursor?: string | null
  page?: {
    next_cursor?: string | null
    has_more?: boolean | null
  } | null
}

/** Query params every generated cursor-list hook accepts. */
export interface CursorListParams {
  limit?: number
  after?: string | null
}

/**
 * Shape of the TanStack Query result the generated list hooks return. Only the
 * fields the accumulator consumes are modeled so any generated hook satisfies
 * it structurally.
 */
export interface CursorQueryResult<TData, TError> {
  data?: TData
  isLoading: boolean
  isFetching: boolean
  isError: boolean
  error: TError | null
}

/**
 * A generated Orval list hook: `useListX(studyId, params, options)`.
 *
 * `TOptions` is left open so the concrete per-hook options type (which embeds
 * the exact `queryKey`/`request` typing) is accepted without widening.
 */
export type CursorListHook<TData, TError, TOptions> = (
  studyId: string,
  params: CursorListParams | undefined,
  options: TOptions,
) => CursorQueryResult<TData, TError>

export interface UseCursorListOptions<TData, TOptions> {
  /** Generated list hook to drive (e.g. `useListRawAggregates`). */
  useListHook: CursorListHook<TData, unknown, TOptions>
  /** Study the list is scoped to; paging resets when it changes. */
  studyId: string
  /**
   * Page size requested from the backend. Clamped to 1-50 and defaulted to 50
   * (Requirement 2.1 / 9.1).
   */
  limit?: number
  /** When false, no request is issued (study-scope gating). Defaults to true. */
  enabled?: boolean
  /**
   * Extra per-hook query options merged into the hook call (e.g. a `request`
   * config). The helper owns `queryKey` and `enabled`, so those are overridden.
   */
  options?: TOptions
}

export interface UseCursorListResult<TItem, TError> {
  /** All items accumulated across the pages fetched so far. */
  items: TItem[]
  /** True while the first page is loading with nothing accumulated yet. */
  isLoading: boolean
  /** True while any page request (initial or `loadMore`) is in flight. */
  isFetching: boolean
  isError: boolean
  error: TError | null
  /** Whether the most recent page reports further results to fetch. */
  hasMore: boolean
  /** Advance to the next page. No-op unless `hasMore` and not already fetching. */
  loadMore: () => void
  /** Drop accumulated pages and restart from the first page. */
  reset: () => void
}

/** Default and bounds for the requested page size (Requirement 2.1 / 9.1). */
export const DEFAULT_CURSOR_LIMIT = 50
export const MIN_CURSOR_LIMIT = 1
export const MAX_CURSOR_LIMIT = 50

/** Clamp a requested page size into the backend-accepted 1-50 window. */
export function clampCursorLimit(limit: number | undefined): number {
  if (limit === undefined || Number.isNaN(limit)) {
    return DEFAULT_CURSOR_LIMIT
  }
  const floored = Math.floor(limit)
  if (floored < MIN_CURSOR_LIMIT) return MIN_CURSOR_LIMIT
  if (floored > MAX_CURSOR_LIMIT) return MAX_CURSOR_LIMIT
  return floored
}

/** Read `items` from either envelope shape. */
function readItems<TItem>(page: CursorPage<TItem> | undefined): TItem[] {
  return page?.items ?? []
}

/** Read the next cursor from the nested `page` envelope or the flat top level. */
function readNextCursor<TItem>(
  page: CursorPage<TItem> | undefined,
): string | null {
  if (page?.page && 'next_cursor' in page.page) {
    return page.page.next_cursor ?? null
  }
  return page?.next_cursor ?? null
}

/**
 * Resolve `has_more`: honour an explicit flag from the nested envelope,
 * otherwise derive it from the presence of a next cursor.
 */
function readHasMore<TItem>(page: CursorPage<TItem> | undefined): boolean {
  const explicit = page?.page?.has_more
  if (typeof explicit === 'boolean') {
    return explicit
  }
  return readNextCursor(page) != null
}

export function useCursorList<
  TItem extends CursorListItem,
  TData extends CursorPage<TItem>,
  TOptions,
  TError = unknown,
>(
  config: UseCursorListOptions<TData, TOptions>,
): UseCursorListResult<TItem, TError> {
  const { useListHook, studyId, limit, enabled = true, options } = config

  const clampedLimit = clampCursorLimit(limit)

  // The cursor sent to the backend for the page currently being fetched.
  const [after, setAfter] = useState<string | null>(null)
  // The ordered list of cursors that have been requested so far, from the first
  // page (`null`) onward. `pageItems` holds the latest items returned for each
  // of those cursors. Accumulated `items` are recomputed from these maps, so a
  // REFETCH of an already-seen page (e.g. the first page after a create/delete
  // mutation invalidates the list) replaces that page's items in place instead
  // of being ignored. The previous implementation folded each cursor exactly
  // once and dropped every later refetch, which is why created items only
  // appeared after a manual full-page reload.
  const [cursorOrder, setCursorOrder] = useState<(string | null)[]>([null])
  const pageItems = useRef<Map<string | null, TItem[]>>(new Map())
  // Bumped whenever a page's items change so the accumulation `useMemo` reruns.
  const [pagesVersion, setPagesVersion] = useState(0)

  const params = useMemo<CursorListParams>(
    () => ({ limit: clampedLimit, after }),
    [clampedLimit, after],
  )

  const mergedOptions = {
    ...(options as object),
    query: {
      ...((options as { query?: object } | undefined)?.query ?? {}),
      enabled: enabled && !!studyId,
    },
  } as TOptions

  const query = useListHook(studyId, params, mergedOptions)
  const page = query.data as CursorPage<TItem> | undefined

  const reset = useCallback(() => {
    pageItems.current = new Map()
    setCursorOrder([null])
    setPagesVersion((v) => v + 1)
    setAfter(null)
  }, [])

  // Restart paging whenever the scope or page size changes.
  useEffect(() => {
    reset()
  }, [studyId, clampedLimit, reset])

  // Record (or refresh) the current page's items keyed by the cursor used to
  // request it. On a refetch of an already-seen cursor the stored items are
  // replaced, so an invalidated list reflects created/updated/deleted rows
  // without a manual page refresh.
  useEffect(() => {
    if (!page) return
    const items = readItems(page)
    const existing = pageItems.current.get(after)
    const sameLength = existing?.length === items.length
    const unchanged =
      sameLength && existing!.every((item, i) => item === items[i])
    if (unchanged && pageItems.current.has(after)) return
    pageItems.current.set(after, items)
    setPagesVersion((v) => v + 1)
  }, [page, after])

  // Rebuild the accumulated list from every known page, in request order, with
  // id de-duplication across pages (earliest occurrence wins).
  const accumulated = useMemo<TItem[]>(() => {
    const result: TItem[] = []
    const seen = new Set<string>()
    for (const cursor of cursorOrder) {
      const items = pageItems.current.get(cursor)
      if (!items) continue
      for (const item of items) {
        if (seen.has(item.id)) continue
        seen.add(item.id)
        result.push(item)
      }
    }
    return result
    // `pagesVersion` is the explicit signal that `pageItems` mutated.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cursorOrder, pagesVersion])

  const hasMore = readHasMore(page)

  const loadMore = useCallback(() => {
    if (query.isFetching) return
    const nextCursor = readNextCursor(page)
    if (nextCursor == null) return
    setCursorOrder((prev) =>
      prev.includes(nextCursor) ? prev : [...prev, nextCursor],
    )
    setAfter(nextCursor)
  }, [page, query.isFetching])

  return {
    items: accumulated,
    isLoading: query.isLoading && accumulated.length === 0,
    isFetching: query.isFetching,
    isError: query.isError,
    error: query.error as TError | null,
    hasMore,
    loadMore,
    reset,
  }
}
