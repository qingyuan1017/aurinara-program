// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { JsonAuthoringPanel } from './json-authoring-panel'

describe('JsonAuthoringPanel', () => {
  it('blocks malformed JSON without invoking the owning module write', async () => {
    const onSave = vi.fn()
    render(
      <JsonAuthoringPanel
        title="Specification"
        description="Manual authoring"
        value={undefined}
        isLoading={false}
        error={null}
        emptyValue={{ datasets: [] }}
        isSaving={false}
        onReload={vi.fn()}
        onSave={onSave}
      />,
    )

    fireEvent.change(screen.getByLabelText('Versioned content'), {
      target: { value: '{broken' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    expect((await screen.findByRole('alert')).textContent).toContain('JSON')
    expect(onSave).not.toHaveBeenCalled()
  })

  it('sends exactly the user-authored object and shows the persisted payload', async () => {
    const onSave = vi.fn().mockResolvedValue({
      revision: 2,
      fingerprint: 'a'.repeat(64),
      payload: { datasets: [{ code: 'ADSL' }] },
    })
    render(
      <JsonAuthoringPanel
        title="Specification"
        description="Manual authoring"
        value={undefined}
        isLoading={false}
        error={null}
        emptyValue={{ datasets: [] }}
        isSaving={false}
        onReload={vi.fn()}
        onSave={onSave}
      />,
    )

    fireEvent.change(screen.getByLabelText('Versioned content'), {
      target: { value: '{"datasets":[{"code":"ADSL"}]}' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(onSave).toHaveBeenCalledWith({ datasets: [{ code: 'ADSL' }] }))
    await waitFor(() => expect(
      (screen.getByLabelText('Versioned content') as HTMLTextAreaElement).value,
    ).toBe(JSON.stringify({ datasets: [{ code: 'ADSL' }] }, null, 2)))
  })
})
