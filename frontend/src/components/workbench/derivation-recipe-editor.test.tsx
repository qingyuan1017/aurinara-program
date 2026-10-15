// @vitest-environment jsdom
import * as React from 'react'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { CustomFunctionDefinition } from '@/api/generated/model'
import {
  CustomFunctionEditor,
} from './custom-function-editor'
import { validateCustomFunctions } from './custom-function-validation'
import { synchronizeCustomFunctionCalls } from './custom-function-references'
import {
  AssignmentList,
  type PlanExpression,
} from './plan-graph/expression-builder'

function AssignmentHost() {
  const [assignments, setAssignments] = React.useState<Record<string, PlanExpression>>({
    A: { kind: 'column', dataset: 'DM', column: 'B' },
    B: { kind: 'column', dataset: 'RAW', column: 'SOURCE' },
    C: {
      kind: 'function',
      function: 'substring',
      arguments: [
        { kind: 'column', dataset: 'RAW', column: 'TEXT' },
        { kind: 'literal', value: 1 },
        { kind: 'literal', value: 3 },
      ],
    },
    D: { kind: 'literal', value: 'Y' },
  })
  return (
    <AssignmentList
      assignments={assignments}
      onChange={setAssignments}
      targetDomain="DM"
    />
  )
}

describe('variable derivation recipes', () => {
  it('shows named function parameters and dependency/order guidance', () => {
    render(<AssignmentHost />)

    expect(screen.getByText('uses B')).toBeTruthy()
    expect(screen.getByText('Move B earlier')).toBeTruthy()
    expect(screen.getByLabelText('text kind')).toBeTruthy()
    expect(screen.getByLabelText('start kind')).toBeTruthy()
    expect(screen.getByLabelText('length kind')).toBeTruthy()
  })

  it('searches, duplicates, collapses, and reorders variable recipes', () => {
    const { container } = render(<AssignmentHost />)

    fireEvent.change(screen.getByLabelText('Search derived variables'), {
      target: { value: 'substring' },
    })
    expect(container.querySelectorAll('[data-slot="variable-recipe"]')).toHaveLength(1)

    fireEvent.change(screen.getByLabelText('Search derived variables'), {
      target: { value: '' },
    })
    fireEvent.click(screen.getByLabelText('Collapse C'))
    expect(screen.queryByLabelText('text kind')).toBeNull()

    fireEvent.click(screen.getByLabelText('Duplicate assignment D'))
    expect(screen.getByDisplayValue('D_COPY')).toBeTruthy()
    fireEvent.click(screen.getByLabelText('Move D_COPY up'))
    expect(screen.getByText('5 variable recipes')).toBeTruthy()
  })
})

describe('typed custom function editor', () => {
  const definition: CustomFunctionDefinition = {
    id: 'subject_key',
    parameters: ['site', 'subject'],
    return_type: 'character',
    implementations: [{ language: 'python', source: 'return site + subject' }],
  }

  it('edits named signatures and reports the previous and next shape', () => {
    const onSignatureChange = vi.fn()

    function Host() {
      const [functions, setFunctions] = React.useState([definition])
      return (
        <CustomFunctionEditor
          functions={functions}
          onChange={setFunctions}
          onSignatureChange={onSignatureChange}
        />
      )
    }

    render(<Host />)
    fireEvent.change(screen.getByLabelText('Parameter 2 for subject_key'), {
      target: { value: 'participant' },
    })

    expect(onSignatureChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ parameters: ['site', 'subject'] }),
      expect.objectContaining({ parameters: ['site', 'participant'] }),
    )
    expect(screen.getByLabelText('python body for subject_key')).toBeTruthy()
  })

  it('blocks malformed signatures and empty language bodies before save', () => {
    expect(
      validateCustomFunctions([
        {
          ...definition,
          id: 'Bad ID',
          parameters: ['site', 'site'],
          implementations: [{ language: 'python', source: '   ' }],
        },
      ]),
    ).toContain('invalid function ID')
  })

  it('keeps call expressions attached to named parameters when a signature changes', () => {
    const next = synchronizeCustomFunctionCalls(
      {
        kind: 'custom_function',
        function_id: 'subject_key',
        arguments: [
          { kind: 'column', dataset: 'RAW', column: 'SITE' },
          { kind: 'column', dataset: 'RAW', column: 'SUBJECT' },
        ],
      },
      definition,
      {
        ...definition,
        id: 'participant_key',
        parameters: ['subject', 'site', 'separator'],
      },
    ) as { function_id: string; arguments: { column: string }[] }

    expect(next.function_id).toBe('participant_key')
    expect(next.arguments[0].column).toBe('SUBJECT')
    expect(next.arguments[1].column).toBe('SITE')
    expect(next.arguments[2]).toMatchObject({ kind: 'column', dataset: '', column: '' })
  })
})
