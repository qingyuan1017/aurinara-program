import * as React from 'react'
import type { AxiosError } from 'axios'
import { useQueryClient } from '@tanstack/react-query'
import { FileSearch, Loader2, Plus, Trash2 } from 'lucide-react'
import { PageHeader } from '@/components/layout/page-header'
import { EmptyState } from '@/components/data/states'
import { StatusBadge } from '@/components/data/status-badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  FormControl,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
import { Badge } from '@/components/ui/badge'
import { toast } from '@/components/ui/sonner'
import { ConfirmDialog } from '@/components/forms/confirm-dialog'
import { OperationRunner } from '@/components/workbench/operation-runner'
import { ArtifactList } from '@/components/workbench/artifact-list'
import type { ArtifactListItem } from '@/components/workbench/artifact-list'
import { AcrfPdfViewer } from '@/components/workbench/acrf-pdf-viewer'
import {
  TransferContext,
  DraggableItem,
  DropTarget,
} from '@/components/workbench/transfer'
import { useWorkbench } from '@/components/workbench/workbench-context'
import {
  useListAnnotations,
  useCreateAnnotation,
  usePatchAnnotation,
  useDeleteAnnotation,
  useWriteLinks,
  useGetCoverage,
  useCreateAcrfArtifact,
  getGetAnnotationQueryKey,
} from '@/api/generated/sdtm-acrf/sdtm-acrf'
import {
  getGetSdtmAggregateQueryKey,
  useGetSdtmDependencies,
} from '@/api/generated/sdtm/sdtm'
import {
  getGetArtifactBuildQueryKey,
  useGetArtifactBuild,
} from '@/api/generated/artifact-builds/artifact-builds'
import type {
  AcrfAnnotationResponse,
  AcrfRegion,
  AcrfSdtmVariableLink,
  AcrfCoverageResponse,
  ArtifactBuildResponse,
} from '@/api/generated/model'
import {
  OPERATION_POLL_PRESETS,
  type OperationQueryOpts,
  type OperationQueryState,
} from '@/hooks/use-operation-poll'
import {
  invalidateSdtmSubResource,
  invalidateSdtmOperationArtifacts,
} from '@/lib/invalidate'
import { ifMatchRequest, useIdempotencyKey } from '@/lib/requests'
import { parseProblem, stalenessAlert } from '@/lib/problems'

/**
 * aCRF tab body for the SDTM workbench detail (Requirement 17).
 *
 * The whole panel hangs off two concurrency tokens:
 * - Annotation CREATE uses the aggregate ETag (the SDTM workbench revision from
 *   {@link useWorkbench}); the backend bumps the workbench revision, so a
 *   successful create refetches the aggregate to pick up the new token
 *   (Requirement 17.2, design "aCRF create uses the aggregate ETag").
 * - Annotation EDIT / soft-DELETE / link WRITE use the per-annotation ETag
 *   (`If-Match: "revision-{N}"` for the annotation's own `revision`,
 *   Requirement 17.4, 17.5).
 */

// ---------------------------------------------------------------------------
// Pure rectangle-bounds validation (exported for task 15.2's unit tests)
// ---------------------------------------------------------------------------

/** A normalized top-left rectangle plus the 1-based page number to validate. */
export interface RectInput {
  x: number
  y: number
  width: number
  height: number
  page: number
}

/** The field a {@link validateRect} failure refers to. */
export type RectField = 'x' | 'y' | 'width' | 'height' | 'page'

export interface RectValidationError {
  /** The single offending field. */
  field: RectField
  /** A human-readable message naming the out-of-range field (Requirement 17.3). */
  message: string
}

/**
 * Validate an aCRF annotation rectangle and page number (Requirement 17.3),
 * as a pure function with no side effects so it can gate submission AND be
 * unit-tested in isolation (task 15.2).
 *
 * Rules (checked in a stable field order so the first offending field is
 * reported deterministically):
 * - `page` must be an integer `>= 1`.
 * - each of `x`, `y`, `width`, `height` must be a finite number within the
 *   inclusive range `0..1`.
 * - the rectangle must not overflow the page: `x + width <= 1` and
 *   `y + height <= 1` (reported against `width` / `height` respectively).
 *
 * Returns `null` when the rectangle is valid, otherwise the first offending
 * field with a message. The create request is only issued when this returns
 * `null`.
 */
export function validateRect(input: RectInput): RectValidationError | null {
  const { x, y, width, height, page } = input

  if (!Number.isInteger(page) || page < 1) {
    return { field: 'page', message: 'Page number must be an integer of 1 or greater.' }
  }

  const unit: { field: Exclude<RectField, 'page'>; value: number }[] = [
    { field: 'x', value: x },
    { field: 'y', value: y },
    { field: 'width', value: width },
    { field: 'height', value: height },
  ]
  for (const { field, value } of unit) {
    if (!Number.isFinite(value) || value < 0 || value > 1) {
      return {
        field,
        message: `${RECT_FIELD_LABEL[field]} must be a decimal between 0 and 1 inclusive.`,
      }
    }
  }

  if (x + width > 1) {
    return {
      field: 'width',
      message: 'The rectangle overflows the page: x + width must not exceed 1.',
    }
  }
  if (y + height > 1) {
    return {
      field: 'height',
      message: 'The rectangle overflows the page: y + height must not exceed 1.',
    }
  }

  return null
}

const RECT_FIELD_LABEL: Record<Exclude<RectField, 'page'>, string> = {
  x: 'X',
  y: 'Y',
  width: 'Width',
  height: 'Height',
}

// ---------------------------------------------------------------------------
// Panel
// ---------------------------------------------------------------------------

export interface AcrfPanelProps {
  /** The SDTM workbench id (path parameter for list/create/coverage/build). */
  sdtmId: string
}

export function AcrfPanel({ sdtmId }: AcrfPanelProps) {
  const annotationsQuery = useListAnnotations(sdtmId)
  const annotations = annotationsQuery.data ?? []

  const [createOpen, setCreateOpen] = React.useState(false)
  const [editTarget, setEditTarget] =
    React.useState<AcrfAnnotationResponse | null>(null)
  const [deleteTarget, setDeleteTarget] =
    React.useState<AcrfAnnotationResponse | null>(null)
  const [viewerOpen, setViewerOpen] = React.useState(false)

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="aCRF"
        description={
          <>
            Author CRF-to-SDTM annotations and links, review coverage, and build
            the aCRF artifact (
            <code>POST /api/v1/sdtms/{'{sdtm_id}'}/acrf/artifacts</code>).
          </>
        }
        actions={
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="outline"
              disabled={annotations.length === 0}
              onClick={() => setViewerOpen(true)}
            >
              <FileSearch /> View PDF annotations
            </Button>
            <Button size="sm" onClick={() => setCreateOpen(true)}>
              <Plus /> New annotation
            </Button>
          </div>
        }
      />

      <AcrfPdfViewer
        annotations={annotations}
        open={viewerOpen}
        onOpenChange={setViewerOpen}
      />

      <AnnotationLinkBuilder
        sdtmId={sdtmId}
        annotations={annotations}
        isLoading={annotationsQuery.isLoading}
        onEdit={setEditTarget}
        onDelete={setDeleteTarget}
      />

      <CoverageCard sdtmId={sdtmId} />

      <AcrfBuildCard sdtmId={sdtmId} />

      <AnnotationCreateDialog
        sdtmId={sdtmId}
        open={createOpen}
        onOpenChange={setCreateOpen}
      />

      <AnnotationEditDialog
        sdtmId={sdtmId}
        annotation={editTarget}
        onOpenChange={(open) => {
          if (!open) setEditTarget(null)
        }}
      />

      <AnnotationDeleteConfirm
        sdtmId={sdtmId}
        annotation={deleteTarget}
        onOpenChange={(open) => {
          if (!open) setDeleteTarget(null)
        }}
      />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Link builder (annotations as drop targets, SDTM variables as draggables)
// ---------------------------------------------------------------------------

/**
 * The target SDTM variables that can be linked onto an annotation. There is no
 * backend list endpoint for "linkable variables" in this surface, so the user
 * types a domain/variable pair; both the drag drop and the explicit "add link"
 * control issue the identical typed {@link useWriteLinks} request with the
 * annotation ETag (Requirement 17.5, design DnD-parity rule).
 */
interface SdtmVariableChoice {
  domain: string
  variable: string
  specificationRevision: number
}

function AnnotationLinkBuilder({
  sdtmId,
  annotations,
  isLoading,
  onEdit,
  onDelete,
}: {
  sdtmId: string
  annotations: AcrfAnnotationResponse[]
  isLoading: boolean
  onEdit: (a: AcrfAnnotationResponse) => void
  onDelete: (a: AcrfAnnotationResponse) => void
}) {
  // A single pending source variable the user authored, draggable onto a
  // target annotation or added via the explicit control.
  const [domain, setDomain] = React.useState('')
  const [variable, setVariable] = React.useState('')
  const [specRevision, setSpecRevision] = React.useState('1')

  const source: SdtmVariableChoice | null = React.useMemo(() => {
    const spec = Number.parseInt(specRevision, 10)
    if (!domain.trim() || !variable.trim() || !Number.isInteger(spec) || spec < 1) {
      return null
    }
    return {
      domain: domain.trim().toUpperCase(),
      variable: variable.trim().toUpperCase(),
      specificationRevision: spec,
    }
  }, [domain, variable, specRevision])

  const writeLink = useAcrfLinkWriter(sdtmId)

  function handleTransfer(_sourceId: string, targetId: string) {
    const annotation = annotations.find((a) => a.id === targetId)
    if (!annotation || !source) return
    void writeLink.write(annotation, source)
  }

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Annotations</CardTitle>
          <CardDescription>Loading annotations…</CardDescription>
        </CardHeader>
      </Card>
    )
  }

  if (annotations.length === 0) {
    return (
      <EmptyState
        title="No annotations yet"
        description="Create an annotation to document CRF-to-SDTM traceability."
      />
    )
  }

  return (
    <TransferContext
      onTransfer={({ sourceId, targetId }) => handleTransfer(sourceId, targetId)}
    >
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Build links</CardTitle>
          <CardDescription>
            Describe a target SDTM variable, then drag it onto an annotation — or
            use the explicit <strong>Add link</strong> control. Both issue the
            same links request with the annotation ETag.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium">Domain</span>
              <Input
                className="w-28"
                aria-label="Link domain"
                value={domain}
                onChange={(e) => setDomain(e.target.value)}
                placeholder="DM"
              />
            </label>
            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium">Variable</span>
              <Input
                className="w-36"
                aria-label="Link variable"
                value={variable}
                onChange={(e) => setVariable(e.target.value)}
                placeholder="USUBJID"
              />
            </label>
            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium">Spec revision</span>
              <Input
                className="w-28"
                type="number"
                min={1}
                aria-label="Link specification revision"
                value={specRevision}
                onChange={(e) => setSpecRevision(e.target.value)}
              />
            </label>
            <div>
              {source ? (
                <DraggableItem
                  id={`src-${source.domain}.${source.variable}`}
                  ariaLabel={`Drag source variable ${source.domain}.${source.variable}`}
                >
                  {source.domain}.{source.variable}
                </DraggableItem>
              ) : (
                <span className="text-muted-foreground text-xs">
                  Enter a domain, variable, and spec revision to drag.
                </span>
              )}
            </div>
          </div>

          <ul className="flex flex-col gap-3">
            {annotations.map((annotation) => (
              <li key={annotation.id}>
                <DropTarget
                  id={annotation.id}
                  ariaLabel={`Drop a source variable onto annotation on page ${annotation.page_number}`}
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex flex-col gap-1">
                      <div className="flex items-center gap-2">
                        <StatusBadge status={annotation.status} />
                        <span className="text-sm font-medium">
                          Page {annotation.page_number}
                        </span>
                        <Badge variant="outline">rev {annotation.revision}</Badge>
                      </div>
                      <span className="text-muted-foreground text-xs">
                        {annotation.annotation_text || 'No annotation text'}
                      </span>
                      <AnnotationLinks links={annotation.links} />
                    </div>
                    <div className="flex items-center gap-2">
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={!source || writeLink.isPending}
                        onClick={() => {
                          if (source) void writeLink.write(annotation, source)
                        }}
                        title={
                          source
                            ? undefined
                            : 'Enter a target variable to add a link'
                        }
                      >
                        Add link
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => onEdit(annotation)}
                      >
                        Edit
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => onDelete(annotation)}
                      >
                        <Trash2 /> Delete
                      </Button>
                    </div>
                  </div>
                </DropTarget>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </TransferContext>
  )
}

function AnnotationLinks({
  links,
}: {
  links: AcrfAnnotationResponse['links']
}) {
  if (!links || links.length === 0) {
    return (
      <span className="text-muted-foreground text-xs italic">Unlinked</span>
    )
  }
  return (
    <div className="flex flex-wrap gap-1">
      {links.map((link, index) => {
        const label =
          'domain' in link && 'variable' in link
            ? `${link.domain}.${link.variable}`
            : JSON.stringify(link)
        return (
          <Badge key={`${label}-${index}`} variant="secondary">
            {label}
          </Badge>
        )
      })}
    </div>
  )
}

/**
 * Shared link-write helper: amends an annotation's links with one typed SDTM
 * variable link, carrying the per-annotation ETag (Requirement 17.5). The same
 * `write` powers both the drag drop and the explicit "add link" control so the
 * two paths issue an identical request.
 */
interface PendingLink {
  annotation: AcrfAnnotationResponse
  source: SdtmVariableChoice
}

function useAcrfLinkWriter(sdtmId: string) {
  const qc = useQueryClient()
  const [pending, setPending] = React.useState<PendingLink | null>(null)

  // The per-annotation ETag (Requirement 17.5) must be supplied to the hook
  // factory's `request` (the orval mutator's second arg comes from here, NOT
  // from a `mutateAsync` option). It is derived from the pending annotation's
  // revision, so the drag drop and the explicit "add link" control both carry
  // the SAME `If-Match` for the SAME annotation — an identical request.
  const write = useWriteLinks({
    request: pending ? ifMatchRequest(pending.annotation.revision) : undefined,
  })

  React.useEffect(() => {
    if (!pending) return
    let cancelled = false
    const { annotation, source } = pending
    const link: AcrfSdtmVariableLink = {
      target_type: 'sdtm_variable',
      specification_revision: source.specificationRevision,
      domain: source.domain,
      variable: source.variable,
    }
    write
      .mutateAsync({
        annotationId: annotation.id,
        data: { operation: 'amend', links: [link] },
      })
      .then(() => {
        toast.success(`Linked ${source.domain}.${source.variable}.`)
        invalidateSdtmSubResource(qc, 'acrf', sdtmId)
        void qc.invalidateQueries({
          queryKey: getGetAnnotationQueryKey(annotation.id),
        })
      })
      .catch((error: AxiosError) => {
        if (error.response?.status === 412) {
          invalidateSdtmSubResource(qc, 'acrf', sdtmId)
        }
        toast.error(
          stalenessAlert(error) ??
            parseProblem(error).detail ??
            'Could not write the link.',
        )
      })
      .finally(() => {
        if (!cancelled) setPending(null)
      })
    return () => {
      cancelled = true
    }
    // Run exactly once per pending link; `write` identity is stable enough and
    // intentionally excluded to avoid re-firing on its own state changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pending, qc, sdtmId])

  function run(annotation: AcrfAnnotationResponse, source: SdtmVariableChoice) {
    setPending({ annotation, source })
  }

  return { write: run, isPending: pending !== null }
}

// ---------------------------------------------------------------------------
// Create / edit / delete
// ---------------------------------------------------------------------------

interface RectFormState {
  sourcePdfArtifactId: string
  page: string
  x: string
  y: string
  width: string
  height: string
  annotationText: string
}

const EMPTY_RECT_FORM: RectFormState = {
  sourcePdfArtifactId: '',
  page: '1',
  x: '0',
  y: '0',
  width: '0.1',
  height: '0.1',
  annotationText: '',
}

function parseRectForm(form: RectFormState): RectInput {
  return {
    x: Number(form.x),
    y: Number(form.y),
    width: Number(form.width),
    height: Number(form.height),
    page: Number(form.page),
  }
}

/**
 * Create an annotation (Requirement 17.2). Client-side rect-bounds validation
 * ({@link validateRect}) gates submission: an out-of-range rectangle blocks the
 * submit and names the offending field WITHOUT issuing the create request
 * (Requirement 17.3). A valid create sends the SDTM workbench (aggregate) ETag
 * and, on success, refetches the aggregate for the bumped revision.
 */
function AnnotationCreateDialog({
  sdtmId,
  open,
  onOpenChange,
}: {
  sdtmId: string
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const qc = useQueryClient()
  const { aggregate, ifMatch } = useWorkbench()
  const [form, setForm] = React.useState<RectFormState>(EMPTY_RECT_FORM)
  const [rectError, setRectError] = React.useState<RectValidationError | null>(
    null,
  )
  const [formError, setFormError] = React.useState<string | null>(null)
  const [fieldError, setFieldError] = React.useState<string | null>(null)

  React.useEffect(() => {
    if (open) {
      setForm(EMPTY_RECT_FORM)
      setRectError(null)
      setFormError(null)
      setFieldError(null)
    }
  }, [open])

  // Annotation create uses the aggregate ETag (R17.2); it is supplied to the
  // hook factory `request` (the orval mutator reads its config from here).
  const create = useCreateAnnotation({ request: ifMatch() })

  function set<K extends keyof RectFormState>(key: K, value: string) {
    setForm((prev) => ({ ...prev, [key]: value }))
    setRectError(null)
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    setFormError(null)

    if (!form.sourcePdfArtifactId.trim()) {
      setFieldError('A source PDF artifact id is required.')
      return
    }
    setFieldError(null)

    // Rect-bounds gate (R17.3): block submit and name the offending field, with
    // NO create request issued.
    const rectResult = validateRect(parseRectForm(form))
    if (rectResult) {
      setRectError(rectResult)
      return
    }

    const region: AcrfRegion = {
      coordinate_system: 'normalized_top_left',
      x: Number(form.x),
      y: Number(form.y),
      width: Number(form.width),
      height: Number(form.height),
    }

    try {
      await create.mutateAsync({
        sdtmId,
        data: {
          source_pdf_artifact_id: form.sourcePdfArtifactId.trim(),
          page_number: Number(form.page),
          region,
          annotation_text: form.annotationText.trim() || null,
        },
      })
      toast.success('Annotation created.')
      // The workbench revision was bumped: refetch the aggregate and the aCRF
      // collections so the panel reads a fresh token (design: refetch rather
      // than parse X-Aggregate-ETag).
      invalidateSdtmSubResource(qc, 'acrf', sdtmId)
      void qc.invalidateQueries({
        queryKey: getGetSdtmAggregateQueryKey(sdtmId),
      })
      onOpenChange(false)
    } catch (error) {
      const axiosError = error as AxiosError
      setFormError(
        stalenessAlert(axiosError) ??
          parseProblem(axiosError).detail ??
          axiosError.message ??
          'Could not create the annotation.',
      )
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!create.isPending) onOpenChange(next)
      }}
    >
      <DialogContent>
        <form onSubmit={handleSubmit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>New annotation</DialogTitle>
            <DialogDescription>
              Annotate the source aCRF PDF with a normalized top-left rectangle.
              The create uses workbench revision {aggregate.revision}.
            </DialogDescription>
          </DialogHeader>

          {formError && (
            <div className="border-destructive/50 bg-destructive/10 text-destructive rounded-md border px-3 py-2 text-sm">
              {formError}
            </div>
          )}

          <FormItem>
            <FormLabel htmlFor="acrf-pdf">
              Source PDF artifact id<span className="text-destructive"> *</span>
            </FormLabel>
            <FormControl>
              <Input
                id="acrf-pdf"
                value={form.sourcePdfArtifactId}
                aria-invalid={!!fieldError}
                onChange={(e) => {
                  set('sourcePdfArtifactId', e.target.value)
                  setFieldError(null)
                }}
              />
            </FormControl>
            {fieldError && <FormMessage>{fieldError}</FormMessage>}
          </FormItem>

          <FormItem>
            <FormLabel htmlFor="acrf-page">Page number</FormLabel>
            <FormControl>
              <Input
                id="acrf-page"
                type="number"
                min={1}
                step={1}
                value={form.page}
                aria-invalid={rectError?.field === 'page'}
                onChange={(e) => set('page', e.target.value)}
              />
            </FormControl>
            {rectError?.field === 'page' && (
              <FormMessage>{rectError.message}</FormMessage>
            )}
          </FormItem>

          <div className="grid grid-cols-2 gap-4">
            {(['x', 'y', 'width', 'height'] as const).map((field) => (
              <FormItem key={field}>
                <FormLabel htmlFor={`acrf-${field}`}>
                  {RECT_FIELD_LABEL[field]}
                </FormLabel>
                <FormControl>
                  <Input
                    id={`acrf-${field}`}
                    type="number"
                    step="0.01"
                    min={0}
                    max={1}
                    value={form[field]}
                    aria-invalid={rectError?.field === field}
                    onChange={(e) => set(field, e.target.value)}
                  />
                </FormControl>
                {rectError?.field === field && (
                  <FormMessage>{rectError.message}</FormMessage>
                )}
              </FormItem>
            ))}
          </div>

          <FormItem>
            <FormLabel htmlFor="acrf-text">Annotation text</FormLabel>
            <FormControl>
              <Input
                id="acrf-text"
                value={form.annotationText}
                onChange={(e) => set('annotationText', e.target.value)}
              />
            </FormControl>
          </FormItem>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={create.isPending}
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={create.isPending}>
              {create.isPending && <Loader2 className="animate-spin" />}
              {create.isPending ? 'Creating…' : 'Create annotation'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

/**
 * Edit an annotation (Requirement 17.4): `PATCH /acrf-annotations/{id}` with the
 * per-annotation ETag. The same rect-bounds gate blocks an out-of-range region
 * before any request is issued.
 */
function AnnotationEditDialog({
  sdtmId,
  annotation,
  onOpenChange,
}: {
  sdtmId: string
  annotation: AcrfAnnotationResponse | null
  onOpenChange: (open: boolean) => void
}) {
  const qc = useQueryClient()
  const open = !!annotation
  const [form, setForm] = React.useState<RectFormState>(EMPTY_RECT_FORM)
  const [rectError, setRectError] = React.useState<RectValidationError | null>(
    null,
  )
  const [formError, setFormError] = React.useState<string | null>(null)

  React.useEffect(() => {
    if (annotation) {
      setForm({
        sourcePdfArtifactId: annotation.source_pdf_artifact_id,
        page: String(annotation.page_number),
        x: String(annotation.region.x),
        y: String(annotation.region.y),
        width: String(annotation.region.width),
        height: String(annotation.region.height),
        annotationText: annotation.annotation_text ?? '',
      })
      setRectError(null)
      setFormError(null)
    }
  }, [annotation])

  // Per-annotation ETag (R17.4) supplied to the hook factory `request`.
  const patch = usePatchAnnotation({
    request: annotation ? ifMatchRequest(annotation.revision) : undefined,
  })

  function set<K extends keyof RectFormState>(key: K, value: string) {
    setForm((prev) => ({ ...prev, [key]: value }))
    setRectError(null)
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    if (!annotation) return
    setFormError(null)

    const rectResult = validateRect(parseRectForm(form))
    if (rectResult) {
      setRectError(rectResult)
      return
    }

    const region: AcrfRegion = {
      coordinate_system: 'normalized_top_left',
      x: Number(form.x),
      y: Number(form.y),
      width: Number(form.width),
      height: Number(form.height),
    }

    try {
      await patch.mutateAsync({
        annotationId: annotation.id,
        data: {
          page_number: Number(form.page),
          region,
          annotation_text: form.annotationText.trim() || null,
        },
      })
      toast.success('Annotation updated.')
      invalidateSdtmSubResource(qc, 'acrf', sdtmId)
      void qc.invalidateQueries({
        queryKey: getGetAnnotationQueryKey(annotation.id),
      })
      onOpenChange(false)
    } catch (error) {
      const axiosError = error as AxiosError
      if (axiosError.response?.status === 412) {
        invalidateSdtmSubResource(qc, 'acrf', sdtmId)
      }
      setFormError(
        stalenessAlert(axiosError) ??
          parseProblem(axiosError).detail ??
          axiosError.message ??
          'Could not update the annotation.',
      )
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!patch.isPending) onOpenChange(next)
      }}
    >
      <DialogContent>
        <form onSubmit={handleSubmit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>Edit annotation</DialogTitle>
            <DialogDescription>
              Update the rectangle, page, or text. Saved with the annotation
              revision {annotation?.revision ?? ''}.
            </DialogDescription>
          </DialogHeader>

          {formError && (
            <div className="border-destructive/50 bg-destructive/10 text-destructive rounded-md border px-3 py-2 text-sm">
              {formError}
            </div>
          )}

          <FormItem>
            <FormLabel htmlFor="acrf-edit-page">Page number</FormLabel>
            <FormControl>
              <Input
                id="acrf-edit-page"
                type="number"
                min={1}
                step={1}
                value={form.page}
                aria-invalid={rectError?.field === 'page'}
                onChange={(e) => set('page', e.target.value)}
              />
            </FormControl>
            {rectError?.field === 'page' && (
              <FormMessage>{rectError.message}</FormMessage>
            )}
          </FormItem>

          <div className="grid grid-cols-2 gap-4">
            {(['x', 'y', 'width', 'height'] as const).map((field) => (
              <FormItem key={field}>
                <FormLabel htmlFor={`acrf-edit-${field}`}>
                  {RECT_FIELD_LABEL[field]}
                </FormLabel>
                <FormControl>
                  <Input
                    id={`acrf-edit-${field}`}
                    type="number"
                    step="0.01"
                    min={0}
                    max={1}
                    value={form[field]}
                    aria-invalid={rectError?.field === field}
                    onChange={(e) => set(field, e.target.value)}
                  />
                </FormControl>
                {rectError?.field === field && (
                  <FormMessage>{rectError.message}</FormMessage>
                )}
              </FormItem>
            ))}
          </div>

          <FormItem>
            <FormLabel htmlFor="acrf-edit-text">Annotation text</FormLabel>
            <FormControl>
              <Input
                id="acrf-edit-text"
                value={form.annotationText}
                onChange={(e) => set('annotationText', e.target.value)}
              />
            </FormControl>
          </FormItem>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={patch.isPending}
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={patch.isPending}>
              {patch.isPending && <Loader2 className="animate-spin" />}
              {patch.isPending ? 'Saving…' : 'Save annotation'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

/**
 * Soft-delete an annotation (Requirement 17.4) behind an explicit confirmation
 * that names the annotation. `DELETE /acrf-annotations/{id}` carries the
 * per-annotation ETag.
 */
function AnnotationDeleteConfirm({
  sdtmId,
  annotation,
  onOpenChange,
}: {
  sdtmId: string
  annotation: AcrfAnnotationResponse | null
  onOpenChange: (open: boolean) => void
}) {
  const qc = useQueryClient()
  // Per-annotation ETag (R17.4) supplied to the hook factory `request`.
  const remove = useDeleteAnnotation({
    request: annotation ? ifMatchRequest(annotation.revision) : undefined,
  })

  async function handleConfirm() {
    if (!annotation) return
    try {
      await remove.mutateAsync({ annotationId: annotation.id })
      toast.success('Annotation deleted.')
      invalidateSdtmSubResource(qc, 'acrf', sdtmId)
    } catch (error) {
      if ((error as AxiosError).response?.status === 412) {
        invalidateSdtmSubResource(qc, 'acrf', sdtmId)
      }
      throw error
    }
  }

  return (
    <ConfirmDialog
      open={!!annotation}
      onOpenChange={onOpenChange}
      title="Delete annotation"
      description={
        annotation ? (
          <>
            Delete the annotation on <strong>page {annotation.page_number}</strong>
            {annotation.annotation_text ? ` ("${annotation.annotation_text}")` : ''}?
            This soft-deletes the annotation.
          </>
        ) : null
      }
      confirmLabel="Delete annotation"
      destructive
      onConfirm={handleConfirm}
      isPending={remove.isPending}
      error={remove.error}
    />
  )
}

// ---------------------------------------------------------------------------
// Coverage
// ---------------------------------------------------------------------------

/**
 * Coverage view (Requirement 17.6): total annotation count, plus the count and
 * list of unlinked annotations, uncovered (unlinked) SDTM variables, and links
 * pinned to non-current revisions.
 */
function CoverageCard({ sdtmId }: { sdtmId: string }) {
  const coverageQuery = useGetCoverage(sdtmId)
  const coverage = coverageQuery.data

  if (coverageQuery.isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Coverage</CardTitle>
          <CardDescription>Loading coverage…</CardDescription>
        </CardHeader>
      </Card>
    )
  }

  if (!coverage) {
    return (
      <EmptyState
        title="Coverage unavailable"
        description="Coverage will appear once the specification and annotations exist."
      />
    )
  }

  const unlinkedAnnotations = coverage.unlinked_annotation_ids
  const uncoveredVariables = coverage.uncovered_sdtm_variables

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Coverage</CardTitle>
        <CardDescription className="flex flex-wrap gap-2">
          <Badge variant="outline">
            Total annotations: {coverage.annotation_count}
          </Badge>
          <Badge variant="secondary">
            Linked: {coverage.linked_annotation_count}
          </Badge>
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4 sm:grid-cols-3">
        <CoverageGroup
          title="Unlinked annotations"
          count={unlinkedAnnotations.length}
          items={unlinkedAnnotations}
          render={(id) => id}
          empty="All annotations are linked."
        />
        <CoverageGroup
          title="Unlinked SDTM variables"
          count={uncoveredVariables.length}
          items={uncoveredVariables}
          render={(item) => formatCoverageVariable(item)}
          empty="All SDTM variables are covered."
        />
        <CoverageGroup
          title="Non-current-revision links"
          count={coverage.noncurrent_link_count}
          items={[]}
          render={() => ''}
          empty={
            coverage.noncurrent_link_count === 0
              ? 'All links point at the current revision.'
              : `${coverage.noncurrent_link_count} link(s) pin a non-current revision.`
          }
        />
      </CardContent>
    </Card>
  )
}

function formatCoverageVariable(
  item: AcrfCoverageResponse['uncovered_sdtm_variables'][number],
): string {
  const domain = item.domain ?? ''
  const variable = item.variable ?? ''
  if (domain && variable) return `${domain}.${variable}`
  return Object.values(item).join('.') || 'variable'
}

function CoverageGroup<T>({
  title,
  count,
  items,
  render,
  empty,
}: {
  title: string
  count: number
  items: readonly T[]
  render: (item: T) => React.ReactNode
  empty: React.ReactNode
}) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <span className="text-sm font-medium">{title}</span>
        <Badge variant={count > 0 ? 'destructive' : 'outline'}>{count}</Badge>
      </div>
      {items.length > 0 ? (
        <ul className="text-muted-foreground flex flex-col gap-1 text-xs">
          {items.map((item, index) => (
            <li key={index} className="break-all">
              {render(item)}
            </li>
          ))}
        </ul>
      ) : (
        <span className="text-muted-foreground text-xs">{empty}</span>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Build
// ---------------------------------------------------------------------------

function useAcrfBuildOperation(
  buildId: string,
  opts: OperationQueryOpts,
): OperationQueryState<ArtifactBuildResponse> {
  const query = useGetArtifactBuild(buildId, { query: opts.query })
  return { data: query.data, error: query.error as AxiosError | null }
}

function CompletedAcrfBuild({
  build,
  sdtmId,
  studyId,
}: {
  build: ArtifactBuildResponse
  sdtmId: string
  studyId: string
}) {
  const qc = useQueryClient()
  React.useEffect(() => {
    // A completed `202` build produces an artifact and advances the aggregate's
    // latest-run state: reload the study-scoped artifact collection + aggregate
    // (shared operation helper) and the aCRF sub-resource view, plus the polled
    // build resource (R21.6).
    invalidateSdtmOperationArtifacts(qc, sdtmId, studyId)
    invalidateSdtmSubResource(qc, 'acrf', sdtmId)
    void qc.invalidateQueries({ queryKey: getGetArtifactBuildQueryKey(build.id) })
  }, [qc, sdtmId, studyId, build.id])

  const artifacts: ArtifactListItem[] = build.result_artifact_ids.map((id) => ({
    id,
  }))

  return (
    <ArtifactList
      artifacts={artifacts}
      title="aCRF artifact"
      emptyTitle="No artifact produced"
      emptyDescription="The build completed but produced no downloadable artifact."
    />
  )
}

/**
 * Build the aCRF artifact (Requirements 17.7, 17.8): `POST /acrf/artifacts` with
 * an `Idempotency-Key`, then poll the resulting build at a fixed 2s interval to
 * a terminal state or 300s via {@link OperationRunner}. A failed terminal or a
 * client timeout names the affected build and presents no artifact.
 */
function AcrfBuildCard({ sdtmId }: { sdtmId: string }) {
  const { aggregate } = useWorkbench()
  const [buildId, setBuildId] = React.useState<string | null>(null)
  const idempotency = useIdempotencyKey()

  // The build pins the current dependency-selection fingerprint as the expected
  // input fingerprint; the server rejects a stale one with 409
  // `stale_input_fingerprint`, which the start error surfaces (mirrors the Raw
  // Artifacts panel).
  const dependenciesQuery = useGetSdtmDependencies(sdtmId)
  const inputFingerprint = dependenciesQuery.data?.fingerprint ?? null

  const create = useCreateAcrfArtifact({ request: idempotency.requestConfig })

  async function handleStart() {
    if (inputFingerprint === null) return
    idempotency.begin()
    try {
      const build = await create.mutateAsync({
        sdtmId,
        data: { expected_input_fingerprint: inputFingerprint },
      })
      setBuildId(build.id)
    } catch (error) {
      const problem = parseProblem(error as AxiosError)
      toast.error(problem.title ?? 'aCRF build could not be started', {
        description: problem.detail,
      })
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">aCRF artifact</CardTitle>
        <CardDescription>
          Build the annotated CRF artifact. The build polls every 2s up to 300s.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {dependenciesQuery.isError && (
          <p className="text-destructive text-sm">
            The dependency selection could not be loaded, so the input
            fingerprint is unavailable. Reload and try again.
          </p>
        )}
        <OperationRunner<ArtifactBuildResponse>
          operationLabel="aCRF build"
          operationId={buildId}
          useGetOperation={useAcrfBuildOperation}
          intervalMs={OPERATION_POLL_PRESETS.build.intervalMs}
          timeoutMs={OPERATION_POLL_PRESETS.build.timeoutMs}
          onStart={handleStart}
          startLabel="Build aCRF artifact"
          startDisabled={create.isPending || inputFingerprint === null}
          renderResult={(build) => (
            <CompletedAcrfBuild
              build={build}
              sdtmId={sdtmId}
              studyId={aggregate.study_id}
            />
          )}
        />
      </CardContent>
    </Card>
  )
}

export default AcrfPanel
