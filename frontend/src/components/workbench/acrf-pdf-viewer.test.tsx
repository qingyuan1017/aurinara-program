// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

import type { AcrfAnnotationResponse } from '@/api/generated/model'
import { installJsdomHarness } from '@/test/jsdom-harness'

const mocks = vi.hoisted(() => {
  const render = vi.fn(() => ({ promise: Promise.resolve(), cancel: vi.fn() }))
  const getPage = vi.fn(async () => ({
    getViewport: ({ scale }: { scale: number }) => ({
      width: 600 * scale,
      height: 800 * scale,
    }),
    render,
  }))
  const destroyDocument = vi.fn(async () => undefined)
  const document = { numPages: 5, getPage, destroy: destroyDocument }
  const destroyLoadingTask = vi.fn(async () => undefined)
  const getDocument = vi.fn(() => ({
    promise: Promise.resolve(document),
    destroy: destroyLoadingTask,
  }))
  return {
    axiosGet: vi.fn(),
    getDocument,
    getPage,
    render,
    destroyDocument,
    destroyLoadingTask,
  }
})

vi.mock('@/api/axios-instance', () => ({
  AXIOS_INSTANCE: { get: mocks.axiosGet },
}))

vi.mock('pdfjs-dist', () => ({
  GlobalWorkerOptions: { workerSrc: '' },
  getDocument: mocks.getDocument,
}))

import { AcrfPdfViewer } from './acrf-pdf-viewer'

beforeAll(() => {
  installJsdomHarness()
})

function annotation(
  overrides: Partial<AcrfAnnotationResponse> = {},
): AcrfAnnotationResponse {
  return {
    id: 'ann-1',
    sdtm_id: 'sdtm-1',
    study_id: 'study-1',
    source_pdf_artifact_id: 'pdf-artifact-1',
    page_number: 3,
    region: {
      coordinate_system: 'normalized_top_left',
      x: 0.1,
      y: 0.2,
      width: 0.3,
      height: 0.15,
    },
    annotation_text: 'Demographics block',
    links: [],
    question: null,
    resolution: null,
    status: 'active',
    fingerprint: 'fp-1',
    revision: 2,
    created_by: 'user-1',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  } as AcrfAnnotationResponse
}

beforeEach(() => {
  mocks.axiosGet.mockResolvedValue({ data: new ArrayBuffer(8) })
})

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('aCRF PDF viewer', () => {
  it('loads the authorized PDF artifact and overlays annotations on their page', async () => {
    const annotations = [
      annotation(),
      annotation({
        id: 'ann-2',
        annotation_text: 'Subject identifier',
        region: {
          coordinate_system: 'normalized_top_left',
          x: 0.5,
          y: 0.4,
          width: 0.2,
          height: 0.1,
        },
      }),
      annotation({ id: 'ann-3', page_number: 4, annotation_text: 'Visit date' }),
    ]

    render(
      <AcrfPdfViewer
        annotations={annotations}
        open
        onOpenChange={() => {}}
      />,
    )

    await waitFor(() => {
      expect(mocks.axiosGet).toHaveBeenCalledWith(
        '/api/v1/artifacts/pdf-artifact-1/download',
        expect.objectContaining({ responseType: 'arraybuffer' }),
      )
    })
    expect(await screen.findByLabelText('PDF page 3')).toBeTruthy()
    const firstOverlay = screen.getByRole('button', {
      name: /annotation 1: demographics block/i,
    })
    expect(firstOverlay.style.left).toBe('10%')
    expect(firstOverlay.style.top).toBe('20%')
    expect(firstOverlay.style.width).toBe('30%')
    expect(firstOverlay.style.height).toBe('15%')
    expect(
      screen.getByRole('button', {
        name: /annotation 2: subject identifier/i,
      }),
    ).toBeTruthy()
    expect(screen.getByText(/Demographics block/)).toBeTruthy()
    expect(screen.getByText(/Subject identifier/)).toBeTruthy()

    fireEvent.click(screen.getByRole('button', { name: /next pdf page/i }))

    expect(await screen.findByLabelText('PDF page 4')).toBeTruthy()
    expect(screen.getByText(/Visit date/)).toBeTruthy()
    expect(screen.queryByText(/Demographics block/)).toBeNull()
  })
})
