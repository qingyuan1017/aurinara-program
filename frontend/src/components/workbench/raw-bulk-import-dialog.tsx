import * as React from 'react'
import type { AxiosError } from 'axios'
import { useQueryClient } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { toast } from '@/components/ui/sonner'
import { FileDropzone } from '@/components/workbench/file-dropzone'
import {
  useCreateDatasetImport,
  useCancelDatasetImport,
} from '@/api/generated/raw/raw'
import { useCreateSourceFilesBulk } from '@/api/generated/artifacts/artifacts'
import type {
  RawDatasetImportResponse,
  RawDatasetImportResponseStatus,
  SourceFileResponse,
} from '@/api/generated/model'
import { invalidateRawDataset } from '@/lib/invalidate'
import { useIdempotencyKey } from '@/lib/requests'
import { parseProblem, stalenessAlert } from '@/lib/problems'
import {
  buildImportRequest,
  rowsAreValid,
  seedRowsFromUpload,
  validateRows,
  type BulkImportRow,
  type RowFieldErrors,
} from './raw-bulk-import'
import { RawBulkImportTable } from './raw-bulk-import-table'
import { IMPORT_TERMINAL, RawBulkImportStatus } from './raw-bulk-import-status'

export interface RawBulkImportDialogProps {
  /** The owning Raw workbench id (path parameter for the import POST). */
  rawId: string
  /** The study the workbench belongs to (path parameter for bulk upload). */
  studyId: string
  open: boolean
  onOpenChange: (open: boolean) => void
}

/** The discriminated phase of the two-phase flow. */
type Phase =
  | 'select'
  | 'uploading'
  | 'author'
  | 'submitting'
  | 'polling'
  | 'terminal'

const TERMINAL_STATUSES = new Set<RawDatasetImportResponseStatus>(IMPORT_TERMINAL)

/** Format a 413/415 bulk-upload failure into a user-facing message. */
function uploadErrorMessage(error: AxiosError): string | null {
  const status = error.response?.status
  if (status === 413) {
    return 'One or more selected files exceed the accepted size limit. Choose smaller files.'
  }
  if (status === 415) {
    return 'One or more selected files are an unsupported media type. Choose different files.'
  }
  return null
}

/**
 * Bulk-import dialog (two-phase flow): upload many source files, then author
 * one dataset per uploaded file and submit an all-or-nothing import that is
 * polled to a terminal status.
 *
 * Phases: `select` (multi-file picker) → `uploading` → `author` (editable
 * entry table + client validation) → `submitting` → `polling` → `terminal`.
 * Re-opening resets to `select`; uploaded files from a prior session are
 * discarded on close.
 */
export function RawBulkImportDialog({
  rawId,
  studyId,
  open,
  onOpenChange,
}: RawBulkImportDialogProps) {
  const qc = useQueryClient()

  const [phase, setPhase] = React.useState<Phase>('select')
  const [picked, setPicked] = React.useState<File[]>([])
  const [files, setFiles] = React.useState<SourceFileResponse[]>([])
  const [rows, setRows] = React.useState<BulkImportRow[]>([])
  const [importId, setImportId] = React.useState<string | null>(null)
  const [liveStatus, setLiveStatus] =
    React.useState<RawDatasetImportResponseStatus | null>(null)
  const [formError, setFormError] = React.useState<string | null>(null)
  const [serverRowErrors, setServerRowErrors] = React.useState<
    Record<string, RowFieldErrors>
  >({})

  // Reset to the initial phase whenever the dialog is (re)opened.
  React.useEffect(() => {
    if (open) {
      setPhase('select')
      setPicked([])
      setFiles([])
      setRows([])
      setImportId(null)
      setLiveStatus(null)
      setFormError(null)
      setServerRowErrors({})
    }
  }, [open])

  const bulkUpload = useCreateSourceFilesBulk()
  const idempotency = useIdempotencyKey()
  const createImport = useCreateDatasetImport({
    request: idempotency.requestConfig,
  })
  const cancelImport = useCancelDatasetImport()

  const validation = React.useMemo(
    () => validateRows(rows, files),
    [rows, files],
  )
  const canSubmit = phase === 'author' && rows.length > 0 && rowsAreValid(validation)

  // Merge client-side and server-side (422) per-row errors for display.
  const mergedRowErrors = React.useMemo(() => {
    const merged: Record<string, RowFieldErrors> = {}
    for (const [id, errs] of Object.entries(serverRowErrors)) {
      merged[id] = { ...errs }
    }
    for (const [id, errs] of Object.entries(validation.rowErrors)) {
      merged[id] = { ...merged[id], ...errs }
    }
    return merged
  }, [serverRowErrors, validation.rowErrors])

  function handleRowChange(id: string, patch: Partial<BulkImportRow>) {
    setRows((prev) =>
      prev.map((row) => (row.id === id ? { ...row, ...patch } : row)),
    )
    // Clear any server-side error on the edited row's touched fields.
    setServerRowErrors((prev) => {
      if (!prev[id]) return prev
      const next = { ...prev }
      delete next[id]
      return next
    })
  }

  async function handleUpload() {
    if (picked.length === 0) return
    setFormError(null)
    setPhase('uploading')
    try {
      const result = await bulkUpload.mutateAsync({
        studyId,
        data: { files: picked as unknown as string[] },
      })
      setFiles(result.items)
      setRows(seedRowsFromUpload(result.items))
      setPhase('author')
    } catch (error) {
      const axiosError = error as AxiosError
      setFormError(
        uploadErrorMessage(axiosError) ??
          parseProblem(axiosError).detail ??
          axiosError.message ??
          'Upload failed.',
      )
      // Retain the picked files so the user can retry the upload.
      setPhase('select')
    }
  }

  async function handleSubmit() {
    if (!canSubmit) return
    setFormError(null)
    setServerRowErrors({})
    idempotency.begin()
    setPhase('submitting')
    try {
      const response = await createImport.mutateAsync({
        rawId,
        data: buildImportRequest(rows),
      })
      setImportId(response.id)
      setLiveStatus(response.status)
      setPhase('polling')
    } catch (error) {
      const axiosError = error as AxiosError
      const status = axiosError.response?.status
      // Stay in `author` and retain all edits on any submit error.
      setPhase('author')
      if (status === 409 || status === 428) {
        setFormError(
          stalenessAlert(axiosError) ??
            'This import conflicts with the current state. Nothing was created.',
        )
        return
      }
      if (status === 422) {
        mapIssuesToRows(axiosError)
        return
      }
      setFormError(
        parseProblem(axiosError).detail ??
          axiosError.message ??
          'The import could not be submitted. Nothing was created.',
      )
    }
  }

  /**
   * Map a 422 problem's issues onto the matching rows by `dataset` (the dataset
   * code), falling back to a top-level list when an issue cannot be placed.
   */
  function mapIssuesToRows(error: AxiosError) {
    const problem = parseProblem(error)
    const issues = problem.issues ?? []
    const byCode = new Map<string, string>()
    for (const row of rows) {
      byCode.set(row.code.trim(), row.id)
    }
    const nextRowErrors: Record<string, RowFieldErrors> = {}
    const topLevel: string[] = []
    for (const issue of issues) {
      const dataset =
        typeof issue.dataset === 'string' ? issue.dataset : undefined
      const rowId = dataset ? byCode.get(dataset) : undefined
      const message = issue.message ?? issue.code ?? 'Invalid entry.'
      if (rowId) {
        nextRowErrors[rowId] = { ...nextRowErrors[rowId], code: message }
      } else {
        topLevel.push(message)
      }
    }
    setServerRowErrors(nextRowErrors)
    setFormError(
      topLevel.length > 0
        ? topLevel.join(' ')
        : problem.detail ??
            'The import was rejected. No datasets were created — correct the flagged entries and resubmit.',
    )
  }

  async function handleCancel() {
    if (!importId) return
    try {
      await cancelImport.mutateAsync({ importId })
    } catch (error) {
      // Best-effort: the server state remains authoritative; keep polling.
      const problem = parseProblem(error as AxiosError)
      toast.error(problem.title ?? 'Could not cancel the import', {
        description: problem.detail,
      })
    }
  }

  // Fire the dataset-list invalidation exactly once on a terminal `succeeded`.
  function handleTerminal(response: RawDatasetImportResponse) {
    setLiveStatus(response.status)
    setPhase('terminal')
    if (response.status === 'succeeded') {
      invalidateRawDataset(qc, rawId)
    }
  }

  const isUploading = phase === 'uploading'
  const isSubmitting = phase === 'submitting'
  const isBusy = isUploading || isSubmitting || phase === 'polling'
  const isNonTerminal =
    phase === 'polling' ||
    (liveStatus !== null && !TERMINAL_STATUSES.has(liveStatus))
  const showCancel = !!importId && isNonTerminal

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!isBusy) onOpenChange(next)
      }}
    >
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>Bulk upload datasets</DialogTitle>
          <DialogDescription>
            Upload multiple source files, then create one dataset per file in a
            single all-or-nothing import.
          </DialogDescription>
        </DialogHeader>

        {formError && (
          <div
            role="alert"
            className="border-destructive/50 bg-destructive/10 text-destructive rounded-md border px-3 py-2 text-sm"
          >
            {formError}
          </div>
        )}

        {/* Phase 1: multi-file picker. */}
        {(phase === 'select' || phase === 'uploading') && (
          <div className="flex flex-col gap-3">
            <FileDropzone
              multiple
              onFiles={(next) => setPicked(next)}
              disabled={phase === 'uploading'}
              ariaLabel="Bulk source file upload drop target"
              label={
                phase === 'uploading'
                  ? 'Uploading…'
                  : 'Drag source files here, or browse'
              }
              description="Each file becomes an immutable source file, then a dataset you author below."
            />
            {picked.length > 0 && (
              <ul className="text-muted-foreground flex flex-col gap-1 text-xs">
                {picked.map((file, index) => (
                  <li key={`${file.name}-${index}`}>
                    {file.name} ({file.size} bytes)
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {/* Phase 2: editable entry table. */}
        {(phase === 'author' || phase === 'submitting') && (
          <RawBulkImportTable
            rows={rows}
            files={files}
            rowErrors={mergedRowErrors}
            onChange={handleRowChange}
            disabled={phase === 'submitting'}
          />
        )}

        {/* Phase 3: inline status/polling + terminal outcome. */}
        {(phase === 'polling' || phase === 'terminal') && importId && (
          <RawBulkImportStatus
            importId={importId}
            onStatus={setLiveStatus}
            onTerminal={handleTerminal}
          />
        )}

        <DialogFooter>
          {showCancel && (
            <Button
              type="button"
              variant="outline"
              disabled={cancelImport.isPending}
              onClick={handleCancel}
            >
              {cancelImport.isPending && (
                <Loader2 className="animate-spin" aria-hidden />
              )}
              Cancel import
            </Button>
          )}

          {phase === 'select' || isUploading ? (
            <Button
              type="button"
              disabled={picked.length === 0 || isUploading}
              onClick={handleUpload}
            >
              {isUploading && <Loader2 className="animate-spin" aria-hidden />}
              Upload files
            </Button>
          ) : null}

          {phase === 'author' || isSubmitting ? (
            <Button
              type="button"
              disabled={!canSubmit || isSubmitting}
              onClick={handleSubmit}
            >
              {isSubmitting && <Loader2 className="animate-spin" aria-hidden />}
              Submit import
            </Button>
          ) : null}

          {phase === 'terminal' ? (
            <Button type="button" onClick={() => onOpenChange(false)}>
              Close
            </Button>
          ) : null}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export default RawBulkImportDialog
