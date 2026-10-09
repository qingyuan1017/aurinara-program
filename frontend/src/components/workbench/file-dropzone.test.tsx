// @vitest-environment jsdom
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { FileDropzone } from './file-dropzone'

function makeFile(name: string): File {
  return new File(['x'], name, { type: 'application/octet-stream' })
}

describe('FileDropzone', () => {
  it('emits the dropped file through onFiles', () => {
    const onFiles = vi.fn()
    render(<FileDropzone onFiles={onFiles} ariaLabel="upload" />)

    const zone = screen.getByRole('button', { name: 'upload' })
    const file = makeFile('a.xpt')
    fireEvent.drop(zone, { dataTransfer: { files: [file] } })

    expect(onFiles).toHaveBeenCalledTimes(1)
    expect(onFiles.mock.calls[0][0]).toEqual([file])
  })

  it('emits the browsed file through the same onFiles callback', () => {
    const onFiles = vi.fn()
    render(<FileDropzone onFiles={onFiles} ariaLabel="upload" />)

    const input = screen.getByTestId('file-dropzone-input') as HTMLInputElement
    const file = makeFile('a.xpt')
    fireEvent.change(input, { target: { files: [file] } })

    expect(onFiles).toHaveBeenCalledTimes(1)
    expect(onFiles.mock.calls[0][0]).toEqual([file])
  })

  it('drop and browse produce an identical payload (parity)', () => {
    const dropped: File[][] = []
    const browsed: File[][] = []

    const { rerender } = render(
      <FileDropzone onFiles={(f) => dropped.push(f)} ariaLabel="upload" />,
    )
    const file = makeFile('same.xpt')
    fireEvent.drop(screen.getByRole('button', { name: 'upload' }), {
      dataTransfer: { files: [file] },
    })

    rerender(
      <FileDropzone onFiles={(f) => browsed.push(f)} ariaLabel="upload" />,
    )
    fireEvent.change(screen.getByTestId('file-dropzone-input'), {
      target: { files: [file] },
    })

    expect(dropped[0]).toEqual(browsed[0])
  })

  it('limits to a single file unless multiple is set', () => {
    const onFiles = vi.fn()
    const { rerender } = render(
      <FileDropzone onFiles={onFiles} ariaLabel="upload" />,
    )
    const files = [makeFile('a'), makeFile('b')]
    fireEvent.drop(screen.getByRole('button', { name: 'upload' }), {
      dataTransfer: { files },
    })
    expect(onFiles.mock.calls[0][0]).toHaveLength(1)

    onFiles.mockClear()
    rerender(<FileDropzone onFiles={onFiles} ariaLabel="upload" multiple />)
    fireEvent.drop(screen.getByRole('button', { name: 'upload' }), {
      dataTransfer: { files },
    })
    expect(onFiles.mock.calls[0][0]).toHaveLength(2)
  })

  it('does not emit when disabled', () => {
    const onFiles = vi.fn()
    render(<FileDropzone onFiles={onFiles} ariaLabel="upload" disabled />)
    fireEvent.drop(screen.getByRole('button', { name: 'upload' }), {
      dataTransfer: { files: [makeFile('a')] },
    })
    expect(onFiles).not.toHaveBeenCalled()
  })
})
