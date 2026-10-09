import * as React from 'react'
import type { AxiosError } from 'axios'
import { useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Loader2 } from 'lucide-react'

import { PageHeader } from '@/components/layout/page-header'
import { EmptyState } from '@/components/data/states'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { toast } from '@/components/ui/sonner'
import { OperationRunner } from '@/components/workbench/operation-runner'
import { ArtifactList } from '@/components/workbench/artifact-list'
import type { ArtifactListItem } from '@/components/workbench/artifact-list'
import { useWorkbench } from '@/components/workbench/workbench-context'
import {
  OPERATION_POLL_PRESETS,
  type OperationQueryOpts,
  type OperationQueryState,
} from '@/hooks/use-operation-poll'
import {
  useCompileSdtm,
  useCreateSdtmArtifacts,
  useGetInputSelection,
  useListSdtmPlans,
} from '@/api/generated/sdtm/sdtm'
import {
  getGetArtifactBuildQueryKey,
  useGetArtifactBuild,
} from '@/api/generated/artifact-builds/artifact-builds'
import type { ArtifactBuildResponse } from '@/api/generated/model'
import { invalidateSdtmOperationArtifacts } from '@/lib/invalidate'
import { useIdempotencyKey } from '@/lib/requests'
import { parseProblem } from '@/lib/problems'

/**
 * The three compiler backends a compile may target (Requirement 15.1). The
 * machine `value` is submitted verbatim in the `backend` body field (the
 * backend validates it against `^(python|r|sas)$`); the `label` drives the
 * selection UI.
 */
export const COMPILE_BACKENDS = [
  { value: 'python', label: 'Python' },
  { value: 'r', label: 'R' },
  { value: 'sas', label: 'SAS' },
] as const

export type CompileBackend = (typeof COMPILE_BACKENDS)[number]['value']

/**
 * The extra SDTM metadata/report artifact types a build may produce beyond the
 * compiled program (Requirement 15.5). FIXED client constant, not derived from
 * a backend list: the panel offers exactly these types. The machine value is
 * submitted verbatim in the `artifact_types` body.
 */
export const SDTM_ARTIFACT_TYPES = [
  { value: 'sdtm_metadata_json', label: 'Metadata (JSON)' },
  { value: 'sdtm_validation_report_json', label: 'Validation report (JSON)' },
] as const

export type SdtmArtifactType = (typeof SDTM_ARTIFACT_TYPES)[number]['value']

/**
 * Successful-terminal result slot for a compile/artifact build. On mount for a
 * completed build it reloads the study-scoped artifact collection (and the
 * aggregate) so newly produced artifacts appear elsewhere, refreshes the polled
 * build resource, then lists the produced program artifacts (R15.2). A `failed`
 * terminal never reaches here — {@link OperationRunner} renders the typed
 * failure and presents no partial artifacts instead (R15.3).
 */
function CompletedBuildResult({
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
    void qc.invalidateQueries({ queryKey: getGetArtifactBuildQueryKey(build.id) })
  }, [qc, sdtmId, studyId, build.id])

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

/** Inline destructive notice (same shape as the input-selection panel). */
function CompileNotice({
  title,
  detail,
}: {
  title: string
  detail?: React.ReactNode
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
      </div>
    </div>
  )
}

export interface CompilePanelProps {
  /** The owning SDTM workbench id (path parameter for the compile/build POSTs). */
  sdtmId: string
}

/**
 * SDTM Compile & artifacts tab body (Requirement 15).
 *
 * Flow:
 * - Compile the aligned plan into one backend (`python`/`r`/`sas`) via
 *   `POST /api/v1/sdtms/{sdtm_id}/compile` ({@link useCompileSdtm}) carrying the
 *   selected `backend`, the pinned `expected_input_fingerprint` (the current
 *   input-selection fingerprint), and a stable `Idempotency-Key` held across the
 *   automatic retries of the attempt (R15.1, R21.2).
 * - On the `202` build resource, poll `useGetArtifactBuild` at 1-5s with a 120s
 *   cap through {@link OperationRunner} (R15.2). On a `completed` terminal the
 *   produced program artifacts list with a per-row download; a `failed` terminal
 *   shows the typed failure object and presents no partial artifacts (R15.3).
 * - A `409 backend_capability_missing` on compile shows that the selected
 *   backend cannot implement the declared semantics (R15.4).
 * - Separately, extra SDTM metadata/report artifact types are built via
 *   `POST /api/v1/sdtms/{sdtm_id}/artifacts` ({@link useCreateSdtmArtifacts})
 *   with the same pinned fingerprint and its own `Idempotency-Key` (R15.5).
 *
 * The pinned input fingerprint is the current input-selection fingerprint; both
 * POSTs are rejected server-side if it no longer matches, which the start
 * errors surface.
 */
export function CompilePanel({ sdtmId }: CompilePanelProps) {
  const { studyId } = useWorkbench()

  const selectionQuery = useGetInputSelection(sdtmId)
  const inputFingerprint = selectionQuery.data?.fingerprint ?? null
  const selectionNotFound =
    (selectionQuery.error as AxiosError | null)?.response?.status === 404

  // Compilation is per-domain: the compile request pins the exact domain whose
  // aligned plan is compiled. Resolve the available domains from the plan head
  // list and let the user pick one.
  const plansQuery = useListSdtmPlans(sdtmId)
  const planHeads = plansQuery.data?.items ?? []
  const [domainCode, setDomainCode] = React.useState<string | null>(null)
  const activeDomain =
    domainCode !== null && planHeads.some((head) => head.domain === domainCode)
      ? domainCode
      : (planHeads[0]?.domain ?? null)

  // --- Compile (one backend -> generated program) ---
  const [backend, setBackend] = React.useState<CompileBackend>('python')
  const [compileBuildId, setCompileBuildId] = React.useState<string | null>(null)
  const compileIdempotency = useIdempotencyKey()
  const compile = useCompileSdtm({
    request: compileIdempotency.requestConfig,
  })

  const compileError = compile.error as AxiosError | null
  const compileProblem = compileError ? parseProblem(compileError) : null
  const isCapabilityMissing =
    compileError?.response?.status === 409 &&
    compileProblem?.code === 'backend_capability_missing'

  const canCompile =
    inputFingerprint !== null && activeDomain !== null && !compile.isPending

  async function handleCompile() {
    if (inputFingerprint === null || activeDomain === null) return
    // New attempt: mint a fresh key so the compile's automatic retries reuse it
    // while a distinct compile gets a distinct key.
    compileIdempotency.begin()
    try {
      const build = await compile.mutateAsync({
        sdtmId,
        data: {
          backend,
          expected_input_fingerprint: inputFingerprint,
          domain_code: activeDomain,
        },
      })
      setCompileBuildId(build.id)
    } catch (error) {
      const axiosError = error as AxiosError
      const problem = parseProblem(axiosError)
      // The 409 capability-missing case renders inline below; only toast other
      // start failures (invalid fingerprint, etc.).
      if (
        !(
          axiosError.response?.status === 409 &&
          problem.code === 'backend_capability_missing'
        )
      ) {
        toast.error(problem.title ?? 'Compile could not be started', {
          description: problem.detail,
        })
      }
    }
  }

  // --- Extra metadata/report artifact types (separate build) ---
  const [selectedTypes, setSelectedTypes] = React.useState<
    ReadonlySet<SdtmArtifactType>
  >(() => new Set())
  const [artifactBuildId, setArtifactBuildId] = React.useState<string | null>(
    null,
  )
  const artifactIdempotency = useIdempotencyKey()
  const createArtifacts = useCreateSdtmArtifacts({
    request: artifactIdempotency.requestConfig,
  })

  function toggleType(type: SdtmArtifactType) {
    setSelectedTypes((prev) => {
      const next = new Set(prev)
      if (next.has(type)) next.delete(type)
      else next.add(type)
      return next
    })
  }

  const noneSelected = selectedTypes.size === 0
  const canBuildArtifacts =
    !noneSelected && inputFingerprint !== null && !createArtifacts.isPending

  async function handleBuildArtifacts() {
    if (noneSelected || inputFingerprint === null) return
    artifactIdempotency.begin()
    try {
      const build = await createArtifacts.mutateAsync({
        sdtmId,
        data: {
          // Preserve the fixed-constant order rather than Set iteration order.
          artifact_types: SDTM_ARTIFACT_TYPES.map((t) => t.value).filter((v) =>
            selectedTypes.has(v),
          ),
          expected_input_fingerprint: inputFingerprint,
        },
      })
      setArtifactBuildId(build.id)
    } catch (error) {
      const problem = parseProblem(error as AxiosError)
      toast.error(problem.title ?? 'Artifact build could not be started', {
        description: problem.detail,
      })
    }
  }

  const fingerprintUnavailable = selectionNotFound || selectionQuery.isError

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Compile & artifacts"
        description={
          <>
            Compile the aligned plan via{' '}
            <code>POST /api/v1/sdtms/{'{sdtm_id}'}/compile</code> and build extra
            metadata/report artifacts via{' '}
            <code>POST /api/v1/sdtms/{'{sdtm_id}'}/artifacts</code>.
          </>
        }
      />

      {/* The pinned input fingerprint both POSTs carry. */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Pinned input fingerprint</CardTitle>
          <CardDescription>
            Read from the current input selection. Both compile and artifact
            builds pin this fingerprint; the server rejects the build if it no
            longer matches.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {selectionQuery.isLoading ? (
            <Skeleton className="h-6 w-full" />
          ) : fingerprintUnavailable || inputFingerprint === null ? (
            <p className="text-destructive text-sm">
              No input selection has been saved, so the input fingerprint is
              unavailable. Save an input selection before compiling.
            </p>
          ) : (
            <code className="text-sm break-all">{inputFingerprint}</code>
          )}
        </CardContent>
      </Card>

      {/* --- Compile --- */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Compile program</CardTitle>
          <CardDescription>
            Compile the aligned plan into a Python, R, or SAS program.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="flex flex-col gap-1">
            <Label htmlFor="compile-domain" className="text-sm font-medium">
              Domain
            </Label>
            {planHeads.length === 0 ? (
              <p className="text-destructive text-sm">
                This workbench has no per-domain derivation plans yet. Author and
                align a domain plan before compiling.
              </p>
            ) : (
              <Select
                value={activeDomain ?? undefined}
                onValueChange={setDomainCode}
              >
                <SelectTrigger
                  id="compile-domain"
                  size="sm"
                  className="w-48"
                  aria-label="Compile domain"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {planHeads.map((head) => (
                    <SelectItem key={head.id} value={head.domain}>
                      {head.domain}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </div>

          <fieldset className="flex flex-col gap-2">
            <legend className="mb-1 text-sm font-medium">Backend</legend>
            <div className="flex flex-wrap gap-4">
              {COMPILE_BACKENDS.map((entry) => {
                const id = `compile-backend-${entry.value}`
                return (
                  <Label key={entry.value} htmlFor={id} className="gap-2">
                    <input
                      id={id}
                      type="radio"
                      name="compile-backend"
                      className="size-4"
                      value={entry.value}
                      checked={backend === entry.value}
                      onChange={() => setBackend(entry.value)}
                    />
                    <span>{entry.label}</span>
                    <code className="text-muted-foreground text-xs">
                      {entry.value}
                    </code>
                  </Label>
                )
              })}
            </div>
          </fieldset>

          {/* 15.4: the selected backend cannot implement the declared semantics. */}
          {isCapabilityMissing && (
            <CompileNotice
              title="This backend cannot compile the plan"
              detail={
                compileProblem?.detail ??
                'The selected backend cannot implement the declared semantics of the plan. Choose a different backend.'
              }
            />
          )}

          <div>
            <Button type="button" onClick={handleCompile} disabled={!canCompile}>
              {compile.isPending && (
                <Loader2 className="animate-spin" aria-hidden />
              )}
              Compile
            </Button>
          </div>
        </CardContent>
      </Card>

      {compileBuildId ? (
        <OperationRunner<ArtifactBuildResponse>
          operationLabel="compile"
          operationId={compileBuildId}
          useGetOperation={useArtifactBuildOperation}
          intervalMs={OPERATION_POLL_PRESETS.fast.intervalMs}
          timeoutMs={OPERATION_POLL_PRESETS.fast.timeoutMs}
          renderResult={(build) => (
            <CompletedBuildResult
              build={build}
              sdtmId={sdtmId}
              studyId={studyId}
            />
          )}
        />
      ) : (
        <EmptyState
          title="No compile started"
          description="Select a backend and compile to see the generated program artifacts here."
        />
      )}

      {/* --- Extra metadata/report artifacts --- */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            Metadata & report artifacts
          </CardTitle>
          <CardDescription>
            Build additional SDTM metadata or report artifact types alongside
            the compiled program.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <fieldset className="flex flex-col gap-2">
            <legend className="sr-only">SDTM artifact types</legend>
            {SDTM_ARTIFACT_TYPES.map((type) => {
              const id = `sdtm-artifact-${type.value}`
              return (
                <Label key={type.value} htmlFor={id} className="gap-2">
                  <input
                    id={id}
                    type="checkbox"
                    className="size-4"
                    checked={selectedTypes.has(type.value)}
                    onChange={() => toggleType(type.value)}
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
              onClick={handleBuildArtifacts}
              disabled={!canBuildArtifacts}
              title={
                noneSelected
                  ? 'Select at least one artifact type to build'
                  : undefined
              }
            >
              {createArtifacts.isPending && (
                <Loader2 className="animate-spin" aria-hidden />
              )}
              Build artifacts
            </Button>
          </div>
        </CardContent>
      </Card>

      {artifactBuildId ? (
        <OperationRunner<ArtifactBuildResponse>
          operationLabel="artifact build"
          operationId={artifactBuildId}
          useGetOperation={useArtifactBuildOperation}
          intervalMs={OPERATION_POLL_PRESETS.fast.intervalMs}
          timeoutMs={OPERATION_POLL_PRESETS.fast.timeoutMs}
          renderResult={(build) => (
            <CompletedBuildResult
              build={build}
              sdtmId={sdtmId}
              studyId={studyId}
            />
          )}
        />
      ) : null}
    </div>
  )
}

export default CompilePanel
