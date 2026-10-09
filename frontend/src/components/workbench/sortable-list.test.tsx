// @vitest-environment jsdom
import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { SortableList } from './sortable-list'

interface Row {
  id: string
  label: string
}

const ROWS: Row[] = [
  { id: 'a', label: 'Alpha' },
  { id: 'b', label: 'Beta' },
  { id: 'c', label: 'Gamma' },
]

function renderList(onReorder = vi.fn()) {
  render(
    <SortableList
      items={ROWS}
      getId={(r) => r.id}
      onReorder={onReorder}
      renderItem={(r) => <span>{r.label}</span>}
    />,
  )
  return onReorder
}

describe('SortableList fallback controls', () => {
  it('move-down swaps an item with the next one', () => {
    const onReorder = renderList()
    const items = screen.getAllByRole('listitem')
    const downButtons = screen.getAllByRole('button', { name: 'Move down' })
    // Move Alpha (index 0) down.
    fireEvent.click(within(items[0]).getByRole('button', { name: 'Move down' }))
    void downButtons

    expect(onReorder).toHaveBeenCalledTimes(1)
    const [nextItems, moved] = onReorder.mock.calls[0]
    expect(nextItems.map((r: Row) => r.id)).toEqual(['b', 'a', 'c'])
    expect(moved).toEqual({ item: ROWS[0], fromIndex: 0, toIndex: 1 })
  })

  it('move-up swaps an item with the previous one', () => {
    const onReorder = renderList()
    const items = screen.getAllByRole('listitem')
    fireEvent.click(within(items[2]).getByRole('button', { name: 'Move up' }))

    const [nextItems, moved] = onReorder.mock.calls[0]
    expect(nextItems.map((r: Row) => r.id)).toEqual(['a', 'c', 'b'])
    expect(moved.fromIndex).toBe(2)
    expect(moved.toIndex).toBe(1)
  })

  it('disables move-up on first and move-down on last', () => {
    renderList()
    const items = screen.getAllByRole('listitem')
    expect(
      (within(items[0]).getByRole('button', { name: 'Move up' }) as HTMLButtonElement)
        .disabled,
    ).toBe(true)
    expect(
      (within(items[2]).getByRole('button', { name: 'Move down' }) as HTMLButtonElement)
        .disabled,
    ).toBe(true)
  })

  it('numeric ordinal field moves an item to the typed 1-based position', () => {
    const onReorder = renderList()
    const items = screen.getAllByRole('listitem')
    // Move Gamma (index 2) to position 1 (index 0).
    fireEvent.change(within(items[2]).getByRole('spinbutton'), {
      target: { value: '1' },
    })
    const [nextItems] = onReorder.mock.calls[0]
    expect(nextItems.map((r: Row) => r.id)).toEqual(['c', 'a', 'b'])
  })

  it('clamps an out-of-range ordinal into bounds', () => {
    const onReorder = renderList()
    const items = screen.getAllByRole('listitem')
    fireEvent.change(within(items[0]).getByRole('spinbutton'), {
      target: { value: '99' },
    })
    const [nextItems] = onReorder.mock.calls[0]
    // Alpha moved to the last position.
    expect(nextItems.map((r: Row) => r.id)).toEqual(['b', 'c', 'a'])
  })

  it('does not fire when the position does not change', () => {
    const onReorder = renderList()
    const items = screen.getAllByRole('listitem')
    fireEvent.change(within(items[0]).getByRole('spinbutton'), {
      target: { value: '1' },
    })
    expect(onReorder).not.toHaveBeenCalled()
  })

  it('exposes keyboard-operable drag handles', () => {
    renderList()
    // A drag handle exists per row, giving the dnd-kit keyboard sensor a target.
    expect(
      screen.getAllByRole('button', { name: 'Drag to reorder' }),
    ).toHaveLength(ROWS.length)
  })
})
