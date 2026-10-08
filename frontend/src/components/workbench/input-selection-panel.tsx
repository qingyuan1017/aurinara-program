import * as React from 'react'
import type { AxiosError } from 'axios'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Plus, Trash2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { EmptyState } from '@/components/data/states'
import { Skeleton } from '@/components/ui/skeleton'
import { IssueList } from '@/components/data/issue-list'
import { StalenessBanner } from '@/components/workbench/staleness-banner'
import { useWorkbench } from '@/components/workbench/workbench-context'
import { parseProblem } from '@/lib/problems'
import { invalidateSdtmSubResource } from '@/lib/invalidate'
import {
  getGetSdtmAggregateQueryKey,
  useGetInputSelection,
  useGetRawContext,
  usePutInputSelection,
} from '@/api/generated/sdtm/sdtm'
import { useListDatasets, useListRawAggregates } from '@/api/generated/raw/raw'
import { useListSourceFiles } from '@/api/generated/artifacts/artifacts'
import type {
  InputSelectionResponse,
  SdtmInputSelectionWrite,
  SelectedRawArtifact,
} from '@/api/generated/model'

/**
 * A single first page of options is loaded per dropdown (the schema max page
 * size). These lists are cursor-paginated, but a workbench realistically pins
 * from a small set, so in-dropdown pagination is intentionally out of scope —
 * mirroring how the study switcher consumes one `useListStudies` page.
 */
const OPTIONS_PAGE_SIZE = 200

/**
 * The 422 problem codes the backend returns when an input selection pins an
 * invalid Raw source artifact or a non-successful validation run (Requirement
 * 10.4). Either one renders the problem `detail` plus the `issues[]` list.
 */
const INPUT_SELECTION_INVALID_CODES = new Set([
  'sdtm_raw_artifact_invalid',
  'sdtm_raw_validation_invalid',
])

/** A single editable source-file artifact row in the form. */
interface ArtifactRow {
  dataset_code: string
  artifact_id: string
  checksum: string
}

const EMPTY_ARTIFACT: ArtifactRow = {
  dataset_code: '',
  artifact_id: '',
  checksum: '',
}

interface FormState {
  raw_id: string
  raw_revision: string
  validation_run_id: string
  raw_dependency_fingerprint: string
  source_artifacts: ArtifactRow[]
}

function emptyForm(): FormState {
  return {
    raw_id: '',
    raw_revision: '',
    validation_run_id: '',
    raw_dependency_fingerprint: '',
    source_artifacts: [{ ...EMPTY_ARTIFACT }],
  }
}

/**
 * Seed the editable form from the current selection payload when one exists so
 * the user re-saves against the pinned values rather than a blank form. The
 * payload is an opaque dictionary (the generator cannot model it), so each
 * field is read defensively.
 */
function formFromSelection(selection: InputSelectionResponse | undefined): FormState {
  if (!selection) return emptyForm()
  const payload = selection.payload as Record<string, unknown>
  const rawArtifacts = payload.source_artifacts
  const artifacts: ArtifactRow[] = Array.isArray(rawArtifacts)
    ? rawArtifacts.map((entry) => {
        const record = (entry ?? {}) as Record<string, unknown>
        return {
          dataset_code: String(record.dataset_code ?? ''),
          artifact_id: String(record.artifact_id ?? ''),
          checksum: String(record.checksum ?? ''),
        }
      })
    : []
  return {
    raw_id: String(payload.raw_id ?? ''),
    raw_revision:
      payload.raw_revision === undefined || payload.raw_revision === null
        ? ''
        : String(payload.raw_revision),
    validation_run_id: String(payload.validation_run_id ?? ''),
    raw_dependency_fingerprint: String(payload.raw_dependency_fingerprint ?? ''),
    source_artifacts: artifacts.length > 0 ? artifacts : [{ ...EMPTY_ARTIFACT }],
  }
}

function toWriteBody(form: FormState): SdtmInputSelectionWrite {
  const sourceArtifacts: SelectedRawArtifact[] = form.source_artifacts.map(
    (row) => ({
      dataset_code: row.dataset_code.trim(),
      artifact_id: row.artifact_id.trim(),
      checksum: row.checksum.trim(),
    }),
  )
  return {
    raw_id: form.raw_id.trim(),
    raw_revision: Number(form.raw_revision),
    validation_run_id: form.validation_run_id.trim(),
    raw_dependency_fingerprint: form.raw_dependency_fingerprint.trim(),
    source_artifacts: sourceArtifacts,
  }
}

/** Render the opaque resolved raw-context dictionary as a labeled field grid. */
function RawContextView({ data }: { data: Record<string, unknown> | undefined }) {
  const entries = React.useMemo(
    () => (data ? Object.entries(data) : []),
    [data],
  )
  if (entries.length === 0) {
    return (
      <EmptyState
        title="No resolved raw context"
        description="A resolved raw context appears once an input selection is saved."
      />
    )
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Resolved raw context</CardTitle>
        <CardDescription>
          Read from <code>GET /api/v1/sdtms/{'{sdtm_id}'}/raw-context</code>.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-1 gap-x-6 gap-y-2 sm:grid-cols-2">
          {entries.map(([key, value]) => (
            <div key={key} className="min-w-0">
              <dt className="text-muted-foreground text-xs">{key}</dt>
              <dd className="text-sm break-all">
                {typeof value === 'object'
                  ? JSON.stringify(value)
                  : String(value)}
              </dd>
            </div>
          ))}
        </dl>
      </CardContent>
    </Card>
  )
}

/**
 * SDTM Input selection panel (Requirement 10).
 *
 * - Saves the exact pinned Raw inputs via `PUT .../input-selection` carrying
 *   the SDTM workbench ETag as `If-Match` (10.1).
 * - Displays the current selection (revision + state) and the resolved raw
 *   context (10.2, 10.3).
 * - 422 `sdtm_raw_artifact_invalid` / `sdtm_raw_validation_invalid` render the
 *   problem `detail` plus the `issues[]` list (10.4).
 * - `input_refresh_required` renders a persistent staleness notice (10.5).
 * - 412 renders a concurrency message with a reload action that re-fetches the
 *   current SDTM workbench revision before a retry (10.6).
 */
export function InputSelectionPanel() {
  const { aggregate, ifMatch, studyId } = useWorkbench()
  const sdtmId = aggregate.id
  const qc = useQueryClient()

  const selectionQuery = useGetInputSelection(sdtmId)
  const rawContextQuery = useGetRawContext(sdtmId)

  const [form, setForm] = React.useState<FormState>(() => emptyForm())

  // Dropdown option sources. Each is backed by a real LIST endpoint and gated
  // so it only runs once the identifiers it needs are known. The raw-aggregate
  // and source-file lists are study-scoped; datasets require a chosen Raw
  // workbench (`form.raw_id`).
  const rawAggregatesQuery = useListRawAggregates(
    studyId,
    { limit: OPTIONS_PAGE_SIZE },
    { query: { enabled: !!studyId } },
  )
  const sourceFilesQuery = useListSourceFiles(
    studyId,
    { limit: OPTIONS_PAGE_SIZE },
    { query: { enabled: !!studyId } },
  )
  const datasetsQuery = useListDatasets(form.raw_id, {
    query: { enabled: !!form.raw_id },
  })

  const rawAggregates = rawAggregatesQuery.data?.items ?? []
  const sourceFiles = sourceFilesQuery.data?.items ?? []
  const datasets = datasetsQuery.data ?? []

  const selection = selectionQuery.data
  // A 404 means "no selection yet" — not an error worth blocking the panel on.
  const selectionNotFound =
    (selectionQuery.error as AxiosError | null)?.response?.status === 404

  // Seed the form from the loaded selection the first time it resolves (and
  // whenever its revision changes after a save/reload), without clobbering an
  // in-progress edit on every render.
  const seededRevisionRef = React.useRef<number | null>(null)
  React.useEffect(() => {
    if (selection && seededRevisionRef.current !== selection.revision) {
      seededRevisionRef.current = selection.revision
      setForm(formFromSelection(selection))
    }
  }, [selection])

  const putSelection = usePutInputSelection({
    mutation: {
      // Input-selection write: reload the selection, the aggregate (its
      // revision/ETag bumps), and the lineage/raw-context (inputs changed).
      onSuccess: () => invalidateSdtmSubResource(qc, 'input-selection', sdtmId),
    },
    // Rebinds to the latest aggregate revision on every render, so after a 412
    // reload the retry carries the fresh ETag (Requirement 10.6, 21.1).
    request: ifMatch(),
  })

  const saveError = putSelection.error as AxiosError | null
  const saveProblem = saveError ? parseProblem(saveError) : null
  const isConcurrencyConflict = saveError?.response?.status === 412
  const isInvalidSelection =
    saveError?.response?.status === 422 &&
    !!saveProblem?.code &&
    INPUT_SELECTION_INVALID_CODES.has(saveProblem.code)

  function updateField<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }))
  }

  function updateArtifact(index: number, key: keyof ArtifactRow, value: string) {
    setForm((prev) => ({
      ...prev,
      source_artifacts: prev.source_artifacts.map((row, i) =>
        i === index ? { ...row, [key]: value } : row,
      ),
    }))
  }

  /**
   * Pick a Raw workbench from the dropdown. The chosen aggregate's current
   * `revision` auto-fills `raw_revision` (still editable below so a seeded or
   * older pinned revision round-trips).
   */
  function selectRawAggregate(rawId: string) {
    // Radix can emit an empty value while reconciling a controlled value that
    // has no matching item yet; never let that blank a seeded selection.
    if (!rawId) return
    const aggregateMatch = rawAggregates.find((item) => item.id === rawId)
    setForm((prev) => ({
      ...prev,
      raw_id: rawId,
      raw_revision: aggregateMatch
        ? String(aggregateMatch.revision)
        : prev.raw_revision,
    }))
  }

  /**
   * Pick a source-file artifact for a row. The chosen file's `sha256`
   * auto-fills that row's `checksum` so it is pinned from a real value rather
   * than typed by hand.
   */
  function selectArtifact(index: number, artifactId: string) {
    // See `selectRawAggregate`: ignore an empty reconciliation value so a
    // seeded artifact id is never blanked.
    if (!artifactId) return
    const fileMatch = sourceFiles.find((file) => file.artifact_id === artifactId)
    setForm((prev) => ({
      ...prev,
      source_artifacts: prev.source_artifacts.map((row, i) =>
        i === index
          ? {
              ...row,
              artifact_id: artifactId,
              checksum: fileMatch ? fileMatch.sha256 : row.checksum,
            }
          : row,
      ),
    }))
  }

  function addArtifact() {
    setForm((prev) => ({
      ...prev,
      source_artifacts: [...prev.source_artifacts, { ...EMPTY_ARTIFACT }],
    }))
  }

  function removeArtifact(index: number) {
    setForm((prev) => ({
      ...prev,
      source_artifacts: prev.source_artifacts.filter((_, i) => i !== index),
    }))
  }

  async function handleSave(event: React.FormEvent) {
    event.preventDefault()
    try {
      await putSelection.mutateAsync({ sdtmId, data: toWriteBody(form) })
      toast.success('Input selection saved.')
    } catch {
      // Error state is rendered inline from `putSelection.error`; a 412 reload
      // is offered through the concurrency banner below. Swallow here so the
      // promise rejection does not surface as an unhandled rejection.
    }
  }

  // 10.6: on a concurrency conflict, reload the current SDTM workbench revision
  // (which flows a fresh ETag into `ifMatch()`) and reset the mutation error so
  // the user can retry against the current revision.
  async function handleReloadRevision() {
    await qc.invalidateQueries({ queryKey: getGetSdtmAggregateQueryKey(sdtmId) })
    putSelection.reset()
  }

  const selectionState = selection?.state

  return (
    <div className="flex flex-col gap-6">
      {/* 10.5: persistent notice while the pinned inputs are stale. */}
      <StalenessBanner
        state={selectionState === 'input_refresh_required' ? 'input_refresh_required' : null}
      />

      {/* 10.2: current selection summary (revision + state). */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Current input selection</CardTitle>
          <CardDescription>
            Read from <code>GET /api/v1/sdtms/{'{sdtm_id}'}/input-selection</code>.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {selectionQuery.isLoading ? (
            <Skeleton className="h-10 w-full" />
          ) : selectionNotFound || !selection ? (
            <p className="text-muted-foreground text-sm">
              No input selection has been saved yet.
            </p>
          ) : (
            <dl className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-4">
              <div>
                <dt className="text-muted-foreground text-xs">Revision</dt>
                <dd className="text-sm">{selection.revision}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground text-xs">State</dt>
                <dd className="text-sm">{selection.state}</dd>
              </div>
              <div className="col-span-2">
                <dt className="text-muted-foreground text-xs">Fingerprint</dt>
                <dd className="text-sm break-all">{selection.fingerprint}</dd>
              </div>
            </dl>
          )}
        </CardContent>
      </Card>

      {/* 10.1: save the exact pinned Raw inputs. */}
      <Card>
        <form onSubmit={handleSave} className="flex flex-col gap-6">
          <CardHeader>
            <CardTitle className="text-base">Pin Raw inputs</CardTitle>
            <CardDescription>
              Save the exact validated Raw revision and source-file artifacts
              this SDTM workbench consumes.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="is-raw-id">Raw workbench</Label>
                <Select
                  value={form.raw_id}
                  onValueChange={selectRawAggregate}
                >
                  <SelectTrigger id="is-raw-id">
                    <SelectValue placeholder="Select a Raw workbench" />
                  </SelectTrigger>
                  <SelectContent>
                    {/* Keep a seeded value visible even if its workbench is no
                        longer in the current list (e.g. retired). */}
                    {form.raw_id &&
                      !rawAggregates.some((item) => item.id === form.raw_id) && (
                        <SelectItem value={form.raw_id}>
                          {form.raw_id} (not in current list)
                        </SelectItem>
                      )}
                    {rawAggregates.map((item) => (
                      <SelectItem key={item.id} value={item.id}>
                        {item.code} — {item.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="is-raw-revision">Raw revision</Label>
                {/* Auto-filled from the selected Raw workbench's current
                    revision, but editable so an older revision can be pinned
                    and a seeded value round-trips. */}
                <Input
                  id="is-raw-revision"
                  type="number"
                  min={1}
                  value={form.raw_revision}
                  onChange={(e) => updateField('raw_revision', e.target.value)}
                  required
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="is-validation-run">Validation run ID</Label>
                {/* Free-text: no list-validation-runs endpoint exists in the
                    generated client to back a dropdown. */}
                <Input
                  id="is-validation-run"
                  value={form.validation_run_id}
                  onChange={(e) =>
                    updateField('validation_run_id', e.target.value)
                  }
                  required
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="is-fingerprint">Raw dependency fingerprint</Label>
                {/* Free-text: an opaque server-computed value with no typed or
                    list source to populate from. */}
                <Input
                  id="is-fingerprint"
                  value={form.raw_dependency_fingerprint}
                  onChange={(e) =>
                    updateField('raw_dependency_fingerprint', e.target.value)
                  }
                  required
                />
              </div>
            </div>

            <div className="flex flex-col gap-3">
              <div className="flex items-center justify-between">
                <Label>Source-file artifacts</Label>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={addArtifact}
                >
                  <Plus /> Add artifact
                </Button>
              </div>
              {form.source_artifacts.map((row, index) => (
                <div
                  key={index}
                  className="grid grid-cols-1 items-end gap-3 sm:grid-cols-[1fr_1fr_1fr_auto]"
                >
                  <div className="flex flex-col gap-1.5">
                    <Label
                      htmlFor={`is-artifact-dataset-${index}`}
                      className="text-xs"
                    >
                      Dataset code
                    </Label>
                    <Select
                      value={row.dataset_code}
                      onValueChange={(value) => {
                        // Ignore an empty reconciliation value so a seeded
                        // dataset code is never blanked (see selectRawAggregate).
                        if (!value) return
                        updateArtifact(index, 'dataset_code', value)
                      }}
                      disabled={!form.raw_id}
                    >
                      <SelectTrigger id={`is-artifact-dataset-${index}`}>
                        <SelectValue
                          placeholder={
                            form.raw_id
                              ? 'Select a dataset'
                              : 'Select a Raw workbench first'
                          }
                        />
                      </SelectTrigger>
                      <SelectContent>
                        {row.dataset_code &&
                          !datasets.some(
                            (dataset) => dataset.code === row.dataset_code,
                          ) && (
                            <SelectItem value={row.dataset_code}>
                              {row.dataset_code} (not in current list)
                            </SelectItem>
                          )}
                        {datasets.map((dataset) => (
                          <SelectItem key={dataset.id} value={dataset.code}>
                            {dataset.code} — {dataset.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <Label
                      htmlFor={`is-artifact-id-${index}`}
                      className="text-xs"
                    >
                      Artifact ID
                    </Label>
                    <Select
                      value={row.artifact_id}
                      onValueChange={(value) => selectArtifact(index, value)}
                    >
                      <SelectTrigger id={`is-artifact-id-${index}`}>
                        <SelectValue placeholder="Select a source file" />
                      </SelectTrigger>
                      <SelectContent>
                        {row.artifact_id &&
                          !sourceFiles.some(
                            (file) => file.artifact_id === row.artifact_id,
                          ) && (
                            <SelectItem value={row.artifact_id}>
                              {row.artifact_id} (not in current list)
                            </SelectItem>
                          )}
                        {sourceFiles.map((file) => (
                          <SelectItem
                            key={file.id}
                            value={file.artifact_id}
                          >
                            {file.filename}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <Label
                      htmlFor={`is-artifact-checksum-${index}`}
                      className="text-xs"
                    >
                      Checksum (SHA-256)
                    </Label>
                    {/* Derived from the chosen source file's `sha256`; shown
                        read-only. It still submits through `toWriteBody`. */}
                    <Input
                      id={`is-artifact-checksum-${index}`}
                      value={row.checksum}
                      readOnly
                      required
                    />
                  </div>
                  <Button
                    type="button"
                    size="icon"
                    variant="ghost"
                    aria-label={`Remove source artifact ${index + 1}`}
                    disabled={form.source_artifacts.length <= 1}
                    onClick={() => removeArtifact(index)}
                  >
                    <Trash2 />
                  </Button>
                </div>
              ))}
            </div>

            {/* 10.6: concurrency conflict message + reload action. */}
            {isConcurrencyConflict && (
              <div
                role="alert"
                className="border-destructive/50 text-destructive flex flex-col gap-1 rounded-md border px-4 py-3 text-sm"
              >
                <span className="font-medium">
                  This workbench changed since you opened it.
                </span>
                <span className="text-destructive/90">
                  Reload the current workbench revision before saving again.
                </span>
                <button
                  type="button"
                  onClick={handleReloadRevision}
                  className="text-destructive mt-1 w-fit font-medium underline underline-offset-2"
                >
                  Reload current revision
                </button>
              </div>
            )}

            {/* 10.4: invalid-artifact / invalid-validation 422 detail + issues. */}
            {isInvalidSelection && saveProblem && (
              <div className="flex flex-col gap-3">
                <div
                  role="alert"
                  className="border-destructive/50 text-destructive rounded-md border px-4 py-3 text-sm"
                >
                  {saveProblem.detail ?? 'The input selection is invalid.'}
                </div>
                {saveProblem.issues && saveProblem.issues.length > 0 && (
                  <IssueList issues={saveProblem.issues as Record<string, unknown>[]} />
                )}
              </div>
            )}

            {/* Any other failure: surface the problem detail/title. */}
            {saveError && !isConcurrencyConflict && !isInvalidSelection && (
              <div
                role="alert"
                className="border-destructive/50 text-destructive rounded-md border px-4 py-3 text-sm"
              >
                {saveProblem?.detail ?? saveError.message ?? 'Save failed.'}
              </div>
            )}
          </CardContent>
          <CardContent>
            <Button type="submit" disabled={putSelection.isPending}>
              {putSelection.isPending ? 'Saving…' : 'Save input selection'}
            </Button>
          </CardContent>
        </form>
      </Card>

      {/* 10.3: resolved raw context. */}
      {rawContextQuery.isLoading ? (
        <Skeleton className="h-24 w-full" />
      ) : (
        <RawContextView
          data={rawContextQuery.data as Record<string, unknown> | undefined}
        />
      )}
    </div>
  )
}
