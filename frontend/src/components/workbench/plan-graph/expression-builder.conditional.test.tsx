// @vitest-environment jsdom
//
// Component tests for the conditional (case/when) editor added to the typed
// ExpressionBuilder (design §10, Phase 1). These prove the typed controls
// render — a per-branch "When"/"Then" builder, add/remove-branch controls, and a
// single mandatory "Otherwise" — and that the editor NEVER exposes a free-text
// Python/R/SAS/SQL/code field. The invariant check (no free-text code input) is
// the platform boundary from AGENTS.md "Compilation and execution".
import * as React from 'react'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  ExpressionBuilder,
  defaultExpression,
  type PlanExpression,
} from './expression-builder'

afterEach(() => {
  vi.clearAllMocks()
})

/**
 * A tiny controlled host so the recursive builder behaves like it does in the
 * node inspector: edits flow through `onChange` back into `value`.
 */
function Host({
  initial,
  onChange,
}: {
  initial: PlanExpression
  onChange?: (next: PlanExpression) => void
}) {
  const [value, setValue] = React.useState<PlanExpression>(initial)
  return (
    <ExpressionBuilder
      value={value}
      onChange={(next) => {
        setValue(next)
        onChange?.(next)
      }}
    />
  )
}

/**
 * The invariant guard: no input in the subtree is a free-text code field. The
 * only free-text inputs the typed builder allows are labelled literal values
 * and column/dataset identifiers — never "code", "expression", "python", "r",
 * "sas" or "sql".
 */
function assertNoFreeTextCodeField(container: HTMLElement) {
  const inputs = Array.from(container.querySelectorAll('input, textarea'))
  for (const input of inputs) {
    const label = (
      input.getAttribute('aria-label') ??
      input.getAttribute('placeholder') ??
      ''
    ).toLowerCase()
    expect(label).not.toMatch(/\b(code|expression|python|r|sas|sql|script)\b/)
  }
  // A code editor would be a <textarea>; the typed builder never renders one.
  expect(container.querySelector('textarea')).toBeNull()
}

describe('ExpressionBuilder conditional editor', () => {
  it('defaults a conditional to one branch plus a mandatory null otherwise', () => {
    const value = defaultExpression('conditional')
    expect(value.kind).toBe('conditional')
    if (value.kind !== 'conditional') return
    expect(value.branches).toHaveLength(1)
    expect(value.otherwise).toEqual({ kind: 'literal', value: null })
  })

  it('renders the When/Then builders and a single Otherwise with no free-text code field', () => {
    const { container } = render(
      <Host initial={defaultExpression('conditional')} />,
    )

    // One branch -> one When and one Then kind selector.
    expect(screen.getByLabelText('When kind')).toBeTruthy()
    expect(screen.getByLabelText('Then kind')).toBeTruthy()
    // Exactly one Otherwise builder.
    expect(screen.getAllByLabelText('Otherwise kind')).toHaveLength(1)
    // The conditional owns at least one branch row.
    expect(
      container.querySelectorAll('[data-slot="conditional-branch"]').length,
    ).toBe(1)

    assertNoFreeTextCodeField(container)
  })

  it('adds and removes branches (keeping at least one) and reflects it in the typed value', () => {
    const onChange = vi.fn()
    const { container } = render(
      <Host initial={defaultExpression('conditional')} onChange={onChange} />,
    )

    // Add a second branch.
    fireEvent.click(screen.getByRole('button', { name: /add branch/i }))
    expect(
      container.querySelectorAll('[data-slot="conditional-branch"]').length,
    ).toBe(2)
    const afterAdd = onChange.mock.calls.at(-1)?.[0] as PlanExpression
    expect(afterAdd.kind).toBe('conditional')
    if (afterAdd.kind === 'conditional') {
      expect(afterAdd.branches).toHaveLength(2)
    }

    // Remove the first branch -> back to one.
    fireEvent.click(screen.getByRole('button', { name: /remove branch 1/i }))
    expect(
      container.querySelectorAll('[data-slot="conditional-branch"]').length,
    ).toBe(1)

    // The sole remaining branch cannot be removed (min_length >= 1).
    const removeButtons = screen.getAllByRole('button', {
      name: /remove branch/i,
    })
    expect((removeButtons[0] as HTMLButtonElement).disabled).toBe(true)
  })

  it('edits a When column and reflects it back into the typed branch', () => {
    const onChange = vi.fn()
    render(<Host initial={defaultExpression('conditional')} onChange={onChange} />)

    // The first branch's When defaults to a column; its dataset/column inputs
    // are plain typed identifiers, not code.
    const branch = screen
      .getByText('Branch 1')
      .closest('[data-slot="conditional-branch"]') as HTMLElement
    const datasetInput = within(branch).getAllByLabelText('Column dataset')[0]
    fireEvent.change(datasetInput, { target: { value: 'DM' } })

    const next = onChange.mock.calls.at(-1)?.[0] as PlanExpression
    expect(next.kind).toBe('conditional')
    if (next.kind !== 'conditional') return
    expect(next.branches[0].when).toMatchObject({
      kind: 'column',
      dataset: 'DM',
    })
  })
})
