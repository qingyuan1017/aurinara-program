import * as React from 'react'
import type { AxiosError } from 'axios'
import type { PDFDocumentProxy, RenderTask } from 'pdfjs-dist'
import pdfWorkerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { ChevronLeft, ChevronRight, FileSearch, ZoomIn, ZoomOut } from 'lucide-react'

import { AXIOS_INSTANCE } from '@/api/axios-instance'
import type { AcrfAnnotationResponse } from '@/api/generated/model'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { parseProblem } from '@/lib/problems'

interface AcrfPdfViewerProps {
  annotations: AcrfAnnotationResponse[]
  open: boolean
  onOpenChange: (open: boolean) => void
}

interface PageSize {
  width: number
  height: number
}

const MIN_ZOOM = 0.5
const MAX_ZOOM = 2
const ZOOM_STEP = 0.25

function clampPage(value: number, pageCount: number): number {
  if (!Number.isFinite(value)) return 1
  return Math.min(Math.max(Math.trunc(value), 1), Math.max(pageCount, 1))
}

/** CSS placement for a normalized top-left aCRF rectangle. */
function annotationOverlayStyle(
  annotation: AcrfAnnotationResponse,
): React.CSSProperties {
  return {
    left: `${annotation.region.x * 100}%`,
    top: `${annotation.region.y * 100}%`,
    width: `${annotation.region.width * 100}%`,
    height: `${annotation.region.height * 100}%`,
  }
}

/**
 * Loads one authorized immutable PDF artifact and renders its saved aCRF
 * annotations over the exact normalized page coordinates.
 */
export function AcrfPdfViewer({
  annotations,
  open,
  onOpenChange,
}: AcrfPdfViewerProps) {
  const canvasRef = React.useRef<HTMLCanvasElement | null>(null)
  const renderTaskRef = React.useRef<RenderTask | null>(null)
  const sourceIds = React.useMemo(
    () => [...new Set(annotations.map((item) => item.source_pdf_artifact_id))],
    [annotations],
  )
  const [sourceId, setSourceId] = React.useState('')
  const [pageNumber, setPageNumber] = React.useState(1)
  const [zoom, setZoom] = React.useState(1)
  const [pdfDocument, setPdfDocument] =
    React.useState<PDFDocumentProxy | null>(null)
  const [pageSize, setPageSize] = React.useState<PageSize | null>(null)
  const [isLoading, setIsLoading] = React.useState(false)
  const [isRendering, setIsRendering] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const [selectedAnnotationId, setSelectedAnnotationId] = React.useState<
    string | null
  >(null)

  React.useEffect(() => {
    if (!open || annotations.length === 0) return
    const currentSourceStillExists = sourceIds.includes(sourceId)
    const nextSourceId = currentSourceStillExists
      ? sourceId
      : annotations[0].source_pdf_artifact_id
    const firstForSource = annotations.find(
      (item) => item.source_pdf_artifact_id === nextSourceId,
    )
    setSourceId(nextSourceId)
    if (!currentSourceStillExists && firstForSource) {
      setPageNumber(firstForSource.page_number)
      setSelectedAnnotationId(firstForSource.id)
    }
  }, [annotations, open, sourceId, sourceIds])

  React.useEffect(() => {
    if (!open || !sourceId) {
      setPdfDocument(null)
      return
    }

    const controller = new AbortController()
    let loadingTask: ReturnType<
      typeof import('pdfjs-dist')['getDocument']
    > | null = null
    let disposed = false

    setIsLoading(true)
    setError(null)
    setPdfDocument(null)
    setPageSize(null)

    void (async () => {
      try {
        const response = await AXIOS_INSTANCE.get<ArrayBuffer>(
          `/api/v1/artifacts/${sourceId}/download`,
          { responseType: 'arraybuffer', signal: controller.signal },
        )
        const pdfjs = await import('pdfjs-dist')
        pdfjs.GlobalWorkerOptions.workerSrc = pdfWorkerUrl
        loadingTask = pdfjs.getDocument({ data: new Uint8Array(response.data) })
        const loadedDocument = await loadingTask.promise
        if (disposed) {
          return
        }
        setPdfDocument(loadedDocument)
        setPageNumber((current) => clampPage(current, loadedDocument.numPages))
      } catch (requestError) {
        if (disposed || controller.signal.aborted) return
        setError(
          parseProblem(requestError as AxiosError).detail ??
            'The source PDF could not be loaded.',
        )
      } finally {
        if (!disposed) setIsLoading(false)
      }
    })()

    return () => {
      disposed = true
      controller.abort()
      void loadingTask?.destroy()
    }
  }, [open, sourceId])

  React.useEffect(() => {
    if (!pdfDocument || !canvasRef.current) return
    let cancelled = false
    setIsRendering(true)
    setError(null)

    void (async () => {
      try {
        const page = await pdfDocument.getPage(pageNumber)
        if (cancelled || !canvasRef.current) return
        const viewport = page.getViewport({ scale: zoom })
        const pixelRatio = window.devicePixelRatio || 1
        const canvas = canvasRef.current
        canvas.width = Math.floor(viewport.width * pixelRatio)
        canvas.height = Math.floor(viewport.height * pixelRatio)
        canvas.style.width = `${viewport.width}px`
        canvas.style.height = `${viewport.height}px`
        setPageSize({ width: viewport.width, height: viewport.height })
        renderTaskRef.current = page.render({
          canvas,
          viewport,
          transform:
            pixelRatio === 1
              ? undefined
              : [pixelRatio, 0, 0, pixelRatio, 0, 0],
        })
        await renderTaskRef.current.promise
      } catch (renderError) {
        if (cancelled || (renderError as { name?: string }).name === 'RenderingCancelledException') {
          return
        }
        setError('This PDF page could not be rendered.')
      } finally {
        if (!cancelled) setIsRendering(false)
      }
    })()

    return () => {
      cancelled = true
      renderTaskRef.current?.cancel()
      renderTaskRef.current = null
    }
  }, [pageNumber, pdfDocument, zoom])

  const pageAnnotations = annotations.filter(
    (item) =>
      item.source_pdf_artifact_id === sourceId &&
      item.page_number === pageNumber &&
      item.status !== 'deleted',
  )
  const pageCount = pdfDocument?.numPages ?? 0

  function selectSource(nextSourceId: string) {
    const first = annotations.find(
      (item) => item.source_pdf_artifact_id === nextSourceId,
    )
    setSourceId(nextSourceId)
    setPageNumber(first?.page_number ?? 1)
    setSelectedAnnotationId(first?.id ?? null)
  }

  function updateZoom(delta: number) {
    setZoom((current) =>
      Math.min(Math.max(current + delta, MIN_ZOOM), MAX_ZOOM),
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="h-[calc(100vh-2rem)] max-w-[calc(100vw-2rem)] grid-rows-[auto_auto_minmax(0,1fr)] overflow-hidden sm:max-w-7xl">
        <DialogHeader>
          <DialogTitle>PDF annotations</DialogTitle>
          <DialogDescription>
            Review the immutable source PDF with saved normalized annotation
            regions overlaid on each page.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-wrap items-end gap-3 border-y py-3">
          <div className="flex min-w-64 flex-col gap-1.5">
            <Label htmlFor="acrf-viewer-source">Source PDF</Label>
            <Select value={sourceId} onValueChange={selectSource}>
              <SelectTrigger id="acrf-viewer-source" className="w-full">
                <SelectValue placeholder="Select a source PDF" />
              </SelectTrigger>
              <SelectContent>
                {sourceIds.map((id, index) => (
                  <SelectItem key={id} value={id}>
                    PDF {index + 1} · {id}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="flex items-center gap-1">
            <Button
              type="button"
              size="icon"
              variant="outline"
              aria-label="Previous PDF page"
              disabled={pageNumber <= 1 || !pdfDocument}
              onClick={() => setPageNumber((current) => current - 1)}
            >
              <ChevronLeft />
            </Button>
            <Label htmlFor="acrf-viewer-page" className="sr-only">
              PDF page
            </Label>
            <Input
              id="acrf-viewer-page"
              className="w-20 text-center"
              type="number"
              min={1}
              max={pageCount || undefined}
              value={pageNumber}
              disabled={!pdfDocument}
              onChange={(event) =>
                setPageNumber(
                  clampPage(Number(event.target.value), pageCount || 1),
                )
              }
            />
            <span className="text-muted-foreground min-w-16 text-sm">
              of {pageCount || '—'}
            </span>
            <Button
              type="button"
              size="icon"
              variant="outline"
              aria-label="Next PDF page"
              disabled={!pdfDocument || pageNumber >= pageCount}
              onClick={() => setPageNumber((current) => current + 1)}
            >
              <ChevronRight />
            </Button>
          </div>

          <div className="ml-auto flex items-center gap-1">
            <Button
              type="button"
              size="icon"
              variant="outline"
              aria-label="Zoom out"
              disabled={zoom <= MIN_ZOOM}
              onClick={() => updateZoom(-ZOOM_STEP)}
            >
              <ZoomOut />
            </Button>
            <span className="text-muted-foreground w-14 text-center text-sm">
              {Math.round(zoom * 100)}%
            </span>
            <Button
              type="button"
              size="icon"
              variant="outline"
              aria-label="Zoom in"
              disabled={zoom >= MAX_ZOOM}
              onClick={() => updateZoom(ZOOM_STEP)}
            >
              <ZoomIn />
            </Button>
          </div>
        </div>

        <div className="grid min-h-0 grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_18rem]">
          <div className="bg-muted/40 min-h-0 overflow-auto rounded-md border p-4">
            {isLoading && (
              <div className="flex h-full items-center justify-center text-sm">
                Loading source PDF…
              </div>
            )}
            {error && (
              <div
                role="alert"
                className="border-destructive/50 bg-destructive/10 text-destructive rounded-md border px-4 py-3 text-sm"
              >
                {error}
              </div>
            )}
            {!isLoading && !error && pdfDocument && (
              <div
                className="relative mx-auto bg-white shadow-lg"
                style={
                  pageSize
                    ? { width: pageSize.width, height: pageSize.height }
                    : undefined
                }
              >
                <canvas ref={canvasRef} aria-label={`PDF page ${pageNumber}`} />
                {pageSize &&
                  pageAnnotations.map((annotation, index) => (
                    <button
                      key={annotation.id}
                      type="button"
                      aria-label={`Annotation ${index + 1}: ${annotation.annotation_text || `page ${pageNumber} region`}`}
                      title={annotation.annotation_text || annotation.id}
                      className={`absolute border-2 bg-amber-300/25 text-left transition-colors hover:bg-amber-300/40 ${
                        selectedAnnotationId === annotation.id
                          ? 'border-amber-600 ring-2 ring-amber-500/50'
                          : 'border-amber-500'
                      }`}
                      style={annotationOverlayStyle(annotation)}
                      onClick={() => setSelectedAnnotationId(annotation.id)}
                    >
                      <span className="absolute -top-3 -left-3 flex size-6 items-center justify-center rounded-full bg-amber-600 text-xs font-semibold text-white shadow">
                        {index + 1}
                      </span>
                    </button>
                  ))}
                {isRendering && (
                  <div className="bg-background/60 absolute inset-0 flex items-center justify-center text-sm">
                    Rendering page…
                  </div>
                )}
              </div>
            )}
          </div>

          <aside className="min-h-0 overflow-auto rounded-md border p-3">
            <div className="mb-3 flex items-center justify-between gap-2">
              <h3 className="text-sm font-medium">Page annotations</h3>
              <Badge variant="secondary">{pageAnnotations.length}</Badge>
            </div>
            {pageAnnotations.length === 0 ? (
              <div className="text-muted-foreground flex flex-col items-center gap-2 py-8 text-center text-sm">
                <FileSearch />
                No annotations on this page.
              </div>
            ) : (
              <ol className="flex flex-col gap-2">
                {pageAnnotations.map((annotation, index) => (
                  <li key={annotation.id}>
                    <button
                      type="button"
                      className={`w-full rounded-md border p-3 text-left text-sm ${
                        selectedAnnotationId === annotation.id
                          ? 'border-amber-500 bg-amber-50 dark:bg-amber-950/20'
                          : 'hover:bg-muted'
                      }`}
                      onClick={() => setSelectedAnnotationId(annotation.id)}
                    >
                      <span className="font-medium">
                        {index + 1}. {annotation.annotation_text || 'Untitled annotation'}
                      </span>
                      <span className="text-muted-foreground mt-1 block text-xs">
                        {annotation.links.length} link
                        {annotation.links.length === 1 ? '' : 's'} · revision{' '}
                        {annotation.revision}
                      </span>
                    </button>
                  </li>
                ))}
              </ol>
            )}
          </aside>
        </div>
      </DialogContent>
    </Dialog>
  )
}
