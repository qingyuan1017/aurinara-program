// @vitest-environment jsdom
import * as React from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import { installJsdomHarness } from '@/test/jsdom-harness'
import type { SdtmDomain } from '@/api/generated/model'
import { SpecificationAuthoringCard } from './specification-authoring-card'

beforeAll(() => {
  installJsdomHarness()
  HTMLElement.prototype.scrollIntoView = vi.fn()
})

function domain(
  code: string,
  variables: Array<{ name: string; label: string }> = [
    { name: 'STUDYID', label: 'Study Identifier' },
    { name: 'USUBJID', label: 'Unique Subject Identifier' },
  ],
): SdtmDomain {
  return {
    code,
    label: code === 'DM' ? 'Demographics' : 'Adverse Events',
    domain_class: 'SPECIAL PURPOSE',
    structure: 'one record per subject',
    keys: ['STUDYID', 'USUBJID'],
    sort_order: ['USUBJID'],
    expected_output_name: `${code.toLowerCase()}.xpt`,
    variables: variables.map((variable) => ({
      ...variable,
      data_type: 'character',
      role: 'Identifier',
      core: 'Req',
      origin: 'Protocol',
    })),
  }
}

function Harness({
  initial,
  onSave = vi.fn(),
}: {
  initial: SdtmDomain[]
  onSave?: () => void
}) {
  const [domains, setDomains] = React.useState(initial)
  return (
    <>
      <SpecificationAuthoringCard
        domains={domains}
        onChange={setDomains}
        onSave={onSave}
        isSaving={false}
      />
      <output data-testid="draft">{JSON.stringify(domains)}</output>
    </>
  )
}

function draft(): SdtmDomain[] {
  return JSON.parse(screen.getByTestId('draft').textContent ?? '[]')
}

describe('SpecificationAuthoringCard', () => {
  it('creates a domain and variable, then enables the atomic save', () => {
    const onSave = vi.fn()
    render(<Harness initial={[domain('DM')]} onSave={onSave} />)

    fireEvent.click(screen.getByRole('button', { name: 'New domain' }))
    fireEvent.change(screen.getByLabelText('Domain code'), {
      target: { value: 'AE' },
    })
    fireEvent.change(screen.getByLabelText('Output filename'), {
      target: { value: 'ae.xpt' },
    })
    fireEvent.change(screen.getByLabelText('Label'), {
      target: { value: 'Adverse Events' },
    })
    fireEvent.change(screen.getByLabelText('Domain class'), {
      target: { value: 'EVENTS' },
    })
    fireEvent.change(screen.getByLabelText('Structure'), {
      target: { value: 'one record per event' },
    })
    fireEvent.change(screen.getByLabelText('Keys'), {
      target: { value: 'USUBJID' },
    })
    fireEvent.change(screen.getByLabelText('Sort order'), {
      target: { value: 'USUBJID' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Create domain' }))

    expect(screen.getByText('AE requires at least one variable.')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Add variable to AE' }))
    fireEvent.change(screen.getByLabelText('Variable name'), {
      target: { value: 'USUBJID' },
    })
    fireEvent.change(screen.getByLabelText('Label'), {
      target: { value: 'Unique Subject Identifier' },
    })
    fireEvent.change(screen.getByLabelText('Role'), {
      target: { value: 'Identifier' },
    })
    fireEvent.change(screen.getByLabelText('Origin'), {
      target: { value: 'Derived' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Create variable' }))

    expect(draft()[1]).toMatchObject({
      code: 'AE',
      label: 'Adverse Events',
      keys: ['USUBJID'],
      variables: [
        {
          name: 'USUBJID',
          label: 'Unique Subject Identifier',
          data_type: 'character',
          core: 'Req',
        },
      ],
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save Specification' }))
    expect(onSave).toHaveBeenCalledTimes(1)
  })

  it('edits a domain and renames a variable while preserving references', () => {
    const initial = domain('DM')
    initial.value_level_metadata = [
      {
        id: 'vlm-1',
        variable: 'STUDYID',
        condition: {
          kind: 'literal',
          value: true,
        },
        label: 'Study-specific identifier',
        data_type: 'character',
      },
    ]
    render(<Harness initial={[initial]} />)

    fireEvent.click(screen.getByRole('button', { name: 'Edit domain DM' }))
    fireEvent.change(screen.getByLabelText('Label'), {
      target: { value: 'Subject Demographics' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save domain' }))

    fireEvent.click(screen.getByRole('button', { name: 'Edit DM.STUDYID' }))
    fireEvent.change(screen.getByLabelText('Variable name'), {
      target: { value: 'STUDY' },
    })
    fireEvent.change(screen.getByLabelText('Label'), {
      target: { value: 'Study' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save variable' }))

    expect(draft()[0]).toMatchObject({
      label: 'Subject Demographics',
      keys: ['STUDY', 'USUBJID'],
      variables: [{ name: 'STUDY', label: 'Study' }, { name: 'USUBJID' }],
      value_level_metadata: [{ variable: 'STUDY' }],
    })
  })

  it('deletes variables and domains and cleans deleted-variable references', async () => {
    const dm = domain('DM')
    dm.value_level_metadata = [
      {
        id: 'vlm-1',
        variable: 'STUDYID',
        condition: {
          kind: 'literal',
          value: true,
        },
        label: 'Study-specific identifier',
        data_type: 'character',
      },
    ]
    render(<Harness initial={[dm, domain('AE')]} />)

    fireEvent.click(screen.getByRole('button', { name: 'Delete DM.STUDYID' }))
    expect(
      screen.getByText(/key, sort-order, and value-level references/i),
    ).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Delete variable' }))

    await waitFor(() => {
      expect(draft()[0]).toMatchObject({
        keys: ['USUBJID'],
        sort_order: ['USUBJID'],
        variables: [{ name: 'USUBJID' }],
        value_level_metadata: [],
      })
      expect(screen.queryByRole('dialog', { name: 'Delete variable' })).toBeNull()
    })

    fireEvent.click(screen.getByRole('button', { name: 'Delete domain AE' }))
    fireEvent.click(screen.getByRole('button', { name: 'Delete domain' }))
    await waitFor(() => {
      expect(draft().map((item) => item.code)).toEqual(['DM'])
    })
  })
})
