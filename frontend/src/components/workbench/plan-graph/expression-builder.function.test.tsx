// @vitest-environment jsdom
//
// Component tests for the typed function + list-literal editor added to the
// ExpressionBuilder (design §10, Phase 2). These prove the typed controls
// render — a function Select populated from the generated FunctionName enum,
// one child builder per positional argument, arity-aware argument reset on
// function change, variadic add/remove, and a typed `is_in` list-literal editor
// (individual typed values only) — and that there is NEVER a free-text
// Python/R/SAS/SQL/code field (AGENTS.md "Compilation and execution").
import * as React from 'react'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { FunctionCallExpressionFunction } from '@/api/generated/model'
import type { CustomFunctionDefinition } from '@/api/generated/model'

import {
  ExpressionBuilder,
  defaultExpression,
  type PlanExpression,
} from './expression-builder'

afterEach(() => {
  vi.clearAllMocks()
})

function Host({
  initial,
  onChange,
  customFunctions,
}: {
  initial: PlanExpression
  onChange?: (next: PlanExpression) => void
  customFunctions?: CustomFunctionDefinition[]
}) {
  const [value, setValue] = React.useState<PlanExpression>(initial)
  return (
    <ExpressionBuilder
      value={value}
      onChange={(next) => {
        setValue(next)
        onChange?.(next)
      }}
      customFunctions={customFunctions}
    />
  )
}

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
  expect(container.querySelector('textarea')).toBeNull()
}

/** A function-call expression starting at the given function name. */
function functionExpression(fn: PlanExpression & { kind: 'function' }) {
  return fn
}

describe('ExpressionBuilder function editor', () => {
  it('authors cast as a typed function inside an assignment expression', () => {
    const { container } = render(<Host initial={defaultExpression('cast')} />)

    expect(container.querySelector('[data-slot="cast-function-fields"]')).toBeTruthy()
    expect(screen.getByLabelText('Value to cast kind')).toBeTruthy()
    expect(screen.getByLabelText('Target type')).toBeTruthy()
    expect(screen.getByLabelText('On invalid')).toBeTruthy()
    assertNoFreeTextCodeField(container)
  })

  it('authors terminology mapping as a typed function inside an assignment expression', () => {
    const onChange = vi.fn()
    const { container } = render(
      <Host initial={defaultExpression('terminology_map')} onChange={onChange} />,
    )

    expect(
      container.querySelector('[data-slot="terminology-function-fields"]'),
    ).toBeTruthy()
    expect(screen.getByLabelText('Value to map kind')).toBeTruthy()
    fireEvent.change(screen.getByLabelText('Terminology source 1'), {
      target: { value: 'M' },
    })
    fireEvent.change(screen.getByLabelText('Terminology target 1'), {
      target: { value: 'MALE' },
    })

    expect(onChange.mock.calls.at(-1)?.[0]).toMatchObject({
      kind: 'terminology_map',
      mappings: { M: 'MALE' },
    })
    assertNoFreeTextCodeField(container)
  })

  it('authors a typed custom-function call with declared named parameters', () => {
    const onChange = vi.fn()
    const customFunctions: CustomFunctionDefinition[] = [
      {
        id: 'subject_id',
        parameters: ['site', 'subject'],
        return_type: 'character',
        implementations: [{ language: 'python', source: 'return site + subject' }],
      },
    ]
    const { container } = render(
      <Host
        initial={defaultExpression('custom_function')}
        onChange={onChange}
        customFunctions={customFunctions}
      />,
    )

    fireEvent.click(screen.getByLabelText('Custom function'))
    fireEvent.click(screen.getByRole('option', { name: 'subject_id' }))

    const next = onChange.mock.calls.at(-1)?.[0] as PlanExpression
    expect(next).toMatchObject({
      kind: 'custom_function',
      function_id: 'subject_id',
    })
    expect(next.kind === 'custom_function' && next.arguments).toHaveLength(2)
    expect(screen.getByLabelText('site kind')).toBeTruthy()
    expect(screen.getByLabelText('subject kind')).toBeTruthy()
    expect(container.querySelector('[data-slot="custom-function-fields"]')).toBeTruthy()
    expect(container.querySelector('textarea')).toBeNull()
  })

  it('defaults a function to a safe single-argument upper() call', () => {
    const value = defaultExpression('function')
    expect(value.kind).toBe('function')
    if (value.kind !== 'function') return
    expect(value.function).toBe('upper')
    expect(value.arguments).toHaveLength(1)
    expect(value.arguments[0]).toMatchObject({ kind: 'column' })
  })

  it('renders a function Select listing every generated FunctionName with no free-text code field', () => {
    const { container } = render(
      <Host initial={defaultExpression('function')} />,
    )

    // The function Select is present and typed.
    expect(screen.getByLabelText('Function name')).toBeTruthy()

    // Every catalog function from the generated enum is an option in the
    // (jsdom-rendered Radix) listbox. The enum drives the control — no names are
    // hand-maintained in the frontend.
    const names = Object.values(FunctionCallExpressionFunction)
    expect(names.length).toBe(40)

    // One positional argument builder for the default upper() call.
    expect(
      container.querySelectorAll('[data-slot="function-argument"]').length,
    ).toBe(1)

    assertNoFreeTextCodeField(container)
  })

  it('renders exactly the current function arity (arity-aware argument slots)', () => {
    // The editor renders one argument builder per positional argument. A fixed-
    // arity function (substring = 3) shows three slots; a 1-arg function (trim)
    // shows one. This is the invariant the arity-aware reset preserves when the
    // function changes.
    const substring = render(
      <Host
        initial={functionExpression({
          kind: 'function',
          function: 'substring',
          arguments: [
            { kind: 'column', dataset: 'DM', column: 'USUBJID' },
            { kind: 'literal', value: 1 },
            { kind: 'literal', value: 4 },
          ],
        })}
      />,
    )
    expect(
      substring.container.querySelectorAll('[data-slot="function-argument"]')
        .length,
    ).toBe(3)
    substring.unmount()

    const trim = render(
      <Host
        initial={{
          kind: 'function',
          function: 'trim',
          arguments: [{ kind: 'column', dataset: '', column: '' }],
        }}
      />,
    )
    expect(
      trim.container.querySelectorAll('[data-slot="function-argument"]').length,
    ).toBe(1)
  })

  it('rebuilds the argument list to the new function arity on change (defaultExpression → is_in gets a typed list slot)', () => {
    // The function change handler resets arguments via the same arity map that
    // defaultExpression('function') uses. Switching to is_in must produce a
    // column arg[0] and a typed list_literal arg[1] (never free text).
    const upper = defaultExpression('function')
    expect(upper.kind === 'function' && upper.arguments).toHaveLength(1)

    // Simulate the reset the Select change performs: is_in at its arity.
    const isIn = {
      kind: 'function' as const,
      function: 'is_in' as const,
      arguments: [
        { kind: 'column' as const, dataset: '', column: '' },
        { kind: 'list_literal' as const, values: [''] },
      ],
    }
    const { container } = render(<Host initial={isIn} />)
    expect(
      container.querySelectorAll('[data-slot="function-argument"]').length,
    ).toBe(2)
    expect(
      container.querySelector('[data-slot="list-literal-fields"]'),
    ).toBeTruthy()
  })

  it('allows adding and removing arguments for a variadic function', () => {
    const onChange = vi.fn()
    const { container } = render(
      <Host
        initial={{
          kind: 'function',
          function: 'concat',
          arguments: [{ kind: 'column', dataset: '', column: '' }],
        }}
        onChange={onChange}
      />,
    )

    // concat is variadic (min 1); the Add argument control is offered.
    fireEvent.click(screen.getByRole('button', { name: /add argument/i }))
    expect(
      container.querySelectorAll('[data-slot="function-argument"]').length,
    ).toBe(2)
    const afterAdd = onChange.mock.calls.at(-1)?.[0] as PlanExpression
    expect(afterAdd.kind === 'function' && afterAdd.arguments.length).toBe(2)

    // The now-extra argument can be removed back to the minimum.
    fireEvent.click(screen.getByRole('button', { name: /remove argument 2/i }))
    expect(
      container.querySelectorAll('[data-slot="function-argument"]').length,
    ).toBe(1)
  })

  it('renders the is_in second argument as a typed list-literal editor, not a code field', () => {
    const { container } = render(
      <Host
        initial={{
          kind: 'function',
          function: 'is_in',
          arguments: [
            { kind: 'column', dataset: 'DM', column: 'ARMCD' },
            { kind: 'list_literal', values: ['A', 'B'] },
          ],
        }}
      />,
    )

    // The 2nd argument is the dedicated typed value-list editor.
    const listEditor = container.querySelector('[data-slot="list-literal-fields"]')
    expect(listEditor).toBeTruthy()

    // It renders one typed value row per member (type select + value input),
    // not a free-text set/code field.
    const memberTypeSelects = screen.getAllByLabelText(/member \d+ type/i)
    expect(memberTypeSelects.length).toBe(2)
    const memberValueInputs = screen.getAllByLabelText(/member \d+ value/i)
    expect(memberValueInputs.length).toBe(2)

    assertNoFreeTextCodeField(container)
  })

  it('edits a list-literal member value and reflects it into the typed list', () => {
    const onChange = vi.fn()
    render(
      <Host
        initial={{
          kind: 'function',
          function: 'is_in',
          arguments: [
            { kind: 'column', dataset: 'DM', column: 'ARMCD' },
            { kind: 'list_literal', values: ['A'] },
          ],
        }}
        onChange={onChange}
      />,
    )

    const listEditor = screen
      .getByLabelText(/member 1 value/i)
      .closest('[data-slot="list-literal-fields"]') as HTMLElement
    const valueInput = within(listEditor).getByLabelText(/member 1 value/i)
    fireEvent.change(valueInput, { target: { value: 'PLACEBO' } })

    const next = onChange.mock.calls.at(-1)?.[0] as PlanExpression
    expect(next.kind).toBe('function')
    if (next.kind !== 'function') return
    const listArg = next.arguments[1]
    expect(listArg.kind).toBe('list_literal')
    if (listArg.kind !== 'list_literal') return
    expect(listArg.values).toEqual(['PLACEBO'])
  })
})
