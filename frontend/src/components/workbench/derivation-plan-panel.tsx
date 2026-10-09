import * as React from 'react'
import type { AxiosError } from 'axios'
import { useQueryClient } from '@tanstack/react-query'
import { Save } from 'lucide-react'
import { toast } from 'sonner'

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState, ErrorState } from '@/components/data/states'
import {
  AlignmentBanner,
  isMisaligned,
  type AlignmentState,
} from '@/components/workbench/alignment-banner'
import { DerivationPlanGraph } from '@/components/workbench/plan-graph/derivation-plan-graph'
import { DerivationPreviewLineagePanel } from '@/components/workbench/derivation-preview-lineage-panel'
import {
  graphToPlan,
  planToGraph,
  type PlanGraphEdge,
  type PlanGraphNode,
} from '@/components/workbench/plan-graph-adapters'
import { useWorkbench } from '@/components/workbench/workbench-context'
import { parseProblem, stalenessAlert, type ProblemDetail } from '@/lib/problems'
import { ifMatchRequest } from '@/lib/requests'
import { invalidateSdtmSubResource } from '@/lib/invalidate'
import {
  getGetPlanQueryKey,
  useGetInputSelection,
  useGetPlan,
  useGetSpecification,
  usePutPlan,
} from '@/api/generated/sdtm/sdtm'
import type {
  AppSdtmRoutesPlanResponse as PlanResponse,
  SdtmDerivationPlan,
} from '@/api/generated/model'

/**
 * SDTM Derivation Plan tab body (Requirements 12.1-12.4, task 12.3).
 *
 * This panel owns the persistence, alignment-gating, and conflict handling that
 * {@link DerivationPlanGraph} (the pure controlled editor from task 12.2)
 * deliberately leaves out:
 *
 * The plan is per-domain: the panel is scoped to a single `domainCode` and
 * drives the `GET|PUT /sdtms/{sdtm_id}/domains/{domain_code}/derivation-plan`
 * routes. Each per-domain plan carries its own revision, which is the ETag.
 *
 * - Load the current plan via `GET .../domains/{domain_code}/derivation-plan`,
 *   deserialize its typed `nodes`/`edges` with {@link planToGraph}, and render
 *   the editor as a controlled surface driven by local `nodes`/`edges` state
 *   (12.1).
 * - Show the plan `revision`, the pinned `specification_revision` /
 *   `input_selection_revision`, and the server Alignment_State (`state`).
 * - Save serializes the on-canvas graph with {@link graphToPlan} through
 *   `PUT .../domains/{domain_code}/derivation-plan`, carrying `If-Match` for the
 *   loaded *per-domain plan* revision (the plan's own concurrency token) and the
 *   pinned specification / input-selection revisions the plan is authored
 *   against (12.1). A brand-new plan has no revision yet, so its first save
 *   falls back to the aggregate `If-Match`.
 * - A `409 stale_input_fingerprint` identifies which pinned input drifted
 *   (Specification vs Input Selection) by comparing the plan's pinned revisions
 *   against the freshly fetched current ones, and keeps the user's unsaved
 *   on-canvas graph edits (12.3).
 * - A `misaligned` Alignment_State renders the graph read-only (no palette,
 *   edge creation, reposition-to-save, or inspector writes), shows the
 *   {@link AlignmentBanner}, and disables validate/preview/compile/execute
 *   (12.2, 12.4).
 * - A `412` surfaces a concurrency notice with a reload action that re-fetches
 *   the current plan revision before a retry.
 *
 * New-plan mode: a `404 sdtm_derivation_plan_required` means no plan is
 * authored yet. When a current Specification and a current Input Selection are
 * BOTH available, the panel renders the full interactive editor seeded with an
 * empty canvas so the user can author the very first plan — resolving the
 * chicken-and-egg where the editor used to appear only once a plan existed. The
 * first save pins the new plan against the *current* Specification / Input
 * Selection revisions (there is no loaded plan to read pinned revisions from)
 * and carries the same aggregate `If-Match` as a normal save; on success the
 * `onSuccess` invalidation refetches the plan and the panel transitions to the
 * loaded-plan path. The backend rejects a zero-node save (the plan contract
 * requires at least one node) with a `422`, which surfaces as a toast so the
 * user adds a node and retries. When the prerequisites are not yet current
 * (still loading or genuinely absent) the guidance empty state is kept instead.
 */
export function DerivationPlanPanel({
  sdtmId,
  domainCode,
}: {
  sdtmId: string
  domainCode: string
}) {
  const qc = useQueryClient()
  // `ifMatch()` carries `If-Match` for the current aggregate revision. It is
  // only used for a brand-new plan's first save (no per-domain plan revision
  // exists yet); a loaded plan uses its own revision as the ETag.
  const { ifMatch } = useWorkbench()

  const planKey = React.useMemo(
    () => getGetPlanQueryKey(sdtmId, domainCode),
    [sdtmId, domainCode],
  )

  // The current per-domain plan. A `404 sdtm_derivation_plan_required` means
  // "no plan authored yet" and is rendered as an unsaved empty editor rather
  // than an error.
  const query = useGetPlan(sdtmId, domainCode)
  const plan = query.data

  // The current Specification / Input Selection revisions. These serve two
  // purposes: (1) attributing a 409 stale_input_fingerprint to a specific
  // pinned input (the backend returns a single combined `sdtm_plan_alignment`
  // field_path, so the panel compares the plan's pinned revisions against these
  // current values to name which input drifted, 12.3); and (2) in new-plan mode
  // (no saved plan) they supply the revisions the first plan is pinned against,
  // since there is no loaded plan to read pinned revisions from.
  const specQuery = useGetSpecification(sdtmId)
  const inputQuery = useGetInputSelection(sdtmId)

  // The controlled graph the editor renders. Seeded from the loaded plan and
  // re-seeded whenever the server plan revision changes (after a save or a 412
  // reload) so the canvas reflects the latest persisted graph before further
  // edits. A 409 deliberately does NOT re-seed, preserving unsaved edits.
  const [nodes, setNodes] = React.useState<PlanGraphNode[]>([])
  const [edges, setEdges] = React.useState<PlanGraphEdge[]>([])
  const seededRevision = React.useRef<number | null>(null)

  React.useEffect(() => {
    if (!plan) return
    if (seededRevision.current === plan.revision) return
    seededRevision.current = plan.revision
    const graph = planToGraph(planBodyFromResponse(plan))
    setNodes(graph.nodes)
    setEdges(graph.edges)
  }, [plan])

  const [concurrency, setConcurrency] = React.useState<string | null>(null)
  const [staleInput, setStaleInput] = React.useState<string | null>(null)
  // Per-domain plan 409s surfaced beside the existing stale-input notice: an
  // upstream `sdtm_read` sibling that is misaligned/absent, or an incomplete
  // all-domain output coverage.
  const [upstreamMisaligned, setUpstreamMisaligned] = React.useState<
    string | null
  >(null)
  const [coverageIncomplete, setCoverageIncomplete] = React.useState<
    string | null
  >(null)

  const put = usePutPlan({
    mutation: {
      onSuccess: () =>
        invalidateSdtmSubResource(
          qc,
          'derivation-plan',
          sdtmId,
          undefined,
          domainCode,
        ),
    },
    // The per-domain plan revision is the ETag. When a plan is loaded, send
    // `If-Match` for its own revision; a brand-new plan (no revision yet) falls
    // back to the aggregate `If-Match` for its first save.
    request: plan ? ifMatchRequest(plan.revision) : ifMatch(),
  })

  const status = query.error?.response?.status
  const notFoundCode =
    status === 404 ? parseProblem(query.error as AxiosError).code : undefined
  const planRequired =
    status === 404 && notFoundCode === 'sdtm_derivation_plan_required'

  // New-plan prerequisites. A first plan can only be pinned once a current
  // Specification (GET 200) and a current Input Selection (GET 200 with
  // `state === 'current'`) both exist — exactly the inputs the backend
  // validates PUT against. These revisions are the ones the first save pins.
  const currentSpecRevision = specQuery.data?.revision
  const currentInputRevision =
    inputQuery.data?.state === 'current' ? inputQuery.data.revision : undefined
  const prerequisitesReady =
    currentSpecRevision !== undefined && currentInputRevision !== undefined

  // Enter interactive new-plan mode only when there is no saved plan AND both
  // prerequisites are current; otherwise the guidance empty state is kept.
  const newPlanMode = planRequired && prerequisitesReady

  // Alignment is server-authoritative. `state` is the plan Alignment_State; a
  // misaligned plan locks the editor and disables the downstream operations. A
  // brand-new plan being authored is editable (treated as aligned).
  const alignmentState = plan?.state as AlignmentState | undefined
  const misaligned = isMisaligned(alignmentState)

  // The specification / input-selection revisions the plan is (or will be)
  // pinned against: a loaded plan carries its own pinned revisions, while a
  // new plan pins against the current ones.
  const pinnedSpecRevision = plan?.specification_revision ?? currentSpecRevision
  const pinnedInputRevision =
    plan?.input_selection_revision ?? currentInputRevision

  // ---- save ---------------------------------------------------------------

  async function handleSave() {
    // A save needs pinned revisions from either a loaded plan or the current
    // prerequisites (new-plan mode). Without either there is nothing to pin.
    if (pinnedSpecRevision === undefined || pinnedInputRevision === undefined) {
      return
    }
    setConcurrency(null)
    setStaleInput(null)
    setUpstreamMisaligned(null)
    setCoverageIncomplete(null)
    // Serialize the on-canvas graph to the typed plan body, naming the domain
    // this per-domain plan produces and pinning the exact specification /
    // input-selection revisions the plan is authored against.
    const body: SdtmDerivationPlan = graphToPlan(nodes, edges, {
      domain: domainCode,
      specificationRevision: pinnedSpecRevision,
      inputSelectionRevision: pinnedInputRevision,
      schemaVersion: '1.1.0',
    })
    try {
      await put.mutateAsync({ sdtmId, domainCode, data: body })
      toast.success('Derivation plan saved.')
    } catch (error) {
      const err = error as AxiosError
      const problem = parseProblem(err)
      const code = problem.code
      if (err.response?.status === 409 && code === 'stale_input_fingerprint') {
        // A pinned input drifted. The on-canvas edits are retained; identify
        // which input (Specification vs Input Selection) changed by comparing
        // the pinned revisions against the current ones (12.3).
        setStaleInput(
          describeStaleInput(
            { specificationRevision: pinnedSpecRevision, inputSelectionRevision: pinnedInputRevision },
            specQuery.data,
            inputQuery.data,
          ),
        )
        return
      }
      if (
        err.response?.status === 409 &&
        code === 'sdtm_plan_upstream_misaligned'
      ) {
        // An `sdtm_read` sibling this plan reads is no longer aligned (or has
        // no plan at all — `upstream_state: "absent"`). Keep the on-canvas
        // edits and name the upstream domain(s) and their state.
        setUpstreamMisaligned(describeUpstreamMisaligned(problem))
        return
      }
      if (
        err.response?.status === 409 &&
        code === 'sdtm_output_coverage_incomplete'
      ) {
        // The union of per-domain plans does not yet cover every derived domain
        // in the Specification. Name the missing domains from the problem body.
        setCoverageIncomplete(describeCoverageIncomplete(problem))
        return
      }
      if (err.response?.status === 412) {
        setConcurrency(
          stalenessAlert(err) ??
            'This workbench changed since you opened it. Reload and try again.',
        )
        return
      }
      toast.error(
        parseProblem(err).detail ??
          err.message ??
          'Could not save the derivation plan.',
      )
    }
  }

  async function reloadCurrentRevision() {
    setConcurrency(null)
    setStaleInput(null)
    setUpstreamMisaligned(null)
    setCoverageIncomplete(null)
    // Force the editor to re-seed from the freshly fetched plan revision.
    seededRevision.current = null
    await qc.invalidateQueries({ queryKey: planKey })
  }

  // ---- render -------------------------------------------------------------

  if (query.isLoading) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-[32rem] w-full" />
      </div>
    )
  }

  // 404 sdtm_derivation_plan_required -> no plan authored yet. A first plan can
  // only be pinned once a current Specification and Input Selection both exist.
  // When they do (`newPlanMode`), fall through to the interactive editor seeded
  // with an empty canvas so the user can author the first plan; otherwise show
  // the guidance empty state directing the user to author those prerequisites.
  if (planRequired && !newPlanMode) {
    return (
      <div className="flex flex-col gap-4">
        <EmptyState
          title="No derivation plan yet"
          description="This SDTM workbench has no saved derivation plan. Save a current Specification and Input Selection, then author the plan here."
        />
        <ConcurrencyNotice message={concurrency} onReload={reloadCurrentRevision} />
      </div>
    )
  }

  // Any load error other than the "no plan yet" case is a genuine error.
  if (query.isError && !newPlanMode) {
    return <ErrorState error={query.error} resourceLabel="SDTM derivation plan" />
  }

  // A loaded response but no plan body (and not new-plan mode) is unexpected.
  if (!plan && !newPlanMode) {
    return (
      <EmptyState
        title="No derivation plan"
        description="The derivation plan is unavailable."
      />
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            Derivation plan
            <AlignmentPill state={alignmentState} />
          </CardTitle>
          <CardDescription>
            {plan ? (
              <>
                Revision {plan.revision} · pinned Specification revision{' '}
                {plan.specification_revision} · pinned Input Selection revision{' '}
                {plan.input_selection_revision} · schema version{' '}
                {plan.schema_version}
              </>
            ) : (
              <>
                New {domainCode} plan (unsaved) · pins Specification revision{' '}
                {pinnedSpecRevision} · Input Selection revision{' '}
                {pinnedInputRevision} · schema version 1.1.0. Add at least one
                node, then save to create revision 1.
              </>
            )}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            onClick={handleSave}
            disabled={put.isPending || misaligned}
          >
            <Save /> Save plan
          </Button>
          {misaligned && (
            <span className="text-muted-foreground text-sm">
              The plan is read-only while misaligned.
            </span>
          )}
        </CardContent>
      </Card>

      {/* Persistent misalignment notice; disables validate/preview/compile/execute
          (those controls live in the preview/validation/compile/execution tabs and
          gate on the same Alignment_State). */}
      <AlignmentBanner state={alignmentState} />

      <StaleInputNotice message={staleInput} onReload={reloadCurrentRevision} />
      <UpstreamMisalignedNotice
        message={upstreamMisaligned}
        onReload={reloadCurrentRevision}
      />
      <CoverageIncompleteNotice message={coverageIncomplete} />
      <ConcurrencyNotice message={concurrency} onReload={reloadCurrentRevision} />

      <DerivationPlanGraph
        nodes={nodes}
        edges={edges}
        onNodesChange={setNodes}
        onEdgesChange={setEdges}
        readOnly={misaligned}
      />

      {/* Derivation preview, inline validation, and read-only lineage operate on
          a saved plan, so they appear only once a plan exists; a misaligned plan
          disables preview/validate and hides lineage, matching the server-side
          alignment gate (Requirements 12.5-12.7, 13). */}
      {plan && (
        <DerivationPreviewLineagePanel
          sdtmId={sdtmId}
          domainCode={domainCode}
          disabled={misaligned}
        />
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

/** Compact Alignment_State pill in the header. */
function AlignmentPill({ state }: { state: AlignmentState | undefined }) {
  if (!state) return null
  const misaligned = isMisaligned(state)
  return (
    <Badge variant={misaligned ? 'destructive' : 'secondary'}>
      {misaligned ? 'Misaligned' : 'Aligned'}
    </Badge>
  )
}

interface NoticeProps {
  message: string | null
  onReload: () => void
}

/**
 * 409 stale_input_fingerprint notice. Names the drifted input (Specification vs
 * Input Selection) and offers a reload; the on-canvas graph edits are retained
 * so the user does not lose work while re-aligning (12.3).
 */
function StaleInputNotice({ message, onReload }: NoticeProps) {
  if (!message) return null
  return (
    <div
      role="alert"
      className="border-destructive/50 text-destructive flex flex-col gap-2 rounded-md border px-4 py-3 text-sm"
    >
      <span className="font-medium">Pinned input is stale</span>
      <span className="text-destructive/90">{message}</span>
      <span className="text-destructive/80 text-xs">
        Your on-canvas edits are kept. Reload the current plan revision to
        re-pin against current inputs, then re-apply your changes.
      </span>
      <button
        type="button"
        onClick={onReload}
        className="text-destructive w-fit text-sm font-medium underline underline-offset-2"
      >
        Reload current plan revision
      </button>
    </div>
  )
}

/**
 * 409 sdtm_plan_upstream_misaligned notice. An `sdtm_read` sibling this plan
 * reads is misaligned or has no plan yet (`upstream_state: "absent"`). The
 * on-canvas edits are retained; the user must align (or author) the upstream
 * domain plan first, then reload and re-save.
 */
function UpstreamMisalignedNotice({ message, onReload }: NoticeProps) {
  if (!message) return null
  return (
    <div
      role="alert"
      className="border-destructive/50 text-destructive flex flex-col gap-2 rounded-md border px-4 py-3 text-sm"
    >
      <span className="font-medium">Upstream plan is not aligned</span>
      <span className="text-destructive/90">{message}</span>
      <span className="text-destructive/80 text-xs">
        Your on-canvas edits are kept. Align (or author) the upstream domain
        plan, then reload the current plan revision and save again.
      </span>
      <button
        type="button"
        onClick={onReload}
        className="text-destructive w-fit text-sm font-medium underline underline-offset-2"
      >
        Reload current plan revision
      </button>
    </div>
  )
}

/**
 * 409 sdtm_output_coverage_incomplete notice. The union of per-domain plans
 * does not yet cover every derived domain in the Specification; name the
 * domains still missing a plan.
 */
function CoverageIncompleteNotice({ message }: { message: string | null }) {
  if (!message) return null
  return (
    <div
      role="alert"
      className="border-destructive/50 text-destructive flex flex-col gap-2 rounded-md border px-4 py-3 text-sm"
    >
      <span className="font-medium">Output coverage is incomplete</span>
      <span className="text-destructive/90">{message}</span>
      <span className="text-destructive/80 text-xs">
        Author and align a plan for each listed domain before an all-domain
        deliverable can be built.
      </span>
    </div>
  )
}

/** Persistent 412 concurrency notice with a reload action. */
function ConcurrencyNotice({ message, onReload }: NoticeProps) {
  if (!message) return null
  return (
    <div
      role="alert"
      className="border-destructive/50 text-destructive flex flex-col gap-2 rounded-md border px-4 py-3 text-sm"
    >
      <span className="font-medium">Workbench changed</span>
      <span className="text-destructive/90">{message}</span>
      <button
        type="button"
        onClick={onReload}
        className="text-destructive w-fit text-sm font-medium underline underline-offset-2"
      >
        Reload current plan revision
      </button>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Read the typed plan body (nodes/edges + pinned revisions) out of the opaque
 * `PlanResponse.payload`. The backend stores the exact serialized
 * {@link SdtmDerivationPlan} command as the payload, so the typed `nodes`/
 * `edges` round-trip through it; the pinned revisions are taken from the
 * typed response columns, which are authoritative.
 */
function planBodyFromResponse(plan: PlanResponse): SdtmDerivationPlan {
  const payload = plan.payload as Record<string, unknown>
  const nodes = Array.isArray(payload.nodes)
    ? (payload.nodes as SdtmDerivationPlan['nodes'])
    : []
  const edges = Array.isArray(payload.edges)
    ? (payload.edges as SdtmDerivationPlan['edges'])
    : []
  return {
    schema_version: '1.1.0',
    domain: plan.domain,
    specification_revision: plan.specification_revision,
    input_selection_revision: plan.input_selection_revision,
    nodes,
    edges,
  }
}

/**
 * Describe a 409 sdtm_plan_upstream_misaligned problem by naming the upstream
 * `sdtm_read` domain(s) and their state. The backend fills `issues[]` with
 * `{ upstream_code, upstream_state }` entries; `upstream_state` is `"absent"`
 * when the referenced sibling has no plan yet, otherwise the sibling's state.
 * Falls back to the problem `detail` when the issue shape is unavailable.
 */
function describeUpstreamMisaligned(problem: ProblemDetail): string {
  const parts = (problem.issues ?? [])
    .map((issue) => {
      const code = issue.upstream_code
      const state = issue.upstream_state
      if (typeof code !== 'string') return null
      if (state === 'absent') {
        return `${code} (no plan authored yet)`
      }
      return typeof state === 'string' ? `${code} (${state})` : code
    })
    .filter((part): part is string => part !== null)

  if (parts.length > 0) {
    return `This plan reads an SDTM domain whose plan is not aligned: ${parts.join(', ')}.`
  }
  return (
    problem.detail ??
    'This plan reads an SDTM domain whose plan is not aligned at the pinned revision.'
  )
}

/**
 * Describe a 409 sdtm_output_coverage_incomplete problem by listing the derived
 * domains still missing a plan. The backend fills `issues[]` with a single
 * `{ missing_domains: [...] }` entry; falls back to the problem `detail`.
 */
function describeCoverageIncomplete(problem: ProblemDetail): string {
  const missing = (problem.issues ?? [])
    .flatMap((issue) =>
      Array.isArray(issue.missing_domains) ? issue.missing_domains : [],
    )
    .filter((domain): domain is string => typeof domain === 'string')

  if (missing.length > 0) {
    return `These derived domains have no aligned plan yet: ${missing.join(', ')}.`
  }
  return (
    problem.detail ??
    'Not every derived domain in the Specification has an aligned plan yet.'
  )
}

/** The specification / input-selection revisions a plan is pinned against. */
interface PinnedRevisions {
  specificationRevision: number
  inputSelectionRevision: number
}

/**
 * Attribute a 409 stale_input_fingerprint to a specific pinned input by
 * comparing the pinned revisions against the freshly fetched current
 * Specification / Input Selection revisions. The backend returns a single
 * combined signal, so this client-side comparison names which input the user
 * must re-align against.
 */
function describeStaleInput(
  pinned: PinnedRevisions,
  spec: { revision: number } | undefined,
  input: { revision: number } | undefined,
): string {
  const specDrifted =
    spec !== undefined && spec.revision !== pinned.specificationRevision
  const inputDrifted =
    input !== undefined && input.revision !== pinned.inputSelectionRevision

  if (specDrifted && inputDrifted) {
    return `Both the Specification (pinned revision ${pinned.specificationRevision}, now ${spec!.revision}) and the Input Selection (pinned revision ${pinned.inputSelectionRevision}, now ${input!.revision}) have changed since the plan was authored.`
  }
  if (specDrifted) {
    return `The Specification changed since the plan was authored (pinned revision ${pinned.specificationRevision}, now ${spec!.revision}).`
  }
  if (inputDrifted) {
    return `The Input Selection changed since the plan was authored (pinned revision ${pinned.inputSelectionRevision}, now ${input!.revision}).`
  }
  // Current revisions not loaded or unchanged: fall back to a combined message.
  return 'A pinned input (Specification or Input Selection) is no longer current. Reload to re-pin against current inputs.'
}

export default DerivationPlanPanel
