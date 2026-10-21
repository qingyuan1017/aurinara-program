import * as React from 'react'
import type { AxiosError } from 'axios'
import { useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, FileCode2, Loader2, Save } from 'lucide-react'
import { toast } from 'sonner'

import { PageHeader } from '@/components/layout/page-header'
import { EmptyState, ErrorState } from '@/components/data/states'
import { StatusBadge } from '@/components/data/status-badge'
import { IssueList } from '@/components/data/issue-list'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import {
  TransferContext,
  DraggableItem,
  DropTarget,
} from '@/components/workbench/transfer'
import { OperationRunner } from '@/components/workbench/operation-runner'
import { ArtifactList } from '@/components/workbench/artifact-list'
import { useWorkbench } from '@/components/workbench/workbench-context'
import {
  useDownload,
  type DefineRenderVersion,
} from '@/hooks/use-download'
import {
  OPERATION_POLL_PRESETS,
  type OperationQueryOpts,
  type OperationQueryState,
} from '@/hooks/use-operation-poll'
import { useIdempotencyKey } from '@/lib/requests'
import { parseProblem, stalenessAlert } from '@/lib/problems'
import {
  invalidateSdtmSubResource,
  invalidateSdtmOperationArtifacts,
} from '@/lib/invalidate'
import {
  getGetDefineQueryKey,
  useGetDefine,
  useInitializeDefine,
  usePutDefine,
  useValidateDefine,
  useReconcileDefine,
  useCreateDefineArtifacts,
} from '@/api/generated/sdtm-define/sdtm-define'
import {
  getGetReconciliationQueryKey,
  useGetReconciliation,
} from '@/api/generated/reconciliation/reconciliation'
import { useGetArtifactBuild } from '@/api/generated/artifact-builds/artifact-builds'
import { useListArtifacts } from '@/api/generated/artifacts/artifacts'
import type {
  ArtifactBuildResponse,
  AppSdtmDefineDefineArtifactRequestVersionsItem as DefineArtifactRequestVersionsItem,
  AppSdtmDefineDefineResponse as DefineResponse,
  ReconciliationResponse,
  SdtmDefineInitialize,
  SdtmDefineModel,
  ValidationRunResponse,
} from '@/api/generated/model'

/**
 * The two Define-XML versions a render preview or an artifact build may target
 * (Requirements 18.5, 18.7). FIXED client constant — the panel offers exactly
 * these. The render `version` is submitted verbatim as the `2.0`/`2.1` query
 * param; the build submits the same literals in the `versions` body array.
 */
const DEFINE_VERSIONS: readonly DefineRenderVersion[] = ['2.0', '2.1'] as const

/** Terminal statuses for a Define reconciliation run (Requirement 18.6). */
const RECONCILE_TERMINAL_STATUSES = ['completed', 'failed'] as const

/**
 * The 409 problem codes the backend raises for Define staleness/conflict. Any
 * of them means the client's view of the current Define model is stale, so the
 * panel refreshes the current Define model before a retry (Requirement 18.9).
 */
const DEFINE_STALE_CODES = new Set([
  'define_specification_misaligned',
  'define_revision_mismatch',
  'define_output_selection_conflict',
  'stale_define_reconciliation_input',
])

export interface DefinePanelProps {
  /** The owning SDTM workbench id (path parameter for every Define call). */
  sdtmId: string
}

/** Inline destructive notice, consistent with the other SDTM panels. */
function Notice({
  title,
  detail,
  onReload,
  reloadLabel = 'Reload current Define model',
}: {
  title: string
  detail?: React.ReactNode
  onReload?: () => void
  reloadLabel?: string
}) {
  return (
    <div
      role="alert"
      className="border-destructive/50 text-destructive flex items-start gap-3 rounded-md border px-4 py-3 text-sm"
    >
      <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
      <div className="flex flex-col gap-1">
        <span className="font-medium">{title}</span>
        {detail && <span className="opacity-90">{detail}</span>}
        {onReload && (
          <button
            type="button"
            onClick={onReload}
            className="text-destructive mt-1 w-fit font-medium underline underline-offset-2"
          >
            {reloadLabel}
          </button>
        )}
      </div>
    </div>
  )
}

/**
 * Adapter around the generated reconciliation-run query so it matches the
 * minimal `(id, opts) => { data, error }` shape {@link OperationRunner} expects.
 */
function usePollDefineReconciliation(
  id: string,
  opts: OperationQueryOpts,
): OperationQueryState<ReconciliationResponse> {
  const query = useGetReconciliation(id, {
    query: {
      enabled: opts.query.enabled,
      refetchInterval: opts.query.refetchInterval,
      retry: false,
    },
  })
  return { data: query.data, error: query.error as AxiosError | null }
}

/** Adapter around the generated artifact-build query for {@link OperationRunner}. */
function usePollDefineBuild(
  id: string,
  opts: OperationQueryOpts,
): OperationQueryState<ArtifactBuildResponse> {
  const query = useGetArtifactBuild(id, {
    query: {
      enabled: opts.query.enabled,
      refetchInterval: opts.query.refetchInterval,
      retry: false,
    },
  })
  return { data: query.data, error: query.error as AxiosError | null }
}

/**
 * SDTM Define tab body (Requirement 18).
 *
 * Lifecycle, all driven by the single aggregate ETag from
 * {@link useWorkbench} for conditional writes:
 *
 * - View the current Define model via `GET /define` ({@link useGetDefine}); a
 *   `404 sdtm_define_not_found` renders an unsaved empty state (18.1).
 * - Initialize a first/next revision via `POST /define/initialize`
 *   ({@link useInitializeDefine}) with the aggregate ETag, the
 *   `expected_define_revision`, and the selected XPT `output_artifact_ids`. XPT
 *   artifacts are selectable by dnd-kit drag-to-select OR an equivalent
 *   checkbox fallback — both funnel into the identical initialize body (18.2).
 * - Save the authored model via `PUT /define` ({@link usePutDefine}) with the
 *   aggregate ETag (18.3).
 * - Validate via `POST /define/validate` ({@link useValidateDefine}), which
 *   returns a synchronous Validation_Run; render status, error+warning counts,
 *   and the full issue list (18.4).
 * - Render a non-persisting XML preview via `GET /define/render?version=2.0|2.1`
 *   through {@link useDownload.renderDefineXml} (18.5).
 * - Reconcile via `POST /define/reconcile` ({@link useReconcileDefine}) with the
 *   Define revision + fingerprint + a stable `Idempotency-Key`; poll the `202`
 *   run at a fixed 2s to a terminal status, capping at 300s (18.6).
 * - Build Define-XML artifacts via `POST /define/artifacts`
 *   ({@link useCreateDefineArtifacts}) with the selected version(s) + the
 *   canonical Define fingerprint + a stable `Idempotency-Key`; poll the `202`
 *   build at 2s to terminal/300s (18.7).
 * - A failed/timeout run or build is identified by {@link OperationRunner} with
 *   no artifact presented (18.8).
 * - A 409 staleness response refreshes the current Define model before a retry
 *   (18.9).
 */
export function DefinePanel({ sdtmId }: DefinePanelProps) {
  const qc = useQueryClient()
  const { ifMatch } = useWorkbench()
  const download = useDownload()

  const defineKey = React.useMemo(
    () => getGetDefineQueryKey(sdtmId),
    [sdtmId],
  )

  const query = useGetDefine(sdtmId, { query: { retry: false } })
  const define = query.data
  const loadStatus = (query.error as AxiosError | null)?.response?.status
  const loadCode =
    loadStatus === 404
      ? parseProblem(query.error as AxiosError).code
      : undefined
  const notSaved = loadStatus === 404 && loadCode === 'sdtm_define_not_found'

  // Persistent staleness notice shown after a 409 on any write. Cleared when
  // the user refreshes the current Define model before retrying (18.9).
  const [staleMessage, setStaleMessage] = React.useState<string | null>(null)

  /** Refresh the current Define model (18.9) and clear the stale notice. */
  const reloadDefine = React.useCallback(async () => {
    setStaleMessage(null)
    await qc.invalidateQueries({ queryKey: defineKey })
  }, [qc, defineKey])

  /** Common 409-staleness branch for every write; returns true if handled. */
  const handleStale = React.useCallback((error: AxiosError): boolean => {
    if (error.response?.status !== 409) return false
    const problem = parseProblem(error)
    if (problem.code && DEFINE_STALE_CODES.has(problem.code)) {
      setStaleMessage(
        problem.detail ??
          stalenessAlert(error) ??
          'The current Define model changed since you opened it. Refresh and try again.',
      )
      return true
    }
    return false
  }, [])

  if (query.isLoading) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-48 w-full" />
      </div>
    )
  }

  // Any load error other than the "not yet saved" 404.
  if (query.isError && !notSaved) {
    return <ErrorState error={query.error} resourceLabel="SDTM Define" />
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Define"
        description={
          <>
            Author, validate, render, reconcile, and build the version-neutral
            Define metadata via <code>/api/v1/sdtms/{'{sdtm_id}'}/define</code>.
          </>
        }
      />

      {staleMessage && (
        <Notice
          title="The Define model is out of date"
          detail={staleMessage}
          onReload={() => void reloadDefine()}
        />
      )}

      {/* Current model summary (or unsaved empty state). */}
      {notSaved || !define ? (
        <EmptyState
          title="No Define model yet"
          description="This SDTM workbench has no saved Define metadata. Initialize a model from the selected exact SDTM XPT artifacts below."
        />
      ) : (
        <DefineSummary define={define} />
      )}

      {/* Initialize (XPT drag-select + checkbox fallback). */}
      <InitializeCard
        sdtmId={sdtmId}
        define={define ?? null}
        ifMatch={ifMatch}
        onInitialized={async () => {
          await invalidateSdtmSubResource(qc, 'define', sdtmId)
          await reloadDefine()
        }}
        onStale={handleStale}
      />

      {/* Save (authored model, aggregate ETag). */}
      {define && (
        <SaveCard
          sdtmId={sdtmId}
          define={define}
          ifMatch={ifMatch}
          onSaved={async () => {
            await invalidateSdtmSubResource(qc, 'define', sdtmId)
          }}
          onStale={handleStale}
        />
      )}

      {/* Validate (synchronous Validation_Run). */}
      {define && <ValidateCard sdtmId={sdtmId} />}

      {/* Render a non-persisting XML preview. */}
      {define && <RenderCard sdtmId={sdtmId} download={download} />}

      {/* Reconcile (2s/300s poll). */}
      {define && (
        <ReconcileCard sdtmId={sdtmId} define={define} onStale={handleStale} />
      )}

      {/* Build Define-XML artifacts (2s/300s poll). */}
      {define && <BuildCard sdtmId={sdtmId} define={define} />}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Current model summary
// ---------------------------------------------------------------------------

function DefineSummary({ define }: { define: DefineResponse }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Current Define model</CardTitle>
        <CardDescription className="flex flex-wrap items-center gap-2">
          <Badge variant="outline">Revision {define.revision}</Badge>
          <Badge variant="secondary">
            Specification rev {define.specification_revision}
          </Badge>
          <Badge variant="outline">schema {define.schema_version}</Badge>
        </CardDescription>
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-3">
          <div>
            <dt className="text-muted-foreground text-xs">Define ID</dt>
            <dd className="text-sm break-all">{define.id}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground text-xs">Fingerprint</dt>
            <dd className="text-sm break-all">{define.fingerprint}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground text-xs">
              Selected XPT outputs
            </dt>
            <dd className="text-sm">{define.output_artifact_ids.length}</dd>
          </div>
        </dl>
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Initialize
// ---------------------------------------------------------------------------

interface InitializeCardProps {
  sdtmId: string
  define: DefineResponse | null
  ifMatch: ReturnType<typeof useWorkbench>['ifMatch']
  onInitialized: () => Promise<void> | void
  onStale: (error: AxiosError) => boolean
}

/**
 * Initialize a Define model from selected exact SDTM XPT artifacts
 * (Requirement 18.2).
 *
 * The XPT artifact ids are selectable two equivalent ways that produce the
 * IDENTICAL `output_artifact_ids` body:
 * - dnd-kit drag-to-select: drag an available XPT chip onto the "Selected" drop
 *   target (and drag a selected chip back to "Available" to deselect).
 * - checkbox fallback: toggle the same ids via the per-id checkbox.
 *
 * The initialize `POST` carries the aggregate ETag as `If-Match` and the
 * `expected_define_revision` (the current revision, or null when none exists).
 */
function InitializeCard({
  sdtmId,
  define,
  ifMatch,
  onInitialized,
  onStale,
}: InitializeCardProps) {
  const { studyId } = useWorkbench()
  const artifacts = useListArtifacts(studyId, { limit: 200 })
  const xptArtifacts = React.useMemo(
    () =>
      (artifacts.data?.items ?? []).filter(
        (artifact) =>
          artifact.artifact_type === 'sdtm_dataset_xpt' &&
          artifact.status === 'available',
      ),
    [artifacts.data?.items],
  )
  const artifactLabels = React.useMemo(
    () => new Map(xptArtifacts.map((artifact) => [artifact.id, artifact.filename])),
    [xptArtifacts],
  )
  const pool = React.useMemo(
    () =>
      Array.from(
        new Set([
          ...xptArtifacts.map((artifact) => artifact.id),
          ...(define?.output_artifact_ids ?? []),
        ]),
      ),
    [define?.output_artifact_ids, xptArtifacts],
  )
  const [selected, setSelected] = React.useState<ReadonlySet<string>>(
    () => new Set(define?.output_artifact_ids ?? []),
  )

  // Metadata fields the backend requires when no current model exists. When a
  // model exists the backend reuses its values, so these are only needed for a
  // first initialization.
  const [studyOid, setStudyOid] = React.useState('')
  const [metadataVersionOid, setMetadataVersionOid] = React.useState('')
  const [name, setName] = React.useState('')
  const [standardName, setStandardName] = React.useState('')
  const [standardVersion, setStandardVersion] = React.useState('')

  const idempotency = useIdempotencyKey()
  const initialize = useInitializeDefine({
    request: {
      headers: {
        ...ifMatch().headers,
        'Idempotency-Key': idempotency.key,
      },
    },
  })

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  // The pointer drop (DraggableItem -> DropTarget) funnels into the same
  // selection mutation as the checkbox: dropping onto "selected" selects,
  // dropping onto "available" deselects.
  function handleTransfer({
    sourceId,
    targetId,
  }: {
    sourceId: string
    targetId: string
  }) {
    if (targetId === 'define-selected') {
      setSelected((prev) => new Set(prev).add(sourceId))
    } else if (targetId === 'define-available') {
      setSelected((prev) => {
        const next = new Set(prev)
        next.delete(sourceId)
        return next
      })
    }
  }

  // Preserve pool order in the submitted body for a deterministic request.
  const outputArtifactIds = pool.filter((id) => selected.has(id))
  const firstInit = define === null
  const metadataComplete =
    !firstInit ||
    Boolean(
      studyOid.trim() &&
        metadataVersionOid.trim() &&
        name.trim() &&
        standardName.trim() &&
        standardVersion.trim(),
    )
  const canInitialize = metadataComplete && !initialize.isPending

  async function handleInitialize() {
    // When a model already exists the backend reuses its stored metadata and
    // ignores these fields, so send schema-valid placeholders; for the first
    // model the user-entered values are required and used.
    const body: SdtmDefineInitialize = {
      expected_define_revision: define?.revision ?? null,
      study_oid: firstInit ? studyOid.trim() : 'STUDY',
      metadata_version_oid: firstInit ? metadataVersionOid.trim() : 'MDV.1',
      name: firstInit ? name.trim() : 'Define',
      standard_name: firstInit ? standardName.trim() : 'SDTMIG',
      standard_version: firstInit ? standardVersion.trim() : '3.4',
      output_artifact_ids: outputArtifactIds,
    }
    try {
      await initialize.mutateAsync({ sdtmId, data: body })
      toast.success('Define model initialized.')
      await onInitialized()
    } catch (error) {
      const err = error as AxiosError
      if (onStale(err)) return
      if (err.response?.status === 412) {
        toast.error(
          stalenessAlert(err) ??
            'This workbench changed since you opened it. Reload and try again.',
        )
        return
      }
      toast.error(
        parseProblem(err).detail ?? err.message ?? 'Could not initialize Define.',
      )
    }
  }

  const availableIds = pool.filter((id) => !selected.has(id))
  const selectedIds = pool.filter((id) => selected.has(id))

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Initialize</CardTitle>
        <CardDescription>
          Select the exact SDTM XPT artifacts to bind, then initialize. Drag a
          chip between the lists or use the checkboxes — both build the same
          output selection.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {artifacts.isLoading ? (
          <Skeleton className="h-24 w-full" />
        ) : artifacts.isError ? (
          <ErrorState error={artifacts.error} resourceLabel="SDTM XPT artifacts" />
        ) : pool.length === 0 ? (
          <EmptyState
            title="No XPT artifacts"
            description="Build an SDTM XPT artifact first, then return here to select it."
          />
        ) : (
          <TransferContext onTransfer={handleTransfer}>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="flex flex-col gap-2">
                <span className="text-sm font-medium">Available</span>
                <DropTarget
                  id="define-available"
                  ariaLabel="Available XPT artifacts"
                  className="min-h-24"
                >
                  <div className="flex flex-col gap-2">
                    {availableIds.length === 0 ? (
                      <span className="text-muted-foreground text-xs">
                        All added artifacts are selected.
                      </span>
                    ) : (
                      availableIds.map((id) => (
                        <div key={id} className="flex items-center gap-2">
                          <input
                            type="checkbox"
                            className="size-4"
                            checked={false}
                            onChange={() => toggle(id)}
                            aria-label={`Select ${artifactLabels.get(id) ?? 'XPT artifact'}`}
                          />
                          <DraggableItem
                            id={id}
                            ariaLabel={`${artifactLabels.get(id) ?? 'XPT artifact'}, drag to select`}
                            className="max-w-full"
                          >
                            <span className="truncate">
                              {artifactLabels.get(id) ?? 'Previously selected artifact'}
                            </span>
                          </DraggableItem>
                        </div>
                      ))
                    )}
                  </div>
                </DropTarget>
              </div>

              <div className="flex flex-col gap-2">
                <span className="text-sm font-medium">
                  Selected ({selectedIds.length})
                </span>
                <DropTarget
                  id="define-selected"
                  ariaLabel="Selected XPT artifacts"
                  className="min-h-24"
                >
                  <div className="flex flex-col gap-2">
                    {selectedIds.length === 0 ? (
                      <span className="text-muted-foreground text-xs">
                        Drag an artifact here, or check it, to select.
                      </span>
                    ) : (
                      selectedIds.map((id) => (
                        <div key={id} className="flex items-center gap-2">
                          <input
                            type="checkbox"
                            className="size-4"
                            checked
                            onChange={() => toggle(id)}
                            aria-label={`Deselect ${artifactLabels.get(id) ?? 'XPT artifact'}`}
                          />
                          <DraggableItem
                            id={id}
                            ariaLabel={`${artifactLabels.get(id) ?? 'XPT artifact'}, drag to deselect`}
                            className="max-w-full"
                          >
                            <span className="truncate">
                              {artifactLabels.get(id) ?? 'Previously selected artifact'}
                            </span>
                          </DraggableItem>
                        </div>
                      ))
                    )}
                  </div>
                </DropTarget>
              </div>
            </div>
          </TransferContext>
        )}

        {firstInit && (
          <fieldset className="grid gap-3 sm:grid-cols-2">
            <legend className="mb-1 text-sm font-medium">
              Define metadata (required for the first model)
            </legend>
            <div className="flex flex-col gap-1">
              <Label htmlFor="define-study-oid">Study OID</Label>
              <Input
                id="define-study-oid"
                value={studyOid}
                onChange={(event) => setStudyOid(event.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1">
              <Label htmlFor="define-mdv-oid">Metadata version OID</Label>
              <Input
                id="define-mdv-oid"
                value={metadataVersionOid}
                onChange={(event) => setMetadataVersionOid(event.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1">
              <Label htmlFor="define-name">Name</Label>
              <Input
                id="define-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1">
              <Label htmlFor="define-standard-name">Standard name</Label>
              <Input
                id="define-standard-name"
                value={standardName}
                onChange={(event) => setStandardName(event.target.value)}
              />
            </div>
            <div className="flex flex-col gap-1">
              <Label htmlFor="define-standard-version">Standard version</Label>
              <Input
                id="define-standard-version"
                value={standardVersion}
                onChange={(event) => setStandardVersion(event.target.value)}
              />
            </div>
          </fieldset>
        )}

        <div>
          <Button
            type="button"
            onClick={handleInitialize}
            disabled={!canInitialize}
          >
            {initialize.isPending && (
              <Loader2 className="animate-spin" aria-hidden />
            )}
            Initialize Define
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Save
// ---------------------------------------------------------------------------

interface SaveCardProps {
  sdtmId: string
  define: DefineResponse
  ifMatch: ReturnType<typeof useWorkbench>['ifMatch']
  onSaved: () => Promise<void> | void
  onStale: (error: AxiosError) => boolean
}

/**
 * Save the authored Define model via `PUT /define` with the aggregate ETag
 * (Requirement 18.3). The model body is the currently loaded payload (the
 * version-neutral metadata model); this panel persists it unchanged so a save
 * is a round-trip of the authored structure under the current revision.
 */
function SaveCard({ sdtmId, define, ifMatch, onSaved, onStale }: SaveCardProps) {
  const put = usePutDefine({ request: ifMatch() })

  async function handleSave() {
    // The loaded payload is the version-neutral authored model; submit it as
    // the typed body under the current aggregate ETag.
    const body = define.payload as unknown as SdtmDefineModel
    try {
      await put.mutateAsync({ sdtmId, data: body })
      toast.success('Define model saved.')
      await onSaved()
    } catch (error) {
      const err = error as AxiosError
      if (onStale(err)) return
      if (err.response?.status === 412) {
        toast.error(
          stalenessAlert(err) ??
            'This Define model changed since you opened it. Reload and try again.',
        )
        return
      }
      toast.error(
        parseProblem(err).detail ?? err.message ?? 'Could not save Define.',
      )
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Save</CardTitle>
        <CardDescription>
          Persist the authored Define model under the current workbench
          revision.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Button type="button" onClick={handleSave} disabled={put.isPending}>
          {put.isPending && <Loader2 className="animate-spin" aria-hidden />}
          <Save /> Save Define
        </Button>
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Validate (synchronous)
// ---------------------------------------------------------------------------

/**
 * Validate the current Define model (Requirement 18.4). The backend returns a
 * synchronous Validation_Run (`succeeded`), with `error_count`/`warning_count`
 * reflecting the authored-vs-input mismatches and the full issue list.
 */
function ValidateCard({ sdtmId }: { sdtmId: string }) {
  const validate = useValidateDefine()
  const [run, setRun] = React.useState<ValidationRunResponse | null>(null)

  async function handleValidate() {
    try {
      const result = await validate.mutateAsync({ sdtmId })
      setRun(result)
    } catch (error) {
      const err = error as AxiosError
      toast.error(
        parseProblem(err).detail ?? err.message ?? 'Could not validate Define.',
      )
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Validate</CardTitle>
        <CardDescription>
          Validate the current Define revision against both pinned XSD versions
          and its authored inputs.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div>
          <Button
            type="button"
            onClick={handleValidate}
            disabled={validate.isPending}
          >
            {validate.isPending && (
              <Loader2 className="animate-spin" aria-hidden />
            )}
            Validate Define
          </Button>
        </div>

        {run && (
          <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge status={run.status} />
              <Badge variant="destructive">Error: {run.error_count}</Badge>
              <Badge variant="secondary">Warning: {run.warning_count}</Badge>
              <Badge variant="outline">Info: {run.info_count}</Badge>
            </div>
            <IssueList
              issues={run.issues}
              emptyTitle="No Define issues"
              emptyDescription="This validation run produced no issues."
            />
          </div>
        )}
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Render preview
// ---------------------------------------------------------------------------

/**
 * Render a non-persisting Define-XML preview (Requirement 18.5). The XML is
 * fetched through the binary bypass ({@link useDownload.renderDefineXml}) with
 * `version=2.0|2.1` and shown read-only — it is never written to disk and never
 * injected as HTML (rendered as escaped text).
 */
function RenderCard({
  sdtmId,
  download,
}: {
  sdtmId: string
  download: ReturnType<typeof useDownload>
}) {
  const [version, setVersion] = React.useState<DefineRenderVersion>('2.1')
  const [xml, setXml] = React.useState<string | null>(null)
  const [error, setError] = React.useState<AxiosError | null>(null)

  async function handleRender() {
    setError(null)
    try {
      const text = await download.renderDefineXml(sdtmId, version)
      setXml(text)
    } catch (err) {
      setXml(null)
      setError(err as AxiosError)
    }
  }

  const problem = error ? parseProblem(error) : null

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Render preview</CardTitle>
        <CardDescription>
          Render a validated revision through the pinned Define XSD as a
          non-persisting XML preview.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <fieldset className="flex flex-wrap items-center gap-4">
          <legend className="sr-only">Define-XML version</legend>
          {DEFINE_VERSIONS.map((entry) => {
            const id = `define-render-${entry}`
            return (
              <Label key={entry} htmlFor={id} className="gap-2">
                <input
                  id={id}
                  type="radio"
                  name="define-render-version"
                  className="size-4"
                  value={entry}
                  checked={version === entry}
                  onChange={() => setVersion(entry)}
                />
                <span>Define-XML {entry}</span>
              </Label>
            )
          })}
          <Button
            type="button"
            variant="outline"
            onClick={handleRender}
            disabled={download.isPending}
          >
            {download.isPending ? (
              <Loader2 className="animate-spin" aria-hidden />
            ) : (
              <FileCode2 aria-hidden />
            )}
            Render preview
          </Button>
        </fieldset>

        {problem && (
          <Notice
            title={problem.code ?? 'Could not render Define-XML'}
            detail={problem.detail ?? error?.message}
          />
        )}

        {xml !== null && (
          <pre
            className="bg-muted max-h-96 overflow-auto rounded-md border p-3 text-xs"
            aria-label={`Define-XML ${version} preview`}
          >
            <code>{xml}</code>
          </pre>
        )}
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Reconcile (2s / 300s poll)
// ---------------------------------------------------------------------------

interface ReconcileCardProps {
  sdtmId: string
  define: DefineResponse
  onStale: (error: AxiosError) => boolean
}

/**
 * Terminal Define-reconciliation result. A completed `202` reconciliation
 * produces a report artifact and advances the aggregate's latest-run state, so
 * on mount it reloads the study-scoped artifact collection and the aggregate
 * detail (R21.6) before rendering the per-severity counts and issue list.
 */
function DefineReconcileResult({
  run,
  sdtmId,
  studyId,
}: {
  run: ReconciliationResponse
  sdtmId: string
  studyId: string
}) {
  const qc = useQueryClient()
  React.useEffect(() => {
    invalidateSdtmOperationArtifacts(qc, sdtmId, studyId)
  }, [qc, sdtmId, studyId, run.id])

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge status={run.status} />
        <Badge variant="destructive">Error: {run.error_count}</Badge>
        <Badge variant="secondary">Warning: {run.warning_count}</Badge>
        <Badge variant="outline">Info: {run.info_count}</Badge>
      </div>
      <IssueList
        issues={run.issues as Record<string, unknown>[]}
        emptyTitle="No reconciliation issues"
        emptyDescription="This reconciliation run produced no issues."
      />
    </div>
  )
}

/**
 * Reconcile the Define outputs (Requirement 18.6). The `POST /define/reconcile`
 * carries the exact Define `revision` + `fingerprint` and a stable
 * `Idempotency-Key`; on `202` the run is polled at a fixed 2s to a terminal
 * status, capping at 300s. A 409 `stale_define_reconciliation_input` refreshes
 * the current Define model before a retry (18.9); a failed/timeout run is
 * identified by {@link OperationRunner} with no artifact presented (18.8).
 */
function ReconcileCard({ sdtmId, define, onStale }: ReconcileCardProps) {
  const qc = useQueryClient()
  const { studyId } = useWorkbench()
  const idempotency = useIdempotencyKey()
  const [runId, setRunId] = React.useState<string | null>(null)

  const reconcile = useReconcileDefine({
    request: idempotency.requestConfig,
  })

  async function handleStart() {
    idempotency.begin()
    setRunId(null)
    reconcile.reset()
    try {
      const run = await reconcile.mutateAsync({
        sdtmId,
        data: {
          define_revision: define.revision,
          expected_define_fingerprint: define.fingerprint,
        },
      })
      setRunId(run.id)
      void qc.invalidateQueries({
        queryKey: getGetReconciliationQueryKey(run.id),
      })
    } catch (error) {
      const err = error as AxiosError
      if (onStale(err)) return
      toast.error(
        parseProblem(err).detail ??
          err.message ??
          'Could not start Define reconciliation.',
      )
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Reconcile</CardTitle>
        <CardDescription>
          Queue an immutable comparison of the exact Define revision (
          {define.revision}) against its selected XPT outputs.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <OperationRunner<ReconciliationResponse>
          operationLabel="Define reconciliation run"
          operationId={runId}
          useGetOperation={usePollDefineReconciliation}
          intervalMs={OPERATION_POLL_PRESETS.build.intervalMs}
          timeoutMs={OPERATION_POLL_PRESETS.build.timeoutMs}
          terminalStatuses={RECONCILE_TERMINAL_STATUSES}
          onStart={handleStart}
          startLabel="Start reconciliation"
          startDisabled={reconcile.isPending}
          renderResult={(run) => (
            <DefineReconcileResult
              run={run}
              sdtmId={sdtmId}
              studyId={studyId}
            />
          )}
        />
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------------
// Build Define-XML artifacts (2s / 300s poll)
// ---------------------------------------------------------------------------

/**
 * Build immutable Define-XML artifacts (Requirement 18.7). The
 * `POST /define/artifacts` carries the selected version(s) and the canonical
 * Define `fingerprint` as `expected_input_fingerprint`, plus a stable
 * `Idempotency-Key`; on `202` the build is polled at a fixed 2s to
 * terminal/300s. A failed/timeout build is identified by {@link OperationRunner}
 * with no artifact presented (18.8).
 */
function BuildCard({
  sdtmId,
  define,
}: {
  sdtmId: string
  define: DefineResponse
}) {
  const { studyId } = useWorkbench()
  const idempotency = useIdempotencyKey()
  const [buildId, setBuildId] = React.useState<string | null>(null)
  // Default to both versions; the user may narrow the selection.
  const [versions, setVersions] = React.useState<ReadonlySet<DefineRenderVersion>>(
    () => new Set(DEFINE_VERSIONS),
  )

  const build = useCreateDefineArtifacts({
    request: idempotency.requestConfig,
  })

  function toggleVersion(version: DefineRenderVersion) {
    setVersions((prev) => {
      const next = new Set(prev)
      if (next.has(version)) next.delete(version)
      else next.add(version)
      return next
    })
  }

  const selectedVersions = DEFINE_VERSIONS.filter((v) => versions.has(v))
  const noneSelected = selectedVersions.length === 0

  async function handleStart() {
    if (noneSelected) return
    idempotency.begin()
    setBuildId(null)
    build.reset()
    try {
      const result = await build.mutateAsync({
        sdtmId,
        data: {
          expected_input_fingerprint: define.fingerprint,
          versions: selectedVersions as DefineArtifactRequestVersionsItem[],
        },
      })
      setBuildId(result.id)
    } catch (error) {
      const err = error as AxiosError
      toast.error(
        parseProblem(err).detail ??
          err.message ??
          'Could not start the Define artifact build.',
      )
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Build Define-XML</CardTitle>
        <CardDescription>
          Queue immutable Define-XML 2.0 and/or 2.1 artifacts from the current
          authored model (fingerprint pinned).
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <fieldset className="flex flex-wrap items-center gap-4">
          <legend className="sr-only">Define-XML versions to build</legend>
          {DEFINE_VERSIONS.map((entry) => {
            const id = `define-build-${entry}`
            return (
              <Label key={entry} htmlFor={id} className="gap-2">
                <input
                  id={id}
                  type="checkbox"
                  className="size-4"
                  checked={versions.has(entry)}
                  onChange={() => toggleVersion(entry)}
                />
                <span>Define-XML {entry}</span>
              </Label>
            )
          })}
        </fieldset>

        <OperationRunner<ArtifactBuildResponse>
          operationLabel="Define artifact build"
          operationId={buildId}
          useGetOperation={usePollDefineBuild}
          intervalMs={OPERATION_POLL_PRESETS.build.intervalMs}
          timeoutMs={OPERATION_POLL_PRESETS.build.timeoutMs}
          onStart={handleStart}
          startLabel="Build Define-XML"
          startDisabled={noneSelected || build.isPending}
          renderResult={(result) => (
            <CompletedBuild build={result} sdtmId={sdtmId} studyId={studyId} />
          )}
        />
      </CardContent>
    </Card>
  )
}

/**
 * Successful-terminal slot for a Define artifact build: reload the study-scoped
 * artifact collection and the aggregate so the new artifacts appear, then list
 * the produced Define-XML artifacts with a per-row download (18.7).
 */
function CompletedBuild({
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
    invalidateSdtmOperationArtifacts(qc, sdtmId, studyId)
  }, [qc, sdtmId, studyId])

  const items = build.result_artifact_ids.map((id) => ({ id }))

  return (
    <ArtifactList
      artifacts={items}
      title="Produced Define-XML artifacts"
      emptyTitle="No artifacts produced"
      emptyDescription="The build completed but produced no downloadable artifacts."
    />
  )
}

export default DefinePanel
