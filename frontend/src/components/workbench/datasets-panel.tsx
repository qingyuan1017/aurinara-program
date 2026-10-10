import * as React from 'react'
import type { AxiosError } from 'axios'
import { useQueryClient } from '@tanstack/react-query'
import { FileUp, Loader2, Plus } from 'lucide-react'
import { PageHeader } from '@/components/layout/page-header'
import { ResourceTable } from '@/components/data/resource-table'
import type { ResourceColumn } from '@/components/data/resource-table'
import { EmptyState } from '@/components/data/states'
import { StatusBadge } from '@/components/data/status-badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
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
  FormDescription,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form'
import { toast } from '@/components/ui/sonner'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { FileDropzone } from '@/components/workbench/file-dropzone'
import { RawBulkImportDialog } from '@/components/workbench/raw-bulk-import-dialog'
import { PreviewPanel } from '@/components/workbench/preview-panel'
import { VariablesPanel } from '@/components/workbench/variables-panel'
import { ConfirmDialog } from '@/components/forms/confirm-dialog'
import {
  useCreateDataset,
  useListDatasets,
  usePatchDataset,
  useRetireDataset,
} from '@/api/generated/raw/raw'
import { useCreateSourceFile } from '@/api/generated/artifacts/artifacts'
import type {
  RawDatasetCreate,
  RawDatasetPatch,
  RawDatasetResponse,
  SourceFileResponse,
} from '@/api/generated/model'
import { invalidateRawDataset } from '@/lib/invalidate'
import { ifMatchRequest, jsonRequest } from '@/lib/requests'
import { parseProblem, stalenessAlert } from '@/lib/problems'

export interface DatasetsPanelProps {
  /** The owning Raw workbench id (path parameter for list/create). */
  rawId: string
  /** The study the workbench belongs to (path parameter for source-file upload). */
  studyId: string
}

/**
 * Datasets tab body for the Raw workbench detail (Requirement 3).
 *
 * Flows:
 * - List datasets ordered ascending by dataset code (R3.1). The backend
 *   `GET /api/v1/raw/{raw_id}/datasets` returns a bare array; it is sorted
 *   client-side by `code` to guarantee the ordering regardless of backend sort.
 * - Create a dataset (R3.4): first upload the immutable source file via a
 *   {@link FileDropzone} (drag OR browse — both funnel through the same
 *   multipart `POST /studies/{study_id}/source-files`, R3.2), then
 *   `POST /raw/{raw_id}/datasets` with code/label/source-file id. A 409
 *   `duplicate_raw_dataset_code` shows a uniqueness message and retains the
 *   form (R3.5); a 413/415 upload failure shows a size/media-type message and
 *   retains the form on both drop and browse (R3.3).
 * - Rebind a dataset to a corrected source file (R3.6): upload then
 *   `PATCH /raw-datasets/{dataset_id}` with `If-Match` for the dataset ETag.
 * - Retire a dataset (R3.7) behind an explicit {@link ConfirmDialog} that names
 *   the dataset: `DELETE /raw-datasets/{dataset_id}` with `If-Match`.
 * - A 412 on rebind/retire shows a concurrency message and reloads the current
 *   dataset revision before a retry (R3.8).
 */
export function DatasetsPanel({ rawId, studyId }: DatasetsPanelProps) {
  const qc = useQueryClient()

  const listQuery = useListDatasets(rawId)

  // Sort ascending by dataset code (R3.1); the backend returns a bare array.
  const datasets = React.useMemo(() => {
    const items = listQuery.data ?? []
    return [...items].sort((a, b) => a.code.localeCompare(b.code))
  }, [listQuery.data])

  const [createOpen, setCreateOpen] = React.useState(false)
  const [bulkOpen, setBulkOpen] = React.useState(false)
  const [rebindTarget, setRebindTarget] =
    React.useState<RawDatasetResponse | null>(null)
  const [retireTarget, setRetireTarget] =
    React.useState<RawDatasetResponse | null>(null)
  const [previewTarget, setPreviewTarget] =
    React.useState<RawDatasetResponse | null>(null)

  const columns: ResourceColumn<RawDatasetResponse>[] = [
    { key: 'code', header: 'Code' },
    { key: 'label', header: 'Label' },
    {
      key: 'status',
      header: 'Status',
      cell: (row) => <StatusBadge status={row.status} />,
    },
    { key: 'revision', header: 'Revision' },
  ]

  // Retire (R3.7): DELETE with the dataset ETag. On 412 (R3.8) reload the
  // dataset collection so the next attempt reads a fresh revision.
  const retire = useRetireDataset({
    mutation: {
      onSuccess: () => invalidateRawDataset(qc, rawId),
    },
    request: retireTarget ? ifMatchRequest(retireTarget.revision) : undefined,
  })

  async function handleRetire() {
    if (!retireTarget) return
    try {
      await retire.mutateAsync({ datasetId: retireTarget.id })
      toast.success(`Dataset ${retireTarget.code} retired.`)
      invalidateRawDataset(qc, rawId, retireTarget.id)
    } catch (error) {
      const status = (error as AxiosError).response?.status
      if (status === 412) {
        // Concurrency: reload the current revision before any retry (R3.8).
        invalidateRawDataset(qc, rawId, retireTarget.id)
      }
      // Re-throw so ConfirmDialog surfaces the concurrency message.
      throw error
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Datasets"
        description={
          <>
            Datasets from <code>GET /api/v1/raw/{'{raw_id}'}/datasets</code>,
            ordered by code.
          </>
        }
        actions={
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={() => setBulkOpen(true)}
            >
              <FileUp /> Bulk upload
            </Button>
            <Button size="sm" onClick={() => setCreateOpen(true)}>
              <Plus /> New dataset
            </Button>
          </div>
        }
      />

      <ResourceTable
        columns={columns}
        rows={datasets}
        getRowId={(row) => row.id}
        isLoading={listQuery.isLoading}
        isError={listQuery.isError}
        error={listQuery.error}
        resourceLabel="datasets"
        emptyState={
          <EmptyState
            title="No datasets yet"
            description="Create a dataset to bind an immutable source file."
          />
        }
        rowActions={(row) => (
          <div className="flex justify-end gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={() => setPreviewTarget(row)}
            >
              Open
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setRebindTarget(row)}
            >
              Rebind
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setRetireTarget(row)}
            >
              Retire
            </Button>
          </div>
        )}
      />

      <DatasetCreateDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        rawId={rawId}
        studyId={studyId}
      />

      <RawBulkImportDialog
        rawId={rawId}
        studyId={studyId}
        open={bulkOpen}
        onOpenChange={setBulkOpen}
      />

      <DatasetRebindDialog
        dataset={rebindTarget}
        onOpenChange={(open) => {
          if (!open) setRebindTarget(null)
        }}
        studyId={studyId}
        rawId={rawId}
      />

      <ConfirmDialog
        open={!!retireTarget}
        onOpenChange={(open) => {
          if (!open) setRetireTarget(null)
        }}
        title="Retire dataset"
        description={
          retireTarget ? (
            <>
              Retire dataset <strong>{retireTarget.code}</strong>
              {retireTarget.label ? ` (${retireTarget.label})` : ''}? This marks
              the dataset retired within the workbench.
            </>
          ) : null
        }
        confirmLabel="Retire dataset"
        destructive
        onConfirm={handleRetire}
        isPending={retire.isPending}
        error={retire.error}
      />

      {/*
        Dataset drill-in (R4 + R5): the Variables and Preview panels are mounted
        only while the sheet is open. The PreviewPanel's locally-held rows are
        discarded on close/unmount so they are never persisted beyond this view
        (R5.6). `key` on the dataset id resets panel state when switching
        datasets. The Variables panel receives the dataset `revision` so factual
        initialization can send the dataset ETag as `If-Match` (R4.6).
      */}
      <Sheet
        open={!!previewTarget}
        onOpenChange={(open) => {
          if (!open) setPreviewTarget(null)
        }}
      >
        <SheetContent
          side="right"
          className="w-full gap-0 overflow-y-auto p-6 sm:max-w-2xl"
        >
          <SheetHeader className="p-0">
            <SheetTitle>
              {previewTarget ? `Dataset ${previewTarget.code}` : 'Dataset'}
            </SheetTitle>
            <SheetDescription>
              {previewTarget
                ? 'Maintain variables and preview a bounded window of rows.'
                : null}
            </SheetDescription>
          </SheetHeader>
          {previewTarget && (
            <Tabs defaultValue="variables" className="mt-6">
              <TabsList>
                <TabsTrigger value="variables">Variables</TabsTrigger>
                <TabsTrigger value="preview">Preview</TabsTrigger>
              </TabsList>
              <TabsContent value="variables" className="mt-4">
                <VariablesPanel
                  key={`vars-${previewTarget.id}`}
                  datasetId={previewTarget.id}
                  datasetCode={previewTarget.code}
                  datasetRevision={previewTarget.revision}
                />
              </TabsContent>
              <TabsContent value="preview" className="mt-4">
                <PreviewPanel
                  key={`preview-${previewTarget.id}`}
                  datasetId={previewTarget.id}
                  datasetCode={previewTarget.code}
                />
              </TabsContent>
            </Tabs>
          )}
        </SheetContent>
      </Sheet>
    </div>
  )
}

/** Format a 413/415 upload failure into a user-facing message (R3.3). */
function uploadErrorMessage(error: AxiosError): string | null {
  const status = error.response?.status
  if (status === 413) {
    return 'The selected file exceeds the accepted size limit. Choose a smaller file.'
  }
  if (status === 415) {
    return 'The selected file is an unsupported media type. Choose a different file.'
  }
  return null
}

interface SourceFileFieldProps {
  studyId: string
  value: SourceFileResponse | null
  onUploaded: (file: SourceFileResponse) => void
  disabled?: boolean
}

/**
 * Shared source-file upload control used by both the create and rebind dialogs.
 *
 * A dropped file and a browsed file flow through the identical multipart
 * `POST` (R3.2), and a 413/415 is surfaced the same way on both paths (R3.3)
 * while the parent dialog form is retained so the user can pick another file.
 */
function SourceFileField({
  studyId,
  value,
  onUploaded,
  disabled,
}: SourceFileFieldProps) {
  const [uploadError, setUploadError] = React.useState<string | null>(null)

  const upload = useCreateSourceFile()

  async function handleFiles(files: File[]) {
    const file = files[0]
    if (!file) return
    setUploadError(null)
    try {
      // Both the drop and browse paths reach here identically, so the request
      // and its 413/415 handling never diverge (R3.2, R3.3).
      const result = await upload.mutateAsync({
        studyId,
        data: { file: file as unknown as string },
      })
      onUploaded(result)
    } catch (error) {
      const axiosError = error as AxiosError
      setUploadError(
        uploadErrorMessage(axiosError) ??
          parseProblem(axiosError).detail ??
          axiosError.message ??
          'Upload failed.',
      )
    }
  }

  return (
    <FormItem>
      <FormLabel>Source file</FormLabel>
      <FormControl>
        <div className="flex flex-col gap-2">
          <FileDropzone
            onFiles={handleFiles}
            disabled={disabled || upload.isPending}
            ariaLabel="Source file upload drop target"
            label={
              upload.isPending
                ? 'Uploading…'
                : 'Drag a source file here, or browse'
            }
            description="The file is stored as an immutable source file, then bound to the dataset."
          />
          {upload.isPending && (
            <div className="text-muted-foreground flex items-center gap-2 text-xs">
              <Loader2 className="size-3 animate-spin" /> Uploading source file…
            </div>
          )}
          {value && (
            <div className="text-muted-foreground text-xs">
              Bound to <span className="font-medium">{value.filename}</span> (
              {value.media_type})
            </div>
          )}
        </div>
      </FormControl>
      {uploadError && <FormMessage>{uploadError}</FormMessage>}
    </FormItem>
  )
}

interface DatasetCreateDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  rawId: string
  studyId: string
}

/**
 * Create a dataset (R3.4): upload a source file, then `POST` the dataset with
 * code/label/source-file id. A 409 `duplicate_raw_dataset_code` retains the
 * form and shows a uniqueness message (R3.5).
 */
function DatasetCreateDialog({
  open,
  onOpenChange,
  rawId,
  studyId,
}: DatasetCreateDialogProps) {
  const qc = useQueryClient()
  const [code, setCode] = React.useState('')
  const [label, setLabel] = React.useState('')
  const [sourceFile, setSourceFile] = React.useState<SourceFileResponse | null>(
    null,
  )
  const [formError, setFormError] = React.useState<string | null>(null)
  const [fieldErrors, setFieldErrors] = React.useState<{
    code?: string
    label?: string
    sourceFile?: string
  }>({})

  React.useEffect(() => {
    if (open) {
      setCode('')
      setLabel('')
      setSourceFile(null)
      setFormError(null)
      setFieldErrors({})
    }
  }, [open])

  const create = useCreateDataset({
    mutation: {
      onSuccess: () => invalidateRawDataset(qc, rawId),
    },
    request: jsonRequest(),
  })

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    const nextFieldErrors: typeof fieldErrors = {}
    if (!code.trim()) nextFieldErrors.code = 'Code is required.'
    if (!label.trim()) nextFieldErrors.label = 'Label is required.'
    if (!sourceFile) nextFieldErrors.sourceFile = 'Upload a source file first.'
    if (Object.keys(nextFieldErrors).length > 0) {
      setFieldErrors(nextFieldErrors)
      return
    }
    setFieldErrors({})
    setFormError(null)

    const body: RawDatasetCreate = {
      code: code.trim(),
      label: label.trim(),
      source_file_id: sourceFile!.id,
    }
    try {
      await create.mutateAsync({ rawId, data: body })
      toast.success(`Dataset ${body.code} created.`)
      onOpenChange(false)
    } catch (error) {
      const axiosError = error as AxiosError
      const problem = parseProblem(axiosError)
      if (
        axiosError.response?.status === 409 &&
        problem.code === 'duplicate_raw_dataset_code'
      ) {
        // Uniqueness conflict: retain the entered values (R3.5).
        setFieldErrors((prev) => ({
          ...prev,
          code: 'Dataset codes must be unique within this workbench.',
        }))
        return
      }
      setFormError(
        stalenessAlert(axiosError) ??
          problem.detail ??
          axiosError.message ??
          'Could not create the dataset.',
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
            <DialogTitle>New dataset</DialogTitle>
            <DialogDescription>
              Upload an immutable source file and bind it to a new dataset.
            </DialogDescription>
          </DialogHeader>

          {formError && (
            <div className="border-destructive/50 bg-destructive/10 text-destructive rounded-md border px-3 py-2 text-sm">
              {formError}
            </div>
          )}

          <FormItem>
            <FormLabel htmlFor="dataset-code">
              Code<span className="text-destructive"> *</span>
            </FormLabel>
            <FormControl>
              <Input
                id="dataset-code"
                value={code}
                aria-invalid={!!fieldErrors.code}
                onChange={(e) => {
                  setCode(e.target.value)
                  setFieldErrors((prev) => ({ ...prev, code: undefined }))
                }}
              />
            </FormControl>
            <FormMessage>{fieldErrors.code}</FormMessage>
          </FormItem>

          <FormItem>
            <FormLabel htmlFor="dataset-label">
              Label<span className="text-destructive"> *</span>
            </FormLabel>
            <FormControl>
              <Input
                id="dataset-label"
                value={label}
                aria-invalid={!!fieldErrors.label}
                onChange={(e) => {
                  setLabel(e.target.value)
                  setFieldErrors((prev) => ({ ...prev, label: undefined }))
                }}
              />
            </FormControl>
            <FormMessage>{fieldErrors.label}</FormMessage>
          </FormItem>

          <SourceFileField
            studyId={studyId}
            value={sourceFile}
            disabled={create.isPending}
            onUploaded={(file) => {
              setSourceFile(file)
              setFieldErrors((prev) => ({ ...prev, sourceFile: undefined }))
            }}
          />
          {fieldErrors.sourceFile && (
            <FormDescription className="text-destructive">
              {fieldErrors.sourceFile}
            </FormDescription>
          )}

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
              {create.isPending ? 'Creating…' : 'Create dataset'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

interface DatasetRebindDialogProps {
  dataset: RawDatasetResponse | null
  onOpenChange: (open: boolean) => void
  studyId: string
  rawId: string
}

/**
 * Rebind a dataset to a corrected source file (R3.6): upload a new source file
 * then `PATCH /raw-datasets/{dataset_id}` with the current dataset ETag as
 * `If-Match`. A 412 shows a concurrency message and reloads the current dataset
 * revision before a retry (R3.8).
 */
function DatasetRebindDialog({
  dataset,
  onOpenChange,
  studyId,
  rawId,
}: DatasetRebindDialogProps) {
  const qc = useQueryClient()
  const [sourceFile, setSourceFile] = React.useState<SourceFileResponse | null>(
    null,
  )
  const [formError, setFormError] = React.useState<string | null>(null)

  const open = !!dataset

  React.useEffect(() => {
    if (open) {
      setSourceFile(null)
      setFormError(null)
    }
  }, [open, dataset?.id])

  // Rebind to the latest known revision; after a 412 reload, the dialog closes
  // so the refreshed dataset drives the next attempt's ETag.
  const patch = usePatchDataset({
    mutation: {
      onSuccess: () => dataset && invalidateRawDataset(qc, rawId, dataset.id),
    },
    request: dataset ? ifMatchRequest(dataset.revision) : undefined,
  })

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    if (!dataset) return
    if (!sourceFile) {
      setFormError('Upload a corrected source file first.')
      return
    }
    setFormError(null)
    const body: RawDatasetPatch = { source_file_id: sourceFile.id }
    try {
      await patch.mutateAsync({ datasetId: dataset.id, data: body })
      toast.success(`Dataset ${dataset.code} rebound.`)
      onOpenChange(false)
    } catch (error) {
      const axiosError = error as AxiosError
      if (axiosError.response?.status === 412) {
        // Concurrency: reload the current dataset revision before retry (R3.8),
        // then discard this stale edit by closing the dialog.
        invalidateRawDataset(qc, rawId, dataset.id)
        setFormError(
          stalenessAlert(axiosError) ??
            'This dataset changed since you opened it. Reload and try again.',
        )
        return
      }
      setFormError(
        stalenessAlert(axiosError) ??
          parseProblem(axiosError).detail ??
          axiosError.message ??
          'Could not rebind the dataset.',
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
            <DialogTitle>Rebind dataset</DialogTitle>
            <DialogDescription>
              {dataset ? (
                <>
                  Bind dataset <strong>{dataset.code}</strong> to a corrected
                  immutable source file.
                </>
              ) : null}
            </DialogDescription>
          </DialogHeader>

          {formError && (
            <div className="border-destructive/50 bg-destructive/10 text-destructive rounded-md border px-3 py-2 text-sm">
              {formError}
            </div>
          )}

          <SourceFileField
            studyId={studyId}
            value={sourceFile}
            disabled={patch.isPending}
            onUploaded={setSourceFile}
          />

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={patch.isPending}
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={patch.isPending || !sourceFile}>
              {patch.isPending && <Loader2 className="animate-spin" />}
              {patch.isPending ? 'Rebinding…' : 'Rebind dataset'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
