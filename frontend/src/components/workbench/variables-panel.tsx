import * as React from 'react'
import type { AxiosError } from 'axios'
import { useQueryClient } from '@tanstack/react-query'
import { Loader2, Pencil, Plus, Trash2 } from 'lucide-react'
import { PageHeader } from '@/components/layout/page-header'
import { EmptyState, ErrorState } from '@/components/data/states'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { toast } from '@/components/ui/sonner'
import { SortableList } from '@/components/workbench/sortable-list'
import { ConfirmDialog } from '@/components/forms/confirm-dialog'
import {
  patchVariable,
  useCreateVariable,
  useDeleteVariable,
  useInitializeVariables,
  useListVariables,
  usePatchVariable,
} from '@/api/generated/raw/raw'
import type {
  RawVariablePatch,
  RawVariableResponse,
  RawVariableWrite,
  RawVariableWritePhysicalType,
} from '@/api/generated/model'
import { invalidateRawVariable } from '@/lib/invalidate'
import { ifMatchRequest, jsonRequest } from '@/lib/requests'
import { parseProblem, stalenessAlert } from '@/lib/problems'

/** Physical-type options accepted by the backend (`RawVariableWritePhysicalType`). */
const PHYSICAL_TYPES: Exclude<RawVariableWritePhysicalType, null>[] = [
  'string',
  'integer',
  'number',
  'boolean',
  'date',
  'datetime',
]

export interface VariablesPanelProps {
  /** The dataset whose variables are maintained (path parameter for list/create/initialize). */
  datasetId: string
  /** The dataset code, shown for context and in confirmation prompts. */
  datasetCode: string
  /**
   * The current dataset revision. Factual initialization sends this as the
   * dataset `If-Match` ETag (R4.6); after a 412/428 the parent reloads the
   * dataset so a fresh revision flows back in (R4.7).
   */
  datasetRevision: number
}

/**
 * Variables tab body for the Raw dataset drill-in (Requirement 4).
 *
 * Flows:
 * - List variables ordered ascending by ordinal (R4.1). The backend
 *   `GET /api/v1/raw-datasets/{dataset_id}/variables` returns a bare array; it
 *   is sorted client-side by `ordinal` to guarantee the ordering.
 * - Create a variable with the full maintained metadata (R4.2) via
 *   `useCreateVariable`.
 * - Edit a variable (R4.4) via `usePatchVariable` with the variable ETag as
 *   `If-Match`.
 * - Delete a variable (R4.5) behind an explicit {@link ConfirmDialog} that
 *   names the variable, sending the variable ETag as `If-Match`.
 * - Reorder ordinals (R4.4) via {@link SortableList} drag/keyboard/numeric
 *   fallback; each move persists through `usePatchVariable` with the moved
 *   variable's ETag as `If-Match`.
 * - Factual initialization (R4.6) via `useInitializeVariables` with the dataset
 *   ETag, showing created/filled counts and refreshing the list. A 412/428
 *   (R4.7) reloads the current dataset revision for a fresh ETag before retry.
 * - A 409 `duplicate_raw_variable` (R4.3) shows a uniqueness message and
 *   retains the entered form values.
 */
export function VariablesPanel({
  datasetId,
  datasetCode,
  datasetRevision,
}: VariablesPanelProps) {
  const qc = useQueryClient()

  const listQuery = useListVariables(datasetId)

  // Sort ascending by ordinal (R4.1); the backend returns a bare array.
  const variables = React.useMemo(() => {
    const items = listQuery.data ?? []
    return [...items].sort((a, b) => a.ordinal - b.ordinal)
  }, [listQuery.data])

  const [createOpen, setCreateOpen] = React.useState(false)
  const [editTarget, setEditTarget] = React.useState<RawVariableResponse | null>(
    null,
  )
  const [deleteTarget, setDeleteTarget] =
    React.useState<RawVariableResponse | null>(null)
  const [reorderError, setReorderError] = React.useState<string | null>(null)
  const [reordering, setReordering] = React.useState(false)

  // Reorder: each move PATCHes the single moved variable's ordinal with its own
  // ETag as If-Match (R4.4). Because every moved variable carries a distinct
  // ETag, the per-call `patchVariable` is invoked directly with
  // `ifMatchRequest(revision)` as the per-request axios config (the hook-level
  // `request` option cannot vary per move). The persisting request is identical
  // whether the move came from pointer drag, keyboard drag, the move buttons, or
  // the numeric field, because SortableList funnels all paths through onReorder.
  async function handleReorder(
    _next: RawVariableResponse[],
    moved: { item: RawVariableResponse; fromIndex: number; toIndex: number },
  ) {
    setReorderError(null)
    setReordering(true)
    // Ordinal is 1-based; the target index is 0-based.
    const nextOrdinal = moved.toIndex + 1
    const body: RawVariablePatch = { ordinal: nextOrdinal }
    try {
      await patchVariable(
        moved.item.id,
        body,
        ifMatchRequest(moved.item.revision),
      )
      invalidateRawVariable(qc, datasetId, moved.item.id)
    } catch (error) {
      const axiosError = error as AxiosError
      // A concurrency or uniqueness conflict reloads the list so the next move
      // reads fresh revisions/ordinals.
      invalidateRawVariable(qc, datasetId, moved.item.id)
      setReorderError(
        stalenessAlert(axiosError) ??
          parseProblem(axiosError).detail ??
          'Could not reorder the variable. The list was reloaded.',
      )
    } finally {
      setReordering(false)
    }
  }

  // Delete (R4.5): DELETE with the variable ETag. On 412 (concurrency) reload
  // the variable list so the next attempt reads a fresh revision.
  const remove = useDeleteVariable({
    mutation: {
      onSuccess: () => invalidateRawVariable(qc, datasetId),
    },
    request: deleteTarget ? ifMatchRequest(deleteTarget.revision) : undefined,
  })

  async function handleDelete() {
    if (!deleteTarget) return
    try {
      await remove.mutateAsync({ variableId: deleteTarget.id })
      toast.success(`Variable ${deleteTarget.name} deleted.`)
      invalidateRawVariable(qc, datasetId, deleteTarget.id)
    } catch (error) {
      if ((error as AxiosError).response?.status === 412) {
        invalidateRawVariable(qc, datasetId, deleteTarget.id)
      }
      throw error
    }
  }

  if (listQuery.isLoading) {
    return (
      <div className="text-muted-foreground flex items-center gap-2 text-sm">
        <Loader2 className="size-4 animate-spin" /> Loading variables…
      </div>
    )
  }
  if (listQuery.isError) {
    return (
      <ErrorState
        error={listQuery.error as AxiosError}
        resourceLabel="variables"
      />
    )
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Variables"
        description={
          <>
            Variables for <code>{datasetCode}</code> ordered by ordinal.
          </>
        }
        actions={
          <div className="flex gap-2">
            <InitializeButton
              datasetId={datasetId}
              datasetCode={datasetCode}
              datasetRevision={datasetRevision}
            />
            <Button size="sm" onClick={() => setCreateOpen(true)}>
              <Plus /> New variable
            </Button>
          </div>
        }
      />

      {reorderError && (
        <div
          role="alert"
          className="border-destructive/50 bg-destructive/10 text-destructive rounded-md border px-3 py-2 text-sm"
        >
          {reorderError}
        </div>
      )}

      {variables.length === 0 ? (
        <EmptyState
          title="No variables yet"
          description="Create a variable manually, or initialize from the bound source file."
        />
      ) : (
        <SortableList
          items={variables}
          getId={(variable) => variable.id}
          onReorder={handleReorder}
          disabled={reordering}
          ariaLabel="Dataset variables ordered by ordinal"
          renderItem={(variable) => (
            <VariableRow
              variable={variable}
              onEdit={() => setEditTarget(variable)}
              onDelete={() => setDeleteTarget(variable)}
            />
          )}
        />
      )}

      <VariableCreateDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        datasetId={datasetId}
        nextOrdinal={variables.length + 1}
      />

      <VariableEditDialog
        variable={editTarget}
        datasetId={datasetId}
        onOpenChange={(open) => {
          if (!open) setEditTarget(null)
        }}
      />

      <ConfirmDialog
        open={!!deleteTarget}
        onOpenChange={(open) => {
          if (!open) setDeleteTarget(null)
        }}
        title="Delete variable"
        description={
          deleteTarget ? (
            <>
              Delete variable <strong>{deleteTarget.name}</strong>
              {deleteTarget.label ? ` (${deleteTarget.label})` : ''}? This
              permanently removes the variable from the dataset.
            </>
          ) : null
        }
        confirmLabel="Delete variable"
        destructive
        onConfirm={handleDelete}
        isPending={remove.isPending}
        error={remove.error}
      />
    </div>
  )
}

interface VariableRowProps {
  variable: RawVariableResponse
  onEdit: () => void
  onDelete: () => void
}

/** A single reorderable variable row body (ordinal controls are added by SortableList). */
function VariableRow({ variable, onEdit, onDelete }: VariableRowProps) {
  return (
    <div className="flex items-center justify-between gap-3">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-medium">{variable.name}</span>
          {variable.physical_type && (
            <span className="text-muted-foreground text-xs">
              {variable.physical_type}
            </span>
          )}
        </div>
        {variable.label && (
          <div className="text-muted-foreground truncate text-xs">
            {variable.label}
          </div>
        )}
      </div>
      <div className="flex shrink-0 gap-1">
        <Button
          size="icon"
          variant="ghost"
          aria-label={`Edit ${variable.name}`}
          onClick={onEdit}
        >
          <Pencil className="size-4" aria-hidden="true" />
        </Button>
        <Button
          size="icon"
          variant="ghost"
          aria-label={`Delete ${variable.name}`}
          onClick={onDelete}
        >
          <Trash2 className="size-4" aria-hidden="true" />
        </Button>
      </div>
    </div>
  )
}

interface InitializeButtonProps {
  datasetId: string
  datasetCode: string
  datasetRevision: number
}

/**
 * Factual initialization (R4.6): `POST .../variables/initialize` with the
 * current dataset ETag as `If-Match`. On success the created/filled counts are
 * shown and the variable list is refreshed. A 412/428 (R4.7) reloads the
 * current dataset revision so a fresh ETag drives the retry.
 */
function InitializeButton({
  datasetId,
  datasetCode,
  datasetRevision,
}: InitializeButtonProps) {
  const qc = useQueryClient()
  const [error, setError] = React.useState<string | null>(null)

  const initialize = useInitializeVariables({
    mutation: {
      onSuccess: () => invalidateRawVariable(qc, datasetId),
    },
    // Send the current dataset ETag as If-Match (R4.6).
    request: ifMatchRequest(datasetRevision),
  })

  async function handleInitialize() {
    setError(null)
    try {
      const result = await initialize.mutateAsync({ datasetId })
      toast.success(
        `Initialized ${datasetCode}: ${result.created} created, ${result.filled} filled.`,
      )
    } catch (err) {
      const axiosError = err as AxiosError
      const status = axiosError.response?.status
      if (status === 412 || status === 428) {
        // Reload the dataset (and variable list) so a fresh dataset
        // revision/ETag flows back before retry (R4.7). invalidateRawVariable
        // invalidates the owning dataset detail key, refreshing its revision.
        invalidateRawVariable(qc, datasetId)
      }
      setError(
        stalenessAlert(axiosError) ??
          parseProblem(axiosError).detail ??
          'Could not initialize variables. Reload and try again.',
      )
    }
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <Button
        size="sm"
        variant="outline"
        onClick={handleInitialize}
        disabled={initialize.isPending}
      >
        {initialize.isPending && <Loader2 className="animate-spin" />}
        {initialize.isPending ? 'Initializing…' : 'Initialize from source'}
      </Button>
      {error && <span className="text-destructive text-xs">{error}</span>}
    </div>
  )
}

/** Local editable shape for the maintained metadata form fields. */
interface VariableFormState {
  name: string
  label: string
  physicalType: Exclude<RawVariableWritePhysicalType, null> | ''
  length: string
  precision: string
  ordinal: string
  role: string
  description: string
  terminologyReleaseId: string
  codelistCode: string
}

const EMPTY_FORM: VariableFormState = {
  name: '',
  label: '',
  physicalType: '',
  length: '',
  precision: '',
  ordinal: '',
  role: '',
  description: '',
  terminologyReleaseId: '',
  codelistCode: '',
}

/** Parse an integer field; empty/invalid yields `null` so it is omitted/cleared. */
function parseIntOrNull(value: string): number | null {
  const trimmed = value.trim()
  if (!trimmed) return null
  const parsed = Number.parseInt(trimmed, 10)
  return Number.isNaN(parsed) ? null : parsed
}

interface VariableCreateDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  datasetId: string
  nextOrdinal: number
}

/**
 * Create a variable (R4.2): `POST .../variables` with the maintained metadata
 * fields (name, label, physical type, length/precision, ordinal, role,
 * controlled terminology reference, description). A 409 `duplicate_raw_variable`
 * (R4.3) shows a uniqueness message and retains the entered values.
 */
function VariableCreateDialog({
  open,
  onOpenChange,
  datasetId,
  nextOrdinal,
}: VariableCreateDialogProps) {
  const qc = useQueryClient()
  const [form, setForm] = React.useState<VariableFormState>(EMPTY_FORM)
  const [formError, setFormError] = React.useState<string | null>(null)
  const [nameError, setNameError] = React.useState<string | null>(null)

  React.useEffect(() => {
    if (open) {
      setForm({ ...EMPTY_FORM, ordinal: String(nextOrdinal) })
      setFormError(null)
      setNameError(null)
    }
  }, [open, nextOrdinal])

  const create = useCreateVariable({
    mutation: {
      onSuccess: () => invalidateRawVariable(qc, datasetId),
    },
    request: jsonRequest(),
  })

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    if (!form.name.trim()) {
      setNameError('Source name is required.')
      return
    }
    const ordinal = parseIntOrNull(form.ordinal)
    if (ordinal === null || ordinal < 1) {
      setFormError('Ordinal must be a positive integer.')
      return
    }
    setFormError(null)
    setNameError(null)

    const body = buildWrite(form, ordinal)
    try {
      await create.mutateAsync({ datasetId, data: body })
      toast.success(`Variable ${body.name} created.`)
      onOpenChange(false)
    } catch (error) {
      const axiosError = error as AxiosError
      const problem = parseProblem(axiosError)
      if (
        axiosError.response?.status === 409 &&
        problem.code === 'duplicate_raw_variable'
      ) {
        // Uniqueness conflict: retain the entered values (R4.3).
        setFormError(
          'Variable names and ordinals must be unique within this dataset.',
        )
        return
      }
      setFormError(
        stalenessAlert(axiosError) ??
          problem.detail ??
          axiosError.message ??
          'Could not create the variable.',
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
      <DialogContent className="max-h-[90vh] overflow-y-auto">
        <form onSubmit={handleSubmit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>New variable</DialogTitle>
            <DialogDescription>
              Maintain the physical metadata for a dataset variable.
            </DialogDescription>
          </DialogHeader>

          {formError && (
            <div className="border-destructive/50 bg-destructive/10 text-destructive rounded-md border px-3 py-2 text-sm">
              {formError}
            </div>
          )}

          <VariableFields
            form={form}
            setForm={setForm}
            nameEditable
            nameError={nameError}
            onNameChange={() => setNameError(null)}
          />

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
              {create.isPending ? 'Creating…' : 'Create variable'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

interface VariableEditDialogProps {
  variable: RawVariableResponse | null
  datasetId: string
  onOpenChange: (open: boolean) => void
}

/**
 * Edit a variable (R4.4): `PATCH /raw-variables/{variable_id}` with the current
 * variable ETag as `If-Match`. A 409 `duplicate_raw_variable` (R4.3) shows a
 * uniqueness message and retains the edited values.
 */
function VariableEditDialog({
  variable,
  datasetId,
  onOpenChange,
}: VariableEditDialogProps) {
  const qc = useQueryClient()
  const open = !!variable
  const [form, setForm] = React.useState<VariableFormState>(EMPTY_FORM)
  const [formError, setFormError] = React.useState<string | null>(null)

  React.useEffect(() => {
    if (variable) {
      setForm(fromResponse(variable))
      setFormError(null)
    }
  }, [variable])

  const patch = usePatchVariable({
    mutation: {
      onSuccess: () =>
        variable && invalidateRawVariable(qc, datasetId, variable.id),
    },
    request: variable ? ifMatchRequest(variable.revision) : undefined,
  })

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    if (!variable) return
    const ordinal = parseIntOrNull(form.ordinal)
    if (ordinal === null || ordinal < 1) {
      setFormError('Ordinal must be a positive integer.')
      return
    }
    setFormError(null)

    const body = buildPatch(form, ordinal)
    try {
      await patch.mutateAsync({ variableId: variable.id, data: body })
      toast.success(`Variable ${variable.name} updated.`)
      onOpenChange(false)
    } catch (error) {
      const axiosError = error as AxiosError
      const problem = parseProblem(axiosError)
      if (
        axiosError.response?.status === 409 &&
        problem.code === 'duplicate_raw_variable'
      ) {
        // Uniqueness conflict: retain the edited values (R4.3).
        setFormError(
          'Variable names and ordinals must be unique within this dataset.',
        )
        return
      }
      if (axiosError.response?.status === 412) {
        // Concurrency: reload the variable before retry.
        invalidateRawVariable(qc, datasetId, variable.id)
      }
      setFormError(
        stalenessAlert(axiosError) ??
          problem.detail ??
          axiosError.message ??
          'Could not update the variable.',
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
      <DialogContent className="max-h-[90vh] overflow-y-auto">
        <form onSubmit={handleSubmit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>Edit variable</DialogTitle>
            <DialogDescription>
              {variable ? (
                <>
                  Update the maintained metadata for{' '}
                  <strong>{variable.name}</strong>.
                </>
              ) : null}
            </DialogDescription>
          </DialogHeader>

          {formError && (
            <div className="border-destructive/50 bg-destructive/10 text-destructive rounded-md border px-3 py-2 text-sm">
              {formError}
            </div>
          )}

          {/* Source name is the variable's natural key; it is shown read-only. */}
          <VariableFields form={form} setForm={setForm} nameEditable={false} />

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
              {patch.isPending ? 'Saving…' : 'Save variable'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

interface VariableFieldsProps {
  form: VariableFormState
  setForm: React.Dispatch<React.SetStateAction<VariableFormState>>
  nameEditable: boolean
  nameError?: string | null
  onNameChange?: () => void
}

/** The shared maintained-metadata field set used by create and edit (R4.2). */
function VariableFields({
  form,
  setForm,
  nameEditable,
  nameError,
  onNameChange,
}: VariableFieldsProps) {
  const numericType =
    form.physicalType === 'integer' || form.physicalType === 'number'

  return (
    <div className="grid gap-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <FormItem>
          <FormLabel htmlFor="variable-name">
            Source name<span className="text-destructive"> *</span>
          </FormLabel>
          <FormControl>
            <Input
              id="variable-name"
              value={form.name}
              readOnly={!nameEditable}
              aria-invalid={!!nameError}
              onChange={(e) => {
                setForm((prev) => ({ ...prev, name: e.target.value }))
                onNameChange?.()
              }}
            />
          </FormControl>
          <FormMessage>{nameError}</FormMessage>
        </FormItem>

        <FormItem>
          <FormLabel htmlFor="variable-ordinal">
            Ordinal<span className="text-destructive"> *</span>
          </FormLabel>
          <FormControl>
            <Input
              id="variable-ordinal"
              type="number"
              min={1}
              value={form.ordinal}
              onChange={(e) =>
                setForm((prev) => ({ ...prev, ordinal: e.target.value }))
              }
            />
          </FormControl>
        </FormItem>
      </div>

      <FormItem>
        <FormLabel htmlFor="variable-label">Label</FormLabel>
        <FormControl>
          <Input
            id="variable-label"
            value={form.label}
            onChange={(e) =>
              setForm((prev) => ({ ...prev, label: e.target.value }))
            }
          />
        </FormControl>
      </FormItem>

      <div className="grid gap-4 sm:grid-cols-3">
        <FormItem>
          <FormLabel>Physical type</FormLabel>
          <Select
            value={form.physicalType || undefined}
            onValueChange={(value) =>
              setForm((prev) => ({
                ...prev,
                physicalType: value as Exclude<
                  RawVariableWritePhysicalType,
                  null
                >,
              }))
            }
          >
            <SelectTrigger aria-label="Physical type">
              <SelectValue placeholder="Select a type" />
            </SelectTrigger>
            <SelectContent>
              {PHYSICAL_TYPES.map((type) => (
                <SelectItem key={type} value={type}>
                  {type}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormItem>

        <FormItem>
          <FormLabel htmlFor="variable-length">Length</FormLabel>
          <FormControl>
            <Input
              id="variable-length"
              type="number"
              min={0}
              value={form.length}
              onChange={(e) =>
                setForm((prev) => ({ ...prev, length: e.target.value }))
              }
            />
          </FormControl>
        </FormItem>

        <FormItem>
          <FormLabel htmlFor="variable-precision">Precision</FormLabel>
          <FormControl>
            <Input
              id="variable-precision"
              type="number"
              min={0}
              disabled={!numericType && form.physicalType !== ''}
              value={form.precision}
              onChange={(e) =>
                setForm((prev) => ({ ...prev, precision: e.target.value }))
              }
            />
          </FormControl>
        </FormItem>
      </div>

      <FormItem>
        <FormLabel htmlFor="variable-role">Role</FormLabel>
        <FormControl>
          <Input
            id="variable-role"
            value={form.role}
            onChange={(e) =>
              setForm((prev) => ({ ...prev, role: e.target.value }))
            }
          />
        </FormControl>
      </FormItem>

      <div className="grid gap-4 sm:grid-cols-2">
        <FormItem>
          <FormLabel htmlFor="variable-terminology-release">
            Terminology release
          </FormLabel>
          <FormControl>
            <Input
              id="variable-terminology-release"
              placeholder="Release id"
              value={form.terminologyReleaseId}
              onChange={(e) =>
                setForm((prev) => ({
                  ...prev,
                  terminologyReleaseId: e.target.value,
                }))
              }
            />
          </FormControl>
        </FormItem>

        <FormItem>
          <FormLabel htmlFor="variable-codelist">Codelist code</FormLabel>
          <FormControl>
            <Input
              id="variable-codelist"
              placeholder="Codelist code"
              value={form.codelistCode}
              onChange={(e) =>
                setForm((prev) => ({ ...prev, codelistCode: e.target.value }))
              }
            />
          </FormControl>
        </FormItem>
      </div>

      <FormItem>
        <FormLabel htmlFor="variable-description">Description</FormLabel>
        <FormControl>
          <Textarea
            id="variable-description"
            rows={3}
            value={form.description}
            onChange={(e) =>
              setForm((prev) => ({ ...prev, description: e.target.value }))
            }
          />
        </FormControl>
      </FormItem>
    </div>
  )
}

/** Build the terminology binding only when both required fields are present. */
function buildTerminologyBinding(form: VariableFormState) {
  const releaseId = form.terminologyReleaseId.trim()
  const codelistCode = form.codelistCode.trim()
  if (releaseId && codelistCode) {
    return { terminology_release_id: releaseId, codelist_code: codelistCode }
  }
  return undefined
}

/** Build the create body from the form state (R4.2). */
function buildWrite(form: VariableFormState, ordinal: number): RawVariableWrite {
  const body: RawVariableWrite = {
    name: form.name.trim(),
    ordinal,
  }
  if (form.label.trim()) body.label = form.label.trim()
  if (form.physicalType) body.physical_type = form.physicalType
  const length = parseIntOrNull(form.length)
  if (length !== null) body.length = length
  const precision = parseIntOrNull(form.precision)
  if (precision !== null) body.precision = precision
  if (form.role.trim()) body.role = form.role.trim()
  if (form.description.trim()) body.description = form.description.trim()
  const binding = buildTerminologyBinding(form)
  if (binding) body.terminology_binding = binding
  return body
}

/**
 * Build the patch body from the form state. Fields the user cleared are sent as
 * `null` so the backend clears them; the required `name` is not patched (it is
 * the variable's natural key and shown read-only in edit).
 */
function buildPatch(form: VariableFormState, ordinal: number): RawVariablePatch {
  return {
    label: form.label.trim() || null,
    physical_type: form.physicalType || null,
    length: parseIntOrNull(form.length),
    precision: parseIntOrNull(form.precision),
    ordinal,
    role: form.role.trim() || null,
    description: form.description.trim() || null,
    terminology_binding: buildTerminologyBinding(form) ?? null,
  }
}

/** Populate the form from an existing variable for editing. */
function fromResponse(variable: RawVariableResponse): VariableFormState {
  const binding =
    variable.terminology_binding &&
    typeof variable.terminology_binding === 'object'
      ? variable.terminology_binding
      : null
  return {
    name: variable.name,
    label: variable.label ?? '',
    physicalType: (variable.physical_type ??
      '') as VariableFormState['physicalType'],
    length: variable.length != null ? String(variable.length) : '',
    precision: variable.precision != null ? String(variable.precision) : '',
    ordinal: String(variable.ordinal),
    role: variable.role ?? '',
    description: variable.description ?? '',
    terminologyReleaseId:
      binding && 'terminology_release_id' in binding
        ? String(binding.terminology_release_id ?? '')
        : '',
    codelistCode:
      binding && 'codelist_code' in binding
        ? String(binding.codelist_code ?? '')
        : '',
  }
}
