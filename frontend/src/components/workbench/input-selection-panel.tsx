import * as React from 'react'
import type { AxiosError } from 'axios'
import { useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
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
import {
  useGetLatestValidationRun,
  useGetRawDependencies,
  useListDatasets,
  useListRawAggregates,
} from '@/api/generated/raw/raw'
import { useListSourceFiles } from '@/api/generated/artifacts/artifacts'
import type {
  InputSelectionResponse,
  SdtmInputSelectionWrite,
  SelectedRawArtifact,
} from '@/api/generated/model'

/**
 * Load the schema's maximum page for Raw-version choices and source-file
 * resolution. Raw workbenches conventionally contain a bounded dataset set;
 * cursor navigation inside the single version selector is out of scope.
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

/** One automatically resolved source-file pin in the submitted selection. */
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
 * Seed the internal selection state from the current payload when one exists so
 * the user re-saves against the selected Raw version rather than a blank form. The
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

  // One Raw workbench/revision is the only user choice. Dataset and source-file
  // lists are resolver inputs: they are never exposed as independent choices.
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

  // The remaining exact pins are resolved from that version. The dependency
  // selection yields the fingerprint and the latest-validation-run resource
  // yields validation evidence for the same Raw revision.
  const dependenciesQuery = useGetRawDependencies(form.raw_id, {
    query: { enabled: !!studyId && !!form.raw_id },
  })
  const latestValidationRunQuery = useGetLatestValidationRun(form.raw_id, {
    query: { enabled: !!studyId && !!form.raw_id, retry: false },
  })

  const rawAggregates = rawAggregatesQuery.data?.items ?? []
  const sourceFiles = sourceFilesQuery.data?.items ?? []
  const datasets = datasetsQuery.data ?? []

  const selectedRawAggregate = rawAggregates.find(
    (item) => item.id === form.raw_id,
  )
  const selectedRawRevision =
    selectedRawAggregate?.revision ?? Number(form.raw_revision)
  const validationRunMatchesVersion =
    !!latestValidationRunQuery.data &&
    latestValidationRunQuery.data.raw_revision === selectedRawRevision
  const resolvedFingerprint = dependenciesQuery.data?.fingerprint ?? ''
  const resolvedValidationRunId = validationRunMatchesVersion
    ? latestValidationRunQuery.data?.validation_run_id ?? ''
    : ''
  // A 404 means "no successful validation run yet": a non-blocking prompt, not
  // an error (mirrors how the selection 404 is treated above).
  const latestValidationRunNotFound =
    (latestValidationRunQuery.error as AxiosError | null)?.response?.status ===
    404

  const activeDatasets = datasets.filter(
    (dataset) => !dataset.status || dataset.status === 'active',
  )
  const resolvedArtifacts: ArtifactRow[] = activeDatasets.flatMap((dataset) => {
    const sourceFile = sourceFiles.find(
      (file) => file.id === dataset.current_source_file_id,
    )
    return sourceFile
      ? [
          {
            dataset_code: dataset.code,
            artifact_id: sourceFile.artifact_id,
            checksum: sourceFile.sha256,
          },
        ]
      : []
  })
  const missingSourceFileCount =
    activeDatasets.length - resolvedArtifacts.length
  const resolutionIsLoading =
    !!form.raw_id &&
    (datasetsQuery.isLoading ||
      sourceFilesQuery.isLoading ||
      dependenciesQuery.isLoading ||
      latestValidationRunQuery.isLoading)
  const selectionIsReady =
    !!form.raw_id &&
    Number.isInteger(selectedRawRevision) &&
    selectedRawRevision > 0 &&
    activeDatasets.length > 0 &&
    missingSourceFileCount === 0 &&
    !!resolvedFingerprint &&
    !!resolvedValidationRunId &&
    !resolutionIsLoading

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

  /**
   * Pick one coherent Raw data version. All other exact values are discarded
   * immediately and re-resolved so pins from two versions cannot be mixed.
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
      validation_run_id: '',
      raw_dependency_fingerprint: '',
      source_artifacts: [],
    }))
  }

  async function handleSave(event: React.FormEvent) {
    event.preventDefault()
    if (!selectionIsReady) return
    try {
      await putSelection.mutateAsync({
        sdtmId,
        data: toWriteBody({
          raw_id: form.raw_id,
          raw_revision: String(selectedRawRevision),
          validation_run_id: resolvedValidationRunId,
          raw_dependency_fingerprint: resolvedFingerprint,
          source_artifacts: resolvedArtifacts,
        }),
      })
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
            <CardTitle className="text-base">Select Raw data version</CardTitle>
            <CardDescription>
              Choose one validated Raw version. Its active datasets, source
              artifacts, checksums, validation run, and dependencies are pinned
              automatically.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <div className="flex max-w-2xl flex-col gap-1.5">
              <Label htmlFor="is-raw-id">Raw data version</Label>
              <Select
                value={form.raw_id}
                onValueChange={selectRawAggregate}
              >
                <SelectTrigger id="is-raw-id">
                  <SelectValue placeholder="Select a Raw version" />
                </SelectTrigger>
                <SelectContent>
                  {/* Keep a seeded value visible even if its workbench is no
                        longer in the current list (e.g. retired). */}
                  {form.raw_id &&
                    !rawAggregates.some((item) => item.id === form.raw_id) && (
                      <SelectItem value={form.raw_id}>
                        Saved Raw version {form.raw_revision} (not in current
                        list)
                      </SelectItem>
                    )}
                  {rawAggregates.map((item) => (
                    <SelectItem key={item.id} value={item.id}>
                      {item.code} — {item.name} · revision {item.revision}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {form.raw_id && (
              <div
                role="status"
                className="text-muted-foreground border-input rounded-md border border-dashed px-3 py-2 text-sm"
              >
                {resolutionIsLoading
                  ? 'Resolving the datasets and evidence for this version…'
                  : latestValidationRunNotFound
                    ? 'Run and pass validation on this Raw version first.'
                    : latestValidationRunQuery.data && !validationRunMatchesVersion
                      ? 'The latest successful validation is for an older Raw revision. Revalidate this version first.'
                      : activeDatasets.length === 0
                        ? 'This Raw version has no active datasets to select.'
                        : missingSourceFileCount > 0
                          ? `${missingSourceFileCount} active dataset source file${missingSourceFileCount === 1 ? '' : 's'} could not be resolved.`
                          : !resolvedFingerprint
                            ? 'The dependency selection for this Raw version could not be resolved.'
                            : `${activeDatasets.length} active dataset${activeDatasets.length === 1 ? '' : 's'} and source artifact${activeDatasets.length === 1 ? '' : 's'} will be pinned automatically.`}
              </div>
            )}

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
            <Button
              type="submit"
              disabled={putSelection.isPending || !selectionIsReady}
            >
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
