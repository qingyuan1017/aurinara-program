import * as React from 'react'
import type { AxiosError } from 'axios'
import { useQueryClient } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import { PageHeader } from '@/components/layout/page-header'
import { EmptyState } from '@/components/data/states'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { toast } from '@/components/ui/sonner'
import { OperationRunner } from '@/components/workbench/operation-runner'
import { ArtifactList } from '@/components/workbench/artifact-list'
import type { ArtifactListItem } from '@/components/workbench/artifact-list'
import {
  OPERATION_POLL_PRESETS,
  type OperationQueryOpts,
  type OperationQueryState,
} from '@/hooks/use-operation-poll'
import {
  useCreateRawArtifacts,
  usePreviewRawArtifactFingerprint,
} from '@/api/generated/raw/raw'
import {
  getGetArtifactBuildQueryKey,
  useGetArtifactBuild,
} from '@/api/generated/artifact-builds/artifact-builds'
import type { ArtifactBuildResponse } from '@/api/generated/model'
import { invalidateRawOperationArtifacts } from '@/lib/invalidate'
import { useIdempotencyKey } from '@/lib/requests'
import { parseProblem } from '@/lib/problems'

/**
 * The four Raw artifact types a build may produce (Requirement 8.2). This is a
 * FIXED client constant, not derived from a backend list: the Artifacts panel
 * offers exactly these types and nothing else. Each entry carries a readable
 * label for the selection UI; the machine value is submitted verbatim in the
 * `artifact_types` body.
 */
export const RAW_ARTIFACT_TYPES = [
  { value: 'raw_dependency_manifest', label: 'Dependency manifest' },
  { value: 'raw_metadata_json', label: 'Metadata (JSON)' },
  { value: 'raw_data_dictionary_xlsx', label: 'Data dictionary (XLSX)' },
  { value: 'raw_validation_report_json', label: 'Validation report (JSON)' },
] as const

export type RawArtifactType = (typeof RAW_ARTIFACT_TYPES)[number]['value']

/**
 * Successful-terminal result slot. On mount for a completed build it reloads
 * the study-scoped artifact collection (and the aggregate) so newly produced
 * artifacts appear elsewhere, and refreshes the polled build resource, then
 * lists the produced artifacts with a per-row download (R8.4). Invalidation
 * lives in an effect so it never runs during the parent's render.
 */
function CompletedBuildResult({
  build,
  rawId,
  studyId,
}: {
  build: ArtifactBuildResponse
  rawId: string
  studyId: string
}) {
  const qc = useQueryClient()

  React.useEffect(() => {
    invalidateRawOperationArtifacts(qc, rawId, studyId)
    void qc.invalidateQueries({ queryKey: getGetArtifactBuildQueryKey(build.id) })
  }, [qc, rawId, studyId, build.id])

  const artifacts: ArtifactListItem[] = build.result_artifact_ids.map((id) => ({
    id,
  }))

  return (
    <ArtifactList
      artifacts={artifacts}
      title="Produced artifacts"
      emptyTitle="No artifacts produced"
      emptyDescription="The build completed but produced no downloadable artifacts."
    />
  )
}

export interface ArtifactsPanelProps {
  /** The owning Raw workbench id (path parameter for the build POST). */
  rawId: string
  /** The study the workbench belongs to (scopes artifact-collection invalidation). */
  studyId: string
}

/**
 * Adapts the generated {@link useGetArtifactBuild} query to the shape
 * {@link OperationRunner}/`useOperationPoll` expect: it forwards the computed
 * `enabled`/`refetchInterval` through `opts.query` so the generated query drives
 * the actual polling, and projects back `{ data, error }`.
 */
function useArtifactBuildOperation(
  buildId: string,
  opts: OperationQueryOpts,
): OperationQueryState<ArtifactBuildResponse> {
  const query = useGetArtifactBuild(buildId, { query: opts.query })
  return { data: query.data, error: query.error as AxiosError | null }
}

/**
 * Artifacts tab body for the Raw workbench detail (Requirement 8).
 *
 * Flow:
 * - Offer exactly the four fixed Raw artifact types ({@link RAW_ARTIFACT_TYPES},
 *   R8.1/R8.2); the submit control is disabled while no type is selected (R8.2).
 * - Start the build via `POST /api/v1/raw/{raw_id}/artifacts`
 *   ({@link useCreateRawArtifacts}) carrying the selected `artifact_types`, the
 *   `expected_input_fingerprint` resolved for that exact set from
 *   `POST /api/v1/raw/{raw_id}/artifacts/fingerprint`
 *   ({@link usePreviewRawArtifactFingerprint}), and a stable `Idempotency-Key`
 *   held across the automatic retries of the attempt (R8.3, R21.2).
 * - On the `202` build resource, poll `useGetArtifactBuild` at 1-5s with a 120s
 *   cap through {@link OperationRunner} (R8.3). On a `completed` terminal the
 *   produced artifacts list with a per-row download (R8.4); a `failed` terminal
 *   shows the typed failure object and presents no download (R8.5).
 */
export function ArtifactsPanel({ rawId, studyId }: ArtifactsPanelProps) {
  const [selected, setSelected] = React.useState<ReadonlySet<RawArtifactType>>(
    () => new Set(),
  )
  const [buildId, setBuildId] = React.useState<string | null>(null)

  // One stable Idempotency-Key per build attempt (R21.2). `begin()` mints a
  // fresh key when the user starts a new build.
  const idempotency = useIdempotencyKey()

  // Resolves the exact build-input fingerprint for the selected set from the
  // server right before the build so the value matches the backend staleness
  // check. The fingerprint depends on the selected artifact types, so it is
  // fetched per attempt rather than cached study-wide.
  const previewFingerprint = usePreviewRawArtifactFingerprint()

  const create = useCreateRawArtifacts({
    request: idempotency.requestConfig,
  })

  function toggle(type: RawArtifactType) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(type)) next.delete(type)
      else next.add(type)
      return next
    })
  }

  const noneSelected = selected.size === 0
  const canStart =
    !noneSelected && !previewFingerprint.isPending && !create.isPending

  async function handleStart() {
    if (noneSelected) return
    // Preserve the fixed-constant order rather than Set iteration order.
    const artifactTypes = RAW_ARTIFACT_TYPES.map((t) => t.value).filter((v) =>
      selected.has(v),
    )
    // New attempt: mint a fresh key so the build's automatic retries reuse it
    // while a distinct build gets a distinct key.
    idempotency.begin()
    try {
      const { input_fingerprint } = await previewFingerprint.mutateAsync({
        rawId,
        data: { artifact_types: artifactTypes },
      })
      const build = await create.mutateAsync({
        rawId,
        data: {
          artifact_types: artifactTypes,
          expected_input_fingerprint: input_fingerprint,
        },
      })
      setBuildId(build.id)
    } catch (error) {
      const problem = parseProblem(error as AxiosError)
      toast.error(problem.title ?? 'Artifact build could not be started', {
        description: problem.detail,
      })
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Artifacts"
        description={
          <>
            Generate Raw artifacts via{' '}
            <code>POST /api/v1/raw/{'{raw_id}'}/artifacts</code>.
          </>
        }
      />

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Artifact types</CardTitle>
          <CardDescription>
            Select one or more artifact types to build. The build resolves the
            input fingerprint for the selected set from the server before it
            starts.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <fieldset className="flex flex-col gap-2">
            <legend className="sr-only">Raw artifact types</legend>
            {RAW_ARTIFACT_TYPES.map((type) => {
              const id = `raw-artifact-${type.value}`
              return (
                <Label key={type.value} htmlFor={id} className="gap-2">
                  <input
                    id={id}
                    type="checkbox"
                    className="size-4"
                    checked={selected.has(type.value)}
                    onChange={() => toggle(type.value)}
                  />
                  <span>{type.label}</span>
                  <code className="text-muted-foreground text-xs">
                    {type.value}
                  </code>
                </Label>
              )
            })}
          </fieldset>

          <div>
            <Button
              type="button"
              onClick={handleStart}
              disabled={!canStart}
              title={
                noneSelected
                  ? 'Select at least one artifact type to build'
                  : undefined
              }
            >
              {(previewFingerprint.isPending || create.isPending) && (
                <Loader2 className="animate-spin" aria-hidden />
              )}
              Build artifacts
            </Button>
          </div>
        </CardContent>
      </Card>

      {buildId ? (
        <OperationRunner<ArtifactBuildResponse>
          operationLabel="artifact build"
          operationId={buildId}
          useGetOperation={useArtifactBuildOperation}
          intervalMs={OPERATION_POLL_PRESETS.fast.intervalMs}
          timeoutMs={OPERATION_POLL_PRESETS.fast.timeoutMs}
          renderResult={(build) => (
            <CompletedBuildResult
              build={build}
              rawId={rawId}
              studyId={studyId}
            />
          )}
        />
      ) : (
        <EmptyState
          title="No build started"
          description="Select artifact types and start a build to see produced artifacts here."
        />
      )}
    </div>
  )
}

export default ArtifactsPanel
