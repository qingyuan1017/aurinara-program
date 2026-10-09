// @vitest-environment jsdom
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { DraggableItem, DropTarget, TransferContext } from './transfer'

describe('transfer wrappers', () => {
  it('renders a draggable source and a drop target inside a context', () => {
    render(
      <TransferContext onTransfer={vi.fn()}>
        <DraggableItem id="var-1" ariaLabel="SDTM variable AGE">
          AGE
        </DraggableItem>
        <DropTarget id="annot-1" ariaLabel="annotation 1">
          Target
        </DropTarget>
      </TransferContext>,
    )

    expect(
      screen.getByRole('button', { name: 'SDTM variable AGE' }),
    ).toBeTruthy()
    expect(screen.getByLabelText('annotation 1')).toBeTruthy()
  })

  it('the explicit fallback control funnels into the same onTransfer shape', () => {
    const onTransfer = vi.fn()
    // Consumers render an "add link" control that calls onTransfer with the same
    // { sourceId, targetId } pair a pointer/keyboard drop would produce.
    function Harness() {
      return (
        <TransferContext onTransfer={onTransfer}>
          <DraggableItem id="var-1">AGE</DraggableItem>
          <DropTarget id="annot-1">Target</DropTarget>
          <button
            type="button"
            onClick={() =>
              onTransfer({ sourceId: 'var-1', targetId: 'annot-1' })
            }
          >
            Add link
          </button>
        </TransferContext>
      )
    }
    render(<Harness />)
    screen.getByRole('button', { name: 'Add link' }).click()

    expect(onTransfer).toHaveBeenCalledWith({
      sourceId: 'var-1',
      targetId: 'annot-1',
    })
  })

  it('disables the draggable source when disabled', () => {
    render(
      <TransferContext onTransfer={vi.fn()}>
        <DraggableItem id="var-1" ariaLabel="src" disabled>
          AGE
        </DraggableItem>
      </TransferContext>,
    )
    expect(
      (screen.getByRole('button', { name: 'src' }) as HTMLButtonElement)
        .disabled,
    ).toBe(true)
  })
})
