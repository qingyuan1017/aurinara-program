// @vitest-environment jsdom
//
// Cross-cutting tests for task 18.2 — query-key invalidation and
// DnD-vs-fallback parity + no-pointer accessibility.
//
// Coverage (Requirements 21.1, 21.2, 21.5, 21.6):
//
//   (a) Invalidation (R21.6): a representative successful mutation per aggregate
//       invalidates the aggregate key AND its dependent collection keys so
//       dependent views refetch. The per-panel task tests already assert their
//       own panel-level invalidation; this suite asserts the shared
//       `lib/invalidate.ts` grouping each of those panels funnels through, so
//       the exact aggregate + dependent-collection key sets are proven once,
//       centrally, rather than re-derived per screen.
//
//   (b) DnD-vs-fallback parity (R21.1, R21.2, R21.5): every DnD surface's pointer
//       drop and its keyboard/non-pointer fallback issue the identical typed
//       request. The five concrete surfaces are each already proven in their
//       own panel tests:
//         * source-file dropzone        -> datasets-panel test (drop vs browse)
//         * Specification import dropzone -> input-selection-specification test
//         * Define XPT drag-select       -> define-panel test (drag vs checkbox)
//         * Raw/Specification var reorder -> variables/specification panel tests
//         * aCRF link drag               -> acrf-panel test (drag vs add-link)
//       The shared primitives those surfaces are built on — `SortableList`
//       (reorder) and `FileDropzone` (upload) — carry the parity guarantee.
//       This suite fills the remaining gap with a FOCUSED parity assertion on
//       `SortableList`: a real pointer drag and the numeric/keyboard fallback
//       produce the IDENTICAL `onReorder` result for the same move, which is
//       exactly the invariant each per-panel reorder/transfer test relies on.
//
//   (c) Accessibility (R21.1): every DnD action is operable without a pointer —
//       the shared primitives expose keyboard-operable affordances (SortableList
//       drag handle + numeric field + move buttons; FileDropzone keyboard-
//       activatable browse) so no capability is pointer-only.
import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { QueryClient } from '@tanstack/react-query'
import { arrayMove } from '@dnd-kit/sortable'

import { installJsdomHarness } from '@/test/jsdom-harness'
import { SortableList } from './sortable-list'
import { FileDropzone } from './file-dropzone'
import {
  invalidateRawAggregate,
  invalidateRawDataset,
  invalidateRawVariable,
  invalidateRawDependencies,
  invalidateRawOperationArtifacts,
  invalidateSdtmSubResource,
  invalidateSdtmDependencies,
  invalidateSdtmOperationArtifacts,
} from '@/lib/invalidate'
import {
  getGetRawAggregateQueryKey,
  getGetRawDependenciesQueryKey,
  getGetDatasetQueryKey,
  getGetVariableQueryKey,
  getListDatasetsQueryKey,
  getListRawAggregatesQueryKey,
  getListVariablesQueryKey,
} from '@/api/generated/raw/raw'
import {
  getGetSdtmAggregateQueryKey,
  getGetSdtmDependenciesQueryKey,
  getGetInputSelectionQueryKey,
  getGetRawContextQueryKey,
  getGetSpecificationQueryKey,
  getGetLineageQueryKey,
  getListWorkareasQueryKey,
} from '@/api/generated/sdtm/sdtm'
import { getListArtifactsQueryKey } from '@/api/generated/artifacts/artifacts'

beforeAll(() => {
  installJsdomHarness()
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

// ---------------------------------------------------------------------------
// (a) Invalidation — each representative mutation invalidates the aggregate key
//     + its dependent collection keys (Requirement 21.6).
//
// Drive the real `lib/invalidate.ts` helpers (the single grouping every
// mutation `onSuccess` funnels through) against a real QueryClient with a spied
// `invalidateQueries`, and assert the exact set of keys. `containsKey` matches
// a call by deep-equality so assertions are order-independent.
// ---------------------------------------------------------------------------
function makeClientWithSpy() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const spy = vi.spyOn(qc, 'invalidateQueries')
  return { qc, spy }
}

function invalidatedKeys(spy: ReturnType<typeof vi.fn>): unknown[][] {
  return spy.mock.calls.map((call) => (call[0] as { queryKey: unknown[] }).queryKey)
}

function expectInvalidated(
  spy: ReturnType<typeof vi.fn>,
  expected: readonly (readonly unknown[])[],
) {
  const actual = invalidatedKeys(spy)
  for (const key of expected) {
    expect(actual).toContainEqual(key)
  }
  // Exactly the expected set is invalidated — no missing, no extra keys.
  expect(actual).toHaveLength(expected.length)
}

describe('Mutation invalidation groups the aggregate + dependent keys (Req 21.6)', () => {
  // --- Raw aggregate (name/status PATCH) ---
  it('Raw aggregate edit invalidates the aggregate detail + study list', () => {
    const { qc, spy } = makeClientWithSpy()
    invalidateRawAggregate(qc, 'raw-1', 'study-1')
    expectInvalidated(spy as never, [
      getGetRawAggregateQueryKey('raw-1'),
      getListRawAggregatesQueryKey('study-1'),
    ])
  })

  // --- Raw dataset (create/rebind/retire) ---
  it('Raw dataset write invalidates the dataset collection + the dataset detail', () => {
    const { qc, spy } = makeClientWithSpy()
    invalidateRawDataset(qc, 'raw-1', 'ds-1')
    expectInvalidated(spy as never, [
      getListDatasetsQueryKey('raw-1'),
      getGetDatasetQueryKey('ds-1'),
    ])
  })

  // --- Raw variable (create/patch/delete/reorder/initialize) ---
  it('Raw variable write invalidates the variable collection + owning dataset + variable detail', () => {
    const { qc, spy } = makeClientWithSpy()
    invalidateRawVariable(qc, 'ds-1', 'var-1')
    expectInvalidated(spy as never, [
      getListVariablesQueryKey('ds-1'),
      getGetDatasetQueryKey('ds-1'),
      getGetVariableQueryKey('var-1'),
    ])
  })

  // --- Raw dependencies replacement ---
  it('Raw dependency replacement invalidates the selection + the aggregate detail', () => {
    const { qc, spy } = makeClientWithSpy()
    invalidateRawDependencies(qc, 'raw-1')
    expectInvalidated(spy as never, [
      getGetRawDependenciesQueryKey('raw-1'),
      getGetRawAggregateQueryKey('raw-1'),
    ])
  })

  // --- Completed Raw 202 operation (reconcile/artifact build) ---
  it('Completed Raw operation invalidates the study artifact collection + aggregate detail', () => {
    const { qc, spy } = makeClientWithSpy()
    invalidateRawOperationArtifacts(qc, 'raw-1', 'study-1')
    expectInvalidated(spy as never, [
      getListArtifactsQueryKey('study-1'),
      getGetRawAggregateQueryKey('raw-1'),
    ])
  })

  // --- SDTM authoring write without input context (e.g. specification save) ---
  it('SDTM specification save invalidates the sub-resource + aggregate detail only', () => {
    const { qc, spy } = makeClientWithSpy()
    invalidateSdtmSubResource(qc, 'specification', 'sdtm-1')
    expectInvalidated(spy as never, [
      getGetSpecificationQueryKey('sdtm-1'),
      getGetSdtmAggregateQueryKey('sdtm-1'),
    ])
  })

  // --- SDTM input-selection write ALSO reloads lineage + raw-context ---
  it('SDTM input-selection write ALSO invalidates lineage + raw-context (inputs changed)', () => {
    const { qc, spy } = makeClientWithSpy()
    invalidateSdtmSubResource(qc, 'input-selection', 'sdtm-1')
    expectInvalidated(spy as never, [
      getGetInputSelectionQueryKey('sdtm-1'),
      getGetSdtmAggregateQueryKey('sdtm-1'),
      getGetLineageQueryKey('sdtm-1'),
      getGetRawContextQueryKey('sdtm-1'),
    ])
  })

  it('SDTM Code Workarea write invalidates the list and aggregate ETag source', async () => {
    const { qc, spy } = makeClientWithSpy()
    await invalidateSdtmSubResource(qc, 'code-workareas', 'sdtm-1')
    expectInvalidated(spy as never, [
      getListWorkareasQueryKey('sdtm-1'),
      getGetSdtmAggregateQueryKey('sdtm-1'),
    ])
  })

  // --- SDTM dependencies replacement ---
  it('SDTM dependency replacement invalidates the selection + the aggregate detail', () => {
    const { qc, spy } = makeClientWithSpy()
    invalidateSdtmDependencies(qc, 'sdtm-1')
    expectInvalidated(spy as never, [
      getGetSdtmDependenciesQueryKey('sdtm-1'),
      getGetSdtmAggregateQueryKey('sdtm-1'),
    ])
  })

  // --- Completed SDTM 202 operation (validate/compile/execute/build) ---
  it('Completed SDTM operation invalidates the study artifact collection + aggregate detail', () => {
    const { qc, spy } = makeClientWithSpy()
    invalidateSdtmOperationArtifacts(qc, 'sdtm-1', 'study-1')
    expectInvalidated(spy as never, [
      getListArtifactsQueryKey('study-1'),
      getGetSdtmAggregateQueryKey('sdtm-1'),
    ])
  })
})

// ---------------------------------------------------------------------------
// (b) + (c) SortableList: pointer-drag vs non-pointer fallback parity, and
//     keyboard-operability of every reorder affordance.
//
// `SortableList` backs every variable-reorder DnD surface (Raw variables,
// Specification variables). Its contract is that a pointer drag and its
// non-pointer fallbacks (numeric ordinal field, move-up/down buttons, keyboard
// drag handle) all funnel through one `onReorder(nextItems, moved)` call, so a
// drag and its fallback produce the IDENTICAL typed persistence request. The
// per-panel reorder tests assert the fallback persists a PATCH; this proves the
// shared primitive makes the pointer path produce the same reorder result.
// ---------------------------------------------------------------------------
interface Row {
  id: string
  label: string
}

const ROWS: Row[] = [
  { id: 'a', label: 'Alpha' },
  { id: 'b', label: 'Beta' },
  { id: 'c', label: 'Gamma' },
]

function renderSortable(onReorder: (next: Row[], moved: unknown) => void) {
  return render(
    <SortableList
      items={ROWS}
      getId={(r) => r.id}
      onReorder={onReorder}
      renderItem={(r) => <span>{r.label}</span>}
      ariaLabel="variables"
    />,
  )
}

/**
 * Give each row element a distinct stacked bounding rect (100px tall, 0px gap)
 * so dnd-kit's `closestCenter` collision detection can tell the rows apart in
 * jsdom, which has no layout engine. Returns a restore fn that removes the
 * per-element overrides so the shared harness default is reinstated.
 */
function stackRowRects(rows: HTMLElement[]): () => void {
  rows.forEach((row, i) => {
    const top = i * 100
    row.getBoundingClientRect = () =>
      ({
        x: 0,
        y: top,
        top,
        left: 0,
        right: 200,
        bottom: top + 100,
        width: 200,
        height: 100,
        toJSON() {
          return this
        },
      }) as DOMRect
  })
  return () => {
    for (const row of rows) {
      delete (row as unknown as { getBoundingClientRect?: unknown })
        .getBoundingClientRect
    }
  }
}

describe('SortableList DnD-vs-fallback parity (Req 21.1, 21.2, 21.5)', () => {
  it('a pointer drag and the numeric fallback produce the IDENTICAL onReorder result', async () => {
    // --- Numeric (non-pointer) fallback path: move Alpha (index 0) to pos 2 ---
    const fallbackReorder = vi.fn()
    const fallback = renderSortable(fallbackReorder)
    const fallbackItems = screen.getAllByRole('listitem')
    fireEvent.change(within(fallbackItems[0]).getByRole('spinbutton'), {
      target: { value: '2' },
    })
    expect(fallbackReorder).toHaveBeenCalledTimes(1)
    const [fallbackNext, fallbackMoved] = fallbackReorder.mock.calls[0]
    fallback.unmount()

    // --- Pointer-drag path: drive dnd-kit's PointerSensor through the real
    //     `onDragEnd`. jsdom has no layout engine, so the shared harness returns
    //     one fixed rect for every element and dnd-kit's collision math cannot
    //     tell the rows apart. Give each row a distinct STACKED rect for this
    //     test so `closestCenter` resolves Beta's slot as the drop target, then
    //     press the source handle, move past the activation threshold, move onto
    //     Beta, and release (index 0 -> 1). ---
    const dragReorder = vi.fn()
    const drag = renderSortable(dragReorder)
    const items = screen.getAllByRole('listitem')
    const restoreRects = stackRowRects(items)
    const sourceHandle = within(items[0]).getByRole('button', {
      name: 'Drag to reorder',
    })

    fireEvent.pointerDown(sourceHandle, { pointerId: 1, clientX: 5, clientY: 5 })
    // Past the PointerSensor activation distance.
    fireEvent.pointerMove(document, { pointerId: 1, clientX: 5, clientY: 20 })
    // Onto the vertical center of Beta's stacked rect (y ~ 150).
    fireEvent.pointerMove(document, { pointerId: 1, clientX: 5, clientY: 150 })
    fireEvent.pointerUp(document, { pointerId: 1, clientX: 5, clientY: 150 })

    await waitFor(() => {
      expect(dragReorder).toHaveBeenCalledTimes(1)
    })
    const [dragNext, dragMoved] = dragReorder.mock.calls[0]

    // Both affordances moved Alpha from index 0 to index 1 and therefore produce
    // the identical reordered array + moved descriptor — the exact invariant a
    // consumer's single `onReorder`->PATCH handler relies on for drag/fallback
    // parity (R21.1, R21.5).
    const expected = arrayMove([...ROWS], 0, 1).map((r) => r.id)
    expect((fallbackNext as Row[]).map((r) => r.id)).toEqual(expected)
    expect((dragNext as Row[]).map((r) => r.id)).toEqual(expected)
    expect(dragNext).toEqual(fallbackNext)
    expect(dragMoved).toEqual(fallbackMoved)

    // Let dnd-kit's post-drop scheduled frame settle before unmount so no
    // document listener/timer leaks into a later test.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 50))
    })
    restoreRects()
    drag.unmount()
  })

  it('the move-up/down buttons and the numeric field agree for the same move (fallback parity)', () => {
    // Two distinct non-pointer affordances for the same move (Alpha down one
    // slot) must produce the identical onReorder result, so whichever a user
    // reaches for issues the same typed request.
    const buttonReorder = vi.fn()
    const buttons = renderSortable(buttonReorder)
    fireEvent.click(screen.getAllByRole('button', { name: 'Move down' })[0])
    const [buttonNext] = buttonReorder.mock.calls[0]
    buttons.unmount()

    const numericReorder = vi.fn()
    renderSortable(numericReorder)
    const items = screen.getAllByRole('listitem')
    fireEvent.change(within(items[0]).getByRole('spinbutton'), {
      target: { value: '2' },
    })
    const [numericNext] = numericReorder.mock.calls[0]

    expect((buttonNext as Row[]).map((r) => r.id)).toEqual(
      (numericNext as Row[]).map((r) => r.id),
    )
    expect(buttonNext).toEqual(numericNext)
  })

  it('exposes a keyboard-operable affordance for every reorder action (operable without a pointer)', () => {
    renderSortable(vi.fn())
    // Keyboard drag handle (dnd-kit KeyboardSensor target) per row…
    expect(
      screen.getAllByRole('button', { name: 'Drag to reorder' }),
    ).toHaveLength(ROWS.length)
    // …plus a numeric ordinal field per row…
    expect(screen.getAllByRole('spinbutton')).toHaveLength(ROWS.length)
    // …plus move-up/down buttons, so the reorder is fully operable without a
    // pointer (every affordance is a focusable, keyboard-activatable control).
    expect(
      screen.getAllByRole('button', { name: 'Move up' }).length,
    ).toBeGreaterThan(0)
    expect(
      screen.getAllByRole('button', { name: 'Move down' }).length,
    ).toBeGreaterThan(0)
  })
})

// ---------------------------------------------------------------------------
// (c) FileDropzone: the upload DnD surface is operable without a pointer — its
//     browse affordance is a keyboard-activatable control, and a keyboard
//     activation reaches the same file <input> a pointer drop feeds, so the
//     drop and non-pointer paths funnel into the same `onFiles` callback.
// ---------------------------------------------------------------------------
describe('FileDropzone no-pointer operability (Req 21.1)', () => {
  it('browse is a keyboard-activatable control wired to the same file input', () => {
    const onFiles = vi.fn()
    render(<FileDropzone onFiles={onFiles} ariaLabel="upload source file" />)

    // The dropzone is exposed as a focusable control (role=button, tabIndex 0)
    // reachable by keyboard, not a pointer-only region.
    const zone = screen.getByRole('button', { name: 'upload source file' })
    expect(zone.getAttribute('tabindex')).toBe('0')

    // Activating it via keyboard (Enter) opens the native file picker: the
    // keydown handler calls the hidden input's click(), the SAME input a pointer
    // drop/browse feeds, so no upload capability is pointer-only.
    const input = screen.getByTestId('file-dropzone-input') as HTMLInputElement
    const clickSpy = vi.spyOn(input, 'click')
    fireEvent.keyDown(zone, { key: 'Enter' })
    expect(clickSpy).toHaveBeenCalled()

    // And a change on that input (the browse result) funnels into onFiles,
    // identical to the drop path proven in file-dropzone.test.tsx.
    const file = new File(['x'], 'a.xpt', { type: 'application/octet-stream' })
    fireEvent.change(input, { target: { files: [file] } })
    expect(onFiles).toHaveBeenCalledTimes(1)
    expect(onFiles.mock.calls[0][0]).toEqual([file])
  })
})
